//! W2f exit-criterion tests: scanner guardrails, ranking, warm-up skips,
//! determinism (ticket #355; spec §8).

use ot_script::{compile, run_scan, ScanConfig, ScanRequest};
use ot_core::bar::Bar;

fn bars(closes: &[f64]) -> Vec<Bar> {
    closes
        .iter()
        .enumerate()
        .map(|(i, &c)| Bar {
            ts: 1000 + i as i64,
            open: c * 0.999,
            high: c * 1.005,
            low: c * 0.995,
            close: c,
            volume: 1000.0,
        })
        .collect()
}

fn scan_req(filter: &str, sort: Option<&str>, limit: usize) -> ScanRequest {
    ScanRequest {
        source: UNIVERSE_SRC.to_string(),
        filter: filter.to_string(),
        sort: sort.map(String::from),
        timeframe: "1h".into(),
        limit,
    }
}

const UNIVERSE_SRC: &str = "def hot = close > 105;
def momentum = close - Average(close, 5);
plot sig = momentum;";

// ── 1. ranking + filter + limit ────────────────────────────────────────────

#[test]
fn scan_ranks_by_sort_desc_and_applies_filter_and_limit() {
    let plan = compile(UNIVERSE_SRC).expect("compile");
    // AAA: flat 100 → filter false. BBB: 110, momentum 8. CCC: 106,
    // momentum 4. DDD: 106, momentum 4 → tie with CCC → symbol asc.
    let universe = vec![
        ("AAA".to_string(), bars(&[100.0; 8])),
        ("BBB".to_string(), bars(&[100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 108.0, 110.0])),
        ("CCC".to_string(), bars(&[100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 105.0, 106.0])),
        ("DDD".to_string(), bars(&[100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 105.0, 106.0])),
    ];
    let cfg = ScanConfig::default();
    let req = scan_req("hot", Some("momentum"), 10);
    let r = run_scan(&req, &plan, &universe, &cfg).expect("scan");
    assert_eq!(r.scanned, 4);
    assert_eq!(r.skipped_warmup, 0);
    assert_eq!(r.ranked_pool, 3, "AAA filtered out: {:?}", r.hits);
    // ranking: BBB first (momentum 6.4 = 110 − mean(100,100,100,108,110));
    // CCC/DDD tie (3.8 = 106 − mean(100,100,100,105,106)) → symbol asc
    assert_eq!(r.hits[0].symbol, "BBB");
    assert!((r.hits[0].sort - 6.4).abs() < 1e-9, "sort {}", r.hits[0].sort);
    assert!((r.hits[1].sort - 3.8).abs() < 1e-9, "sort {}", r.hits[1].sort);
    assert_eq!(r.hits[1].symbol, "CCC");
    assert_eq!(r.hits[2].symbol, "DDD");
    // limit truncation
    let req_lim = scan_req("hot", Some("momentum"), 2);
    let r2 = run_scan(&req_lim, &plan, &universe, &cfg).expect("scan");
    assert_eq!(r2.ranked_pool, 3);
    assert_eq!(r2.hits.len(), 2);
}

#[test]
fn scan_without_sort_ranks_by_symbol() {
    let plan = compile(UNIVERSE_SRC).expect("compile");
    let universe = vec![
        ("ZZZ".to_string(), bars(&[100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 110.0])),
        ("AAA".to_string(), bars(&[100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 120.0])),
    ];
    let req = scan_req("hot", None, 10);
    let r = run_scan(&req, &plan, &universe, &ScanConfig::default()).expect("scan");
    assert_eq!(r.hits.len(), 2);
    assert_eq!(r.hits[0].symbol, "AAA", "no sort → symbol asc");
    assert_eq!(r.hits[1].symbol, "ZZZ");
}

// ── 2. warm-up skips are counted, not silent ───────────────────────────────

#[test]
fn insufficient_bars_are_skipped_and_counted() {
    // hot's warm-up = Average's lookback (4) → needs ≥ 5 bars; a 3-bar
    // symbol is SKIPPED and counted, never silently dropped or errored.
    let src = "def hot = close > Average(close, 5);";
    let plan = compile(src).expect("compile");
    let universe = vec![
        ("THIN".to_string(), bars(&[100.0, 106.0, 108.0])),
        ("FULL".to_string(), bars(&[100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 110.0])),
    ];
    let req = ScanRequest {
        source: src.to_string(),
        filter: "hot".to_string(),
        sort: None,
        timeframe: "1h".into(),
        limit: 10,
    };
    let r = run_scan(&req, &plan, &universe, &ScanConfig::default()).expect("scan");
    assert_eq!(r.skipped_warmup, 1, "THIN skipped and counted");
    assert_eq!(r.scanned, 2);
    assert_eq!(r.hits.iter().map(|h| h.symbol.as_str()).collect::<Vec<_>>(), ["FULL"]);
}

