//! W3a exit-criterion tests: MCP protocol (handshake, tools/list, calls,
//! error shapes), the SIM labeling, honesty metadata, metering (ticket #356).

use ot_mcp::{serve_lines, ServerState};
use serde_json::{json, Value};

fn call_tool(name: &str, args: Value) -> (ServerState, Value) {
    // the tool surfaces are tested here; the auth gate itself is covered
    // in auth.rs — this file skips it (local-dev mode)
    let mut state = ServerState {
        skip_auth: true,
        ..Default::default()
    };
    let msg = json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": args}
    });
    let resp = ot_mcp::handle_message(&msg, &mut state).expect("response");
    (state, resp)
}

fn result_text(resp: &Value) -> String {
    resp.pointer("/result/content/0/text")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string()
}

// ── protocol ───────────────────────────────────────────────────────────────

#[test]
fn initialize_handshake_echoes_protocol_version() {
    let mut state = ServerState {
        skip_auth: true,
        ..Default::default()
    };
    let msg = json!({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-03-26", "capabilities": {}}
    });
    let resp = ot_mcp::handle_message(&msg, &mut state).unwrap();
    assert_eq!(resp.pointer("/result/protocolVersion").unwrap(), "2025-03-26");
    assert_eq!(resp.pointer("/result/serverInfo/name").unwrap(), "opentrader-v2");
    assert!(resp.pointer("/result/capabilities/tools").is_some());
}

#[test]
fn notifications_produce_no_response() {
    let mut state = ServerState::default();
    let msg = json!({"jsonrpc": "2.0", "method": "notifications/initialized"});
    assert!(ot_mcp::handle_message(&msg, &mut state).is_none());
}

#[test]
fn unknown_method_is_jsonrpc_error() {
    let mut state = ServerState::default();
    let msg = json!({"jsonrpc": "2.0", "id": 7, "method": "resources/list"});
    let resp = ot_mcp::handle_message(&msg, &mut state).unwrap();
    assert_eq!(resp.pointer("/error/code").unwrap(), -32601);
}

#[test]
fn unparseable_line_yields_parse_error() {
    let mut state = ServerState::default();
    let mut responses = Vec::new();
    serve_lines(["not json".to_string()].into_iter(), &mut |r| responses.push(r.clone()), &mut state);
    assert_eq!(responses[0].pointer("/error/code").unwrap(), -32700);
}

#[test]
fn stdio_loop_serves_multiple_messages_in_order() {
    let mut state = ServerState {
        skip_auth: true,
        ..Default::default()
    };
    let lines = vec![
        json!({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}).to_string(),
        json!({"jsonrpc": "2.0", "method": "notifications/initialized"}).to_string(),
        json!({"jsonrpc": "2.0", "id": 2, "method": "ping"}).to_string(),
        String::new(), // blank lines skipped
    ];
    let mut responses = Vec::new();
    serve_lines(lines.into_iter(), &mut |r| responses.push(r.clone()), &mut state);
    assert_eq!(responses.len(), 2, "notification silent, blank skipped");
    assert_eq!(responses[0].pointer("/id").unwrap(), 1);
    assert_eq!(responses[1].pointer("/id").unwrap(), 2);
}

#[test]
fn tools_list_carries_the_four_surfaces_with_metering_classes() {
    let mut state = ServerState::default();
    let msg = json!({"jsonrpc": "2.0", "id": 1, "method": "tools/list"});
    let resp = ot_mcp::handle_message(&msg, &mut state).unwrap();
    let tools = resp.pointer("/result/tools").unwrap().as_array().unwrap();
    let names: Vec<&str> = tools
        .iter()
        .filter_map(|t| t.get("name").and_then(|n| n.as_str()))
        .collect();
    assert!(names.contains(&"script.validate"));
    assert!(names.contains(&"script.eval"));
    assert!(names.contains(&"script.backtest"));
    assert!(names.contains(&"scan.run"));
    // metering classes declared in the descriptions (spec §9)
    for t in tools {
        let desc = t.get("description").and_then(|d| d.as_str()).unwrap_or("");
        assert!(desc.contains("Metering:"), "tool {:?} lacks a metering class", t["name"]);
    }
}

// ── script.validate ────────────────────────────────────────────────────────

#[test]
fn validate_good_source_reports_schema_and_warmup() {
    let (state, resp) = call_tool(
        "script.validate",
        json!({"source": "input length = 14;\ndef fast = Average(close, length);\nplot sig = fast;"}),
    );
    assert!(!resp.pointer("/result/isError").unwrap().as_bool().unwrap());
    let v: Value = serde_json::from_str(&result_text(&resp)).unwrap();
    assert_eq!(v["ok"], true);
    assert_eq!(v["inputs"], json!(["length"]));
    assert_eq!(v["warmup_unbounded"], false);
    let fast = v["bindings"]
        .as_array()
        .unwrap()
        .iter()
        .find(|b| b["name"] == "fast")
        .unwrap();
    assert_eq!(fast["lookback"], 13);
    assert_eq!(state.meter.validate, 1, "metered");
}

#[test]
fn validate_bad_source_returns_structured_error_not_rpc_error() {
    let (state, resp) = call_tool(
        "script.validate",
        json!({"source": "def x = close[-1]; plot p = x;"}),
    );
    assert!(!resp.pointer("/result/isError").unwrap().as_bool().unwrap());
    let v: Value = serde_json::from_str(&result_text(&resp)).unwrap();
    assert_eq!(v["ok"], false);
    assert!(v["error"].as_str().unwrap().contains("past-only"));
    assert_eq!(state.meter.validate, 1);
}

