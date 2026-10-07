//! Recursive-descent parser for the core grammar (spec §3).
//! Word-operator desugaring happens here:
//!   `a crosses above b` → `CrossesAbove(a, b)`
//!   `close from 2 bars ago` → `close[2]`

use crate::ast::*;
use crate::ast::TokenKind as K;
use TokenKind as T;

pub fn parse(tokens: &[Token]) -> Result<Vec<Stmt>, String> {
    let mut p = P { toks: tokens, pos: 0 };
    let mut stmts = Vec::new();
    while !p.at(K::Eof) {
        stmts.push(p.statement()?);
    }
    Ok(stmts)
}

struct P<'a> {
    toks: &'a [Token],
    pos: usize,
}

impl<'a> P<'a> {
    fn kind(&self) -> &K {
        &self.toks[self.pos].kind
    }
    fn at(&self, k: K) -> bool {
        *self.kind() == k
    }
    fn eat(&mut self, k: K) -> bool {
        if self.at(k) {
            self.pos += 1;
            true
        } else {
            false
        }
    }
    fn expect(&mut self, k: K, what: &str) -> Result<(), String> {
        if self.eat(k) {
            Ok(())
        } else {
            Err(format!(
                "parse error: expected {what}, found {:?} at byte {}",
                self.toks[self.pos].kind, self.toks[self.pos].span.start
            ))
        }
    }
    fn ident(&mut self) -> Result<String, String> {
        if let K::Ident(s) = self.kind().clone() {
            self.pos += 1;
            Ok(s)
        } else {
            Err(format!(
                "parse error: expected identifier, found {:?} at byte {}",
                self.toks[self.pos].kind, self.toks[self.pos].span.start
            ))
        }
    }

    fn statement(&mut self) -> Result<Stmt, String> {
        match self.kind().clone() {
            K::KwDeclare => self.declare_stmt(),
            K::KwInput => self.input_stmt(),
            K::KwDef => self.def_stmt(),
            K::KwSeries => self.series_stmt(),
            K::KwPlot => self.plot_stmt(),
            K::KwIf => self.if_assign_stmt(),
            other => Err(format!(
                "parse error: unexpected {:?} at byte {} — expected declare/input/def/series/plot/if",
                other, self.toks[self.pos].span.start
            )),
        }
    }

    fn declare_stmt(&mut self) -> Result<Stmt, String> {
        self.pos += 1; // declare
        if self.eat(K::Lower) {
            self.expect(K::Semicolon, "';'")?;
            return Ok(Stmt::DeclarePane(Pane::Lower));
        }
        if self.eat(K::Upper) {
            self.expect(K::Semicolon, "';'")?;
            return Ok(Stmt::DeclarePane(Pane::Upper));
        }
        if self.eat(K::OnPrice) {
            self.expect(K::Semicolon, "';'")?;
            return Ok(Stmt::DeclarePane(Pane::OnPrice));
        }
        // declare <key> = <text> ;
        let key = self.ident()?;
        self.expect(K::Eq, "'='")?;
        let mut value = String::new();
        while !self.at(K::Semicolon) && !self.at(K::Eof) {
            value.push_str(&self.toks[self.pos].text);
            value.push(' ');
            self.pos += 1;
        }
        self.expect(K::Semicolon, "';'")?;
        Ok(Stmt::DeclareProp { key, value: value.trim().to_string() })
    }

    fn input_stmt(&mut self) -> Result<Stmt, String> {
        self.pos += 1; // input
        let name = self.ident()?;
        self.expect(K::Eq, "'='")?;
        // enum input: input mode = { SMA, EMA } default SMA;  → W2 later slice
        if self.eat(K::LBrace) {
            return Err("enum inputs ({A, B} default A) land in a later W2 slice".into());
        }
        let default_expr = self.expr()?;
        self.expect(K::Semicolon, "';'")?;
        Ok(Stmt::Input { name, default_expr })
    }

    fn def_stmt(&mut self) -> Result<Stmt, String> {
        let span = self.toks[self.pos].span;
        self.pos += 1; // def
        let name = self.ident()?;
        self.expect(K::Eq, "'='")?;
        let expr = self.expr()?;
        self.expect(K::Semicolon, "';'")?;
        Ok(Stmt::Def { name, expr, span })
    }

    fn series_stmt(&mut self) -> Result<Stmt, String> {
        self.pos += 1; // series
        let name = self.ident()?;
        self.expect(K::Eq, "'='")?;
        let init = self.expr()?;
        self.expect(K::KwThen, "'then'")?;
        let step = self.expr()?;
        self.expect(K::Semicolon, "';'")?;
        Ok(Stmt::Series { name, init, step })
    }

