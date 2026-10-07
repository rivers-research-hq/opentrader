//! ot-mcp — the MCP server surfaces (spec §9, ticket #356).
//!
//! A2A story (locked #334): agents plug in as customers of the hosted API,
//! metered per tool-call with the two-meter structure (reads wholesale-
//! cheap, actions priced). This slice ships the protocol + the script
//! surfaces over a **SIM data plane** (labeled); the hosted venue-data
//! plane is the W1-tails work.
//!
//! Capability sandbox (spec §9, why the interpreter was chosen): a script
//! can only transform data the host feeds it — no I/O, no wall-clock, no
//! randomness, no network. Every result carries honesty metadata
//! (warmup_complete, bars) so an agent consumer cannot misread a truncated
//! evaluation (audit-gate rule 4 applied to the API).
//!
//! Strategy outputs from MCP are REPORTS only — the §7.3 boundary means no
//! tool bridges a script backtest into live order flow.

pub mod sim;
pub mod tools;

use serde_json::{json, Value};

/// One MCP request handled → one response (or None for notifications).
/// Pure and side-effect-free except the meter — testable without a socket.
pub fn handle_message(msg: &Value, state: &mut ServerState) -> Option<Value> {
    let method = msg.get("method").and_then(|m| m.as_str())?;
    if let Some(id) = msg.get("id") {
        Some(dispatch(method, msg, id.clone(), state))
    } else {
        // notifications: initialized / cancelled etc. — no response
        None
    }
}

fn dispatch(method: &str, msg: &Value, id: Value, state: &mut ServerState) -> Value {
    match method {
        "initialize" => {
            let client_version = msg
                .pointer("/params/protocolVersion")
                .and_then(|v| v.as_str())
                .unwrap_or("2024-11-05");
            json!({
                "jsonrpc": "2.0",
                "id": id,
                "result": {
                    "protocolVersion": client_version,
                    "capabilities": {
                        "tools": {"listChanged": false}
                    },
                    "serverInfo": {
                        "name": "opentrader-v2",
                        "version": env!("CARGO_PKG_VERSION"),
                    }
                }
            })
        }
        "tools/list" => json!({
            "jsonrpc": "2.0",
            "id": id,
            "result": {"tools": tools::catalog()}
        }),
        "tools/call" => {
            let name = msg
                .pointer("/params/name")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            let args = msg.pointer("/params/arguments").cloned().unwrap_or(json!({}));
            let (is_error, content) = tools::call(name, &args, state);
            json!({
                "jsonrpc": "2.0",
                "id": id,
                "result": {
                    "content": content,
                    "isError": is_error,
                }
            })
        }
        "ping" => json!({"jsonrpc": "2.0", "id": id, "result": {}}),
        other => json!({
            "jsonrpc": "2.0",
            "id": id,
            "error": {
                "code": -32601,
                "message": format!("method not found: {other}"),
            }
        })
    }
}

/// Server state: the meter (billing lands later; counting is the honest
/// first step — per tool, per spec §9's metering classes).
#[derive(Debug, Default, Clone)]
pub struct ServerState {
    pub meter: tools::Meter,
}

/// The stdio loop — newline-delimited JSON in, responses out. Testable via
/// [`serve_lines`].
pub fn serve_lines(
    input: impl Iterator<Item = String>,
    out: &mut dyn FnMut(&Value),
    state: &mut ServerState,
) {
    for line in input {
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }
        match serde_json::from_str::<Value>(trimmed) {
            Ok(msg) => {
                if let Some(resp) = handle_message(&msg, state) {
                    out(&resp);
                }
            }
            Err(e) => {
                // unparseable line → JSON-RPC parse error (id null)
                let resp = json!({
                    "jsonrpc": "2.0",
                    "id": null,
                    "error": {"code": -32700, "message": format!("parse error: {e}")}
                });
                out(&resp);
            }
        }
    }
}
