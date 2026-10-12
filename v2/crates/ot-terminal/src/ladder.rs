//! # FX Ladder Model
//!
//! This module provides a pure data model for rendering an FX order book ladder.
//! It consumes an `ot_venues::oanda::book::BookSnapshot` and produces a `LadderModel`
//! suitable for UI rendering.
//!
//! ## Laws
//!
//! - **L1 (Parity):** Rows are exactly the snapshot's `book.buckets`. No synthesis, merging, or averaging.
//! - **L2 (Order):** Rows are sorted price-DESCENDING. The wire order is ascending; we reverse it.
//! - **L3 (Tick):** `tick` is the smallest positive price difference between adjacent wire (ascending) levels.
//! - **L4 (Mid):** `mid` is the average of the two centremost levels (even count) or middle + neighbour (odd count).
//! - **L5 (Truncation):** `truncated` reports the number of rows dropped. 0 means unlimited (but we cap at max_rows).
//! - **L6 (Empty):** Zero buckets yields empty rows, not an error.
//! - **L7 (Source):** `instrument` and `time` come from `snap.book`, never local clock.
//! - **L8 (Error Handling):** `set_error` preserves the last good model. `set_snapshot` clears error.
//! - **L9 (Safety):** No panics on malformed data (NaN, inf, empty). Degenerate inputs handled gracefully.
//! - **L10 (Purity):** No egui dependencies in the model. Pure data.

use std::f64::NAN;

/// A single row in the ladder representing one price level from the book.
#[derive(Debug, Clone, PartialEq)]
pub struct LadderRow {
    /// The price level.
    pub price: f64,
    /// The volume at this level.
    pub volume: f64,
}

/// The computed model derived from a venue snapshot.
///
/// This struct contains no logic, only data ready for the UI painter.
#[derive(Debug, Clone, PartialEq)]
pub struct LadderModel {
    /// The instrument name, sourced from the venue snapshot.
    pub instrument: String,
    /// The timestamp string, sourced from the venue snapshot.
    pub time: String,
    /// The rows to render, sorted price-DESCENDING (L2).
    pub rows: Vec<LadderRow>,
    /// The mid-price derived from the two centremost levels (L4).
    /// UI-DERIVED. Not a venue quote.
    pub mid: Option<f64>,
    /// The tick size (smallest adjacent gap) (L3).
    pub tick: Option<f64>,
    /// The number of rows dropped due to `max_rows` limit (L5).
    pub truncated: usize,
}

/// State holder for the ladder component.
///
/// Manages the current model and any error states without panicking.
pub struct LadderState {
    /// The current valid model.
    pub model: Option<LadderModel>,
    /// The raw snapshot for potential re-processing or debugging.
    pub snapshot: Option<ot_venues::oanda::book::BookSnapshot>,
    /// An error message if the last update failed.
    pub error: Option<String>,
    /// The instrument currently being watched.
    pub instrument: String,
    /// Maximum number of rows to display.
    pub max_rows: usize,
}

