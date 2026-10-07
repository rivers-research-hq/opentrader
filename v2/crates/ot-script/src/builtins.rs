//! Built-ins — declared lookback + light type signatures (spec §4).
//! Every averaging family declares its lookback so per-binding warm-up is
//! static; EMA/Wilders additionally declare a prefetch convention
//! (warm-up = 4×length) per spec §1.4.

use crate::ast::{Expr, Type};
use crate::check::{CheckError, Ctx};
use std::collections::BTreeSet;

/// Fundamentals are identifiers (`close`, `volume`, …), not calls.
pub fn is_fundamental(name: &str) -> bool {
    matches!(
        name,
        "open" | "high" | "low" | "close" | "volume"
            | "hl2" | "hlc3" | "ohlc4"
            | "NaN" | "Infinity"
    )
}

/// Declared parameter order per built-in — resolves positional args
/// (ThinkScript-compatible; the named form is canonical and order-free).
pub fn param_order(name: &str) -> &'static [&'static str] {
    match name {
        "Average" | "SMA" | "WMA" | "EMA" | "Wilders" | "Highest" | "Lowest"
        | "Sum" | "StDev" | "RSI" => &["data", "length"],
        "ATR" => &["length"],
        "TrueRange" => &[],
        "CrossesAbove" | "CrossesBelow" => &["a", "b"],
        "CompoundValue" => &["length", "visible", "historical"],
        "GetValue" => &["data", "offset"],
        "Abs" | "Log" | "Exp" | "Sqrt" => &["x"],
        "Min" | "Max" => &["a", "b"],
        "Round" => &["x", "places"],
        _ => &[],
    }
}

/// Resolve a call's args to fully-named form: positional args zip with the
/// declared order; mixed positional/named rejected; unknown names rejected.
/// The W2a core set — anything else is an unknown built-in (compile error
/// with the full list).
pub fn is_known_builtin(name: &str) -> bool {
    matches!(
        name,
        "Average" | "SMA" | "WMA" | "EMA" | "Wilders" | "Highest" | "Lowest" | "Sum"
            | "StDev" | "RSI" | "ATR" | "TrueRange" | "CrossesAbove" | "CrossesBelow"
            | "CompoundValue" | "GetValue" | "Abs" | "Log" | "Exp" | "Sqrt" | "Round"
            | "Min" | "Max"
    )
}

pub fn resolve_args(
    name: &str,
    args: &[(Option<String>, Expr)],
) -> Result<Vec<(String, Expr)>, CheckError> {
    if !is_known_builtin(name) {
        return Err(CheckError {
            message: format!(
                "unknown built-in `{name}` (W2a core set: Average, EMA, Wilders, WMA, Highest, Lowest, Sum, StDev, TrueRange, ATR, RSI, CrossesAbove/Below, CompoundValue, GetValue, math; `study` subroutines and the strategy family are later W2 slices)"
            ),
        });
    }
    let has_positional = args.iter().any(|(n, _)| n.is_none());
    let has_named = args.iter().any(|(n, _)| n.is_some());
    if has_positional && has_named {
        return Err(CheckError {
            message: format!("`{name}`: mixing positional and named args is a type error (use all-named or all-positional)"),
        });
    }
    if !has_positional {
        let order = param_order(name);
        for (n, _) in args {
            let Some(n) = n else { unreachable!() };
            if !order.contains(&n.as_str()) {
                return Err(CheckError {
                    message: format!("`{name}`: unknown parameter `{n}` (expected one of {order:?})"),
                });
            }
        }
        return Ok(args.iter().map(|(n, e)| (n.clone().unwrap(), e.clone())).collect());
    }
    let order = param_order(name);
    if args.len() > order.len() {
        return Err(CheckError {
            message: format!("`{name}`: too many positional args (takes {order:?})"),
        });
    }
    Ok(args
        .iter()
        .zip(order)
        .map(|((_, e), pname)| (pname.to_string(), e.clone()))
        .collect())
}

