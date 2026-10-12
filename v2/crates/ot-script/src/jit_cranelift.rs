//! Cranelift JIT backend for `ot-script`.
//!
//! This module provides a JIT-compiled implementation of the momentum kernel
//! (Mean Reversion/Momentum calculation) using Cranelift.
//!
//! # Laws
//! - J1: `compile_momentum_kernel` never panics; unsupported hosts return Err.
//! - J2: JIT output matches interpreter semantics bit-for-bit (or within 1e-12 rel tol).
//! - J3: `is_jit()` returns true only if compiled via Cranelift, not a fallback.
//! - J4: Invalid inputs return Err, never panic or 0.0.
//! - J5: `CraneliftBackend` implements `ScanBackend` and delegates to interpreter for non-JIT paths.
//! - J6: All public items have doc comments stating the law they enforce.

#![cfg(feature = "cranelift")]

use crate::jit::ScanBackend;
use cranelift_codegen::ir::UserFuncName;
use cranelift_codegen::ir::InstBuilder; // the *InstBuilder methods are trait methods
use cranelift_codegen::ir::BlockArg;
use cranelift_codegen::ir::types;
use cranelift_codegen::ir::AbiParam;
use cranelift_codegen::settings::{self, Configurable};
use cranelift_codegen::Context;
use cranelift_frontend::{FunctionBuilder, FunctionBuilderContext};
use cranelift_jit::{JITBuilder, JITModule};
use cranelift_module::{Linkage, Module, default_libcall_names};
use cranelift_codegen::isa::OwnedTargetIsa;

/// A JIT-compiled kernel for the momentum calculation.
///
/// Law J1: Construction never panics.
/// Law J2: Execution matches interpreter semantics.
/// Law J3: `is_jit()` accurately reflects compilation source.
/// Law J4: Input validation is handled during construction or execution.
pub struct JitKernel {
    func: Option<extern "C" fn(*const f64, usize, usize) -> f64>,
    is_jit: bool,
    window: usize,
}

impl JitKernel {
    pub fn compile_momentum_kernel(window: usize) -> Result<JitKernel, String> {
        if window == 0 {
            return Err("window must be > 0".to_string());
        }

        let isa = make_isa().ok_or_else(|| "Unsupported host architecture for Cranelift JIT".to_string())?;

        let mut module = JITModule::new(JITBuilder::with_isa(isa, default_libcall_names()));
        let mut ctx = module.make_context();
        let mut func_ctx = FunctionBuilderContext::new();

        let mut sig = module.make_signature();
        sig.params.push(AbiParam::new(types::I64)); // ptr
        sig.params.push(AbiParam::new(types::I64)); // len
        sig.params.push(AbiParam::new(types::I64)); // window
        sig.returns.push(AbiParam::new(types::F64));

        let func_id = module.declare_function("momentum_kernel", Linkage::Local, &sig).map_err(|e| e.to_string())?;
        ctx.func.signature = sig.clone();
        ctx.func.name = UserFuncName::user(0, func_id.as_u32());

        {
            let mut bcx = FunctionBuilder::new(&mut ctx.func, &mut func_ctx);
            let entry = bcx.create_block();
            let loop_head = bcx.create_block();
            let loop_body = bcx.create_block();
            let exit_block = bcx.create_block();

            bcx.switch_to_block(entry);
            let ptr_arg = bcx.append_block_param(entry, types::I64);
            let len_arg = bcx.append_block_param(entry, types::I64);
            let window_arg = bcx.append_block_param(entry, types::I64);

            let zero = bcx.ins().f64const(0.0);
            let i_init = bcx.ins().iadd_imm(len_arg, -(window as i64));

            bcx.ins().jump(loop_head, &[BlockArg::Value(zero), BlockArg::Value(i_init)]);

            bcx.switch_to_block(loop_head);
            let acc = bcx.append_block_param(loop_head, types::F64);
            let i = bcx.append_block_param(loop_head, types::I64);

            // exit_block consumes the accumulated sum, so the branch that
            // enters it MUST pass it: declaring a block param and branching
            // with &[] is a verifier error (the accumulation would also be
            // lost, so the kernel would return a wrong number).
            let exit_acc = bcx.append_block_param(exit_block, types::F64);
            let cond = bcx.ins().icmp(cranelift_codegen::ir::condcodes::IntCC::SignedLessThan, i, len_arg);
            bcx.ins().brif(cond, loop_body, &[], exit_block, &[BlockArg::Value(acc)]);

            bcx.switch_to_block(loop_body);
            let byte_offset = bcx.ins().imul_imm(i, 8);
            let effective_ptr = bcx.ins().iadd(ptr_arg, byte_offset);
            
            let val = bcx.ins().load(
                types::F64, // load(Type, MemFlags, ptr, offset) in 0.136
                cranelift_codegen::ir::MemFlagsData::trusted(),
                effective_ptr,
                0,
            );

            let new_acc = bcx.ins().fadd(acc, val);
            let new_i = bcx.ins().iadd_imm(i, 1);

            bcx.ins().jump(loop_head, &[BlockArg::Value(new_acc), BlockArg::Value(new_i)]);

            bcx.switch_to_block(exit_block);

            let last_idx = bcx.ins().iadd_imm(len_arg, -1);
            let last_byte_offset = bcx.ins().imul_imm(last_idx, 8);
            let last_ptr = bcx.ins().iadd(ptr_arg, last_byte_offset);
            let last_val = bcx.ins().load(
                types::F64,
                cranelift_codegen::ir::MemFlagsData::trusted(),
                last_ptr,
                0,
            );

            let window_f64 = bcx.ins().fcvt_from_sint(types::F64, window_arg);
            let mean = bcx.ins().fdiv(exit_acc, window_f64);
            let result = bcx.ins().fsub(last_val, mean);

            bcx.ins().return_(&[result]);
            bcx.seal_all_blocks();
            bcx.finalize(module.target_config());
        }

        module.define_function(func_id, &mut ctx).map_err(|e| format!("{e:?}"))?;
        module.finalize_definitions().map_err(|e| e.to_string())?;

        let ptr = module.get_finalized_function(func_id);
        
        let f: extern "C" fn(*const f64, usize, usize) -> f64 = unsafe {
            std::mem::transmute(ptr)
        };

        Ok(JitKernel {
            func: Some(f),
            is_jit: true,
            window,
        })
    }

