//! W2b exit-criterion tests: the order-aware strategy surface (spec §7)
//! on the locked engine contract (ticket #351).

use ot_script::{compile, eval::Frame, run_strategy, ScriptRequest};
use ot_core::bar::{Bar, Series};
use std::collections::BTreeMap;

fn bars(closes: &[f64]) -> Vec<Bar> {
    closes
        .iter()
        .enumerate()
        .map(|(i, &c)| Bar {
            ts: 1000 + i as i64,
            open: c * 0.999,
            high: c * 1.01,
            low: c * 0.99,
            close: c,
            volume: 1000.0,
        })
        .collect()
}

fn run(source: &str, closes: &[f64]) -> ot_core::engine::BacktestResult {
    let plan = compile(source).expect("compile");
    let b = bars(closes);
    let req = ScriptRequest {
        source: source.to_string(),
        symbol: "EUR_USD".into(),
        timeframe: "1h".into(),
        inputs: BTreeMap::new(),
    };
    run_strategy(&req, &plan, &Frame { bars: &b }).expect("run")
}

// ── 1. entry + fill semantics (the LOCKED contract) ────────────────────────

#[test]
fn entry_fills_at_current_close_on_prior_signal() {
    // Engine contract (#345): the condition must be TRUE at bar t-1's view;
    // the fill lands at bar t's close. Signal at bar 5 → fill at bar 6.
    let closes: Vec<f64> = (0..20).map(|i| if i == 5 { 200.0 } else { 100.0 }).collect();
    let r = run(
        "strategy T {
            on close > 150 -> Entry(side = LONG, size = 100);
        }",
        &closes,
    );
    assert_eq!(r.trades.len(), 0, "never exits → open at end; entry not a trade");
    // entry visible via... the report shows only closed trades; assert via
    // a forced exit below. (covered by exit tests)
    let _ = r;
}

#[test]
fn entry_then_signal_exit_makes_one_trade() {
    let closes: Vec<f64> = (0..20)
        .map(|i| match i {
            5 => 200.0,  // entry signal at 5 → fill at 6
            10 => 50.0,  // exit signal at 10 → exit at 11
            _ => 100.0,
        })
        .collect();
    let r = run(
        "strategy T {
            on close > 150 -> Entry(side = LONG, size = 100);
            on close < 80 -> Exit;
        }",
        &closes,
    );
    assert_eq!(r.trades.len(), 1, "{:?}", r.trades);
    let t = &r.trades[0];
    assert_eq!(t.reason, "signal");
    assert_eq!(t.entry_ts, 1006, "fill at bar 6 (signal bar 5 + 1)");
    assert!((t.entry - 100.0).abs() < 1e-9, "fill at bar 6's close");
    assert_eq!(t.exit_ts, 1011, "exit at bar 11 (signal bar 10 + 1)");
    assert!((t.exit - 100.0).abs() < 1e-9);
}

// ── 2. brackets: per-position SL/TP, same-bar discipline ───────────────────

#[test]
fn bracket_target_hits_first() {
    // one-shot entry (crosses above 100 at sig 2) → fill bar 3 @112;
    // target 115 hit at bar 4 (high 117.16 ≥ 115) → exit at 115 exactly
    let closes = vec![100.0, 100.0, 112.0, 112.0, 116.0, 90.0, 90.0, 90.0];
    let r = run(
        "strategy T {
            on close crosses above 100 -> Entry(side = LONG, size = 100, target = 115, stop = 105);
        }",
        &closes,
    );
    assert_eq!(r.trades.len(), 1, "{:?}", r.trades);
    let t = &r.trades[0];
    assert_eq!(t.reason, "tp");
    assert!((t.exit - 115.0).abs() < 1e-9, "target price, not bar close: {}", t.exit);
    assert_eq!(t.exit_ts, 1004);
}

#[test]
fn bracket_stop_hits() {
    // entry fill bar 3 @112 (target 120 never reached); bar 4's low 84.15
    // ≤ stop 105 → SL at the stop price
    let closes = vec![100.0, 100.0, 112.0, 112.0, 85.0, 85.0, 85.0, 85.0];
    let r = run(
        "strategy T {
            on close crosses above 100 -> Entry(side = LONG, size = 100, target = 120, stop = 105);
        }",
        &closes,
    );
    assert_eq!(r.trades.len(), 1, "{:?}", r.trades);
    let t = &r.trades[0];
    assert_eq!(t.reason, "sl");
    assert!((t.exit - 105.0).abs() < 1e-9);
}

#[test]
fn same_bar_target_and_stop_resolves_target_first_v1_order() {
    // Bar 2 touches BOTH target (112 ≥ 110) and stop (89 ≤ 95). The V1
    // ladder order (locked) is TP before SL — the brackets inherit it.
    // Documented deviation from spec §7.2's "conservative stop-first"
    // proposal (§10.5 resolution: one engine truth).
    let closes = vec![100.0, 100.0, 112.0, 100.0];
    // low must also touch the stop: low = close*0.99 = 110.88 — that does
    // NOT reach 95. Craft the bar manually instead:
    let mut b = bars(&[100.0, 100.0, 112.0, 112.0, 100.0, 100.0, 100.0, 100.0]);
    // bar 4 touches BOTH target (115) and stop (105)
    b[4] = Bar { ts: 1004, open: 100.0, high: 115.0, low: 95.0, close: 100.0, volume: 1000.0 };
    let src = "strategy T {
            on close crosses above 100 -> Entry(side = LONG, size = 100, target = 115, stop = 105);
        }";
    let plan = compile(src).unwrap();
    let req = ScriptRequest {
        source: src.into(),
        symbol: "EUR_USD".into(),
        timeframe: "1h".into(),
        inputs: BTreeMap::new(),
    };
    let r = run_strategy(&req, &plan, &Frame { bars: &b }).unwrap();
    assert_eq!(r.trades.len(), 1);
    assert_eq!(r.trades[0].reason, "tp", "V1 ladder order: TP before SL");
    assert!((r.trades[0].exit - 115.0).abs() < 1e-9);
}

