//! Static analysis — the compile plan (spec §1.3/§1.4, §6):
//!   * per-binding warm-up (max static [n] + callee lookbacks)
//!   * acyclic `def` graph (self-reference is a compile error; state
//!     requires `series`)
//!   * light type checks (bool-not-numeric, float-only NaN)
//!   * plot panes + inputs (the GUI/config schema, JSON-serializable)

use crate::ast::*;
use std::collections::{BTreeMap, BTreeSet};

pub use crate::ast::Pane;

#[derive(Debug, Clone)]
pub struct CheckError {
    pub message: String,
}

impl std::fmt::Display for CheckError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "compile error: {}", self.message)
    }
}

fn cerr<T>(message: impl Into<String>) -> Result<T, CheckError> {
    Err(CheckError { message: message.into() })
}

/// One binding's static facts (the compile plan the host binds against).
#[derive(Debug, Clone)]
pub struct BindingPlan {
    pub name: String,
    pub kind: BindingKind,
    pub ty: Type,
    /// Static lookback: max `[n]` in the expression tree + callee lookback.
    pub lookback: i64,
    /// Bars before this binding's first defined value (warm-up holes are
    /// NaN for floats; bool/int bindings must be total — checker-enforced).
    pub warmup: i64,
    pub pane: Option<Pane>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BindingKind {
    Def,
    Series,
    Plot,
    Input,
    /// a fundamentals-family bar column (close, volume, …) — host-supplied
    Field,
}

#[derive(Debug, Clone, Default)]
pub struct CompilePlan {
    pub bindings: Vec<BindingPlan>,
    pub inputs: BTreeMap<String, InputSpec>,
    pub pane: Option<Pane>,
    /// True when any binding's warm-up is unbounded (whole-history state —
    /// spec §1.4: consumers may refuse; no output presented as complete
    /// without `warmup_complete`).
    pub warmup_unbounded: bool,
    /// Binding evaluation order (series in declaration order first at each
    /// bar; defs after their dependencies — the evaluator uses this order).
    pub eval_order: Vec<String>,
}

#[derive(Debug, Clone)]
pub struct InputSpec {
    pub ty: Type,
    pub default: serde_json::Value,
}

pub struct Ctx<'a> {
    pub stmts: &'a [Stmt],
    /// name → (kind, ty, static lookback)
    pub bindings: BTreeMap<String, (BindingKind, Type, i64)>,
    pub plan: CompilePlan,
    pub in_progress: BTreeSet<String>,
}

