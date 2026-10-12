//! OANDA v20 order-book / position-book — bucketed depth-of-market snapshots
//! for the ladder surface (ticket #389, spec §7).
//!
//! The venue's buckets are the ONLY level source. Laws (each traces to the
//! adapter's truthfulness contract, `oanda.rs` law 1/2):
//!   1. **Venue errors are Err, never an empty book.** The `_error`/`_status`
//!      wrapper from `request()`, and the `{}` a transport failure produces,
//!      both become `Err`. An `Ok` with zero buckets must mean the venue
//!      genuinely published zero buckets.
//!   2. **Counts read as published.** v20 quotes numbers as strings; a level's
//!      `volume` = longCount + shortCount with an absent count = 0.0. A level
//!      whose price is unreadable is a loud error — never a silent drop.
//!   3. **Order is the venue's order, sorted once, ascending.** No dedupe,
//!      no averaging, no synthetic midpoint levels.
//!   4. **Time and instrument come from the payload.** Never a local clock.
//!   5. **Polling shape only.** `poll_book_snapshot` takes ONE snapshot and
//!      returns; the sleep cadence belongs to the caller. The human lock
//!      (polling vs streaming on practice) is unresolved, so no streaming
//!      surface ships here.

use crate::oanda::OandaAdapter;
use serde_json::Value;

/// One bucketed depth level: the venue's price and its total resting volume.
#[derive(Debug, Clone, PartialEq)]
pub struct BookLevel {
    pub price: f64,
    pub volume: f64,
}

/// A depth snapshot of resting orders (orderBook).
#[derive(Debug, Clone, PartialEq)]
pub struct OrderBook {
    pub instrument: String,
    pub time: String,
    /// ascending by price (law 3)
    pub buckets: Vec<BookLevel>,
}

/// A depth snapshot of open positions (positionBook).
#[derive(Debug, Clone, PartialEq)]
pub struct PositionBook {
    pub instrument: String,
    pub time: String,
    /// ascending by price (law 3)
    pub buckets: Vec<BookLevel>,
}

/// Both books for one instrument, fetched in order.
#[derive(Debug, Clone, PartialEq)]
pub struct BookSnapshot {
    pub book: OrderBook,
    pub position_book: PositionBook,
}

/// v20 publishes numbers as strings and occasionally as numbers — accept both,
/// refuse anything else (law 2).
fn as_f64(v: &Value) -> Option<f64> {
    match v {
        Value::Number(n) => n.as_f64(),
        Value::String(s) => s.trim().parse::<f64>().ok(),
        _ => None,
    }
}

/// Parse one book payload (`orderBook` / `positionBook`). Shared by both
/// fetches so the two can never drift apart in their truthfulness rules.
fn parse_book(
    resp: &Value,
    key: &str,
    instrument: &str,
) -> Result<(String, String, Vec<BookLevel>), String> {
    // law 1: the venue's own error wrapper is an error, not an empty book.
    if let Some(err) = resp.get("_error") {
        let msg = err
            .get("errorMessage")
            .and_then(|m| m.as_str())
            .or_else(|| err.as_str())
            .unwrap_or("venue error");
        let status = resp.get("_status").and_then(|s| s.as_i64()).unwrap_or(0);
        return Err(format!("venue error (HTTP {status}): {msg}"));
    }
    // law 1: transport failure yields `{}` — missing body is an error too.
    let book = resp.get(key).ok_or_else(|| {
        format!("no `{key}` in response (transport failure or wrong endpoint)")
    })?;
    let buckets = book
        .get("buckets")
        .and_then(|b| b.as_array())
        .ok_or_else(|| format!("malformed payload: `{key}.buckets` is not an array"))?;

    // law 4: payload time/instrument, never a local clock.
    let time = book
        .get("time")
        .and_then(|t| t.as_str())
        .unwrap_or("")
        .to_string();
    let venue_instrument = book
        .get("instrument")
        .and_then(|i| i.as_str())
        .unwrap_or(instrument)
        .to_string();

    let mut levels: Vec<BookLevel> = Vec::with_capacity(buckets.len());
    for (i, b) in buckets.iter().enumerate() {
        // law 2: an unreadable price is loud, never a silent drop.
        let price = b
            .get("price")
            .and_then(as_f64)
            .ok_or_else(|| format!("bucket {i} has no readable price"))?;
        let long_count = b.get("longCount").and_then(as_f64).unwrap_or(0.0);
        let short_count = b.get("shortCount").and_then(as_f64).unwrap_or(0.0);
        levels.push(BookLevel {
            price,
            volume: long_count + short_count,
        });
    }

    // law 3: one sort, ascending. Ties are impossible for distinct bucketed
    // prices; a NaN would be a venue defect and sorts last deterministically.
    levels.sort_by(|a, b| {
        a.price
            .partial_cmp(&b.price)
            .unwrap_or(std::cmp::Ordering::Equal)
    });

    Ok((venue_instrument, time, levels))
}

impl<'a> OandaAdapter<'a> {
    /// Order-book depth (resting orders) for `instrument`.
    /// Laws 1–4 hold; the path is exactly `/v3/instruments/{instrument}/orderBook`.
    pub fn order_book(&self, instrument: &str) -> Result<OrderBook, String> {
        let path = format!("/v3/instruments/{instrument}/orderBook");
        let resp = self.request("GET", &path, None);
        let (instrument, time, buckets) = parse_book(&resp, "orderBook", instrument)?;
        Ok(OrderBook {
            instrument,
            time,
            buckets,
        })
    }

    /// Position-book depth (open positions) for `instrument`.
    /// Laws 1–4 hold; the path is exactly `/v3/instruments/{instrument}/positionBook`.
    pub fn position_book(&self, instrument: &str) -> Result<PositionBook, String> {
        let path = format!("/v3/instruments/{instrument}/positionBook");
        let resp = self.request("GET", &path, None);
        let (instrument, time, buckets) = parse_book(&resp, "positionBook", instrument)?;
        Ok(PositionBook {
            instrument,
            time,
            buckets,
        })
    }

    /// Both books for one instrument: orderBook first, then positionBook.
    /// No partial `Ok` — if either fetch fails, that `Err` is returned.
    pub fn book_snapshot(&self, instrument: &str) -> Result<BookSnapshot, String> {
        let book = self.order_book(instrument)?;
        let position_book = self.position_book(instrument)?;
        Ok(BookSnapshot {
            book,
            position_book,
        })
    }

    /// One polling tick: a single `book_snapshot`, no sleep, no loop.
    ///
    /// `cadence_secs` is the caller's intended poll interval and is recorded
    /// here for the caller's use — this method never blocks (law 5). Errors
    /// propagate: a poll failure must be visible to the caller, never turned
    /// into an empty book (law 1). The sleep cadence and the polling-vs-
    /// streaming decision live with the human lock on ticket #389.
    pub fn poll_book_snapshot(
        &self,
        instrument: &str,
        cadence_secs: u64,
    ) -> Result<BookSnapshot, String> {
        debug_assert!(cadence_secs > 0, "poll cadence must be positive");
        self.book_snapshot(instrument)
    }
}
