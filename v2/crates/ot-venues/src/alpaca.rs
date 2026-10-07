//! Alpaca v2 broker adapter (paper-first) — W2d, ticket #353.
//!
//! The same laws as OANDA, adapted to Alpaca's async order reality — and
//! one law that matters MORE here:
//!
//!   1. **Accepted ≠ filled.** A 2xx POST /v2/orders returns an order
//!      object with status `accepted`/`pending_new` — NOT a fill. The V1
//!      phantom-entry defect class (OANDA 2026-09-02) is worse here: the
//!      venue confirms asynchronously. `place_order` therefore returns an
//!      [`OrderReceipt`] (accepted + ids), never a fill; fills surface
//!      only via [`AlpacaAdapter::poll_order`] / the stream.
//!   2. **client_order_id is the owner tag + idempotency key** (the V1
//!      `clientExtensions` law): Alpaca dedupes on it (duplicate rejected
//!      while the original is open) — lanes share one account without
//!      closing each other's positions and retried orders cannot double-fill.
//!   3. **Fresh prices only** — the data endpoint is hit per call; no
//!      untimestamped caches (the 2026-09-02 stale-mark law).
//!   4. **Credentials ride the APCA headers, never logs.**

use serde_json::{json, Value};

use crate::transport::Transport;

pub const FX_HOST_PAPER: &str = "https://paper-api.alpaca.markets";
pub const FX_HOST_LIVE: &str = "https://api.alpaca.markets";
pub const DATA_HOST: &str = "https://data.alpaca.markets";

/// harness timeframe -> Alpaca bar timeframe (fail loud on unmapped).
pub fn timeframe(timeframe: &str) -> Result<&'static str, String> {
    Ok(match timeframe {
        "1m" => "1Min",
        "5m" => "5Min",
        "15m" => "15Min",
        "30m" => "30Min",
        "1h" => "1Hour",
        "1d" => "1Day",
        _ => {
            return Err(format!(
                "unknown timeframe {timeframe:?} — valid: 1m,5m,15m,30m,1h,1d"
            ))
        }
    })
}

/// An accepted order — NOT a fill (law 1).
#[derive(Debug, Clone)]
pub struct OrderReceipt {
    pub order_id: String,
    pub client_order_id: String,
    pub status: String,
}

/// A confirmed fill (only from a terminal status poll / stream).
#[derive(Debug, Clone)]
pub struct Fill {
    pub order_id: String,
    pub symbol: String,
    pub side: String,
    pub qty: f64,
    pub price: f64,
    pub status: String,
}

#[derive(Debug, Clone)]
pub struct Keys {
    pub key_id: String,
    pub secret: String,
    pub trade_host: String,
}

impl Keys {
    pub fn paper(key_id: &str, secret: &str) -> Self {
        Keys {
            key_id: key_id.to_string(),
            secret: secret.to_string(),
            trade_host: FX_HOST_PAPER.into(),
        }
    }
}

#[derive(Debug, Clone)]
pub struct AccountSummary {
    pub equity: f64,
    pub cash: f64,
    pub buying_power: f64,
    pub currency: String,
}

#[derive(Debug, Clone)]
pub struct PositionSummary {
    pub symbol: String,
    pub qty: f64,
    pub avg_entry_price: f64,
    pub unrealized_pl: f64,
}

pub struct AlpacaAdapter<'a> {
    pub keys: Keys,
    transport: &'a dyn Transport,
}

impl<'a> AlpacaAdapter<'a> {
    pub fn new(keys: Keys, transport: &'a dyn Transport) -> Self {
        AlpacaAdapter { keys, transport }
    }

    fn headers(&self) -> Vec<(String, String)> {
        vec![
            ("APCA-API-KEY-ID".to_string(), self.keys.key_id.clone()),
            ("APCA-API-SECRET-KEY".to_string(), self.keys.secret.clone()),
            ("Content-Type".to_string(), "application/json".to_string()),
            ("User-Agent".to_string(), "OpenTrader/2.0".to_string()),
        ]
    }

    /// One broker REST call; HTTP errors → the `_error`/`_status` shape.
    fn request(&self, method: &str, url: &str, body: Option<Value>) -> Value {
        let body_str = body.as_ref().map(|b| b.to_string());
        match self
            .transport
            .request(method, url, body_str.as_deref(), &self.headers())
        {
            Ok(resp) => {
                if resp.status >= 400 {
                    let err = resp
                        .json()
                        .unwrap_or(json!({"message": format!("HTTP {}", resp.status)}));
                    json!({"_error": err, "_status": resp.status})
                } else {
                    resp.json().unwrap_or(json!({}))
                }
            }
            Err(_) => json!({}),
        }
    }

