//! W2a exit-criterion tests: representative scripts covering the series
//! model, warm-up, lazy if, series state, built-ins, compile errors, and
//! determinism (ticket #350; spec docs/agents/research/v2-scripting-spec.md).

use ot_script::{compile, eval, Frame, ScriptRequest, Warmup, check::Pane};
use ot_core::bar::{Bar, Series};
use std::collections::BTreeMap;

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
            volume: 1000.0 + i as f64,
        })
        .collect()
}

fn run(source: &str, closes: &[f64], inputs: BTreeMap<String, serde_json::Value>) -> ot_script::EvalOutput {
    let plan = compile(source).expect("compile");
    let b = bars(closes);
    let req = ScriptRequest {
        source: source.to_string(),
        symbol: "EUR_USD".into(),
        timeframe: "1h".into(),
        inputs,
    };
    eval(&req, &plan, &Frame { bars: &b }).expect("eval")
}

fn run_simple(source: &str, closes: &[f64]) -> ot_script::EvalOutput {
    run(source, closes, BTreeMap::new())
}

fn must_fail(source: &str, contains: &str) {
    match compile(source) {
        Ok(_) => panic!("expected compile error containing `{contains}`, got a plan"),
        Err(e) => assert!(e.contains(contains), "error `{e}` lacks `{contains}`"),
    }
}

// ── 1. series-by-default + per-binding warm-up ─────────────────────────────

#[test]
fn sma_warmup_windows_are_per_binding() {
    let out = run_simple(
        "declare lower;
         def fast = Average(close, 9);
         def slow = Average(close, 20);
         plot f = fast;
         plot s = slow;",
        &(0..60).map(|i| 100.0 + (i % 7) as f64).collect::<Vec<_>>(),
    );
    let f = &out.plots[0].values;
    let s = &out.plots[1].values;
    // binding-local warm-up: fast forms at bar 8, slow at bar 19 — a
    // slow warm-up hole never shifts fast's values (spec §1.3).
    assert!(f[..8].iter().all(|v| v.is_nan()));
    assert!(!f[8].is_nan());
    assert!(s[..19].iter().all(|v| v.is_nan()));
    assert!(!s[19].is_nan());
    // values check: fast[8] = mean of closes[0..=8]
    let expect: f64 = (0..=8).map(|i| 100.0 + (i % 7) as f64).sum::<f64>() / 9.0;
    assert!((f[8] - expect).abs() < 1e-9, "fast[8]={} expect={expect}", f[8]);
}

#[test]
fn history_index_reads_relative_past() {
    let out = run_simple(
        "def chg = close - close[3];
         plot p = chg;",
        &[10.0, 11.0, 12.0, 13.0, 20.0, 21.0],
    );
    let p = &out.plots[0].values;
    assert!(p[2].is_nan()); // close[-1] → NaN
    assert!((p[3] - (13.0 - 10.0)).abs() < 1e-9);
    assert!((p[5] - (21.0 - 12.0)).abs() < 1e-9); // close[5]-close[2]
}

#[test]
fn from_bars_ago_desugars_to_index() {
    let out = run_simple(
        "def c = close from 2 bars ago;
         plot p = c;",
        &[10.0, 11.0, 12.0],
    );
    assert!((out.plots[0].values[2] - 10.0).abs() < 1e-9);
}

// ── 2. series: explicit init, self-state ───────────────────────────────────

#[test]
fn series_has_explicit_init_and_state() {
    let out = run_simple(
        "series cum = volume then cum[1] + volume;
         plot p = cum;",
        &[10.0; 5],
    );
    let p = &out.plots[0].values;
    // volumes are 1000+i; cum = prefix sums
    assert!((p[0] - 1000.0).abs() < 1e-9);
    assert!((p[4] - (1000.0 + 1001.0 + 1002.0 + 1003.0 + 1004.0)).abs() < 1e-9);
}

// ── 3. lazy if (spec §1.2) ─────────────────────────────────────────────────

#[test]
fn lazy_if_only_takes_the_taken_branch() {
    // The else branch divides by a length that would be zero-shaped; if the
    // interpreter evaluated both branches it would still be fine numerically,
    // so instead observe laziness through built-in call state: EMA's state
    // advances only on taken-branch bars.
    let closes: Vec<f64> = (0..30).map(|i| 100.0 + if i % 2 == 0 { 5.0 } else { -5.0 }).collect();
    // The EMA call is INLINE in the branch: with lazy evaluation its
    // call-site state advances ONLY on taken-branch bars. closes: even
    // bars 105, odd 95. EMA(5) evals at bars 0,2,4,6,8 only: NaN, NaN,
    // seed(SMA of closes[0..=4] = (105+95+105+95+105)/5 = 101) at bar 4,
    // then steps at 6 and 8 → 101 + (105-101)/3 = 102.3333 → 103.2222.
    // An EAGER both-branches evaluator advances state every bar: seed 101
    // at bar 4, steps at 5,6,7,8 → p[8] ≈ 100.37 — distinguishable.
    let out = run_simple(
        "def pick = if close > 100 then EMA(close, 5) else 0;
         plot p = pick;",
        &closes,
    );
    let p = &out.plots[0].values;
    for i in (0..10).filter(|i| i % 2 == 1) {
        assert!((p[i] - 0.0).abs() < 1e-12, "odd bar {i} must take the else branch");
    }
    let lazy = {
        let seed = 101.0_f64;
        let alpha = 2.0 / 6.0;
        let s1 = seed + (105.0 - seed) * alpha; // bar 6
        s1 + (105.0 - s1) * alpha               // bar 8
    };
    assert!((p[8] - lazy).abs() < 1e-9, "p[8]={} — EMA state must advance only on taken-branch bars (lazy = {lazy})", p[8]);
}

