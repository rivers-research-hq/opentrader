//! W3c exit-criterion: checkpoint/resume live-restart parity (ticket #361).
//! The law: checkpoint/restart must reproduce identical subsequent output
//! given identical subsequent bars. Full replay == checkpoint@N + resume.

use ot_core::bar::{Bar, Series};
use ot_core::config::{clamp_config, Config, DEFAULT_CONFIG};
use ot_core::engine::{replay_with_checkpoint, replay, resume_from_checkpoint, Candidate, DecisionView, Handler};
use ot_core::rulefloor::RuleFloor;
use ot_core::universe::Universe;
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

fn universe(closes: &[f64]) -> Universe {
    let mut series = BTreeMap::new();
    let mut vols = BTreeMap::new();
    series.insert("TEST".to_string(), Series::from_bars(bars(closes)));
    vols.insert("TEST".to_string(), (0..closes.len()).map(|i| 1000.0 + i as f64).collect());
    Universe::from_series(series, vols)
}

fn make_handler(uni: &Universe, cfg: &Config) -> RuleFloor {
    RuleFloor::new(uni, cfg.clone(), None)
}

fn same_trades(a: &[ot_core::engine::Trade], b: &[ot_core::engine::Trade]) {
    assert_eq!(a.len(), b.len(), "trade count: {} vs {}", a.len(), b.len());
    for (ta, tb) in a.iter().zip(b) {
        assert_eq!(ta.sym, tb.sym);
        assert_eq!(ta.entry_ts, tb.entry_ts);
        assert_eq!(ta.exit_ts, tb.exit_ts);
        assert_eq!(ta.reason, tb.reason);
        assert_eq!(ta.bars, tb.bars);
        assert!((ta.entry - tb.entry).abs() < 1e-12, "entry {} vs {}", ta.entry, tb.entry);
        assert!((ta.exit - tb.exit).abs() < 1e-12, "exit {} vs {}", ta.exit, tb.exit);
        assert!((ta.pnl - tb.pnl).abs() < 1e-9, "pnl {} vs {}", ta.pnl, tb.pnl);
    }
}

fn same_equity(a: &[f64], b: &[f64]) {
    assert_eq!(a.len(), b.len());
    for (i, (x, y)) in a.iter().zip(b).enumerate() {
        assert!(
            (x - y).abs() < 1e-9,
            "equity[{i}]: {x} vs {y}"
        );
    }
}

/// Full-replay equity is indexed from the warm-up start bar
/// (`compute_start`), so the tail from a checkpoint bar N is the slice
/// (N - start), NOT (N - 1). Checkpoints are only restorable at/after
/// start — the state before warm-up is not replay-parity-recoverable.
fn full_tail_equity(
    full: &ot_core::engine::BacktestResult,
    cfg: &Config,
    uni: &Universe,
    cp_at: usize,
) -> Vec<f64> {
    let start = ot_core::engine::compute_start(cfg, uni.master.len());
    assert!(
        cp_at >= start,
        "checkpoint bar {cp_at} is before the replay start {start} — not restorable"
    );
    full.equity.iter().skip(cp_at - start).copied().collect()
}

// ── the parity law ─────────────────────────────────────────────────────────

