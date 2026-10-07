//! Universe — per-symbol series plus the master index, mirroring V1's
//! `master = next(iter(closes.values())).index` with a deterministic
//! definition: the master is the ts-sorted union? No — V1 uses the FIRST
//! symbol's index. V2 defines (documented spec note): **master = the sorted
//! ts union of all series**; per-symbol lookups stay exact-ts (date-guard
//! semantics preserved), so symbols not covering a master bar are simply
//! absent from lookups — exactly V1's `if sig_idx in feat[s].index` guard.
//! (With the curated universe where all series share one index, this is
//! identical to V1; with ragged series it is a superset of V1's master but
//! every guard behaves the same because per-symbol coverage is what gates.)

use crate::bar::{Bar, Series};
use std::collections::BTreeMap;

pub type Symbol = String;

#[derive(Debug, Clone, Default)]
pub struct Universe {
    /// Sorted master timestamps (the engine's event clock).
    pub master: Vec<i64>,
    /// Per-symbol series, symbols in sorted order.
    pub series: BTreeMap<Symbol, Series>,
    /// Per-symbol volumes (V1 `vols[s]`), same length as the series.
    pub vols: BTreeMap<Symbol, Vec<f64>>,
}

impl Universe {
    pub fn from_series(series: BTreeMap<Symbol, Series>, vols: BTreeMap<Symbol, Vec<f64>>) -> Self {
        let mut ts: Vec<i64> = series
            .values()
            .flat_map(|s| s.bars().iter().map(|b| b.ts))
            .collect();
        ts.sort_unstable();
        ts.dedup();
        Universe {
            master: ts,
            series,
            vols,
        }
    }

    pub fn syms(&self) -> Vec<Symbol> {
        self.series.keys().cloned().collect()
    }

    pub fn get(&self, sym: &str) -> Option<&Series> {
        self.series.get(sym)
    }

    pub fn master_pos(&self, ts: i64) -> Option<usize> {
        self.master.binary_search(&ts).ok()
    }
}

/// Convenience test/fuilder helper: one bar per symbol.
pub fn bar(ts: i64, o: f64, h: f64, l: f64, c: f64, v: f64) -> Bar {
    Bar {
        ts,
        open: o,
        high: h,
        low: l,
        close: c,
        volume: v,
    }
}
