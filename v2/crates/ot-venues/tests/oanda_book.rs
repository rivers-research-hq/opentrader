//! OANDA book laws — ticket #389 exit criterion (REST snapshot vs parsed depth
//! parity). All responses are canned; the venue is NEVER touched by test code.

use ot_venues::oanda::{Keys, OandaAdapter};
use ot_venues::transport::{Resp, Transport};
use serde_json::{json, Value};
use std::collections::BTreeMap;

/// Canned-response transport: path → (status, body). Unmatched paths → 404
/// with an errorMessage (the venue said no). Same shape as oanda_laws.rs so
/// the two suites stay comparable.
struct FakeTransport {
    responses: BTreeMap<String, (u16, String)>,
    pub calls: std::sync::Mutex<Vec<String>>,
}

impl FakeTransport {
    fn new(responses: BTreeMap<String, (u16, String)>) -> Self {
        FakeTransport {
            responses,
            calls: std::sync::Mutex::new(Vec::new()),
        }
    }
    fn calls(&self) -> Vec<String> {
        self.calls.lock().unwrap().clone()
    }
}

impl Transport for FakeTransport {
    fn request(
        &self,
        _method: &str,
        url: &str,
        _body: Option<&str>,
        _headers: &[(String, String)],
    ) -> Result<Resp, String> {
        self.calls.lock().unwrap().push(url.to_string());
        let path = url.split(".oanda.com").nth(1).unwrap_or("").to_string();
        match self.responses.get(&path) {
            Some((status, body)) => Ok(Resp {
                status: *status,
                body: body.clone(),
            }),
            None => Ok(Resp {
                status: 404,
                body: r#"{"errorMessage":"not canned"}"#.into(),
            }),
        }
    }

    fn stream(
        &self,
        _url: &str,
        _headers: &[(String, String)],
    ) -> Result<Box<dyn Iterator<Item = String> + Send>, String> {
        Ok(Box::new(std::iter::empty()))
    }
}

fn canned(pairs: Vec<(&str, u16, Value)>) -> BTreeMap<String, (u16, String)> {
    pairs
        .into_iter()
        .map(|(p, s, v)| (p.to_string(), (s, v.to_string())))
        .collect()
}

fn adapter<'a>(t: &'a FakeTransport) -> OandaAdapter<'a> {
    OandaAdapter::new(Keys::practice("tok", "101-004-1234567-001"), t)
}

/// A v20-shaped orderBook body: numbers quoted as strings, buckets unsorted.
fn order_book_body() -> Value {
    json!({
        "orderBook": {
            "instrument": "EUR_USD",
            "time": "2026-10-12T15:00:00.000000000Z",
            "bucketWidth": "0.00050",
            "buckets": [
                {"price": "1.10100", "longCount": "50", "shortCount": "25"},
                {"price": "1.09900", "longCount": "200", "shortCount": "100"},
                {"price": "1.10000", "longCount": "100", "shortCount": "50"}
            ]
        }
    })
}

fn position_book_body() -> Value {
    json!({
        "positionBook": {
            "instrument": "EUR_USD",
            "time": "2026-10-12T15:00:00.000000000Z",
            "bucketWidth": "0.00050",
            "buckets": [
                {"price": "1.10000", "shortCount": "50"},
                {"price": "1.09900", "longCount": "100", "shortCount": "100"}
            ]
        }
    })
}

// ── 1. parsing + order + volume (v20 string-numbers) ──────────────────────

#[test]
fn order_book_parses_bucketed_depth() {
    let t = FakeTransport::new(canned(vec![(
        "/v3/instruments/EUR_USD/orderBook",
        200,
        order_book_body(),
    )]));
    let a = adapter(&t);
    let book = a.order_book("EUR_USD").expect("parses");

    assert_eq!(book.instrument, "EUR_USD");
    assert_eq!(book.time, "2026-10-12T15:00:00.000000000Z");
    // sorted ascending by price, not venue order
    let prices: Vec<f64> = book.buckets.iter().map(|b| b.price).collect();
    assert_eq!(prices, vec![1.099, 1.100, 1.101]);
    // volume == longCount + shortCount
    let vols: Vec<f64> = book.buckets.iter().map(|b| b.volume).collect();
    assert_eq!(vols, vec![300.0, 150.0, 75.0]);
}

#[test]
fn position_book_treats_missing_count_as_zero() {
    let t = FakeTransport::new(canned(vec![(
        "/v3/instruments/EUR_USD/positionBook",
        200,
        position_book_body(),
    )]));
    let a = adapter(&t);
    let book = a.position_book("EUR_USD").expect("parses");
    assert_eq!(book.buckets.len(), 2);
    assert_eq!(book.buckets[0].price, 1.099);
    assert_eq!(book.buckets[0].volume, 200.0);
    // 1.10000 bucket omits longCount → shortCount only
    assert_eq!(book.buckets[1].price, 1.100);
    assert_eq!(book.buckets[1].volume, 50.0);
}

