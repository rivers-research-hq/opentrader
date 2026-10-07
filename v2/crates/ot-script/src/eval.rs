//! The evaluator — bar-by-bar, columnar, lazy-branch, capability-sandboxed.
//!
//! Model (spec §1/§6): each binding is a column; evaluation walks bars in
//! order; at bar t an expression evaluates with history access relative to
//! t; only the taken if-branch evaluates per bar. `series` bindings carry
//! their [1] state from previous bars (explicit init at bar 0 — no implicit
//! initialization). Bars before a binding's static warm-up are NaN.
//! Comparisons with NaN are false (bool columns stay total). Arithmetic
//! with NaN → NaN. Stateful built-ins (EMA/RSI/ATR) carry per-call-site
//! columns keyed by an arena index — the same node always owns the same
//! state slot (determinism).

use crate::ast::*;
use crate::check::{BindingKind, CompilePlan, CondSpec};
use crate::ast::{StrategyAction, StrategyItem};
use crate::check::{OnAction, OnPlan};
use serde_json::Value;
use std::collections::BTreeMap;

/// Host-facing eval request (spec §6 ScriptRequest shape; single
/// symbol/frame in W2a — the host supplies the bars).
#[derive(Debug, Clone)]
pub struct ScriptRequest {
    pub source: String,
    pub symbol: String,
    pub timeframe: String,
    /// Declared inputs (JSON; script defaults apply when absent).
    pub inputs: BTreeMap<String, Value>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Warmup {
    Complete,
    /// the last bar's value may still depend on loaded-history length
    /// (unbounded warm-up — spec §1.4: consumers must not present as final)
    Incomplete,
}

#[derive(Debug, Clone)]
pub struct Plot {
    pub name: String,
    pub values: Vec<f64>,
    pub pane: Option<crate::check::Pane>,
}

#[derive(Debug, Clone)]
pub struct EvalOutput {
    pub plots: Vec<Plot>,
    /// Named scalars: the LAST defined value of every def/series (spec §8).
    pub last: BTreeMap<String, f64>,
    pub warmup_complete: Warmup,
    pub bars: usize,
}

/// Evaluation frame: one symbol's bars on the primary timeframe.
pub struct Frame<'a> {
    pub bars: &'a [ot_core::bar::Bar],
}

impl<'a> Frame<'a> {
    /// Universe view for the strategy runner (single symbol, master = the
    /// frame's bar timestamps).
    pub(crate) fn bars_as_universe(&self, symbol: &str) -> ot_core::universe::Universe {
        let mut series = std::collections::BTreeMap::new();
        let mut vols = std::collections::BTreeMap::new();
        series.insert(
            symbol.to_string(),
            ot_core::bar::Series::from_bars(self.bars.to_vec()),
        );
        vols.insert(
            symbol.to_string(),
            self.bars.iter().map(|b| b.volume).collect(),
        );
        ot_core::universe::Universe::from_series(series, vols)
    }
}

#[derive(Debug, Clone, Copy, PartialEq)]
enum Val {
    Bool(bool),
    Num(f64),
    Str,
}

impl Val {
    fn as_f64(self) -> f64 {
        match self {
            Val::Num(v) => v,
            _ => f64::NAN, // bool/str as f64 is unreachable in typed code
        }
    }
    fn as_bool(self) -> bool {
        match self {
            Val::Bool(b) => b,
            _ => false, // NaN semantics: comparisons with NaN are false
        }
    }
}

pub enum Column {
    Float(Vec<f64>),
    Bool(Vec<bool>),
}

impl Column {
    fn push(&mut self, v: Val) {
        match self {
            Column::Float(f) => f.push(v.as_f64()),
            Column::Bool(b) => b.push(v.as_bool()),
        }
    }
    fn get(&self, i: usize) -> Val {
        match self {
            Column::Float(f) => Val::Num(f[i]),
            Column::Bool(b) => Val::Bool(b[i]),
        }
    }
    fn len(&self) -> usize {
        match self {
            Column::Float(f) => f.len(),
            Column::Bool(b) => b.len(),
        }
    }
}

/// Indexed expression arena — Call nodes get stable ids for state slots.
#[derive(Clone)]
enum EExpr {
    Num(f64),
    Bool(bool),
    Str,
    Ident(String),
    /// history read: name, back (static, non-negative)
    Hist(String, usize),
    Bin(BinOp, usize, usize),
    Not(usize),
    /// lazy if: only the taken branch evaluates
    If(usize, usize, usize),
    Call { id: usize, name: String, args: Vec<(Option<String>, usize)> },
}

struct Arena {
    nodes: Vec<EExpr>,
    #[allow(dead_code)] // the host re-derives roots via stmt_exprs; kept for the W2b host-binding seam
    root: usize,
}

