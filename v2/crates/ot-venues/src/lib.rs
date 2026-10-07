//! ot-venues — the venue-abstraction trait (locked #336): account, quotes,
//! orders, positions, history. ONE seam feeding both the egui terminal and
//! the MCP server; every added broker is one adapter crate behind it.
//!
//! Adapter law (semantic port of V1 `exchange/oanda.py`, locked #339):
//!   * `place_order` is TRUTHFUL: no fill transaction in the response means
//!     REJECTED — never assume a POST succeeded = filled.
//!   * Prices are always fetched fresh — a write-once never-expiring price
//!     cache is the phantom-entry defect class; forbidden by construction
//!     (quote accessors take the adapter's own fetch path, no TTL cache).
//!   * Owner tags ride on every order (V1 `clientExtensions` lane tags) so
//!     attribution never guesses from fill size.

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum Side {
    Buy,
    Sell,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum OrderType {
    Market,
    Limit,
    Stop,
    StopLimit,
}

/// Owner tag — V1 `clientExtensions` (lane attribution must never guess).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OwnerTag(pub String);

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OrderRequest {
    pub symbol: String,
    pub side: Side,
    pub qty: f64,
    pub order_type: OrderType,
    /// None = market price (fresh-fetched, never cached).
    pub limit_price: Option<f64>,
    pub stop_price: Option<f64>,
    /// Attached protective orders (server-side SL/TP where the venue
    /// supports them — V1's OANDA gteantry).
    pub take_profit: Option<f64>,
    pub stop_loss: Option<f64>,
    pub tag: Option<OwnerTag>,
}

/// The truthful fill model: `filled == false` means REJECTED — the venue
/// cancelled (e.g. OANDA STOP_LOSS_ON_FILL_LOSS) or refused. There is no
/// "assume it worked" path.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OrderAck {
    pub order_id: String,
    /// True ONLY with a venue fill transaction attached.
    pub filled: bool,
    /// Venue fill transaction id (V1 `orderFillTransaction`) — required
    /// when `filled`; the reason string carries the venue's rejection
    /// reason when not.
    pub fill_tx_id: Option<String>,
    pub filled_qty: Option<f64>,
    pub fill_price: Option<f64>,
    pub reject_reason: Option<String>,
}

impl OrderAck {
    /// Construct the only two valid acks. A "filled" ack without a fill
    /// transaction id is unrepresentable — that is the point.
    pub fn filled(order_id: &str, tx_id: &str, qty: f64, price: f64) -> Self {
        OrderAck {
            order_id: order_id.to_string(),
            filled: true,
            fill_tx_id: Some(tx_id.to_string()),
            filled_qty: Some(qty),
            fill_price: Some(price),
            reject_reason: None,
        }
    }

    pub fn rejected(order_id: &str, reason: &str) -> Self {
        OrderAck {
            order_id: order_id.to_string(),
            filled: false,
            fill_tx_id: None,
            filled_qty: None,
            fill_price: None,
            reject_reason: Some(reason.to_string()),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AccountSummary {
    pub balance: f64,
    /// Venue-truth unrealized P/L (V1: the server-truth balance lesson —
    /// account questions are answered from the venue, never a cache).
    pub unrealized_pl: f64,
    pub margin_available: f64,
    pub currency: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PositionSummary {
    pub symbol: String,
    pub net_qty: f64,
    pub unrealized_pl: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Quote {
    pub symbol: String,
    pub ts: i64,
    pub bid: f64,
    pub ask: f64,
}

/// The venue seam. Async-capable in W1+ (OANDA streaming); W0 fixes the
/// shape and the adapter law. All money/position questions resolve HERE,
/// never from a cache — the venue is authoritative (binding).
pub trait VenueAdapter {
    fn name(&self) -> &str;

    /// Fresh account state (venue-truth; no cache).
    fn account(&self) -> Result<AccountSummary, String>;

    /// FRESH quote — this is the no-TTL-cache seam: every call hits the
    /// venue's pricing endpoint (or a stream frame), never a stored price.
    fn quote(&mut self, symbol: &str) -> Result<Quote, String>;

    /// Truthful order placement: see [`OrderAck`].
    fn place_order(&mut self, req: &OrderRequest) -> Result<OrderAck, String>;

    fn cancel_order(&mut self, order_id: &str) -> Result<bool, String>;

    fn positions(&self) -> Result<Vec<PositionSummary>, String>;

    /// Candle history for the symbol (backtest corpus / warmup).
    fn history(
        &self,
        symbol: &str,
        from_ts: i64,
        to_ts: i64,
        granularity: &str,
    ) -> Result<Vec<crate::history::Candle>, String>;
}

/// History candle (venue-neutral; OANDA v20 granularity strings pass
/// through as opaque venue grammar on the adapter side).
pub mod history {
    use serde::{Deserialize, Serialize};

    #[derive(Debug, Clone, Copy, Serialize, Deserialize)]
    pub struct Candle {
        pub ts: i64,
        pub open: f64,
        pub high: f64,
        pub low: f64,
        pub close: f64,
        pub volume: f64,
        pub complete: bool,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn filled_ack_requires_fill_tx() {
        let ack = OrderAck::filled("123", "tx-9", 10.0, 1.2345);
        assert!(ack.filled && ack.fill_tx_id.is_some());
        let rej = OrderAck::rejected("123", "STOP_LOSS_ON_FILL_LOSS");
        assert!(!rej.filled && rej.fill_tx_id.is_none());
    }
}
