use crate::engine::Side;
use std::collections::BTreeMap;

/// Represents a position for what-if analysis.
#[derive(Debug, Clone)]
pub struct WhatifPosition {
    pub sym: String,
    pub side: Side,
    pub qty: f64,
    pub entry: f64,
    pub entry_fee: f64,
}

/// Represents a single leg's result in a what-if scenario.
#[derive(Debug, Clone)]
pub struct WhatifLeg {
    pub sym: String,
    pub price: f64,
    pub pnl: f64,
}

/// Calculates P&L for each position given a snapshot of market prices.
///
/// Missing price for a symbol results in that position being skipped.
/// Exit fee is calculated as: qty * price * fee_pct if fee_pct > 0.0, else flat_fee.
pub fn whatif_at(
    positions: &[WhatifPosition],
    prices: &BTreeMap<String, f64>,
    fee_pct: f64,
    flat_fee: f64,
) -> Vec<WhatifLeg> {
    let mut legs = Vec::with_capacity(positions.len());
    for pos in positions {
        let exit_price = match prices.get(&pos.sym) {
            Some(&p) => p,
            None => continue, // Skip missing prices
        };

        let exit_fee = if fee_pct > 0.0 {
            pos.qty * exit_price * fee_pct
        } else {
            flat_fee
        };

        let pnl = match pos.side {
            Side::Long => pos.qty * (exit_price - pos.entry) - pos.entry_fee - exit_fee,
            Side::Short => pos.qty * (pos.entry - exit_price) - pos.entry_fee - exit_fee,
        };

        legs.push(WhatifLeg {
            sym: pos.sym.clone(),
            price: exit_price,
            pnl,
        });
    }
    legs
}

/// Sweeps one symbol's price from lo to hi across steps and returns legs for all positions.
///
/// If steps < 2, returns an empty vector.
pub fn whatif_sweep(
    positions: &[WhatifPosition],
    sym: &str,
    lo: f64,
    hi: f64,
    steps: usize,
    fee_pct: f64,
    flat_fee: f64,
) -> Vec<WhatifLeg> {
    // Sweep one symbol's price across [lo, hi] (inclusive, `steps` points).
    // Per step, EVERY position gets a leg: the swept symbol at the scenario
    // price, every other symbol at its entry price (the "no change"
    // assumption that portfolio_curve also documents). Step-major ordering.
    if steps < 2 {
        return Vec::new();
    }
    let step_size = (hi - lo) / (steps as f64 - 1.0);
    let mut result = Vec::with_capacity(steps * positions.len());
    for i in 0..steps {
        let price = lo + step_size * i as f64;
        let mut prices = BTreeMap::new();
        prices.insert(sym.to_string(), price);
        for pos in positions {
            if pos.sym != sym {
                prices.entry(pos.sym.clone()).or_insert(pos.entry);
            }
        }
        result.extend(whatif_at(positions, &prices, fee_pct, flat_fee));
    }
    result
}

