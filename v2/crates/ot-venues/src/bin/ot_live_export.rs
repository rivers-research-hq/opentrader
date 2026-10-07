//! ot-live-export — the W1-tails read-only live verification + journal
//! export (human-authorized). GET requests ONLY: account, pricing,
//! positions, and the full transaction journal walk. No POSTs, no orders.
//!
//! Usage: cargo run -p ot-venues --bin ot-live-export -- <out.json>
//! Credentials load from V1's gitignored config (never printed).

use ot_venues::oanda::{Keys, OandaAdapter};
use ot_venues::transport::UreqTransport;

fn main() {
    let out_path = std::env::args()
        .nth(1)
        .unwrap_or_else(|| "v2/tests/fixtures/live_journal.json".to_string());
    let keys_path = std::env::args()
        .nth(2)
        .unwrap_or_else(|| "../config/oanda_keys.json".to_string());

    let keys = Keys::from_v1_config(std::path::Path::new(&keys_path))
        .expect("credentials (V1 gitignored config)");
    let transport = UreqTransport::new();
    let mut a = OandaAdapter::new(keys, &transport);

    // ── read-only live verification ────────────────────────────────────
    let acc = a.request("GET", &format!("/v3/accounts/{}", a.keys.account_id), None);
    let balance = acc
        .pointer("/account/balance")
        .and_then(|v| v.as_str())
        .and_then(|s| s.parse::<f64>().ok())
        .unwrap_or(-1.0);
    let currency = acc.pointer("/account/currency").and_then(|v| v.as_str()).unwrap_or("?");
    let open_trade_count = acc.pointer("/account/openTradeCount").and_then(|v| v.as_i64()).unwrap_or(-1);
    println!("account: balance={balance} {currency} openTrades={open_trade_count}");

    let price = a.get_current_price("EUR_USD");
    println!("fresh price EUR_USD: {:?}", price.map(|p| (p * 1000.0).round() / 1000.0));

    let open_trades = a.open_trades();
    println!("open venue trades: {} (tagged)", open_trades.len());

    // ── full journal walk (sinceid cursor pagination) ───────────────────
    let txs = a.walk_transactions(&format!(
        "/v3/accounts/{}/transactions/sinceid?id=0",
        a.keys.account_id
    ));
    let mut counts: std::collections::BTreeMap<String, usize> = std::collections::BTreeMap::new();
    for t in &txs {
        let typ = t.get("type").and_then(|v| v.as_str()).unwrap_or("?").to_string();
        *counts.entry(typ).or_insert(0) += 1;
    }
    println!("journal: {} transactions", txs.len());
    for (typ, n) in &counts {
        println!("  {typ}: {n}");
    }
    let fills: Vec<_> = txs
        .iter()
        .filter(|t| t.get("type").and_then(|v| v.as_str()) == Some("ORDER_FILL"))
        .collect();
    println!("ORDER_FILLs: {}", fills.len());

    // ── snapshot (redact nothing but credentials — none are in txns) ───
    let snapshot = serde_json::json!({
        "exported": chrono_now_iso(),
        "account_id": a.keys.account_id,
        "balance": balance,
        "currency": currency,
        "transactions": txs,
    });
    std::fs::write(&out_path, serde_json::to_string_pretty(&snapshot).unwrap())
        .expect("write snapshot");
    println!("snapshot written to {out_path} ({} bytes)", snapshot.to_string().len());
}

fn chrono_now_iso() -> String {
    // no chrono dep — seconds-precision epoch via the same civil algorithm
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_secs() as i64;
    let days = now.div_euclid(86400);
    let secs = now.rem_euclid(86400);
    // civil-from-days (Howard Hinnant)
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = if m <= 2 { y + 1 } else { y };
    format!("{y:04}-{m:02}-{d:02}T{:02}:{:02}:{:02}Z", secs / 3600, (secs % 3600) / 60, secs % 60)
}
