//! The engine — deterministic event-driven replay with the structural
//! no-lookahead contract.
//!
//! Events are `BarClose(ts)` in master order. On event at master position
//! `t`, the engine hands the handler a [`DecisionView`] truncated to the
//! SIGNAL bar `t-1` (structural guarantee — the handler cannot observe bar
//! `t` while deciding), then evaluates the exit ladder and fills at bar
//! `t`'s close. Ladder priority is verbatim V1:
//!   delist → tp → sl → trail → max_hold → signal → rsi_exit,
//! with delist force-exit (symbol's series ended) at the symbol's last
//! recorded close.
//!
//! Backtest/live parity: backtest drives [`Handler`] from replayed events;
//! the live driver (W1+) drives the same handler from venue streams.

use crate::bar::Series;
use crate::config::{fee_amt, Config};
use crate::universe::Universe;

/// The structural contract constant: the decision view at master position
/// `t` ends at `t-1`. Exported so tests and the live driver assert the same
/// invariant.
pub const DECISION_VIEW_END_EXCLUSIVE: usize = 1;

#[derive(Debug, Clone, serde::Serialize)]
pub struct Trade {
    pub sym: String,
    pub entry: f64,
    pub exit: f64,
    pub pnl: f64,
    pub pnl_pct: f64,
    pub bars: i64,
    pub reason: String,
    pub entry_ts: i64,
    pub exit_ts: i64,
}

#[derive(Debug, Clone, Copy, Default, serde::Serialize)]
pub struct Metrics {
    pub net_return: f64,
    pub ann_sharpe: f64,
    pub max_drawdown: f64,
    pub win_rate: f64,
    pub n_trades: usize,
    pub total_fees: f64,
    pub fee_ratio: f64,
    pub profit_factor: f64,
    pub avg_hold: f64,
    pub final_equity: f64,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct BacktestResult {
    pub metrics: Metrics,
    pub trades: Vec<Trade>,
    pub equity_ts: Vec<i64>,
    pub equity: Vec<f64>,
}

/// Open position book entry.
#[derive(Debug, Clone)]
pub struct Position {
    pub sym: String,
    pub qty: f64,
    pub entry: f64,
    pub cost: f64,
    pub peak: f64,
    pub bars: i64,
    pub entry_ts: i64,
    /// Fallback equity mark when a bar is missing (V1 would KeyError; V2
    /// documents the robustness fix and marks at the last recorded close).
    pub last_close: f64,
    /// Strategy-surface brackets (absolute prices) — take precedence over
    /// the cfg-percentage ladder when set.
    pub stop_loss: Option<f64>,
    pub take_profit: Option<f64>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ExitReason {
    Tp,
    Sl,
    Trail,
    MaxHold,
    Signal,
    RsiExit,
    Delist,
}

impl ExitReason {
    pub fn as_str(&self) -> &'static str {
        match self {
            ExitReason::Tp => "tp",
            ExitReason::Sl => "sl",
            ExitReason::Trail => "trail",
            ExitReason::MaxHold => "max_hold",
            ExitReason::Signal => "signal",
            ExitReason::RsiExit => "rsi_exit",
            ExitReason::Delist => "delist",
        }
    }
}

/// A pre-gated, pre-sorted entry candidate the handler emits (V1's
/// `candidates` list): engine performs sizing/fees/exposure/cash checks.
#[derive(Debug, Clone)]
pub struct Candidate {
    pub sym: String,
    /// True when the handler's sizing gate (vol_level > vol_reduce_thr)
    /// applies at the signal bar → notional scaled by vol_reduce_frac.
    pub vol_reduce_applies: bool,
    /// Explicit notional (strategy-surface entries: `size` units × fill
    /// close) — overrides risk_pct sizing when Some.
    pub notional_override: Option<f64>,
    /// Per-position protective brackets riding the entry (strategy
    /// surface): absolute prices, checked in the exit ladder with the V1
    /// same-bar discipline. None → the cfg-percentage ladder applies.
    pub stop_loss: Option<f64>,
    pub take_profit: Option<f64>,
}

/// One decision at bar `t` (view = bars ≤ t-1): handler-level exits
/// (signal/rsi — engine-level exits are automatic) and entries.
/// What the handler sees when deciding at master position `t`: data through
/// the SIGNAL bar `t-1` only. This is the structural no-lookahead boundary.
pub struct DecisionView<'a> {
    pub universe: &'a Universe,
    /// Master position of the signal bar (t-1).
    pub sig_t: usize,
    /// Master position of the fill bar (t).
    pub fill_t: usize,
}

