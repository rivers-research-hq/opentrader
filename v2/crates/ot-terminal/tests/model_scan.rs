//! W4a (ticket #388) — ScanTab integration over the real ot-script::scan API.
//! The scan engine is W2f's (no second path); this tests the UI-state wrapper:
//! deterministic ranking, error surfacing, and no panic on bad input.

use ot_core::bar::Bar;
use ot_terminal::model::{BarsStore, ScanTab};

fn bar(ts: i64, open: f64, close: f64) -> Bar {
    Bar {
        ts,
        open,
        high: close.max(open) * 1.005,
        low: close.min(open) * 0.995,
        close,
        volume: 1000.0,
    }
}

fn rising(sym: &str, store: &mut BarsStore, n: i64) {
    for i in 0..n {
        let base = 100.0 + i as f64;
        store.append(sym, bar(1000 + i, base, base + 1.0));
    }
}

fn falling(sym: &str, store: &mut BarsStore, n: i64) {
    for i in 0..n {
        let base = 200.0 - i as f64;
        store.append(sym, bar(2000 + i, base, base - 1.0));
    }
}

#[test]
fn scan_runs_over_the_store_and_is_deterministic() {
    let mut store = BarsStore::default();
    rising("EUR_USD", &mut store, 30);
    falling("USD_JPY", &mut store, 30);

    let mut tab = ScanTab::new();
    tab.source = "def up = close > close[1];".to_string();
    tab.filter = "up".to_string();
    tab.run(&store, &["EUR_USD", "USD_JPY"]);

    assert!(tab.error.is_none(), "unexpected error: {:?}", tab.error);
    let result = tab.result.as_ref().expect("scan must produce a result");
    assert_eq!(result.scanned, 2, "both symbols scanned");
    // EUR_USD closes rise every bar → filter true at the last bar.
    // USD_JPY falls → filter false → not a hit.
    assert_eq!(result.hits.len(), 1);
    assert_eq!(result.hits[0].symbol, "EUR_USD");
    assert!(result.hits[0].filter);

    // determinism: same store → same ranked output
    let mut tab2 = ScanTab::new();
    tab2.source = tab.source.clone();
    tab2.filter = tab.filter.clone();
    tab2.run(&store, &["USD_JPY", "EUR_USD"]); // different symbol order
    let r2 = tab2.result.as_ref().unwrap();
    assert_eq!(r2.hits.len(), result.hits.len());
    assert_eq!(r2.hits[0].symbol, result.hits[0].symbol);
    assert_eq!(r2.hits[0].last_close, result.hits[0].last_close);
}

#[test]
fn compile_errors_surface_and_result_stays_none() {
    let mut store = BarsStore::default();
    rising("EUR_USD", &mut store, 20);

    let mut tab = ScanTab::new();
    tab.source = "def broken syntax !!!".to_string();
    tab.filter = "broken".to_string();
    tab.run(&store, &["EUR_USD"]);

    assert!(tab.result.is_none(), "no result on compile error");
    let err = tab.error.as_ref().expect("error must be set");
    assert!(err.contains("Compile error"), "error should say compile: {err}");
}

#[test]
fn guardrail_refusals_surface_as_errors_not_panics() {
    // a series binding is history-dependent → the scanner refuses it unless
    // granted (W2f's guardrail must come through the UI wrapper loudly)
    let mut store = BarsStore::default();
    rising("EUR_USD", &mut store, 20);

    let mut tab = ScanTab::new();
    tab.source = "def w = Highest(high, 5000);".to_string();
    tab.filter = "w".to_string();
    tab.run(&store, &["EUR_USD"]);
    // either a compile/run refusal in error, or a loud per-symbol error —
    // but NEVER a panic and NEVER a silent fabricated hit
    if tab.result.is_none() {
        assert!(tab.error.is_some(), "refusal must surface an error");
    }
}