fn build_arena(e: &Expr, nodes: &mut Vec<EExpr>) -> usize {
    let id = nodes.len();
    nodes.push(EExpr::Num(f64::NAN)); // placeholder (reserve the slot)
    let filled = match e {
        Expr::Num(v) => EExpr::Num(*v),
        Expr::BoolLit(b) => EExpr::Bool(*b),
        Expr::StrLit(_) => EExpr::Str,
        Expr::Ident(name, _) => EExpr::Ident(name.clone()),
        Expr::Index(inner, n) => {
            let name = match inner.as_ref() {
                Expr::Ident(name, _) => name.clone(),
                _ => String::new(), // checker rejects non-ident bases
            };
            EExpr::Hist(name, (*n).max(0) as usize)
        }
        Expr::Bin { op, lhs, rhs } => {
            let l = build_arena(lhs, nodes);
            let r = build_arena(rhs, nodes);
            EExpr::Bin(*op, l, r)
        }
        Expr::Not(inner) => EExpr::Not(build_arena(inner, nodes)),
        Expr::If { cond, then, els } => {
            let c = build_arena(cond, nodes);
            let t = build_arena(then, nodes);
            let e2 = build_arena(els, nodes);
            EExpr::If(c, t, e2)
        }
        Expr::Call { name, args, .. } => {
            let mut a = Vec::new();
            for (k, v) in args {
                a.push((k.clone(), build_arena(v, nodes)));
            }
            EExpr::Call { id, name: name.clone(), args: a }
        }
    };
    nodes[id] = filled;
    id
}

struct Machine<'a> {
    bars: &'a [ot_core::bar::Bar],
    bindings: BTreeMap<String, (BindingKind, Type, i64, i64)>, // kind, ty, lookback, warmup
    stmt_exprs: BTreeMap<String, (Option<usize>, Option<usize>)>, // def/plot: arena root; series: (init, step)
    columns: BTreeMap<String, Column>,
    arenas: BTreeMap<String, Arena>,
    inputs: BTreeMap<String, Val>,
    /// stateful-builtin slots keyed by arena node id
    state: BTreeMap<usize, Column>,
    visiting: Vec<String>,
}

impl<'a> Machine<'a> {
    fn col(&self, name: &str) -> Option<&Column> {
        self.columns.get(name)
    }

    /// Ensure a binding's column is defined through bar t (on-demand,
    /// memoized; recursion handles dependencies declared out of order).
    fn ensure(&mut self, name: &str, t: usize) -> Result<(), String> {
        let need = t + 1;
        let have = self.col(name).map(|c| c.len()).unwrap_or(0);
        if have >= need {
            return Ok(());
        }
        if self.visiting.iter().any(|v| v == name) {
            return Err(format!("cyclic evaluation of `{name}`"));
        }
        self.visiting.push(name.to_string());
        let res = (|| {
            let Some((kind, _, _lookback, _warmup)) = self.bindings.get(name).copied() else {
                return Err(format!("unknown binding `{name}`"));
            };
            match kind {
                BindingKind::Input => {
                    let v = self.inputs.get(name).copied().unwrap_or(Val::Num(f64::NAN));
                    for _ in have..need {
                        self.columns.get_mut(name).unwrap().push(v);
                    }
                    Ok(())
                }
                BindingKind::Series => {
                    let (init, step) = self.stmt_exprs[name].clone();
                    let (init, step) = (
                        init.expect("series init"),
                        step.expect("series step"),
                    );
                    // explicit-init state machine (spec §1.1): init at bar
                    // 0; step reads self via the column's own history.
                    // (visiting stays balanced: entry push popped by the
                    // shared pop at the end of ensure.)
                    for tt in have..need {
                        let v = if tt == 0 {
                            self.eval(init, 0)?
                        } else {
                            self.eval(step, tt)?
                        };
                        self.columns.get_mut(name).unwrap().push(v);
                    }
                    Ok(())
                }
                _ => {
                    let root = self.stmt_exprs[name].0.expect("expr root");
                    // visiting stays balanced: the entry push serves the
                    // whole loop (eval() reads visiting.back() as the arena
                    // — which must be THIS binding); the shared pop at the
                    // end of ensure handles the bookkeeping.
                    for tt in have..need {
                        // no warm-up gate: history holes NaN naturally via
                        // Hist (back > t); static warm-up stays in the plan
                        // as host metadata + completeness flag (spec §1.4)
                        let v = self.eval(root, tt)?;
                        self.columns.get_mut(name).unwrap().push(v);
                    }
                    Ok(())
                }
            }
        })();
        let popped = self.visiting.pop();
        debug_assert_eq!(popped.as_deref(), Some(name));
        res
    }

