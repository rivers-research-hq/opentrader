//! W2e exit-criterion tests: the headless view-model — SIM feed
//! determinism, paper fills at the NEXT bar, short marks, study overlay
//! (ticket #354).

use ot_terminal::model::{BarsStore, PaperBroker, PaperSide, SimFeed, StudyOverlay};
use std::collections::BTreeMap;

#[test]
fn sim_feed_is_deterministic() {
    let mut a = SimFeed::new("X", 42, 100.0);
    let mut b = SimFeed::new("X", 42, 100.0);
    for _ in 0..50 {
        let ba = a.advance();
        let bb = b.advance();
        assert_eq!(ba.close, bb.close);
        assert_eq!(ba.ts, bb.ts);
    }
}

#[test]
fn sim_feed_stays_positive_and_moves() {
    let mut f = SimFeed::new("X", 7, 100.0);
    let mut moves = 0;
    let mut last = 100.0;
    for _ in 0..200 {
        let b = f.advance();
        assert!(b.close > 0.0);
        assert!(b.low <= b.close.min(b.open) && b.high >= b.close.max(b.open));
        if b.close != last {
            moves += 1;
        }
        last = b.close;
    }
    assert!(moves > 10, "the walk must actually move (SIM, labeled)");
}

#[test]
fn paper_fills_at_the_next_bar() {
    let mut broker = PaperBroker::new(10_000.0, 0.35);
    let bar0 = ot_core::bar::Bar { ts: 1, open: 100.0, high: 101.0, low: 99.0, close: 100.0, volume: 10.0 };
    let bar1 = ot_core::bar::Bar { ts: 2, open: 100.0, high: 101.0, low: 99.0, close: 102.0, volume: 10.0 };
    // place during bar 0 — must NOT fill on bar 0 (decision/fill separation)
    broker.market("X", PaperSide::Long, 10.0);
    broker.on_bar("X", &bar0);
    assert!(broker.positions().is_empty(), "no same-bar fill");
    // bar 1 fills the pending at bar 1's close
    broker.on_bar("X", &bar1);
    assert_eq!(broker.positions().len(), 1);
    assert!((broker.positions()[0].entry - 102.0).abs() < 1e-9, "fill at NEXT bar's close");
    assert!((broker.cash - (10_000.0 - 10.0 * 102.0 - 0.35)).abs() < 1e-9);
}

#[test]
fn paper_close_realizes_exact_pnl() {
    let mut broker = PaperBroker::new(10_000.0, 0.35);
    let b = ot_core::bar::Bar { ts: 1, open: 100.0, high: 101.0, low: 99.0, close: 100.0, volume: 10.0 };
    let b2 = ot_core::bar::Bar { ts: 2, open: 100.0, high: 101.0, low: 99.0, close: 100.0, volume: 10.0 };
    broker.market("X", PaperSide::Long, 10.0);
    broker.on_bar("X", &b); // arm
    broker.on_bar("X", &b2); // fill @100
    let pnl = broker.close(0, 105.0).expect("close");
    // 10·(105−100) − 2 fees
    assert!((pnl - (50.0 - 0.7)).abs() < 1e-9, "pnl {pnl}");
    assert!(broker.positions().is_empty());
    // cash: entry −(1000+0.35), exit +(1050−0.35) → 10_000 + 49.3
    assert!((broker.cash - (10_000.0 + 49.3)).abs() < 1e-9, "cash {}", broker.cash);
}

#[test]
fn paper_short_mark_mirrors() {
    let mut broker = PaperBroker::new(10_000.0, 0.35);
    let b = ot_core::bar::Bar { ts: 1, open: 100.0, high: 101.0, low: 99.0, close: 100.0, volume: 10.0 };
    let b2 = ot_core::bar::Bar { ts: 2, open: 100.0, high: 101.0, low: 99.0, close: 100.0, volume: 10.0 };
    broker.market("X", PaperSide::Short, 10.0);
    broker.on_bar("X", &b); // arm
    broker.on_bar("X", &b2); // fill @100
    // W0 marks: equity = cash − qty·m (the entry proceeds are in cash).
    // At the entry mark the only delta is the entry fee.
    let base = broker.equity(|_| Some(100.0));
    assert!((base - (10_000.0 - 0.35)).abs() < 1e-9, "entry-fee delta only: {base}");
    // price rises 10 → short loses 100
    let adverse = broker.equity(|_| Some(110.0));
    assert!((adverse - (base - 100.0)).abs() < 1e-9, "short loses when price rises");
    // price falls 10 → short gains 100
    let favor = broker.equity(|_| Some(90.0));
    assert!((favor - (base + 100.0)).abs() < 1e-9, "short gains when price falls");
}

#[test]
fn study_overlay_compiles_and_evaluates() {
    let overlay = StudyOverlay::compile(
        "def fast = Average(close, 3);\nplot sig = fast;",
    )
    .expect("compile");
    let bars: Vec<ot_core::bar::Bar> = (0..10)
        .map(|i| ot_core::bar::Bar {
            ts: 1000 + i,
            open: 100.0,
            high: 101.0,
            low: 99.0,
            close: 100.0 + i as f64,
            volume: 10.0,
        })
        .collect();
    let values = overlay.evaluate(&bars, "X").expect("eval");
    assert_eq!(values.len(), 10);
    // SMA(3) at bar 2 = mean(100, 101, 102)
    assert!((values[2] - 101.0).abs() < 1e-9, "{}", values[2]);
    assert!(values[..2].iter().all(|v| v.is_nan()), "warm-up holes");
}

#[test]
fn study_overlay_rejects_bad_source() {
    let err = StudyOverlay::compile("def x = close[-1]; plot p = x;").unwrap_err();
    assert!(err.contains("past-only"), "{err}");
}

#[test]
fn bars_store_roundtrip() {
    let mut store = BarsStore::default();
    let mut f = SimFeed::new("X", 3, 50.0);
    for _ in 0..30 {
        let b = f.advance();
        store.append("X", b);
    }
    assert_eq!(store.frame("X").unwrap().len(), 30);
    assert!(store.last_close("X").is_some());
    assert!(store.frame("Y").is_none());
    let _ = std::collections::BTreeMap::<String, f64>::new();
}
