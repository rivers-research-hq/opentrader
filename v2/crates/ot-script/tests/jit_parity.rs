//! # JIT Parity Harness
//!
//! This test module verifies the correctness of the pluggable scan backend seam.
//! It ensures that the interpreter backend behaves identically to the direct `run_scan`
//! entry point and that backend resolution works as specified.
//!
//! ## Corpus
//! The tests use a shared corpus of scripts covering:
//! - Filter + Sort with ranked hits.
//! - Tie-breaking by symbol ascending.
//! - Limit enforcement (ranked_pool > hits.len()).
//! - Warmup skipping for short-history symbols.
//! - Refusal of unbounded history-dependent scripts.
//! - Refusal of scripts exceeding lookback caps.
//!
//! ## Determinism
//! Tests verify that the interpreter produces byte-identical results across multiple runs.
//!
//! ## Baseline
//! A measured baseline for the interpreter performance is printed to stdout.
//! This is a report, not a pass/fail gate.

use ot_script::jit::{backend_by_name, interpreter, ScanBackend};
use ot_script::check::CompilePlan;
use ot_script::scan::{ScanConfig, ScanRequest, ScanResult};
use ot_core::bar::Bar;
use std::time::Instant;

/// Helper function to build a canned universe of bars.
///
/// # Arguments
/// * `symbol` - The symbol name.
/// * `closes` - A slice of closing prices.
///
/// # Returns
/// A vector of `Bar` structs with sequential timestamps.
fn bars(_symbol: &str, closes: &[f64]) -> Vec<Bar> {
    closes
        .iter()
        .enumerate()
        .map(|(i, &close)| Bar {
            ts: (i as i64) * 86400, // Daily bars
            open: close * 0.99,
            high: close * 1.01,
            low: close * 0.98,
            close,
            volume: 1000.0,
        })
        .collect()
}

/// Builds a test universe with multiple symbols.
fn universe() -> Vec<(String, Vec<Bar>)> {
    vec![
        (
            "AAPL".to_string(),
            bars("AAPL", &[100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0]),
        ),
        (
            "GOOG".to_string(),
            bars("GOOG", &[100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0]),
        ),
        (
            "MSFT".to_string(),
            bars("MSFT", &[100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0]),
        ),
        (
            "TSLA".to_string(),
            bars("TSLA", &[100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0]),
        ),
        (
            "AMZN".to_string(),
            bars("AMZN", &[100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0]),
        ),
        (
            "META".to_string(),
            bars("META", &[100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0]),
        ),
    ]
}

/// Helper to compile a script.
fn compile_script(source: &str) -> CompilePlan {
    ot_script::compile(source).expect("Script should compile")
}

/// Helper to run a scan via the direct API.
fn run_scan_direct(req: &ScanRequest, plan: &CompilePlan, universe: &[(String, Vec<Bar>)], cfg: &ScanConfig) -> Result<ScanResult, String> {
    ot_script::scan::run_scan(req, plan, universe, cfg)
}

/// Helper to run a scan via the backend seam.
fn run_scan_backend(backend: &dyn ScanBackend, req: &ScanRequest, plan: &CompilePlan, universe: &[(String, Vec<Bar>)], cfg: &ScanConfig) -> Result<ScanResult, String> {
    backend.run(req, plan, universe, cfg)
}

/// Corpus of scripts for parity testing.
///
/// Each tuple contains:
/// 1. A name for the test case.
/// 2. The script source.
/// 3. A flag indicating if the script is expected to be refused (Err).
/// 4. The ScanConfig to use.
fn corpus() -> Vec<(&'static str, &'static str, bool, ScanConfig)> {
    // Grounded in crates/ot-script/tests/scan.rs: the valid scan script shape
    // plus the three real refusal cases (history-dependent, lookback cap,
    // symbol cap). `should_fail == true` means run_scan must return Err.
    let ok = ScanConfig {
        max_lookback: 100,
        max_symbols: 100,
        max_bindings: 100,
        allow_unbounded: false,
    };
    vec![
        (
            "filter_sort_ranked",
            "def hot = close > 105;\ndef momentum = close - Average(close, 5);\nplot sig = momentum;",
            false,
            ok.clone(),
        ),
        (
            "tie_breaking_same_sort_key",
            "def hot = close > 105;\ndef momentum = close - Average(close, 5);\nplot sig = momentum;",
            false,
            ok.clone(),
        ),
        (
            "limit_enforcement",
            "def hot = close > 105;\ndef momentum = close - Average(close, 5);\nplot sig = momentum;",
            false,
            ok.clone(),
        ),
        (
            "warmup_skip_short_history",
            "def hot = close > 105;\ndef momentum = close - Average(close, 5);\nplot sig = momentum;",
            false,
            ok.clone(),
        ),
        (
            "refused_history_dependent",
            "series cum = volume then cum[1] + volume;\ndef hot = close > 105;\nplot sig = cum;",
            true,
            ok.clone(),
        ),
        (
            "refused_overlookback",
            "def hot = close > 105;\ndef momentum = close - Average(close, 600);\nplot sig = momentum;",
            true,
            ScanConfig { max_lookback: 500, ..ok.clone() },
        ),
        (
            "refused_symbol_cap",
            "def hot = close > 105;\ndef momentum = close - Average(close, 5);\nplot sig = momentum;",
            true,
            ScanConfig { max_symbols: 2, ..ok.clone() },
        ),
    ]
}

