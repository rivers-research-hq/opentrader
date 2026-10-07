//! OANDA v20 adapter — a faithful semantic port of V1
//! `exchange/oanda.py` (locked #339: "faithful semantic port" — these
//! semantics encode hard-won defect knowledge; re-inventing them re-runs
//! the defects).
//!
//! The adapter laws (each traces to a recorded incident):
//!   1. **Truthful fills**: no `orderFillTransaction` in the POST response
//!      means REJECTED — the venue cancels (STOP_LOSS_ON_FILL_LOSS) or
//!      refuses instead of filling into a guaranteed stop-out. Assuming
//!      "POST ok = filled" wrote phantom ledger rows + a phantom position
//!      (2026-09-02).
//!   2. **Fresh prices only**: `get_current_price` always hits the pricing
//!      endpoint; no untimestamped cache fall-back. A write-once
//!      never-expiring cache quoted 160.198 while the venue traded 158.82
//!      → stops set off a stale mark → STOP_LOSS_ON_FILL_LOSS.
//!   3. **Priced fills only**: a fill MUST be priceable (fill price →
//!      fullVWAP → the venue's own transaction record → fresh quote).
//!      Unpriced fills corrupted every FIFO/PnL consumer (2026-09-09/10).
//!   4. **Owner tags**: every order carries `tradeClientExtensions`
//!      (id/tag/comment) — lanes share one account without closing each
//!      other's positions; attribution never guesses from fill size.
//!   5. **displayPrecision prices**: prices are formatted at the
//!      instrument's precision as clean strings — raw floats killed every
//!      h1-mom USD_JPY entry with
//!      TAKE_PROFIT_ON_FILL_PRICE_PRECISION_EXCEEDED (09-02/03).
//!   6. **Fail-loud timeframes**: an unmapped timeframe is an error, never
//!      a silent default (a silent H1 default faked daily data).

pub mod stream;

use crate::transport::Transport;
use serde_json::{json, Value};

pub const FX_MAJORS: &[&str] = &[
    "EUR_USD", "GBP_USD", "USD_JPY", "USD_CHF", "GBP_JPY", "AUD_USD", "USD_CAD",
];

/// harness timeframe -> OANDA granularity (fail loud on unmapped).
pub fn granularity(timeframe: &str) -> Result<&'static str, String> {
    Ok(match timeframe {
        "1m" => "M1",
        "5m" => "M5",
        "15m" => "M15",
        "30m" => "M30",
        "1h" => "H1",
        "4h" => "H4",
        "1d" => "D",
        "1w" => "W",
        _ => return Err(format!(
            "unknown timeframe {timeframe:?} — valid: 1m,5m,15m,30m,1h,4h,1d,1w"
        )),
    })
}

/// Python's round (half-to-even), for `int(round(quantity))`.
fn py_round(v: f64) -> i64 {
    let r = v.round();
    if (v - v.trunc()).abs() == 0.5 && r % 2.0 != 0.0 {
        let down = v.trunc();
        let up = if v > 0.0 { down + 1.0 } else { down - 1.0 };
        return (if down % 2.0 == 0.0 { down } else { up }) as i64;
    }
    r as i64
}

/// V1 `_fmt_price`: format at the instrument's displayPrecision, HALF-UP,
/// as a clean decimal string (raw floats are venue rejections waiting to
/// happen — law 5).
pub fn fmt_price(price: f64, digits: u32) -> String {
    // Shortest-repr string (V1: Decimal(str(price))), then half-up at `digits`.
    let s = format!("{price}");
    let (int_part, frac) = match s.split_once('.') {
        Some((i, f)) => (i.to_string(), f.to_string()),
        None => (s, String::new()),
    };
    let neg = int_part.starts_with('-');
    let int_digits: String = int_part.trim_start_matches('-').to_string();
    if digits == 0 {
        let first_frac = frac.chars().next().unwrap_or('0');
        let mut base = int_digits;
        if first_frac >= '5' {
            base = (base.parse::<u128>().unwrap_or(0) + 1).to_string();
        }
        return if neg && base != "0" { format!("-{base}") } else { base };
    }
    let d = digits as usize;
    let mut out_frac: String = frac.chars().take(d).collect();
    while out_frac.len() < d {
        out_frac.push('0');
    }
    let round_digit = frac.chars().nth(d).unwrap_or('0');
    let mut carry = round_digit >= '5';
    let mut digits_v: Vec<u8> = out_frac.bytes().collect();
    if carry {
        let mut k = digits_v.len();
        while k > 0 && carry {
            k -= 1;
            if digits_v[k] == b'9' {
                digits_v[k] = b'0';
            } else {
                digits_v[k] += 1;
                carry = false;
            }
        }
        let mut int_v = int_digits.parse::<u128>().unwrap_or(0);
        if carry {
            int_v += 1;
        }
        let s = format!("{int_v}.{}", String::from_utf8(digits_v).unwrap());
        return if neg { format!("-{s}") } else { s };
    }
    let s = format!("{int_digits}.{out_frac}");
    if neg { format!("-{s}") } else { s }
}

