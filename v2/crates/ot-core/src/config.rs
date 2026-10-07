//! Config space — verbatim port of V1 `setup_search/core.py` bounds,
//! defaults, and clamp, plus the fee model (`_fee_amt`).

pub const FEE_PER_SIDE: f64 = 0.35;
pub const START_EQUITY: f64 = 500.0;

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Config {
    pub mom_lb: i64,
    pub w_mom: f64,
    pub rev_lb: i64,
    pub w_rev: f64,
    pub rsi_period: i64,
    pub w_rsi: f64,
    pub breakout_lb: i64,
    pub w_brk: f64,
    pub z_period: i64,
    pub w_z: f64,
    pub rank_on: bool,
    pub w_rank: f64,
    pub buy_thresh: f64,
    pub sell_thresh: Option<f64>,
    pub regime_filter: bool,
    pub regime_window: i64,
    pub risk_pct: f64,
    pub max_positions: usize,
    pub max_exposure: f64,
    pub min_notional: f64,
    pub sl: f64,
    pub tp: f64,
    pub max_hold: i64,
    pub trailing_pct: f64,
    // Research-feature gates (0 = off)
    pub ma_reject_n: i64,
    pub ma_reject_pct: f64,
    pub vol_spike_n: i64,
    pub vol_spike_mult: f64,
    pub vol_reduce_n: i64,
    pub vol_reduce_thr: f64,
    pub vol_reduce_frac: f64,
    pub impact_cap_pct: f64,
    pub rsi_filter_n: i64,
    pub rsi_filter_hi: f64,
    pub rsi_filter_lo: f64,
    pub mom_filter_n: i64,
    pub mom_filter_max: f64,
    pub mom_filter_min: f64,
    pub rsi_exit_hi: f64,
    pub rsi_exit_lo: f64,
    // Non-bounded keys
    pub fee_pct: f64,
    pub start_equity: f64,
}

pub const DEFAULT_CONFIG: Config = Config {
    mom_lb: 20,
    w_mom: 1.0,
    rev_lb: 10,
    w_rev: -0.2,
    rsi_period: 14,
    w_rsi: 0.3,
    breakout_lb: 55,
    w_brk: 0.2,
    z_period: 20,
    w_z: 0.1,
    rank_on: false,
    w_rank: 0.0,
    buy_thresh: 0.2,
    sell_thresh: Some(-0.2),
    regime_filter: false,
    regime_window: 50,
    risk_pct: 0.05,
    max_positions: 6,
    max_exposure: 0.60,
    min_notional: 10.0,
    sl: 0.05,
    tp: 0.10,
    max_hold: 20,
    trailing_pct: 0.0,
    ma_reject_n: 0,
    ma_reject_pct: 0.0,
    vol_spike_n: 0,
    vol_spike_mult: 0.0,
    vol_reduce_n: 0,
    vol_reduce_thr: 0.0,
    vol_reduce_frac: 0.0,
    impact_cap_pct: 0.0,
    rsi_filter_n: 0,
    rsi_filter_hi: 0.0,
    rsi_filter_lo: 0.0,
    mom_filter_n: 0,
    mom_filter_max: 0.0,
    mom_filter_min: 0.0,
    rsi_exit_hi: 0.0,
    rsi_exit_lo: 0.0,
    fee_pct: 0.0,
    start_equity: START_EQUITY,
};

/// V1 `int(round(v))` — Python's round: half-to-even.
fn py_round(v: f64) -> i64 {
    let r = v.round(); // half away from zero
    if (v - v.trunc()).abs() == 0.5 && r % 2.0 != 0.0 {
        // exact .5 case: choose the even neighbor
        let down = v.trunc();
        let up = if v > 0.0 { down + 1.0 } else { down - 1.0 };
        let pick = if down % 2.0 == 0.0 { down } else { up };
        return pick as i64;
    }
    r as i64
}