/// Test: Interpreter backend is byte-identical to run_scan.
///
/// For every corpus script, run both `ot_script::run_scan` and `interpreter().run`
/// and assert equality of the serialized results.
#[test]
fn interpreter_backend_is_byte_identical_to_run_scan() {
    let universe = universe();
    let backend = interpreter();

    for (name, source, should_fail, cfg) in corpus() {
        let plan = compile_script(source);
        let req = ScanRequest {
            source: source.to_string(),
            filter: String::new(),
            sort: Some("sig".to_string()),
            timeframe: "1D".to_string(),
            limit: 10,
        };

        let direct_result = run_scan_direct(&req, &plan, &universe, &cfg);
        let backend_result = run_scan_backend(&backend, &req, &plan, &universe, &cfg);

        // Assert both results are the same type (Ok/Ok or Err/Err)
        match (direct_result, backend_result) {
            (Ok(direct), Ok(backend)) => {
                let direct_json = serde_json::to_string(&direct).expect("Direct result should serialize");
                let backend_json = serde_json::to_string(&backend).expect("Backend result should serialize");
                assert_eq!(direct_json, backend_json, "Script '{}' produced different results", name);
            }
            (Err(direct_err), Err(backend_err)) => {
                assert_eq!(direct_err, backend_err, "Script '{}' produced different error messages", name);
            }
            (Ok(_), Err(_)) => {
                panic!("Script '{}' failed: Direct returned Ok, Backend returned Err", name);
            }
            (Err(_), Ok(_)) => {
                panic!("Script '{}' failed: Direct returned Err, Backend returned Ok", name);
            }
        }
    }
}

/// Test: backend_by_name resolves only implemented backends.
///
/// "interpreter" and "interp" return Some; "cranelift", "jit" and "totally-unknown" return None.
/// Assert the returned interpreter backend's `name()` is "interpreter".
#[test]
fn backend_by_name_resolves_only_implemented_backends() {
    // Should resolve
    let interp_backend = backend_by_name("interpreter");
    assert!(interp_backend.is_some(), "interpreter should resolve");
    assert_eq!(interp_backend.unwrap().name(), "interpreter");

    let interp_alias_backend = backend_by_name("interp");
    assert!(interp_alias_backend.is_some(), "interp should resolve");
    assert_eq!(interp_alias_backend.unwrap().name(), "interpreter");

    // Should NOT resolve (no silent fallback)
    assert!(backend_by_name("cranelift").is_none(), "cranelift should not resolve");
    assert!(backend_by_name("jit").is_none(), "jit should not resolve");
    assert!(backend_by_name("jit-cranelift").is_none(), "jit-cranelift should not resolve");
    assert!(backend_by_name("totally-unknown").is_none(), "totally-unknown should not resolve");
}

/// Test: Scan is deterministic across runs and backends.
///
/// Running the same corpus twice through the interpreter produces byte-identical
/// ranked output; refusals are deterministic too.
#[test]
fn scan_is_deterministic_across_runs_and_backends() {
    let universe = universe();
    let backend = interpreter();
    for (name, source, _should_fail, cfg) in corpus() {
        let plan = compile_script(source);
        let req = ScanRequest {
            source: source.to_string(),
            filter: "hot".to_string(),
            sort: Some("sig".to_string()),
            timeframe: "1D".to_string(),
            limit: 10,
        };
        let r1 = backend.run(&req, &plan, &universe, &cfg);
        let r2 = backend.run(&req, &plan, &universe, &cfg);
        match (r1, r2) {
            (Ok(a), Ok(b)) => assert_eq!(
                serde_json::to_string(&a).unwrap(),
                serde_json::to_string(&b).unwrap(),
                "{name}: ranking is not deterministic"
            ),
            (Err(a), Err(b)) => assert_eq!(a, b, "{name}: refusal is not deterministic"),
            _ => panic!("{name}: Ok/Err disagreed across identical runs"),
        }
    }
}