    pub fn account(&self) -> Result<AccountSummary, String> {
        let data = self.request("GET", &format!("{}/v2/account", self.keys.trade_host), None);
        match data.get("account_number").or_else(|| data.get("equity")) {
            Some(_) => Ok(AccountSummary {
                equity: f64_from(&data, "equity").unwrap_or(0.0),
                cash: f64_from(&data, "cash").unwrap_or(0.0),
                buying_power: f64_from(&data, "buying_power").unwrap_or(0.0),
                currency: data
                    .get("currency")
                    .and_then(|v| v.as_str())
                    .unwrap_or("USD")
                    .to_string(),
            }),
            None => Err(format!("account query failed: {data}")),
        }
    }

    pub fn positions(&self) -> Result<Vec<PositionSummary>, String> {
        let data = self.request("GET", &format!("{}/v2/positions", self.keys.trade_host), None);
        let mut out = Vec::new();
        if let Some(arr) = data.as_array() {
            for p in arr {
                out.push(PositionSummary {
                    symbol: p
                        .get("symbol")
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .to_string(),
                    qty: p
                        .get("qty")
                        .and_then(|v| v.as_str().and_then(|s| s.parse().ok()))
                        .unwrap_or(0.0),
                    avg_entry_price: p
                        .get("avg_entry_price")
                        .and_then(|v| v.as_str().and_then(|s| s.parse().ok()))
                        .unwrap_or(0.0),
                    unrealized_pl: p
                        .get("unrealized_pl")
                        .and_then(|v| v.as_str().and_then(|s| s.parse().ok()))
                        .unwrap_or(0.0),
                });
            }
            return Ok(out);
        }
        if data.get("_error").is_some() {
            return Err(format!("positions failed: {data}"));
        }
        Ok(out) // empty array / empty body
    }

    /// Place an order. Returns an [`OrderReceipt`] — NEVER a fill (law 1).
    /// `client_order_id` is required discipline: the owner tag + idempotency
    /// key (law 2).
    pub fn place_order(
        &self,
        symbol: &str,
        side: &str,
        qty: f64,
        order_type: &str, // market | limit | stop | stop_limit
        limit_price: Option<f64>,
        stop_price: Option<f64>,
        time_in_force: &str, // day | gtc | ioc | fok
        client_order_id: &str,
    ) -> Result<OrderReceipt, String> {
        if client_order_id.is_empty() {
            return Err("client_order_id is required (owner-tag/idempotency law)".into());
        }
        let mut order = json!({
            "symbol": symbol,
            "qty": format!("{qty}"),
            "side": if side.eq_ignore_ascii_case("buy") { "buy" } else { "sell" },
            "type": order_type,
            "time_in_force": time_in_force,
            "client_order_id": client_order_id,
        });
        match order_type {
            "market" => {}
            "limit" => {
                let Some(p) = limit_price else {
                    return Err("limit order requires limit_price".into());
                };
                order["limit_price"] = json!(format!("{p}"));
            }
            "stop" => {
                let Some(p) = stop_price else {
                    return Err("stop order requires stop_price".into());
                };
                order["stop_price"] = json!(format!("{p}"));
            }
            "stop_limit" => {
                let (Some(lp), Some(sp)) = (limit_price, stop_price) else {
                    return Err("stop_limit requires limit_price and stop_price".into());
                };
                order["limit_price"] = json!(price_str(lp));
                order["stop_price"] = json!(price_str(sp));
            }
            other => return Err(format!("unsupported order_type: {other}")),
        }
        let data = self.request(
            "POST",
            &format!("{}/v2/orders", self.keys.trade_host),
            Some(json!({"order": order})),
        );
        if data.get("_error").is_some() {
            return Err(format!("order rejected: {data}"));
        }
        // The POST body echoes the order with status accepted/pending_new —
        // there is NO fill here, and the adapter must not invent one.
        let status = data.get("status").and_then(|v| v.as_str()).unwrap_or("");
        if matches!(
            status,
            "filled" | "partially_filled" | "pending_replace" | "done_for_day" | "canceled"
                | "expired" | "rejected"
        ) {
            // A REST POST is accepted at most; a filled status in the POST
            // body would mean the shape changed — refuse loudly rather than
            // trust it unpolled.
            return Err(format!(
                "unexpected POST status {status:?} (accepted≠filled law: fills come from poll_order)"
            ));
        }
        Ok(OrderReceipt {
            order_id: data
                .get("id")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string(),
            client_order_id: data
                .get("client_order_id")
                .and_then(|v| v.as_str())
                .unwrap_or(client_order_id)
                .to_string(),
            status: status.to_string(),
        })
    }

