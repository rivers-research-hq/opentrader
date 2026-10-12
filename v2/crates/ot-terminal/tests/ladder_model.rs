use ot_terminal::ladder::{LadderModel, LadderState, LadderRow};
use ot_venues::oanda::book::{BookLevel, BookSnapshot, OrderBook, PositionBook};

/// Helper to create a minimal PositionBook (unused but required for snapshot)
fn dummy_position_book() -> PositionBook {
    PositionBook {
        instrument: String::new(),
        time: String::new(),
        buckets: vec![],
    }
}

/// Helper to create a BookSnapshot from a list of prices and volumes
fn make_snapshot(instrument: &str, time: &str, prices: Vec<f64>, volumes: Vec<f64>) -> BookSnapshot {
    let buckets: Vec<BookLevel> = prices.iter().zip(volumes.iter())
        .map(|(p, v)| BookLevel { price: *p, volume: *v })
        .collect();
    
    BookSnapshot {
        book: OrderBook {
            instrument: instrument.to_string(),
            time: time.to_string(),
            buckets,
        },
        position_book: dummy_position_book(),
    }
}

#[test]
fn rows_are_the_books_buckets_exactly() {
    // L1: Parity
    let prices = vec![1.1000, 1.1001, 1.1002, 1.1003, 1.1004];
    let volumes = vec![10.0, 20.0, 30.0, 40.0, 50.0];
    let snap = make_snapshot("EUR_USD", "2023-01-01T00:00:00Z", prices.clone(), volumes.clone());
    
    let model = LadderModel::from_snapshot(&snap, 100);
    
    assert_eq!(model.rows.len(), 5);
    
    // Parity: the multiset of (price, volume) pairs must match the book
    // exactly. f64 has no Eq/Hash, so compare sorted vectors — this also
    // catches duplicates, which a HashSet would have silently collapsed.
    let mut model_pairs: Vec<(f64, f64)> = model.rows.iter().map(|r| (r.price, r.volume)).collect();
    let mut book_pairs: Vec<(f64, f64)> = snap.book.buckets.iter().map(|b| (b.price, b.volume)).collect();
    model_pairs.sort_by(|a, b| a.partial_cmp(b).unwrap());
    book_pairs.sort_by(|a, b| a.partial_cmp(b).unwrap());
    assert_eq!(model_pairs, book_pairs, "rendered rows must be exactly the venue's buckets");
}

#[test]
fn rows_are_price_descending() {
    // L2: Order
    // Wire order is ascending: 1.1000, 1.1001, 1.1002
    let snap = make_snapshot("EUR_USD", "2023-01-01T00:00:00Z", 
                             vec![1.1000, 1.1001, 1.1002], 
                             vec![10.0, 10.0, 10.0]);
    
    let model = LadderModel::from_snapshot(&snap, 100);
    
    // Ladder order must be descending
    for i in 0..model.rows.len() - 1 {
        assert!(model.rows[i].price > model.rows[i+1].price, 
                "Rows must be descending: {} vs {}", model.rows[i].price, model.rows[i+1].price);
    }
}

#[test]
fn tick_is_the_smallest_adjacent_gap() {
    // L3: Tick
    // Gaps: 1.1000->1.1010 (0.0010), 1.1010->1.1025 (0.0015), 1.1025->1.1030 (0.0005)
    let snap = make_snapshot("EUR_USD", "2023-01-01T00:00:00Z", 
                             vec![1.1000, 1.1010, 1.1025, 1.1030], 
                             vec![10.0, 10.0, 10.0, 10.0]);
    
    let model = LadderModel::from_snapshot(&snap, 100);
    
    // computed differences are not exact in binary floating point
    let tick = model.tick.expect("tick");
    assert!((tick - 0.0005).abs() < 1e-12, "tick was {tick}");
}

#[test]
fn tick_is_none_for_a_single_level() {
    // L3: Tick edge case
    let snap = make_snapshot("EUR_USD", "2023-01-01T00:00:00Z", 
                             vec![1.1000], 
                             vec![10.0]);
    
    let model = LadderModel::from_snapshot(&snap, 100);
    
    assert!(model.tick.is_none());
}