impl<'a> DecisionView<'a> {
    /// The latest ts the handler may use — verbatim `master[t-1]`.
    pub fn max_visible_ts(&self) -> i64 {
        self.universe.master[self.sig_t]
    }

    /// Symbol's series position of the signal bar (date-guard lookup,
    /// V1's `sig_idx in feat[s].index`).
    pub fn sig_pos(&self, sym: &str) -> Option<usize> {
        self.universe.get(sym)?.pos(self.universe.master[self.sig_t])
    }

    /// Symbol's close at the FILL bar (`idx in closes[s].index`).
    pub fn fill_close(&self, sym: &str) -> Option<f64> {
        self.universe
            .get(sym)?
            .get(self.universe.master[self.fill_t])
            .map(|b| b.close)
    }
}

/// Strategy handler — the decision layer. Live and backtest use the same
/// trait (parity invariant). Two phases mirror V1's exact sequencing:
/// scores are computed ONCE per bar (from the signal-bar view) and drive
/// BOTH the in-loop signal/rsi exits and the post-exit-loop candidates.
pub trait Handler {
    /// Phase 1 — called BEFORE the exit loop. Returns handler-level exits
    /// (signal/rsi) for currently-held symbols, keyed by symbol. V1 checks
    /// `scores.get(s, 0.0) < sell_thresh` (default 0.0) and the rsi gates
    /// inside the exit loop, in insertion order — the engine consults this
    /// map per position in exactly that order. Handlers see full positions
    /// (age, brackets) — the strategy surface's MaxHold reads `bars`.
    fn signal_exits(&mut self, _view: &DecisionView, _open: &[Position]) -> Vec<(String, ExitReason)> {
        Vec::new()
    }

    /// Phase 2 — called AFTER the full exit loop (engine + signal exits
    /// applied). V1 computes candidates from the SAME scores, excluding
    /// post-exit holdings — so a symbol exited this bar (either way) is
    /// re-eligible in the same bar. Pre-gated, pre-sorted, score-descending.
    fn candidates(&mut self, _view: &DecisionView, _open: &[Position]) -> Vec<Candidate> {
        Vec::new()
    }
}

/// Metrics — verbatim `_metrics` (including the V1 quirk that `fee_ratio`
/// divides by the DEFAULT 500 starting-equity constant, not the actual
/// start).
pub fn metrics(equity: &[f64], trades: &[Trade], fees_total: f64) -> Metrics {
    let empty = Metrics::default();
    if equity.is_empty() {
        return Metrics {
            final_equity: crate::config::START_EQUITY,
            ..empty
        };
    }
    let start_eq = equity[0];
    let end_eq = equity[equity.len() - 1];
    let rets: Vec<f64> = equity
        .windows(2)
        .map(|w| if w[0] != 0.0 { w[1] / w[0] - 1.0 } else { f64::NAN })
        .filter(|r| !r.is_nan())
        .collect();
    let sharpe = if rets.len() > 2 {
        let n = rets.len() as f64;
        let mean = rets.iter().sum::<f64>() / n;
        let var = rets.iter().map(|r| (r - mean) * (r - mean)).sum::<f64>() / (n - 1.0);
        let std = var.sqrt();
        if std > 0.0 {
            mean / std * (252.0f64).sqrt()
        } else {
            0.0
        }
    } else {
        0.0
    };
    let mut running_max = f64::NEG_INFINITY;
    let mut max_dd = 0.0f64;
    for &e in equity {
        if e > running_max {
            running_max = e;
        }
        if running_max > 0.0 {
            let dd = (e - running_max) / running_max;
            if -dd > max_dd {
                max_dd = -dd;
            }
        }
    }
    let n = trades.len();
    let wins = trades.iter().filter(|t| t.pnl > 0.0).count();
    let gw: f64 = trades.iter().filter(|t| t.pnl > 0.0).map(|t| t.pnl).sum();
    let gl: f64 = trades.iter().filter(|t| t.pnl < 0.0).map(|t| -t.pnl).sum();
    let pf = if gl > 0.0 { gw / gl } else { 0.0 };
    let avg_hold = if n > 0 {
        trades.iter().map(|t| t.bars as f64).sum::<f64>() / n as f64
    } else {
        0.0
    };
    let r3 = |x: f64| (x * 1000.0).round() / 1000.0;
    let r4 = |x: f64| (x * 10000.0).round() / 10000.0;
    Metrics {
        net_return: end_eq / start_eq - 1.0,
        ann_sharpe: r3(sharpe),
        max_drawdown: r4(max_dd),
        win_rate: r3(wins as f64 / (n.max(1) as f64)),
        n_trades: n,
        total_fees: (fees_total * 100.0).round() / 100.0,
        fee_ratio: r4(fees_total / crate::config::START_EQUITY.max(1.0)),
        profit_factor: r3(pf),
        avg_hold: (avg_hold * 100.0).round() / 100.0,
        final_equity: (end_eq * 100.0).round() / 100.0,
    }
}

