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

pub mod auth;
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
            let mut result = json!({
                "protocolVersion": client_version,
                "capabilities": {
                    "tools": {"listChanged": false}
                },
                "serverInfo": {
                    "name": "opentrader-v2",
                    "version": env!("CARGO_PKG_VERSION"),
                }
            });
            if !state.skip_auth {
                match presented_key(msg)
                    .ok_or_else(|| "no API key presented (params._ot_auth or OT_MCP_API_KEY)".to_string())
                    .and_then(|key| {
                        let ledger = auth::Ledger::load(&state.ledger_path)?;
                        ledger.verify(&key).ok_or_else(|| "invalid API key".to_string())
                    }) {
                    Ok(identity) => {
                        result["_ot"] = json!({
                            "authenticated": true,
                            "customer": identity.customer,
                            "plan": identity.plan,
                        });
                        state.identity = Some(identity);
                    }
                    Err(e) => {
                        return json!({
                            "jsonrpc": "2.0",
                            "id": id,
                            "error": {"code": -32001, "message": e}
                        });
                    }
                }
            } else {
                result["_ot"] = json!({"authenticated": false, "mode": "no-auth (local dev)"});
            }
            json!({
                "jsonrpc": "2.0",
                "id": id,
                "result": result
            })
        }
        "tools/list" => json!({
            "jsonrpc": "2.0",
            "id": id,
            "result": {"tools": tools::catalog()}
        }),
        "tools/call" => {
            if state.identity.is_none() && !state.skip_auth {
                return json!({
                    "jsonrpc": "2.0",
                    "id": id,
                    "error": {"code": -32001, "message": "not authenticated — initialize with a valid API key"}
                });
            }
            // plan limit: per-session tool-call cap (counters reset on
            // restart — documented in the ledger schema, not hidden)
            if let Some(identity) = &state.identity {
                if let Some(max) = identity.max_calls {
                    if state.session_calls >= max {
                        return json!({
                            "jsonrpc": "2.0",
                            "id": id,
                            "error": {"code": -32002, "message": format!(
                                "meter limit exceeded (plan `{}`: {max} calls/session) — counters reset on restart",
                                identity.plan
                            )}
                        });
                    }
                }
            }
            state.session_calls += 1;
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

/// Server state: auth identity + the meter (billing lands later; counting
/// is the honest first step — per tool, per spec §9's metering classes).
#[derive(Debug, Default, Clone)]
pub struct ServerState {
    pub meter: tools::Meter,
    /// set by a successful authenticated initialize (or --no-auth mode)
    pub identity: Option<auth::Identity>,
    /// total tool calls this session — enforced against identity.max_calls
    pub session_calls: u64,
    /// dev mode: local processes skip auth (explicit flag, not default)
    pub skip_auth: bool,
    /// ledger path (default ~/.ot-mcp/keys.json; overridable for tests)
    pub ledger_path: std::path::PathBuf,
}

/// Extract the presented key: initialize params._ot_auth, or the
/// OT_MCP_API_KEY env var (the process was launched with it).
fn presented_key(msg: &Value) -> Option<String> {
    if let Some(k) = msg.pointer("/params/_ot_auth").and_then(|v| v.as_str()) {
        return Some(k.to_string());
    }
    std::env::var("OT_MCP_API_KEY").ok().filter(|k| !k.is_empty())
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
