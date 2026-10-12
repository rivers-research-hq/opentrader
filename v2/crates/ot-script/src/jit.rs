//! # Pluggable Scan Backend Seam
//!
//! This module defines the abstraction layer for scan backends. It allows the
//! scan engine to be implemented via different strategies (e.g., interpreter,
//! JIT) while maintaining a consistent interface for the rest of the application.
//!
//! ## Laws
//! 1. **Interpreter Backend**: `InterpreterBackend::run` is a pure pass-through to
//!    `crate::scan::run_scan`. It performs no re-sorting, re-filtering, re-ranking,
//!    or limit clamping. All semantics remain in `run_scan`.
//! 2. **Backend Resolution**: `backend_by_name` maps "interpreter" and "interp" to
//!    the interpreter backend. It returns `None` for "cranelift", "jit", "jit-cranelift",
//!    and any other unknown name. It NEVER silently falls back to the interpreter for
//!    unimplemented backends.
//! 3. **Unknown Names**: Any name not explicitly recognized returns `None`.
//! 4. **No Panics**: This module contains no `unwrap`, `expect`, or `panic` calls.
//! 5. **Dependencies**: Only `std` and crate-internal modules are used. No new external
//!    dependencies are introduced.

use crate::check::CompilePlan;
use ot_core::bar::Bar;
use crate::scan::{run_scan, ScanConfig, ScanRequest, ScanResult};

/// The trait defining the interface for a scan backend.
///
/// Implementations of this trait must satisfy the laws defined in the module documentation.
pub trait ScanBackend {
    /// Returns the human-readable name of this backend.
    fn name(&self) -> &'static str;

    /// Runs the scan request against the provided universe.
    ///
    /// # Arguments
    /// * `req` - The scan request parameters.
    /// * `plan` - The compiled script plan.
    /// * `universe` - The historical bar data, keyed by symbol.
    /// * `cfg` - Configuration for the scan execution.
    ///
    /// # Returns
    /// A `Result` containing either the `ScanResult` or an error string.
    fn run(
        &self,
        req: &ScanRequest,
        plan: &CompilePlan,
        universe: &[(String, Vec<Bar>)],
        cfg: &ScanConfig,
    ) -> Result<ScanResult, String>;
}

/// The interpreter-based backend implementation.
///
/// This backend delegates all work to the existing `crate::scan::run_scan` function.
/// It serves as the baseline for differential parity testing against future JIT backends.
pub struct InterpreterBackend;

impl ScanBackend for InterpreterBackend {
    /// Returns the name of this backend.
    ///
    /// # Law
    /// The name is always "interpreter".
    fn name(&self) -> &'static str {
        "interpreter"
    }

    /// Runs the scan using the interpreter.
    ///
    /// # Law
    /// This method calls `crate::scan::run_scan` and returns its value UNCHANGED.
    /// It performs no re-sorting, no re-filtering, no re-ranking, and no clamping of the limit.
    /// All semantics stay in `run_scan`.
    fn run(
        &self,
        req: &ScanRequest,
        plan: &CompilePlan,
        universe: &[(String, Vec<Bar>)],
        cfg: &ScanConfig,
    ) -> Result<ScanResult, String> {
        run_scan(req, plan, universe, cfg)
    }
}

/// Creates a new instance of the interpreter backend.
pub fn interpreter() -> InterpreterBackend {
    InterpreterBackend
}

/// Resolves a backend by its name.
///
/// # Law
/// - "interpreter" and "interp" return `Some(Box<dyn ScanBackend>)` pointing to the interpreter.
/// - "cranelift", "jit", "jit-cranelift" return `None`.
/// - Any other unknown name returns `None`.
/// - It NEVER silently falls back to the interpreter for an unimplemented name.
///
/// # Arguments
/// * `name` - The name of the backend to resolve.
///
/// # Returns
/// `Some(Box<dyn ScanBackend>)` if the backend is implemented, `None` otherwise.
pub fn backend_by_name(name: &str) -> Option<Box<dyn ScanBackend>> {
    match name {
        "interpreter" | "interp" => Some(Box::new(interpreter())),
        // Explicitly return None for known JIT names to prevent silent fallback.
        "cranelift" | "jit" | "jit-cranelift" => None,
        // Unknown names also return None.
        _ => None,
    }
}