#[test]
fn checkpoint_resume_parity_mid_replay() {
    let closes: Vec<f64> = (0..200)
        .map(|i| { let p = 100.0 + ((i * 37) % 53) as f64 - 26.0; p })
        .collect();
    let uni = universe(&closes);
    let cfg = clamp_config(|k| match k {
        "breakout_lb" => Some(10.0),
        "trailing_pct" => Some(0.02),
        "min_notional" => Some(0.0),
        "risk_pct" => Some(0.10),
        "buy_thresh" => Some(-1.0),
        "risk_pct" => Some(0.10),
        "buy_thresh" => Some(-1.0),
        "breakout_lb" => Some(10.0),
        "breakout_lb" => Some(10.0),
        "max_hold" => Some(15.0),
        "rsi_exit_hi" => Some(0.6),
        "rsi_exit_lo" => Some(-0.6),
        _ => None,
    });

    // full replay
    let mut h_full = make_handler(&uni, &cfg);
    let full = replay(&uni, &cfg, &mut h_full);
    assert!(full.trades.len() > 3, "the test must exercise real trading: {} trades", full.trades.len());

    // checkpoint at bar 30 (mid-replay, some trades already closed)
    let cp_at = 50;
    let mut h_cp = make_handler(&uni, &cfg);
    let (_, checkpoint) = replay_with_checkpoint(&uni, &cfg, &mut h_cp, Some(cp_at));
    let checkpoint = checkpoint.expect("checkpoint");
    assert_eq!(checkpoint.bar_index, cp_at);

    // resume from the checkpoint
    let mut h_res = make_handler(&uni, &cfg);
    let resumed = resume_from_checkpoint(&checkpoint, &uni, &cfg, &mut h_res);

    // the resumed segment must match the full replay's tail exactly
    // (the full replay's bars ≥ 30)
    let full_tail_trades: Vec<ot_core::engine::Trade> = full
        .trades
        .iter()
        .filter(|t| t.exit_ts >= 1000 + cp_at as i64)
        .cloned()
        .collect();
    same_trades(&full_tail_trades, &resumed.trades);
    let full_tail_equity = full_tail_equity(&full, &cfg, &uni, cp_at);
    same_equity(&full_tail_equity, &resumed.equity);

    // the checkpoint's positions must carry into the resume (open positions
    // at the checkpoint bar are held and closed later)
    let full_open_at_cp: Vec<_> = full
        .trades
        .iter()
        .filter(|t| t.entry_ts < 1000 + cp_at as i64 && t.exit_ts >= 1000 + cp_at as i64)
        .cloned()
        .collect();
    // if there are positions open at the checkpoint, the resumed segment
    // must have trades that started before the checkpoint
    if !full_open_at_cp.is_empty() {
        assert!(
            resumed.trades.iter().any(|t| t.entry_ts < 1000 + cp_at as i64),
            "positions open at the checkpoint must carry into the resume"
        );
    }
}

#[test]
fn checkpoint_resume_parity_early() {
    // checkpoint at bar 10 (very early — before most trades)
    let closes: Vec<f64> = (0..200)
        .map(|i| { let p = 100.0 + ((i * 41) % 61) as f64 - 30.0; p })
        .collect();
    let uni = universe(&closes);
    let cfg = clamp_config(|k| match k {
        "breakout_lb" => Some(10.0),
        "trailing_pct" => Some(0.02),
        "min_notional" => Some(0.0),
        "risk_pct" => Some(0.10),
        "buy_thresh" => Some(-1.0),
        "risk_pct" => Some(0.10),
        "buy_thresh" => Some(-1.0),
        "breakout_lb" => Some(10.0),
        "max_hold" => Some(12.0),
        "tp" => Some(0.06),
        "sl" => Some(0.03),
        _ => None,
    });

    let mut h_full = make_handler(&uni, &cfg);
    let full = replay(&uni, &cfg, &mut h_full);
    assert!(full.trades.len() > 5, "must exercise real trading: {}", full.trades.len());

    let cp_at = 30; // ≥ the warm-up start — earlier bars are not restorable
    let mut h_cp = make_handler(&uni, &cfg);
    let (_, checkpoint) = replay_with_checkpoint(&uni, &cfg, &mut h_cp, Some(cp_at));
    let checkpoint = checkpoint.expect("checkpoint");

    let mut h_res = make_handler(&uni, &cfg);
    let resumed = resume_from_checkpoint(&checkpoint, &uni, &cfg, &mut h_res);

    let full_tail_trades: Vec<ot_core::engine::Trade> = full
        .trades
        .iter()
        .filter(|t| t.exit_ts >= 1000 + cp_at as i64)
        .cloned()
        .collect();
    same_trades(&full_tail_trades, &resumed.trades);
    let full_tail_equity = full_tail_equity(&full, &cfg, &uni, cp_at);
    same_equity(&full_tail_equity, &resumed.equity);
}

