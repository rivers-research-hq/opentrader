//! AST — typed after parsing; spans kept for compile errors / hot-reload.

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Span {
    pub start: usize,
    pub end: usize,
}

#[derive(Debug, Clone, PartialEq)]
pub enum TokenKind {
    Ident(String),
    Number(f64),
    Str(String),
    // punctuation / operators
    Plus,
    Minus,
    Star,
    Slash,
    Lt,
    Gt,
    Le,
    Ge,
    Eq,    // =
    Ne,    // != (accepted; canonical form is `!=`, spec spells `=` for eq)
    EqEq,  // == accepted alias
    LBracket,
    RBracket,
    LParen,
    RParen,
    LBrace,
    RBrace,
    Comma,
    Semicolon,
    Arrow, // ->
    Colon,
    // keywords
    KwDeclare,
    KwInput,
    KwDef,
    KwSeries,
    KwPlot,
    KwThen,
    KwIf,
    KwElse,
    KwAnd,
    KwOr,
    KwXor,
    KwNot,
    KwTrue,
    KwFalse,
    KwFrom,
    KwBars,
    KwAgo,
    KwAbove,
    KwBelow,
    KwCrosses,
    KwDefault,
    // words in declare/effector contexts
    Lower,
    Upper,
    OnPrice,
    Eof,
}

#[derive(Debug, Clone)]
pub struct Token {
    pub kind: TokenKind,
    pub text: String,
    pub span: Span,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Type {
    Bool,
    Int,
    Float,
    Str,
}

#[derive(Debug, Clone, PartialEq)]
pub enum Expr {
    Num(f64),
    BoolLit(bool),
    StrLit(String),
    Ident(String, Span),
    /// History access: expr[n], n statically non-negative.
    Index(Box<Expr>, i64),
    Bin {
        op: BinOp,
        lhs: Box<Expr>,
        rhs: Box<Expr>,
    },
    Not(Box<Expr>),
    /// Lazy if-then-else (only the taken branch evaluates per bar).
    If {
        cond: Box<Expr>,
        then: Box<Expr>,
        els: Box<Expr>,
    },
    /// Built-in or study call. Args may be named (order-free, canonical)
    /// or positional (ThinkScript-compatible; resolved via the built-in's
    /// declared parameter order). All-positional or all-named per call.
    Call {
        name: String,
        args: Vec<(Option<String>, Expr)>,
        span: Span,
    },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BinOp {
    Add,
    Sub,
    Mul,
    Div,
    Eq,
    Ne,
    Lt,
    Gt,
    Le,
    Ge,
    And,
    Or,
    Xor,
}

#[derive(Debug, Clone)]
pub enum Stmt {
    /// declare lower | upper | on_price;
    DeclarePane(Pane),
    /// declare <key> = <value>;  (data, consumed by the host)
    DeclareProp { key: String, value: String },
    /// input name = default;  (typed by the literal)
    Input { name: String, default_expr: Expr },
    /// def name = expr;
    Def { name: String, expr: Expr, span: Span },
    /// series name = init_expr then step_expr;
    Series {
        name: String,
        init: Expr,
        step: Expr,
    },
    /// plot name = expr;  |  plot name;  (declared, assigned later)
    Plot { name: String, expr: Option<Expr> },
    /// plot-name assignment inside top-level if/else (exhaustiveness-checked)
    PlotAssign { name: String, expr: Expr },
    /// if cond { stmts } else { stmts } — statement form (plots only in W2a)
    IfAssign {
        cond: Expr,
        then: Vec<Stmt>,
        els: Vec<Stmt>,
    },
    /// strategy Name { ... } — the order-aware surface (spec §7)
    Strategy(StrategyBlock),
}

/// A compiled script: statements + the plan the host binds against.
#[derive(Debug, Clone, Default)]
pub struct Script {
    pub stmts: Vec<Stmt>,
}

/// Plot pane (declare lower | upper | on_price).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Pane {
    Lower,
    Upper,
    OnPrice,
}

// ── strategy surface (spec §7) ────────────────────────────────────────────

/// A `strategy Name { ... }` block — a study body plus `on` order
/// statements. VIRTUAL orders only (spec §7.3 boundary): the evaluator
/// returns a report; routing to a venue is a separate human-gated
/// promotion. The language has no live-order verb.
#[derive(Debug, Clone)]
pub struct StrategyBlock {
    pub name: String,
    pub items: Vec<StrategyItem>,
}

#[derive(Debug, Clone)]
pub enum StrategyItem {
    Input { name: String, default_expr: Expr },
    Def { name: String, expr: Expr },
    Series { name: String, init: Expr, step: Expr },
    /// `on <cond> -> Action;` — cond evaluated on closed bars (engine
    /// contract: the decision view is the signal bar t-1).
    On { cond: Expr, action: StrategyAction },
}

#[derive(Debug, Clone)]
pub enum StrategyAction {
    /// market entry, or a pending limit/stop entry (`limit =` / `trigger =`
    /// — `stop` stays the protective bracket name)
    Entry { args: Vec<(Option<String>, Expr)> },
    /// reduce/close by side or tag
    Exit,
    /// close everything (and cancel pendings)
    Flatten,
    /// update brackets on the held position (trailing stops ride this)
    Modify { args: Vec<(Option<String>, Expr)> },
}
