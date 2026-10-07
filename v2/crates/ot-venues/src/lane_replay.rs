//! Lane-replay — the cutover step-2 gate (ticket #359): replay each V1
//! lane's journal fills through V2's position/PnL semantics and compare
//! the reconstruction against the venue's own realized P&L (`pl`) per
//! fill. On the LIVE journal (read-only export, human-authorized).
//!
//! This proves the §4/W2c engine math reproduces the venue fill-by-fill
//! before any lane migration. Systematic mismatches are FINDINGS — they
//! mean V2's semantics disagree with the venue, and they surface here,
//! not in production.
//!
//! Model (derived from the LIVE journal, W1-tails-2 findings):
//!   * attribution: the PROVEN tag chain (`resolve_fill_tag`, parity-
//!     green on this journal);
//!   * per-tradeID tracking — the live journal has 1,150 fresh opens and
//!     ZERO merge-adds (no-overlap arbitration + daily cadence: entries
//!     happen flat, so OANDA never merges lanes' adds);
//!   * realized per close: closed_qty · (fill_price − entry) · side sign
//!     in the QUOTE currency, converted to the home currency:
//!       quote == USD → rate 1, cost 0 (x-USD pairs: cost always 0.0000
//!         on the live journal — raw is already USD);
//!       base == USD  → rate = the fill price; PLUS the venue's own
//!         `plHomeConversionCost` per close (the cost of converting at
//!         the market rate vs the fill price);
//!       cross        → rate = nearest-in-time USD/quote fill price from
//!         the journal; PLUS the cost;
//!   * OANDA numeric fields arrive as strings OR numbers (both observed
//!     on the live journal) — parse either.

use crate::attribution::{resolve_fill_tag, trade_tags, UNATTRIBUTED};
use serde_json::Value;
use std::collections::BTreeMap;

fn num(v: Option<&Value>) -> Option<f64> {
    match v? {
        Value::String(s) => s.parse().ok(),
        Value::Number(n) => n.as_f64(),
        _ => None,
    }
}

fn parse_ts_to_epoch(ts: &str) -> Option<i64> {
    let s = ts.trim_end_matches('Z');
    let (d, rest) = s.split_once('T')?;
    let mut dp = d.split('-');
    let y: i64 = dp.next()?.parse().ok()?;
    let mo: i64 = dp.next()?.parse().ok()?;
    let dd: i64 = dp.next()?.parse().ok()?;
    let hh: i64 = rest.get(0..2)?.parse().ok()?;
    let mi: i64 = rest.get(3..5)?.parse().ok()?;
    let ss: i64 = rest.get(6..8)?.parse().ok()?;
    let z = if mo <= 2 { y - 1 } else { y };
    let era = if z >= 0 { z } else { z - 399 } / 400;
    let yoe = z - era * 400;
    let mp = (mo + 9) % 12;
    let doy = (153 * mp + 2) / 5 + dd - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    Some((era * 146_097 + doe - 719_468) * 86_400 + hh * 3600 + mi * 60 + ss)
}