    fn eval(&mut self, node: usize, t: usize) -> Result<Val, String> {
        // the active arena is the binding being evaluated (visiting.back());
        // clone the node out (shallow — children are usize indices) so the
        // recursive &mut self calls don't fight the arena borrow.
        let binding = self.visiting.last().cloned().unwrap_or_default();
        let node_v = {
            let arena = self
                .arenas
                .get(&binding)
                .ok_or_else(|| format!("no arena for `{binding}`"))?;
            arena.nodes[node].clone()
        };
        Ok(match &node_v {
            EExpr::Num(v) => Val::Num(*v),
            EExpr::Bool(b) => Val::Bool(*b),
            EExpr::Str => Val::Str,
            EExpr::Ident(name) => {
                if let Some(v) = self.inputs.get(name) {
                    return Ok(*v);
                }
                if crate::builtins::is_fundamental(name) {
                    return Ok(fundamental(self.bars, name, t));
                }
                self.ensure(name, t)?;
                self.col(name).map(|c| c.get(t)).unwrap_or(Val::Num(f64::NAN))
            }
            EExpr::Hist(name, back) => {
                if let Some(v) = self.inputs.get(name) {
                    return Ok(*v); // constant series
                }
                if crate::builtins::is_fundamental(name) {
                    return Ok(if *back > t {
                        Val::Num(f64::NAN)
                    } else {
                        fundamental(self.bars, name, t - back)
                    });
                }
                if *back > t {
                    return Ok(Val::Num(f64::NAN));
                }
                self.ensure(name, t - back)?;
                self.col(name)
                    .map(|c| c.get(t - back))
                    .unwrap_or(Val::Num(f64::NAN))
            }
            EExpr::Bin(op, l, r) => {
                let lv = self.eval(*l, t)?;
                let rv = self.eval(*r, t)?;
                let lf = lv.as_f64();
                let rf = rv.as_f64();
                match op {
                    BinOp::Add => Val::Num(lf + rf),
                    BinOp::Sub => Val::Num(lf - rf),
                    BinOp::Mul => Val::Num(lf * rf),
                    BinOp::Div => Val::Num(lf / rf),
                    BinOp::And => Val::Bool(lv.as_bool() && rv.as_bool()),
                    BinOp::Or => Val::Bool(lv.as_bool() || rv.as_bool()),
                    BinOp::Xor => Val::Bool(lv.as_bool() ^ rv.as_bool()),
                    BinOp::Eq => Val::Bool(match (lv, rv) {
                        (Val::Bool(a), Val::Bool(b)) => a == b,
                        _ => !lf.is_nan() && !rf.is_nan() && lf == rf,
                    }),
                    BinOp::Ne => Val::Bool(match (lv, rv) {
                        (Val::Bool(a), Val::Bool(b)) => a != b,
                        _ => lf.is_nan() || rf.is_nan() || lf != rf,
                    }),
                    // NaN comparisons are false (bool columns stay total)
                    BinOp::Lt => Val::Bool(!lf.is_nan() && !rf.is_nan() && lf < rf),
                    BinOp::Gt => Val::Bool(!lf.is_nan() && !rf.is_nan() && lf > rf),
                    BinOp::Le => Val::Bool(!lf.is_nan() && !rf.is_nan() && lf <= rf),
                    BinOp::Ge => Val::Bool(!lf.is_nan() && !rf.is_nan() && lf >= rf),
                }
            }
            EExpr::Not(inner) => Val::Bool(!self.eval(*inner, t)?.as_bool()),
            EExpr::If(c, a, b) => {
                // LAZY: only the taken branch evaluates (spec §1.2)
                let cv = self.eval(*c, t)?;
                if cv.as_bool() {
                    self.eval(*a, t)?
                } else {
                    self.eval(*b, t)?
                }
            }
            EExpr::Call { id, name, args } => eval_builtin(self, *id, name, args, t)?,
        })
    }
}

fn fundamental(bars: &[ot_core::bar::Bar], name: &str, t: usize) -> Val {
    if t >= bars.len() {
        return Val::Num(f64::NAN);
    }
    let b = &bars[t];
    Val::Num(match name {
        "open" => b.open,
        "high" => b.high,
        "low" => b.low,
        "close" => b.close,
        "volume" => b.volume,
        "hl2" => (b.high + b.low) / 2.0,
        "hlc3" => (b.high + b.low + b.close) / 3.0,
        "ohlc4" => (b.open + b.high + b.low + b.close) / 4.0,
        "NaN" => f64::NAN,
        "Infinity" => f64::INFINITY,
        _ => f64::NAN,
    })
}