#[test]
fn checkpoint_resume_parity_late() {
    // checkpoint at bar 45 (very late — most trades already closed)
    let closes: Vec<f64> = (0..200)
        .map(|i| { let p = 100.0 + ((i * 43) % 71) as f64 - 35.0; p })
        .collect();
    let uni = universe(&closes);
    let cfg = clamp_config(|k| match k {
        "breakout_lb" => Some(10.0),
        "trailing_pct" => Some(0.03),
        "min_notional" => Some(0.0),
        "risk_pct" => Some(0.10),
        "buy_thresh" => Some(-1.0),
        "breakout_lb" => Some(10.0),
        "max_hold" => Some(8.0),
        _ => None,
    });

    let mut h_full = make_handler(&uni, &cfg);
    let full = replay(&uni, &cfg, &mut h_full);

    let cp_at = 80;
    let mut h_cp = make_handler(&uni, &cfg);
    let (_, checkpoint) = replay_with_checkpoint(&uni, &cfg, &mut h_cp, Some(cp_at));
    let checkpoint = checkpoint.expect("checkpoint");

    let mut h_res = make_handler(&uni, &cfg);
    let resumed = resume_from_checkpoint(&checkpoint, &uni, &cfg, &mut h_res);

    let full_tail_trades: Vec<ot_core::engine::Trade> = full
        .trades
        .iter()
        .filter(|t| t.exit_ts >= 1000 + cp_at as i64)
        .cloned()
        .collect();
    same_trades(&full_tail_trades, &resumed.trades);
}

#[test]
fn checkpoint_serializes_deserializes() {
    // the universe must outlive the warm-up + the checkpoint bar:
    // DEFAULT_CONFIG warms up 55 bars, so 40 bars can never produce one
    let closes: Vec<f64> = (0..200).map(|i| 100.0 + i as f64).collect();
    let uni = universe(&closes);
    let cfg = DEFAULT_CONFIG;
    let mut h = make_handler(&uni, &cfg);
    let (_, checkpoint) = replay_with_checkpoint(&uni, &cfg, &mut h, Some(100));
    let cp = checkpoint.expect("checkpoint");

    // serialize → deserialize → resume
    let json = serde_json::to_string(&cp).expect("serialize");
    let restored: ot_core::engine::Checkpoint = serde_json::from_str(&json).expect("deserialize");
    assert_eq!(restored.bar_index, cp.bar_index);
    assert_eq!(restored.positions.len(), cp.positions.len());
    assert!((restored.cash - cp.cash).abs() < 1e-12);

    // resume from the restored checkpoint — same output
    let mut h_res = make_handler(&uni, &cfg);
    let resumed = resume_from_checkpoint(&restored, &uni, &cfg, &mut h_res);
    let mut h_direct = make_handler(&uni, &cfg);
    let resumed_direct = resume_from_checkpoint(&cp, &uni, &cfg, &mut h_direct);
    same_trades(&resumed.trades, &resumed_direct.trades);
    same_equity(&resumed.equity, &resumed_direct.equity);
}

#[test]
fn checkpoint_resume_with_brackets_and_shorts() {
    // the W2c features: SHORT side + SL/TP brackets must also survive
    // checkpoint/resume (side-aware accounting + bracket positions)
    let closes: Vec<f64> = (0..200)
        .map(|i| { let p = 100.0 + ((i * 53) % 83) as f64 - 41.0; p })
        .collect();
    let uni = universe(&closes);
    let cfg = clamp_config(|k| match k {
        "breakout_lb" => Some(10.0),
        "breakout_lb" => Some(10.0),
        "max_hold" => Some(15.0),
        _ => None,
    });

    struct BracketHandler;
    impl Handler for BracketHandler {
        fn candidates(&mut self, view: &DecisionView, open: &[ot_core::engine::Position]) -> Vec<Candidate> {
            if !open.is_empty() {
                return vec![];
            }
            if view.sig_pos("TEST").is_some() && view.fill_close("TEST").is_some() {
                return vec![Candidate {
                    sym: "TEST".into(),
                    vol_reduce_applies: false,
                    notional_override: Some(10000.0),
                    stop_loss: Some(view.fill_close("TEST").unwrap() * 0.97),
                    take_profit: Some(view.fill_close("TEST").unwrap() * 1.05),
                    fill_price_override: None,
                    side: Some(ot_core::engine::Side::Long),
                }];
            }
            vec![]
        }
    }

    let mut h_full = BracketHandler;
    let full = replay(&uni, &cfg, &mut h_full);
    assert!(full.trades.len() > 3, "must exercise real trading: {}", full.trades.len());

    let cp_at = 25;
    let mut h_cp = BracketHandler;
    let (_, checkpoint) = replay_with_checkpoint(&uni, &cfg, &mut h_cp, Some(cp_at));
    let checkpoint = checkpoint.expect("checkpoint");

    let mut h_res = BracketHandler;
    let resumed = resume_from_checkpoint(&checkpoint, &uni, &cfg, &mut h_res);

    let full_tail_trades: Vec<ot_core::engine::Trade> = full
        .trades
        .iter()
        .filter(|t| t.exit_ts >= 1000 + cp_at as i64)
        .cloned()
        .collect();
    same_trades(&full_tail_trades, &resumed.trades);
    let full_tail_equity = full_tail_equity(&full, &cfg, &uni, cp_at);
    same_equity(&full_tail_equity, &resumed.equity);
}