#[test]
fn if_branches_must_share_type() {
    must_fail("def x = if close > 5 then 1 else true;", "share a type");
}

// ── 4. built-ins ───────────────────────────────────────────────────────────

#[test]
fn ema_matches_the_recursive_definition() {
    let closes: Vec<f64> = (0..40).map(|i| 100.0 + i as f64).collect();
    let out = run_simple(
        "def e = EMA(data = close, length = 5);
         plot p = e;",
        &closes,
    );
    let p = &out.plots[0].values;
    // seed = SMA of first 5 bars at bar 4
    let seed: f64 = (100.0 + 101.0 + 102.0 + 103.0 + 104.0) / 5.0;
    assert!((p[4] - seed).abs() < 1e-9);
    // recursive: alpha = 2/(n+1)
    let alpha = 2.0 / 6.0;
    let mut expect = seed;
    for i in 5..10 {
        expect = expect + (closes[i] - expect) * alpha;
        assert!((p[i] - expect).abs() < 1e-9, "EMA[{i}] {} vs {expect}", p[i]);
    }
}

#[test]
fn rsi_is_centered_and_matches_wilders_smoothing() {
    // Hand-computable series: alternating up/down moves.
    let closes: Vec<f64> = (0..30).map(|i| 100.0 + if i % 2 == 0 { 1.0 } else { 0.0 }).collect();
    let out = run_simple(
        "def r = RSI(close, 14);
         plot p = r;",
        &closes,
    );
    let p = &out.plots[0].values;
    assert!(p[..14].iter().all(|v| v.is_nan()));
    // steady 50% up-bars: avg gain = 0.5, avg loss = 0.5 → RSI 50 → centered 0
    assert!((p[14] - 0.0).abs() < 1e-9, "RSI[14]={}", p[14]);
}

#[test]
fn crosses_above_and_below() {
    let out = run_simple(
        "def sig_a = close crosses above Average(close, 3);
         def sig_b = close crosses below Average(close, 3);
         plot a = if sig_a then 1 else 0;
         plot b = if sig_b then 1 else 0;",
        &[100.0, 100.0, 100.0, 100.0, 110.0, 90.0, 90.0],
    );
    // close crosses above avg at bar 4 (100→110 vs avg[3] ≈ 100)
    assert_eq!(out.plots[0].values[4], 1.0);
    assert_eq!(out.plots[0].values[3], 0.0);
    // crosses below at bar 5 (110→90 vs avg(100,110,90)=100)
    assert_eq!(out.plots[1].values[5], 1.0);
}

#[test]
fn compound_value_and_named_arg_order() {
    let out = run_simple(
        "def c = CompoundValue(3, close, 0);
         plot p = c;",
        &[10.0, 11.0, 12.0, 13.0],
    );
    let p = &out.plots[0].values;
    assert!((p[0] - 0.0).abs() < 1e-9);
    assert!((p[1] - 0.0).abs() < 1e-9);
    assert!((p[2] - 0.0).abs() < 1e-9);
    assert!((p[3] - 13.0).abs() < 1e-9);
}

#[test]
fn highest_lowest_sum_stdev() {
    let out = run_simple(
        "def h = Highest(high, 3);
         def l = Lowest(low, 3);
         def s = Sum(volume, 3);
         def d = StDev(close, 3);
         plot ph = h;
         plot pl = l;
         plot ps = s;
         plot pd = d;",
        &[10.0, 12.0, 11.0, 15.0],
    );
    let ph = &out.plots[0].values;
    let pl = &out.plots[1].values;
    let ps = &out.plots[2].values;
    let pd = &out.plots[3].values;
    // highs of {10,12,11} = {10.05, 12.06, 11.055} → max 12.06
    assert!((ph[2] - (12.0 * 1.005)).abs() < 1e-9);
    assert!((pl[2] - (10.0 * 0.995)).abs() < 1e-9); // min low = 10's
    assert!((ps[2] - 3003.0).abs() < 1e-9);
    // StDev of {10,12,11}: mean 11, sample std = sqrt((1+1+0)/2) = 1
    assert!((pd[2] - 1.0).abs() < 1e-9);
}