/// Evaluate a built-in call at bar t. Named args (order-free) resolve
/// through each built-in's signature.
fn eval_builtin(
    m: &mut Machine,
    id: usize,
    name: &str,
    raw_args: &[(Option<String>, usize)],
    t: usize,
) -> Result<Val, String> {
    // resolve positional → named (same rule as the checker)
    let args: Vec<(String, usize)> = {
        let has_positional = raw_args.iter().any(|(n, _)| n.is_none());
        let has_named = raw_args.iter().any(|(n, _)| n.is_some());
        if has_positional && has_named {
            return Err(format!("`{name}`: mixed positional/named args"));
        }
        if !has_positional {
            raw_args.iter().map(|(n, v)| (n.clone().unwrap(), *v)).collect()
        } else {
            let order = crate::builtins::param_order(name);
            if raw_args.len() > order.len() {
                return Err(format!("`{name}`: too many positional args"));
            }
            raw_args
                .iter()
                .zip(order)
                .map(|((_, v), pname)| (pname.to_string(), *v))
                .collect()
        }
    };
    let get = |m: &mut Machine, key: &str| -> Result<Val, String> {
        let node = args
            .iter()
            .find(|(k, _)| k == key)
            .map(|(_, v)| *v)
            .ok_or_else(|| format!("{name}: missing arg `{key}`"))?;
        m.eval(node, t)
    };
    let arg_f = |m: &mut Machine, key: &str| -> Result<f64, String> { Ok(get(m, key)?.as_f64()) };
    let num = |v: Val| -> f64 { v.as_f64() };
    let nan = f64::NAN;

    match name {
        // ── windowed (stateless) families ──────────────────────────────
        "Average" | "SMA" | "WMA" | "Highest" | "Lowest" | "Sum" | "StDev" => {
            let n = arg_f(m, "length")? as usize;
            if t + 1 < n || n == 0 {
                return Ok(Val::Num(nan));
            }
            let data = args
                .iter()
                .find(|(k, _)| k == "data")
                .map(|(_, v)| *v)
                .ok_or_else(|| format!("{name}: missing arg `data`"))?;
            let mut vals = Vec::with_capacity(n);
            for back in (0..n).rev() {
                vals.push(num(m.eval(data, t - back)?));
            }
            Ok(Val::Num(match name {
                "Average" | "SMA" => vals.iter().sum::<f64>() / n as f64,
                "WMA" => {
                    let denom = n * (n + 1) / 2;
                    let mut acc = 0.0;
                    for (i, v) in vals.iter().enumerate() {
                        acc += v * (i as f64 + 1.0);
                    }
                    acc / denom as f64
                }
                "Highest" => vals.iter().cloned().fold(nan, f64::max),
                "Lowest" => vals.iter().cloned().fold(nan, f64::min),
                "Sum" => vals.iter().sum(),
                "StDev" => {
                    let mean = vals.iter().sum::<f64>() / n as f64;
                    let ss: f64 = vals.iter().map(|v| (v - mean) * (v - mean)).sum();
                    (ss / (n as f64 - 1.0)).sqrt()
                }
                _ => nan,
            }))
        }
        // ── stateful recursive families (per-call-site state) ──────────
        "EMA" => {
            let n = arg_f(m, "length")? as usize;
            let data = arg_node(&args, "data")?;
            ema_like(m, id, data, t, n, |prev, x, n| prev + (x - prev) * (2.0 / (n as f64 + 1.0)))
        }
        "Wilders" => {
            let n = arg_f(m, "length")? as usize;
            let data = arg_node(&args, "data")?;
            ema_like(m, id, data, t, n, |prev, x, n| prev + (x - prev) / n as f64)
        }
        "RSI" => {
            let n = arg_f(m, "length")? as usize;
            if t < n {
                return Ok(Val::Num(nan));
            }
            let data = arg_node(&args, "data")?;
            // Wilders-smoothed gains/losses; centered output (ThinkScript)
            let cur = num(m.eval(data, t)?);
            let prev = num(m.eval(data, t - 1)?);
            let gain = if cur > prev { cur - prev } else { 0.0 };
            let loss = if cur < prev { prev - cur } else { 0.0 };
            let (ag, al) = match m.state.get(&id) {
                Some(Column::Float(f)) if f.len() >= 2 => (f[f.len() - 2], f[f.len() - 1]),
                _ => (f64::NAN, f64::NAN),
            };
            let (ag, al) = if ag.is_nan() {
                // seed at bar n: SMA of gains/losses over n bars
                let mut sg = 0.0;
                let mut sl = 0.0;
                for back in 0..n {
                    let c0 = num(m.eval(data, t - back)?);
                    let c1 = num(m.eval(data, t - back - 1)?);
                    sg += if c0 > c1 { c0 - c1 } else { 0.0 };
                    sl += if c0 < c1 { c1 - c0 } else { 0.0 };
                }
                (sg / n as f64, sl / n as f64)
            } else {
                (
                    (ag * (n as f64 - 1.0) + gain) / n as f64,
                    (al * (n as f64 - 1.0) + loss) / n as f64,
                )
            };
            push_state(m, id, ag, al);
            if al == 0.0 || al.is_nan() || ag.is_nan() {
                return Ok(Val::Num(nan));
            }
            let rs = ag / al;
            let rsi = 100.0 - 100.0 / (1.0 + rs);
            Ok(Val::Num((rsi - 50.0) / 50.0))
        }
        "ATR" => {
            let n = arg_f(m, "length")? as usize;
            if m.bars.is_empty() {
                return Ok(Val::Num(nan));
            }
            let tr = true_range(m.bars, t);
            let prev = match m.state.get(&id) {
                Some(Column::Float(f)) if !f.is_empty() => f[f.len() - 1],
                _ => f64::NAN,
            };
            let atr = if prev.is_nan() {
                if t + 1 < n {
                    return Ok(Val::Num(nan));
                }
                // seed: SMA of TR over the first n bars
                let mut acc = 0.0;
                for i in 0..n {
                    acc += true_range(m.bars, i);
                }
                acc / n as f64
            } else {
                prev + (tr - prev) / n as f64
            };
            push_state(m, id, atr, f64::NAN);
            Ok(Val::Num(atr))
        }
        "TrueRange" => Ok(Val::Num(true_range(m.bars, t))),
        "CrossesAbove" | "CrossesBelow" => {
            let a = arg_node(&args, "a")?;
            let b = arg_node(&args, "b")?;
            if t == 0 {
                return Ok(Val::Bool(false));
            }
            let (a0, a1) = (num(m.eval(a, t - 1)?), num(m.eval(a, t)?));
            let (b0, b1) = (num(m.eval(b, t - 1)?), num(m.eval(b, t)?));
            if a0.is_nan() || a1.is_nan() || b0.is_nan() || b1.is_nan() {
                return Ok(Val::Bool(false));
            }
            Ok(Val::Bool(if name == "CrossesAbove" {
                a0 <= b0 && a1 > b1
            } else {
                a0 >= b0 && a1 < b1
            }))
        }
        "CompoundValue" => {
            let n = arg_f(m, "length")? as usize;
            let visible = arg_node(&args, "visible")?;
            let historical = arg_node(&args, "historical")?;
            if t >= n {
                m.eval(visible, t)
            } else {
                m.eval(historical, t)
            }
        }
        "GetValue" => {
            let data = arg_node(&args, "data")?;
            let offset = arg_f(m, "offset")?;
            if offset < 0.0 || offset.fract() != 0.0 || (offset as usize) > t {
                return Ok(Val::Num(nan));
            }
            m.eval(data, t - offset as usize)
        }
        // ── math family (pointwise) ────────────────────────────────────
        "Abs" => Ok(Val::Num(arg_f(m, "x")?.abs())),
        "Log" => Ok(Val::Num(arg_f(m, "x")?.ln())),
        "Exp" => Ok(Val::Num(arg_f(m, "x")?.exp())),
        "Sqrt" => Ok(Val::Num(arg_f(m, "x")?.sqrt())),
        "Round" => Ok(Val::Num({
            let x = arg_f(m, "x")?;
            let places = args.iter().find(|(k, _)| k == "places").map(|(_, v)| v);
            match places {
                Some(pnode) => {
                    let p = num(m.eval(*pnode, t)?);
                    let f = 10f64.powf(p);
                    (x * f).round() / f
                }
                None => x.round(),
            }
        })),
        "Min" => {
            let a = arg_f(m, "a")?;
            let b = arg_f(m, "b")?;
            Ok(Val::Num(if a.is_nan() { b } else if b.is_nan() { a } else { a.min(b) }))
        }
        "Max" => {
            let a = arg_f(m, "a")?;
            let b = arg_f(m, "b")?;
            Ok(Val::Num(if a.is_nan() { b } else if b.is_nan() { a } else { a.max(b) }))
        }
        other => Err(format!("unknown built-in `{other}`")),
    }
}