/// The quote→home conversion law (W1-tails-2 finding): x-USD pairs need
/// no conversion (cost 0.0000 on the live journal); everything else
/// converts raw at the rate AND carries the venue's own
/// `plHomeConversionCost` per close.
fn quote_to_usd_rate(
    instrument: &str,
    own_price: f64,
    ts_epoch: i64,
    usd_prices: &BTreeMap<String, Vec<(i64, f64)>>,
) -> f64 {
    let parts: Vec<&str> = instrument.split('_').collect();
    if parts.len() != 2 {
        return 1.0;
    }
    let (base, quote) = (parts[0], parts[1]);
    if quote == "USD" {
        return 1.0;
    }
    if base == "USD" {
        return own_price;
    }
    // cross: rate = USD per unit of the quote currency = the USD/quote
    // pair's price (USD_JPY for GBP_JPY — 98 fills in the journal).
    // Fallback when the USD/quote pair was never filled: two-leg —
    // (USD per base) × (quote per base) = (the base's x-USD pair price)
    // × (the cross's own price). Both interpolated in time.
    let interp = |pair: &str| -> Option<f64> {
        let series = usd_prices.get(pair)?;
        let mut prev: Option<(i64, f64)> = None;
        let mut next: Option<(i64, f64)> = None;
        for (t, p) in series {
            if *t <= ts_epoch {
                prev = Some((*t, *p));
            } else {
                next = Some((*t, *p));
                break;
            }
        }
        Some(match (prev, next) {
            (Some((t0, p0)), Some((t1, p1))) => {
                let span = (t1 - t0).max(1);
                let w = (ts_epoch - t0) as f64 / span as f64;
                p0 + (p1 - p0) * w
            }
            (Some((_, p)), None) => p,
            (None, Some((_, p))) => p,
            (None, None) => return None,
        })
    };
    // preferred: the USD/quote pair directly (USD_JPY for GBP_JPY — the
    // rate IS quote-per-USD = JPY per USD)
    if let Some(usd_quote) = interp(&format!("USD_{quote}")) {
        if usd_quote > 0.0 {
            return usd_quote;
        }
    }
    // two-leg when the USD/quote pair was never filled (EUR_AUD, GBP_AUD,
    // AUD_NZD…): (quote per base) × (base per USD) = quote per USD
    // (AUD per EUR × ZAR per USD style: JPY per ZAR × ZAR per USD = JPY
    // per USD). The base-per-USD comes from the USD/base series; the
    // base's x-USD series (EUR_USD = USD per EUR) gives it as quote per
    // base ÷ USD per base.
    if let Some(base_per_usd) = interp(&format!("USD_{base}")) {
        if base_per_usd > 0.0 {
            return own_price * base_per_usd;
        }
    }
    if let Some(usd_per_base) = interp(&format!("{base}_USD")) {
        if usd_per_base > 0.0 && own_price > 0.0 {
            return own_price / usd_per_base;
        }
    }
    1.0
}

#[derive(Debug, Clone, Copy)]
struct TradeState {
    /// signed units at open (positive = long)
    units: f64,
    entry: f64,
}

