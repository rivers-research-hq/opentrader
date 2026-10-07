//! Scanner host mode (spec §8) — the SAME language/compiler as charts and
//! strategies, batch-evaluated over a universe on bar close.
//!
//! A scan = { script, filter binding (bool), sort binding (float, optional),
//! limit }. The filter is read at each symbol's LAST closed bar; hits are
//! ranked by the sort value (descending, symbol tie-break) and truncated.
//!
//! Scanner-grade guardrails (spec §8, made static):
//!   * history-dependent scripts (any `series` binding / unbounded warm-up)
//!     are REFUSED unless the scan explicitly grants history — a scan over
//!     10k symbols must not depend on how much history the host loaded;
//!   * capped per-binding lookback (default 500 bars);
//!   * capped symbol count and binding count (TOS's
//!     ScriptIsTooLongException discipline, made static);
//!   * whole-history built-ins arrive with the Cranelift tier — the
//!     interpreter refuses them by the same warm-up rule.
//!
//! Symbols whose bars don't cover the script's warm-up are SKIPPED and
//! counted — never silently dropped into an error bucket (the date-guard
//! lesson, salavage §2.1).

use crate::ast::Type;
use crate::check::{BindingKind, CompilePlan};
use crate::eval::{evaluate_full, Column, Frame, ScriptRequest};
use serde::Serialize;
use std::collections::BTreeMap;

#[derive(Debug, Clone)]
pub struct ScanRequest {
    pub source: String,
    /// bool binding — the filter, read at the last closed bar
    pub filter: String,
    /// float binding — the sort key (None → rank by symbol)
    pub sort: Option<String>,
    pub timeframe: String,
    pub limit: usize,
}

#[derive(Debug, Clone)]
pub struct ScanConfig {
    /// max static lookback any binding may carry (spec §8 default ~500)
    pub max_lookback: i64,
    pub max_symbols: usize,
    pub max_bindings: usize,
    /// grant history to history-dependent scripts (explicit opt-in)
    pub allow_unbounded: bool,
}

impl Default for ScanConfig {
    fn default() -> Self {
        ScanConfig {
            max_lookback: 500,
            max_symbols: 10_000,
            max_bindings: 500,
            allow_unbounded: false,
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct ScanHit {
    pub symbol: String,
    pub filter: bool,
    pub sort: f64,
    pub last_close: f64,
}

#[derive(Debug, Clone, Default, Serialize)]
pub struct ScanResult {
    /// ranked (sort desc, symbol tie-break), limited
    pub hits: Vec<ScanHit>,
    /// hits before the limit was applied
    pub ranked_pool: usize,
    pub scanned: usize,
    /// symbols whose bars don't cover the script's warm-up — counted,
    /// never silently dropped
    pub skipped_warmup: usize,
    /// per-symbol evaluation failures (loud, per audit-gate rule 4)
    pub errors: Vec<(String, String)>,
}

/// Run a scan over a universe (per-symbol bars). Deterministic: the same
/// universe produces the same ranked output.
pub fn run_scan(
    req: &ScanRequest,
    plan: &CompilePlan,
    universe: &[(String, Vec<ot_core::bar::Bar>)],
    cfg: &ScanConfig,
) -> Result<ScanResult, String> {
    // ── guardrails (static, refuse-not-warn) ────────────────────────────
    let history_dependent = plan.warmup_unbounded
        || plan.bindings.iter().any(|b| b.kind == BindingKind::Series);
    if history_dependent && !cfg.allow_unbounded {
        return Err(
            "scan refused: script is history-dependent (series/unbounded warm-up) — scans must be history-length-independent unless the scan explicitly grants history (spec §8)"
                .into(),
        );
    }
    let max_lb = plan
        .bindings
        .iter()
        .map(|b| b.lookback)
        .max()
        .unwrap_or(0);
    if max_lb > cfg.max_lookback {
        return Err(format!(
            "scan refused: binding lookback {max_lb} exceeds the scan cap {} (spec §8)",
            cfg.max_lookback
        ));
    }
    if universe.len() > cfg.max_symbols {
        return Err(format!(
            "scan refused: universe {} exceeds the symbol cap {}",
            universe.len(),
            cfg.max_symbols
        ));
    }
    if plan.bindings.len() > cfg.max_bindings {
        return Err(format!(
            "scan refused: script has {} bindings (cap {} — ScriptIsTooLongException, made static)",
            plan.bindings.len(),
            cfg.max_bindings
        ));
    }

    // ── resolve filter/sort bindings ────────────────────────────────────
    let filter_binding = plan
        .bindings
        .iter()
        .find(|b| b.name == req.filter)
        .ok_or_else(|| format!("filter binding `{}` not found in script", req.filter))?;
    if filter_binding.ty != Type::Bool {
        return Err(format!(
            "filter binding `{}` must be bool (got {:?})",
            req.filter, filter_binding.ty
        ));
    }
    let sort_binding = match &req.sort {
        Some(name) => {
            let b = plan
                .bindings
                .iter()
                .find(|b| b.name == *name)
                .ok_or_else(|| format!("sort binding `{name}` not found in script"))?;
            if b.ty != Type::Float {
                return Err(format!(
                    "sort binding `{name}` must be float (got {:?})",
                    b.ty
                ));
            }
            Some(name.clone())
        }
        None => None,
    };

    // ── per-symbol evaluation ───────────────────────────────────────────
    let mut result = ScanResult::default();
    let mut pool: Vec<ScanHit> = Vec::new();
    for (symbol, bars) in universe {
        result.scanned += 1;
        let sort_warmup = sort_binding
            .as_ref()
            .and_then(|name| plan.bindings.iter().find(|b| b.name == *name))
            .map(|b| b.warmup);
        let warmup = match sort_warmup {
            Some(w) => filter_binding.warmup.max(w),
            None => filter_binding.warmup,
        };
        if (bars.len() as i64) < warmup + 1 {
            result.skipped_warmup += 1;
            continue;
        }
        let script_req = ScriptRequest {
            source: req.source.clone(),
            symbol: symbol.clone(),
            timeframe: req.timeframe.clone(),
            inputs: BTreeMap::new(),
        };
        let frame = Frame { bars };
        match evaluate_full(&script_req, plan, &frame) {
            Ok((_, cols)) => {
                let filter_true = match cols.get(&req.filter) {
                    Some(Column::Bool(b)) => *b.last().unwrap_or(&false),
                    _ => false,
                };
                if !filter_true {
                    continue;
                }
                let sort_v = sort_binding
                    .as_ref()
                    .and_then(|name| match cols.get(name) {
                        Some(Column::Float(f)) => f.last().copied(),
                        _ => None,
                    })
                    .unwrap_or(f64::NEG_INFINITY);
                pool.push(ScanHit {
                    symbol: symbol.clone(),
                    filter: true,
                    sort: sort_v,
                    last_close: bars.last().map(|b| b.close).unwrap_or(f64::NAN),
                });
            }
            Err(e) => result.errors.push((symbol.clone(), e)),
        }
    }

    // ── rank: sort desc, NaN bottom, symbol tie-break; then limit ───────
    pool.sort_by(|a, b| {
        let sa = if a.sort.is_nan() { f64::NEG_INFINITY } else { a.sort };
        let sb = if b.sort.is_nan() { f64::NEG_INFINITY } else { b.sort };
        sb.partial_cmp(&sa)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| a.symbol.cmp(&b.symbol))
    });
    result.ranked_pool = pool.len();
    result.hits = pool.into_iter().take(req.limit).collect();
    Ok(result)
}
