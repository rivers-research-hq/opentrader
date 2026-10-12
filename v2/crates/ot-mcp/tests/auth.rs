//! W3b exit-criterion tests: key generation/ledger laws, the auth flow
//! over the MCP protocol, per-customer meter limits (ticket #357).

use ot_mcp::{auth::Ledger, serve_lines, ServerState};
use serde_json::{json, Value};
use std::path::PathBuf;

fn temp_ledger(tag: &str) -> PathBuf {
    let p = std::env::temp_dir().join(format!("ot-mcp-test-{tag}-{}.json", std::process::id()));
    let _ = std::fs::remove_file(&p);
    p
}

fn make_customer(path: &PathBuf, customer: &str, plan: &str, max_calls: Option<u64>) -> String {
    Ledger::add(path, customer, plan, max_calls).expect("add customer")
}

fn init_msg(key: Option<&str>) -> Value {
    let mut msg = json!({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-03-26", "capabilities": {}}
    });
    if let Some(k) = key {
        msg["params"]["_ot_auth"] = json!(k);
    }
    msg
}

fn call_tool_msg(id: u64, name: &str, args: Value) -> Value {
    json!({
        "jsonrpc": "2.0", "id": id, "method": "tools/call",
        "params": {"name": name, "arguments": args}
    })
}

fn state_with(ledger: &PathBuf) -> ServerState {
    ServerState {
        ledger_path: ledger.clone(),
        ..Default::default()
    }
}

/// the env-var test is serialized (env is process-global)
static ENV_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());
fn env_lock() -> std::sync::MutexGuard<'static, ()> {
    ENV_LOCK.lock().unwrap_or_else(|poisoned| poisoned.into_inner())
}

fn run(messages: &[Value], state: &mut ServerState) -> Vec<Value> {
    let lines: Vec<String> = messages.iter().map(|m| m.to_string()).collect();
    let mut responses = Vec::new();
    serve_lines(lines.into_iter(), &mut |r| responses.push(r.clone()), state);
    responses
}

// ── ledger laws ────────────────────────────────────────────────────────────

#[test]
fn key_is_generated_once_and_only_the_hash_is_stored() {
    let path = temp_ledger("hash");
    let key = make_customer(&path, "acme", "alpha", None);
    // shape: ot_<32 hex>
    assert!(key.starts_with("ot_") && key.len() == 35, "{key}");
    let ledger = Ledger::load(&path).expect("ledger");
    assert_eq!(ledger.entries.len(), 1);
    // the raw key appears NOWHERE in the ledger
    let text = std::fs::read_to_string(&path).unwrap();
    assert!(!text.contains(&key), "raw key must never be stored");
    // hash verification works
    let identity = ledger.verify(&key).expect("verify");
    assert_eq!(identity.customer, "acme");
    assert_eq!(identity.plan, "alpha");
    assert!(ledger.verify("ot_00000000000000000000000000000000").is_none());
    let _ = std::fs::remove_file(&path);
}

#[test]
fn generate_is_idempotent_safe_and_deterministic_verify() {
    let path = temp_ledger("multi");
    let k1 = make_customer(&path, "acme", "alpha", None);
    let k2 = make_customer(&path, "blob", "alpha", Some(3));
    assert_ne!(k1, k2);
    let ledger = Ledger::load(&path).expect("ledger");
    assert_eq!(ledger.entries.len(), 2);
    assert_eq!(ledger.verify(&k2).unwrap().max_calls, Some(3));
    assert_eq!(ledger.verify(&k1).unwrap().max_calls, None);
    let _ = std::fs::remove_file(&path);
}

#[test]
fn corrupt_ledger_fails_loudly() {
    let path = temp_ledger("corrupt");
    std::fs::write(&path, "not json").unwrap();
    assert!(Ledger::load(&path).is_err());
    let _ = std::fs::remove_file(&path);
}

// ── auth flow over the protocol ────────────────────────────────────────────

#[test]
fn unauthenticated_initialize_is_refused() {
    let _guard = env_lock();
    let path = temp_ledger("auth1");
    let _key = make_customer(&path, "acme", "alpha", None);
    std::env::remove_var("OT_MCP_API_KEY");
    let mut state = state_with(&path);
    let responses = run(&[init_msg(None)], &mut state);
    assert_eq!(responses[0].pointer("/error/code").unwrap(), -32001);
    assert!(responses[0].pointer("/error/message").unwrap().as_str().unwrap().contains("no API key"));
    let _ = std::fs::remove_file(&path);
}

#[test]
fn invalid_key_is_refused() {
    let _guard = env_lock();
    let path = temp_ledger("auth2");
    let _key = make_customer(&path, "acme", "alpha", None);
    std::env::remove_var("OT_MCP_API_KEY");
    let mut state = state_with(&path);
    let responses = run(&[init_msg(Some("ot_00000000000000000000000000000000"))], &mut state);
    assert_eq!(responses[0].pointer("/error/code").unwrap(), -32001);
    assert!(responses[0].pointer("/error/message").unwrap().as_str().unwrap().contains("invalid API key"));
    let _ = std::fs::remove_file(&path);
}