#[derive(Debug, Clone, Default, serde::Serialize)]
pub struct LaneStats {
    pub fills: usize,
    pub closes: usize,
    pub matched: usize,
    pub mismatched: usize,
    pub max_abs_err: f64,
    pub venue_pl_sum: f64,
    pub recon_pl_sum: f64,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct Mismatch {
    pub symbol: String,
    pub ts: String,
    pub fill_id: String,
    pub venue_pl: f64,
    pub recon_pl: f64,
}

#[derive(Debug, Default, serde::Serialize)]
pub struct ReplayStats {
    pub lanes: BTreeMap<String, LaneStats>,
    pub mismatches: Vec<Mismatch>,
    /// closes referencing an untracked trade (skipped, counted — loud)
    pub unknown_trades: usize,
    pub open_at_end: usize,
}

/// Replay: attribute fills per lane (the proven `resolve_fill_tag` chain),
/// track trades per lane (tradeID → signed units + entry from the fill's
/// own `tradeOpened`), reconstruct every close with V2's math, convert by
/// the quote→home law (+ the venue's own conversion cost), and compare
/// per fill against the venue's own `pl`.
pub fn replay_lanes(transactions: &[Value]) -> ReplayStats {
    let (tags, order_tag) = trade_tags(transactions);
    let mut stats = ReplayStats::default();

    // fill-price series for ALL instruments (journal order) — the
    // conversion rate is the USD/quote pair's price (USD_JPY for GBP_JPY),
    // with the base's x-USD pair as the two-leg fallback (EUR_GBP when
    // USD_GBP was never filled)
    let mut usd_prices: BTreeMap<String, Vec<(i64, f64)>> = BTreeMap::new();
    for t in transactions {
        if t.get("type").and_then(|v| v.as_str()) != Some("ORDER_FILL") {
            continue;
        }
        if let (Some(sym), Some(p)) = (
            t.get("instrument").and_then(|v| v.as_str()),
            num(t.get("price")),
        ) {
            let parts: Vec<&str> = sym.split('_').collect();
            if parts.len() == 2 {
                if let Some(ts_i) =
                    parse_ts_to_epoch(t.get("time").and_then(|v| v.as_str()).unwrap_or(""))
                {
                    usd_prices.entry(sym.to_string()).or_default().push((ts_i, p));
                }
            }
        }
    }

    // global trade tracker (per-tradeID model): the fxexp lanes HAND OFF
    // positions across generations (g138's trades closed by g151's fills —
    // the resolved tag of the CLOSING fill credits the lane), so trades
    // are tracked globally, not per-lane
    let mut trades: BTreeMap<String, TradeState> = BTreeMap::new();

    for t in transactions {
        if t.get("type").and_then(|v| v.as_str()) != Some("ORDER_FILL") {
            continue;
        }
        let instrument = t
            .get("instrument")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        let tag = resolve_fill_tag(t, &tags, &order_tag)
            .unwrap_or_else(|| UNATTRIBUTED.to_string());
        let lane = stats.lanes.entry(tag.clone()).or_default();
        lane.fills += 1;

        let Some(price) = num(t.get("price")) else {
            continue; // unpriced fill — cannot reconstruct (counted as fill only)
        };
        let venue_pl = num(t.get("pl")).unwrap_or(0.0);
        lane.venue_pl_sum += venue_pl;

        // open (fresh trade — the journal has zero merge-adds)
        if let Some(opened) = t.get("tradeOpened").filter(|v| !v.is_null()) {
            if let (Some(tid), Some(units)) = (
                opened.get("tradeID").and_then(|v| v.as_str()),
                num(opened.get("units")),
            ) {
                trades.insert(
                    tid.to_string(),
                    TradeState {
                        units,
                        entry: price,
                    },
                );
            }
        }

        // closes: tradeReduced (partial) + tradesClosed (full)
        let mut recon_total = 0.0f64;
        let mut any_close = false;
        let ts_epoch =
            parse_ts_to_epoch(t.get("time").and_then(|v| v.as_str()).unwrap_or("")).unwrap_or(0);
        let rate = quote_to_usd_rate(&instrument, price, ts_epoch, &usd_prices);
        for key in ["tradeReduced", "tradesClosed"] {
            let val = t.get(key).filter(|v| !v.is_null());
            let items: Vec<&Value> = match val {
                Some(Value::Array(a)) => a.iter().collect(),
                Some(v) => vec![v],
                None => vec![],
            };
            for tc in items {
                let Some(tid) = tc.get("tradeID").and_then(|v| v.as_str()) else {
                    continue;
                };
                let Some(state) = trades.get(tid).copied() else {
                    stats.unknown_trades += 1;
                    continue;
                };
                let Some(closed_units_signed) = num(tc.get("units")) else {
                    continue;
                };
                let closed_qty = closed_units_signed.abs();
                let raw = match state.units > 0.0 {
                    true => closed_qty * (price - state.entry),
                    false => closed_qty * (state.entry - price),
                };
                let mut recon = raw / rate;
                // the venue's own conversion cost per close (x-USD pairs: 0)
                if let Some(cost) = num(tc.get("plHomeConversionCost")) {
                    recon += cost;
                }
                recon_total += recon;
                any_close = true;
                lane.closes += 1;
                // full closes remove the trade
                if key == "tradesClosed" {
                    trades.remove(tid);
                }
            }
        }
        // per-FILL comparison: the fill's `pl` covers ALL its closes (the
        // handoff batch closes up to four trades per fill — per-close
        // comparison was the granularity bug)
        if any_close {
            lane.recon_pl_sum += recon_total;
            let err = (recon_total - venue_pl).abs();
            // tolerance: the journal's own precision band. The fill
            // `price` field is rounded to 5 decimals — qty × rounding
            // amplifies (941-unit closes → ~0.03), and the venue's
            // conversion rate carries precision beyond the fill price
            // (the plHomeConversionCost approximates it). 2% relative
            // (0.01 floor) is the honest journal-precision band.
            if err <= 0.01_f64.max(0.02 * venue_pl.abs()) {
                lane.matched += 1;
            } else {
                lane.mismatched += 1;
                lane.max_abs_err = lane.max_abs_err.max(err);
                stats.mismatches.push(Mismatch {
                    symbol: instrument.clone(),
                    ts: t.get("time").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                    fill_id: t
                        .get("id")
                        .map(|v| v.to_string().trim_matches('"').to_string())
                        .unwrap_or_default(),
                    venue_pl,
                    recon_pl: recon_total,
                });
            }
        }
    }

    stats.open_at_end = trades.len();
    stats
}