    fn plot_stmt(&mut self) -> Result<Stmt, String> {
        self.pos += 1; // plot
        let name = self.ident()?;
        if self.eat(K::Eq) {
            let expr = self.expr()?;
            self.expect(K::Semicolon, "';'")?;
            Ok(Stmt::Plot { name, expr: Some(expr) })
        } else {
            self.expect(K::Semicolon, "';'")?;
            Ok(Stmt::Plot { name, expr: None })
        }
    }

    fn if_assign_stmt(&mut self) -> Result<Stmt, String> {
        self.pos += 1; // if
        let cond = self.expr()?;
        self.expect(K::LBrace, "'{'")?;
        let mut then = Vec::new();
        while !self.at(K::RBrace) && !self.at(K::Eof) {
            then.push(self.plot_or_if()?);
        }
        self.expect(K::RBrace, "'}'")?;
        let mut els = Vec::new();
        if self.eat(K::KwElse) {
            if self.eat(K::LBrace) {
                while !self.at(K::RBrace) && !self.at(K::Eof) {
                    els.push(self.plot_or_if()?);
                }
                self.expect(K::RBrace, "'}'")?;
            } else {
                els.push(self.if_assign_stmt()?);
            }
        }
        Ok(Stmt::IfAssign { cond, then, els })
    }

    fn plot_or_if(&mut self) -> Result<Stmt, String> {
        if self.at(K::KwPlot) {
            self.pos += 1;
            let name = self.ident()?;
            self.expect(K::Eq, "'='")?;
            let expr = self.expr()?;
            self.expect(K::Semicolon, "';'")?;
            Ok(Stmt::PlotAssign { name, expr })
        } else if self.at(K::KwIf) {
            self.if_assign_stmt()
        } else {
            Err("statement-form if bodies may only assign plots (W2a)".into())
        }
    }

    // ── expressions ────────────────────────────────────────────────────

    fn expr(&mut self) -> Result<Expr, String> {
        self.if_expr()
    }

    fn if_expr(&mut self) -> Result<Expr, String> {
        if self.eat(K::KwIf) {
            let cond = self.expr()?;
            self.expect(K::KwThen, "'then'")?;
            let then = self.expr()?;
            self.expect(K::KwElse, "'else'")?;
            let els = self.expr()?;
            return Ok(Expr::If {
                cond: Box::new(cond),
                then: Box::new(then),
                els: Box::new(els),
            });
        }
        self.or_expr()
    }

    fn or_expr(&mut self) -> Result<Expr, String> {
        let mut lhs = self.and_expr()?;
        loop {
            let op = if self.eat(K::KwOr) {
                BinOp::Or
            } else if self.eat(K::KwXor) {
                BinOp::Xor
            } else {
                break;
            };
            let rhs = self.and_expr()?;
            lhs = Expr::Bin { op, lhs: Box::new(lhs), rhs: Box::new(rhs) };
        }
        Ok(lhs)
    }

    fn and_expr(&mut self) -> Result<Expr, String> {
        let mut lhs = self.not_expr()?;
        while self.eat(K::KwAnd) {
            let rhs = self.not_expr()?;
            lhs = Expr::Bin { op: BinOp::And, lhs: Box::new(lhs), rhs: Box::new(rhs) };
        }
        Ok(lhs)
    }

    fn not_expr(&mut self) -> Result<Expr, String> {
        if self.eat(K::KwNot) {
            let e = self.not_expr()?;
            return Ok(Expr::Not(Box::new(e)));
        }
        self.comparison()
    }

    fn comparison(&mut self) -> Result<Expr, String> {
        let lhs = self.additive()?;
        // crosses above/below → builtins
        if self.eat(K::KwCrosses) {
            if self.eat(K::KwAbove) {
                let rhs = self.additive()?;
                return Ok(Expr::Call {
                    name: "CrossesAbove".into(),
                    args: vec![(Some("a".into()), lhs), (Some("b".into()), rhs)],
                    span: Span { start: 0, end: 0 },
                });
            }
            if self.eat(K::KwBelow) {
                let rhs = self.additive()?;
                return Ok(Expr::Call {
                    name: "CrossesBelow".into(),
                    args: vec![(Some("a".into()), lhs), (Some("b".into()), rhs)],
                    span: Span { start: 0, end: 0 },
                });
            }
            return Err("parse error: `crosses` requires `above` or `below`".into());
        }
        let op = match self.kind() {
            K::Lt => Some(BinOp::Lt),
            K::Gt => Some(BinOp::Gt),
            K::Le => Some(BinOp::Le),
            K::Ge => Some(BinOp::Ge),
            K::Eq | K::EqEq => Some(BinOp::Eq),
            K::Ne => Some(BinOp::Ne),
            _ => None,
        };
        if let Some(op) = op {
            self.pos += 1;
            let rhs = self.additive()?;
            return Ok(Expr::Bin { op, lhs: Box::new(lhs), rhs: Box::new(rhs) });
        }
        Ok(lhs)
    }

