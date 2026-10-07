//! Conventional lexer; word-operators (`crosses above`) desugar at parse.

use crate::ast::{Span, Token, TokenKind};

pub fn lex(source: &str) -> Result<Vec<Token>, String> {
    let b = source.as_bytes();
    let mut i = 0usize;
    let mut out: Vec<Token> = Vec::new();
    while i < b.len() {
        let c = b[i] as char;
        match c {
            ' ' | '\t' | '\r' | '\n' => i += 1,
            '#' => {
                while i < b.len() && b[i] != b'\n' {
                    i += 1;
                }
            }
            '/' if i + 1 < b.len() && b[i + 1] == b'/' => {
                while i < b.len() && b[i] != b'\n' {
                    i += 1;
                }
            }
            '+' => {
                out.push(tok(TokenKind::Plus, "+", i, i + 1));
                i += 1;
            }
            '*' => {
                out.push(tok(TokenKind::Star, "*", i, i + 1));
                i += 1;
            }
            '/' => {
                out.push(tok(TokenKind::Slash, "/", i, i + 1));
                i += 1;
            }
            '-' => {
                if i + 1 < b.len() && b[i + 1] == b'>' {
                    out.push(tok(TokenKind::Arrow, "->", i, i + 2));
                    i += 2;
                } else {
                    out.push(tok(TokenKind::Minus, "-", i, i + 1));
                    i += 1;
                }
            }
            '<' => {
                if i + 1 < b.len() && b[i + 1] == b'=' {
                    out.push(tok(TokenKind::Le, "<=", i, i + 2));
                    i += 2;
                } else {
                    out.push(tok(TokenKind::Lt, "<", i, i + 1));
                    i += 1;
                }
            }
            '>' => {
                if i + 1 < b.len() && b[i + 1] == b'=' {
                    out.push(tok(TokenKind::Ge, ">=", i, i + 2));
                    i += 2;
                } else {
                    out.push(tok(TokenKind::Gt, ">", i, i + 1));
                    i += 1;
                }
            }
            '=' => {
                if i + 1 < b.len() && b[i + 1] == b'=' {
                    out.push(tok(TokenKind::EqEq, "==", i, i + 2));
                    i += 2;
                } else {
                    out.push(tok(TokenKind::Eq, "=", i, i + 1));
                    i += 1;
                }
            }
            '!' => {
                if i + 1 < b.len() && b[i + 1] == b'=' {
                    out.push(tok(TokenKind::Ne, "!=", i, i + 2));
                    i += 2;
                } else {
                    return Err(err("unexpected '!' (use `not` for negation, `!=` for inequality)", i));
                }
            }
            '[' => {
                out.push(tok(TokenKind::LBracket, "[", i, i + 1));
                i += 1;
            }
            ']' => {
                out.push(tok(TokenKind::RBracket, "]", i, i + 1));
                i += 1;
            }
            '(' => {
                out.push(tok(TokenKind::LParen, "(", i, i + 1));
                i += 1;
            }
            ')' => {
                out.push(tok(TokenKind::RParen, ")", i, i + 1));
                i += 1;
            }
            '{' => {
                out.push(tok(TokenKind::LBrace, "{", i, i + 1));
                i += 1;
            }
            '}' => {
                out.push(tok(TokenKind::RBrace, "}", i, i + 1));
                i += 1;
            }
            ',' => {
                out.push(tok(TokenKind::Comma, ",", i, i + 1));
                i += 1;
            }
            ';' => {
                out.push(tok(TokenKind::Semicolon, ";", i, i + 1));
                i += 1;
            }
            ':' => {
                out.push(tok(TokenKind::Colon, ":", i, i + 1));
                i += 1;
            }
            '"' => {
                // string literal (no escapes this slice)
                let start = i;
                i += 1;
                let s = i;
                while i < b.len() && b[i] != b'"' {
                    i += 1;
                }
                if i >= b.len() {
                    return Err(err("unterminated string", start));
                }
                out.push(Token {
                    kind: TokenKind::Str(source[s..i].to_string()),
                    text: source[s..i].to_string(),
                    span: Span { start: s, end: i },
                });
                i += 1;
            }
            c if c.is_ascii_digit() || (c == '.' && i + 1 < b.len() && b[i + 1].is_ascii_digit()) => {
                let start = i;
                while i < b.len() && (b[i] as char).is_ascii_digit() {
                    i += 1;
                }
                if i < b.len() && b[i] == b'.' {
                    i += 1;
                    while i < b.len() && (b[i] as char).is_ascii_digit() {
                        i += 1;
                    }
                }
                let text = &source[start..i];
                let n: f64 = text.parse().map_err(|_| err("bad number", start))?;
                out.push(Token {
                    kind: TokenKind::Number(n),
                    text: text.to_string(),
                    span: Span { start, end: i },
                });
            }
            c if c.is_ascii_alphabetic() || c == '_' => {
                let start = i;
                while i < b.len() && ((b[i] as char).is_ascii_alphanumeric() || b[i] == b'_') {
                    i += 1;
                }
                let text = &source[start..i];
                let kind = match text {
                    "declare" => TokenKind::KwDeclare,
                    "input" => TokenKind::KwInput,
                    "def" => TokenKind::KwDef,
                    "series" => TokenKind::KwSeries,
                    "plot" => TokenKind::KwPlot,
                    "then" => TokenKind::KwThen,
                    "if" => TokenKind::KwIf,
                    "else" => TokenKind::KwElse,
                    "and" => TokenKind::KwAnd,
                    "or" => TokenKind::KwOr,
                    "xor" => TokenKind::KwXor,
                    "not" => TokenKind::KwNot,
                    "true" => TokenKind::KwTrue,
                    "false" => TokenKind::KwFalse,
                    "from" => TokenKind::KwFrom,
                    "bars" => TokenKind::KwBars,
                    "ago" => TokenKind::KwAgo,
                    "above" => TokenKind::KwAbove,
                    "below" => TokenKind::KwBelow,
                    "crosses" => TokenKind::KwCrosses,
                    "default" => TokenKind::KwDefault,
                    "lower" => TokenKind::Lower,
                    "upper" => TokenKind::Upper,
                    "on_price" | "onPrice" => TokenKind::OnPrice,
                    _ => TokenKind::Ident(text.to_string()),
                };
                out.push(Token {
                    kind,
                    text: text.to_string(),
                    span: Span { start, end: i },
                });
            }
            other => return Err(err(&format!("unexpected character {other:?}"), i)),
        }
    }
    out.push(Token {
        kind: TokenKind::Eof,
        text: String::new(),
        span: Span { start: b.len(), end: b.len() },
    });
    Ok(out)
}

fn tok(kind: TokenKind, text: &str, start: usize, end: usize) -> Token {
    Token {
        kind,
        text: text.to_string(),
        span: Span { start, end },
    }
}

fn err(msg: &str, at: usize) -> String {
    format!("lex error at byte {at}: {msg}")
}
