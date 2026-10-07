//! W1 attribution parity — V2's Rust resolver must reproduce V1's
//! resolver outputs on the recorded journal (the fixture's `expect` side
//! was computed by V1's real code; see v2/tools/gen_attribution_fixture.py).

use ot_venues::attribution::{realized_by_tag, resolve_fill_tag, trade_tags};
use serde_json::Value;
use std::collections::BTreeMap;

fn fixture() -> Value {
    let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../tests/fixtures/attribution_journal.json");
    serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap()
}

fn id_str(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        Value::Number(n) => n.to_string(),
        _ => panic!("non-scalar id"),
    }
}

#[test]
fn attribution_parity_with_v1() {
    let f = fixture();
    let transactions: Vec<Value> = f["transactions"].as_array().unwrap().clone();
    let today = f["today"].as_str().unwrap();

    // 1. trade_tags
    let (tags, order_tag) = trade_tags(&transactions);
    let expect_tags: BTreeMap<String, String> = f["expect_tags"]
        .as_object()
        .unwrap()
        .iter()
        .map(|(k, v)| (k.clone(), v.as_str().unwrap().to_string()))
        .collect();
    assert_eq!(tags, expect_tags, "tradeID → tag map");
    let expect_order_tag: BTreeMap<String, String> = f["expect_order_tag"]
        .as_object()
        .unwrap()
        .iter()
        .map(|(k, v)| (k.clone(), v.as_str().unwrap().to_string()))
        .collect();
    assert_eq!(order_tag, expect_order_tag, "orderID → tag map");

    // 2. per-fill resolve
    for t in &transactions {
        if t.get("type").and_then(|v| v.as_str()) != Some("ORDER_FILL") {
            continue;
        }
        let txid = id_str(t.get("id").unwrap());
        let got = resolve_fill_tag(t, &tags, &order_tag);
        let want = f["expect_resolve"].get(&txid);
        match want {
            None => panic!("fixture has no expectation for fill {txid}"),
            Some(Value::Null) => assert!(
                got.is_none(),
                "fill {txid}: expected None, got {got:?}"
            ),
            Some(w) => assert_eq!(
                got.as_deref(),
                w.as_str(),
                "fill {txid} resolve mismatch"
            ),
        }
    }

    // 3. realized_by_tag (all + today)
    let (realized_all, realized_today) = realized_by_tag(&transactions, today);
    let round4 = |m: &BTreeMap<String, f64>| -> BTreeMap<String, i64> {
        m.iter().map(|(k, v)| (k.clone(), (v * 10000.0).round() as i64)).collect()
    };
    let expect_all: BTreeMap<String, f64> = f["expect_realized_all"]
        .as_object()
        .unwrap()
        .iter()
        .map(|(k, v)| (k.clone(), v.as_f64().unwrap()))
        .collect();
    let expect_today: BTreeMap<String, f64> = f["expect_realized_today"]
        .as_object()
        .unwrap()
        .iter()
        .map(|(k, v)| (k.clone(), v.as_f64().unwrap()))
        .collect();
    assert_eq!(round4(&realized_all), round4(&expect_all), "realized_all");
    assert_eq!(round4(&realized_today), round4(&expect_today), "realized_today");
}

#[test]
fn legacy_cutoff_grandfathers_pre_cutoff_tagless() {
    // A tagless fill from 2026-08-30 must land in legacy-smoke, NOT
    // unattributed (the ledger is append-only; those rows never rewrite).
    let f = fixture();
    let transactions: Vec<Value> = f["transactions"].as_array().unwrap().clone();
    let (realized_all, _) = realized_by_tag(&transactions, "2026-08-30"); // different "today"
    assert!(realized_all.contains_key("legacy-smoke"));
    assert!((realized_all["legacy-smoke"] - 0.5).abs() < 1e-9);
}