/// Engine exit-ladder evaluation for ONE open position on the fill bar —
/// the engine-level half of the V1 ladder (delist/tp/sl/trail/max_hold).
/// Returns (price, reason) if an exit fires. The handler's signal/rsi
/// exits are consulted by the caller when this returns None.
/// NOTE: mutates `p.peak` (trailing) exactly as V1 does — only inside the
/// `trailing_pct > 0` branch.
pub fn evaluate_engine_exit(
    cfg: &Config,
    p: &mut Position,
    series: &Series,
    fill_ts: i64,
    close_t: Option<f64>,
) -> Option<(f64, ExitReason)> {
    let bar = match series.get(fill_ts) {
        None => {
            // Held symbol's data ended (delisted): force exit at its LAST
            // recorded close (V1: `closes[s].iloc[-1]`).
            return series.last_close().map(|px| (px, ExitReason::Delist));
        }
        Some(b) => b,
    };
    let entry = p.entry;
    // Strategy brackets (absolute prices) take precedence; same TP→SL
    // order as V1's percentage ladder (the locked same-bar discipline).
    if let Some(tp) = p.take_profit {
        if bar.high >= tp {
            return Some((tp, ExitReason::Tp));
        }
    }
    if let Some(sl) = p.stop_loss {
        if bar.low <= sl {
            return Some((sl, ExitReason::Sl));
        }
    }
    if p.take_profit.is_none() && p.stop_loss.is_none() {
        if bar.high >= entry * (1.0 + cfg.tp) {
            return Some((entry * (1.0 + cfg.tp), ExitReason::Tp));
        }
        if bar.low <= entry * (1.0 - cfg.sl) {
            return Some((entry * (1.0 - cfg.sl), ExitReason::Sl));
        }
    }
    if cfg.trailing_pct > 0.0 {
        p.peak = p.peak.max(bar.high);
        let trail = p.peak * (1.0 - cfg.trailing_pct);
        if bar.low <= trail {
            return Some((trail, ExitReason::Trail));
        }
    }
    if p.bars >= cfg.max_hold {
        // V1: close_t.get(s, entry) — missing close fills at ENTRY price.
        return Some((close_t.unwrap_or(p.entry), ExitReason::MaxHold));
    }
    None
}

