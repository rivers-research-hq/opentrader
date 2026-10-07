//! The SIM data plane — deterministic bars for the MCP surfaces until the
//! hosted venue-data plane lands (W1 tails). LABELED SIM in every result.

use ot_core::bar::Bar;

/// Deterministic per-symbol bar history, seeded by (symbol, seed) so the
/// same request replays identically — the cache key per spec §9
/// (`(script_rev, inputs, data snapshot)`).
pub struct SimUniverse {
    pub seed: u64,
}

impl SimUniverse {
    pub fn new(seed: u64) -> Self {
        SimUniverse { seed }
    }

    pub fn bars(&self, symbol: &str, n: usize) -> Vec<Bar> {
        let mut state = {
            // seed = hash of symbol + universe seed (FNV-1a)
            let mut h: u64 = self.seed ^ 0xcbf2_9ce4_8422_2325;
            for b in symbol.as_bytes() {
                h ^= *b as u64;
                h = h.wrapping_mul(0x100_0000_01b3);
            }
            h | 1
        };
        let mut price = match symbol {
            s if s.starts_with("EUR") || s.starts_with("GBP") => 1.1,
            s if s.contains("JPY") => 150.0,
            _ => 100.0,
        };
        let mut out = Vec::with_capacity(n);
        for i in 0..n {
            // xorshift64* step
            let mut x = state;
            x ^= x >> 12;
            x ^= x << 25;
            x ^= x >> 27;
            state = x;
            let r = ((x.wrapping_mul(0x2545_F491_4F6C_DD1D) % 2001) as f64) / 1_000_000.0 - 0.001;
            price = (price * (1.0 + r)).max(0.01);
            let spread = price * 0.004;
            out.push(Bar {
                ts: 1_700_000_000 + (i as i64) * 3600,
                open: price * (1.0 - r / 2.0),
                high: price + spread,
                low: price - spread,
                close: price,
                volume: 1000.0 + (x % 4000) as f64,
            });
        }
        out
    }

    /// The alpha universe: 6 SIM symbols.
    pub const SYMBOLS: [&str; 6] = ["SIM_EURUSD", "SIM_GBPUSD", "SIM_USDJPY", "SIM_AUDUSD", "SIM_USDCAD", "SIM_SPX"];
}