#[test]
fn valid_key_authenticates_and_identity_surfaces() {
    let _guard = env_lock();
    let path = temp_ledger("auth3");
    let key = make_customer(&path, "acme", "alpha", None);
    std::env::remove_var("OT_MCP_API_KEY");
    let mut state = state_with(&path);
    let responses = run(
        &[init_msg(Some(&key)), call_tool_msg(2, "script.validate", json!({"source": "plot p = close;"}))],
        &mut state,
    );
    let init = &responses[0];
    assert!(init.get("error").is_none(), "{init}");
    assert_eq!(init.pointer("/result/_ot/authenticated").unwrap(), true);
    assert_eq!(init.pointer("/result/_ot/customer").unwrap(), "acme");
    // tools work after auth
    assert!(responses[1].pointer("/result/content").is_some());
    assert!(state.identity.is_some());
    let _ = std::fs::remove_file(&path);
}

#[test]
fn tools_call_before_auth_is_refused() {
    let _guard = env_lock();
    let path = temp_ledger("auth4");
    let _key = make_customer(&path, "acme", "alpha", None);
    std::env::remove_var("OT_MCP_API_KEY");
    let mut state = state_with(&path);
    let responses = run(
        &[call_tool_msg(1, "script.validate", json!({"source": "plot p = close;"}))],
        &mut state,
    );
    assert_eq!(responses[0].pointer("/error/code").unwrap(), -32001);
    assert!(responses[0].pointer("/error/message").unwrap().as_str().unwrap().contains("not authenticated"));
    let _ = std::fs::remove_file(&path);
}

#[test]
fn env_var_key_authenticates_without_params() {
    let path = temp_ledger("auth5");
    let key = make_customer(&path, "env-user", "alpha", None);
    let _guard = env_lock();
    std::env::set_var("OT_MCP_API_KEY", &key);
    let mut state = state_with(&path);
    let responses = run(&[init_msg(None)], &mut state);
    std::env::remove_var("OT_MCP_API_KEY");
    assert!(responses[0].get("error").is_none(), "{}", responses[0]);
    assert_eq!(responses[0].pointer("/result/_ot/customer").unwrap(), "env-user");
    let _ = std::fs::remove_file(&path);
}

#[test]
fn no_auth_mode_skips_authentication() {
    let _guard = env_lock();
    let path = temp_ledger("noauth");
    let mut state = state_with(&path);
    state.skip_auth = true;
    std::env::remove_var("OT_MCP_API_KEY");
    let responses = run(
        &[
            init_msg(None),
            call_tool_msg(2, "script.validate", json!({"source": "plot p = close;"})),
        ],
        &mut state,
    );
    assert!(responses[0].get("error").is_none());
    assert_eq!(responses[0].pointer("/result/_ot/mode").unwrap(), "no-auth (local dev)");
    assert!(responses[1].pointer("/result/content").is_some());
}

// ── per-customer meter limits ──────────────────────────────────────────────

#[test]
fn meter_limit_enforced_with_explicit_error() {
    let path = temp_ledger("limit");
    let key = make_customer(&path, "frugal", "alpha", Some(2));
    let _guard = env_lock();
    std::env::remove_var("OT_MCP_API_KEY");
    let mut state = state_with(&path);
    let responses = run(
        &[
            init_msg(Some(&key)),
            call_tool_msg(2, "script.validate", json!({"source": "plot p = close;"})),
            call_tool_msg(3, "script.validate", json!({"source": "plot p = close;"})),
            call_tool_msg(4, "script.validate", json!({"source": "plot p = close;"})), // over limit
        ],
        &mut state,
    );
    assert!(responses[1].pointer("/result/content").is_some(), "call 1 ok");
    assert!(responses[2].pointer("/result/content").is_some(), "call 2 ok");
    assert_eq!(responses[3].pointer("/error/code").unwrap(), -32002, "call 3 over limit");
    let msg = responses[3].pointer("/error/message").unwrap().as_str().unwrap();
    assert!(msg.contains("meter limit exceeded"), "{msg}");
    assert!(msg.contains("reset on restart"), "honesty: in-memory counters are documented");
    let _ = std::fs::remove_file(&path);
}

#[test]
fn unlimited_plan_is_not_limited() {
    let path = temp_ledger("unlim");
    let key = make_customer(&path, "unlimited", "alpha", None);
    let _guard = env_lock();
    std::env::remove_var("OT_MCP_API_KEY");
    let mut state = state_with(&path);
    let mut messages = vec![init_msg(Some(&key))];
    for i in 2..12 {
        messages.push(call_tool_msg(i, "script.validate", json!({"source": "plot p = close;"})));
    }
    let responses = run(&messages, &mut state);
    for (i, r) in responses.iter().enumerate() {
        assert!(r.get("error").is_none(), "response {i} errored: {r:?}");
    }
    let _ = std::fs::remove_file(&path);
}