// ── 3. guardrails ──────────────────────────────────────────────────────────

#[test]
fn guardrail_refuses_history_dependent_scripts() {
    let plan = compile("series cum = volume then cum[1] + volume;\ndef hot = close > 105;\nplot sig = cum;")
        .expect("compile");
    let universe = vec![("AAA".to_string(), bars(&[100.0; 8]))];
    let req = scan_req("hot", None, 10);
    let err = run_scan(&req, &plan, &universe, &ScanConfig::default()).unwrap_err();
    assert!(err.contains("history-dependent"), "{err}");
    // explicit grant passes
    let cfg = ScanConfig { allow_unbounded: true, ..ScanConfig::default() };
    let r = run_scan(&req, &plan, &universe, &cfg).expect("granted");
    assert_eq!(r.scanned, 1);
}

#[test]
fn guardrail_refuses_overlookback() {
    // Average(close, 600) → lookback 599 > cap 500
    let plan = compile("def hot = close > Average(close, 600);").expect("compile");
    let universe = vec![("AAA".to_string(), bars(&[100.0; 700]))];
    let req = scan_req("hot", None, 10);
    let cfg = ScanConfig::default();
    let err = run_scan(&req, &plan, &universe, &cfg).unwrap_err();
    assert!(err.contains("lookback"), "{err}");
    // cap raised → passes
    let cfg = ScanConfig { max_lookback: 700, ..ScanConfig::default() };
    let r = run_scan(&req, &plan, &universe, &cfg).expect("raised cap");
    assert_eq!(r.scanned, 1);
}

#[test]
fn guardrail_refuses_symbol_overage() {
    let plan = compile(UNIVERSE_SRC).expect("compile");
    let universe: Vec<(String, Vec<Bar>)> = (0..5)
        .map(|i| (format!("S{i}"), bars(&[100.0; 8])))
        .collect();
    let cfg = ScanConfig { max_symbols: 4, ..ScanConfig::default() };
    let req = scan_req("hot", None, 10);
    let err = run_scan(&req, &plan, &universe, &cfg).unwrap_err();
    assert!(err.contains("symbol cap"), "{err}");
}

#[test]
fn filter_and_sort_types_are_enforced() {
    // source comes from the REQUEST (the scanner re-parses it) — one source
    // per case, plan compiled from the same text
    let cases: &[(&str, &str, Option<&str>, &str)] = &[
        ("def n = close - close[1];", "n", None, "must be bool"),
        ("def b = close > 105;", "b", Some("b"), "must be float"),
        ("def b = close > 105;", "nope", None, "not found"),
    ];
    for (src, filter, sort, expect) in cases {
        let plan = compile(src).expect("compile");
        let universe = vec![("AAA".to_string(), bars(&[100.0; 8]))];
        let req = ScanRequest {
            source: src.to_string(),
            filter: filter.to_string(),
            sort: sort.map(String::from),
            timeframe: "1h".into(),
            limit: 10,
        };
        let err = run_scan(&req, &plan, &universe, &ScanConfig::default()).unwrap_err();
        assert!(err.contains(expect), "{err}");
    }
}

#[test]
fn scan_is_deterministic() {
    let plan = compile(UNIVERSE_SRC).expect("compile");
    let universe = vec![
        ("BBB".to_string(), bars(&[100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 108.0, 110.0])),
        ("CCC".to_string(), bars(&[100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 105.0, 106.0])),
    ];
    let req = scan_req("hot", Some("momentum"), 10);
    let a = run_scan(&req, &plan, &universe, &ScanConfig::default()).expect("a");
    let b = run_scan(&req, &plan, &universe, &ScanConfig::default()).expect("b");
    assert_eq!(a.hits.len(), b.hits.len());
    for (ha, hb) in a.hits.iter().zip(&b.hits) {
        assert_eq!(ha.symbol, hb.symbol);
        assert_eq!(ha.sort, hb.sort);
        assert_eq!(ha.last_close, hb.last_close);
    }
}

#[test]
fn scan_hits_serialize_for_the_mcp_surface() {
    // the scan.run MCP tool rides later on this API — the result shape
    // must be serializable NOW
    let plan = compile(UNIVERSE_SRC).expect("compile");
    let universe = vec![("AAA".to_string(), bars(&[100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 110.0]))];
    let req = scan_req("hot", None, 10);
    let r = run_scan(&req, &plan, &universe, &ScanConfig::default()).expect("scan");
    let json = serde_json::to_string(&r).expect("serialize");
    assert!(json.contains("AAA"), "{json}");
    assert!(json.contains("hits"), "{json}");
}