/// Static lookback a built-in adds to its arguments' lookback.
/// Signature: fn(name, named args) → lookback bars.
pub fn declared_lookback(
    name: &str,
    args: &[(String, Expr)],
    input_default: &dyn Fn(&str) -> Option<f64>,
) -> Result<i64, CheckError> {
    let arg_val = |key: &str| -> Option<f64> {
        for (k, e) in args {
            if k == key {
                match e {
                    Expr::Num(v) => return Some(*v),
                    // an input-Ident length resolves through the input's
                    // declared default (the static-bound convention; the
                    // host may exceed it — warm-up then recomputes honestly)
                    Expr::Ident(n, _) => return input_default(n),
                    _ => {}
                }
            }
        }
        None
    };
    Ok(match name {
        // Technical family
        "Average" | "SMA" | "WMA" | "Highest" | "Lowest" | "Sum" | "StDev" => {
            let n = arg_val("length").ok_or_else(|| CheckError {
                message: format!("{name} requires `length = <n>`"),
            })?;
            (n as i64 - 1).max(0)
        }
        // EMA/Wilders: recursive — lookback 0, warm-up via the prefetch
        // convention (4×length) recorded at eval; see spec §1.4.
        "EMA" | "Wilders" => 0,
        "TrueRange" => 1, // needs previous close
        "ATR" => {
            let n = arg_val("length").ok_or_else(|| CheckError {
                message: "ATR requires `length = <n>`".into(),
            })?;
            n as i64 // TrueRange's 1 + the Wilders seed
        }
        "RSI" => {
            let n = arg_val("length").ok_or_else(|| CheckError {
                message: "RSI requires `length = <n>`".into(),
            })?;
            n as i64
        }
        "CrossesAbove" | "CrossesBelow" => 1,
        // CompoundValue IS the early-bar tool: it substitutes `historical`
        // before bar n, so its own lookback is 0 (args may carry more).
        "CompoundValue" => 0,
        "GetValue" => {
            // dynamic offset with a declared cap; the CAP bounds the
            // lookback (spec §3).
            arg_val("max_offset").map(|v| v as i64).unwrap_or(0)
        }
        // Math family — pointwise
        "Abs" | "Min" | "Max" | "Log" | "Exp" | "Sqrt" | "Round" => 0,
        other => {
            return Err(CheckError {
                message: format!(
                    "unknown built-in `{other}` (W2a core set: Average, EMA, Wilders, WMA, Highest, Lowest, Sum, StDev, TrueRange, ATR, RSI, CrossesAbove/Below, CompoundValue, GetValue, math; `study` subroutines and the strategy family are later W2 slices)"
                ),
            })
        }
    })
}

/// Return type of a built-in call.
pub fn return_type(name: &str) -> Type {
    match name {
        "CrossesAbove" | "CrossesBelow" => Type::Bool,
        _ => Type::Float,
    }
}

/// Light signature check + recursive type check of the arguments.
pub fn check_call(
    ctx: &mut Ctx,
    name: &str,
    args: &[(Option<String>, Expr)],
    visiting: &mut BTreeSet<String>,
) -> Result<Type, CheckError> {
    // fundamentals callable with no args? They are identifiers; a call form
    // is accepted only for the period-param future — reject for now.
    if is_fundamental(name) {
        return Err(CheckError {
            message: format!(
                "`{name}(...)` — fundamental data params (`symbol`/`period` = secondary frames) land in a later W2 slice; use the bare identifier"
            ),
        });
    }
    let resolved = resolve_args(name, args)?;
    let input_default = |n: &str| -> Option<f64> {
        ctx.plan.inputs.get(n).and_then(|s| s.default.as_f64())
    };
    let _ = declared_lookback(name, &resolved, &input_default)?;
    for (_, a) in &resolved {
        crate::check::type_of_pub(ctx, a, visiting)?;
    }
    Ok(return_type(name))
}

/// Prefetch-convention warm-up (spec §1.4): EMA/Wilders/RSI/ATR converge
/// asymptotically — the host must supply 4×length of prior bars for the
/// emitted value to be history-independent within published tolerance.
/// Returns 0 for stateless built-ins.
pub fn declared_warmup(
    name: &str,
    args: &[(String, Expr)],
    input_default: &dyn Fn(&str) -> Option<f64>,
) -> i64 {
    let arg_val = |key: &str| -> i64 {
        for (k, e) in args {
            if k == key {
                match e {
                    Expr::Num(v) => return *v as i64,
                    Expr::Ident(n, _) => return input_default(n).map(|f| f as i64).unwrap_or(0),
                    _ => {}
                }
            }
        }
        0
    };
    match name {
        "EMA" | "Wilders" => 4 * arg_val("length"),
        "RSI" => 4 * arg_val("length") + 1,
        "ATR" => 4 * arg_val("length") + 1,
        _ => 0,
    }
}