fn arg_node(args: &[(String, usize)], key: &str) -> Result<usize, String> {
    args.iter()
        .find(|(k, _)| k == key)
        .map(|(_, v)| *v)
        .ok_or_else(|| format!("missing arg `{key}`"))
}

fn ema_like(
    m: &mut Machine,
    id: usize,
    data: usize,
    t: usize,
    n: usize,
    step: impl Fn(f64, f64, usize) -> f64,
) -> Result<Val, String> {
    let nan = f64::NAN;
    if n == 0 {
        return Ok(Val::Num(nan));
    }
    let prev = match m.state.get(&id) {
        Some(Column::Float(f)) if !f.is_empty() => f[f.len() - 1],
        _ => nan,
    };
    let x = m.eval(data, t)?.as_f64();
    let v = if prev.is_nan() {
        if t + 1 < n {
            push_state(m, id, nan, f64::NAN);
            return Ok(Val::Num(nan));
        }
        // seed: SMA of the first n bars
        let mut acc = 0.0;
        for back in (0..n).rev() {
            acc += m.eval(data, t - back)?.as_f64();
        }
        acc / n as f64
    } else {
        step(prev, x, n)
    };
    push_state(m, id, v, f64::NAN);
    Ok(Val::Num(v))
}

fn push_state(m: &mut Machine, id: usize, a: f64, b: f64) {
    let col = m.state.entry(id).or_insert_with(|| Column::Float(Vec::new()));
    if let Column::Float(f) = col {
        f.push(a);
        if !b.is_nan() {
            f.push(b);
        }
    }
}

fn true_range(bars: &[ot_core::bar::Bar], t: usize) -> f64 {
    if t >= bars.len() {
        return f64::NAN;
    }
    let b = &bars[t];
    if t == 0 {
        return b.high - b.low;
    }
    let pc = bars[t - 1].close;
    (b.high - b.low).max((b.high - pc).abs()).max((b.low - pc).abs())
}

/// Evaluate a compiled script over a frame (the host seam — spec §6).
pub fn evaluate(
    request: &ScriptRequest,
    plan: &CompilePlan,
    frame: &Frame,
) -> Result<EvalOutput, String> {
    evaluate_full(request, plan, frame).map(|(out, _)| out)
}