    fn additive(&mut self) -> Result<Expr, String> {
        let mut lhs = self.multiplicative()?;
        loop {
            let op = if self.eat(K::Plus) {
                BinOp::Add
            } else if self.eat(K::Minus) {
                BinOp::Sub
            } else {
                break;
            };
            let rhs = self.multiplicative()?;
            lhs = Expr::Bin { op, lhs: Box::new(lhs), rhs: Box::new(rhs) };
        }
        Ok(lhs)
    }

    fn multiplicative(&mut self) -> Result<Expr, String> {
        let mut lhs = self.unary()?;
        loop {
            let op = if self.eat(K::Star) {
                BinOp::Mul
            } else if self.eat(K::Slash) {
                BinOp::Div
            } else {
                break;
            };
            let rhs = self.unary()?;
            lhs = Expr::Bin { op, lhs: Box::new(lhs), rhs: Box::new(rhs) };
        }
        Ok(lhs)
    }

    fn unary(&mut self) -> Result<Expr, String> {
        if self.eat(K::Minus) {
            let e = self.unary()?;
            return Ok(Expr::Bin {
                op: BinOp::Sub,
                lhs: Box::new(Expr::Num(0.0)),
                rhs: Box::new(e),
            });
        }
        self.postfix()
    }

    fn postfix(&mut self) -> Result<Expr, String> {
        let mut e = self.primary()?;
        loop {
            if self.eat(K::LBracket) {
                // [n] — static, non-negative; dynamic offsets go through
                // GetValue (spec §3). Negative literals rejected here.
                let negative = self.eat(K::Minus);
                let n = match self.kind().clone() {
                    K::Number(v) => {
                        self.pos += 1;
                        v
                    }
                    _ => {
                        return Err(
                            "history index [n] must be a constant non-negative integer (dynamic offsets: GetValue)".into(),
                        )
                    }
                };
                self.expect(K::RBracket, "']'")?;
                if negative || n < 0.0 {
                    return Err(
                        "negative (future) indexing does not exist in v2script — [n] is past-only"
                            .into(),
                    );
                }
                if n.fract() != 0.0 {
                    return Err("history index [n] must be an integer".into());
                }
                e = Expr::Index(Box::new(e), n as i64);
            } else {
                break;
            }
        }
        Ok(e)
    }

    fn primary(&mut self) -> Result<Expr, String> {
        match self.kind().clone() {
            K::Number(v) => {
                self.pos += 1;
                Ok(Expr::Num(v))
            }
            K::Str(s) => {
                self.pos += 1;
                Ok(Expr::StrLit(s))
            }
            K::KwTrue => {
                self.pos += 1;
                Ok(Expr::BoolLit(true))
            }
            K::KwFalse => {
                self.pos += 1;
                Ok(Expr::BoolLit(false))
            }
            K::LParen => {
                self.pos += 1;
                let e = self.expr()?;
                self.expect(K::RParen, "')'")?;
                Ok(e)
            }
            K::Ident(name) => {
                self.pos += 1;
                if self.eat(K::LParen) {
                    // call with named args (order-free); positional calls
                    // rejected (the calling convention is named — spec §1.6)
                    let mut args = Vec::new();
                    if !self.at(K::RParen) {
                        loop {
                            // named (IDENT = expr) or positional (expr)
                            let named = if let K::Ident(pname) = self.kind().clone() {
                                // lookahead: IDENT followed by '=' → named
                                if self.toks.len() > self.pos + 1
                                    && self.toks[self.pos + 1].kind == K::Eq
                                {
                                    self.pos += 2;
                                    Some(pname)
                                } else {
                                    None
                                }
                            } else {
                                None
                            };
                            let v = self.expr()?;
                            args.push((named, v));
                            if !self.eat(K::Comma) {
                                break;
                            }
                        }
                    }
                    let span = self.toks[self.pos - 1].span;
                    self.expect(K::RParen, "')'")?;
                    return Ok(Expr::Call { name, args, span });
                }
                // `close from 2 bars ago` desugar
                if self.at(K::KwFrom) {
                    self.pos += 1;
                    let n = match self.kind().clone() {
                        K::Number(v) => {
                            self.pos += 1;
                            v
                        }
                        _ => return Err("parse error: `from N bars ago` needs a constant N".into()),
                    };
                    self.expect(K::KwBars, "'bars'")?;
                    self.expect(K::KwAgo, "'ago'")?;
                    if n < 0.0 || n.fract() != 0.0 {
                        return Err("`from N bars ago` requires a constant non-negative integer N".into());
                    }
                    return Ok(Expr::Index(Box::new(Expr::Ident(name, Span { start: 0, end: 0 })), n as i64));
                }
                Ok(Expr::Ident(name, Span { start: 0, end: 0 }))
            }
            other => Err(format!(
                "parse error: unexpected {other:?} at byte {}",
                self.toks[self.pos].span.start
            )),
        }
    }
}

#[allow(unused)]
fn unused_marker(_: T) {}
