//! V1-parity harness — the W0 exit criterion: ot-core's engine replays the
//! REAL V1 `run_backtest` contract (recorded into `v2/tests/fixtures/*.json`
//! by `v2/tools/gen_parity_fixtures.py`, which executed the sandbox V1
//! engine) and must reproduce the trade structure exactly and the metrics
//! within fp tolerance.

use ot_core::bar::{Bar, Series};
use ot_core::config::{clamp_config, Config};
use ot_core::engine::replay;
use ot_core::rulefloor::RuleFloor;
use ot_core::universe::Universe;
use serde::Deserialize;
use std::collections::BTreeMap;

#[derive(Debug, Deserialize)]
struct Fixture {
    desc: String,
    #[allow(dead_code)]
    n_master: usize,
    bars: BTreeMap<String, Vec<FBar>>,
    volumes: BTreeMap<String, Vec<f64>>,
    config: FConfig,
    expect: Expect,
}

#[derive(Debug, Deserialize)]
struct FBar {
    ts: i64,
    #[allow(dead_code)]
    open: f64,
    high: f64,
    low: f64,
    close: f64,
}

#[derive(Debug, Deserialize)]
struct FConfig {
    #[allow(dead_code)]
    desc: String,
    keys: BTreeMap<String, serde_json::Value>,
}

#[derive(Debug, Deserialize)]
struct Expect {
    #[allow(dead_code)]
    desc: String,
    n_trades: usize,
    trades: Vec<FTrade>,
    net_return: f64,
    sharpe: f64,
    max_dd: f64,
    win_rate: f64,
    total_fees: f64,
    profit_factor: f64,
    avg_hold: f64,
    final_equity: f64,
    equity: Vec<(i64, f64)>,
}

#[derive(Debug, Deserialize)]
struct FTrade {
    sym: String,
    entry: f64,
    exit: f64,
    reason: String,
    #[allow(dead_code)]
    entry_idx: i64,
    #[allow(dead_code)]
    exit_idx: i64,
    bars: i64,
}

fn build_universe(f: &Fixture) -> Universe {
    let mut series: BTreeMap<String, Series> = BTreeMap::new();
    for (sym, bars) in &f.bars {
        series.insert(
            sym.clone(),
            Series::from_bars(
                bars.iter()
                    .map(|b| Bar {
                        ts: b.ts,
                        open: b.open,
                        high: b.high,
                        low: b.low,
                        close: b.close,
                        volume: 0.0,
                    })
                    .collect(),
            ),
        );
    }
    Universe::from_series(series, f.volumes.clone())
}

fn cfg_from(fc: &FConfig) -> Config {
    clamp_config(|k| {
        fc.keys.get(k).and_then(|v| match v {
            serde_json::Value::Null => None,
            serde_json::Value::Number(n) => n.as_f64(),
            serde_json::Value::Bool(b) => Some(*b as i64 as f64),
            _ => None,
        })
    })
}

#[test]
fn v1_parity_fixtures_match() {
    let dir = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../tests/fixtures");
    let mut cases = 0;
    for entry in std::fs::read_dir(&dir).expect("fixtures dir") {
        let path = entry.unwrap().path();
        if path.extension().and_then(|e| e.to_str()) != Some("json")
            || !path.file_name().map(|n| n.to_string_lossy().starts_with("fixture_")).unwrap_or(false)
        {
            continue;
        }
        cases += 1;
        let text = std::fs::read_to_string(&path).unwrap();
        let f: Fixture = serde_json::from_str(&text)
            .unwrap_or_else(|e| panic!("parse {}: {e}", path.display()));
        let uni = build_universe(&f);
        let cfg = cfg_from(&f.config);
        let mut h = RuleFloor::new(&uni, cfg, None);
        let r = replay(&uni, &cfg, &mut h);

        // ── trade structure must match EXACTLY (same bars, same reasons) ──
        assert_eq!(
            r.trades.len(),
            f.expect.n_trades,
            "fixture `{}`: trade count (got {:?})",
            f.desc,
            r.trades.iter().map(|t| (&t.sym, &t.reason)).collect::<Vec<_>>()
        );
        for (i, (got, want)) in r.trades.iter().zip(&f.expect.trades).enumerate() {
            assert_eq!(got.sym, want.sym, "fixture `{}` trade #{i}: sym", f.desc);
            assert_eq!(got.reason, want.reason, "fixture `{}` trade #{i}: reason", f.desc);
            assert_eq!(got.bars, want.bars, "fixture `{}` trade #{i}: bars", f.desc);
            assert_eq!(got.entry_ts, want.entry_idx, "fixture `{}` trade #{i}: entry bar", f.desc);
            assert_eq!(got.exit_ts, want.exit_idx, "fixture `{}` trade #{i}: exit bar", f.desc);
            assert!(
                (got.entry - want.entry).abs() <= 1e-9,
                "fixture `{}` trade #{i}: entry {} vs {}",
                f.desc, got.entry, want.entry
            );
            assert!(
                (got.exit - want.exit).abs() <= 1e-9,
                "fixture `{}` trade #{i}: exit {} vs {}",
                f.desc, got.exit, want.exit
            );
        }

        // ── metrics within fp tolerance ────────────────────────────────────
        let m = &r.metrics;
        let close = |a: f64, b: f64, what: &str, tol: f64| {
            assert!(
                (a - b).abs() <= tol,
                "fixture `{}`: {what} {a} vs {b} (tol {tol})",
                f.desc
            );
        };
        close(m.net_return, f.expect.net_return, "net_return", 1e-9);
        close(m.ann_sharpe, f.expect.sharpe, "ann_sharpe", 1e-6);
        close(m.max_drawdown, f.expect.max_dd, "max_drawdown", 1e-6);
        close(m.win_rate, f.expect.win_rate, "win_rate", 1e-9);
        close(m.total_fees, f.expect.total_fees, "total_fees", 1e-6);
        close(m.profit_factor, f.expect.profit_factor, "profit_factor", 1e-6);
        close(m.avg_hold, f.expect.avg_hold, "avg_hold", 1e-6);
        close(m.final_equity, f.expect.final_equity, "final_equity", 1e-6);

        // ── equity curve shape + values ────────────────────────────────────
        assert_eq!(r.equity.len(), f.expect.equity.len(), "fixture `{}`: equity len", f.desc);
        for (i, (got, (_, want))) in r.equity.iter().zip(&f.expect.equity).enumerate() {
            assert!(
                (got - want).abs() <= 1e-6,
                "fixture `{}`: equity[{i}] {got} vs {want}",
                f.desc
            );
        }
    }
    assert!(cases >= 5, "expected ≥5 parity fixtures, found {cases}");
}
