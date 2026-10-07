//! Static analysis — the compile plan (spec §1.3/§1.4, §6):
//!   * per-binding warm-up (max static [n] + callee lookbacks)
//!   * acyclic `def` graph (self-reference is a compile error; state
//!     requires `series`)
//!   * light type checks (bool-not-numeric, float-only NaN)
//!   * plot panes + inputs (the GUI/config schema, JSON-serializable)

use crate::ast::*;
use ot_core::engine::Side;
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

/// The order-aware strategy surface plan (spec §7).
#[derive(Debug, Clone)]
pub struct StrategyPlan {
    pub name: String,
    pub ons: Vec<OnPlan>,
}

#[derive(Debug, Clone)]
pub struct OnPlan {
    pub action: OnAction,
    pub cond: CondSpec,
}

#[derive(Debug, Clone)]
pub enum PendingSpec {
    /// resting limit order (buy fills when low ≤ price)
    Limit(String),
    /// resting stop-entry order (buy fills when high ≥ price)
    Trigger(String),
}

#[derive(Debug, Clone)]
pub enum OnAction {
    /// market entry (pending: None) or a pending limit/trigger entry;
    /// explicit `size` (units); optional absolute brackets ride the
    /// position (engine ladder).
    Entry {
        size: Option<String>,
        stop: Option<String>,
        target: Option<String>,
        pending: Option<PendingSpec>,
        side: Side,
    },
    Exit,
    Flatten,
    /// bracket updates (trailing stops ride this)
    Modify {
        stop: Option<String>,
        target: Option<String>,
    },
}

#[derive(Debug, Clone)]
pub enum CondSpec {
    /// hidden bool binding (column name in the plan's bindings)
    Column(String),
    /// position age ≥ n bars (engine state — the handler computes it)
    MaxHold(i64),
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
    /// strategy blocks (W2b: at most one per script)
    pub strategies: Vec<StrategyPlan>,
    /// hidden action-value exprs keyed by column name (the evaluator
    /// builds their arenas from these)
    pub hidden_exprs: BTreeMap<String, Expr>,
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
    /// hidden action-value exprs (size/stop/target/limit/trigger/modify)
    /// keyed by their column name — the evaluator re-derives them from
    /// source via this map carried on the plan
    pub hidden_exprs: BTreeMap<String, Expr>,
}