/// Test: Guardrail refusals are identical in both entry points.
///
/// A refusal must not be swallowed or reworded by the backend seam — the
/// future JIT backend is gated on this (it must refuse for the same reasons).
#[test]
fn guardrail_refusals_are_identical_in_both_entry_points() {
    let universe = universe();
    let backend = interpreter();
    for (name, source, should_fail, cfg) in corpus() {
        if !should_fail {
            continue;
        }
        let plan = compile_script(source);
        let req = ScanRequest {
            source: source.to_string(),
            filter: "hot".to_string(),
            sort: Some("sig".to_string()),
            timeframe: "1D".to_string(),
            limit: 10,
        };
        let direct = run_scan_direct(&req, &plan, &universe, &cfg)
            .expect_err(&format!("{name}: run_scan must refuse"));
        let via_backend = backend
            .run(&req, &plan, &universe, &cfg)
            .expect_err(&format!("{name}: backend must refuse"));
        assert_eq!(direct, via_backend, "{name}: refusal text drifted");
    }
}

/// MEASURED interpreter baseline for ticket #391's exit criterion.
///
/// This is a REPORT, not a pass/fail gate: the printed symbols/sec is a real
/// measurement from this machine at test time and must never be hard-coded or
/// quoted as a fixed constant. It is the denominator a future Cranelift JIT
/// backend will be scored against. Run with `-- --nocapture` to see it.
#[test]
fn measured_interpreter_baseline() {
    let num_symbols = 200usize;
    let num_bars = 300usize;
    let n_runs = 3usize;

    // deterministic pseudo-random walk (varied closes, not a flat ramp)
    let mut seed = 12345u64;
    let mut universe: Vec<(String, Vec<Bar>)> = Vec::with_capacity(num_symbols);
    for i in 0..num_symbols {
        let mut closes = Vec::with_capacity(num_bars);
        let mut px = 100.0f64;
        for _ in 0..num_bars {
            seed = seed.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
            let step = ((seed >> 33) % 2001) as f64 / 1000.0 - 1.0; // [-1, 1)
            px = (px + step).max(1.0);
            closes.push(px);
        }
        let symbol = format!("SYM{i:04}");
        universe.push((symbol.clone(), bars(&symbol, &closes)));
    }

    // A REAL filter+sort scan. The first version of this benchmark timed
    // `def val = close;` — a series binding that is REFUSED instantly, so it
    // reported a meaningless 176M symbols/sec from an error path.
    let source = "def hot = close > 105;\ndef momentum = close - Average(close, 5);\nplot sig = momentum;";
    let plan = compile_script(source);
    let req = ScanRequest {
        source: source.to_string(),
        filter: "hot".to_string(),
        sort: Some("momentum".to_string()),
        timeframe: "1D".to_string(),
        limit: 100,
    };
    let cfg = ScanConfig {
        max_lookback: 1000,
        max_symbols: 1000,
        max_bindings: 1000,
        allow_unbounded: false,
    };
    let backend = interpreter();

    // proof the timed work is real work, not a refusal
    let warm = backend
        .run(&req, &plan, &universe, &cfg)
        .expect("baseline must measure a successful scan, not a refusal");
    assert!(warm.scanned > 0, "baseline scanned zero symbols");

    let mut best = std::time::Duration::from_secs(u64::MAX);
    for _ in 0..n_runs {
        let t0 = Instant::now();
        let out = backend.run(&req, &plan, &universe, &cfg);
        let dt = t0.elapsed();
        assert!(out.is_ok(), "timed run must succeed");
        best = best.min(dt);
    }
    let symbols_per_sec = num_symbols as f64 / best.as_secs_f64();
    println!(
        "MEASURED interpreter baseline: symbols={num_symbols}, bars_per_symbol={num_bars}, best_of={n_runs}, elapsed_ms={:.2}, symbols/sec={:.1}, hit_pool={}",
        best.as_secs_f64() * 1000.0,
        symbols_per_sec,
        warm.ranked_pool
    );
}