/// displayPrecision fallback: JPY-quote pairs 3, other majors 5 (until
/// connect() provides the venue's own metadata — V1 `_price_digits`).
pub fn fallback_precision(symbol: &str) -> u32 {
    if symbol.ends_with("_JPY") {
        3
    } else {
        5
    }
}

/// The truthful order result (mirrors V1's `OrderResult` semantics).
#[derive(Debug, Clone)]
pub struct OrderResult {
    pub order_id: String,
    pub filled: bool,
    pub fill_price: f64,
    pub filled_qty: f64,
    pub reject_reason: Option<String>,
    pub raw: Value,
}

#[derive(Debug, Clone)]
pub struct Keys {
    pub token: String,
    pub account_id: String,
    pub host: String,
}

impl Keys {
    pub fn practice(token: &str, account_id: &str) -> Self {
        Keys {
            token: token.to_string(),
            account_id: account_id.to_string(),
            host: "https://api-fxpractice.oanda.com".into(),
        }
    }

    /// Load the V1 gitignored practice credentials (the live-key wiring,
    /// W1 tails): {token, account_id, host}. The file is read once; the
    /// token is never printed, logged, or committed (the secrets law).
    pub fn from_v1_config(path: &std::path::Path) -> Result<Self, String> {
        let text = std::fs::read_to_string(path)
            .map_err(|e| format!("oanda keys unreadable at {}: {e}", path.display()))?;
        let v: Value = serde_json::from_str(&text)
            .map_err(|e| format!("oanda keys corrupt: {e}"))?;
        let token = v
            .get("token")
            .and_then(|t| t.as_str())
            .filter(|t| !t.is_empty())
            .ok_or_else(|| "oanda keys: missing/empty token".to_string())?;
        let account_id = v
            .get("account_id")
            .and_then(|t| t.as_str())
            .filter(|t| !t.is_empty())
            .ok_or_else(|| "oanda keys: missing/empty account_id".to_string())?;
        let host = v
            .get("host")
            .and_then(|t| t.as_str())
            .unwrap_or("https://api-fxpractice.oanda.com");
        Ok(Keys {
            token: token.to_string(),
            account_id: account_id.to_string(),
            host: host.to_string(),
        })
    }
}

/// One open venue trade — the trade ID is the venue's own (needed for
/// the trade-specific close — W1-tails-3).
#[derive(Debug, Clone)]
pub struct OpenTradeInfo {
    pub symbol: String,
    pub tag: String,
    pub units: f64,
    pub trade_id: String,
}

pub struct OandaAdapter<'a> {
    pub keys: Keys,
    transport: &'a dyn Transport,
    /// Per-instrument displayPrecision from /instruments (connect).
    pub precision: std::collections::BTreeMap<String, u32>,
    /// Local mirror (paper semantics — write-through only; the venue is
    /// authoritative for positions/balance/PnL questions).
    pub mirror_cash: f64,
    pub mirror_positions: std::collections::BTreeMap<String, f64>,
    pub mirror_cost_basis: std::collections::BTreeMap<String, f64>,
}

impl<'a> OandaAdapter<'a> {
    pub fn new(keys: Keys, transport: &'a dyn Transport) -> Self {
        OandaAdapter {
            keys,
            transport,
            precision: Default::default(),
            mirror_cash: 100_000.0,
            mirror_positions: Default::default(),
            mirror_cost_basis: Default::default(),
        }
    }