/// Full evaluation including the raw columns (the strategy runner needs
/// the on-condition and Entry-value columns).
pub fn evaluate_full(
    request: &ScriptRequest,
    plan: &CompilePlan,
    frame: &Frame,
) -> Result<(EvalOutput, BTreeMap<String, Column>), String> {
    // Re-parse (the plan is the cached static half; source re-parses for
    // eval — hot-reload friendly and deterministic).
    let tokens = crate::lexer::lex(&request.source)?;
    let stmts = crate::parser::parse(&tokens)?;
    let checked = crate::check::check(stmts.clone()).map_err(|e2| e2.to_string())?;
    if checked.eval_order != plan.eval_order {
        return Err("plan/source mismatch (stale compile plan?)".into());
    }

    let bars = frame.bars.len();
    let mut m = Machine {
        bars: frame.bars,
        bindings: BTreeMap::new(),
        stmt_exprs: BTreeMap::new(),
        columns: BTreeMap::new(),
        arenas: BTreeMap::new(),
        inputs: BTreeMap::new(),
        state: BTreeMap::new(),
        visiting: Vec::new(),
    };

    // inputs (defaults + overrides, type-checked)
    for (name, spec) in &checked.inputs {
        let v = match request.inputs.get(name) {
            Some(Value::Bool(b)) => {
                if spec.ty != Type::Bool {
                    return Err(format!("input `{name}` expects {:?}", spec.ty));
                }
                Val::Bool(*b)
            }
            Some(Value::Number(n)) => {
                if spec.ty == Type::Bool || spec.ty == Type::Str {
                    return Err(format!("input `{name}` expects {:?}", spec.ty));
                }
                Val::Num(n.as_f64().unwrap_or(f64::NAN))
            }
            Some(Value::String(s)) => {
                if spec.ty != Type::Str {
                    return Err(format!("input `{name}` expects {:?}", spec.ty));
                }
                let _ = s;
                Val::Str
            }
            Some(other) => return Err(format!("input `{name}` bad value {other}")),
            None => match &spec.default {
                Value::Bool(b) => Val::Bool(*b),
                Value::Number(n) => Val::Num(n.as_f64().unwrap_or(f64::NAN)),
                Value::String(_) => Val::Str,
                _ => Val::Num(f64::NAN),
            },
        };
        m.inputs.insert(name.clone(), v);
    }

    // per-binding: kind/ty/lookback/warmup + arenas + stmt roots
    let mut stmt_iter = stmts.iter();
    for b in &checked.bindings {
        let col = match b.ty {
            Type::Bool => Column::Bool(Vec::with_capacity(bars)),
            _ => Column::Float(Vec::with_capacity(bars)),
        };
        m.columns.insert(b.name.clone(), col);
        m.bindings.insert(
            b.name.clone(),
            (b.kind, b.ty, b.lookback, b.warmup),
        );
        if b.kind == BindingKind::Input {
            continue; // resolved via machine.inputs; no statement
        }
        if b.name.contains("::") {
            continue; // strategy-hidden binding — arena built in the
                      // Stmt::Strategy walk below
        }
        // advance the statement iterator to this binding's statement
        let stmt = loop {
            match stmt_iter.next() {
                Some(s @ (Stmt::Def { name, .. }
                | Stmt::Series { name, .. }
                | Stmt::Plot { name, .. })) if name == &b.name => break s,
                Some(_) => continue,
                None => return Err(format!("plan binding `{}` missing from source", b.name)),
            }
        };
        let (kind, ty, lookback, warmup) = (
            b.kind,
            b.ty,
            b.lookback,
            b.warmup,
        );
        m.bindings
            .insert(b.name.clone(), (kind, ty, lookback, warmup));
        match stmt {
            Stmt::Def { expr, .. } | Stmt::Plot { expr: Some(expr), .. } => {
                let mut nodes = Vec::new();
                let root = build_arena(expr, &mut nodes);
                m.arenas.insert(b.name.clone(), Arena { nodes, root });
                m.stmt_exprs.insert(b.name.clone(), (Some(root), None));
            }
            Stmt::Series { init, step, .. } => {
                let mut nodes = Vec::new();
                let r0 = build_arena(init, &mut nodes);
                let r1 = build_arena(step, &mut nodes);
                m.arenas.insert(b.name.clone(), Arena { nodes, root: r0 });
                m.stmt_exprs.insert(b.name.clone(), (Some(r0), Some(r1)));
            }
            _ => {
                m.stmt_exprs.insert(b.name.clone(), (None, None));
            }
        }
    }

    // strategy blocks: build arenas for their namespaced bindings
    for s in &stmts {
        let Stmt::Strategy(sb) = s else { continue };
        let ns = format!("{}::", sb.name);
        let mut k = 0usize;
        for item in &sb.items {
            match item {
                StrategyItem::Def { name, expr } => {
                    let rexpr = crate::check::rewrite_pub(expr, &ns, &sb.name).map_err(|e2| e2.to_string())?;
                    let mut nodes = Vec::new();
                    let root = build_arena(&rexpr, &mut nodes);
                    m.arenas.insert(format!("{ns}{name}"), Arena { nodes, root });
                    m.stmt_exprs.insert(format!("{ns}{name}"), (Some(root), None));
                }
                StrategyItem::Series { name, init, step } => {
                    let rinit = crate::check::rewrite_pub(init, &ns, &sb.name).map_err(|e2| e2.to_string())?;
                    let rstep = crate::check::rewrite_pub(step, &ns, &sb.name).map_err(|e2| e2.to_string())?;
                    let mut nodes = Vec::new();
                    let r0 = build_arena(&rinit, &mut nodes);
                    let r1 = build_arena(&rstep, &mut nodes);
                    m.arenas.insert(format!("{ns}{name}"), Arena { nodes, root: r0 });
                    m.stmt_exprs.insert(format!("{ns}{name}"), (Some(r0), Some(r1)));
                }
                StrategyItem::On { cond, .. } => {
                    let Some(on_plan) = checked.strategies.first().and_then(|sp| sp.ons.get(k))
                    else {
                        k += 1;
                        continue;
                    };
                    k += 1;
                    let CondSpec::Column(qn) = &on_plan.cond else { continue };
                    let rcond = crate::check::rewrite_pub(cond, &ns, &sb.name).map_err(|e2| e2.to_string())?;
                    let mut nodes = Vec::new();
                    let root = build_arena(&rcond, &mut nodes);
                    m.arenas.insert(qn.clone(), Arena { nodes, root });
                    m.stmt_exprs.insert(qn.clone(), (Some(root), None));
                }
                StrategyItem::Input { .. } => {}
            }
        }
        // hidden Entry value bindings (size/stop/target): their exprs are
        // re-derived from the parsed items — the plan carries only names.
        // Match ons to Entry items by order of appearance.
        let mut oi = 0usize;
        for item in &sb.items {
            let StrategyItem::On { cond, action } = item else { continue };
            let _ = cond;
            let Some(on_plan) = checked.strategies.first().and_then(|sp| sp.ons.get(oi)) else {
                oi += 1;
                continue;
            };
            oi += 1;
            let StrategyAction::Entry { args } = action else { continue };
            let OnAction::Entry { size, stop, target } = &on_plan.action else { continue };
            let resolve = |plan_name: &Option<String>, want: &str| -> Option<(String, Expr)> {
                // find the arg matching the plan's binding suffix
                let Some(pn) = plan_name else { return None };
                for (n, a) in args {
                    let is_match = match n {
                        Some(nm) => nm == want,
                        None => {
                            // positional: Entry's declared order
                            let _order = ["side", "size", "stop", "target"];
                            args.iter()
                                .filter(|(n2, _)| n2.is_none())
                                .position(|(n2, _)| n2.is_none())
                                .map(|_| true)
                                .unwrap_or(false)
                                && {
                                    let positional_idx = args
                                        .iter()
                                        .take_while(|(n2, _)| n2.is_none())
                                        .count();
                                    let _ = positional_idx;
                                    false
                                }
                        }
                    };
                    if is_match {
                        return Some((pn.clone(), a.clone()));
                    }
                }
                None
            };
            let _ = resolve;
            // simpler: positional/named resolution mirroring check_action
            let order = ["side", "size", "stop", "target"];
            let mut named: Vec<(String, &Expr)> = Vec::new();
            if args.iter().any(|(n, _)| n.is_some()) {
                for (n, a) in args {
                    if let Some(n) = n {
                        named.push((n.clone(), a));
                    }
                }
            } else {
                for ((_, a), pname) in args.iter().zip(order) {
                    named.push((pname.to_string(), a));
                }
            }
            for (k, a) in named {
                let want_suffix = match k.as_str() {
                    "size" => ".size",
                    "stop" => ".stop",
                    "target" => ".target",
                    _ => continue,
                };
                let plan_name = match k.as_str() {
                    "size" => size,
                    "stop" => stop,
                    "target" => target,
                    _ => continue,
                };
                let Some(qn) = plan_name else { continue };
                let _ = want_suffix;
                let rexpr = crate::check::rewrite_pub(a, &ns, &sb.name).map_err(|e2| e2.to_string())?;
                let mut nodes = Vec::new();
                let root = build_arena(&rexpr, &mut nodes);
                m.arenas.insert(qn.clone(), Arena { nodes, root });
                m.stmt_exprs.insert(qn.clone(), (Some(root), None));
            }
        }
    }

    // walk bars; every binding evaluated (memoized on demand) per bar
    for t in 0..bars {
        for name in &checked.eval_order {
            m.ensure(name, t)?;
        }
    }

    // outputs
    let mut plots = Vec::new();
    let mut last = BTreeMap::new();
    let mut complete = true;
    // honesty (spec §1.4): stateful `series` bindings make output depend
    // on loaded-history length — flagged, never silent.
    let unbounded = checked.bindings.iter().any(|b| b.kind == BindingKind::Series);
    for b in &checked.bindings {
        let col = &m.columns[&b.name];
        match b.kind {
            BindingKind::Plot => {
                if let Column::Float(f) = col {
                    plots.push(Plot {
                        name: b.name.clone(),
                        values: f.clone(),
                        pane: b.pane,
                    });
                }
            }
            _ => {
                if let Column::Float(f) = col {
                    if let Some(&v) = f.last() {
                        last.insert(b.name.clone(), v);
                    }
                }
            }
        }
        if unbounded || b.warmup < 0 || (bars as i64) < b.warmup {
            complete = false;
        }
    }
    Ok((
        EvalOutput {
            plots,
            last,
            warmup_complete: if complete { Warmup::Complete } else { Warmup::Incomplete },
            bars,
        },
        m.columns,
    ))
}


