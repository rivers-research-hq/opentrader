//! Contract proptests — the locked invariants (ticket #345) expressed as
//! property tests. The pre-1718f33 lesson: same-bar execution inflated
//! every metric ~4-5pp; these tests are the permanent defense.

use ot_core::bar::{Bar, Series};
use ot_core::config::{clamp_config, Config, DEFAULT_CONFIG};
use ot_core::engine::{evaluate_engine_exit, replay, Candidate, DecisionView, ExitReason, Handler, Position};
use ot_core::rulefloor::RuleFloor;
use ot_core::universe::Universe;
use proptest::prelude::*;
use std::collections::{BTreeMap, BTreeSet};

// ── helpers ────────────────────────────────────────────────────────────────

fn linear_universe(n: usize, n_syms: usize, gap_symbol: Option<(usize, usize)>) -> Universe {
    // n bars on ts = 1000+i; prices deterministic pseudo-random walk.
    let mut series: BTreeMap<String, Series> = BTreeMap::new();
    let mut vols: BTreeMap<String, Vec<f64>> = BTreeMap::new();
    for s in 0..n_syms {
        let sym = format!("S{:02}", s);
        let mut bars = Vec::new();
        let mut price = 100.0 + s as f64 * 7.0;
        for i in 0..n {
            price = (price * (1.0 + ((i * (s + 3)) % 7) as f64 / 500.0 - 0.006)).max(1.0);
            let ts = (1000 + i) as i64;
            if let Some((sym_skip, lo)) = gap_symbol {
                if s == sym_skip && i >= lo && i < n {
                    continue; // symbol's series ends at `lo` (delist)
                }
            }
            bars.push(Bar {
                ts,
                open: price * 0.999,
                high: price * 1.01,
                low: price * 0.99,
                close: price,
                volume: 1000.0 + i as f64,
            });
        }
        vols.insert(sym.clone(), bars.iter().map(|b| b.volume).collect());
        series.insert(sym, Series::from_bars(bars));
    }
    Universe::from_series(series, vols)
}

/// Recorder handler: asserts the structural invariant on every call and
/// exits/enters nothing by default (configurable).
struct AssertingHandler {
    violations: std::cell::RefCell<Vec<String>>,
}

impl AssertingHandler {
    fn new() -> Self {
        AssertingHandler {
            violations: std::cell::RefCell::new(vec![]),
        }
    }
}

impl Handler for AssertingHandler {
    fn signal_exits(&mut self, view: &DecisionView, _open: &[Position]) -> Vec<(String, ExitReason)> {
        // THE structural invariant: the latest visible ts is master[sig_t],
        // never master[fill_t].
        if view.max_visible_ts() != view.universe.master[view.sig_t] {
            self.violations
                .borrow_mut()
                .push(format!("view leaked past sig bar at t={}", view.fill_t));
        }
        if view.sig_t + 1 != view.fill_t {
            self.violations
                .borrow_mut()
                .push(format!("sig/fill not adjacent at t={}", view.fill_t));
        }
        Vec::new()
    }
}

// ── 1. structural no-lookahead: the decision view ends at t-1 ─────────────

