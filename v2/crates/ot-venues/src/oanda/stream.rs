//! OANDA pricing stream — chunked JSON messages terminated by `\n`, with
//! blank-line heartbeats. The parser is pure (testable against canned
//! frames); the live reader rides the Transport::stream seam.

use serde_json::Value;

#[derive(Debug, Clone, PartialEq)]
pub enum StreamMsg {
    /// Fresh price for one instrument (ask > mid > bid representative).
    Price {
        instrument: String,
        time: String,
        bid: f64,
        ask: f64,
    },
    Heartbeat,
    Other(Value),
}

/// Parse one stream line. Empty lines = keepalive (ignored by the caller
/// loop, surfaced here as None).
pub fn parse_line(line: &str) -> Option<StreamMsg> {
    let line = line.trim();
    if line.is_empty() {
        return None;
    }
    let v: Value = serde_json::from_str(line).ok()?;
    match v.get("type").and_then(|t| t.as_str()) {
        Some("HEARTBEAT") => Some(StreamMsg::Heartbeat),
        Some("PRICE") => {
            let instrument = v.get("instrument").and_then(|i| i.as_str())?.to_string();
            let time = v.get("time").and_then(|t| t.as_str()).unwrap_or("").to_string();
            let parse_side = |key: &str| -> f64 {
                v.pointer(&format!("/{key}/0/price"))
                    .and_then(|p| p.as_str())
                    .and_then(|s| s.parse().ok())
                    .unwrap_or(0.0)
            };
            Some(StreamMsg::Price {
                instrument,
                time,
                bid: parse_side("bids"),
                ask: parse_side("asks"),
            })
        }
        _ => Some(StreamMsg::Other(v)),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_price_and_heartbeat_frames() {
        let price = r#"{"type":"PRICE","time":"2026-10-07T12:00:00.123456Z","instrument":"EUR_USD","bids":[{"price":"1.08510","liquidity":10000000}],"asks":[{"price":"1.08525","liquidity":10000000}]}"#;
        match parse_line(price) {
            Some(StreamMsg::Price { instrument, bid, ask, .. }) => {
                assert_eq!(instrument, "EUR_USD");
                assert!((bid - 1.08510).abs() < 1e-9);
                assert!((ask - 1.08525).abs() < 1e-9);
            }
            other => panic!("expected price, got {other:?}"),
        }
        assert_eq!(parse_line(""), None);
        assert_eq!(parse_line(r#"{"type":"HEARTBEAT"}"#), Some(StreamMsg::Heartbeat));
    }
}