// ── 2. truthfulness: errors are Err, never an empty book (law 1) ──────────

#[test]
fn http_error_is_err_not_empty_book() {
    let t = FakeTransport::new(canned(vec![(
        "/v3/instruments/EUR_USD/orderBook",
        404,
        json!({"errorMessage": "not found"}),
    )]));
    let a = adapter(&t);
    let err = a.order_book("EUR_USD").expect_err("404 must be Err");
    assert!(err.contains("404"), "error must name the status: {err}");
    assert!(err.contains("not found"));
}

#[test]
fn transport_failure_empty_object_is_err_not_empty_book() {
    // request() returns {} when the transport itself fails — that is a
    // failure, NOT a book with zero levels.
    let t = FakeTransport::new(canned(vec![("/v3/instruments/EUR_USD/orderBook", 200, json!({}))]));
    let a = adapter(&t);
    assert!(a.order_book("EUR_USD").is_err());
}

#[test]
fn malformed_payload_is_err_not_panic() {
    // 200 with a non-JSON body → request() yields {} → Err (never a panic).
    let t = FakeTransport::new(BTreeMap::from([(
        "/v3/instruments/EUR_USD/orderBook".to_string(),
        (200, "not json".to_string()),
    )]));
    let a = adapter(&t);
    assert!(a.order_book("EUR_USD").is_err());
}

#[test]
fn unreadable_price_is_loud_not_silently_dropped() {
    let t = FakeTransport::new(canned(vec![(
        "/v3/instruments/EUR_USD/orderBook",
        200,
        json!({"orderBook": {"instrument": "EUR_USD", "time": "t",
                             "buckets": [{"price": "??", "longCount": "1"}]}}),
    )]));
    let a = adapter(&t);
    let err = a.order_book("EUR_USD").expect_err("unreadable price must be loud");
    assert!(err.contains("bucket 0"), "error must localise the bucket: {err}");
}

// ── 3. snapshot composition + endpoint discipline ─────────────────────────

#[test]
fn snapshot_paths_are_exactly_the_two_v20_endpoints() {
    let t = FakeTransport::new(canned(vec![
        ("/v3/instruments/EUR_USD/orderBook", 200, order_book_body()),
        ("/v3/instruments/EUR_USD/positionBook", 200, position_book_body()),
    ]));
    let a = adapter(&t);
    let snap = a.book_snapshot("EUR_USD").expect("both books");
    assert_eq!(snap.book.buckets.len(), 3);
    assert_eq!(snap.position_book.buckets.len(), 2);

    let calls = t.calls();
    assert_eq!(calls.len(), 2, "exactly one call per book: {calls:?}");
    assert!(calls[0].ends_with("/v3/instruments/EUR_USD/orderBook"), "{calls:?}");
    assert!(calls[1].ends_with("/v3/instruments/EUR_USD/positionBook"), "{calls:?}");
}

#[test]
fn snapshot_is_err_when_either_book_is_missing() {
    // only the orderBook is canned → the positionBook 404s → whole snapshot Err
    let t = FakeTransport::new(canned(vec![(
        "/v3/instruments/EUR_USD/orderBook",
        200,
        order_book_body(),
    )]));
    let a = adapter(&t);
    assert!(
        a.book_snapshot("EUR_USD").is_err(),
        "no partial Ok — a missing book is an error"
    );
}

// ── 4. polling shape (law 5) ──────────────────────────────────────────────

#[test]
fn poll_book_snapshot_is_one_tick_no_sleep_no_synthesis() {
    let t = FakeTransport::new(canned(vec![
        ("/v3/instruments/EUR_USD/orderBook", 200, order_book_body()),
        ("/v3/instruments/EUR_USD/positionBook", 200, position_book_body()),
    ]));
    let a = adapter(&t);
    let started = std::time::Instant::now();
    let snap = a.poll_book_snapshot("EUR_USD", 2).expect("one tick");
    // no sleep in this call (a real poll loop sleeps in the caller)
    assert!(started.elapsed() < std::time::Duration::from_secs(1));
    assert_eq!(snap.book.buckets.len(), 3);
    assert_eq!(t.calls().len(), 2, "one tick = exactly one call per book");
}

#[test]
fn poll_failure_is_err_not_an_empty_book() {
    // the 2026-09-02 phantom-cache class: a failed fetch must never be
    // reported as a valid empty book.
    let t = FakeTransport::new(canned(vec![(
        "/v3/instruments/EUR_USD/orderBook",
        503,
        json!({"errorMessage": "service unavailable"}),
    )]));
    let a = adapter(&t);
    assert!(a.poll_book_snapshot("EUR_USD", 2).is_err());
}
