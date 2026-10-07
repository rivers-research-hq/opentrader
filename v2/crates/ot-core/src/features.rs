//! Per-symbol causal features — verbatim port of V1 `_features` / `_rsi`.
//!
//! All features are causal (backward-looking windows only), so computing
//! them once over a full series and exposing a truncated view to the
//! decision layer is mathematically identical to computing them on the
//! truncated series. The structural no-lookahead guarantee lives in the
//! engine: the decision view ends at the signal bar (see `engine.rs`).

use crate::bar::Series;

/// One bar's feature row (V1's DataFrame row). NaN = not formed yet.
#[derive(Debug, Clone, Copy, Default)]
pub struct FeatureRow {
    pub mom: f64,
    pub rev: f64,
    pub rsi: f64,
    pub brk: f64,
    pub z: f64,
    pub close: f64,
    pub ma_dist: f64,
    pub vol_spike: f64,
    pub vol_level: f64,
    pub momfilt: f64,
}

pub const NAN: f64 = f64::NAN;

/// Rolling mean with `min_periods` (pandas `.rolling(n, min_periods=n).mean()`):
/// NaN until `min_periods` valid observations in the window.
pub fn rolling_mean(x: &[f64], n: usize, min_periods: usize) -> Vec<f64> {
    let mut out = vec![NAN; x.len()];
    if n == 0 {
        return out;
    }
    for i in 0..x.len() {
        let lo = i.saturating_sub(n - 1);
        let mut sum = 0.0;
        let mut cnt = 0usize;
        for &v in &x[lo..=i] {
            if !v.is_nan() {
                sum += v;
                cnt += 1;
            }
        }
        if cnt >= min_periods {
            out[i] = sum / cnt as f64;
        }
    }
    out
}

/// Rolling max (pandas `.rolling(n, min_periods=n).max()`): NaN until
/// `min_periods` valid observations. Brute force over the window — windows
/// are bounded by config bounds (≤ 120), clarity over cleverness.
pub fn rolling_max(x: &[f64], n: usize, min_periods: usize) -> Vec<f64> {
    let mut out = vec![NAN; x.len()];
    if n == 0 {
        return out;
    }
    for i in 0..x.len() {
        let lo = i.saturating_sub(n - 1);
        let mut m = f64::NAN;
        let mut cnt = 0usize;
        for &v in &x[lo..=i] {
            if !v.is_nan() {
                if m.is_nan() || v > m {
                    m = v;
                }
                cnt += 1;
            }
        }
        if cnt >= min_periods {
            out[i] = m;
        }
    }
    out
}

/// Rolling sample std (pandas `.rolling(n, min_periods=n).std()` — ddof=1).
pub fn rolling_std(x: &[f64], n: usize, min_periods: usize) -> Vec<f64> {
    let mut out = vec![NAN; x.len()];
    if n == 0 {
        return out;
    }
    for i in 0..x.len() {
        let lo = i.saturating_sub(n - 1);
        let vals: Vec<f64> = x[lo..=i].iter().copied().filter(|v| !v.is_nan()).collect();
        if vals.len() < min_periods || vals.len() < 2 {
            continue;
        }
        let m = vals.iter().sum::<f64>() / vals.len() as f64;
        let ss: f64 = vals.iter().map(|v| (v - m) * (v - m)).sum();
        out[i] = (ss / (vals.len() as f64 - 1.0)).sqrt();
    }
    out
}

/// pandas `ewm(alpha, min_periods, adjust=False).mean()` over a series whose
/// only NaNs lead the series (RSI's first diff). With adjust=False and
/// ignore_na=False: seed at the first valid value, then
/// y_t = (1-α)·y_{t-1} + α·x_t. NaN until `min_periods` valid observations.
pub fn ewm_mean(x: &[f64], alpha: f64, min_periods: usize) -> Vec<f64> {
    let mut out = vec![NAN; x.len()];
    let mut y = 0.0f64;
    let mut cnt = 0usize;
    let mut seeded = false;
    for i in 0..x.len() {
        if x[i].is_nan() {
            if cnt >= min_periods {
                out[i] = y; // pandas carries the last value through NaNs
            }
            continue;
        }
        if !seeded {
            y = x[i];
            seeded = true;
        } else {
            y = (1.0 - alpha) * y + alpha * x[i];
        }
        cnt += 1;
        if cnt >= min_periods {
            out[i] = y;
        }
    }
    out
}

/// V1 `_rsi`: RSI centered to [-1, 1] as `(rsi - 50) / 50`.
pub fn rsi(series: &Series, period: i64) -> Vec<f64> {
    let bars = series.bars();
    let n = bars.len();
    let mut delta = vec![NAN; n];
    for i in 1..n {
        delta[i] = bars[i].close - bars[i - 1].close;
    }
    let gain: Vec<f64> = delta
        .iter()
        .map(|d| if d.is_nan() { NAN } else { d.max(0.0) })
        .collect();
    let loss: Vec<f64> = delta
        .iter()
        .map(|d| if d.is_nan() { NAN } else { -d.min(0.0) })
        .collect();
    let a = 1.0 / period as f64;
    let avg_gain = ewm_mean(&gain, a, period as usize);
    let avg_loss = ewm_mean(&loss, a, period as usize);
    let mut out = vec![NAN; n];
    for i in 0..n {
        if avg_gain[i].is_nan() || avg_loss[i].is_nan() {
            continue;
        }
        if avg_loss[i] == 0.0 {
            continue; // replace(0, nan) → rs NaN → rsi NaN
        }
        let rs = avg_gain[i] / avg_loss[i];
        let r = 100.0 - 100.0 / (1.0 + rs);
        out[i] = (r - 50.0) / 50.0;
    }
    out
}