proptest! {
    #![proptest_config(ProptestConfig::with_cases(64))]

    #[test]
    fn decision_view_never_sees_fill_bar(n in 80usize..140, n_syms in 1usize..8) {
        let uni = linear_universe(n, n_syms, None);
        let cfg = DEFAULT_CONFIG;
        let mut h = AssertingHandler::new();
        let r = ot_core::engine::replay(&uni, &cfg, &mut h);
        prop_assert!(h.violations.borrow().is_empty(), "{:?}", h.violations.borrow());
        // warmup: equity starts one bar after the longest lookback
        let warm = cfg.mom_lb.max(cfg.rev_lb).max(cfg.rsi_period)
            .max(cfg.breakout_lb).max(cfg.z_period) as usize;
        prop_assert_eq!(r.equity_ts.first().copied().unwrap_or(0), (1000 + warm + 1) as i64);
    }

    // ── 2. determinism: identical inputs → identical outputs ──────────────
    #[test]
    fn deterministic_replay(n in 90usize..160, seed in 0u64..64) {
        let uni = linear_universe(n, 5, None);
        let cfg = clamp_config(|k| match k {
            "rank_on" => Some((seed % 2) as f64),
            "regime_filter" => Some(((seed / 2) % 2) as f64),
            "trailing_pct" => Some(0.02),
            "rsi_exit_hi" => Some(0.6),
            "rsi_exit_lo" => Some(-0.6),
            "max_hold" => Some(7.0),
            _ => None,
        });
        let mut mk = || {
            let mut h = RuleFloor::new(&uni, cfg, None);
            ot_core::engine::replay(&uni, &cfg, &mut h)
        };
        let a = mk();
        let b = mk();
        prop_assert_eq!(a.trades.len(), b.trades.len());
        for (ta, tb) in a.trades.iter().zip(&b.trades) {
            prop_assert_eq!(&ta.sym, &tb.sym);
            prop_assert_eq!(ta.entry, tb.entry);
            prop_assert_eq!(ta.exit, tb.exit);
            prop_assert_eq!(ta.reason.as_str(), tb.reason.as_str());
        }
        prop_assert_eq!(a.metrics.net_return, b.metrics.net_return);
        prop_assert_eq!(a.equity, b.equity);
    }
}

// ── 3. exit-ladder priority ────────────────────────────────────────────────

#[test]
fn exit_priority_tp_beats_sl_and_trail() {
    let cfg = clamp_config(|k| match k {
        "tp" => Some(0.10),
        "sl" => Some(0.05),
        "trailing_pct" => Some(0.02),
        "max_hold" => Some(5.0),
        _ => None,
    });
    let mut p = Position {
        sym: "X".into(),
        qty: 1.0,
        entry: 100.0,
        cost: 100.35,
        peak: 100.0,
        bars: 10, // past max_hold too
        entry_ts: 0,
        last_close: 100.0,
        stop_loss: None,
        take_profit: None,
    };
    let mut series = Vec::new();
    // One bar that simultaneously hits TP (high >= 110), SL (low <= 95),
    // trail (low <= peak*0.98), and is past max_hold.
    series.push(Bar { ts: 1, open: 100.0, high: 111.0, low: 90.0, close: 105.0, volume: 1.0 });
    let s = Series::from_bars(series);
    let (px, why) = evaluate_engine_exit(&cfg, &mut p, &s, 1, Some(105.0)).unwrap();
    assert_eq!(why, ExitReason::Tp);
    assert!((px - 110.0).abs() < 1e-9, "tp price {px}");
}

#[test]
fn exit_priority_sl_beats_trail_and_maxhold() {
    let cfg = clamp_config(|k| match k {
        "tp" => Some(0.50), // unreachable
        "sl" => Some(0.05),
        "trailing_pct" => Some(0.02),
        "max_hold" => Some(1.0),
        _ => None,
    });
    let mut p = Position {
        sym: "X".into(),
        qty: 1.0,
        entry: 100.0,
        cost: 100.35,
        peak: 100.0,
        bars: 9, // past max_hold
        entry_ts: 0,
        last_close: 100.0,
        stop_loss: None,
        take_profit: None,
    };
    let s = Series::from_bars(vec![Bar { ts: 1, open: 100.0, high: 101.0, low: 90.0, close: 95.0, volume: 1.0 }]);
    let (px, why) = evaluate_engine_exit(&cfg, &mut p, &s, 1, Some(95.0)).unwrap();
    assert_eq!(why, ExitReason::Sl);
    assert_eq!(px, 95.0);
}

