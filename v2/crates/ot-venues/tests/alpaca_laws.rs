//! Alpaca adapter-law tests — the async order reality encoded:
//! accepted ≠ filled (law 1), client_order_id idempotency (law 2),
//! fresh-only quotes (law 3). Canned responses; the venue is never touched.
//! (Unified set: the parent session's 15 laws + the worker's coverage
//! ideas ported to the committed API after a write collision.)

use ot_venues::alpaca::{Keys, AlpacaAdapter};
use ot_venues::transport::{validate_url, Resp, Transport};
use serde_json::{json, Value};
use std::collections::BTreeMap;

struct FakeTransport {
    responses: BTreeMap<String, (u16, String)>,
    pub calls: std::sync::Mutex<Vec<(String, Option<String>)>>,
}

impl FakeTransport {
    fn new(responses: BTreeMap<String, (u16, String)>) -> Self {
        FakeTransport {
            responses,
            calls: std::sync::Mutex::new(Vec::new()),
        }
    }
}

impl Transport for FakeTransport {
    fn request(
        &self,
        _method: &str,
        url: &str,
        body: Option<&str>,
        _headers: &[(String, String)],
    ) -> Result<Resp, String> {
        self.calls
            .lock()
            .unwrap()
            .push((url.to_string(), body.map(String::from)));
        let host_path = url
            .split('/')
            .skip(3)
            .collect::<Vec<_>>()
            .join("/")
            .split('?')
            .next()
            .unwrap_or("")
            .to_string();
        match self.responses.get(&host_path) {
            Some((status, body)) => Ok(Resp {
                status: *status,
                body: body.clone(),
            }),
            None => Ok(Resp {
                status: 404,
                body: r#"{"code":404,"message":"not canned"}"#.into(),
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

fn adapter<'a>(t: &'a FakeTransport) -> AlpacaAdapter<'a> {
    AlpacaAdapter::new(Keys::paper("KEYID", "SECRET"), t)
}

fn canned(pairs: Vec<(&str, u16, Value)>) -> BTreeMap<String, (u16, String)> {
    pairs
        .into_iter()
        .map(|(p, s, v)| (p.to_string(), (s, v.to_string())))
        .collect()
}

// ── LAW 1: accepted ≠ filled ───────────────────────────────────────────────

#[test]
fn post_order_returns_receipt_not_a_fill() {
    let t = FakeTransport::new(canned(vec![(
        "v2/orders",
        200,
        json!({
            "id": "9a2f-uuid", "symbol": "AAPL", "qty": "5",
            "side": "buy", "type": "market", "time_in_force": "gtc",
            "status": "accepted", "client_order_id": "mom-k5-AAPL-1"
        }),
    )]));
    let a = adapter(&t);
    let r = a.place_order("AAPL", "buy", 5.0, "market", None, None, "gtc", "mom-k5-AAPL-1");
    let receipt = r.expect("accepted order");
    assert_eq!(receipt.order_id, "9a2f-uuid");
    assert_eq!(receipt.status, "accepted");
    assert_ne!(receipt.status, "filled", "a POST is never a fill (law 1)");
}

#[test]
fn filled_status_in_post_body_is_refused_loudly() {
    // If Alpaca ever echoes "filled" from a POST (shape change), the
    // adapter refuses rather than trust an unpolled fill.
    let t = FakeTransport::new(canned(vec![(
        "v2/orders",
        200,
        json!({
            "id": "x", "symbol": "AAPL", "status": "filled",
            "filled_avg_price": "100.0", "client_order_id": "c1"
        }),
    )]));
    let a = adapter(&t);
    let err = a
        .place_order("AAPL", "buy", 5.0, "market", None, None, "gtc", "c1")
        .unwrap_err();
    assert!(err.contains("accepted≠filled"), "{err}");
}

#[test]
fn poll_to_terminal_fill() {
    // POST accepted → poll returns None while working → filled with price.
    let t = FakeTransport::new(canned(vec![(
        "v2/orders/9a2f-uuid",
        200,
        json!({"id": "9a2f-uuid", "symbol": "AAPL", "side": "buy",
               "status": "accepted", "filled_qty": "0"}),
    )]));
    let a = adapter(&t);
    let working = a.poll_order("9a2f-uuid").unwrap();
    assert!(working.is_none(), "accepted ≠ filled (law 1)");
    // now terminal:
    let t2 = FakeTransport::new(canned(vec![(
        "v2/orders/9a2f-uuid",
        200,
        json!({"id": "9a2f-uuid", "symbol": "AAPL", "side": "buy",
               "status": "filled", "filled_qty": "5",
               "filled_avg_price": "101.25"}),
    )]));
    let a2 = adapter(&t2);
    let fill = a2.poll_order("9a2f-uuid").unwrap().expect("terminal fill");
    assert!((fill.price - 101.25).abs() < 1e-9);
    assert_eq!(fill.qty, 5.0);
}

#[test]
fn filled_but_unpriced_is_refused() {
    // OANDA unpriced-fill law carried over: a filled order with no price
    // is refused, never surfaced as a priced fill.
    let t = FakeTransport::new(canned(vec![(
        "v2/orders/9a2f-uuid",
        200,
        json!({"id": "9a2f-uuid", "status": "filled", "filled_qty": "5"}),
    )]));
    let a = adapter(&t);
    let err = a.poll_order("9a2f-uuid").unwrap_err();
    assert!(err.contains("unpriced"), "{err}");
}

#[test]
fn rejected_terminal_status_surfaces() {
    let t = FakeTransport::new(canned(vec![(
        "v2/orders/9a2f-uuid",
        200,
        json!({"id": "9a2f-uuid", "status": "rejected"}),
    )]));
    let a = adapter(&t);
    let err = a.poll_order("9a2f-uuid").unwrap_err();
    assert!(err.contains("rejected"), "{err}");
}

// ── LAW 2: client_order_id (owner tag + idempotency) ──────────────────────

#[test]
fn order_body_carries_client_order_id_and_shape() {
    let t = FakeTransport::new(canned(vec![(
        "v2/orders",
        200,
        json!({"id": "x", "status": "accepted", "client_order_id": "mom-k5-AAPL-1"}),
    )]));
    let a = adapter(&t);
    let _ = a.place_order(
        "AAPL", "buy", 5.0, "limit", Some(101.5), None, "gtc", "mom-k5-AAPL-1",
    );
    let calls = t.calls.lock().unwrap();
    let (_, body) = calls
        .iter()
        .find(|(_, b)| b.is_some())
        .expect("POST body captured");
    let order: Value = serde_json::from_str(body.as_deref().unwrap()).unwrap();
    let order = &order["order"];
    assert_eq!(order["symbol"], "AAPL");
    assert_eq!(order["qty"], "5");
    assert_eq!(order["side"], "buy");
    assert_eq!(order["type"], "limit");
    assert_eq!(order["time_in_force"], "gtc");
    assert_eq!(order["limit_price"], "101.5");
    assert_eq!(order["client_order_id"], "mom-k5-AAPL-1");
}

#[test]
fn stop_and_stop_limit_body_shapes() {
    // the worker's coverage idea: every order type carries its own price
    // fields and nothing else
    let accepted = json!({"id": "x", "status": "accepted", "client_order_id": "c"});
    let t = FakeTransport::new(canned(vec![("v2/orders", 200, accepted)]));
    let a = adapter(&t);
    let _ = a.place_order("AAPL", "sell", 3.0, "stop", None, Some(230.25), "gtc", "c-stop");
    let _ = a.place_order(
        "AAPL", "sell", 3.0, "stop_limit", Some(225.5), Some(224.0), "gtc", "c-sl",
    );
    let calls = t.calls.lock().unwrap();
    let bodies: Vec<Value> = calls
        .iter()
        .filter_map(|(_, b)| b.as_deref())
        .map(|b| serde_json::from_str(b).unwrap())
        .collect();
    assert_eq!(bodies.len(), 2);
    let stop = &bodies[0]["order"];
    assert_eq!(stop["type"], "stop");
    assert_eq!(stop["side"], "sell");
    assert_eq!(stop["stop_price"], "230.25");
    assert!(stop.get("limit_price").is_none());
    let sl = &bodies[1]["order"];
    assert_eq!(sl["limit_price"], "225.5");
    assert_eq!(sl["stop_price"], "224.0");
}

#[test]
fn client_order_id_is_required_and_nothing_is_sent() {
    let t = FakeTransport::new(BTreeMap::new());
    let a = adapter(&t);
    let err = a
        .place_order("AAPL", "buy", 5.0, "market", None, None, "gtc", "")
        .unwrap_err();
    assert!(err.contains("client_order_id"), "{err}");
    // the worker's addition: a refused order must not reach the venue
    assert!(t.calls.lock().unwrap().is_empty());
}

#[test]
fn duplicate_client_order_id_rejection_surfaces() {
    // Alpaca rejects a duplicate client_order_id while the original is
    // open — surfaced as a rejection with the venue's message, never as
    // "worked" (retried orders cannot double-fill).
    let t = FakeTransport::new(canned(vec![(
        "v2/orders",
        409,
        json!({"code": 409, "message": "client order id must be unique"}),
    )]));
    let a = adapter(&t);
    let err = a
        .place_order("AAPL", "buy", 5.0, "market", None, None, "gtc", "dup-1")
        .unwrap_err();
    assert!(err.contains("rejected"), "{err}");
}

// ── LAW 3: fresh quotes only ──────────────────────────────────────────────

#[test]
fn quote_always_hits_the_transport_no_cache() {
    // the worker's queue-transport: TWO different prices for the SAME path —
    // the second call must see the second price and hit the transport twice.
    // A stored-price path is unrepresentable here (V1's alpaca_paper.py
    // cached prices 10 minutes; not ported).
    struct QueueTransport {
        quotes: std::sync::Mutex<std::collections::VecDeque<f64>>,
        pub hits: std::sync::Mutex<usize>,
    }
    impl Transport for QueueTransport {
        fn request(
            &self,
            _m: &str,
            _url: &str,
            _b: Option<&str>,
            _h: &[(String, String)],
        ) -> Result<Resp, String> {
            *self.hits.lock().unwrap() += 1;
            let p = self
                .quotes
                .lock()
                .unwrap()
                .pop_front()
                .unwrap_or(0.0);
            Ok(Resp {
                status: 200,
                body: json!({"trade": {"p": p}}).to_string(),
            })
        }
        fn stream(
            &self,
            _u: &str,
            _h: &[(String, String)],
        ) -> Result<Box<dyn Iterator<Item = String> + Send>, String> {
            Ok(Box::new(std::iter::empty()))
        }
    }
    let q = QueueTransport {
        quotes: std::sync::Mutex::new(
            [160.198, 158.82].iter().copied().collect(),
        ),
        hits: std::sync::Mutex::new(0),
    };
    let a = AlpacaAdapter::new(Keys::paper("KEYID", "SECRET"), &q);
    let p1 = a.get_current_price("USD_JPY").unwrap();
    let p2 = a.get_current_price("USD_JPY").unwrap();
    assert!((p1 - 160.198).abs() < 1e-9);
    assert!((p2 - 158.82).abs() < 1e-9, "fresh fetch must see the new mark");
    assert_eq!(*q.hits.lock().unwrap(), 2, "no stored-price path");
}

#[test]
fn no_fresh_price_returns_none() {
    let t = FakeTransport::new(canned(vec![(
        "v2/stocks/AAPL/trades/latest",
        200,
        json!({"trade": {}}),
    )]));
    let a = adapter(&t);
    assert!(a.get_current_price("AAPL").is_none());
}

// ── account / positions / bars ────────────────────────────────────────────

#[test]
fn account_summary_parses() {
    let t = FakeTransport::new(canned(vec![(
        "v2/account",
        200,
        json!({"account_number": "PA-123", "equity": "10250.50", "cash": "5000.10",
               "buying_power": "20000.00", "currency": "USD"}),
    )]));
    let a = adapter(&t);
    let acc = a.account().expect("account");
    assert!((acc.equity - 10250.50).abs() < 1e-9);
    assert!((acc.cash - 5000.10).abs() < 1e-9);
    assert!((acc.buying_power - 20000.0).abs() < 1e-9);
}

#[test]
fn positions_parse() {
    let t = FakeTransport::new(canned(vec![(
        "v2/positions",
        200,
        json!([{"symbol": "AAPL", "qty": "5", "avg_entry_price": "100.0",
                "unrealized_pl": "6.25"}]),
    )]));
    let a = adapter(&t);
    let positions = a.positions().expect("positions");
    assert_eq!(positions.len(), 1);
    assert_eq!(positions[0].symbol, "AAPL");
    assert!((positions[0].qty - 5.0).abs() < 1e-9);
}

#[test]
fn bars_parse_with_timeframe_guard() {
    let t = FakeTransport::new(canned(vec![(
        "v2/stocks/AAPL/bars",
        200,
        json!({"bars": [{"t": "2026-10-07T19:00:00Z", "o": "100.0", "h": "101.0",
                         "l": "99.5", "c": "100.5", "v": 1234}]}),
    )]));
    let a = adapter(&t);
    let bars = a.get_bars("AAPL", "1h", 10).expect("bars");
    assert_eq!(bars.len(), 1);
    assert!((bars[0].close - 100.5).abs() < 1e-9);
    let err = a.get_bars("AAPL", "weekly", 10).unwrap_err();
    assert!(err.contains("unknown timeframe"), "{err}");
}

// ── cancel + guard ────────────────────────────────────────────────────────

#[test]
fn cancel_order_hits_the_path() {
    let t = FakeTransport::new(canned(vec![("v2/orders/9a2f-uuid", 204, json!({}))]));
    let a = adapter(&t);
    let ok = a.cancel_order("9a2f-uuid").expect("cancel");
    assert!(ok);
}

#[test]
fn transport_guard_rejects_non_allowlisted_hosts() {
    assert!(validate_url("https://evil.example.com/v2/account").is_err());
    assert!(validate_url("http://paper-api.alpaca.markets/v2/account").is_err());
    assert!(validate_url("https://paper-api.alpaca.markets/v2/account").is_ok());
    assert!(validate_url("https://api.alpaca.markets/v2/account").is_ok());
    assert!(validate_url("https://data.alpaca.markets/v2/stocks/AAPL/bars").is_ok());
}