pub fn check(stmts: Vec<Stmt>) -> Result<CompilePlan, CheckError> {
    let mut ctx = Ctx {
        stmts: &stmts,
        bindings: BTreeMap::new(),
        plan: CompilePlan::default(),
        in_progress: BTreeSet::new(),
    };
    // the fundamentals family (spec §4.1) — host-supplied bar columns;
    // float, lookback 0 (per-bar reads), never shadowable by `def`.
    for name in ["open", "high", "low", "close", "volume", "hl2", "hlc3", "ohlc4", "NaN", "Infinity"] {
        ctx.bindings
            .insert(name.to_string(), (BindingKind::Field, Type::Float, 0));
    }

    // pass 1: register bindings in declaration order
    for s in &stmts {
        match s {
            Stmt::DeclarePane(p) => {
                if ctx.plan.pane.is_some() {
                    return cerr("multiple declare-pane statements");
                }
                ctx.plan.pane = Some(*p);
            }
            Stmt::DeclareProp { key, .. } => {
                // data-only declarative properties (host-consumed); W2a
                // accepts pyramiding-style keys verbatim.
                let _ = key;
            }
            Stmt::Input { name, default_expr } => {
                if ctx.bindings.contains_key(name) {
                    return cerr(format!("duplicate binding `{name}`"));
                }
                let (ty, default) = literal_type(default_expr)?;
                ctx.bindings.insert(name.clone(), (BindingKind::Input, ty, 0));
                ctx.plan.inputs.insert(
                    name.clone(),
                    InputSpec { ty, default },
                );
                ctx.plan.bindings.push(BindingPlan {
                    name: name.clone(),
                    kind: BindingKind::Input,
                    ty,
                    lookback: 0,
                    warmup: 0,
                    pane: None,
                });
            }
            Stmt::Def { name, .. } => {
                if ctx.bindings.contains_key(name) {
                    return cerr(format!("duplicate binding `{name}`"));
                }
                ctx.bindings.insert(name.clone(), (BindingKind::Def, Type::Float, i64::MAX));
            }
            Stmt::Series { name, .. } => {
                if ctx.bindings.contains_key(name) {
                    return cerr(format!("duplicate binding `{name}`"));
                }
                ctx.bindings.insert(name.clone(), (BindingKind::Series, Type::Float, i64::MAX));
            }
            Stmt::Plot { name, .. } => {
                if ctx.bindings.contains_key(name) {
                    return cerr(format!("duplicate binding `{name}`"));
                }
                ctx.bindings.insert(name.clone(), (BindingKind::Plot, Type::Float, i64::MAX));
            }
            Stmt::PlotAssign { .. } | Stmt::IfAssign { .. } => {
                return cerr("plot assignment must appear at top level in W2a (declared-then-assigned plots land with the full statement-if form)".to_string());
            }
        }
    }

    // pass 2: check each binding's expression; fills lookback + type
    for s in &stmts {
        match s {
            Stmt::Def { name, expr, .. } => {
                if ctx.in_progress.contains(name) {
                    return cerr(format!(
                        "`def {name}` references itself (directly or via a cycle) — self-reference requires `series` with an explicit initializer"
                    ));
                }
                ctx.in_progress.insert(name.clone());
                let ty = type_of(&mut ctx, expr)?;
                let lookback = lookback_of(&mut ctx, expr)?;
                let (kind, _t, _) = ctx.bindings[name];
                ctx.bindings.insert(name.clone(), (kind, ty, lookback));
                ctx.in_progress.remove(name);
                if ty != Type::Float && ty != Type::Bool {
                    return cerr(format!("`def {name}` must be float or bool (got {ty:?})"));
                }
            }
            Stmt::Series { name, init, step } => {
                let _ = type_of(&mut ctx, init)?;
                let ty_step = type_of(&mut ctx, step)?;
                if ty_step != Type::Float && ty_step != Type::Bool {
                    return cerr(format!("`series {name}` must be float or bool (got {ty_step:?})"));
                }
                // series reads its own past via [n] — allowed; the init
                // defines bar 0 so the binding is total from bar 0.
                let init_lb = lookback_of(&mut ctx, init)?;
                let _ = init_lb; // init's lookback beyond bar 0 → NaN init? init must be total
                let step_lb = lookback_of(&mut ctx, step)?;
                let lb = init_lb.max(step_lb);
                ctx.bindings.insert(name.clone(), (BindingKind::Series, Type::Float, lb));
            }
            _ => {}
        }
    }

    // pass 3: plots (bound expr or declared-then-assigned; W2a supports
    // `plot x = expr` and single-level if/else assignment via the
    // IfAssign statement — restricted above to keep the checker total)
    for s in &stmts {
        if let Stmt::Plot { name, expr } = s {
            let lb = match expr {
                Some(e) => {
                    let ty = type_of(&mut ctx, e)?;
                    if ty != Type::Float {
                        return cerr(format!("`plot {name}` must be float (NaN = don't paint)"));
                    }
                    lookback_of(&mut ctx, e)?
                }
                None => {
                    return cerr(format!(
                        "plot `{name}` is declared but never assigned (W2a requires `plot {name} = expr;`)"
                    ));
                }
            };
            let (_, t, _) = ctx.bindings[name];
            ctx.bindings.insert(name.clone(), (BindingKind::Plot, t, lb));
        }
    }

    // build the plan: warm-up per binding, eval order
    let mut eval_order: Vec<String> = Vec::new();
    for s in &stmts {
        match s {
            Stmt::Def { name, .. } | Stmt::Series { name, .. } | Stmt::Plot { name, .. } => {
                let (kind, ty, lb) = ctx.bindings[name];
                let warmup = match kind {
                    BindingKind::Series => 0, // inits at bar 0 by construction
                    _ => {
                        // warm-up = static lookback ⊔ declared prefetch of
                        // every stateful built-in in the tree (spec §1.4)
                        let bw = match s {
                            Stmt::Def { expr, .. } | Stmt::Plot { expr: Some(expr), .. } => {
                                let input_default = |n: &str| -> Option<f64> {
                                    ctx.plan.inputs.get(n).and_then(|s| s.default.as_f64())
                                };
                                builtin_warmup(expr, &input_default)
                            }
                            _ => 0,
                        };
                        lb.max(bw)
                    }
                };
                if warmup < 0 {
                    ctx.plan.warmup_unbounded = true;
                }
                ctx.plan.bindings.push(BindingPlan {
                    name: name.clone(),
                    kind,
                    ty,
                    lookback: lb,
                    warmup,
                    pane: if matches!(kind, BindingKind::Plot) { ctx.plan.pane } else { None },
                });
                eval_order.push(name.clone());
            }
            _ => {}
        }
    }
    ctx.plan.eval_order = eval_order;
    Ok(ctx.plan)
}

