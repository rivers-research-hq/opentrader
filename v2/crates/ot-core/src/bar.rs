//! Bars and per-symbol series. A `Series` is ts-sorted (ascending) so every
//! lookup is a binary search — no hash-order nondeterminism.

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Bar {
    pub ts: i64,
    pub open: f64,
    pub high: f64,
    pub low: f64,
    pub close: f64,
    pub volume: f64,
}

/// Per-symbol bar series, ts-ascending. Mirrors V1's per-symbol
/// `closes[s]`/`highs[s]`/`lows[s]` pandas frames: lookups are by exact ts
/// (`idx in closes[s].index` → `series.get(ts).is_some()`), never by
/// positional alignment against the master index.
#[derive(Debug, Clone, Default)]
pub struct Series {
    bars: Vec<Bar>,
}

impl Series {
    pub fn from_bars(mut bars: Vec<Bar>) -> Self {
        bars.sort_by_key(|b| b.ts);
        // Reject duplicate timestamps (a V1 frame index guarantee).
        debug_assert!(bars.windows(2).all(|w| w[0].ts < w[1].ts));
        Series { bars }
    }

    pub fn len(&self) -> usize {
        self.bars.len()
    }

    pub fn is_empty(&self) -> bool {
        self.bars.is_empty()
    }

    pub fn bars(&self) -> &[Bar] {
        &self.bars
    }

    /// Exact-ts lookup (V1's `idx in index` / `.loc[idx]` semantics).
    pub fn get(&self, ts: i64) -> Option<&Bar> {
        self.bars
            .binary_search_by(|b| b.ts.cmp(&ts))
            .ok()
            .map(|i| &self.bars[i])
    }

    pub fn closes(&self) -> impl Iterator<Item = f64> + '_ {
        self.bars.iter().map(|b| b.close)
    }

    /// V1's `closes[s].iloc[-1]` — the LAST recorded close (delist price).
    pub fn last_close(&self) -> Option<f64> {
        self.bars.last().map(|b| b.close)
    }

    /// Index of `ts` in the series, if present.
    pub fn pos(&self, ts: i64) -> Option<usize> {
        self.bars.binary_search_by(|b| b.ts.cmp(&ts)).ok()
    }
}