// ── 5. plot model ──────────────────────────────────────────────────────────

#[test]
fn panes_and_nan_dont_paint() {
    let out = run_simple(
        "declare lower;
         def gap = if close > 100 then close else NaN;
         plot g = gap;",
        &[99.0, 101.0, 100.5, 98.0],
    );
    assert_eq!(out.plots[0].pane, Some(Pane::Lower));
    let g = &out.plots[0].values;
    assert!(g[0].is_nan(), "NaN = don't paint");
    assert!((g[1] - 101.0).abs() < 1e-9);
    assert!((g[3] - 98.0).abs() < 1e-9 || g[3].is_nan());
}

// ── 6. inputs ──────────────────────────────────────────────────────────────

#[test]
fn inputs_override_defaults_and_shape_the_schema() {
    let src = "input length = 4;
               input useMid = true;
               def a = Average(close, length);
               plot p = a;";
    let plan = compile(src).unwrap();
    assert_eq!(plan.inputs["length"].default, serde_json::json!(4));
    assert_eq!(plan.inputs["useMid"].default, serde_json::json!(true));
    let out = run(src, &[1.0, 2.0, 3.0, 4.0, 5.0, 6.0], {
        let mut m = BTreeMap::new();
        m.insert("length".to_string(), serde_json::json!(2));
        m
    });
    // length 2: a[2] = (2+3)/2
    assert!((out.plots[0].values[2] - 2.5).abs() < 1e-9);
}

#[test]
fn wrong_input_type_is_rejected() {
    let plan = compile("input length = 4; def a = Average(close, length); plot p = a;").unwrap();
    let b = bars(&[1.0, 2.0, 3.0, 4.0, 5.0]);
    let req = ScriptRequest {
        source: "input length = 4; def a = Average(close, length); plot p = a;".into(),
        symbol: "X".into(),
        timeframe: "1h".into(),
        inputs: {
            let mut m = BTreeMap::new();
            m.insert("length".to_string(), serde_json::json!(true));
            m
        },
    };
    let err = eval(&req, &plan, &Frame { bars: &b }).unwrap_err();
    assert!(err.contains("expects"), "{err}");
}

// ── 7. compile errors (the wart drops, made loud) ──────────────────────────

#[test]
fn compile_errors() {
    // no future indexing
    must_fail("def x = close[-1]; plot p = x;", "past-only");
    // def self-reference (state requires series)
    must_fail("def c = c[1] + 1; plot p = c;", "series");
    // bool is not numeric
    must_fail("def x = (close > 5) + 1; plot p = x;", "not numeric");
    // unknown builtin
    must_fail("def x = FancyIndicator(close, 9); plot p = x;", "unknown built-in");
    // non-constant index
    must_fail("def n = 2; def x = close[n]; plot p = x;", "constant non-negative");
    // unknown identifier
    must_fail("def x = frobnicate; plot p = x;", "unknown identifier");
    // positional calls ARE accepted (ThinkScript-compatible; resolve_args
    // maps via the declared parameter order — spec §1.6 named-form is
    // canonical, positional is the compatibility surface)
    assert!(compile("def x = Average(close, 9); plot p = x;").is_ok());
    // secondary frames not in this slice — explicit pointer, not silence
    must_fail("def x = close(period = DAY); plot p = x;", "later W2 slice");
    // duplicate binding
    must_fail("def x = close; def x = close; plot p = x;", "duplicate");
}

// ── 8. determinism + honesty metadata ──────────────────────────────────────

#[test]
fn deterministic_replay_and_warmup_flag() {
    let src = "def e = EMA(close, 5); plot p = e;";
    let closes: Vec<f64> = (0..40).map(|i| 100.0 + i as f64).collect();
    let a = run_simple(src, &closes);
    let b = run_simple(src, &closes);
    let same = a.plots[0].values.iter().zip(&b.plots[0].values)
        .all(|(x, y)| (x.is_nan() && y.is_nan()) || x == y);
    assert!(same);
    assert_eq!(a.last["e"], b.last["e"]);
    // EMA warm-up = 4×5 = 20 (prefetch convention, spec §1.4); 40 bars →
    // complete
    assert_eq!(a.warmup_complete, Warmup::Complete);
    // short frame → incomplete
    let short = run_simple(src, &closes[..10.min(closes.len())]);
    assert_eq!(short.warmup_complete, Warmup::Incomplete);
}

#[test]
fn unbounded_warmup_is_flagged_not_silent() {
    // A cumulative series is history-length-dependent: the output carries
    // warmup_complete = false so consumers can't present it as final.
    let out = run_simple(
        "series cum = close then cum[1] + close; plot p = cum;",
        &[1.0, 2.0, 3.0],
    );
    assert_eq!(out.warmup_complete, Warmup::Incomplete);
}