// ── the strategy runner (spec §7) ─────────────────────────────────────────

/// Extracted strategy columns: on-conditions (bool) and Entry values.
struct StrategyCols {
    bools: BTreeMap<String, Vec<bool>>,
    floats: BTreeMap<String, Vec<f64>>,
}

impl StrategyCols {
    fn b(&self, name: &str, sig: usize) -> bool {
        self.bools.get(name).and_then(|v| v.get(sig)).copied().unwrap_or(false)
    }
    fn f(&self, name: &str, sig: usize) -> Option<f64> {
        self.floats.get(name).and_then(|v| v.get(sig)).copied()
    }
}

/// The handler the engine drives: script conditions (pre-evaluated columns,
/// read at the SIGNAL bar t-1 — the engine contract's decision view) plus
/// MaxHold from engine position state. VIRTUAL orders only: this handler
/// has no venue access by construction (spec §7.3 boundary).
struct StrategyHandler {
    symbol: String,
    ons: Vec<OnPlan>,
    cols: StrategyCols,
}

impl ot_core::engine::Handler for StrategyHandler {
    fn signal_exits(
        &mut self,
        view: &ot_core::engine::DecisionView,
        open: &[ot_core::engine::Position],
    ) -> Vec<(String, ot_core::engine::ExitReason)> {
        if open.is_empty() {
            return vec![];
        }
        let sig = view.sig_t;
        for on in &self.ons {
            // ONLY Exit/Flatten ons drive exits — an Entry condition firing
            // is not an exit signal
            if !matches!(on.action, OnAction::Exit | OnAction::Flatten) {
                continue;
            }
            let fired = match (&on.cond, &on.action) {
                (CondSpec::MaxHold(n), _) => {
                    // the engine increments position age inside the exit
                    // loop AFTER this snapshot — V1's max-hold timing sees
                    // the post-increment age, so compare age+1
                    open.iter().any(|p| p.bars + 1 >= *n)
                }
                (CondSpec::Column(qn), _) => self.cols.b(qn.as_str(), sig),
            };
            if fired {
                return open
                    .iter()
                    .map(|p| (p.sym.clone(), ot_core::engine::ExitReason::Signal))
                    .collect();
            }
        }
        vec![]
    }