pub fn portfolio_curve(
    positions: &[WhatifPosition],
    sym: &str,
    lo: f64,
    hi: f64,
    steps: usize,
    fee_pct: f64,
    flat_fee: f64,
) -> Vec<f64> {
    if steps < 2 {
        return Vec::new();
    }

    let step_size = (hi - lo) / (steps as f64 - 1.0);
    let mut curve = Vec::with_capacity(steps);

    for i in 0..steps {
        let price = lo + step_size * i as f64;
        
        // Calculate static P&L for positions not being swept
        let mut total_pnl = 0.0;
        
        // We need to calculate P&L for non-swept positions at their entry price
        // And for swept positions at the current swept price
        
        // To reuse logic, we can construct a price map
        let mut prices = BTreeMap::new();
        prices.insert(sym.to_string(), price);
        
        for pos in positions {
            if pos.sym != sym {
                prices.entry(pos.sym.clone()).or_insert(pos.entry);
            }
        }
        
        for pos in positions {
            let exit_price = match prices.get(&pos.sym) {
                Some(&p) => p,
                None => continue,
            };

            let exit_fee = if fee_pct > 0.0 {
                pos.qty * exit_price * fee_pct
            } else {
                flat_fee
            };

            let pnl = match pos.side {
                Side::Long => pos.qty * (exit_price - pos.entry) - pos.entry_fee - exit_fee,
                Side::Short => pos.qty * (pos.entry - exit_price) - pos.entry_fee - exit_fee,
            };
            
            total_pnl += pnl;
        }
        
        curve.push(total_pnl);
    }
    
    curve
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::engine::Side;

    fn make_pos(sym: &str, side: Side, qty: f64, entry: f64, entry_fee: f64) -> WhatifPosition {
        WhatifPosition {
            sym: sym.to_string(),
            side,
            qty,
            entry,
            entry_fee,
        }
    }

    #[test]
    fn test_long_pnl_matches_closed_form() {
        let pos = make_pos("AAPL", Side::Long, 100.0, 150.0, 10.0);
        let mut prices = BTreeMap::new();
        prices.insert("AAPL".to_string(), 160.0);
        
        let legs = whatif_at(&[pos], &prices, 0.0, 5.0); // flat_fee = 5.0
        
        assert_eq!(legs.len(), 1);
        let leg = &legs[0];
        // Expected: 100 * (160 - 150) - 10 - 5 = 1000 - 15 = 985
        assert!((leg.pnl - 985.0).abs() < f64::EPSILON);
        assert_eq!(leg.sym, "AAPL");
        assert!((leg.price - 160.0).abs() < f64::EPSILON);
    }

    #[test]
    fn test_short_pnl_matches_closed_form() {
        let pos = make_pos("TSLA", Side::Short, 50.0, 200.0, 20.0);
        let mut prices = BTreeMap::new();
        prices.insert("TSLA".to_string(), 180.0);
        
        let legs = whatif_at(&[pos], &prices, 0.0, 10.0); // flat_fee = 10.0
        
        assert_eq!(legs.len(), 1);
        let leg = &legs[0];
        // Expected: 50 * (200 - 180) - 20 - 10 = 1000 - 30 = 970
        assert!((leg.pnl - 970.0).abs() < f64::EPSILON);
    }

    #[test]
    fn test_missing_symbol_price_is_skipped() {
        let pos1 = make_pos("AAPL", Side::Long, 100.0, 150.0, 0.0);
        let pos2 = make_pos("GOOG", Side::Long, 100.0, 2000.0, 0.0);
        
        let mut prices = BTreeMap::new();
        prices.insert("AAPL".to_string(), 160.0);
        // GOOG is missing
        
        let legs = whatif_at(&[pos1, pos2], &prices, 0.0, 0.0);
        
        assert_eq!(legs.len(), 1);
        assert_eq!(legs[0].sym, "AAPL");
    }

    #[test]
    fn test_sweep_step_count_and_inclusivity() {
        let pos = make_pos("AAPL", Side::Long, 100.0, 100.0, 0.0);
        
        // 3 steps: lo=100, hi=120 -> 100, 110, 120
        let legs = whatif_sweep(&[pos.clone()], "AAPL", 100.0, 120.0, 3, 0.0, 0.0);
        
        assert_eq!(legs.len(), 3);
        
        // Step 0: price 100, pnl 0
        assert!((legs[0].price - 100.0).abs() < f64::EPSILON);
        assert!((legs[0].pnl - 0.0).abs() < f64::EPSILON);
        
        // Step 1: price 110, pnl 1000
        assert!((legs[1].price - 110.0).abs() < f64::EPSILON);
        assert!((legs[1].pnl - 1000.0).abs() < f64::EPSILON);
        
        // Step 2: price 120, pnl 2000
        assert!((legs[2].price - 120.0).abs() < f64::EPSILON);
        assert!((legs[2].pnl - 2000.0).abs() < f64::EPSILON);
        
        // Test steps < 2
        let legs_empty = whatif_sweep(&[pos], "AAPL", 100.0, 120.0, 1, 0.0, 0.0);
        assert!(legs_empty.is_empty());
    }

    #[test]
    fn test_portfolio_curve_equals_sum_of_legs() {
        let pos1 = make_pos("AAPL", Side::Long, 100.0, 100.0, 0.0);
        let pos2 = make_pos("GOOG", Side::Long, 10.0, 2000.0, 0.0);
        
        let steps = 5;
        let lo = 100.0;
        let hi = 120.0;
        
        let curve = portfolio_curve(&[pos1.clone(), pos2.clone()], "AAPL", lo, hi, steps, 0.0, 0.0);
        
        for i in 0..steps {
            let price = lo + (hi - lo) * i as f64 / (steps as f64 - 1.0);
            
            // Calculate expected sum manually
            let mut expected_sum = 0.0;
            
            // P&L for GOOG (static at entry)
            // GOOG entry 2000, price 2000 -> pnl 0
            let goog_pnl = 10.0 * (2000.0 - 2000.0) - 0.0 - 0.0;
            expected_sum += goog_pnl;
            
            // P&L for AAPL (swept)
            let aapl_pnl = 100.0 * (price - 100.0) - 0.0 - 0.0;
            expected_sum += aapl_pnl;
            
            assert!((curve[i] - expected_sum).abs() < f64::EPSILON);
        }
    }
}