impl LadderModel {
    /// Constructs a `LadderModel` from a venue snapshot.
    ///
    /// ## Implementation Details
    /// - **L1:** Copies all buckets into rows.
    /// - **L2:** Reverses the ascending wire order to descending ladder order.
    /// - **L3:** Computes tick from adjacent ascending pairs.
    /// - **L4:** Computes mid from centremost levels.
    /// - **L5:** Truncates rows if count exceeds `max_rows` and records drop count.
    /// - **L6:** Handles empty books gracefully.
    /// - **L7:** Copies instrument/time from snapshot.
    /// - **L9:** Skips NaN/Inf prices during tick/mid calculation.
    pub fn from_snapshot(snap: &ot_venues::oanda::book::BookSnapshot, max_rows: usize) -> LadderModel {
        let instrument = snap.book.instrument.clone();
        let time = snap.book.time.clone();
        
        // L1: Parity - copy all buckets
        let mut rows: Vec<LadderRow> = snap.book.buckets.iter().map(|b| LadderRow {
            price: b.price,
            volume: b.volume,
        }).collect();

        // L2: Order - reverse ascending wire to descending ladder
        rows.reverse();

        // L5: Truncation
        let truncated = if rows.len() > max_rows {
            rows.len() - max_rows
        } else {
            0
        };
        
        // If max_rows is 0, we drop everything (L5 spec: 0 means drop everything)
        if max_rows == 0 {
            rows.clear();
        } else if rows.len() > max_rows {
            rows.truncate(max_rows);
        }

        // L3 & L4: Compute Tick and Mid from the ORIGINAL full set (before truncation)
        // to ensure accuracy of market metrics even if UI is truncated.
        let full_rows = &snap.book.buckets; // ascending order
        
        let tick = compute_tick(full_rows);
        let mid = compute_mid(full_rows);

        LadderModel {
            instrument,
            time,
            rows,
            mid,
            tick,
            truncated,
        }
    }
}

/// Computes the tick size: smallest positive difference between adjacent ascending levels.
///
/// Skips NaN and Inf values. Returns None if fewer than 2 valid levels.
fn compute_tick(levels: &[ot_venues::oanda::book::BookLevel]) -> Option<f64> {
    if levels.len() < 2 {
        return None;
    }

    let mut min_gap = f64::MAX;
    let mut found = false;

    for i in 0..levels.len() - 1 {
        let p1 = levels[i].price;
        let p2 = levels[i+1].price;

        // L9: Skip non-finite prices
        if !p1.is_finite() || !p2.is_finite() {
            continue;
        }

        let gap = (p2 - p1).abs();
        if gap > 0.0 {
            if gap < min_gap {
                min_gap = gap;
            }
            found = true;
        }
    }

    if found {
        Some(min_gap)
    } else {
        None
    }
}

/// Computes the mid-price from the two centremost levels.
///
/// - Even count: average of the two middle elements.
/// - Odd count: average of the middle element and its right neighbor.
///
/// Skips NaN/Inf. Returns None if fewer than 2 valid levels.
fn compute_mid(levels: &[ot_venues::oanda::book::BookLevel]) -> Option<f64> {
    if levels.len() < 2 {
        return None;
    }

    let len = levels.len();
    let mid_idx = len / 2;

    // Select the two levels to average
    let (idx1, idx2) = if len % 2 == 0 {
        // Even: 0,1,2,3 -> mid is between 1 and 2. Indices 1 and 2.
        (mid_idx - 1, mid_idx)
    } else {
        // Odd: 0,1,2,3,4 -> mid is 2. Neighbour is 3.
        (mid_idx, mid_idx + 1)
    };

    let p1 = levels[idx1].price;
    let p2 = levels[idx2].price;

    // L9: Handle NaN/Inf
    if !p1.is_finite() || !p2.is_finite() {
        return None;
    }

    Some((p1 + p2) / 2.0)
}

impl LadderState {
    /// Creates a new LadderState for the given instrument.
    ///
    /// Default max_rows is 40.
    pub fn new(instrument: &str) -> Self {
        LadderState {
            model: None,
            snapshot: None,
            error: None,
            instrument: instrument.to_string(),
            max_rows: 40,
        }
    }

    /// Updates the state with a new snapshot.
    ///
    /// Rebuilds the model and clears any previous error (L8).
    pub fn set_snapshot(&mut self, snap: ot_venues::oanda::book::BookSnapshot) {
        self.snapshot = Some(snap.clone());
        self.error = None; // L8: Clear error on success
        self.model = Some(LadderModel::from_snapshot(&snap, self.max_rows));
    }

    /// Records an error without clearing the current model (L8).
    ///
    /// This ensures the trader sees the last known good ladder even if the feed fails.
    pub fn set_error(&mut self, msg: String) {
        self.error = Some(msg);
        // Do NOT clear model. Do NOT synthesize empty model.
    }
}
