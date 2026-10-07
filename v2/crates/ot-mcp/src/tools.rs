//! The tool catalog + dispatch — four surfaces (spec §9, first slice),
//! each with its metering class declared.

use serde_json::{json, Value};

use crate::ServerState;

#[derive(Debug, Default, Clone)]
pub struct Meter {
    pub validate: u64,
    pub eval: u64,
    pub backtest: u64,
    pub scan_calls: u64,
    pub scan_symbol_bars: u64,
}

/// The catalog — name, metering class (spec §9), JSON schema.
pub fn catalog() -> Vec<Value> {
    vec![
        json!({
            "name": "script.validate",
            "description": "Compile-only: errors, input schema, per-binding lookbacks, warm-up class. Metering: FREE/CHEAP.",
            "inputSchema": {
                "type": "object",
                "properties": {"source": {"type": "string"}},
                "required": ["source"]
            }
        }),
        json!({
            "name": "script.eval",
            "description": "Evaluate a study over SIM bars (labeled SIM; hosted venue data lands with the W1 tails). Returns plots (downsampled), last scalars, warmup_complete. Metering: PER-CALL (read meter).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "symbol": {"type": "string"},
                    "bars": {"type": "integer", "default": 120},
                    "max_plot_points": {"type": "integer", "default": 200}
                },
                "required": ["source", "symbol"]
            }
        }),
        json!({
            "name": "script.backtest",
            "description": "Run a strategy block over SIM bars → the engine's trade report (REPORT ONLY — virtual orders; no live routing by construction, spec §7.3). Metering: PER-RUN compute-heavy (action meter).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "symbol": {"type": "string"},
                    "bars": {"type": "integer", "default": 250}
                },
                "required": ["source", "symbol"]
            }
        }),
        json!({
            "name": "scan.run",
            "description": "Run a scan over the SIM universe (filter bool binding, sort float binding, ranked). Metering: PER symbols×bars touched.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "filter": {"type": "string"},
                    "sort": {"type": "string"},
                    "limit": {"type": "integer", "default": 20},
                    "bars": {"type": "integer", "default": 120}
                },
                "required": ["source", "filter"]
            }
        }),
    ]
}

/// Dispatch a tools/call. Returns (is_error, content blocks).
pub fn call(name: &str, args: &Value, state: &mut ServerState) -> (bool, Vec<Value>) {
    let result: Result<Value, String> = match name {
        "script.validate" => { state.meter.validate += 1; validate(args) }
        "script.eval" => { state.meter.eval += 1; eval(args) }
        "script.backtest" => { state.meter.backtest += 1; backtest(args) }
        "scan.run" => {
            state.meter.scan_calls += 1;
            let out = scan(args);
            if let Ok(v) = &out {
                // symbols × bars touched (the read meter's unit)
                state.meter.scan_symbol_bars +=
                    v.pointer("/scanned").and_then(|s| s.as_u64()).unwrap_or(0)
                        * args.get("bars").and_then(|b| b.as_u64()).unwrap_or(120);
            }
            out
        }
        other => Err(format!("unknown tool: {other}")),
    };
    match result {
        Ok(v) => (
            false,
            vec![json!({
                "type": "text",
                "text": v.to_string(),
                "_meta": {"sim_data": true}
            })],
        ),
        Err(e) => (true, vec![json!({"type": "text", "text": e})]),
    }
}

fn arg_str(args: &Value, key: &str) -> Result<String, String> {
    args.get(key)
        .and_then(|v| v.as_str())
        .map(String::from)
        .ok_or_else(|| format!("missing required argument `{key}`"))
}

fn arg_usize(args: &Value, key: &str, default: usize) -> Result<usize, String> {
    match args.get(key) {
        None | Some(Value::Null) => Ok(default),
        Some(v) => v
            .as_u64()
            .map(|u| u as usize)
            .ok_or_else(|| format!("argument `{key}` must be a positive integer")),
    }
}

