//! The rule-floor strategy — verbatim port of V1 `_score_at`,
//! `_cross_sectional_rank`, and the entry/exit gating in `run_backtest`.
//! This is the reference handler proving the engine contract carries V1's
//! semantics exactly (parity fixture test).
//!
//! V1 sequencing (mirrored exactly):
//!   1. per bar: bar_feat (date-guard) + scores computed ONCE from the
//!      signal-bar view;
//!   2. the exit loop consults those scores per held symbol
//!      (`scores.get(s, 0.0) < sell_thresh` — default 0.0 — then rsi gates
//!      with `bar_feat.get(s, {}).get("rsi", 0.0)` default 0.0);
//!   3. candidates computed after the full exit loop, excluding post-exit
//!      holdings (same-bar re-entry allowed), sorted score-descending with
//!      Python's NaN-last behavior.

use crate::config::Config;
use crate::engine::{Candidate, DecisionView, ExitReason, Handler};
use crate::features::{compute_features, FeatureRow, Features, NAN};
use crate::universe::Universe;
use std::collections::BTreeMap;

/// Precomputed per-symbol causal features + the cross-sectional rank
/// series + the regime means (SPY rolling mean; NaN → regime false).
pub struct RuleFloor {
    cfg: Config,
    pub feats: BTreeMap<String, Features>,
    /// Cross-sectional rank per symbol, indexed by MASTER position
    /// (V1 `rank[s][sig_t]`): value in [-1, 1] over valid symbols that
    /// bar, 0 otherwise.
    pub rank: BTreeMap<String, Vec<f64>>,
    /// SPY rolling-mean series (regime = SPY close > mean at sig bar).
    pub regime: Option<Vec<f64>>,
    /// Optional macro gate keyed by master ts (entry only when true).
    pub macro_gate: Option<BTreeMap<i64, bool>>,
    /// Per-bar memo shared by the two handler phases.
    memo: Option<BarScores>,
}

#[derive(Clone)]
struct BarScores {
    sig_t: usize,
    sig_ts: i64,
    /// (sym, sig_series_pos, row) for symbols covering the signal bar.
    bar_feat: Vec<(String, usize, FeatureRow)>,
    scores: BTreeMap<String, f64>,
}

impl RuleFloor {
    pub fn new(universe: &Universe, cfg: Config, macro_gate: Option<BTreeMap<i64, bool>>) -> Self {
        let feats: BTreeMap<String, Features> = universe
            .series
            .iter()
            .map(|(s, ser)| {
                let vols = universe.vols.get(s);
                (
                    s.clone(),
                    compute_features(ser, vols.map(|v| v.as_slice()), &cfg),
                )
            })
            .collect();

        let rank: BTreeMap<String, Vec<f64>> = if cfg.rank_on {
            cross_sectional_rank(universe, &feats)
        } else {
            BTreeMap::new()
        };

        let regime = if cfg.regime_filter {
            universe.get("SPY").map(|spy| {
                let closes: Vec<f64> = spy.bars().iter().map(|b| b.close).collect();
                crate::features::rolling_mean(
                    &closes,
                    cfg.regime_window as usize,
                    10, // min_periods=10, verbatim
                )
            })
        } else {
            None
        };

        RuleFloor {
            cfg,
            feats,
            rank,
            regime,
            macro_gate,
            memo: None,
        }
    }

    /// V1 `_score_at`: weighted blend; NaN propagates (Python NaN
    /// comparison semantics handled at the call sites).
    fn score_at(&self, row: &FeatureRow, sig_t_rank: f64) -> f64 {
        let c = &self.cfg;
        let r = if c.rank_on { sig_t_rank } else { 0.0 };
        c.w_mom * row.mom
            + c.w_rev * row.rev
            + c.w_rsi * row.rsi
            + c.w_brk * row.brk
            + c.w_z * row.z
            + c.w_rank * r
    }