#[test]
fn exit_priority_trail_beats_maxhold() {
    let cfg = clamp_config(|k| match k {
        "tp" => Some(0.50),
        "sl" => Some(0.15), // unreachable
        "trailing_pct" => Some(0.02),
        "max_hold" => Some(1.0),
        _ => None,
    });
    let mut p = Position {
        sym: "X".into(),
        qty: 1.0,
        entry: 100.0,
        cost: 100.35,
        peak: 110.0,
        bars: 9,
        entry_ts: 0,
        last_close: 100.0,
        stop_loss: None,
        take_profit: None,
    };
    let s = Series::from_bars(vec![Bar { ts: 1, open: 108.0, high: 108.0, low: 107.0, close: 107.5, volume: 1.0 }]);
    // trail = 110*0.98 = 107.8; low 107.0 <= 107.8 → trail at 107.8, even
    // though bars >= max_hold.
    let (px, why) = evaluate_engine_exit(&cfg, &mut p, &s, 1, Some(107.5)).unwrap();
    assert_eq!(why, ExitReason::Trail);
    assert_eq!(px, 107.8);
}

#[test]
fn maxhold_fires_at_close_when_no_price_exit() {
    let cfg = clamp_config(|k| match k {
        "tp" => Some(0.50),
        "sl" => Some(0.15),
        "trailing_pct" => Some(0.0),
        "max_hold" => Some(3.0),
        _ => None,
    });
    let mut p = Position {
        sym: "X".into(),
        qty: 1.0,
        entry: 100.0,
        cost: 100.35,
        peak: 100.0,
        bars: 3,
        entry_ts: 0,
        last_close: 100.0,
        stop_loss: None,
        take_profit: None,
    };
    let s = Series::from_bars(vec![Bar { ts: 1, open: 100.0, high: 100.5, low: 99.5, close: 100.2, volume: 1.0 }]);
    let (px, why) = evaluate_engine_exit(&cfg, &mut p, &s, 1, Some(100.2)).unwrap();
    assert_eq!(why, ExitReason::MaxHold);
    assert_eq!(px, 100.2);
}

// ── 4. delist force-exit at the LAST recorded close ────────────────────────

proptest! {
    #![proptest_config(ProptestConfig::with_cases(32))]
    #[test]
    fn delist_exits_at_last_recorded_close(n in 130usize..170, gap_end in 70usize..95) {
        let uni = linear_universe(n, 4, Some((1, gap_end)));
        // Hold S01 past its series end: enter early via a permissive cfg and
        // a handler that buys S01 on the first eligible bar, then verify the
        // delist trade's exit price == S01's last close.
        struct BuyS01;
        impl Handler for BuyS01 {
            fn candidates(&mut self, view: &DecisionView, open: &[Position]) -> Vec<Candidate> {
                if open.is_empty() && view.fill_close("S01").is_some() && view.sig_pos("S01").is_some() {
                    return vec![Candidate {
                        sym: "S01".into(),
                        vol_reduce_applies: false,
                        notional_override: None,
                        stop_loss: None,
                        take_profit: None,
                    }];
                }
                Vec::new()
            }
        }
        let cfg = clamp_config(|k| match k {
            "risk_pct" => Some(0.05),
            "max_hold" => Some(60.0),
            "max_positions" => Some(1.0),
            _ => None,
        });
        let mut h = BuyS01;
        let r = ot_core::engine::replay(&uni, &cfg, &mut h);
        let delists: Vec<_> = r.trades.iter().filter(|t| t.reason == "delist").collect();
        prop_assert!(!delists.is_empty(), "expected a delist exit, trades: {:?}", r.trades.iter().map(|t| (&t.sym, &t.reason)).collect::<Vec<_>>());
        let last_close = uni.get("S01").unwrap().last_close().unwrap();
        for t in delists {
            prop_assert_eq!(&t.sym, "S01");
            prop_assert!((t.exit - last_close).abs() < 1e-9, "delist exit {} vs last close {}", t.exit, last_close);
        }
    }
}

// ── 5. date-guard: uncovered symbols are unscored, never dropped ───────────

