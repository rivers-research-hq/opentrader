//! FX lane attribution — the single source of truth, ported verbatim from
//! V1 `strategies/lane_attribution.py` (locked #339 semantic port).
//!
//! Resolves a venue ORDER_FILL's lane tag through the
//! clientExtensions/orderID chain (tradeID → opening MARKET_ORDER tag),
//! with a LOUD `unattributed` bucket — the old silent size-matcher default
//! credited every tagless row to mom-k5 (mis-attributing the experts'
//! evidence base). The fill-size matcher survives ONLY as the grandfathered
//! pre-08-31 fallback (ledger is append-only; those rows never rewrite).

use serde_json::Value;

pub const LEGACY_CUTOFF: &str = "2026-08-31T18:00";
pub const UNATTRIBUTED: &str = "unattributed";
pub const LEGACY_SMOKE: &str = "legacy-smoke";

/// `tradeID -> tag` and `orderID -> tag` — verbatim V1 `_trade_tags`:
/// the tag lives on the MARKET_ORDER transaction's tradeClientExtensions
/// (ORDER_FILLs do NOT echo clientExtensions) and fills link back via
/// orderID; closes carry no extensions and resolve through their trade's
/// OPENING fill chain.
pub fn trade_tags(transactions: &[Value]) -> (std::collections::BTreeMap<String, String>, std::collections::BTreeMap<String, String>) {
    let mut order_tag: std::collections::BTreeMap<String, String> = Default::default();
    let mut fills: Vec<&Value> = Vec::new();
    for t in transactions {
        match t.get("type").and_then(|v| v.as_str()) {
            Some("MARKET_ORDER") => {
                if let Some(tag) = t
                    .pointer("/tradeClientExtensions/tag")
                    .and_then(|v| v.as_str())
                {
                    if let Some(id) = t.get("id").and_then(|v| v.as_str()) {
                        order_tag.insert(id.to_string(), tag.to_string());
                    } else if let Some(id) = t.get("id").and_then(|v| v.as_i64()) {
                        order_tag.insert(id.to_string(), tag.to_string());
                    }
                }
            }
            Some("ORDER_FILL") => fills.push(t),
            _ => {}
        }
    }
    let mut tags: std::collections::BTreeMap<String, String> = Default::default();
    for t in fills {
        let tag = t
            .pointer("/clientExtensions/tag")
            .and_then(|v| v.as_str())
            .map(String::from)
            .or_else(|| {
                t.get("orderID")
                    .and_then(|v| v.as_str().map(String::from).or_else(|| v.as_i64().map(|i| i.to_string())))
                    .and_then(|oid| order_tag.get(&oid).cloned())
            });
        let Some(tag) = tag else { continue };
        let tid_str = |v: &Value| -> Option<String> {
            v.as_str()
                .map(String::from)
                .or_else(|| v.as_i64().map(|i| i.to_string()))
        };
        for key in ["tradeOpened", "tradeReduced"] {
            if let Some(tr) = t.get(key).filter(|v| !v.is_null()) {
                if let Some(tid) = tr.get("tradeID").and_then(tid_str) {
                    tags.insert(tid, tag.clone());
                }
            }
        }
        if let Some(tcs) = t.get("tradesClosed").and_then(|v| v.as_array()) {
            for tc in tcs {
                if let Some(tid) = tc.get("tradeID").and_then(&tid_str) {
                    tags.insert(tid, tag.clone());
                }
            }
        }
    }
    (tags, order_tag)
}

/// Resolve an ORDER_FILL's lane tag via the chain — verbatim
/// `resolve_fill_tag`. Returns None when unresolvable (caller decides the
/// fallback: grandfathered legacy size-match vs "unattributed").
pub fn resolve_fill_tag(
    t: &Value,
    tags: &std::collections::BTreeMap<String, String>,
    order_tag: &std::collections::BTreeMap<String, String>,
) -> Option<String> {
    let direct = t
        .pointer("/clientExtensions/tag")
        .and_then(|v| v.as_str())
        .map(String::from);
    let tag = direct.or_else(|| {
        t.get("orderID")
            .and_then(|v| v.as_str().map(String::from).or_else(|| v.as_i64().map(|i| i.to_string())))
            .and_then(|oid| order_tag.get(&oid).cloned())
    });
    if let Some(tag) = tag {
        return Some(tag);
    }
    // Server-side SL/TP and per-trade partial closes land as fills with NO
    // extensions of their own — they resolve through the closed/reduced/
    // opened trade's OPENING-fill tag. tradesClosed is a list;
    // tradeReduced/tradeOpened are single objects (#250: tradeReduced was
    // the missing leg — 55 partial-close fills were wrongly "unattributed").
    for key in ["tradesClosed", "tradeReduced", "tradeOpened"] {
        let val = t.get(key).filter(|v| !v.is_null());
        let Some(val) = val else { continue };
        let items: Vec<&Value> = if val.is_array() {
            val.as_array().unwrap().iter().collect()
        } else {
            vec![val]
        };
        for tc in items {
            let Some(tid) = tc.get("tradeID") else { continue };
            let tid = tid.to_string().trim_matches('"').to_string();
            if let Some(tag) = tags.get(&tid) {
                return Some(tag.clone());
            }
        }
    }
    None
}

/// Grandfathered pre-08-31 fill-size matcher (legacy rows only).
pub fn size_attribution_legacy(qty: Option<f64>) -> &'static str {
    let q = qty.unwrap_or(0.0).abs();
    if q >= 5000.0 {
        "crash"
    } else if q >= 2000.0 {
        "h1-mom"
    } else {
        "mom-k5"
    }
}

/// Per-tag realized PnL from a full journal walk (venue is authoritative).
/// Returns (realized_all, realized_today): {tag: usd} each. Opening fills
/// carry pl 0.0 and are harmless. Tagless fills pre-cutoff grandfather to
/// LEGACY_SMOKE; post-cutoff failures land LOUD in UNATTRIBUTED — never
/// silently credited to a lane. `today` is the as-of date (yyyy-mm-dd);
/// `walk` supplies the journal (the caller owns pagination).
pub fn realized_by_tag(
    transactions: &[Value],
    today: &str,
) -> (std::collections::BTreeMap<String, f64>, std::collections::BTreeMap<String, f64>) {
    let (tags, order_tag) = trade_tags(transactions);
    let mut realized_all: std::collections::BTreeMap<String, f64> = Default::default();
    let mut realized_today: std::collections::BTreeMap<String, f64> = Default::default();
    for t in transactions {
        if t.get("type").and_then(|v| v.as_str()) != Some("ORDER_FILL") {
            continue;
        }
        let tag = resolve_fill_tag(t, &tags, &order_tag).unwrap_or_else(|| {
            let time = t.get("time").and_then(|v| v.as_str()).unwrap_or("");
            if time < LEGACY_CUTOFF {
                LEGACY_SMOKE.to_string()
            } else {
                UNATTRIBUTED.to_string()
            }
        });
        let pl = t
            .get("pl")
            .and_then(|v| v.as_str().map(String::from).or_else(|| v.as_f64().map(|f| f.to_string())))
            .and_then(|s| s.parse::<f64>().ok())
            .unwrap_or(0.0);
        *realized_all.entry(tag.clone()).or_insert(0.0) += pl;
        if t.get("time").and_then(|v| v.as_str()).map(|s| s.len() >= 10 && &s[..10] == today).unwrap_or(false) {
            *realized_today.entry(tag).or_insert(0.0) += pl;
        }
    }
    (realized_all, realized_today)
}