    /// One v20 REST call. HTTP errors → the V1 `_error`/`_status` shape;
    /// transport failures → `{}` (both are "venue said no").
    /// Public for the read-only export bin (W1 tails) — GETs only there.
    pub fn request(&self, method: &str, path: &str, body: Option<Value>) -> Value {
        let url = format!("{}{}", self.keys.host, path);
        let mut headers = vec![
            ("Authorization".to_string(), format!("Bearer {}", self.keys.token)),
            ("Content-Type".to_string(), "application/json".to_string()),
            ("User-Agent".to_string(), "OpenTrader/2.0".to_string()),
        ];
        if body.is_some() && method != "GET" {
            headers.push(("Accept-Datetime-Format".to_string(), "RFC3339".to_string()));
        }
        let body_str = body.as_ref().map(|b| b.to_string());
        match self
            .transport
            .request(method, &url, body_str.as_deref(), &headers)
        {
            Ok(resp) => {
                if resp.status >= 400 {
                    let err = resp
                        .json()
                        .unwrap_or(json!({"errorMessage": format!("HTTP {}", resp.status)}));
                    json!({"_error": err, "_status": resp.status})
                } else {
                    resp.json().unwrap_or(json!({}))
                }
            }
            Err(_) => json!({}),
        }
    }

    pub fn connect(&mut self) -> Result<(), String> {
        if self.keys.token.is_empty() || self.keys.account_id.is_empty() {
            return Err("no credentials".into());
        }
        let data = self.request("GET", &format!("/v3/accounts/{}", self.keys.account_id), None);
        if data.get("account").is_none() {
            return Err(format!("account query failed: {data}"));
        }
        let insts = self.request(
            "GET",
            &format!("/v3/accounts/{}/instruments?state=ENABLED", self.keys.account_id),
            None,
        );
        let mut enabled = Vec::new();
        if let Some(arr) = insts.get("instruments").and_then(|v| v.as_array()) {
            for i in arr {
                if let Some(name) = i.get("name").and_then(|v| v.as_str()) {
                    enabled.push(name.to_string());
                    if let Some(dp) = i.get("displayPrecision").and_then(|v| v.as_u64()) {
                        self.precision.insert(name.to_string(), dp as u32);
                    }
                }
            }
        }
        if !enabled.is_empty() {
            // Intersect base majors with the account's enabled instruments
            // (unused-field cleanup happens in W1's live wiring).
        }
        Ok(())
    }

    fn price_digits(&self, symbol: &str) -> u32 {
        *self.precision.get(symbol).unwrap_or(&fallback_precision(symbol))
    }

    /// Extract a representative price from a Price object (ask > mid > bid).
    /// Used by the live streaming path (W1 tails).
    #[allow(dead_code)]
    fn quote_price(p: &Value) -> f64 {
        for side in ["ask", "mid", "bid"] {
            if let Some(px) = p
                .get(side)
                .and_then(|s| s.get("price"))
                .and_then(|v| v.as_str())
                .and_then(|s| s.parse::<f64>().ok())
            {
                return px;
            }
        }
        0.0
    }

    /// Parse the account pricing response ({instrument: price}) — depth
    /// arrays, not flat bid/ask (V1 `_parse_pricing`).
    fn parse_pricing(data: &Value) -> std::collections::BTreeMap<String, f64> {
        let mut out = std::collections::BTreeMap::new();
        if let Some(prices) = data.get("prices").and_then(|v| v.as_array()) {
            for p in prices {
                let Some(sym) = p.get("instrument").and_then(|v| v.as_str()) else {
                    continue;
                };
                let mut price = 0.0;
                for side in ["asks", "bids"] {
                    if let Some(arr) = p.get(side).and_then(|v| v.as_array()) {
                        if let Some(first) = arr.first() {
                            price = first
                                .get("price")
                                .and_then(|v| v.as_str())
                                .and_then(|s| s.parse::<f64>().ok())
                                .unwrap_or(0.0);
                            break;
                        }
                    }
                }
                if price > 0.0 {
                    out.insert(sym.to_string(), price);
                }
            }
        }
        out
    }

    /// FRESH price — always hits the pricing endpoint (law 2). Returns
    /// None when the venue has no fresh price; NEVER a stale cached mark.
    pub fn get_current_price(&mut self, symbol: &str) -> Option<f64> {
        let data = self.request(
            "GET",
            &format!(
                "/v3/accounts/{}/pricing?instruments={symbol}",
                self.keys.account_id
            ),
            None,
        );
        Self::parse_pricing(&data).get(symbol).copied()
    }