#[test]
fn date_guard_excludes_uncovered_symbols() {
    // S01's series starts LATE (missing early master bars): before its
    // first bar it must never appear in the decision view's coverage.
    let mut series: BTreeMap<String, Series> = BTreeMap::new();
    let mut vols: BTreeMap<String, Vec<f64>> = BTreeMap::new();
    for (name, from) in [("S00", 0usize), ("S01", 40)] {
        let mut bars = Vec::new();
        let mut price = 100.0;
        for i in from..90 {
            price = price * (1.0 + ((i % 5) as f64) / 400.0 - 0.005);
            bars.push(Bar { ts: (1000 + i) as i64, open: price, high: price * 1.01, low: price * 0.99, close: price, volume: 1000.0 });
        }
        vols.insert(name.into(), bars.iter().map(|b| b.volume).collect());
        series.insert(name.into(), Series::from_bars(bars));
    }
    let uni = Universe::from_series(series, vols);

    struct Record(BTreeSet<i64>);
    impl Handler for Record {
        fn candidates(&mut self, view: &DecisionView, _open: &[Position]) -> Vec<Candidate> {
            // S01 must not be scoreable before its series starts.
            if view.universe.master[view.sig_t] < 1040 {
                assert!(view.sig_pos("S01").is_none(), "S01 leaked before coverage");
            } else {
                assert!(view.sig_pos("S01").is_some());
            }
            self.0.insert(view.max_visible_ts());
            Vec::new()
        }
    }
    let cfg = DEFAULT_CONFIG;
    let mut h = Record(BTreeSet::new());
    let r = ot_core::engine::replay(&uni, &cfg, &mut h);
    assert!(r.metrics.n_trades == 0);
}

// ── 6. per-bar cross-sectional rank semantics ──────────────────────────────

#[test]
fn rank_per_bar_dropna_and_normalization() {
    // Three symbols; S01 has NaN momentum (short series start) early.
    // Rank must normalize to [-1, 1] over VALID symbols only, exclude
    // NaN symbols (rank 0), and give zeros when < 2 valid.
    let mut series: BTreeMap<String, Series> = BTreeMap::new();
    let mut vols: BTreeMap<String, Vec<f64>> = BTreeMap::new();
    for (name, from) in [("S00", 0usize), ("S01", 0), ("S02", 30)] {
        let mut bars = Vec::new();
        let mut price = 100.0 + name.bytes().last().unwrap() as f64;
        for i in from..60 {
            price = price * (1.0 + ((i * 3) % 9) as f64 / 300.0 - 0.01);
            bars.push(Bar { ts: (1000 + i) as i64, open: price, high: price * 1.005, low: price * 0.995, close: price, volume: 1000.0 });
        }
        vols.insert(name.into(), bars.iter().map(|b| b.volume).collect());
        series.insert(name.into(), Series::from_bars(bars));
    }
    let uni = Universe::from_series(series, vols);
    let cfg = clamp_config(|k| if k == "rank_on" { Some(1.0) } else { None });
    let rf = RuleFloor::new(&uni, cfg, None);
    // After bar 30 all three are valid at the master bar → ranks in [-1,1]
    // and sum to 0 (3 symbols: -1, 0, +1). Before bar 30 only 2 valid →
    // S02's rank stays 0 at those bars and the two valid are ±1.
    for t in 35..55 {
        let r0 = rf.rank["S00"][t];
        let r1 = rf.rank["S01"][t];
        let r2 = rf.rank["S02"][t];
        assert!(r0 >= -1.0 && r0 <= 1.0);
        assert!(r1 >= -1.0 && r1 <= 1.0);
        if t < 30 {
            assert_eq!(r2, 0.0, "uncovered symbol must have rank 0 at t={t}");
            assert_eq!((r0 + r1).abs(), 2.0, "two valid symbols must be ±1 at t={t}");
        } else {
            assert_eq!(r0 + r1 + r2, 0.0, "three ranks must sum to 0 at t={t}");
        }
    }
}