/// Static lookback of an expression: max `[n]` plus callee-declared
/// lookbacks. Returns i64::MIN for unbounded (whole-history builtins).
fn lookback_of(ctx: &mut Ctx, e: &Expr) -> Result<i64, CheckError> {
    let lb = lookback_inner(ctx, e, &mut BTreeSet::new())?;
    Ok(lb)
}

fn lookback_inner(
    ctx: &mut Ctx,
    e: &Expr,
    visiting: &mut BTreeSet<String>,
) -> Result<i64, CheckError> {
    Ok(match e {
        Expr::Num(_) | Expr::BoolLit(_) | Expr::StrLit(_) => 0,
        Expr::Ident(name, _) => {
            match ctx.bindings.get(name) {
                Some((BindingKind::Input, _, _)) => 0,
                Some((kind, _, lb)) => {
                    if *lb == i64::MAX {
                        // self-reference: a `series` reading its own [n] is
                        // the feature (spec §1.1) — the Ident base
                        // contributes 0, the Index adds n. Defs still
                        // cycle-error.
                        if visiting.contains(name) {
                            if *kind == BindingKind::Series {
                                return Ok(0);
                            }
                            return cerr(format!("cyclic binding `{name}` — self-reference requires `series` with an explicit initializer"));
                        }
                        if !visiting.insert(name.clone()) {
                            return cerr(format!("cyclic binding `{name}` — self-reference requires `series` with an explicit initializer"));
                        }
                        let resolved = resolve_binding_lookback(ctx, name, visiting)?;
                        visiting.remove(name);
                        resolved
                    } else {
                        *lb
                    }
                }
                None => return cerr(format!("unknown identifier `{name}`")),
            }
        }
        Expr::Index(inner, n) => {
            let inner_lb = lookback_inner(ctx, inner, visiting)?;
            inner_lb + n
        }
        Expr::Bin { op: _, lhs, rhs } => {
            lookback_inner(ctx, lhs, visiting)?.max(lookback_inner(ctx, rhs, visiting)?)
        }
        Expr::Not(inner) => lookback_inner(ctx, inner, visiting)?,
        Expr::If { cond, then, els } => lookback_inner(ctx, cond, visiting)?
            .max(lookback_inner(ctx, then, visiting)?)
            .max(lookback_inner(ctx, els, visiting)?),
        Expr::Call { name, args, .. } => {
            let resolved = crate::builtins::resolve_args(name, args)?;
            let input_default = |n: &str| -> Option<f64> {
                ctx.plan.inputs.get(n).and_then(|s| s.default.as_f64())
            };
            let mut max_lb =
                crate::builtins::declared_lookback(name, &resolved, &input_default)? as i64;
            for (_, a) in &resolved {
                max_lb = max_lb.max(lookback_inner(ctx, a, visiting)?);
            }
            max_lb
        }
    })
}