/// Deterministic replay: the backtest/live-parity driver.
pub fn replay(universe: &Universe, cfg: &Config, handler: &mut dyn Handler) -> BacktestResult {
    let master = &universe.master;

    let start = cfg
        .mom_lb
        .max(cfg.rev_lb)
        .max(cfg.rsi_period)
        .max(cfg.breakout_lb)
        .max(cfg.z_period) as usize;
    if master.len() <= start + 6 {
        return BacktestResult {
            metrics: metrics(&[], &[], 0.0),
            trades: vec![],
            equity_ts: vec![],
            equity: vec![],
        };
    }
    let start = start + 1; // first signal bar fully warmed up

    let mut cash = cfg.start_equity;
    let mut positions: Vec<Position> = Vec::new();
    let mut trades: Vec<Trade> = Vec::new();
    let mut fees_total = 0.0;
    let mut equity_ts: Vec<i64> = Vec::new();
    let mut equity: Vec<f64> = Vec::new();

    for t in start..master.len() {
        let idx = master[t];
        let view = DecisionView {
            universe,
            sig_t: t - 1,
            fill_t: t,
        };

        // ── phase 1: handler signal exits (view = bars ≤ t-1; V1 computes
        // scores once, before the exit loop) ────────────────────────────
        let open_positions: Vec<Position> = positions.clone();
        let sig_exits: std::collections::BTreeMap<String, ExitReason> = handler
            .signal_exits(&view, &open_positions)
            .into_iter()
            .collect();

        // ── exits (V1 ladder, in insertion order, interleaved) ──────────
        let mut i = 0;
        while i < positions.len() {
            positions[i].bars += 1;
            let series = universe.get(&positions[i].sym).expect("held symbol exists");
            let close_t = view.fill_close(&positions[i].sym);
            let mut fired = evaluate_engine_exit(cfg, &mut positions[i], series, idx, close_t);
            if fired.is_none() {
                // Handler half, consulted per-symbol in the same loop
                // iteration (V1's in-loop signal/rsi checks).
                if let Some(reason) = sig_exits.get(&positions[i].sym) {
                    // V1: exit_price = close_t.get(s, entry)
                    fired = Some((close_t.unwrap_or(positions[i].entry), *reason));
                }
            }
            if let Some((exit_price, reason)) = fired {
                let p = &positions[i];
                let fee = fee_amt(cfg, p.qty, exit_price);
                let proceeds = p.qty * exit_price - fee;
                fees_total += fee;
                cash += proceeds;
                let pnl = proceeds - p.cost;
                trades.push(Trade {
                    sym: p.sym.clone(),
                    entry: p.entry,
                    exit: exit_price,
                    pnl,
                    pnl_pct: pnl / p.cost,
                    bars: p.bars,
                    reason: reason.as_str().to_string(),
                    entry_ts: p.entry_ts,
                    exit_ts: idx,
                });
                positions.remove(i);
            } else {
                if let Some(c) = close_t {
                    positions[i].last_close = c;
                }
                i += 1;
            }
        }

        // ── equity mark (V1: cash + Σ qty·close_t, after ALL exits) ────
        let equity_now = cash
            + positions
                .iter()
                .map(|p| p.qty * view.fill_close(&p.sym).unwrap_or(p.last_close))
                .sum::<f64>();

        // ── phase 2: candidates from the same scores, post-exit holdings ─
        let open_positions: Vec<Position> = positions.clone();
        let d_entries = handler.candidates(&view, &open_positions);

        // ── entries: engine sizing over pre-gated candidates ───────────
        for c in d_entries {
            if positions.len() >= cfg.max_positions {
                break;
            }
            let Some(close) = view.fill_close(&c.sym) else {
                continue;
            };
            if close <= 0.0 {
                continue;
            }
            let mut notional = c
                .notional_override
                .unwrap_or(cfg.risk_pct * equity_now);
            #[cfg(feature = "debug_strategy")]
            eprintln!("entry attempt t={t} sym={} notional={notional} cash={cash} eq={equity_now}", c.sym);
            if cfg.vol_reduce_n > 0 && c.vol_reduce_applies {
                notional *= cfg.vol_reduce_frac;
            }
            if cfg.impact_cap_pct > 0.0 {
                notional = notional.min(cfg.impact_cap_pct * equity_now);
            }
            if notional < cfg.min_notional {
                continue;
            }
            // Exposure cap applies to portfolio-scaled sizing only; an
            // explicit-size override (the strategy surface: units × price)
            // is the strategy's own sizing decision — cash still bounds it
            // below (notional + fee > cash scales down).
            if c.notional_override.is_none() {
                let exposure = positions
                    .iter()
                    .map(|p| p.qty * view.fill_close(&p.sym).unwrap_or(p.last_close))
                    .sum::<f64>()
                    / equity_now.max(1.0);
                if exposure + notional / equity_now.max(1.0) > cfg.max_exposure {
                    continue;
                }
            }
            let mut fee = fee_amt(cfg, notional / close.max(1e-9), close);
            if notional + fee > cash {
                notional = (cash - fee).max(0.0);
                if notional < cfg.min_notional {
                    continue;
                }
            }
            let qty = notional / close;
            fee = fee_amt(cfg, qty, close);
            let cost = qty * close + fee;
            cash -= cost;
            fees_total += fee;
            positions.push(Position {
                sym: c.sym,
                qty,
                entry: close,
                cost,
                peak: close,
                bars: 0,
                entry_ts: idx,
                last_close: close,
                stop_loss: c.stop_loss,
                take_profit: c.take_profit,
            });
        }

        // Equity is recorded AFTER entries (V1 appends at loop end) — but
        // V1 computes the marked equity BEFORE entries and records that
        // same value; mirror exactly.
        equity_ts.push(idx);
        equity.push(equity_now);
    }

    let m = metrics(&equity, &trades, fees_total);
    BacktestResult {
        metrics: m,
        trades,
        equity_ts,
        equity,
    }
}