pub fn check(stmts: Vec<Stmt>) -> Result<CompilePlan, CheckError> {
    let mut ctx = Ctx {
        stmts: &stmts,
        bindings: BTreeMap::new(),
        plan: CompilePlan::default(),
        in_progress: BTreeSet::new(),
        hidden_exprs: BTreeMap::new(),
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
            Stmt::Strategy(sb) => {
                if !ctx.plan.strategies.is_empty() {
                    return cerr("at most one strategy block per script (W2b)");
                }
                let ns = format!("{}::", sb.name);
                for item in &sb.items {
                    match item {
                        StrategyItem::Input { name, default_expr } => {
                            if ctx.bindings.contains_key(name) {
                                return cerr(format!("duplicate binding `{name}` (strategy `{}`)", sb.name));
                            }
                            let (ty, default) = literal_type(default_expr)?;
                            ctx.bindings.insert(name.clone(), (BindingKind::Input, ty, 0));
                            ctx.plan.inputs.insert(name.clone(), InputSpec { ty, default });
                            ctx.plan.bindings.push(BindingPlan {
                                name: name.clone(),
                                kind: BindingKind::Input,
                                ty,
                                lookback: 0,
                                warmup: 0,
                                pane: None,
                            });
                        }
                        StrategyItem::Def { name, .. } => {
                            let qn = format!("{ns}{name}");
                            ctx.bindings.insert(qn.clone(), (BindingKind::Def, Type::Float, i64::MAX));
                            ctx.plan.bindings.push(BindingPlan {
                                name: qn,
                                kind: BindingKind::Def,
                                ty: Type::Float,
                                lookback: i64::MAX,
                                warmup: i64::MAX,
                                pane: None,
                            });
                        }
                        StrategyItem::Series { name, .. } => {
                            let qn = format!("{ns}{name}");
                            ctx.bindings.insert(qn.clone(), (BindingKind::Series, Type::Float, i64::MAX));
                            ctx.plan.bindings.push(BindingPlan {
                                name: qn,
                                kind: BindingKind::Series,
                                ty: Type::Float,
                                lookback: i64::MAX,
                                warmup: i64::MAX,
                                pane: None,
                            });
                        }
                        StrategyItem::On { .. } => {}
                    }
                }
                ctx.plan.strategies.push(StrategyPlan { name: sb.name.clone(), ons: Vec::new() });
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
            Stmt::Series { name, init, step } if !name.contains("::") => {
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

    // pass 2b: strategy bodies — defs/series (namespaced) + on-conditions
    for s in &stmts {
        let Stmt::Strategy(sb) = s else { continue };
        let ns = format!("{}::", sb.name);
        for item in &sb.items {
            match item {
                StrategyItem::Def { name, expr } => {
                    let qn = format!("{ns}{name}");
                    let rexpr = rewrite(expr, &ns, &sb.name)?;
                    let ty = type_of(&mut ctx, &rexpr)?;
                    if ty != Type::Float && ty != Type::Bool {
                        return cerr(format!("strategy def `{name}` must be float or bool (got {ty:?})"));
                    }
                    let lb = lookback_of(&mut ctx, &rexpr)?;
                    if let Some(e) = ctx.bindings.get_mut(&qn) {
                        e.1 = ty;
                        e.2 = lb;
                    }
                }
                StrategyItem::Series { name, init, step } => {
                    let qn = format!("{ns}{name}");
                    let rinit = rewrite(init, &ns, &sb.name)?;
                    let rstep = rewrite(step, &ns, &sb.name)?;
                    let _ = type_of(&mut ctx, &rinit)?;
                    let ty_step = type_of(&mut ctx, &rstep)?;
                    if ty_step != Type::Float && ty_step != Type::Bool {
                        return cerr(format!("strategy series `{name}` must be float or bool (got {ty_step:?})"));
                    }
                    let lb = lookback_of(&mut ctx, &rinit)?.max(lookback_of(&mut ctx, &rstep)?);
                    if let Some(e) = ctx.bindings.get_mut(&qn) {
                        e.2 = lb;
                    }
                }
                StrategyItem::Input { .. } => {}
                StrategyItem::On { cond, action } => {
                    // compound MaxHold rejected FIRST (any position in the tree)
                    if expr_contains(cond, "MaxHold") {
                        if !matches!(cond, Expr::Call { name, .. } if name == "MaxHold") {
                            return cerr("MaxHold is only supported as a bare `on MaxHold(n)` condition (compound forms are a later W2 slice)");
                        }
                    }
                    // MaxHold marker: bare MaxHold(n) condition
                    if let Expr::Call { name: cn, args, .. } = cond {
                        if cn == "MaxHold" {
                            let n = match args.first() {
                                Some((_, Expr::Num(v))) => *v as i64,
                                _ => return cerr("MaxHold(n) requires a constant n"),
                            };
                            let act = check_action(action, &ns, &mut ctx)?;
                            ctx.plan.strategies.last_mut().unwrap().ons.push(OnPlan {
                                action: act,
                                cond: CondSpec::MaxHold(n),
                            });
                            continue;
                        }
                    }
                    let rcond = rewrite(cond, &ns, &sb.name)?;
                    let ty = type_of(&mut ctx, &rcond)?;
                    if ty != Type::Bool {
                        return cerr(format!("`on` condition must be bool (got {ty:?})"));
                    }
                    let idx = ctx.plan.strategies.last().unwrap().ons.len();
                    let qn = format!("{ns}on{idx}");
                    ctx.bindings.insert(qn.clone(), (BindingKind::Def, Type::Bool, 0));
                    ctx.plan.bindings.push(BindingPlan {
                        name: qn.clone(),
                        kind: BindingKind::Def,
                        ty: Type::Bool,
                        lookback: 0,
                        warmup: 0,
                        pane: None,
                    });
                    let lb = lookback_of(&mut ctx, &rcond)?;
                    if let Some(e) = ctx.bindings.get_mut(&qn) {
                        e.2 = lb;
                    }
                    let act = check_action(action, &ns, &mut ctx)?;
                    ctx.plan.strategies.last_mut().unwrap().ons.push(OnPlan {
                        action: act,
                        cond: CondSpec::Column(qn),
                    });
                }
            }
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
                // honesty (spec §1.4): a `series` binding makes output depend
                // on loaded-history length — flagged in the plan, never silent
                if kind == BindingKind::Series {
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
            Stmt::Strategy(sb) => {
                let ns = format!("{}::", sb.name);
                // strategy bindings in declaration order, then the on-cols
                let mut k = 0usize;
                for item in &sb.items {
                    match item {
                        StrategyItem::Def { name, .. } | StrategyItem::Series { name, .. } => {
                            eval_order.push(format!("{ns}{name}"));
                        }
                        StrategyItem::On { .. } => {
                            let plan = ctx.plan.strategies.first().unwrap();
                            if let Some(OnPlan { cond: CondSpec::Column(qn), .. }) =
                                plan.ons.get(k)
                            {
                                eval_order.push(qn.clone());
                            }
                            k += 1;
                        }
                        _ => {}
                    }
                }
                // hidden action-value bindings (size/stop/target/limit/
                // trigger/modify) registered by check_action under this ns
                // as `ns v<N>` — local suffix v<digits>
                for (n, (kind, _, _)) in ctx.bindings.iter() {
                    if n.starts_with(&ns) && *kind == BindingKind::Def {
                        let local = &n[ns.len()..];
                        if local.starts_with('v')
                            && local.len() > 1
                            && local[1..].chars().all(|ch| ch.is_ascii_digit())
                        {
                            eval_order.push(n.clone());
                        }
                    }
                }
            }
            _ => {}
        }
    }
    ctx.plan.eval_order = eval_order;
    ctx.plan.hidden_exprs = ctx.hidden_exprs.clone();
    Ok(ctx.plan)
}

/// Strategy on-action validation: returns the plan action; value exprs
/// (size/stop/target) become hidden bindings `ns::eK_size` etc.
fn check_action(
    action: &StrategyAction,
    ns: &str,
    ctx: &mut Ctx,
) -> Result<OnAction, CheckError> {
    Ok(match action {
        StrategyAction::Exit => OnAction::Exit,
        StrategyAction::Flatten => OnAction::Flatten,
        StrategyAction::Entry { args } => {
            // resolve positional via Entry's declared order, then named
            let order = ["side", "size", "stop", "target", "limit", "trigger"];
            let mut named: Vec<(String, &Expr)> = Vec::new();
            let seen_named = args.iter().any(|(n, _)| n.is_some());
            let seen_positional = args.iter().any(|(n, _)| n.is_none());
            if seen_named && seen_positional {
                return cerr("Entry: mixing positional and named args is a type error");
            }
            if seen_positional {
                for ((_, e), pname) in args.iter().zip(order) {
                    named.push((pname.to_string(), e));
                }
            } else {
                for (n, e) in args {
                    let Some(n) = n else { unreachable!() };
                    if !order.contains(&n.as_str()) {
                        return cerr(format!("Entry: unknown parameter `{n}` (expected one of {order:?})"));
                    }
                    named.push((n.clone(), e));
                }
            }
            let mut size = None;
            let mut stop = None;
            let mut target = None;
            let mut pending = None;
            let mut side = Side::Long;
            let mut side_seen = false;
            for (k, e) in named {
                match k.as_str() {
                    "side" => {
                        match e {
                            Expr::Ident(s, _) if s == "LONG" => {
                                side = Side::Long;
                                side_seen = true;
                            }
                            Expr::Ident(s, _) if s == "SHORT" => {
                                side = Side::Short;
                                side_seen = true;
                            }
                            _ => return cerr("Entry(side = LONG | SHORT)"),
                        }
                    }
                    "limit" => {
                        let qn = hidden_value_binding(ctx, ns, "limit", e, "pending limit price must be float")?;
                        pending = Some(PendingSpec::Limit(qn));
                    }
                    "trigger" => {
                        let qn = hidden_value_binding(ctx, ns, "trigger", e, "pending trigger price must be float")?;
                        pending = Some(PendingSpec::Trigger(qn));
                    }
                    "size" => {
                        let qn = hidden_value_binding(ctx, ns, "size", e, "Entry(size = <units>) must be numeric")?;
                        size = Some((qn, e.clone()));
                    }
                    "stop" => {
                        let qn = hidden_value_binding(ctx, ns, "stop", e, "Entry(stop = <price>) must be float")?;
                        stop = Some((qn, e.clone()));
                    }
                    "target" => {
                        let qn = hidden_value_binding(ctx, ns, "target", e, "Entry(target = <price>) must be float")?;
                        target = Some((qn, e.clone()));
                    }
                    _ => unreachable!(),
                }
            }
            if !side_seen {
                return cerr("Entry requires `side = LONG | SHORT`");
            }
            // hidden value bindings need their exprs checked/lookbacked —
            // register their stmts so pass-2-style resolution works: we
            // already type-checked; record lookback via lookback_of
            for (qn, e) in [&size, &stop, &target].into_iter().flatten() {
                let lb = lookback_of(ctx, e)?;
                if let Some(entry) = ctx.bindings.get_mut(qn) {
                    entry.2 = lb;
                }
            }
            OnAction::Entry {
                size: size.map(|(q, _)| q),
                stop: stop.map(|(q, _)| q),
                target: target.map(|(q, _)| q),
                pending,
                side,
            }
        }
        StrategyAction::Modify { args } => {
            let order = ["stop", "target"];
            let mut named: Vec<(String, &Expr)> = Vec::new();
            if args.iter().any(|(n, _)| n.is_some()) {
                for (n, a) in args {
                    if let Some(n) = n {
                        if !order.contains(&n.as_str()) {
                            return cerr(format!("Modify: unknown parameter `{n}` (expected one of {order:?})"));
                        }
                        named.push((n.clone(), a));
                    }
                }
            } else {
                for ((_, a), pname) in args.iter().zip(order) {
                    named.push((pname.to_string(), a));
                }
            }
            let mut mstop = None;
            let mut mtarget = None;
            for (k, e) in named {
                let qn = hidden_value_binding(
                    ctx,
                    ns,
                    &format!("mod_{k}"),
                    e,
                    "Modify values must be float",
                )?;
                match k.as_str() {
                    "stop" => mstop = Some(qn),
                    "target" => mtarget = Some(qn),
                    _ => unreachable!(),
                }
            }
            if mstop.is_none() && mtarget.is_none() {
                return cerr("Modify requires `stop =` and/or `target =`");
            }
            OnAction::Modify { stop: mstop, target: mtarget }
        }
    })
}

/// Hidden value binding for strategy action args (size/stop/target/…):
/// type-checked float, column evaluated by the runner.
fn hidden_value_binding(
    ctx: &mut Ctx,
    ns: &str,
    _label: &str,
    e: &Expr,
    err: &str,
) -> Result<String, CheckError> {
    let qn = format!("{ns}v{}", ctx.plan.bindings.len());
    let ty = type_of(ctx, e)?;
    if ty != Type::Float {
        return cerr(err.to_string());
    }
    ctx.bindings.insert(qn.clone(), (BindingKind::Def, Type::Float, 0));
    ctx.plan.bindings.push(BindingPlan {
        name: qn.clone(),
        kind: BindingKind::Def,
        ty: Type::Float,
        lookback: 0,
        warmup: 0,
        pane: None,
    });
    ctx.hidden_exprs.insert(qn.clone(), e.clone());
    Ok(qn)
}

/// Rewrite idents inside a strategy body to their namespaced bindings.
/// Fundamentals, builtins, and unknown names pass through (unknown names
/// error later — including intentional top-level refs, which resolve to
/// top-level columns at eval).
fn rewrite(e: &Expr, ns: &str, strat: &str) -> Result<Expr, CheckError> {
    let owned_names = |name: &str| -> bool { name.starts_with(ns) };
    let _ = owned_names;
    let _ = strat;
    match e {
        Expr::Ident(name, sp) => {
            // rewrite only if NOT a fundamental (fundamentals stay bare)
            if crate::builtins::is_fundamental(name) {
                Ok(e.clone())
            } else {
                Ok(Expr::Ident(format!("{ns}{name}"), *sp))
            }
        }
        Expr::Index(inner, n) => Ok(Expr::Index(
            Box::new(rewrite(inner, ns, strat)?),
            *n,
        )),
        Expr::Bin { op, lhs, rhs } => Ok(Expr::Bin {
            op: *op,
            lhs: Box::new(rewrite(lhs, ns, strat)?),
            rhs: Box::new(rewrite(rhs, ns, strat)?),
        }),
        Expr::Not(inner) => Ok(Expr::Not(Box::new(rewrite(inner, ns, strat)?))),
        Expr::If { cond, then, els } => Ok(Expr::If {
            cond: Box::new(rewrite(cond, ns, strat)?),
            then: Box::new(rewrite(then, ns, strat)?),
            els: Box::new(rewrite(els, ns, strat)?),
        }),
        Expr::Call { name, args, span } => {
            if crate::builtins::is_known_builtin(name) || name == "MaxHold" {
                let mut out = Vec::new();
                for (n, a) in args {
                    out.push((n.clone(), rewrite(a, ns, strat)?));
                }
                return Ok(Expr::Call { name: name.clone(), args: out, span: *span });
            }
            // user study calls land in a later slice — treat unknown call
            // names as errors pointing there
            Err(CheckError {
                message: format!("`{name}(...)` — user-study calls are a later W2 slice"),
            })
        }
        Expr::Num(_) | Expr::BoolLit(_) | Expr::StrLit(_) => Ok(e.clone()),
    }
}

/// Does the expression contain a call to the named builtin anywhere?
fn expr_contains(e: &Expr, name: &str) -> bool {
    match e {
        Expr::Call { name: n, args, .. } => {
            n == name || args.iter().any(|(_, a)| expr_contains(a, name))
        }
        Expr::Bin { lhs, rhs, .. } => expr_contains(lhs, name) || expr_contains(rhs, name),
        Expr::Not(inner) => expr_contains(inner, name),
        Expr::If { cond, then, els } => {
            expr_contains(cond, name) || expr_contains(then, name) || expr_contains(els, name)
        }
        Expr::Index(inner, _) => expr_contains(inner, name),
        _ => false,
    }
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

/// Crate-internal rewrite entry for the evaluator's strategy walk.
pub(crate) fn rewrite_pub(e: &Expr, ns: &str, strat: &str) -> Result<Expr, CheckError> {
    rewrite(e, ns, strat)
}