/// V1 `clamp_config`: start from DEFAULT_CONFIG (ALL keys present in the
/// output), clamp every provided CONFIG_BOUNDS key, int-round the INT_KEYS
/// (half-to-even), then the tp<=sl repair (`tp = round(min(sl+0.05, 0.5), 3)`),
/// then `_start_equity`/`_fee_pct` pass-through.
pub fn clamp_config(over: impl Fn(&str) -> Option<f64>) -> Config {
    use std::sync::OnceLock;
    static BOUNDS: OnceLock<Vec<(&'static str, f64, f64)>> = OnceLock::new();
    let bounds = BOUNDS.get_or_init(|| {
        vec![
            ("mom_lb", 5.0, 60.0),
            ("w_mom", -2.0, 4.0),
            ("rev_lb", 5.0, 60.0),
            ("w_rev", -2.0, 4.0),
            ("rsi_period", 5.0, 30.0),
            ("w_rsi", -2.0, 4.0),
            ("breakout_lb", 10.0, 120.0),
            ("w_brk", -2.0, 4.0),
            ("z_period", 5.0, 60.0),
            ("w_z", -2.0, 4.0),
            ("rank_on", 0.0, 1.0),
            ("w_rank", 0.0, 3.0),
            ("buy_thresh", 0.0, 1.5),
            ("sell_thresh", -1.0, 3.0),
            ("regime_filter", 0.0, 1.0),
            ("regime_window", 20.0, 200.0),
            ("risk_pct", 0.01, 0.15),
            ("max_positions", 1.0, 12.0),
            ("max_exposure", 0.20, 0.95),
            ("min_notional", 5.0, 60.0),
            ("sl", 0.01, 0.15),
            ("tp", 0.02, 0.50),
            ("max_hold", 1.0, 60.0),
            ("trailing_pct", 0.0, 0.05),
            ("ma_reject_n", 0.0, 120.0),
            ("ma_reject_pct", 0.0, 0.5),
            ("vol_spike_n", 0.0, 120.0),
            ("vol_spike_mult", 0.0, 10.0),
            ("vol_reduce_n", 0.0, 120.0),
            ("vol_reduce_thr", 0.0, 0.2),
            ("vol_reduce_frac", 0.0, 1.0),
            ("impact_cap_pct", 0.0, 0.5),
            ("rsi_filter_n", 0.0, 30.0),
            ("rsi_filter_hi", 0.0, 100.0),
            ("rsi_filter_lo", 0.0, 100.0),
            ("mom_filter_n", 0.0, 120.0),
            ("mom_filter_max", 0.0, 10.0),
            ("mom_filter_min", 0.0, 10.0),
            ("rsi_exit_hi", 0.0, 100.0),
            ("rsi_exit_lo", 0.0, 100.0),
        ]
    });

    let mut c = DEFAULT_CONFIG;
    let set = |name: &str, val: f64, c: &mut Config| {
        let (lo, hi) = match bounds.iter().find(|(k, ..)| *k == name) {
            Some((_, lo, hi)) => (*lo, *hi),
            None => (f64::NEG_INFINITY, f64::INFINITY),
        };
        let v = val.clamp(lo, hi);
        let int_keys = [
            "mom_lb", "rev_lb", "rsi_period", "breakout_lb", "z_period", "rank_on",
            "regime_filter", "regime_window", "max_positions", "max_hold", "ma_reject_n",
            "vol_spike_n", "vol_reduce_n", "rsi_filter_n", "mom_filter_n",
        ];
        let vi = if int_keys.contains(&name) { py_round(v) as f64 } else { v };
        match name {
            "mom_lb" => c.mom_lb = vi as i64,
            "w_mom" => c.w_mom = v,
            "rev_lb" => c.rev_lb = vi as i64,
            "w_rev" => c.w_rev = v,
            "rsi_period" => c.rsi_period = vi as i64,
            "w_rsi" => c.w_rsi = v,
            "breakout_lb" => c.breakout_lb = vi as i64,
            "w_brk" => c.w_brk = v,
            "z_period" => c.z_period = vi as i64,
            "w_z" => c.w_z = v,
            "rank_on" => c.rank_on = vi >= 1.0,
            "w_rank" => c.w_rank = v,
            "buy_thresh" => c.buy_thresh = v,
            "sell_thresh" => c.sell_thresh = Some(v),
            "regime_filter" => c.regime_filter = vi >= 1.0,
            "regime_window" => c.regime_window = vi as i64,
            "risk_pct" => c.risk_pct = v,
            "max_positions" => c.max_positions = vi.max(1.0) as usize,
            "max_exposure" => c.max_exposure = v,
            "min_notional" => c.min_notional = v,
            "sl" => c.sl = v,
            "tp" => c.tp = v,
            "max_hold" => c.max_hold = vi.max(1.0) as i64,
            "trailing_pct" => c.trailing_pct = v,
            "ma_reject_n" => c.ma_reject_n = vi as i64,
            "ma_reject_pct" => c.ma_reject_pct = v,
            "vol_spike_n" => c.vol_spike_n = vi as i64,
            "vol_spike_mult" => c.vol_spike_mult = v,
            "vol_reduce_n" => c.vol_reduce_n = vi as i64,
            "vol_reduce_thr" => c.vol_reduce_thr = v,
            "vol_reduce_frac" => c.vol_reduce_frac = v,
            "impact_cap_pct" => c.impact_cap_pct = v,
            "rsi_filter_n" => c.rsi_filter_n = vi as i64,
            "rsi_filter_hi" => c.rsi_filter_hi = v,
            "rsi_filter_lo" => c.rsi_filter_lo = v,
            "mom_filter_n" => c.mom_filter_n = vi as i64,
            "mom_filter_max" => c.mom_filter_max = v,
            "mom_filter_min" => c.mom_filter_min = v,
            "rsi_exit_hi" => c.rsi_exit_hi = v,
            "rsi_exit_lo" => c.rsi_exit_lo = v,
            "_fee_pct" => c.fee_pct = v,
            "_start_equity" => c.start_equity = v,
            _ => {}
        }
    };
    for &(name, _, _) in bounds.iter() {
        if let Some(v) = over(name) {
            set(name, v, &mut c);
        }
    }
    // V1 repair: `if tp <= sl: tp = round(min(sl + 0.05, 0.50), 3)`
    if c.tp <= c.sl {
        c.tp = ((c.sl + 0.05).min(0.50) * 1000.0).round() / 1000.0;
    }
    if let Some(v) = over("_fee_pct") {
        c.fee_pct = v;
    }
    if let Some(v) = over("_start_equity") {
        c.start_equity = v;
    }
    c
}

/// V1 `_fee_amt`: percentage fee when configured, otherwise the fixed
/// $0.35-per-side model that dominates the $500 account.
pub fn fee_amt(cfg: &Config, qty: f64, price: f64) -> f64 {
    if cfg.fee_pct > 0.0 {
        qty * price * cfg.fee_pct
    } else {
        FEE_PER_SIDE
    }
}