    pub fn momentum_last(&self, closes: &[f64]) -> Result<f64, String> {
        if closes.is_empty() {
            return Err("closes slice is empty".to_string());
        }
        if closes.len() < self.window {
            return Err(format!("slice len {} < window {}", closes.len(), self.window));
        }
        
        let f = self.func.ok_or("JIT function not available")?;
        Ok(f(closes.as_ptr(), closes.len(), self.window))
    }
    
    pub fn is_jit(&self) -> bool {
        self.is_jit
    }
}


fn make_isa() -> Option<OwnedTargetIsa> {
    let mut fb = settings::builder();
    fb.set("use_colocated_libcalls", "false").ok()?;
    fb.set("is_pic", if cfg!(target_arch = "x86_64") { "true" } else { "false" }).ok()?;
    cranelift_native::builder().ok()?.finish(settings::Flags::new(fb)).ok()
}

/// A Cranelift JIT backend implementing `ScanBackend`.
///
/// Law J5: Implements `ScanBackend` and delegates to interpreter for non-JIT paths.
pub struct CraneliftBackend;

impl ScanBackend for CraneliftBackend {
    fn name(&self) -> &'static str {
        "cranelift"
    }

    /// Law J5: the interpreter stays the reference/fallback for anything the
    /// JIT kernel does not cover, so this delegates to `run_scan` unchanged
    /// rather than reimplementing scan semantics (a second implementation
    /// would be a second source of truth).
    fn run(
        &self,
        req: &crate::scan::ScanRequest,
        plan: &crate::check::CompilePlan,
        universe: &[(String, Vec<ot_core::bar::Bar>)],
        cfg: &crate::scan::ScanConfig,
    ) -> Result<crate::scan::ScanResult, String> {
        crate::scan::run_scan(req, plan, universe, cfg)
    }
}

/// Returns a new `CraneliftBackend`.
///
/// Law J5: Provides access to the backend behind the existing seam.
pub fn backend() -> CraneliftBackend {
    CraneliftBackend
}