#[test]
fn mid_is_none_for_a_single_level() {
    // L4: Mid edge case
    let snap = make_snapshot("EUR_USD", "2023-01-01T00:00:00Z", 
                             vec![1.1000], 
                             vec![10.0]);
    
    let model = LadderModel::from_snapshot(&snap, 100);
    
    assert!(model.mid.is_none());
}

#[test]
fn mid_is_the_two_centre_levels() {
    // L4: Mid calculation
    // 4 levels: 1.0, 1.1, 1.2, 1.3. Centre pair: 1.1, 1.2. Mid: 1.15
    let snap = make_snapshot("EUR_USD", "2023-01-01T00:00:00Z", 
                             vec![1.0, 1.1, 1.2, 1.3], 
                             vec![10.0, 10.0, 10.0, 10.0]);
    
    let model = LadderModel::from_snapshot(&snap, 100);
    
    assert_eq!(model.mid, Some(1.15));
}

#[test]
fn truncation_is_reported_not_silent() {
    // L5: Truncation
    let prices: Vec<f64> = (1..=10).map(|i| 1.0 + i as f64 * 0.01).collect();
    let volumes: Vec<f64> = vec![10.0; 10];
    let snap = make_snapshot("EUR_USD", "2023-01-01T00:00:00Z", prices, volumes);
    
    // Test max_rows = 4
    let model = LadderModel::from_snapshot(&snap, 4);
    assert_eq!(model.rows.len(), 4);
    assert_eq!(model.truncated, 6);
    
    // Test max_rows = 0
    let model_zero = LadderModel::from_snapshot(&snap, 0);
    assert_eq!(model_zero.rows.len(), 0);
    assert_eq!(model_zero.truncated, 10);
}

#[test]
fn empty_book_is_not_an_error() {
    // L6: Empty book
    let snap = make_snapshot("EUR_USD", "2023-01-01T00:00:00Z", vec![], vec![]);
    
    let model = LadderModel::from_snapshot(&snap, 40);
    
    assert!(model.rows.is_empty());
    assert_eq!(model.truncated, 0);
    assert!(model.mid.is_none());
    assert!(model.tick.is_none());
}

#[test]
fn set_error_keeps_the_last_good_model() {
    // L8: Error handling
    let mut state = LadderState::new("EUR_USD");
    
    // Set a valid snapshot
    let snap = make_snapshot("EUR_USD", "2023-01-01T00:00:00Z", 
                             vec![1.1000, 1.1001], 
                             vec![10.0, 20.0]);
    state.set_snapshot(snap);
    assert!(state.model.is_some());
    assert!(state.error.is_none());
    
    // Simulate an error
    state.set_error("venue 503".to_string());
    assert!(state.model.is_some()); // Model preserved
    assert!(state.error.as_ref().unwrap().contains("503"));
    
    // Recover with new snapshot
    let snap2 = make_snapshot("EUR_USD", "2023-01-01T00:00:01Z", 
                              vec![1.1000, 1.1002], 
                              vec![10.0, 20.0]);
    state.set_snapshot(snap2);
    assert!(state.error.is_none()); // Error cleared
}

#[test]
fn nan_prices_do_not_panic() {
    // L9: Safety with NaN/Inf
    use std::f64::{NAN, INFINITY};
    
    // NaN/inf between two finite levels leaves NO valid adjacent pair;
    // put the junk AFTER the finite pair so a real gap exists.
    let prices = vec![1.1000, 1.1010, NAN, INFINITY];
    let volumes = vec![10.0, 10.0, 10.0, 10.0];
    let snap = make_snapshot("EUR_USD", "2023-01-01T00:00:00Z", prices, volumes);
    
    // Should not panic
    let model = LadderModel::from_snapshot(&snap, 100);
    
    // Rows should still contain the data (L1: Parity)
    assert_eq!(model.rows.len(), 4);
    
    // Tick should ignore non-finite comparisons
    // Valid gap is 1.1010 - 1.1000 = 0.0010 (since others are skipped)
    let tick = model.tick.expect("tick from the finite adjacent pair");
    assert!((tick - 0.0010).abs() < 1e-12, "tick was {tick}");
}
