//! ot-core — Opentrader V2 engine truth.
//!
//! The verbatim no-lookahead contract (locked in ticket #345, ported from
//! V1 `setup_search/engine.py::run_backtest`):
//!   * decisions (score, regime, gates, signal exits) use the PREVIOUS bar's
//!     close (master[t-1]);
//!   * fills execute at the CURRENT bar's close (master[t]);
//!   * warm-up starts one bar later so the first signal bar is fully formed;
//!   * exits: TP/SL evaluated against the SAME bar's high/low, trailing peak
//!     from highs, max-hold, signal exit, RSI exit — in that priority order;
//!   * a symbol whose aligned series does not cover the signal bar is
//!     inactive for that bar (not scored, never silently dropped);
//!   * delisted names force-exit at their LAST recorded close.
//!
//! Everything is deterministic: no wall-clock, no hash-order iteration, and
//! identical inputs replay to identical outputs.

pub mod bar;
pub mod config;
pub mod engine;
pub mod features;
pub mod rulefloor;
pub mod universe;

pub use bar::{Bar, Series};
pub use config::{clamp_config, Config, DEFAULT_CONFIG, FEE_PER_SIDE, START_EQUITY};
pub use engine::{BacktestResult, Metrics, Trade, DECISION_VIEW_END_EXCLUSIVE};
pub use universe::Universe;