    /// V1's per-bar computation: bar_feat (date-guard) + scores — memoized
    /// per signal bar so the two handler phases share it.
    fn bar_scores(&mut self, view: &DecisionView) -> BarScores {
        let sig_t = view.sig_t;
        let sig_ts = view.universe.master[sig_t];
        if let Some(m) = &self.memo {
            if m.sig_t == sig_t {
                return BarScores {
                    sig_t: m.sig_t,
                    sig_ts: m.sig_ts,
                    bar_feat: m.bar_feat.clone(),
                    scores: m.scores.clone(),
                };
            }
        }
        let mut bar_feat: Vec<(String, usize, FeatureRow)> = Vec::new();
        for sym in view.universe.series.keys() {
            if let Some(p) = view.sig_pos(sym) {
                if let Some(row) = self.feats.get(sym).and_then(|f| f.row(p)) {
                    bar_feat.push((sym.clone(), p, *row));
                }
            }
        }
        let scores: BTreeMap<String, f64> = bar_feat
            .iter()
            .map(|(s, _, row)| {
                let r = if self.cfg.rank_on {
                    self.rank
                        .get(s)
                        .and_then(|v| v.get(sig_t))
                        .copied()
                        .unwrap_or(0.0)
                } else {
                    0.0
                };
                (s.clone(), self.score_at(row, r))
            })
            .collect();
        let m = BarScores {
            sig_t,
            sig_ts,
            bar_feat,
            scores,
        };
        self.memo = Some(m.clone());
        m
    }

    fn regime_ok(&self, view: &DecisionView) -> bool {
        match &self.regime {
            None => true, // V1: regime None (no SPY or filter off) → True
            Some(means) => {
                let Some(spy) = view.universe.get("SPY") else {
                    return false;
                };
                let Some(p) = spy.pos(view.universe.master[view.sig_t]) else {
                    return false;
                };
                let mean = means.get(p).copied().unwrap_or(NAN);
                let close = spy.bars().get(p).map(|b| b.close).unwrap_or(NAN);
                // NaN comparisons are False → regime False (fillna(False))
                close > mean
            }
        }
    }

    fn macro_ok(&self, sig_ts: i64) -> bool {
        match &self.macro_gate {
            None => true,
            Some(g) => g.get(&sig_ts).copied().unwrap_or(false),
        }
    }
}

impl Handler for RuleFloor {
    fn signal_exits(&mut self, view: &DecisionView, open: &[crate::engine::Position]) -> Vec<(String, ExitReason)> {
        let c = self.cfg.clone();
        let m = self.bar_scores(view);
        let mut out = Vec::new();
        for held in open.iter().map(|p| &p.sym) {
            // V1: signal exit uses scores.get(s, 0.0) — default 0.0 (NOT
            // the -99 that candidates use). A held symbol that lost
            // signal-bar coverage scores 0.0 → no signal exit at
            // sell_thresh −0.2.
            let sc = m.scores.get(held).copied().unwrap_or(0.0);
            let mut exited = false;
            if let Some(st) = c.sell_thresh {
                // NaN < thresh is False in Python → no signal exit
                if !sc.is_nan() && sc < st {
                    out.push((held.clone(), ExitReason::Signal));
                    exited = true;
                }
            }
            if !exited && (c.rsi_exit_hi > 0.0 || c.rsi_exit_lo > 0.0) {
                // V1: bar_feat.get(s, {}).get("rsi", 0.0) — missing → 0.0
                let rsi_v = m
                    .bar_feat
                    .iter()
                    .find(|(s, _, _)| s == held)
                    .map(|(_, _, r)| r.rsi)
                    .unwrap_or(0.0);
                // NaN comparisons are False → no rsi exit on NaN
                if (c.rsi_exit_hi > 0.0 && rsi_v > c.rsi_exit_hi)
                    || (c.rsi_exit_lo > 0.0 && rsi_v < c.rsi_exit_lo)
                {
                    out.push((held.clone(), ExitReason::RsiExit));
                }
            }
        }
        out
    }