fn validate(args: &Value) -> Result<Value, String> {
    let source = arg_str(args, "source")?;
    match ot_script::compile(&source) {
        Ok(plan) => {
            let bindings: Vec<Value> = plan
                .bindings
                .iter()
                .map(|b| {
                    json!({
                        "name": b.name,
                        "type": format!("{:?}", b.ty),
                        "lookback": b.lookback,
                        "warmup": b.warmup,
                        "kind": format!("{:?}", b.kind),
                    })
                })
                .collect();
            Ok(json!({
                "ok": true,
                "inputs": plan.inputs.keys().collect::<Vec<_>>(),
                "bindings": bindings,
                "warmup_unbounded": plan.warmup_unbounded,
                "eval_order": plan.eval_order,
                "pane": plan.pane.map(|p| format!("{p:?}")),
            }))
        }
        Err(e) => Ok(json!({
            "ok": false,
            "error": e,
        })),
    }
}

fn eval(args: &Value) -> Result<Value, String> {
    let source = arg_str(args, "source")?;
    let symbol = arg_str(args, "symbol")?;
    let bars = arg_usize(args, "bars", 120)?;
    let max_points = arg_usize(args, "max_plot_points", 200)?;
    let sim = crate::sim::SimUniverse::new(0);
    let frame = sim.bars(&symbol, bars.min(5000)); // bars cap: bounded tool
    let plan = ot_script::compile(&source)?;
    let req = ot_script::ScriptRequest {
        source: source.clone(),
        symbol: symbol.clone(),
        timeframe: "1h".into(),
        inputs: Default::default(),
    };
    let out = ot_script::eval(&req, &plan, &ot_script::eval::Frame { bars: &frame })?;
    let plots: Vec<Value> = out
        .plots
        .iter()
        .map(|p| {
            // downsample: stride = ceil(len / max_points)
            let stride = (p.values.len() + max_points - 1) / max_points.max(1);
            let down: Vec<Value> = p
                .values
                .iter()
                .enumerate()
                .filter(|(i, _)| i % stride == 0)
                .map(|(_i, v)| {
                    if v.is_nan() {
                        json!(null) // NaN = don't paint, honestly null on the wire
                    } else {
                        json!(v)
                    }
                })
                .collect();
            json!({
                "name": p.name,
                "values": down,
                "stride": stride,
                "pane": p.pane.map(|x| format!("{x:?}")),
            })
        })
        .collect();
    Ok(json!({
        "data_plane": "SIM",
        "symbol": symbol,
        "bars": bars,
        "plots": plots,
        "last": out.last,
        "warmup_complete": matches!(out.warmup_complete, ot_script::eval::Warmup::Complete),
    }))
}

fn backtest(args: &Value) -> Result<Value, String> {
    let source = arg_str(args, "source")?;
    let symbol = arg_str(args, "symbol")?;
    let bars_n = arg_usize(args, "bars", 250)?;
    let sim = crate::sim::SimUniverse::new(0);
    let bars = sim.bars(&symbol, bars_n.min(5000));
    let plan = ot_script::compile(&source)?;
    let req = ot_script::ScriptRequest {
        source,
        symbol: symbol.clone(),
        timeframe: "1h".into(),
        inputs: Default::default(),
    };
    let report = ot_script::run_strategy(&req, &plan, &ot_script::eval::Frame { bars: &bars })?;
    let report = serde_json::to_value(&report).map_err(|e| e.to_string())?;
    Ok(json!({
        "data_plane": "SIM",
        "report": report,
    }))
}

fn scan(args: &Value) -> Result<Value, String> {
    let source = arg_str(args, "source")?;
    let filter = arg_str(args, "filter")?;
    let sort = args.get("sort").and_then(|v| v.as_str()).map(String::from);
    let limit = arg_usize(args, "limit", 20)?;
    let bars_n = arg_usize(args, "bars", 120)?;
    let sim = crate::sim::SimUniverse::new(0);
    let plan = ot_script::compile(&source)?;
    let universe: Vec<(String, Vec<ot_core::bar::Bar>)> = crate::sim::SimUniverse::SYMBOLS
        .iter()
        .map(|s| (s.to_string(), sim.bars(s, bars_n.min(5000))))
        .collect();
    let req = ot_script::ScanRequest {
        source,
        filter,
        sort,
        timeframe: "1h".into(),
        limit,
    };
    let result = ot_script::run_scan(&req, &plan, &universe, &ot_script::ScanConfig::default())?;
    serde_json::to_value(&result).map_err(|e| e.to_string())
}
