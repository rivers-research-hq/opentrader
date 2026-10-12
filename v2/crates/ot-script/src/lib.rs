//! v2script — the series-native DSL interpreter.
//!
//! Locked design (#337, spec #346 → docs/agents/research/v2-scripting-spec.md):
//!   * **series-by-default**: every binding is a per-bar series; scalars are
//!     constant series.
//!   * **no future indexing**: `[n]` is past-only, static, non-negative.
//!   * **lazy if**: only the taken branch evaluates per bar; both branches
//!     type-check.
//!   * **per-binding warm-up**: bars before a binding's static warm-up are
//!     NaN — no global past offset, no silent shifts.
//!   * **`series` has explicit init/then**: no implicit initialization.
//!   * **NaN = don't paint** (float only).
//!   * capability sandbox: no I/O, no wall-clock, no randomness, no network.
//!
//! This slice implements the core language (W2a, ticket #350): the grammar
//! below, the static checks, the columnar interpreter, and the core
//! built-in families. Secondary frames (`period =`), `fold`, `study`
//! subroutines, and the order-aware strategy surface are later W2 slices
//! (compile errors point at them explicitly).

pub mod ast;
pub mod builtins;
pub mod check;
pub mod eval;
pub mod jit;
pub mod jit_cranelift;
pub mod lexer;
pub mod parser;
pub mod scan;

pub use ast::*;
pub use check::{CheckError, CompilePlan, CondSpec, OnAction, OnPlan, Pane, StrategyPlan};
pub use eval::{EvalOutput, Frame, Plot, ScriptRequest, Warmup, run_strategy};
pub use scan::{ScanConfig, ScanHit, ScanRequest, ScanResult, run_scan};

/// Compile + evaluate convenience for the host seam (single symbol/frame
/// this slice; the ScriptRequest shape per spec §6).
pub fn compile(source: &str) -> Result<CompilePlan, String> {
    let tokens = lexer::lex(source)?;
    let stmts = parser::parse(&tokens)?;
    check::check(stmts).map_err(|e| e.to_string())
}

pub fn eval(
    request: &ScriptRequest,
    plan: &CompilePlan,
    frame: &eval::Frame,
) -> Result<EvalOutput, String> {
    eval::evaluate(request, plan, frame)
}