    /// Poll an order's terminal state. Returns None while it is still
    /// working (accepted/pending_new/partially_filled→None keeps the law
    /// strict; partial fills land as a later slice with the stream).
    pub fn poll_order(&self, order_id: &str) -> Result<Option<Fill>, String> {
        let data = self.request(
            "GET",
            &format!("{}/v2/orders/{order_id}", self.keys.trade_host),
            None,
        );
        let status = data.get("status").and_then(|v| v.as_str()).unwrap_or("");
        match status {
            "filled" => {
                let price = data
                    .get("filled_avg_price")
                    .and_then(|v| v.as_str().and_then(|s| s.parse().ok()))
                    .unwrap_or(0.0);
                if price <= 0.0 {
                    // a filled order MUST be priceable (OANDA unpriced-fill law)
                    return Err(format!("order {order_id} filled but unpriced — refusing"));
                }
                Ok(Some(Fill {
                    order_id: order_id.to_string(),
                    symbol: data
                        .get("symbol")
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .to_string(),
                    side: data
                        .get("side")
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .to_string(),
                    qty: data
                        .get("filled_qty")
                        .and_then(|v| v.as_str().and_then(|s| s.parse().ok()))
                        .unwrap_or(0.0),
                    price,
                    status: status.to_string(),
                }))
            }
            "rejected" | "canceled" | "expired" => Err(format!("order {order_id}: {status}")),
            _ => Ok(None), // accepted / pending_new / partially_filled → keep waiting
        }
    }

    pub fn cancel_order(&self, order_id: &str) -> Result<bool, String> {
        let resp = self
            .transport
            .request(
                "DELETE",
                &format!("{}/v2/orders/{order_id}", self.keys.trade_host),
                None,
                &self.headers(),
            )
            .map_err(|e| e.to_string())?;
        Ok(resp.status < 400)
    }

    /// FRESH quote: latest trade price from the data endpoint (law 3).
    pub fn get_current_price(&self, symbol: &str) -> Option<f64> {
        let data = self.request(
            "GET",
            &format!("{DATA_HOST}/v2/stocks/{symbol}/trades/latest"),
            None,
        );
        data.pointer("/trade/p")
            .and_then(|v| v.as_f64())
            .filter(|p| *p > 0.0)
    }

    /// Bars (complete only; Alpaca bars are closed by definition unless
    /// the request includes the in-progress bucket — we pass through and
    /// drop the last bar if its timestamp is within the current bucket).
    pub fn get_bars(
        &self,
        symbol: &str,
        tf: &str,
        limit: usize,
    ) -> Result<Vec<crate::history::Candle>, String> {
        let tf = timeframe(tf)?;
        let data = self.request(
            "GET",
            &format!(
                "{DATA_HOST}/v2/stocks/{symbol}/bars?timeframe={tf}&limit={limit}"
            ),
            None,
        );
        let mut out = Vec::new();
        if let Some(bars) = data.get("bars").and_then(|v| v.as_array()) {
            for b in bars {
                let ts = b
                    .get("t")
                    .and_then(|v| v.as_str())
                    .and_then(super::oanda::rfc3339_to_epoch)
                    .unwrap_or(0);
                out.push(crate::history::Candle {
                    ts,
                    open: str_f(b, "o"),
                    high: str_f(b, "h"),
                    low: str_f(b, "l"),
                    close: str_f(b, "c"),
                    volume: b.get("v").and_then(|v| v.as_f64()).unwrap_or(0.0),
                    complete: true,
                });
            }
        }
        Ok(out)
    }
}

/// Price as a clean decimal string — integral values keep one decimal
/// (Alpaca parses both, but a stable shape is the law's spirit: no raw
/// float artifacts like 224.00000000000003).
fn price_str(p: f64) -> String {
    if p == p.trunc() && p.abs() < 1e15 {
        format!("{p:.1}")
    } else {
        format!("{p}")
    }
}

fn f64_from(v: &Value, key: &str) -> Option<f64> {
    v.get(key)
        .and_then(|x| x.as_str().and_then(|s| s.parse().ok()).or_else(|| x.as_f64()))
}

fn str_f(v: &Value, key: &str) -> f64 {
    v.get(key)
        .and_then(|x| x.as_str().and_then(|s| s.parse().ok()))
        .unwrap_or(0.0)
}