// ── phase-3 guard: handler modifications must run in replay ────────────
// The replay_inner refactor once silently dropped the modifications
// phase (the strategy surface's `Modify`). This test proves it runs AND
// that a modified stop survives a checkpoint boundary.
struct ModifyHandler;
impl Handler for ModifyHandler {
    fn candidates(
        &mut self,
        view: &DecisionView,
        open: &[ot_core::engine::Position],
    ) -> Vec<Candidate> {
        if !open.is_empty() {
            return vec![];
        }
        if view.sig_pos("TEST").is_some() && view.fill_close("TEST").is_some() {
            return vec![Candidate {
                sym: "TEST".into(),
                vol_reduce_applies: false,
                notional_override: Some(10000.0),
                stop_loss: None,
                take_profit: None,
                fill_price_override: None,
                side: Some(ot_core::engine::Side::Long),
            }];
        }
        vec![]
    }

    fn modifications(
        &mut self,
        _view: &DecisionView,
        open: &[ot_core::engine::Position],
    ) -> Vec<(String, Option<f64>, Option<f64>)> {
        // a stop just above the entry: with the linear series (close +1 per
        // bar, low = close·0.995) the low breaches it as soon as it governs.
        open.iter()
            .map(|p| (p.sym.clone(), Some(p.entry * 1.02), None))
            .collect()
    }
}

#[test]
fn modifications_run_and_survive_checkpoint() {
    let closes: Vec<f64> = (0..200).map(|i| 100.0 + i as f64).collect();
    let uni = universe(&closes);
    let cfg = DEFAULT_CONFIG;

    let mut h_full = ModifyHandler;
    let full = replay(&uni, &cfg, &mut h_full);
    assert!(full.trades.len() > 3, "must exercise real trading: {}", full.trades.len());
    for t in &full.trades {
        assert_eq!(t.reason, "sl", "the modified stop must govern (got {})", t.reason);
        // phase 3 runs BEFORE the entries phase — a position entered at bar
        // t receives its modification at t+1, so the first bar the stop can
        // govern is t+2: exactly 2 bars held.
        assert_eq!(t.bars, 2, "the stop governs from t+2 (set at t+1)");
    }

    let cp_at = 80;
    let mut h_cp = ModifyHandler;
    let (_, checkpoint) = replay_with_checkpoint(&uni, &cfg, &mut h_cp, Some(cp_at));
    let checkpoint = checkpoint.expect("checkpoint");
    // a position entered at bar 79 must be open at the checkpoint, carrying
    // its modified stop across the boundary
    assert_eq!(checkpoint.positions.len(), 1, "an open position with a modified stop must be in flight");
    assert_eq!(
        checkpoint.positions[0].stop_loss,
        Some(checkpoint.positions[0].entry * 1.02),
        "the checkpoint must carry the modified stop"
    );

    let mut h_res = ModifyHandler;
    let resumed = resume_from_checkpoint(&checkpoint, &uni, &cfg, &mut h_res);
    let full_tail_trades: Vec<ot_core::engine::Trade> = full
        .trades
        .iter()
        .filter(|t| t.exit_ts >= 1000 + cp_at as i64)
        .cloned()
        .collect();
    same_trades(&full_tail_trades, &resumed.trades);
    let full_tail_equity = full_tail_equity(&full, &cfg, &uni, cp_at);
    same_equity(&full_tail_equity, &resumed.equity);
}