fn resolve_binding_lookback(
    ctx: &mut Ctx,
    name: &str,
    visiting: &mut BTreeSet<String>,
) -> Result<i64, CheckError> {
    for s in ctx.stmts {
        match s {
            Stmt::Def { name: n, expr, .. } if n == name => {
                if !visiting.insert(n.clone()) {
                    return cerr(format!("cyclic binding `{n}` — self-reference requires `series` with an explicit initializer"));
                }
                let lb = lookback_inner(ctx, expr, visiting)?;
                visiting.remove(n);
                if let Some(entry) = ctx.bindings.get_mut(n) {
                    entry.2 = lb;
                }
                return Ok(lb);
            }
            Stmt::Series { name: n, init, step } if n == name => {
                let lb = lookback_inner(ctx, init, visiting)?
                    .max(lookback_inner(ctx, step, visiting)?);
                if let Some(entry) = ctx.bindings.get_mut(n) {
                    entry.2 = lb;
                }
                return Ok(lb);
            }
            Stmt::Plot { name: n, expr: Some(expr) } if n == name => {
                let lb = lookback_inner(ctx, expr, visiting)?;
                if let Some(entry) = ctx.bindings.get_mut(n) {
                    entry.2 = lb;
                }
                return Ok(lb);
            }
            _ => {}
        }
    }
    cerr(format!("binding `{name}` has no statement"))
}

fn literal_type(e: &Expr) -> Result<(Type, serde_json::Value), CheckError> {
    Ok(match e {
        Expr::Num(v) => {
            if v.fract() == 0.0 && v.abs() < 9e15 {
                (Type::Int, serde_json::json!(*v as i64))
            } else {
                (Type::Float, serde_json::json!(v))
            }
        }
        Expr::BoolLit(b) => (Type::Bool, serde_json::json!(b)),
        Expr::StrLit(s) => (Type::Str, serde_json::json!(s)),
        _ => {
            return cerr("input defaults must be literals in W2a");
        }
    })
}

/// Light type checker: bool-is-not-numeric enforced; NaN is float-only.
fn type_of(ctx: &mut Ctx, e: &Expr) -> Result<Type, CheckError> {
    let ty = type_inner(ctx, e, &mut BTreeSet::new())?;
    Ok(ty)
}

fn type_inner(ctx: &mut Ctx, e: &Expr, visiting: &mut BTreeSet<String>) -> Result<Type, CheckError> {
    Ok(match e {
        Expr::Num(_) => Type::Float,
        Expr::BoolLit(_) => Type::Bool,
        Expr::StrLit(_) => Type::Str,
        Expr::Ident(name, _) => {
            match ctx.bindings.get(name) {
                Some((kind, ty, lb)) => {
                    if *lb == i64::MAX && *kind != BindingKind::Input {
                        if visiting.contains(name) {
                            if *kind == BindingKind::Series {
                                return Ok(*ty);
                            }
                            return cerr(format!("cyclic binding `{name}` — self-reference requires `series` with an explicit initializer"));
                        }
                        if !visiting.insert(name.clone()) {
                            return cerr(format!("cyclic binding `{name}` — self-reference requires `series` with an explicit initializer"));
                        }
                        let t = resolve_binding_type(ctx, name, visiting)?;
                        visiting.remove(name);
                        t
                    } else {
                        *ty
                    }
                }
                None => {
                    // fundamentals are identifiers resolved as builtins
                    if crate::builtins::is_fundamental(name) {
                        Type::Float
                    } else {
                        return cerr(format!("unknown identifier `{name}`"));
                    }
                }
            }
        }
        Expr::Index(inner, _) => type_inner(ctx, inner, visiting)?,
        Expr::Bin { op, lhs, rhs } => {
            let lt = type_inner(ctx, lhs, visiting)?;
            let rt = type_inner(ctx, rhs, visiting)?;
            match op {
                BinOp::And | BinOp::Or | BinOp::Xor => {
                    if lt != Type::Bool || rt != Type::Bool {
                        return cerr(format!("`and/or/xor` need bool operands (got {lt:?}, {rt:?}) — bool is not numeric"));
                    }
                    Type::Bool
                }
                BinOp::Eq | BinOp::Ne | BinOp::Lt | BinOp::Gt | BinOp::Le | BinOp::Ge => {
                    if (lt == Type::Bool) != (rt == Type::Bool) {
                        return cerr("cannot compare bool with numeric — bool is not numeric");
                    }
                    Type::Bool
                }
                BinOp::Add | BinOp::Sub | BinOp::Mul | BinOp::Div => {
                    if lt == Type::Bool || rt == Type::Bool {
                        return cerr("arithmetic on bool — bool is not numeric (use `if cond then 1 else 0`)");
                    }
                    if lt == Type::Str || rt == Type::Str {
                        return cerr("string arithmetic is a type error (Concat for strings)");
                    }
                    Type::Float
                }
            }
        }
        Expr::Not(inner) => {
            if type_inner(ctx, inner, visiting)? != Type::Bool {
                return cerr("`not` needs a bool operand");
            }
            Type::Bool
        }
        Expr::If { cond, then, els } => {
            if type_inner(ctx, cond, visiting)? != Type::Bool {
                return cerr("if condition must be bool");
            }
            let tt = type_inner(ctx, then, visiting)?;
            let et = type_inner(ctx, els, visiting)?;
            if tt != et {
                return cerr(format!("if branches must share a type (then {tt:?}, else {et:?})"));
            }
            tt
        }
        Expr::Call { name, args, .. } => crate::builtins::check_call(ctx, name, args, visiting)?,
    })
}