    /// Batch quotes via the account pricing endpoint (one call, ≤50).
    pub fn get_prices_batch(&mut self, symbols: &[&str]) -> std::collections::BTreeMap<String, f64> {
        let mut uniq = Vec::new();
        for s in symbols {
            if !uniq.contains(s) {
                uniq.push(*s);
            }
        }
        let mut out = std::collections::BTreeMap::new();
        for chunk in uniq.chunks(50) {
            let data = self.request(
                "GET",
                &format!(
                    "/v3/accounts/{}/pricing?instruments={}",
                    self.keys.account_id,
                    chunk.join(",")
                ),
                None,
            );
            out.extend(Self::parse_pricing(&data));
        }
        out
    }

    /// Candles (complete only; mid side). Fail-loud granularity (law 6).
    pub fn get_bars(
        &mut self,
        symbol: &str,
        timeframe: &str,
        limit: usize,
    ) -> Result<Vec<crate::history::Candle>, String> {
        let granularity = granularity(timeframe)?;
        let data = self.request(
            "GET",
            &format!(
                "/v3/instruments/{symbol}/candles?granularity={granularity}&count={limit}&includePending=false"
            ),
            None,
        );
        let mut out = Vec::new();
        if let Some(candles) = data.get("candles").and_then(|v| v.as_array()) {
            for c in candles {
                if c.get("complete").and_then(|v| v.as_bool()) == Some(false) {
                    continue;
                }
                let side = c
                    .get("mid")
                    .or_else(|| c.get("ask"))
                    .or_else(|| c.get("bid"))
                    .cloned()
                    .unwrap_or(json!({}));
                let Some(cp) = side.get("c").and_then(|v| v.as_str()) else {
                    continue;
                };
                let ts = c
                    .get("time")
                    .and_then(|v| v.as_str())
                    .and_then(rfc3339_to_epoch)
                    .unwrap_or(0);
                out.push(crate::history::Candle {
                    ts,
                    open: side.get("o").and_then(|v| v.as_str()).and_then(|s| s.parse().ok()).unwrap_or(0.0),
                    high: side.get("h").and_then(|v| v.as_str()).and_then(|s| s.parse().ok()).unwrap_or(0.0),
                    low: side.get("l").and_then(|v| v.as_str()).and_then(|s| s.parse().ok()).unwrap_or(0.0),
                    close: cp.parse().unwrap_or(0.0),
                    volume: c.get("volume").and_then(|v| v.as_f64()).unwrap_or(0.0),
                    complete: true,
                });
            }
        }
        Ok(out)
    }

    /// Authoritative fill price from the venue's own transaction record
    /// (V1 `_transaction_fill_price`) — 0.0 when unreadable; callers must
    /// then refuse to treat the fill as priced evidence (law 3).
    fn transaction_fill_price(&self, tx_id: Option<&str>) -> f64 {
        let Some(id) = tx_id else { return 0.0 };
        let d = self.request(
            "GET",
            &format!("/v3/accounts/{}/transactions/{id}", self.keys.account_id),
            None,
        );
        let tx = d.get("transaction").cloned().unwrap_or(json!({}));
        tx.get("price")
            .and_then(|v| v.as_str())
            .and_then(|s| s.parse().ok())
            .or_else(|| tx.get("fullVWAP").and_then(|v| v.as_str()).and_then(|s| s.parse().ok()))
            .unwrap_or(0.0)
    }