    fn candidates(&mut self, view: &DecisionView, open_syms: &[crate::engine::Position]) -> Vec<Candidate> {
        let c = self.cfg.clone();
        let m = self.bar_scores(view);
        if m.bar_feat.is_empty() {
            return Vec::new();
        }
        let regime_ok = self.regime_ok(view);
        let macro_ok = self.macro_ok(m.sig_ts);

        let mut out = Vec::new();
        for (sym, _sig_pos, row) in &m.bar_feat {
            if open_syms.iter().any(|h| &h.sym == sym) {
                continue;
            }
            // V1 candidates default: scores.get(s, -99) — but every
            // candidate IS in bar_feat, so scores always contain it.
            let sc = m.scores.get(sym).copied().unwrap_or(-99.0);
            // V1 quirk: `if sc < buy_thresh: continue` — NaN < thresh is
            // False in Python, so NaN-scored symbols are NOT skipped.
            if !sc.is_nan() && sc < c.buy_thresh {
                continue;
            }
            if !regime_ok {
                continue;
            }
            if !macro_ok {
                continue;
            }
            let fill_close = view.fill_close(sym).unwrap_or(0.0);
            if fill_close <= 0.0 {
                continue;
            }
            // Research-feature entry gates (disabled when param is 0);
            // NaN gate values compare False → gate passes (V1 semantics).
            if c.ma_reject_n > 0 && row.ma_dist > c.ma_reject_pct {
                continue;
            }
            if c.vol_spike_n > 0 && row.vol_spike > c.vol_spike_mult {
                continue;
            }
            if c.rsi_filter_n > 0 {
                if row.rsi > c.rsi_filter_hi || row.rsi < c.rsi_filter_lo {
                    continue;
                }
            }
            if c.mom_filter_n > 0 {
                if row.momfilt > c.mom_filter_max || row.momfilt < c.mom_filter_min {
                    continue;
                }
            }
            let vol_reduce_applies = c.vol_reduce_n > 0 && row.vol_level > c.vol_reduce_thr;
            out.push(Candidate {
                sym: sym.clone(),
                vol_reduce_applies,
                notional_override: None,
                stop_loss: None,
                take_profit: None,
                fill_price_override: None,
                side: None,
            });
        }
        // V1: candidates.sort(key=lambda x: -x[1]) — Python's sort sends
        // NaN keys LAST (every comparison with NaN is False). Stable sort
        // with a nan-last comparator reproduces that exactly; ties keep
        // sorted-symbol order.
        let mut keyed: Vec<(Candidate, f64)> = out
            .into_iter()
            .map(|cd| {
                let sc = m.scores.get(&cd.sym).copied().unwrap_or(-99.0);
                (cd, sc)
            })
            .collect();
        keyed.sort_by(|a, b| match (a.1.is_nan(), b.1.is_nan()) {
            (true, false) => std::cmp::Ordering::Greater,
            (false, true) => std::cmp::Ordering::Less,
            _ => b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal),
        });
        keyed.into_iter().map(|(cd, _)| cd).collect()
    }
}

/// V1 `_cross_sectional_rank`: per bar, rank the symbols with a valid
/// momentum value THIS bar; normalized to [-1, 1]; symbols with NaN get
/// rank 0 and are not candidates; < 2 valid → all 0. (The 9b7301a lesson:
/// per-bar dropna, never column-wise.) Stored on the MASTER index.
fn cross_sectional_rank(
    universe: &Universe,
    feats: &BTreeMap<String, Features>,
) -> BTreeMap<String, Vec<f64>> {
    let master = &universe.master;
    let syms: Vec<String> = universe.series.keys().cloned().collect();
    let mut rank: BTreeMap<String, Vec<f64>> =
        syms.iter().map(|s| (s.clone(), vec![0.0; master.len()])).collect();
    if syms.len() < 2 {
        return rank; // V1: frame.shape[1] < 2 → zeros
    }
    for t in 0..master.len() {
        let ts = master[t];
        // valid = per-bar dropna of momentum at this master bar
        let mut valid: Vec<(String, f64)> = Vec::new();
        for s in &syms {
            let Some(ser) = universe.get(s) else { continue };
            let Some(p) = ser.pos(ts) else { continue };
            let mo = feats
                .get(s)
                .and_then(|f| f.rows.get(p))
                .map(|r| r.mom)
                .unwrap_or(NAN);
            if !mo.is_nan() {
                valid.push((s.clone(), mo));
            }
        }
        if valid.len() < 2 {
            continue;
        }
        // argsort().argsort() → competition rank 0..n-1 (ties: numpy's
        // argsort is unstable, but tied momentum values are measure-zero
        // on real data; stable-sort ties keep sorted-symbol order here).
        let mut order: Vec<usize> = (0..valid.len()).collect();
        let mut key: Vec<(usize, f64)> = (0..valid.len()).map(|i| (i, valid[i].1)).collect();
        key.sort_by(|a, b| a.1.partial_cmp(&b.1).unwrap_or(std::cmp::Ordering::Equal));
        for (place, (idx, _)) in key.iter().enumerate() {
            order[*idx] = place;
        }
        let denom = (valid.len() as f64 - 1.0).max(1.0);
        for (i, (s, _)) in valid.iter().enumerate() {
            rank.get_mut(s).unwrap()[t] = (order[i] as f64 / denom) * 2.0 - 1.0;
        }
    }
    rank
}
