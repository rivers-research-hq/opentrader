//! W1-tails venue-parity gate — V2's Rust resolver must reproduce V1's
//! REAL resolver output on the EXPORTED LIVE OANDA journal (the practice
//! account's own 6,896-transaction history; export authorized by the
//! human, read-only). This is the cutover prerequisite: V2's OANDA
//! semantics must match the venue's own attribution on REAL data before
//! any lane migration.
//!
//! cargo test NEVER touches the venue — this reads the committed fixture.

use ot_venues::attribution::{realized_by_tag, trade_tags};
use serde_json::Value;
use std::collections::BTreeMap;

fn fixture_dir() -> std::path::PathBuf {
    std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures")
}

#[test]
fn venue_parity_v1_resolver_on_the_live_journal() {
    let journal: Value = serde_json::from_str(
        &std::fs::read_to_string(fixture_dir().join("live_journal.json")).unwrap(),
    )
    .unwrap();
    let expected: Value = serde_json::from_str(
        &std::fs::read_to_string(fixture_dir().join("live_parity_expected.json")).unwrap(),
    )
    .unwrap();
    let transactions: Vec<Value> = journal["transactions"].as_array().unwrap().clone();

    // sanity: the journal is the one the expectations were computed from
    assert_eq!(
        transactions.len() as u64,
        expected["n_transactions"].as_u64().unwrap(),
        "journal/fixture mismatch"
    );

    // ── the tag chain ──────────────────────────────────────────────────
    let (tags, order_tag) = trade_tags(&transactions);
    assert_eq!(
        tags.len() as u64,
        expected["expect_tags_count"].as_u64().unwrap(),
        "tradeID→tag count: V1 {} vs V2 {}",
        expected["expect_tags_count"],
        tags.len()
    );
    assert_eq!(
        order_tag.len() as u64,
        expected["expect_order_tag_count"].as_u64().unwrap(),
        "orderID→tag count"
    );

    // ── realized-by-tag, tag-for-tag EXACT (bit-identical f64 sums: same
    //    journal order, same string→f64 parse) ──────────────────────────
    let (realized_all, _realized_today) = realized_by_tag(&transactions, "1970-01-01");
    let expect_all: BTreeMap<String, f64> = expected["expect_realized_all"]
        .as_object()
        .unwrap()
        .iter()
        .map(|(k, v)| (k.clone(), v.as_f64().unwrap()))
        .collect();
    let r4 = |x: f64| (x * 10000.0).round() / 10000.0;
    let got: BTreeMap<String, f64> = realized_all
        .iter()
        .map(|(k, v)| (k.clone(), r4(*v)))
        .collect();
    let want: BTreeMap<String, f64> =
        expect_all.iter().map(|(k, v)| (k.clone(), r4(*v))).collect();
    assert_eq!(got, want, "realized-by-tag mismatch on the LIVE journal");

    // lane names must be the V1 lanes + the two loud buckets
    for tag in got.keys() {
        assert!(
            [
                "fxexp-g138", "fxexp-g151", "fxexp-g137", "fxexp-hpo_c_3070",
                "h1-mom", "h1-rev", "h4-brk", "crash", "c08-fade",
                "legacy-smoke", "unattributed",
            ]
            .contains(&tag.as_str()),
            "unexpected tag {tag} (attribution invented a lane?)"
        );
    }

    // the loud bucket stays small on the real journal (the design: most
    // fills resolve through the chain; the bucket exists for the rest)
    let unattr = got.get("unattributed").copied().unwrap_or(0.0);
    let total_abs: f64 = got.values().map(|v| v.abs()).sum();
    assert!(
        unattr.abs() / total_abs.max(1.0) < 0.05,
        "unattributed bucket {unattr} is >5% of |total| {total_abs} — the chain broke"
    );
}