    /// Place an order — the truthful path (law 1). See V1 `place_order`
    /// for the full body semantics; order_type: market (FOK), limit (GTC),
    /// mit (GTC).
    pub fn place_order(
        &mut self,
        symbol: &str,
        side: &str,
        quantity: f64,
        order_type: &str,
        price: Option<f64>,
        stop_loss: Option<f64>,
        take_profit: Option<f64>,
        tag: Option<&str>,
        client_id: Option<&str>,
    ) -> OrderResult {
        let is_buy = side.eq_ignore_ascii_case("buy");
        let qty = py_round(quantity.abs());
        let units = if is_buy { qty } else { -qty };
        if units == 0 {
            return OrderResult {
                order_id: String::new(),
                filled: false,
                fill_price: 0.0,
                filled_qty: 0.0,
                reject_reason: Some("zero units".into()),
                raw: json!({"error": "zero units"}),
            };
        }
        let digits = self.price_digits(symbol);
        let order = match order_type {
            "market" => {
                let mut o = json!({
                    "type": "MARKET",
                    "instrument": symbol,
                    "units": units.to_string(),
                    "timeInForce": "FOK",
                    "positionFill": "DEFAULT",
                });
                if let Some(tag) = tag {
                    // client id must be unique across open trades; a reused
                    // id is rejected with CLIENT_TRADE_ID_ALREADY_EXISTS.
                    o["tradeClientExtensions"] = json!({
                        "id": client_id.unwrap_or(&format!("{tag}-{symbol}")),
                        "tag": tag,
                        "comment": tag,
                    });
                }
                if let Some(sl) = stop_loss {
                    o["stopLossOnFill"] =
                        json!({"price": fmt_price(sl, digits), "timeInForce": "GTC"});
                }
                if let Some(tp) = take_profit {
                    o["takeProfitOnFill"] =
                        json!({"price": fmt_price(tp, digits), "timeInForce": "GTC"});
                }
                o
            }
            "limit" => {
                let Some(p) = price else {
                    return OrderResult {
                        order_id: String::new(),
                        filled: false,
                        fill_price: 0.0,
                        filled_qty: 0.0,
                        reject_reason: Some("limit order requires price".into()),
                        raw: json!({"error": "limit order requires price"}),
                    };
                };
                json!({
                    "type": "LIMIT",
                    "instrument": symbol,
                    "units": units.to_string(),
                    "price": fmt_price(p, digits),
                    "timeInForce": "GTC",
                    "positionFill": "DEFAULT",
                })
            }
            "mit" => {
                let Some(p) = price else {
                    return OrderResult {
                        order_id: String::new(),
                        filled: false,
                        fill_price: 0.0,
                        filled_qty: 0.0,
                        reject_reason: Some("mit order requires price".into()),
                        raw: json!({"error": "mit order requires price"}),
                    };
                };
                json!({
                    "type": "MARKET_IF_TOUCHED",
                    "instrument": symbol,
                    "units": units.to_string(),
                    "price": fmt_price(p, digits),
                    "timeInForce": "GTC",
                    "positionFill": "DEFAULT",
                })
            }
            other => {
                return OrderResult {
                    order_id: String::new(),
                    filled: false,
                    fill_price: 0.0,
                    filled_qty: 0.0,
                    reject_reason: Some(format!("unsupported order_type: {other}")),
                    raw: json!({"error": format!("unsupported order_type: {other}")}),
                }
            }
        };

        let data = self.request(
            "POST",
            &format!("/v3/accounts/{}/orders", self.keys.account_id),
            Some(json!({"order": order})),
        );
        if data.get("_error").is_some() {
            return OrderResult {
                order_id: String::new(),
                filled: false,
                fill_price: 0.0,
                filled_qty: 0.0,
                reject_reason: Some("http error".into()),
                raw: data,
            };
        }

        // LAW 1: no orderFillTransaction = REJECTED (orderCancelTransaction
        // = e.g. STOP_LOSS_ON_FILL_LOSS; orderRejectTransaction = refused).
        if data.get("orderFillTransaction").is_none() {
            let cancel = data.get("orderCancelTransaction").cloned().unwrap_or(json!({}));
            let reject = data.get("orderRejectTransaction").cloned().unwrap_or(json!({}));
            let reason = cancel
                .get("reason")
                .and_then(|v| v.as_str())
                .or_else(|| reject.get("rejectedReason").and_then(|v| v.as_str()))
                .unwrap_or("no fill");
            return OrderResult {
                order_id: data
                    .get("lastTransactionID")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string(),
                filled: false,
                fill_price: 0.0,
                filled_qty: 0.0,
                reject_reason: Some(reason.to_string()),
                raw: json!({
                    "reason": reason,
                    "lastTransactionID": data.get("lastTransactionID"),
                }),
            };
        }
        let fill_tx = data["orderFillTransaction"].clone();
        let order_id = fill_tx
            .get("orderID")
            .and_then(|v| v.as_str())
            .or_else(|| data.get("lastTransactionID").and_then(|v| v.as_str()))
            .unwrap_or("")
            .to_string();
        // LAW 3: fill price = tx price → fullVWAP → venue transaction
        // record → fresh quote → 0.0 (unpriced — callers refuse).
        let mut fill_price = fill_tx
            .get("price")
            .and_then(|v| v.as_str())
            .and_then(|s| s.parse().ok())
            .unwrap_or(0.0);
        if fill_price == 0.0 {
            fill_price = fill_tx
                .get("fullVWAP")
                .and_then(|v| v.as_str())
                .and_then(|s| s.parse().ok())
                .unwrap_or(0.0);
        }
        if fill_price == 0.0 {
            let tx_id = fill_tx.get("id").and_then(|v| v.as_str());
            fill_price = self.transaction_fill_price(tx_id);
        }
        if fill_price == 0.0 {
            fill_price = self.get_current_price(symbol).unwrap_or(0.0);
        }

        // Local mirror update (paper semantics; write-through cache only).
        let cost = fill_price * units.unsigned_abs() as f64;
        if is_buy {
            self.mirror_cash -= cost;
            *self.mirror_positions.entry(symbol.to_string()).or_insert(0.0) += units.unsigned_abs() as f64;
            *self.mirror_cost_basis.entry(symbol.to_string()).or_insert(0.0) += cost;
        } else {
            self.mirror_cash += cost;
            let e = self.mirror_positions.entry(symbol.to_string()).or_insert(0.0);
            *e -= units.unsigned_abs() as f64;
            if *e <= 0.0 {
                self.mirror_positions.remove(symbol);
                self.mirror_cost_basis.remove(symbol);
            }
        }

        OrderResult {
            raw: json!({
                "order_id": order_id,
                "symbol": symbol,
                "side": side,
                "quantity": units.unsigned_abs(),
                "price": fill_price,
                "cost": (cost * 100.0).round() / 100.0,
            }),
            order_id,
            filled: true,
            fill_price,
            filled_qty: units.unsigned_abs() as f64,
            reject_reason: None,
        }
    }