#[test]
fn validate_history_dependent_is_flagged() {
    let (_, resp) = call_tool(
        "script.validate",
        json!({"source": "series cum = volume then cum[1] + volume; plot p = cum;"}),
    );
    let v: Value = serde_json::from_str(&result_text(&resp)).unwrap();
    assert_eq!(v["warmup_unbounded"], true);
}

// ── script.eval ────────────────────────────────────────────────────────────

#[test]
fn eval_over_sim_labels_and_downsamples() {
    let (state, resp) = call_tool(
        "script.eval",
        json!({"source": "def e = EMA(close, 5); plot p = e;", "symbol": "SIM_EURUSD", "bars": 120, "max_plot_points": 20}),
    );
    assert!(!resp.pointer("/result/isError").unwrap().as_bool().unwrap(), "{}", result_text(&resp));
    let v: Value = serde_json::from_str(&result_text(&resp)).unwrap();
    assert_eq!(v["data_plane"], "SIM", "the result must be labeled SIM");
    assert_eq!(v["bars"], 120);
    let plot = &v["plots"][0];
    assert_eq!(plot["name"], "p");
    let values = plot["values"].as_array().unwrap();
    assert!(values.len() <= 20, "downsampled to max_plot_points: {}", values.len());
    assert_eq!(plot["stride"], 6, "120/20 → stride 6");
    // EMA(5) warm-up: complete (4×5=20 ≤ 120)
    assert_eq!(v["warmup_complete"], true);
    assert_eq!(state.meter.eval, 1, "metered");
}

#[test]
fn eval_series_flags_incomplete_warmup() {
    let (_, resp) = call_tool(
        "script.eval",
        json!({"source": "series cum = volume then cum[1] + volume; plot p = cum;", "symbol": "SIM_EURUSD"}),
    );
    let v: Value = serde_json::from_str(&result_text(&resp)).unwrap();
    assert_eq!(v["warmup_complete"], false, "honesty metadata: series is history-dependent");
}

#[test]
fn eval_requires_symbol() {
    let (_, resp) = call_tool("script.eval", json!({"source": "plot p = close;"}));
    assert!(resp.pointer("/result/isError").unwrap().as_bool().unwrap());
    assert!(result_text(&resp).contains("symbol"));
}

// ── script.backtest ────────────────────────────────────────────────────────

#[test]
fn backtest_returns_a_report_with_honesty_metadata() {
    let (state, resp) = call_tool(
        "script.backtest",
        json!({
            "source": "strategy T {\n  on close crosses above Average(close, 20) -> Entry(side = LONG, size = 10);\n  on MaxHold(10) -> Flatten;\n}",
            "symbol": "SIM_EURUSD",
            "bars": 250
        }),
    );
    assert!(!resp.pointer("/result/isError").unwrap().as_bool().unwrap(), "{}", result_text(&resp));
    let v: Value = serde_json::from_str(&result_text(&resp)).unwrap();
    assert_eq!(v["data_plane"], "SIM");
    let report = &v["report"];
    assert!(report["metrics"]["net_return"].is_number(), "metrics present: {report}");
    assert!(report["trades"].is_array(), "trade list present");
    assert_eq!(state.meter.backtest, 1, "metered per-run");
}

#[test]
fn backtest_rejects_study_without_strategy() {
    let (_, resp) = call_tool(
        "script.backtest",
        json!({"source": "def x = close; plot p = x;", "symbol": "SIM_EURUSD"}),
    );
    assert!(resp.pointer("/result/isError").unwrap().as_bool().unwrap());
    assert!(result_text(&resp).contains("exactly one strategy"));
}

// ── scan.run ───────────────────────────────────────────────────────────────

#[test]
fn scan_run_over_the_sim_universe() {
    let (state, resp) = call_tool(
        "scan.run",
        json!({
            "source": "def hot = close > Average(close, 20);",
            "filter": "hot",
            "limit": 10,
            "bars": 120
        }),
    );
    assert!(!resp.pointer("/result/isError").unwrap().as_bool().unwrap(), "{}", result_text(&resp));
    let v: Value = serde_json::from_str(&result_text(&resp)).unwrap();
    let scanned = v["scanned"].as_u64().unwrap();
    assert_eq!(scanned, 6, "the SIM universe is 6 symbols");
    // ranked by symbol when no sort
    let hits = v["hits"].as_array().unwrap();
    let syms: Vec<&str> = hits.iter().filter_map(|h| h["symbol"].as_str()).collect();
    let mut sorted = syms.clone();
    sorted.sort();
    assert_eq!(syms, sorted, "no sort → symbol asc");
    // metering: symbols×bars touched (the read meter's unit)
    assert_eq!(state.meter.scan_calls, 1);
    assert_eq!(state.meter.scan_symbol_bars, 6 * 120);
}

#[test]
fn scan_run_unknown_filter_is_a_tool_error() {
    let (_, resp) = call_tool(
        "scan.run",
        json!({"source": "def hot = close > 100;", "filter": "nope"}),
    );
    assert!(resp.pointer("/result/isError").unwrap().as_bool().unwrap());
    assert!(result_text(&resp).contains("not found"));
}

#[test]
fn unknown_tool_is_a_tool_error() {
    let (_, resp) = call_tool("nasdaq.hack_the_planet", json!({}));
    assert!(resp.pointer("/result/isError").unwrap().as_bool().unwrap());
    assert!(result_text(&resp).contains("unknown tool"));
}