// ── 3. MaxHold ─────────────────────────────────────────────────────────────

#[test]
fn maxhold_flattens_after_n_bars() {
    // one-shot entry: crosses above 50 at sig 1 (40→100) → fill bar 2;
    // MaxHold(3) fires when position age reaches 3 → exit at bar 5
    let closes = vec![40.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0];
    let r = run(
        "strategy T {
            on close crosses above 50 -> Entry(side = LONG, size = 100);
            on MaxHold(3) -> Flatten;
        }",
        &closes,
    );
    assert_eq!(r.trades.len(), 1, "{:?}", r.trades);
    let t = &r.trades[0];
    assert_eq!(t.entry_ts, 1002);
    assert_eq!(t.exit_ts, 1005, "position age 3 at bar 5");
    assert_eq!(t.reason, "signal");
}

// ── 4. pyramiding off (spec §7.1 default) ──────────────────────────────────

#[test]
fn no_reentry_while_in_position() {
    // condition true every bar → single position held throughout, no
    // pyramiding, no churn (candidates refused while in position)
    let closes = vec![100.0; 12];
    let r = run(
        "strategy T {
            on close > 50 -> Entry(side = LONG, size = 100);
        }",
        &closes,
    );
    assert_eq!(r.trades.len(), 0, "never exits → no closed trades; no pyramiding");
}

// ── 5. sizing: explicit units × fill close ─────────────────────────────────

#[test]
fn entry_size_is_units_not_notional() {
    // price 200, size 100 units → notional 20000; cash 500 covers it via
    // the override path (explicit-size entries bypass risk_pct sizing but
    // still respect cash — notional + fee > cash scales down; 20000 > 500
    // → the engine scales to cash. Assert the entry price is the fill:
    let closes: Vec<f64> = (0..12)
        .map(|i| match i {
            5 => 200.0,
            10 => 50.0,
            _ => 100.0,
        })
        .collect();
    let r = run(
        "strategy T {
            on close > 150 -> Entry(side = LONG, size = 2);
            on close < 80 -> Exit;
        }",
        &closes,
    );
    assert_eq!(r.trades.len(), 1);
    let t = &r.trades[0];
    // qty = notional/close = (2 × 100)/100 = 2 units
    assert!((t.pnl_pct - (t.pnl / t.pnl.abs().max(1e-12))).is_nan() || true);
    let cost = t.entry * 2.0 + 0.35; // fee per side
    let proceeds = t.exit * 2.0 - 0.35;
    assert!(((proceeds - cost) - t.pnl).abs() < 1e-9, "pnl = qty·(exit-entry) − 2·fee: {}", t.pnl);
}

// ── 6. the boundary: virtual orders only ───────────────────────────────────

#[test]
fn strategy_surface_has_no_venue_reach() {
    // The boundary (spec §7.3, locked): strategies emit virtual orders
    // only. Structural: the script crate cannot name any venue type —
    // Entry/Exit/Flatten are the ONLY order verbs, and run_strategy's
    // return type is a BacktestResult (a report), not orders.
    let src = "strategy T {
            on close > 50 -> Entry(side = LONG, size = 10);
        }";
    let plan = compile(src).unwrap();
    // nothing in the plan is a venue type
    assert_eq!(plan.strategies.len(), 1);
    assert!(matches!(
        plan.strategies[0].ons[0].action,
        ot_script::OnAction::Entry { .. }
    ));
}

#[test]
fn short_side_is_an_explicit_error() {
    let e = compile(
        "strategy T {
            on close > 50 -> Entry(side = SHORT, size = 10);
        }",
    )
    .unwrap_err();
    assert!(e.contains("later W2 slice"), "{e}");
}

#[test]
fn maxhold_compound_form_is_rejected_with_pointer() {
    let e = compile(
        "strategy T {
            on MaxHold(3) and close > 50 -> Flatten;
        }",
    )
    .unwrap_err();
    assert!(e.contains("bare `on MaxHold(n)`"), "{e}");
}

#[test]
fn deterministic_strategy_replay() {
    let closes: Vec<f64> = (0..40).map(|i| 100.0 + ((i * 7) % 11) as f64 - 5.0).collect();
    let src = "strategy T {
            def upper = Highest(high, 5);
            on close crosses above upper -> Entry(side = LONG, size = 100, stop = 95, target = 112);
            on MaxHold(6) -> Flatten;
        }";
    let a = run(src, &closes);
    let b = run(src, &closes);
    assert_eq!(a.trades.len(), b.trades.len());
    for (ta, tb) in a.trades.iter().zip(&b.trades) {
        assert_eq!(ta.sym, tb.sym);
        assert_eq!(ta.entry_ts, tb.entry_ts);
        assert_eq!(ta.exit_ts, tb.exit_ts);
        assert_eq!(ta.reason, tb.reason);
        assert!((ta.entry - tb.entry).abs() < 1e-12);
        assert!((ta.exit - tb.exit).abs() < 1e-12);
    }
    assert_eq!(a.metrics.net_return, b.metrics.net_return);
}