    /// Venue-truth balance (V1 `get_balance` — the account query IS the
    /// truth; positions are net units from the local mirror).
    pub fn get_balance(&mut self) -> Result<(f64, f64, std::collections::BTreeMap<String, f64>), String> {
        let data = self.request("GET", &format!("/v3/accounts/{}", self.keys.account_id), None);
        match data.get("account") {
            Some(acc) => {
                let cash = acc
                    .get("balance")
                    .and_then(|v| v.as_str())
                    .and_then(|s| s.parse().ok())
                    .unwrap_or(self.mirror_cash);
                let nav = acc
                    .get("NAV")
                    .and_then(|v| v.as_str())
                    .and_then(|s| s.parse().ok())
                    .unwrap_or(cash);
                Ok((cash, nav, self.mirror_positions.clone()))
            }
            None => Ok((self.mirror_cash, self.mirror_cash, self.mirror_positions.clone())),
        }
    }

    /// Walk a transactions endpoint to completion — verbatim port of V1
    /// `fx_runner._walk_transactions`. TWO shapes (the #251/#252 lesson: a
    /// single sinceid call caps at 1000 txns and hides the rest of the
    /// journal — the trained lanes' closes were invisible and their
    /// realized rendered as a silent 0.0):
    ///   * sinceid endpoint: caps at 1000 txns/call with NO `pages` field —
    ///     advance the `id=` cursor until the batch is short;
    ///   * date-based endpoint: paginates via a `pages` list.
    pub fn walk_transactions(&self, path: &str) -> Vec<Value> {
        let mut txs: Vec<Value> = Vec::new();
        let mut push_batch = |d: &Value| {
            if let Some(arr) = d.get("transactions").and_then(|v| v.as_array()) {
                txs.extend(arr.iter().cloned());
            }
        };
        let first = self.request("GET", path, None);
        push_batch(&first);
        for page in first
            .get("pages")
            .and_then(|v| v.as_array())
            .into_iter()
            .flatten()
        {
            if let Some(p) = page.as_str() {
                let sub = format!("/v3/{}", p.split("/v3/").nth(1).unwrap_or(p));
                push_batch(&self.request("GET", &sub, None));
            }
        }
        if path.contains("sinceid") {
            let base = path.split('?').next().unwrap_or(path).to_string();
            let mut batch = first
                .get("transactions")
                .and_then(|v| v.as_array())
                .cloned()
                .unwrap_or_default();
            let mut guard = 0;
            while batch.len() == 1000 {
                guard += 1;
                if guard > 10_000 {
                    break; // pagination runaway — refuse rather than loop forever
                }
                // OANDA ids arrive as STRINGS (V1's int() parsed them) — and
            // can exceed i64 headroom; parse through i128
                    let last = batch
                    .iter()
                    .filter_map(|t| {
                        t.get("id").and_then(|v| {
                            v.as_i64()
                                .map(i128::from)
                                .or_else(|| v.as_str().and_then(|s| s.parse().ok()))
                        })
                    })
                    .max()
                    .unwrap_or(0);
                    if last <= 0 {
                        break; // unparseable cursor — refuse to spin
                    }
                eprintln!("journal walk: cursor {last}, +{} so far", txs.len());
                batch = self
                    .request("GET", &format!("{base}?id={last}"), None)
                    .get("transactions")
                    .and_then(|v| v.as_array())
                    .cloned()
                    .unwrap_or_default();
                txs.extend(batch.iter().cloned());
                if batch.is_empty() {
                    break;
                }
            }
        }
        txs
    }

