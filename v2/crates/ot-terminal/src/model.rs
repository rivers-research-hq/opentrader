//! The headless view-model — everything testable without a display.
//!
//! Alpha scope (ticket #354): deterministic SIM feed (labeled SIM — no
//! randomness in venue paths), bars store, paper broker (fills at the
//! NEXT bar close — the engine contract's spirit), v2script study overlay
//! (first plot line → chart series).

use ot_core::bar::Bar;
use std::collections::BTreeMap;

// ── SIM feed ───────────────────────────────────────────────────────────────

/// Deterministic seeded random-walk feed. This is a SIMULATED data source
/// for the alpha — every consumer must label it SIM; wiring a real venue
/// stream is the W1-tails/venue-wave work.
pub struct SimFeed {
    state: u64,
    pub symbol: String,
    pub price: f64,
    pub tick: u64,
}

impl SimFeed {
    /// xorshift64* — deterministic, no external rng dep.
    fn next(&mut self) -> u64 {
        let mut x = self.state;
        x ^= x >> 12;
        x ^= x << 25;
        x ^= x >> 27;
        self.state = x;
        x.wrapping_mul(0x2545F4914F6CDD1D)
    }

    pub fn new(symbol: &str, seed: u64, start_price: f64) -> Self {
        SimFeed {
            state: seed | 1,
            symbol: symbol.to_string(),
            price: start_price,
            tick: 0,
        }
    }

    /// Advance one bar: geometric random walk with per-symbol drift.
    pub fn advance(&mut self) -> Bar {
        let r = (self.next() % 2001) as f64 / 1_000_000.0 - 0.001; // [-0.1%, +0.1%]
        self.price = (self.price * (1.0 + r)).max(0.01);
        let spread = self.price * 0.004;
        let bar = Bar {
            ts: 1_700_000_000 + (self.tick as i64) * 3600,
            open: self.price * (1.0 - r / 2.0),
            high: self.price + spread,
            low: self.price - spread,
            close: self.price,
            volume: 1000.0 + (self.next() % 4000) as f64,
        };
        self.tick += 1;
        bar
    }
}

// ── bars store ─────────────────────────────────────────────────────────────

/// Per-symbol bar history (the terminal's data plane; venue-stream wiring
/// lands with the W1 tails).
#[derive(Default)]
pub struct BarsStore {
    pub frames: BTreeMap<String, Vec<Bar>>,
}

impl BarsStore {
    pub fn append(&mut self, symbol: &str, bar: Bar) {
        self.frames.entry(symbol.to_string()).or_default().push(bar);
    }

    pub fn frame(&self, symbol: &str) -> Option<&[Bar]> {
        self.frames.get(symbol).map(|v| v.as_slice())
    }

    pub fn last_close(&self, symbol: &str) -> Option<f64> {
        self.frame(symbol).and_then(|f| f.last()).map(|b| b.close)
    }
}

// ── paper broker ───────────────────────────────────────────────────────────

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PaperSide {
    Long,
    Short,
}

#[derive(Debug, Clone)]
pub struct PaperPosition {
    pub symbol: String,
    pub side: PaperSide,
    pub qty: f64,
    pub entry: f64,
    pub entry_ts: i64,
}

/// Alpha paper broker: market orders REST at the next bar close (the
/// engine contract's spirit — decisions never fill on the bar that formed
/// them). One net position per symbol; per-side fees (V1's fixed model).
pub struct PaperBroker {
    pub cash: f64,
    pub fee_per_side: f64,
    positions: Vec<PaperPosition>,
    /// resting market orders — filled on the next `on_bar`
    pending: Vec<(String, PaperSide, f64)>, // symbol, side, qty
}

impl PaperBroker {
    pub fn new(cash: f64, fee_per_side: f64) -> Self {
        PaperBroker {
            cash,
            fee_per_side,
            positions: Vec::new(),
            pending: Vec::new(),
        }
    }

    /// Place a market order — fills on the NEXT bar (decision/fill
    /// separation).
    pub fn market(&mut self, symbol: &str, side: PaperSide, qty: f64) {
        self.pending.push((symbol.to_string(), side, qty));
    }