fn resolve_binding_type(
    ctx: &mut Ctx,
    name: &str,
    visiting: &mut BTreeSet<String>,
) -> Result<Type, CheckError> {
    for s in ctx.stmts {
        match s {
            Stmt::Def { name: n, expr, .. } if n == name => {
                if !visiting.insert(n.clone()) {
                    return cerr(format!("cyclic binding `{n}` — self-reference requires `series` with an explicit initializer"));
                }
                let t = type_inner(ctx, expr, visiting)?;
                visiting.remove(n);
                if let Some(entry) = ctx.bindings.get_mut(n) {
                    entry.1 = t;
                }
                return Ok(t);
            }
            Stmt::Series { name: n, .. } if n == name => return Ok(Type::Float),
            Stmt::Plot { name: n, expr: Some(expr) } if n == name => {
                let t = type_inner(ctx, expr, visiting)?;
                if let Some(entry) = ctx.bindings.get_mut(n) {
                    entry.1 = t;
                }
                return Ok(t);
            }
            _ => {}
        }
    }
    cerr(format!("binding `{name}` has no statement"))
}

/// Entry point for built-in argument type checks (crate-internal).
pub(crate) fn type_of_pub(
    ctx: &mut Ctx,
    e: &Expr,
    visiting: &mut BTreeSet<String>,
) -> Result<Type, CheckError> {
    type_inner(ctx, e, visiting)
}

/// Max declared warm-up over the built-in calls in an expression tree.
fn builtin_warmup(e: &Expr, input_default: &dyn Fn(&str) -> Option<f64>) -> i64 {
    match e {
        Expr::Num(_) | Expr::BoolLit(_) | Expr::StrLit(_) | Expr::Ident(..) => 0,
        Expr::Index(inner, _) => builtin_warmup(inner, input_default),
        Expr::Bin { lhs, rhs, .. } => {
            builtin_warmup(lhs, input_default).max(builtin_warmup(rhs, input_default))
        }
        Expr::Not(inner) => builtin_warmup(inner, input_default),
        Expr::If { cond, then, els } => builtin_warmup(cond, input_default)
            .max(builtin_warmup(then, input_default))
            .max(builtin_warmup(els, input_default)),
        Expr::Call { name, args, .. } => {
            match crate::builtins::resolve_args(name, args) {
                Ok(resolved) => {
                    let own = crate::builtins::declared_warmup(name, &resolved, input_default);
                    resolved
                        .iter()
                        .map(|(_, a)| builtin_warmup(a, input_default))
                        .fold(own, i64::max)
                }
                Err(_) => 0,
            }
        }
    }
}