    /// Open trades with their owner tags (no-overlap arbitration input).
    pub fn open_trades(&self) -> Vec<(String, String, f64)> {
        self.open_trades_detailed()
            .into_iter()
            .map(|t| (t.symbol, t.tag, t.units))
            .collect()
    }

    /// Detailed open trades: symbol, tag, units, and the venue's own
    /// trade ID (needed for the trade-specific close — W1-tails-3).
    pub fn open_trades_detailed(&self) -> Vec<OpenTradeInfo> {
        let data = self.request(
            "GET",
            &format!("/v3/accounts/{}/openTrades", self.keys.account_id),
            None,
        );
        let mut out = Vec::new();
        if let Some(trades) = data.get("trades").and_then(|v| v.as_array()) {
            for t in trades {
                let sym = t.get("instrument").and_then(|v| v.as_str()).unwrap_or("").to_string();
                let tag = t
                    .pointer("/clientExtensions/tag")
                    .and_then(|v| v.as_str())
                    .unwrap_or("untagged")
                    .to_string();
                let units = t
                    .get("currentUnits")
                    .and_then(|v| v.as_str())
                    .and_then(|s| s.parse().ok())
                    .unwrap_or(0.0);
                let id = t
                    .get("id")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string();
                out.push(OpenTradeInfo {
                    symbol: sym,
                    tag,
                    units,
                    trade_id: id,
                });
            }
        }
        out
    }

    /// Held by other tags (V1 `held_by_other_tags`): instruments with any
    /// open trade NOT owned by my_tag; untagged positions count as foreign.
    pub fn held_by_other_tags(&self, my_tag: &str) -> std::collections::BTreeSet<String> {
        let mut held: std::collections::BTreeMap<String, std::collections::BTreeSet<String>> =
            Default::default();
        for (sym, tag, _) in self.open_trades() {
            held.entry(sym).or_default().insert(tag);
        }
        held.into_iter()
            .filter_map(|(sym, tags)| {
                let foreign: std::collections::BTreeSet<&String> =
                    tags.iter().filter(|t| t.as_str() != my_tag).collect();
                (!foreign.is_empty()).then_some(sym)
            })
            .collect()
    }
}

/// RFC3339 (OANDA "2026-09-14T12:34:56.789012345Z") → epoch seconds.
pub fn rfc3339_to_epoch(s: &str) -> Option<i64> {
    let s = s.trim_end_matches('Z');
    let (date, time) = s.split_once('T')?;
    let mut dp = date.split('-');
    let y: i64 = dp.next()?.parse().ok()?;
    let m: i64 = dp.next()?.parse().ok()?;
    let d: i64 = dp.next()?.parse().ok()?;
    let mut tp = time.split('.');
    let mut hms = tp.next()?.split(':');
    let hh: i64 = hms.next()?.parse().ok()?;
    let mm: i64 = hms.next()?.parse().ok()?;
    let ss: i64 = hms.next()?.parse().ok()?;
    // days-from-civil algorithm (Howard Hinnant)
    let yy = if m <= 2 { y - 1 } else { y };
    let era = if yy >= 0 { yy } else { yy - 399 } / 400;
    let yoe = yy - era * 400;
    let mp = (m + 9) % 12;
    let doy = (153 * mp + 2) / 5 + d - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    let days = era * 146097 + doe - 719468;
    Some(days * 86400 + hh * 3600 + mm * 60 + ss)
}