    /// Advance the broker one bar: fill pendings at THIS bar's close
    /// (they were placed on a previous bar — the separation held), mark
    /// the book.
    pub fn on_bar(&mut self, symbol: &str, bar: &Bar) {
        let pendings: Vec<_> = self
            .pending
            .iter()
            .enumerate()
            .filter(|(i, _)| self.pending[*i].0 == symbol)
            .map(|(i, _)| i)
            .collect();
        for _ in &pendings {
            let (sym, side, qty) = self.pending.remove(0);
            if sym != symbol {
                self.pending.push((sym, side, qty));
                continue;
            }
            let fee = self.fee_per_side;
            match side {
                PaperSide::Long => {
                    let cost = qty * bar.close + fee;
                    if cost > self.cash {
                        continue; // insufficient cash — order dropped (alpha)
                    }
                    self.cash -= cost;
                    self.positions.push(PaperPosition {
                        symbol: sym.clone(),
                        side: PaperSide::Long,
                        qty,
                        entry: bar.close,
                        entry_ts: bar.ts,
                    });
                }
                PaperSide::Short => {
                    // alpha paper: short proceeds net of fee; liability marked
                    self.cash += qty * bar.close - fee;
                    self.positions.push(PaperPosition {
                        symbol: sym.clone(),
                        side: PaperSide::Short,
                        qty,
                        entry: bar.close,
                        entry_ts: bar.ts,
                    });
                }
            }
        }
    }

    pub fn positions(&self) -> &[PaperPosition] {
        &self.positions
    }

    /// Close a position at the given price (button-driven in the alpha).
    pub fn close(&mut self, index: usize, price: f64) -> Option<f64> {
        if index >= self.positions.len() {
            return None;
        }
        let p = self.positions.remove(index);
        let fee = self.fee_per_side;
        let pnl = match p.side {
            PaperSide::Long => p.qty * (price - p.entry) - 2.0 * fee,
            PaperSide::Short => p.qty * (p.entry - price) - 2.0 * fee,
        };
        match p.side {
            PaperSide::Long => self.cash += p.qty * price - fee,
            PaperSide::Short => self.cash -= p.qty * price + fee,
        }
        Some(pnl)
    }

    /// Marked equity: cash + unrealized (long mark +; short mark −).
    pub fn equity(&self, mark: impl Fn(&str) -> Option<f64>) -> f64 {
        self.cash
            + self
                .positions
                .iter()
                .map(|p| {
                    let m = mark(&p.symbol).unwrap_or(p.entry);
                    p.qty
                        * match p.side {
                            PaperSide::Long => m - p.entry,
                            PaperSide::Short => p.entry - m,
                        }
                })
                .sum::<f64>()
            + self
                .positions
                .iter()
                .map(|p| match p.side {
                    PaperSide::Long => p.qty * p.entry,
                    PaperSide::Short => -p.qty * p.entry,
                })
                .sum::<f64>()
    }
}

// ── study overlay ──────────────────────────────────────────────────────────

/// Compile + evaluate a v2script study over a frame; returns the FIRST
/// plot's values (the alpha's overlay line) and the compile error path.
pub struct StudyOverlay {
    pub source: String,
    pub plan: ot_script::CompilePlan,
}

impl StudyOverlay {
    pub fn compile(source: &str) -> Result<Self, String> {
        let plan = ot_script::compile(source)?;
        Ok(StudyOverlay {
            source: source.to_string(),
            plan,
        })
    }

    pub fn evaluate(&self, frame: &[Bar], symbol: &str) -> Result<Vec<f64>, String> {
        let req = ot_script::ScriptRequest {
            source: self.source.clone(),
            symbol: symbol.to_string(),
            timeframe: "1h".into(),
            inputs: BTreeMap::new(),
        };
        let out = ot_script::eval(
            &req,
            &self.plan,
            &ot_script::eval::Frame { bars: frame },
        )?;
        Ok(out
            .plots
            .first()
            .map(|p| p.values.clone())
            .unwrap_or_default())
    }
}