fn pct_change(closes: &[f64], lag: usize) -> Vec<f64> {
    let mut out = vec![NAN; closes.len()];
    for i in lag..closes.len() {
        if closes[i - lag] != 0.0 {
            out[i] = closes[i] / closes[i - lag] - 1.0;
        }
    }
    out
}

/// Full causal feature block for one symbol — V1 `_features` row set.
pub struct Features {
    pub rows: Vec<FeatureRow>,
}

pub fn compute_features(
    series: &Series,
    vols: Option<&[f64]>,
    cfg: &crate::config::Config,
) -> Features {
    let bars = series.bars();
    let n = bars.len();
    let closes: Vec<f64> = bars.iter().map(|b| b.close).collect();
    let highs: Vec<f64> = bars.iter().map(|b| b.high).collect();

    let shift = |lag: usize, arr: &[f64]| -> Vec<f64> {
        let mut out = vec![NAN; arr.len()];
        for i in lag..arr.len() {
            if arr[i - lag] != 0.0 {
                out[i] = arr[i] / arr[i - lag] - 1.0;
            }
        }
        out
    };

    let mom = shift(cfg.mom_lb as usize, &closes);
    // V1: rev = -(c / c.shift(rev_lb) - 1.0) — its OWN lag, not mom's.
    let rev_raw = shift(cfg.rev_lb as usize, &closes);
    let rev: Vec<f64> = rev_raw
        .iter()
        .map(|m| if m.is_nan() { NAN } else { -m })
        .collect();
    let rsi_v = rsi(series, cfg.rsi_period);
    let hi_max = rolling_max(&highs, cfg.breakout_lb as usize, cfg.breakout_lb as usize);
    let brk: Vec<f64> = (0..n)
        .map(|i| {
            if hi_max[i].is_nan() || hi_max[i] == 0.0 {
                NAN
            } else {
                closes[i] / hi_max[i] - 1.0
            }
        })
        .collect();
    let z_mean = rolling_mean(&closes, cfg.z_period as usize, cfg.z_period as usize);
    let z_std = rolling_std(&closes, cfg.z_period as usize, cfg.z_period as usize);
    let z: Vec<f64> = (0..n)
        .map(|i| {
            if z_mean[i].is_nan() || z_std[i].is_nan() || z_std[i] == 0.0 {
                NAN
            } else {
                (closes[i] - z_mean[i]) / z_std[i]
            }
        })
        .collect();

    // Gate columns (0.0 when disabled — matching the Python `else 0.0`)
    let ma_n = cfg.ma_reject_n as usize;
    let ma_dist: Vec<f64> = if ma_n > 0 {
        let ma = rolling_mean(&closes, ma_n, ma_n);
        (0..n)
            .map(|i| {
                if ma[i].is_nan() || ma[i] == 0.0 {
                    NAN
                } else {
                    closes[i] / ma[i] - 1.0
                }
            })
            .collect()
    } else {
        vec![0.0; n]
    };
    let vs_n = cfg.vol_spike_n as usize;
    let vol_spike: Vec<f64> = match (vs_n > 0, vols) {
        (true, Some(v)) => {
            let vmean = rolling_mean(v, vs_n, vs_n);
            (0..n)
                .map(|i| {
                    if vmean[i].is_nan() || vmean[i] == 0.0 {
                        NAN
                    } else {
                        v[i] / vmean[i]
                    }
                })
                .collect()
        }
        _ => vec![0.0; n],
    };
    let vr_n = cfg.vol_reduce_n as usize;
    let vol_level: Vec<f64> = if vr_n > 0 {
        let pc1 = pct_change(&closes, 1);
        rolling_std(&pc1, vr_n, vr_n)
    } else {
        vec![0.0; n]
    };
    let mf_n = cfg.mom_filter_n as usize;
    let momfilt: Vec<f64> = if mf_n > 0 {
        pct_change(&closes, mf_n)
    } else {
        vec![0.0; n]
    };

    let rows: Vec<FeatureRow> = (0..n)
        .map(|i| FeatureRow {
            mom: mom[i],
            rev: rev[i],
            rsi: rsi_v[i],
            brk: brk[i],
            z: z[i],
            close: closes[i],
            ma_dist: ma_dist[i],
            vol_spike: vol_spike[i],
            vol_level: vol_level[i],
            momfilt: momfilt[i],
        })
        .collect();
    Features { rows }
}

impl Features {
    pub fn row(&self, i: usize) -> Option<&FeatureRow> {
        self.rows.get(i)
    }
}