    fn candidates(
        &mut self,
        view: &ot_core::engine::DecisionView,
        open: &[ot_core::engine::Position],
    ) -> Vec<ot_core::engine::Candidate> {
        #[cfg(feature = "debug_strategy")]
        eprintln!("cand@{} sig={} open={}", view.fill_t, view.sig_t, open.len());
        // pyramiding off (spec §7.1 default): single position
        if !open.is_empty() {
            return vec![];
        }
        let sig = view.sig_t;
        let Some(close) = view.fill_close(&self.symbol) else {
            return vec![];
        };
        for on in &self.ons {
            let OnAction::Entry { size, stop, target } = &on.action else {
                continue;
            };
            let CondSpec::Column(qn) = &on.cond else { continue };
            if !self.cols.b(qn.as_str(), sig) {
                continue;
            }
            let Some(units) = size.as_ref().and_then(|q| self.cols.f(q, sig)) else {
                return vec![]; // size missing → no entry (not silently sized)
            };
            if units <= 0.0 {
                return vec![];
            }
            let stop_px = stop.as_ref().and_then(|q| self.cols.f(q, sig));
            let target_px = target.as_ref().and_then(|q| self.cols.f(q, sig));
            return vec![ot_core::engine::Candidate {
                sym: self.symbol.clone(),
                vol_reduce_applies: false,
                notional_override: Some(units * close),
                stop_loss: stop_px,
                take_profit: target_px,
            }];
        }
        vec![]
    }
}

/// Run a compiled strategy over a frame — the §7.4 report is the engine's
/// own BacktestResult (trade list + metrics), produced by the SAME engine
/// the venue lanes use (the #345 lock: one engine truth; spec §7.2's
/// next-bar-open proposal is superseded by that lock — §10.5 resolved).
///
/// Fees: V1's fixed per-side model (FEE_PER_SIDE); costs per venue config
/// are a later slice. W2b: LONG entries only, single position.
pub fn run_strategy(
    request: &ScriptRequest,
    plan: &CompilePlan,
    frame: &Frame,
) -> Result<ot_core::engine::BacktestResult, String> {
    if plan.strategies.len() != 1 {
        return Err(format!(
            "expected exactly one strategy block, found {}",
            plan.strategies.len()
        ));
    }
    let (out, cols) = evaluate_full(request, plan, frame)?;
    let _ = &out;
    let mut bools = BTreeMap::new();
    let mut floats = BTreeMap::new();
    for (name, col) in cols {
        match col {
            Column::Bool(b) => {
                bools.insert(name, b);
            }
            Column::Float(f) => {
                floats.insert(name, f);
            }
        }
    }
    let strategy = &plan.strategies[0];
    let mut handler = StrategyHandler {
        symbol: request.symbol.clone(),
        ons: strategy.ons.clone(),
        cols: StrategyCols { bools, floats },
    };
    // Runner clock: the strategy's own lookbacks govern (columns are
    // precomputed from bar 0) — the engine's rule-floor start gate must not
    // delay or swallow strategy runs, and engine-level exits (tp/sl %,
    // max_hold, trailing) must not override the script's order semantics
    // (brackets ride the position; MaxHold is the script's).
    let mut cfg = ot_core::config::DEFAULT_CONFIG;
    cfg.mom_lb = 0;
    cfg.rev_lb = 0;
    cfg.rsi_period = 0;
    cfg.breakout_lb = 0;
    cfg.z_period = 0;
    cfg.max_positions = 1; // pyramiding off (spec §7.1 default)
    cfg.min_notional = 0.0; // units × price IS the sizing
    cfg.max_hold = i64::MAX / 2;
    cfg.tp = f64::MAX; // percentage ladder inactive for bracketed positions
    cfg.sl = f64::MAX;
    let universe = frame.bars_as_universe(&request.symbol);
    Ok(ot_core::engine::replay(&universe, &cfg, &mut handler))
}
