#!/usr/bin/env python3
"""OpenTrader Harness — the event loop.

from security.guards import guarded_urlopen, guarded_open, guarded_requests_get, sec_pickle_load  # noqa: E402  (hardening layer)
urlopen = guarded_urlopen  # hardening shadow
open = guarded_open  # hardening shadow
Architecture (sync-only, matching the spec):
  Exchange → Agent (MCP tools) → Risk → State → Dashboard

The model calls tools via MCP. The harness orchestrates the cycle.
"""
from security.guards import guarded_urlopen, guarded_open, guarded_requests_get, sec_pickle_load  # noqa: E402  (hardening layer)
urlopen = guarded_urlopen  # hardening shadow
open = guarded_open  # hardening shadow

import argparse
import concurrent.futures
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Ensure project root is on path
PROJECT = str(Path(__file__).resolve().parent)
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)

from agent import TradingAgent, MCPClient, BaseAgent, Signal
from exchange.base import ExchangeBase, get_exchange, OHLCV
from exchange.paper import PaperExchange
from exchange.multi_router import MultiExchangeRouter
from data.synthetic import generate_bars, generate_trending_bars
from mot.tradable_universe import TRADABLE_UNIVERSE, DEFAULT_START_PRICES, SCOUT_PROMPT
from mot.dynamic_discovery import (
    resolve_discovery,
    get_sector_list,
    PRICE_ESTIMATES,
    refresh_from_exchange,
)
from mot.monitors import CommitteeChair
from data.regime_classifier import classify_regime
from risk.manager import RiskManager, RiskConfig
from risk.regime_adaptation import get_regime_instructions, get_regime_risk_overrides
from risk.asset_allocator import AssetClassAllocator
from state.manager import StateManager
from state.context import AccountContext, FEE_TABLES
from training.real_pattern_bank import RealTradePatternBank
from mot.trader_md import TraderMD, distill_coach_report, distill_atdl_action

logger = logging.getLogger("opentrader.harness")


def _find_gpu_python() -> str:
    """Find a Python executable with ROCm/CUDA and Unsloth.

    Checks known ROCm venvs. Falls back to sys.executable.
    """
    candidates = [
        os.path.expanduser("~/rocm_venv/bin/python3"),
        os.path.expanduser("~/rocm_venv/bin/python"),
        sys.executable,
    ]
    for py in candidates:
        if os.path.isfile(py):
            return py
    return sys.executable


# ── Hardware Funding Goal ────────────────────────────────────
# Opentrader's current objective: grow paper capital to fund real hardware.
# Target: $270 (MI60 32GB ~$120 + 64GB DDR4 ~$60 + 2TB NVMe ~$90)
# This goal is injected into every debate so the agent optimizes for growth.
GOAL_CAPITAL: float = 270.0  # Minimum to acquire hardware
GOAL_DESCRIPTION: str = (
    "HARDWARE FUND GOAL: Accumulate ${goal_capital:.0f} for LLM upgrades. "
    "Current paper balance: ${current_balance:.2f}. "
    "Progress: {progress_pct:.1f}% (need ${remaining:.2f} more). "
    "Target hardware: MI60 32GB GPU + 64GB DDR4 RAM + 2TB NVMe for running larger models. "
    "Use this as your primary strategic objective. Grow capital through repeated small wins, "
    "not Hail Mary trades. Protect the downside — you can't buy hardware from a blown account."
)

# ── Progression Stages ───────────────────────────────────────
# Agent graduates to more symbols as it proves profitability.
# Each stage requires: minimum hours running AND minimum % return.
STAGES = {
    1: {
        "symbols": ["BTC/USDT"],
        "label": "BTC Only",
        "unlock_hours": 6,
        "unlock_return_pct": 1.0,
    },
    2: {
        "symbols": ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
        "label": "Crypto Basket",
        "unlock_hours": 24,
        "unlock_return_pct": 5.0,
    },
    3: {
        "symbols": ["BTC/USDT", "ETH/USDT", "SOL/USDT", "AAPL", "NVDA", "SONY"],
        "label": "Crypto + Equities",
        "unlock_hours": 48,
        "unlock_return_pct": 10.0,
    },
}
MAX_STAGE = max(STAGES.keys())

# Cycles a holding may sit without any usable price before it is quarantined
# (frozen against all exits) instead of silently skipped forever. 60 cycles
# ≈ 1 hour at the live --interval 60.
UNPRICEABLE_QUARANTINE_CYCLES = 60

# ── Minimum hold cycles: prevent flip-flop sells ──
# Positions no longer subject to min-hold — ADIR adversarial debate provides
# genuine signal quality that makes mechanical hold gates unnecessary.
# Stop-loss and take-profit levels remain as hard risk controls.


class OpenTraderHarness:
    """Main trading harness — the event loop."""

    def __init__(
        self,
        symbol: str = "BTC/USDT",
        timeframe: str = "1h",
        initial_cash: float = 100_000.0,
        exchange: str = "paper",
        agent_name: str = "trading_agent",
        mcp_url: str = None,
        state_dir: str = None,
        synthetic_data: bool = True,
        synthetic_bars: int = 500,
        synthetic_seed: int = 42,
        max_cycles: int = 0,  # 0 = unlimited
        cycle_interval: float = 1.0,
        model: str = None,
        fast_model: str = "",
        llama_host: str = None,
        use_model: bool = True,
        backtest: bool = False,
        backtest_bars: int = 0,
        backtest_symbol: str = "",
        flash_train: bool = True,
        debate_enabled: bool = True,
        parallel_debate: bool = None,
        debate_mode: str = None,  # "fast" (composite) | "adir" (independent agents)
        rule_gate: bool = False,  # gate BUY signals behind the validated rule screen
        mixture: bool = False,  # MoT experts: route decisions through the regime router (rule-floor prior)
        rule_primary: bool = False,  # the validated rule config is the PRIMARY signal source
        vix_gate: str = "strict",  # VIX regime gate: "strict" (z>=0.5, falsified as edge),
        # "soft" (z>=0.0), "off" (neutralized — informational only, fills never blocked)
        stage: int = 0,  # 0 = auto (from state/progression), >0 = force
        universe_mode: bool = True,  # agent picks symbols from 50+ universe vs hardcoded list
        universe_focus: int = 6,  # number of symbols to deep-debate per cycle
        mot_force: str = "auto",  # "auto"|"increase"|"reduce"|"maintain"
        max_daily_trades: int = 500,  # daily trade cap (resets at UTC midnight)
        sidecar: bool = False,  # offload exchange+risk to Rust sidecar
        sidecar_binary: str = None,  # path to exchange-engine binary
        stock_exchange: str = None,  # stock exchange for multi-asset mode (ibkr|finnhub|...+)
        crypto_exchange: str = None,  # crypto exchange for multi-asset mode (kraken|coinbase|...)
        reset_portfolio: bool = False,  # explicit opt-in: wipe paper_state.json + fills ledger on startup
    ):
        # Load centralized config — CLI args override config, config overrides code defaults
        cfg = self._load_config()
        self.llama_host = llama_host or cfg.get("llama_host", "http://127.0.0.1:5801")
        self.gpu0_host = cfg.get("gpu0_host", "http://127.0.0.1:5801")
        self.mcp_url = mcp_url or cfg.get("mcp_url", "http://127.0.0.1:8092")
        self.debate_model = model or cfg.get("debate_model", "qwythos-9b-mtp")
        self.fast_model = fast_model or cfg.get("fast_model", "qwythos-9b-mtp")
        self.risk_model = cfg.get("risk_model", "qwythos-9b-mtp")
        if parallel_debate is None:
            parallel_debate = cfg.get("parallel_debate", False)
        if debate_mode is None:
            debate_mode = cfg.get("debate_mode", "adir")
        self.flash_train_enabled = flash_train
        self.debate_enabled = debate_enabled
        self.parallel_debate = parallel_debate
        self.debate_mode = debate_mode
        self.rule_gate = rule_gate
        self._rule_gate_cache = {}
        self._rule_gate_cfg = None
        self.mixture = mixture
        self.rule_primary = rule_primary
        self.vix_gate = vix_gate
        self._mot_router = None
        self._mot_experts = {}
        self._force_stage = stage  # 0 = use state/progression, >0 = override
        self._mot_force = mot_force  # "auto" = MoT decides, otherwise forced
        self.universe_mode = universe_mode
        self.universe_focus = universe_focus
        self._universe_loaded = False
        self._tradable_universe: List[str] = list(TRADABLE_UNIVERSE)
        self.symbol = symbol  # kept for backward compat
        self.symbols: List[str] = [symbol]  # active symbols for current stage
        self.timeframe = timeframe
        self.initial_cash = initial_cash
        self.max_cycles = max_cycles
        self.cycle_interval = cycle_interval
        self.synthetic_data = synthetic_data
        self.backtest = backtest
        self.live_mode = False  # set True when using real exchange (coinbase/live)
        self.synthetic_seed = synthetic_seed
        self.synthetic_bars = synthetic_bars
        self.backtest_bars = backtest_bars
        self.backtest_symbol = backtest_symbol

        # Progression system
        self.stage: int = 1
        self.stage_start: float = 0.0  # set when loop starts
        self.stages = dict(STAGES)  # copy so we can mutate per-instance

        # State dir
        if state_dir is None:
            state_dir = str(Path(PROJECT) / "data")
        self.state_dir = state_dir
        os.makedirs(state_dir, exist_ok=True)
        self._fills_ledger_path = os.path.join(state_dir, "fills_ledger.jsonl")

        # Explicit portfolio reset (opt-in via --reset-portfolio)
        if reset_portfolio:
            logger.warning(
                "RESET-PORTFOLIO: wiping paper_state.json and fills_ledger.jsonl — "
                "starting fresh portfolio"
            )
            for _p in (
                os.path.join(state_dir, "paper_state.json"),
                self._fills_ledger_path,
            ):
                if os.path.exists(_p):
                    os.remove(_p)

        # Multi-asset exchange routing overrides
        self._stock_exchange = stock_exchange
        self._crypto_exchange = crypto_exchange

        # ── Sidecar mode: use Rust exchange-engine ──
        self.sidecar_enabled = sidecar
        self._sidecar_client = None
        if sidecar:
            from exchange_engine.python.sidecar import SidecarClient

            self._sidecar_client = SidecarClient(
                binary_path=sidecar_binary,
            )
            self._sidecar_client.start()
            logger.info(
                f"Sidecar exchange-engine started"
                + (f" ({sidecar_binary})" if sidecar_binary else "")
            )

        # Use fast model for faster inference if specified
        effective_model = fast_model or model

        # Init exchange — use MultiExchangeRouter when any stage has mixed
        # crypto+stock symbols (single-asset exchanges can't handle both).
        def _stock_symbols_exist() -> bool:
            """True if any stage includes stock symbols (no '/' separator)."""
            for stage_cfg in self.stages.values():
                for sym in stage_cfg.get("symbols", []):
                    if "/" not in sym:
                        return True
            return False

        def _crypto_symbols_exist() -> bool:
            """True if any stage includes crypto symbols (contains '/')."""
            for stage_cfg in self.stages.values():
                for sym in stage_cfg.get("symbols", []):
                    if "/" in sym:
                        return True
            return False

        _has_stocks = _stock_symbols_exist()
        _has_crypto = _crypto_symbols_exist()
        _needs_router = _has_stocks and _has_crypto

        if exchange == "paper":
            if sidecar:
                from exchange.sidecar_adapter import ExchangeSidecarAdapter

                self.exchange: ExchangeBase = ExchangeSidecarAdapter(
                    name="sidecar",
                    config={"initial_cash": initial_cash},
                )
                self.exchange._sidecar = self._sidecar_client
                self.exchange._connected = True
                if _has_stocks:
                    logger.info(
                        "Sidecar mode with stock symbols: "
                        "ExchangeSidecarAdapter is format-agnostic"
                    )
            else:
                self.exchange: ExchangeBase = PaperExchange(
                    config={"initial_cash": initial_cash}
                )
                if _has_stocks:
                    logger.info(
                        "Paper mode with stock symbols: OK (PaperExchange is format-agnostic)"
                    )
        elif exchange == "alpaca-paper":
            from exchange.alpaca_paper import AlpacaPaperExchange

            self.exchange = AlpacaPaperExchange(initial_cash=float(initial_cash))
            logger.info(
                "Alpaca paper exchange active — real equity prices via Alpaca/yfinance"
            )
        elif _needs_router:
            # Mixed crypto+stock: route through MultiExchangeRouter
            crypto_ex = self._crypto_exchange or (
                "kraken" if exchange == "finnhub" else exchange
            )
            stock_ex = self._stock_exchange or (
                "finnhub" if exchange == "kraken" else exchange
            )
            self.live_mode = True
            self.exchange = MultiExchangeRouter(
                config={
                    "initial_cash": initial_cash,
                    "crypto_exchange": crypto_ex,
                    "stock_exchange": stock_ex,
                }
            )
            logger.info(
                f"Multi-asset mode: crypto+stocks via MultiExchangeRouter "
                f"(crypto={crypto_ex}, stock={stock_ex})"
            )
        else:
            # Single asset class — use exchange directly
            self.live_mode = True
            self.exchange = get_exchange(exchange, {"initial_cash": initial_cash})
            if self.exchange is None:
                logger.warning(f"Unknown exchange '{exchange}', falling back to paper")
                self.live_mode = False
                self.exchange = PaperExchange(config={"initial_cash": initial_cash})
            else:
                logger.info(f"Live mode: {exchange} (real prices, paper settlement)")
        if not self.exchange.connect():
            if self.live_mode:
                logger.warning(
                    f"Failed to connect to {exchange}. Falling back to paper."
                )
                self.live_mode = False
                self.exchange = PaperExchange(config={"initial_cash": initial_cash})
                self.exchange.connect()

        # Load synthetic data (paper mode — also as fallback for alpaca-paper)
        if synthetic_data and exchange in ("paper", "alpaca-paper"):
            load_symbols = list(self.symbols)
            if universe_mode:
                load_symbols = refresh_from_exchange(self.exchange, TRADABLE_UNIVERSE)
                self._tradable_universe = load_symbols
                self._universe_loaded = True
                if self.live_mode and load_symbols != TRADABLE_UNIVERSE:
                    logger.info(
                        f"Universe: discovered {len(load_symbols)} symbols from "
                        f"live exchange (vs {len(TRADABLE_UNIVERSE)} hardcoded)"
                    )
            for sym in load_symbols:
                bars = generate_bars(
                    symbol=sym,
                    count=synthetic_bars,
                    seed=synthetic_seed,
                    start_price=self._start_price(sym),
                    timeframe=timeframe,
                )
                self.exchange.load_bars(sym, bars)
            logger.info(f"Loaded synthetic bars for {len(load_symbols)} symbols")
            if universe_mode:
                logger.info("Universe mode: agent will pick focus symbols each cycle")

        # When universe_mode is enabled with a live (non-synthetic) exchange,
        # mark the universe as loaded. The scout will fetch prices from the
        # exchange directly rather than relying on pre-loaded synthetic bars.
        if self.universe_mode and not self._universe_loaded:
            self._universe_loaded = True
            # Prefer the curated industry registry (511 vetted names across 49
            # sectors); raw exchange discovery returns alphabetically-sorted
            # obscure NYSE names and isn't a good trading universe. The scout's
            # radar already uses get_universe_tickers() = the registry.
            from mot.industry_map import get_universe_tickers

            try:
                registry = get_universe_tickers()
            except Exception:
                registry = []
            if registry:
                self._tradable_universe = list(registry)
                logger.info(
                    f"Universe mode: {len(self._tradable_universe)} symbols "
                    f"(curated industry registry)"
                )
            else:
                self._tradable_universe = list(TRADABLE_UNIVERSE)
                logger.info(
                    f"Universe mode: {len(self._tradable_universe)} symbols "
                    f"(static fallback)"
                )

        # Load backtest data
        if backtest:
            syms = [backtest_symbol] if backtest_symbol else STAGES[1]["symbols"]
            for sym in syms:
                self._load_backtest_data(
                    symbol=sym,
                    count=backtest_bars or synthetic_bars,
                )

        # Load optimized risk parameters for current portfolio scale
        self._optimal_params = self._load_optimal_params(initial_cash)
        self._params_cache = None  # cached parsed params.json data
        self._params_mtime = 0.0  # mtime of cached params.json

        # Init risk manager
        opt = self._optimal_params
        risk_cfg = RiskConfig(
            max_position_pct=opt.get("max_position_pct", 0.18),
            max_daily_trades=max_daily_trades,
            kelly_fraction=opt.get("kelly_fraction", 0.35),
            stop_loss_pct=opt.get("stop_loss_pct", 0.05),
            take_profit_pct=opt.get("take_profit_pct", 0.10),
            max_total_exposure=opt.get("max_total_exposure", 0.60),
        )
        risk_cfg._exchange = (
            self.exchange.name if hasattr(self.exchange, "name") else exchange
        )
        if sidecar:
            from risk.sidecar_adapter import RiskSidecarAdapter

            self.risk = RiskSidecarAdapter(config=risk_cfg)
            self.risk.set_sidecar(self._sidecar_client)
        else:
            self.risk = RiskManager(risk_cfg)
        self.risk.set_initial(initial_cash)

        # Init state manager
        self.state_mgr = StateManager(state_dir)

        # Init MCP client (for harness-level calls)
        self.mcp = MCPClient(base_url=self.mcp_url)

        # Check llama-swap before creating agent
        self._llama_available = self._check_llama(host=llama_host)

        # Init agent
        self.agent: BaseAgent = TradingAgent(
            name=agent_name,
            config={
                "mcp_url": self.mcp_url,
                "model": effective_model,
                "llama_host": self.llama_host,
                "use_model": use_model and self._llama_available,
                "initial_cash": initial_cash,
                "max_tool_calls": 5,
            },
        )

        # State
        self.cycle = 0
        self.equity_curve: List[float] = [initial_cash]
        self.drawdowns: List[float] = [0.0]
        self.peak_value = initial_cash
        self.signal_history = []
        self.running = True
        self._start_time = time.time()
        self._last_cycle_time = 0
        self._symbol_regimes: Dict[str, dict] = {}
        self._real_pattern_bank = RealTradePatternBank(self.state_dir)
        self._last_pattern_extract = 0  # cycle of last pattern extraction
        self._last_arxiv_extract = 0  # cycle of last arxiv feature extraction
        self._last_training_eval = 0  # cycle of last training scheduler evaluation
        self._last_state_key = None  # dedup cycle writes (skip_history when unchanged)
        self._sl_tp_levels: Dict[
            str, dict
        ] = {}  # symbol -> {stop_loss, take_profit, entry_price, qty, highest_price, cycle_opened}
        self._unpriceable_streak: Dict[str, int] = {}  # symbol -> consecutive cycles with no usable price
        self._quarantined: Dict[str, str] = {}  # symbol -> quarantine reason (frozen, excluded from exits)
        self._fundamentals_coverage: Dict[str, str] = {}  # symbol -> ok|missing|no_cik
        # Fresh-start state (positions/SL-TP/cash) is NOT a startup flag anymore.
        # To start clean, remove/rename data/paper_state.json — safe atomic
        # tmp-file state handling lives in state/manager.py.
        self._news_cache = None
        self._arxiv_cache = []
        self._econ_cache = None
        self._social_cache = {}
        self._econ_cycle = -1  # cycle-gate for economics fetch
        self._news_cycle = -1  # cycle-gate for news/arxiv fetch
        self._mtf_cache: Dict[str, dict] = {}  # symbol_tf -> {bars, ts}
        self._mtf_lock = threading.Lock()
        self._circuit_breaker_cycle = 0  # cycle when breaker tripped
        self._trade_journal: List[dict] = []  # completed trades for PnL tracking
        self._alerts: List[dict] = []  # SL/TP alerts for dashboard
        self._signal_scores: Dict[
            str, dict
        ] = {}  # model accuracy: symbol_action -> {correct, total}
        self._accuracy_total: int = 0  # running total predictions
        self._accuracy_correct: int = 0  # running correct predictions
        self.committee = CommitteeChair(
            max_position_pct=0.20, max_total_exposure=0.70, min_accuracy_samples=10
        )
        self._backtest_bar_index = 0
        self._onchain: Any = None  # OnchainAdapter (set externally)
        # Stage: forced via --stage, or default to 1 (overridden by state if available)
        self.stage = 1

        # Restore agent state from disk if available
        self._load_agent_state()

        # Apply forced stage override after state restoration
        if self._force_stage > 0 and self._force_stage <= MAX_STAGE:
            self.stage = self._force_stage
            self.symbols = list(STAGES[self.stage]["symbols"])

        # MoT Coordinator — periodic performance evaluation and schedule adjustment
        self.mot_coordinator = None
        try:
            from mot.coordinator import MoTCoordinator

            self.mot_coordinator = MoTCoordinator(state_dir, harness=self)
            logger.info(
                f"MoT coordinator: v{self.mot_coordinator.version_string()} "
                f"(score={self.mot_coordinator.state.current_score:.3f})"
            )
        except Exception as e:
            logger.debug(f"MoT coordinator unavailable: {e}")

        # Fine-tune subprocess tracking
        self._finetune_process = None
        self._finetune_lock_owner = False
        self._last_finetune_check = 0.0
        self.finetune_cooldown_cycles = 50  # min cycles between fine-tune checks

        # FlashTrainer — single-step training during HOLD streaks
        self.flash_trainer = None
        if self.flash_train_enabled and use_model and self._llama_available:
            try:
                from training.flash_train import FlashTrainer

                self.flash_trainer = FlashTrainer(
                    state_dir=state_dir,
                    llama_host=llama_host,
                    student_model=fast_model or "ls:qwythos-9b-mtp",
                    teacher_model=model or "ls:qwythos-9b-mtp",
                    auto_train=True,
                )
                logger.info("FlashTrainer enabled — training during HOLD streaks")
            except Exception as e:
                logger.debug(f"FlashTrainer init skipped: {e}")

        # ── Debate Engine + MoE Scoring + Reflection ─────────
        self.debate = None
        self.scorer = None
        self.reflection = None
        if self.debate_enabled and use_model and self._llama_available:
            try:
                from mot import DebateEngine, AgentScorer, ReflectionLog

                if self.debate_mode == "adir":
                    from mot.agents.adir_debate import AdirDebateEngine

                    # Debate routing (dual-GPU balanced — both GPUs work every cycle):
                    # Bull  → llama_host (ollama qwen27-trader on GPU1)
                    # Bear  → gpu0_host  (qwen2.5-coder-7b on GPU0 :5803)
                    # Risk  → gpu0_host  (qwen2.5-coder-7b on GPU0 :5803)
                    self.debate = AdirDebateEngine(
                        llama_host=self.llama_host,
                        bull_host=self.llama_host,
                        bear_host=self.gpu0_host,
                        risk_host=self.gpu0_host,
                        bull_model=self.debate_model,
                        bear_model=self.risk_model,
                        risk_model=self.risk_model,
                    )
                    parent = DebateEngine(llama_host=self.llama_host)
                    self.debate.set_parent_engine(parent)
                    logger.info(
                        f"Debate engine — ADIR dual-GPU (bull={self.debate_model}@GPU1, bear={self.risk_model}@GPU0)"
                    )
                else:
                    self.debate = DebateEngine(
                        llama_host=llama_host,
                        bull_model=self.debate_model,
                        bear_model=self.debate_model,
                        risk_model=self.debate_model,
                    )
                    logger.info(
                        "Debate engine enabled — fast composite (Bull/Bear/Risk) "
                        f"model={self.debate_model}"
                    )
                self.scorer = AgentScorer(state_dir)
                self.reflection = ReflectionLog(state_dir)
            except Exception as e:
                logger.warning(f"Debate engine init failed: {e}", exc_info=True)

        # ── Adapter Lifecycle ────────────────────────────────
        self.adapter_registry = None
        self.finetuned_agent = None
        self._adapter_check_cycle = 0
        try:
            from mot import AdapterRegistry

            self.adapter_registry = AdapterRegistry(state_dir)
            active = self.adapter_registry.get_active()
            if active:
                logger.info(f"Active adapter: {active.version} at {active.path}")
                # Skip in-process model load when llama-swap is available.
                # Loading a second model blocks startup and competes for VRAM.
                # Coach/ensemble will use llama-swap API instead.
                if not os.environ.get("OPENTRADER_INFERENCE", "").lower() in (
                    "in-process",
                    "finetuned",
                ):
                    logger.info(
                        "Using llama-swap for inference (set OPENTRADER_INFERENCE=in-process for local model)"
                    )
                else:
                    self._activate_finetuned_agent(active.path)
            else:
                logger.info("No active adapter — using base model via llama-swap")
        except Exception as e:
            logger.debug(f"Adapter registry init skipped: {e}")

        # ── Model Pool + Coach + Ensemble (multi-agent) ─────────
        # Init AFTER debate engine so we can route coach/ATDL calls through
        # the debate engine's _call_agent (llama-swap API).
        self.pool = None
        self.coach = None
        self.ensemble = None
        self.atdl = None
        self._coach_cycle_counter = 0
        self._coach_review_interval = 100  # review every ~100 cycles
        self.trader_md = TraderMD(state_dir)  # self-writing trading knowledge base
        if use_model and self.debate is not None:
            try:
                from mot.coach import TrainingCoach
                from mot.lifecycle import ATDL

                class _ApiPool:
                    """Routes coach/ensemble LLM calls through debate engine's llama-swap API."""

                    def __init__(self, debate):
                        self._debate = debate

                    def generate(
                        self,
                        adapter_name=None,
                        system_prompt=None,
                        user_prompt=None,
                        max_tokens=300,
                        temperature=0.5,
                        json_output=False,
                    ):
                        prompt = user_prompt or system_prompt or ""
                        sys = system_prompt if user_prompt else ""
                        if not prompt:
                            return None
                        full_prompt = f"{sys}\n\n{prompt}" if sys else prompt
                        result = self._debate._call_agent(
                            "", full_prompt, str(adapter_name or self.debate_model)
                        )
                        if json_output and isinstance(result, dict):
                            import json

                            return json.dumps(result)
                        if isinstance(result, dict):
                            return str(
                                result.get(
                                    "response", result.get("content", str(result))
                                )
                            )
                        if isinstance(result, str):
                            return result
                        return None

                    def load_adapter(self, name, path):
                        return True

                self.pool = _ApiPool(self.debate)
                self.coach = TrainingCoach(
                    pool=self.pool,
                    model_adapter=self.debate_model,
                    state_dir=str(state_dir),
                    review_interval=self._coach_review_interval,
                )
                self.atdl = ATDL(
                    pool=self.pool,
                    coach=self.coach,
                    state_dir=str(state_dir),
                )
                logger.info(
                    f"Coach + ATDL initialized via llama-swap "
                    f"(phase={self.atdl.phase.name})"
                )
            except Exception as e:
                logger.warning(f"Coach/ATDL init failed: {e}")
                self.coach = None
                self.atdl = None

    def _activate_finetuned_agent(self, adapter_path: str) -> None:
        """Load a fine-tuned adapter into the in-process HF agent."""
        try:
            from mot import FineTunedAgent

            self.finetuned_agent = FineTunedAgent(
                adapter_path=adapter_path,
                base_model=FineTunedAgent.DEFAULT_BASE_MODEL,
                load_in_4bit=False,
            )
            ok = self.finetuned_agent.ensure_loaded()
            if ok:
                logger.info(f"FineTunedAgent activated with adapter: {adapter_path}")
                self.debate.set_finetuned_backend(self.finetuned_agent)
            else:
                logger.warning("FineTunedAgent failed to load; using llama-swap")
                self.finetuned_agent = None
        except Exception as e:
            logger.warning(f"FineTunedAgent activation failed: {e}")
            self.finetuned_agent = None

    def _check_adapter_lifecycle(self) -> None:
        """Check for new adapters and manage lifecycle transitions.

        Called every N cycles from the main loop.
        """
        if self.adapter_registry is None:
            return

        # Check if finetune completed with a new adapter
        try:
            from training.finetune_cycle import read_status

            status = read_status(self.state_dir)
            if status.get("status") == "completed":
                version = status.get("version", "")
                if version and self.adapter_registry.get(version):
                    record = self.adapter_registry.get(version)
                    # If pending and not yet activated, consider promoting
                    if record and record.status == "pending":
                        active = self.adapter_registry.get_active()
                        if active is None or self.mot_coordinator_should_promote():
                            self.adapter_registry.promote(version)
                            self._activate_finetuned_agent(record.path)
                            logger.info(f"Auto-promoted adapter: {version}")
        except Exception as e:
            logger.debug(f"Adapter lifecycle check error: {e}")

    def mot_coordinator_should_promote(self) -> bool:
        """Check if MoT coordinator recommends promoting a pending adapter.

        Requires: MoT score < 0.3 AND new adapter's eval_score >= active's eval_score.
        This prevents promoting untested or worse-scoring adapters.
        """
        try:
            if self.mot_coordinator and self.mot_coordinator.state.current_score < 0.3:
                active = self.adapter_registry.get_active()
                if active is None:
                    return True  # first adapter, no comparison needed
                # Check if any pending adapter has a valid eval score that beats active
                pending = [
                    r
                    for r in self.adapter_registry.list_adapters()
                    if r.status == "pending"
                ]
                for p in pending:
                    if p.eval_score > 0 and p.eval_score >= active.eval_score:
                        logger.info(
                            f"Auto-promote: {p.version} (eval={p.eval_score:.4f}) "
                            f"beats {active.version} (eval={active.eval_score:.4f})"
                        )
                        return True
                logger.info(
                    f"Auto-promote blocked: no pending adapter with eval_score "
                    f">= {active.eval_score:.4f}"
                )
        except Exception:
            pass
        return False

    def _adapter_update_performance(self, signal, order_result) -> None:
        """Update active adapter performance metrics."""
        if self.adapter_registry is None:
            return
        active = self.adapter_registry.get_active()
        if not active:
            return

        win_rate = None
        avg_return = None
        if order_result and isinstance(order_result, dict):
            if order_result.get("status") == "filled":
                if signal.action == "SELL":
                    # Approximate return: use confidence as proxy
                    avg_return = signal.confidence * 0.02 - 0.005
                    win_rate = 1.0 if avg_return > 0 else 0.0

        self.adapter_registry.update_performance(
            version=active.version,
            win_rate=win_rate,
            avg_return=avg_return,
            avg_confidence=signal.confidence if signal else None,
        )

    def _load_backtest_data(self, symbol: str, count: int = 1000):
        """Pre-load historical bars from CCXT for backtesting."""
        logger.info(f"Loading {count} historical bars for {symbol} backtest...")
        try:
            from exchange.live import fetch_historical_bars

            bars = fetch_historical_bars(
                symbol=symbol,
                timeframe=self.timeframe,
                count=count,
                exchange_id="coinbase",
            )
            self.exchange.load_bars(symbol, bars)
            self._backtest_max_bars = len(bars)
            logger.info(f"Loaded {len(bars)} historical bars from Coinbase")
        except Exception as e:
            logger.warning(f"Failed to load backtest data: {e}. Using synthetic.")
            bars = generate_bars(
                symbol=symbol,
                count=count,
                seed=42,
                start_price=50000.0,
                timeframe=self.timeframe,
            )
            self.exchange.load_bars(symbol, bars)
            self._backtest_max_bars = len(bars)

    def _check_llama(self, host: str = None) -> bool:
        """Check if llama-swap is available."""
        try:
            from urllib.request import urlopen

            url = (host or self.llama_host).rstrip("/") + "/v1/models"
            with urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                models = data.get("data", [])
                logger.info(f"llama-swap available: {len(models)} models")
                return True
        except Exception as e:
            logger.warning(f"llama-swap not available: {e}. Using heuristic fallback.")
            return False

    def _agent_state_path(self) -> str:
        return os.path.join(self.state_dir, "agent_state.json")

    @staticmethod
    def _fill_key(fill: dict) -> tuple:
        """Composite identity for a fill — order_id is optional and may be
        absent, so dedup on (timestamp, symbol, side, quantity, price)."""
        return (
            fill.get("timestamp", ""),
            fill.get("symbol", ""),
            (fill.get("side") or "").lower(),
            fill.get("quantity", 0),
            fill.get("price", 0),
        )

    def _append_fills_to_ledger(self, fills: list) -> None:
        """Append fills not yet in the append-only ledger (fsync'd).

        Dedup is by composite key (timestamp, symbol, side, quantity, price) —
        real fills carry no order_id, so the old order_id check was a no-op.
        """
        if not fills:
            return
        try:
            existing_keys = set()
            if os.path.exists(self._fills_ledger_path):
                with open(self._fills_ledger_path) as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                existing_keys.add(self._fill_key(json.loads(line)))
                            except (json.JSONDecodeError, AttributeError):
                                pass
            new_fills = [f for f in fills if self._fill_key(f) not in existing_keys]
            if not new_fills:
                return
            with open(self._fills_ledger_path, "a") as f:
                for fill in new_fills:
                    f.write(json.dumps(fill, default=str) + "\n")
                f.flush()
                os.fsync(f.fileno())
        except Exception as e:
            logger.warning(f"Could not append fills to ledger: {e}")

    def _rebuild_fills_from_ledger(self, current_fills: list) -> list:
        """Return the fills list to restore.

        The append-only ledger is the authoritative fills source; paper_state
        fills are a derived (truncated) view. Whenever the ledger exists and
        is non-empty, replace — not merge — with the ledger content.
        """
        if not os.path.exists(self._fills_ledger_path):
            return current_fills
        try:
            ledger_fills = []
            with open(self._fills_ledger_path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            ledger_fills.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
            if ledger_fills:
                if len(ledger_fills) > len(current_fills):
                    logger.info(
                        f"Fills ledger has {len(ledger_fills)} fills vs "
                        f"{len(current_fills)} in paper_state — rebuilding from ledger"
                    )
                return ledger_fills
        except Exception as e:
            logger.warning(f"Could not read fills ledger: {e}")
        return current_fills

    def _save_agent_state(self) -> None:
        """Persist agent state to disk."""
        try:
            state = self.agent.get_state()
            state["_cycle"] = self.cycle
            state["_signal_count"] = len(self.signal_history)
            state["_peak_value"] = self.peak_value
            state["_stage"] = self.stage
            state["_stage_start"] = self.stage_start
            state["_initial_cash"] = self.initial_cash
            self._trade_journal = self._trade_journal[-500:]
            self._alerts = self._alerts[-200:]
            state["_trade_journal"] = self._trade_journal
            state["_signal_history"] = self.signal_history
            state["_committee"] = self.committee.summary()
            state["_signal_scores"] = self._signal_scores
            state["_accuracy_total"] = self._accuracy_total
            state["_accuracy_correct"] = self._accuracy_correct
            state["_sl_tp_levels"] = self._sl_tp_levels
            state["_symbol_regimes"] = self._symbol_regimes
            if self.backtest:
                state["_backtest_bar_index"] = self._backtest_bar_index
            path = self._agent_state_path()
            tmp_path = path + ".tmp"
            with open(tmp_path, "w") as f:
                json.dump(state, f, indent=2, default=str)
            os.replace(tmp_path, path)
        except Exception as e:
            logger.error(f"Could not save agent state: {e}", exc_info=True)

    def _load_agent_state(self) -> None:
        """Restore agent state from disk."""
        path = self._agent_state_path()
        if not os.path.exists(path):
            # agent_state.json absent — still restore the portfolio ledger so
            # cash/positions/fills survive restarts (root-cause fix 2026-08-30).
            self._restore_portfolio_state()
            return
        try:
            with open(path) as f:
                state = json.load(f)
            self.agent.load_state(state)
            self.cycle = state.get("_cycle", 0)
            self.peak_value = state.get("_peak_value", self.initial_cash)
            # Handle capital changes: if peak is way above current config,
            # reset it (e.g. switching from $100K paper to $100 live).
            if self.peak_value > self.initial_cash * 10:
                logger.info(
                    f"Capital changed: peak ${self.peak_value:,.0f} → reset to ${self.initial_cash:,.0f}"
                )
                self.peak_value = self.initial_cash
                self.risk.set_initial(self.initial_cash)
            # If the restored ledger's initial_cash differs from the CLI --cash
            # by more than 5%, the capital was hardcoded/rescaled — wipe the
            # per-cycle history so the equity curve starts fresh at the new
            # scale instead of showing the old account's trajectory.
            saved_cash = state.get("_initial_cash")
            if (
                saved_cash
                and abs(saved_cash - self.initial_cash) / max(abs(self.initial_cash), 1)
                >= 0.05
            ):
                try:
                    import shutil as _shutil

                    hist_dir = os.path.join(self.state_dir, "history")
                    if os.path.isdir(hist_dir):
                        _shutil.rmtree(hist_dir)
                        logger.info(
                            f"Capital rescaled ${saved_cash:,.0f}→${self.initial_cash:,.0f}: "
                            f"wiped history, equity curve starts fresh"
                        )
                except Exception as e:
                    logger.warning(f"Could not wipe history on capital change: {e}")
            self.stage = (
                self._force_stage if self._force_stage > 0 else state.get("_stage", 1)
            )
            self.stage_start = state.get("_stage_start", time.time())
            self.symbols = list(STAGES[self.stage]["symbols"])
            # Only restore _initial_cash if matching the CLI arg (prevent $100K overwriting --cash 100)
            saved_cash = state.get("_initial_cash")
            if (
                saved_cash
                and abs(saved_cash - self.initial_cash) / max(abs(self.initial_cash), 1)
                < 0.05
            ):
                self.initial_cash = saved_cash
            if self.backtest and "_backtest_bar_index" in state:
                self._backtest_bar_index = state["_backtest_bar_index"]
            if "_trade_journal" in state:
                self._trade_journal = state["_trade_journal"]
            if "_signal_history" in state:
                self.signal_history = state["_signal_history"]
            if "_symbol_regimes" in state:
                self._symbol_regimes = state["_symbol_regimes"]
            if "_signal_scores" in state:
                self._signal_scores = state["_signal_scores"]
            if "_accuracy_total" in state:
                self._accuracy_total = state["_accuracy_total"]
            if "_accuracy_correct" in state:
                self._accuracy_correct = state["_accuracy_correct"]
            if "_sl_tp_levels" in state and state["_sl_tp_levels"]:
                self._sl_tp_levels = state["_sl_tp_levels"]
            if "_committee" in state and state["_committee"]:
                self.committee.restore(state["_committee"])
            if self.cycle > 0:
                logger.info(
                    f"Restored: cycle={self.cycle} stage={self.stage} "
                    f"({STAGES[self.stage]['label']}) peak=${self.peak_value:,.2f}"
                )
        except Exception as e:
            logger.debug(f"Could not load agent state: {e}")

        # Restore portfolio state (cash, positions, cost basis) from paper_state.json
        self._restore_portfolio_state()

    def _restore_portfolio_state(self) -> None:
        """Restore exchange ledger from the last saved paper_state.json.

        Called after agent state restore so cycle/stage are already known.
        This ensures positions survive restarts, model updates, and redeployments.
        """
        paper_path = os.path.join(self.state_dir, "paper_state.json")
        if not os.path.exists(paper_path):
            return
        try:
            with open(paper_path) as f:
                saved = json.load(f)

            saved_cash = saved.get("cash")
            saved_positions = saved.get("positions", [])
            saved_fills = saved.get("fills", [])
            saved_initial = saved.get("initial_cash")

            if saved_cash is None:
                return

            # The append-only ledger is the authoritative fills source;
            # paper_state fills are a derived (truncated) view. Replace, not
            # merge — merging is what doubled fills on every restart.
            saved_fills = self._rebuild_fills_from_ledger(saved_fills)

            # Capital-rescale guard: if the CLI --cash differs significantly
            # from the saved ledger's initial_cash, the account was hardcoded
            # to a new scale (e.g. $100k paper -> $500 real). Reset the ledger
            # to the CLI cash and drop old positions — restoring a $100k
            # ledger into a $500 account would be meaningless.
            saved_initial = saved.get("initial_cash")
            if (
                saved_initial
                and abs(saved_initial - self.initial_cash)
                / max(abs(self.initial_cash), 1)
                >= 0.05
            ):
                logger.info(
                    f"Ledger rescaled ${saved_initial:,.0f}→${self.initial_cash:,.0f}: "
                    f"resetting cash, dropping old positions"
                )
                saved_cash = float(self.initial_cash)
                saved_positions = []
                saved_fills = []
                saved_initial = float(self.initial_cash)

            # Restore exchange ledger
            # Positions format: list of dicts with symbol, quantity, entry_price, current_price, etc.
            restored_positions = {}
            restored_cost_basis = {}
            restored_entries = {}
            for p in saved_positions:
                sym = p.get("symbol", "")
                qty = float(p.get("quantity", 0) or 0)
                entry = float(p.get("entry_price", 0) or p.get("current_price", 0) or 0)
                if sym and qty > 0 and entry > 0:
                    restored_positions[sym] = qty
                    restored_entries[sym] = entry

            # Reconstruct cost basis by replaying fills chronologically,
            # mirroring the live exchange logic: BUY adds cost, SELL reduces
            # it proportionally by the realized average entry.
            fills_sorted = sorted(
                saved_fills,
                key=lambda f: f.get("timestamp", ""),
            )
            replay_positions = {}
            replay_cost = {}
            for f in fills_sorted:
                sym = f.get("symbol", "")
                side = (f.get("side") or "").lower()
                qty = float(f.get("quantity", 0) or 0)
                cost = float(f.get("cost", 0) or 0)
                if not sym or qty <= 0:
                    continue
                if side == "buy":
                    replay_positions[sym] = replay_positions.get(sym, 0) + qty
                    replay_cost[sym] = replay_cost.get(sym, 0) + cost
                elif side == "sell":
                    pos = replay_positions.get(sym, 0)
                    if pos > 0:
                        sell_qty = min(qty, pos)
                        avg_entry = replay_cost.get(sym, 0) / max(pos, 1e-12)
                        replay_positions[sym] = pos - sell_qty
                        replay_cost[sym] = max(
                            0.0, replay_cost.get(sym, 0) - avg_entry * sell_qty
                        )
                        if replay_positions[sym] <= 0:
                            replay_positions.pop(sym, None)
                            replay_cost.pop(sym, None)
            restored_cost_basis = replay_cost

            # Fill cost-basis gaps with the saved entry price (fills are
            # truncated to the last 50, so old positions may lack fills).
            for sym, qty in restored_positions.items():
                if sym not in restored_cost_basis and sym in restored_entries:
                    restored_cost_basis[sym] = restored_entries[sym] * qty

            # Route the restore through a per-exchange restore_ledger() so it
            # reaches the attrs get_balance() actually reads. The old direct
            # writes (_cash/_positions/_cost_basis) silently no-op'd on
            # alpaca-paper (uses cash/positions) and multi-router (child
            # ledgers) — the book reverted to init cash on every restart.
            if hasattr(self.exchange, "restore_ledger"):
                self.exchange.restore_ledger(
                    saved_cash, restored_positions, restored_cost_basis, saved_fills
                )
            else:
                self.exchange._cash = saved_cash
                self.exchange._positions = restored_positions
                self.exchange._cost_basis = restored_cost_basis
                if hasattr(self.exchange, "_fills"):
                    self.exchange._fills = saved_fills

            # Restore trade journal so coach/ATDL see historical trades on restart
            # Only use paper_state as fallback when agent_state didn't have the journal.
            # agent_state.json persists the full journal every cycle via _save_agent_state();
            # paper_state.json only stores the last N trades for dashboard display.
            saved_trades = saved.get("trades", [])
            if saved_trades and not self._trade_journal:
                self._trade_journal = saved_trades
                logger.info(
                    f"Trade journal restored from paper_state: {len(saved_trades)} historical trades"
                )

            # Update initial_cash and risk manager baseline
            if saved_initial and saved_initial > 0:
                if (
                    abs(saved_initial - self.initial_cash)
                    / max(abs(self.initial_cash), 1)
                    < 0.05
                ):
                    self.initial_cash = saved_initial
                    self.risk.set_initial(saved_initial)
                else:
                    logger.warning(
                        f"paper_state initial_cash ${saved_initial:,.2f} differs significantly from config ${self.initial_cash:,.2f} — using config value"
                    )
                # Reconcile risk._peak_value with the restored high-water mark.
                # set_initial() resets _peak_value to saved_initial; if the portfolio
                # had grown past initial before the restart, the circuit breaker would
                # otherwise measure drawdown from the wrong reference point.
                self.risk.update_peak(self.peak_value)

            # Recalculate portfolio value + ASSERT the restore landed in the
            # real ledger (the old log fired off saved data, not the exchange
            # book, so a no-op restore reported success). get_balance().cash
            # must reflect saved_cash or the restore silently failed.
            bal = self.exchange.get_balance()
            _cash_ok = abs(bal.cash - saved_cash) <= max(1.0, abs(saved_cash) * 1e-6)
            if not _cash_ok:
                logger.error(
                    f"Portfolio restore FAILED verification: get_balance().cash="
                    f"${bal.cash:,.2f} != saved ${saved_cash:,.2f} "
                    f"(exchange={self.exchange.name}) — book may have reverted to init"
                )
            if _cash_ok and bal.total_value > 0 and restored_positions:
                logger.info(
                    f"Portfolio restored: ${bal.total_value:,.2f} "
                    f"({len(restored_positions)} positions, ${saved_cash:,.2f} cash)"
                )
            # Add restored position symbols to active symbols so they get SL/TP tracking
            for sym in restored_positions:
                if sym not in self.symbols:
                    logger.info(
                        f"Resurrecting {sym} from saved state (not in current stage)"
                    )
                    self.symbols.append(sym)

            # Re-establish SL/TP guardrails for restored positions
            for p in saved_positions:
                sym = p.get("symbol", "")
                qty = float(p.get("quantity", 0) or 0)
                current = float(p.get("current_price", 0) or 0)
                # Prefer cost-basis-derived entry (replay is accurate); fall
                # back to the saved entry only if cost basis is unavailable.
                cb = restored_cost_basis.get(sym, 0)
                entry = (
                    cb / qty
                    if sym in restored_cost_basis and qty > 0 and cb > 0
                    else float(p.get("entry_price", 0) or current or 0)
                )
                if sym and qty > 0 and entry > 0:
                    risk_cfg = self.risk.config
                    bars_raw = (
                        self.exchange.get_bars(sym, self.timeframe, 80)
                        if hasattr(self.exchange, "get_bars")
                        else []
                    )
                    atr = self._compute_atr_14(bars_raw) if bars_raw else 0.0
                    atr_mult = 3.0
                    if atr > 0 and not getattr(self, "_runway_mode", False):
                        sl_atr = entry - (atr * atr_mult)
                        tp_atr = entry + (atr * atr_mult * 2)
                    else:
                        sl_atr = round(entry * (1 - risk_cfg.stop_loss_pct), 2)
                        tp_atr = round(entry * (1 + risk_cfg.take_profit_pct), 2)
                    self._sl_tp_levels[sym] = {
                        "stop_loss": sl_atr,
                        "take_profit": tp_atr,
                        "entry_price": entry,
                        "qty": qty,
                        "highest_price": max(entry, current),
                        "cycle_opened": p.get("cycle_opened", self.cycle),
                        "exit_date": self._hold_exit_date(sym) if getattr(self, "_runway_mode", False) else None,
                        "trailing_stop_pct": risk_cfg.trailing_stop_pct,
                        "trailing_activation": risk_cfg.trailing_stop_activation,
                        "max_position_cycles": risk_cfg.max_position_cycles,
                        "position_stop_pct": risk_cfg.position_stop_pct,
                        "atr": atr,
                        "atr_mult": atr_mult if atr > 0 else 0,
                    }
        except Exception as e:
            logger.warning(f"Could not restore portfolio: {e}")

    def _score_prediction(self, symbol: str, action: str, pnl: float):
        """Score a debate prediction against actual outcome for model accuracy."""
        key = f"{symbol}:{action}"
        e = self._signal_scores.setdefault(
            key, {"correct": 0, "total": 0, "symbol": symbol, "action": action}
        )
        e["total"] += 1
        self._accuracy_total += 1
        is_correct = (
            (action == "BUY" and pnl > 0)
            or (action == "SELL" and pnl > 0)
            or (action == "HOLD" and abs(pnl) < 0.005)
        )
        if is_correct:
            e["correct"] += 1
            self._accuracy_correct += 1

    def _get_fear_greed(self) -> dict:
        """Extract Fear & Greed index from news cache."""
        default = {"value": 50, "classification": "unknown"}
        try:
            cache = getattr(self, "_news_cache", None)
            if cache and isinstance(cache, dict):
                fg = cache.get("sources", {}).get("fear_greed", {})
                if fg:
                    return {
                        "value": fg.get("value", 50),
                        "classification": fg.get("classification", "neutral"),
                    }
        except Exception:
            pass
        return default

    def _signal_accuracy_summary(self) -> dict:
        """Model accuracy stats for dashboard. Uses running counters for O(1) overall, rebuilds by_action on demand."""
        by_action = {}
        for v in self._signal_scores.values():
            acc = round(v["correct"] / max(v["total"], 1) * 100, 1)
            by_action[v["action"]] = {
                "correct": v["correct"],
                "total": v["total"],
                "accuracy_pct": acc,
            }
        return {
            "overall_accuracy_pct": round(
                self._accuracy_correct / max(self._accuracy_total, 1) * 100, 1
            ),
            "total_predictions": self._accuracy_total,
            "total_correct": self._accuracy_correct,
            "by_action": by_action,
        }

    def _load_optimal_params(self, portfolio_value: float) -> dict:
        """Load optimized risk parameters for the current portfolio scale.

        Reads data/param_opt/params.json and interpolates between
        the two nearest portfolio scales. Returns empty dict if
        optimization data is unavailable. Caches by mtime.
        """
        import json
        import os
        from pathlib import Path as _Path

        param_file = _Path(PROJECT) / "data" / "param_opt" / "params.json"
        if not param_file.exists():
            return {}
        try:
            # Check mtime for cache invalidation
            current_mtime = os.path.getmtime(param_file)
            if self._params_cache is not None and current_mtime == self._params_mtime:
                data = self._params_cache
            else:
                data = json.loads(param_file.read_text())
                self._params_cache = data
                self._params_mtime = current_mtime
            scales = data.get("scales", {})
            if not scales:
                return {}
            # Sort scales by portfolio value
            sorted_scales = sorted(scales.items(), key=lambda x: float(x[0]))
            # If below smallest scale, use smallest
            if portfolio_value <= float(sorted_scales[0][0]):
                best = sorted_scales[0][1]
            # If above largest scale, use largest
            elif portfolio_value >= float(sorted_scales[-1][0]):
                best = sorted_scales[-1][1]
            else:
                # Linear interpolation between two nearest scales
                for i in range(len(sorted_scales) - 1):
                    lo_val = float(sorted_scales[i][0])
                    hi_val = float(sorted_scales[i + 1][0])
                    if lo_val <= portfolio_value <= hi_val:
                        lo_params = sorted_scales[i][1]
                        hi_params = sorted_scales[i + 1][1]
                        frac = (portfolio_value - lo_val) / (hi_val - lo_val)
                        best = {}
                        for key in lo_params:
                            if key not in hi_params:
                                best[key] = lo_params[key]
                                continue
                            lv, hv = lo_params[key], hi_params[key]
                            if isinstance(lv, (int, float)) and isinstance(
                                hv, (int, float)
                            ):
                                best[key] = lv + frac * (hv - lv)
                            else:
                                best[key] = lv
                        break
                else:
                    best = sorted_scales[0][1]  # fallback
            return best
        except Exception:
            logger.debug(f"Optimal param load failed for {portfolio_value}")
            return {}

    @staticmethod
    def _load_config() -> dict:
        """Load centralized harness config from config/harness_config.json."""
        config_path = Path(__file__).resolve().parent / "config" / "harness_config.json"
        if config_path.exists():
            try:
                with open(config_path) as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _start_price(self, symbol: str) -> float:
        """Return a reasonable starting price for synthetic data."""
        if symbol in DEFAULT_START_PRICES:
            return DEFAULT_START_PRICES[symbol]
        return 100.0

    def _check_progression(self) -> Optional[int]:
        """Check if we should advance to the next stage.

        Returns new stage number if unlocked, None otherwise.
        """
        if self._force_stage > 0:
            return None  # stage is forced, skip progression
        if self.stage >= MAX_STAGE:
            return None
        cfg = STAGES[self.stage]
        hours = (time.time() - self.stage_start) / 3600.0
        bal = self.exchange.get_balance()
        return_pct = (bal.total_value / max(self.initial_cash, 1) - 1.0) * 100.0

        if hours >= cfg["unlock_hours"] and return_pct >= cfg["unlock_return_pct"]:
            self.stage += 1
            self.stage_start = time.time()
            self.symbols = list(STAGES[self.stage]["symbols"])
            new_label = STAGES[self.stage]["label"]
            new_syms = self.symbols
            logger.info(
                f"━━━ STAGE {self.stage} UNLOCKED ━━━ "
                f"{new_label}: {new_syms} "
                f"(after {hours:.1f}h, {return_pct:+.1f}%)"
            )
            # Pre-load data for new symbols
            if self.synthetic_data:
                for sym in new_syms:
                    existing = self.exchange.get_bars(sym, limit=1)
                    if not existing:
                        bars = generate_bars(
                            symbol=sym,
                            count=self.synthetic_bars,
                            seed=self.synthetic_seed,
                            start_price=self._start_price(sym),
                            timeframe=self.timeframe,
                        )
                        self.exchange.load_bars(sym, bars)
                        logger.info(f"Pre-loaded {len(bars)} bars for new symbol {sym}")
            return self.stage
        return None

    def _push_new_bar(self, symbol: str = None) -> bool:
        """Generate and push a new bar for a symbol. Uses self.symbols[0] if no symbol."""
        sym = symbol or (self.symbols[0] if self.symbols else self.symbol)
        if self.backtest:
            bars = self.exchange.get_bars(sym, limit=99999)
            if not bars:
                return False
            self._backtest_bar_index += 1
            idx = self._backtest_bar_index
            if idx >= len(bars):
                logger.info(f"Backtest: reached end of data ({len(bars)} bars)")
                self.running = False
                return False
            # Push the next bar to make it "current"
            bar = bars[idx]
            self.exchange.push_bar(
                sym,
                {
                    "timestamp": bar.timestamp,
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                },
            )
            return True
        try:
            # Pull last real-ish bar for continuity
            bars = self.exchange.get_bars(sym, limit=10)
            if bars:
                last_price = bars[-1].close
            else:
                last_price = self.initial_cash

            bar = generate_bars(
                symbol=sym,
                count=1,
                start_price=last_price,
                volatility=0.02,
                trend=0.0,
                timeframe=self.timeframe,
                seed=None,
            )
            if bar:
                self.exchange.push_bar(sym, bar[0])
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to push bar: {e}")
            return False

    def _check_sl_tp(self) -> List[dict]:
        """Check open positions against all exit guardrails.

        Triggers:
          - Hard stop-loss (price <= fixed SL)
          - Take-profit (price >= fixed TP)
          - Trailing stop (price drops N% below highest seen)
          - Max-time-in-trade (position held > max_position_cycles)
          - Per-position drawdown (price drops > position_stop_pct below entry)

        Returns a list of forced-close order results.
        """
        forced_closes = []
        symbols_to_close = []
        cfg = self.risk.config  # type: RiskConfig

        for sym, levels in list(self._sl_tp_levels.items()):
            price = self.exchange.get_current_price(sym)
            if not price:
                # Unpriceable holding: every exit below this line would fire on a
                # garbage/absent price. Track the streak and quarantine rather
                # than silently skipping forever (zombie-position bug, BALY 2026-08).
                streak = self._unpriceable_streak.get(sym, 0) + 1
                self._unpriceable_streak[sym] = streak
                if streak == UNPRICEABLE_QUARANTINE_CYCLES:
                    in_universe = sym in getattr(self, "symbols", [])
                    reason = (
                        f"no usable price for {streak} cycles"
                        + ("" if in_universe else " AND off-universe")
                    )
                    self._quarantined[sym] = reason
                    logger.critical(
                        f"QUARANTINE {sym}: {reason}. Position frozen — no "
                        f"SL/TP/timeout exit will fire on a priceless feed. "
                        f"Resolve manually via scripts/retire_position.py in a "
                        f"maintenance window."
                    )
                continue
            if sym in self._quarantined:
                logger.warning(
                    f"{sym}: price restored (${price:.2f}) — lifting quarantine"
                )
                del self._quarantined[sym]
            self._unpriceable_streak[sym] = 0

            entry_price = levels.get("entry_price", price)
            sl = levels.get("stop_loss")
            tp = levels.get("take_profit")
            highest = levels.get("highest_price", entry_price)
            cycle_opened = levels.get("cycle_opened") or self.cycle
            trailing_pct = levels.get("trailing_stop_pct", cfg.trailing_stop_pct)

            triggered = False
            reason = ""

            # Update highest price seen (for trailing stop)
            if price > highest:
                highest = price
                levels["highest_price"] = highest

            # ── 1. Hard stop-loss ───────────────────────────
            if not triggered and sl and price <= sl:
                triggered = True
                reason = f"stop-loss: ${price:.2f} <= ${sl:.2f}"

            # ── 2. Take-profit ─────────────────────────────
            if not triggered and tp and price >= tp:
                triggered = True
                reason = f"take-profit: ${price:.2f} >= ${tp:.2f}"

            # ── 3. Trailing stop (only after activation threshold) ─
            if (
                not triggered
                and trailing_pct > 0
                and price < highest * (1 - trailing_pct)
            ):
                # Check activation: trailing only engages after profit > activation%
                profit_from_entry = (
                    (highest - entry_price) / entry_price if entry_price > 0 else 0
                )
                act_pct = levels.get(
                    "trailing_activation", cfg.trailing_stop_activation
                )
                if profit_from_entry >= act_pct:
                    triggered = True
                    reason = (
                        f"trailing-stop: ${price:.2f} "
                        f"({trailing_pct:.1%} below high ${highest:.2f})"
                    )

            # ── 4. Max-time-in-trade ────────────────────────
            # RUNWAY: date-based 14-trading-day hold (validated max_hold).
            exit_date = levels.get("exit_date")
            if not triggered and exit_date is not None:
                try:
                    from datetime import datetime as _dt
                    if _dt.now(timezone.utc).date() >= _dt.strptime(exit_date, "%Y-%m-%d").date():
                        triggered = True
                        reason = f"timeout: held past {exit_date} (14d max-hold)"
                except Exception:
                    pass
            max_cycles = levels.get("max_position_cycles", cfg.max_position_cycles)
            if not triggered and max_cycles > 0:
                age = self.cycle - cycle_opened
                if age >= max_cycles:
                    triggered = True
                    reason = f"timeout: held {age} cycles (max={max_cycles})"

            # ── 5. Per-position drawdown ─────────────────────
            pos_dd_pct = levels.get("position_stop_pct", cfg.position_stop_pct)
            if not triggered and pos_dd_pct > 0 and entry_price > 0:
                dd = (entry_price - price) / entry_price
                if dd >= pos_dd_pct:
                    triggered = True
                    reason = f"position-drawdown: {dd:.1%} >= {pos_dd_pct:.1%}"

            # ── Execute if triggered ─────────────────────────
            if triggered:
                logger.info(f"  {sym}: {reason}")
                pos = self.exchange.get_balance().positions.get(sym, 0)
                if float(pos) > 0:
                    try:
                        order = self.exchange.place_order(
                            sym, "SELL", float(pos), "market"
                        )
                        forced_closes.append(
                            {
                                "symbol": sym,
                                "side": "SELL",
                                "quantity": float(pos),
                                "price": price,
                                "entry_price": entry_price,
                                "reason": reason,
                                "order_id": order.order_id,
                                "status": order.status,
                            }
                        )
                        logger.info(f"  {sym}: auto-closed — {order.status}")

                        # ── Resolve reflection ──────────────
                        if self.reflection and entry_price > 0:
                            pnl_pct = (price - entry_price) / entry_price
                            self.reflection.update_outcome("BUY", pnl_pct)
                            logger.info(
                                f"  Reflection resolved: BUY on {sym} → {pnl_pct:+.4%}"
                            )

                        # ── MoT router monitor (runway: rule floor records) ──
                        # Live attribution is MONITORING only — the arena's
                        # held-out gate is the edge evidence; the router needs
                        # years of live data to shift weight. Record anyway so
                        # live_router_state.json accrues the rule baseline.
                        if entry_price > 0:
                            self._record_router_impact(sym, entry_price, price)

                        # ── Record to trade journal ────────
                        if entry_price > 0:
                            pnl_pct = (price - entry_price) / entry_price
                            pos_qty = float(
                                pos
                            )  # use actual sold qty, not potentially stale SL/TP stored qty
                            notional = pos_qty * entry_price
                            rt_fee = self.exchange.get_fee_schedule(
                                sym
                            ).round_trip_cost(notional)
                            pnl_dollar = pnl_pct * notional - rt_fee
                            pnl_pct = pnl_dollar / notional if notional > 0 else 0
                            self._trade_journal.append(
                                {
                                    "symbol": sym,
                                    "entry_price": round(entry_price, 2),
                                    "exit_price": round(price, 2),
                                    "quantity": round(pos_qty, 8),
                                    "pnl_pct": round(pnl_pct, 4),
                                    "pnl_dollar": round(pnl_dollar, 2),
                                    "fees_paid": round(rt_fee, 2),
                                    "entry_cycle": self._sl_tp_levels.get(sym, {}).get(
                                        "cycle_opened", self.cycle
                                    ),
                                    "exit_cycle": self.cycle,
                                    "duration_cycles": self.cycle
                                    - self._sl_tp_levels.get(sym, {}).get(
                                        "cycle_opened", self.cycle
                                    ),
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                    "exit_reason": reason,
                                }
                            )
                            logger.info(
                                f"  Trade closed [{sym}]: PnL={pnl_pct:+.4%} ({reason})"
                            )
                            # Score: skip zero-PnL flip-flops (no skill), only score meaningful outcomes
                            if abs(pnl_pct) > 0.0001:
                                self._score_prediction(sym, "BUY", pnl_pct)
                                self.committee.record_outcome(sym, "BUY", pnl_pct > 0)
                            # Add alert for dashboard
                            self._alerts.append(
                                {
                                    "type": "guardrail",
                                    "symbol": sym,
                                    "reason": reason,
                                    "pnl_pct": round(pnl_pct, 4),
                                    "pnl_dollar": round(
                                        pnl_pct * (pos_qty * entry_price), 2
                                    ),
                                    "cycle": self.cycle,
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                }
                            )

                    except Exception as e:
                        logger.error(f"  auto-close failed {sym}: {e}")
                symbols_to_close.append(sym)

        # Clean up closed positions from tracking
        for sym in symbols_to_close:
            if sym in self._sl_tp_levels:
                pos = self.exchange.get_balance().positions.get(sym, 0)
                if float(pos) <= 0:
                    del self._sl_tp_levels[sym]

        return forced_closes

    def _record_state(self, signal: Signal, order_result: dict = None) -> dict:
        """Record cycle state to disk."""
        bal = self.exchange.get_balance()

        # Update equity curve (capped to bound RAM — ~5.5h at 10s/cycle)
        self.equity_curve.append(bal.total_value)
        if len(self.equity_curve) > 2000:
            del self.equity_curve[:-2000]
        if bal.total_value > self.peak_value:
            self.peak_value = bal.total_value
        dd = (
            (self.peak_value - bal.total_value) / self.peak_value
            if self.peak_value > 0
            else 0
        )
        self.drawdowns.append(dd)
        if len(self.drawdowns) > 2000:
            del self.drawdowns[:-2000]

        # Build positions list
        prices = {}
        for sym in list(bal.positions.keys()):
            p = self.exchange.get_current_price(sym)
            if p:
                prices[sym] = p

        positions_list = []
        for sym, qty in (bal.positions or {}).items():
            if float(qty) <= 0:
                continue
            p = prices.get(sym, 0)
            guard = self._sl_tp_levels.get(sym, {})
            entry = guard.get("entry_price")
            if not entry:
                cost = getattr(self.exchange, "_cost_basis", {}).get(sym, 0)
                if cost and float(qty) > 0:
                    entry = cost / float(qty)
                else:
                    entry = p
            positions_list.append(
                {
                    "symbol": sym,
                    "quantity": round(float(qty), 8),
                    "current_price": p,
                    "entry_price": entry,
                    "stop_loss": guard.get("stop_loss"),
                    "take_profit": guard.get("take_profit"),
                    "highest_price": guard.get("highest_price"),
                    "cycle_opened": guard.get("cycle_opened"),
                }
            )

        # Get fills
        fills = []
        if hasattr(self.exchange, "get_fills"):
            fills = self.exchange.get_fills()

        # Append new fills to the append-only ledger (crash-safe, fsync'd)
        self._append_fills_to_ledger(fills)

        # (Signal history is recorded per-symbol in Phase 1.5 of run_cycle)

        # Risk update
        self.risk.update_peak(bal.total_value)

        # Write state — skip per-cycle history file if nothing meaningful changed
        cycle_time = self._last_cycle_time or 0

        _raw_state = {
            "portfolio_value": bal.total_value,
            "cash": bal.cash,
            "positions": positions_list,
            "fills": fills,
            "trades": self._trade_journal[-5:],
            "signals": self.signal_history,
            "Committee": self.committee.summary(),
        }
        state_key = StateManager.state_key(_raw_state)
        skip_history = (
            self._last_state_key is not None and state_key == self._last_state_key
        )
        self._last_state_key = state_key

        state = self.state_mgr.write(
            cycle=self.cycle,
            portfolio={
                "cash": bal.cash,
                "total_value": bal.total_value,
                "positions": bal.positions or {},
            },
            positions=positions_list,
            fills=fills,
            prices=prices,
            regime=signal.meta if signal.meta else {},
            symbol_regimes=self._symbol_regimes,
            signals=self.signal_history,
            models={
                "agent": self.agent.name,
                "stage": self.stage,
                "symbols": self.symbols,
                "llama_available": bool(getattr(self, "_llama_available", False)),
                "llama_host": self.llama_host,
                "debate_model": self.debate_model,
            },
            fundamentals_coverage=dict(self._fundamentals_coverage),
            data_provenance={
                "mode": "live" if self.live_mode else "synthetic",
                "exchange": getattr(self.exchange, "name", ""),
                "synthetic_data": bool(self.synthetic_data),
                "note": (
                    "Real market prices (kraken crypto + finnhub stocks) — "
                    "paper settlement."
                    if not self.synthetic_data and self.live_mode
                    else "SYNTHETIC random-walk prices — NOT real market data."
                ),
            },
            metrics={
                "cycle_time_s": round(cycle_time, 3),
                "total_cycles": self.cycle,
                "total_fills": len(fills) if fills else 0,
                "drawdown_pct": round(dd * 100, 2),
                "peak_value": round(self.peak_value, 2),
                "stage": self.stage,
                "symbol_count": len(self.symbols),
                "fear_greed": self._get_fear_greed(),
                "signal_accuracy": self._signal_accuracy_summary(),
            },
            portfolio_metrics=signal.meta.get("portfolio", {}) if signal.meta else {},
            initial_cash=self.initial_cash,
            trades=self._trade_journal[-50:],
            alerts=self._alerts[-20:],
            hodl_benchmark=self._compute_hodl_benchmark(),
            committee=self.committee.summary(),
            skip_history=skip_history,
        )

        # ── Persist agent state (including trade journal) ──────────────
        # FIX (trade_journal_empty): Persist the full journal after every cycle.
        # Previously, _save_agent_state() only ran at __init__, so the journal
        # appended here at line 1109 was never written to disk.
        self._save_agent_state()

        # ── Per-symbol parameter optimization (every 50 cycles) ──
        # RUNWAY: disabled under --pin-risk (same reason as the 100-cycle block).
        if not getattr(self, "_pin_risk", False) and self.cycle % 50 == 0 and self.cycle > 0 and self._trade_journal:
            try:
                from risk.param_optimizer import run_cycle as run_param_cycle

                run_param_cycle(self.state_mgr.state_dir, self.cycle)
            except Exception:
                pass

        # ── DPO training data builder (every 5000 cycles, needs 50+ new closed trades) ──
        if self.cycle % 5000 == 0 and self.cycle > 0:
            last_dpo = getattr(self, "_last_dpo_cycle", 0)
            new_closed = len(self._trade_journal) - getattr(
                self, "_last_dpo_trade_count", 0
            )
            if new_closed >= 50:
                try:
                    from training.dpo_builder import build_dpo_dataset

                    build_dpo_dataset(self.state_mgr.state_dir)
                    self._last_dpo_cycle = self.cycle
                    self._last_dpo_trade_count = len(self._trade_journal)
                    logger.info(
                        f"DPO dataset rebuilt at cycle {self.cycle} ({new_closed} new trades)"
                    )
                except Exception:
                    logger.debug("DPO builder skipped (not enough data or error)")
                    pass

        # Write high-level state for the dashboard regime panel
        port_meta = (signal.meta or {}).get("portfolio", {})
        high_portfolio = {}
        if port_meta:
            high_portfolio = {
                "diversification_ratio": port_meta.get("diversification_ratio", 0),
                "portfolio_var": port_meta.get("portfolio_var", 0),
                "total_exposure_pct": port_meta.get("total_exposure_pct", 0),
                "kelly_fractions": port_meta.get("kelly_fractions", {}),
            }
        self.state_mgr.write_high_level(
            regime=signal.action,
            confidence=signal.confidence,
            thesis=signal.reason,
            posture="offensive" if signal.action == "BUY" else "defensive",
            available=True,
            portfolio=high_portfolio,
        )

        return state

    def _compute_hodl_benchmark(self) -> dict:
        """Compute buy-and-hold benchmark for performance comparison."""
        bench = {"enabled": False, "value": 0, "return_pct": 0, "outperform_pct": 0}
        try:
            bars = self.exchange.get_bars(self.symbols[0], self.timeframe, limit=5000)
            if not bars or len(bars) < 2:
                return bench
            start_price = bars[0].close
            end_price = (
                bars[-1].close
                if not self.live_mode
                else self.exchange.get_current_price(self.symbols[0]) or start_price
            )
            hodl_return = (end_price / max(start_price, 1) - 1) * 100
            bal = self.exchange.get_balance()
            bot_return = (bal.total_value / max(self.initial_cash, 1) - 1) * 100
            bench["enabled"] = True
            bench["hodl_return_pct"] = round(hodl_return, 2)
            bench["bot_return_pct"] = round(bot_return, 2)
            bench["outperform_pct"] = round(bot_return - hodl_return, 2)
        except Exception:
            pass
        return bench

    def _compute_atr_14(self, bars: list) -> float:
        """Compute ATR-14 using Wilder's smoothing. Returns 0.0 if insufficient data."""
        if len(bars) < 15:
            return 0.0

        def get_val(b, key):
            return getattr(b, key, None) if not isinstance(b, dict) else b.get(key)

        highs = [get_val(b, "high") for b in bars]
        lows = [get_val(b, "low") for b in bars]
        closes = [get_val(b, "close") for b in bars]
        if any(v is None for v in highs + lows + closes):
            return 0.0

        tr_values = []
        for i in range(1, len(bars)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
            tr_values.append(tr)
        if len(tr_values) < 14:
            return 0.0

        atr = sum(tr_values[:14]) / 14
        for i in range(14, len(tr_values)):
            atr = (atr * 13 + tr_values[i]) / 14
        return atr

    @staticmethod
    def _compute_rsi(closes: list, period: int = 14) -> float:
        """Compute RSI from closing prices. Returns 50.0 if insufficient data."""
        if len(closes) < period + 1:
            return 50.0
        gains = losses = 0.0
        for i in range(1, period + 1):
            diff = closes[i] - closes[i - 1]
            if diff > 0:
                gains += diff
            else:
                losses -= diff
        avg_gain = gains / period
        avg_loss = losses / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _debate_one_symbol(
        self, sym: str, cycle: int, timeframe: str, bal: Any
    ) -> Tuple[str, "Signal", "AgentContext", Optional[dict]]:
        """Run debate for a single symbol (designed for parallel execution).

        Returns (symbol, signal, context, regime_dict) tuple.
        Thread-safe: all reads from exchange are GIL-protected,
        debate calls are independent HTTP requests.
        """
        from agent.base import AgentContext, Signal

        ctx = AgentContext(symbol=sym, timeframe=timeframe, cycle=cycle)

        # Build OHLCV context (fetch bars once, reused for regime)
        bars_raw = None
        try:
            bars_raw = self.exchange.get_bars(sym, timeframe, 80)
            # Compact multi-TF indicator summary (fits in 500-char ADIR limit)
            cur = bars_raw[-1].close if bars_raw else 0
            # 1h indicators from bars_raw
            atr = self._compute_atr_14(bars_raw) if bars_raw else 0
            # Fetch 4h and 1d for multi-TF confirmation
            rsi_1h = rsi_4h = rsi_1d = 50.0
            sma_1h = sma_4h = sma_1d = cur
            try:
                # 4h bars
                bars_4h = self.exchange.get_bars(sym, "4h", 30)
                if bars_4h and len(bars_4h) >= 14:
                    rsi_4h = self._compute_rsi([b.close for b in bars_4h])
                    sma_4h = sum(b.close for b in bars_4h[-20:]) / min(20, len(bars_4h))
                # 1d bars
                bars_1d = self._daily_bars(sym, 30)
                if bars_1d and len(bars_1d) >= 14:
                    rsi_1d = self._compute_rsi([b.close for b in bars_1d])
                    sma_1d = sum(b.close for b in bars_1d[-20:]) / min(20, len(bars_1d))
            except Exception:
                pass
            # 1h RSI
            if bars_raw and len(bars_raw) >= 14:
                rsi_1h = self._compute_rsi([b.close for b in bars_raw[-30:]])
                sma_1h = sum(b.close for b in bars_raw[-20:]) / min(20, len(bars_raw))
            # Compute recent returns
            pct_1h = (
                ((cur / bars_raw[-2].close - 1) * 100)
                if bars_raw and len(bars_raw) >= 2
                else 0
            )
            pct_4h = (
                ((cur / bars_raw[-4].close - 1) * 100)
                if bars_raw and len(bars_raw) >= 5
                else 0
            )
            ctx.ohlcv_json = (
                f"{sym} ${cur:.2f} "
                f"1h:RSI={rsi_1h:.0f} SMA={sma_1h:.2f} "
                f"4h:RSI={rsi_4h:.0f} SMA={sma_4h:.2f} "
                f"1d:RSI={rsi_1d:.0f} SMA={sma_1d:.2f} "
                f"ATR={atr:.2f} "
                f"chg={pct_1h:+.2f}%"
            )
        except Exception as e:
            ctx.ohlcv_json = f"{sym} price unavailable ({e})"

        # Typed OHLCV bars for heuristic fallback (no JSON round-trip)
        ctx.ohlcv_bars = bars_raw

        # Portfolio context (shared balance snapshot)
        try:
            # Build entry prices from SL/TP tracker
            entry_prices = {}
            for sym_pos, levels in self._sl_tp_levels.items():
                entry_prices[sym_pos] = levels.get("entry_price", 0)
            portfolio_dict = {
                "cash": bal.cash,
                "total_value": bal.total_value,
                "positions": bal.positions or {},
                "entry_price": entry_prices.get(sym, 0),
                "position_count": len(bal.positions),
            }
            ctx.portfolio_json = json.dumps(portfolio_dict)
            ctx.portfolio_dict = portfolio_dict
        except Exception as e:
            ctx.portfolio_json = json.dumps({"error": str(e)})
            ctx.portfolio_dict = {"error": str(e)}

        # Regime (per symbol) — reuse bars_raw from OHLCV fetch above
        try:
            if bars_raw and len(bars_raw) >= 20:
                bar_dicts = [
                    {
                        "open": b.open,
                        "high": b.high,
                        "low": b.low,
                        "close": b.close,
                        "volume": b.volume,
                    }
                    for b in bars_raw
                ]
                rg = classify_regime(bar_dicts)
                ctx.regime_json = json.dumps(rg)
                ctx.regime_dict = rg
            else:
                unknown_regime = {
                    "regime": "unknown",
                    "confidence": 0,
                    "thesis": "insufficient data",
                }
                ctx.regime_json = json.dumps(unknown_regime)
                ctx.regime_dict = unknown_regime
        except Exception:
            try:
                rg = self.mcp.get_regime(sym)
                ctx.regime_json = json.dumps(rg)
                ctx.regime_dict = rg
            except Exception as e:
                err_regime = {
                    "regime": "unknown",
                    "confidence": 0,
                    "thesis": f"unavailable: {e}",
                }
                ctx.regime_json = json.dumps(err_regime)
                ctx.regime_dict = err_regime

        # Economics (shared — cache per cycle to avoid 3 identical MCP calls)
        try:
            if self.cycle != self._econ_cycle:  # fetch-once-per-cycle, thread-safe
                self._econ_cycle = self.cycle
                self._econ_cache = json.dumps(self.mcp.get_economics())
            ctx.economics_json = self._econ_cache or json.dumps({"source": "pending"})
            try:
                from data.economics import fred_to_context

                ctx.fred_json = fred_to_context(json.loads(ctx.economics_json))
            except Exception:
                ctx.fred_json = ""
        except Exception:
            ctx.economics_json = json.dumps({"source": "unavailable"})

        # News, sentiment & social media (all symbols share the same feed)
        mtf_context = ""  # initialize before news/arxiv block
        try:
            from data.news import fetch_all_news
            from data.arxiv import fetch_arxiv, format_arxiv_context
            from data.social_sentiment import get_social_sentiment

            with self._mtf_lock:
                if self.cycle != self._news_cycle:  # thread-safe fetch-once-per-cycle
                    self._news_cycle = self.cycle
                    self._news_cache = fetch_all_news()
                    self._arxiv_cache = fetch_arxiv()
                    try:
                        from data.arxiv import fetch_cross_domain

                        fetch_cross_domain()  # Feed B: merge into the library (extraction-only)
                    except Exception:
                        pass
                    self._social_cache = get_social_sentiment(self.symbols)
            ctx.news_json = json.dumps(self._news_cache or {"sources": {}})
            arxiv_ctx = format_arxiv_context(
                self._arxiv_cache if hasattr(self, "_arxiv_cache") else []
            )
            if arxiv_ctx:
                mtf_context = (mtf_context or "") + arxiv_ctx
            # Social sentiment context
            if hasattr(self, "_social_cache") and self._social_cache:
                social_lines = ["\nSOCIAL SENTIMENT:"]
                for social_sym, data in self._social_cache.items():
                    if data.get("mentions", 0) > 0:
                        social_lines.append(
                            f"  {social_sym}: {data['sentiment']} (score={data['score']:.2f}, "
                            f"{data['mentions']} mentions, src={data['source']})"
                        )
                    else:
                        social_lines.append(
                            f"  {social_sym}: {data['sentiment']} (score={data['score']:.2f}, "
                            f"src={data['source']})"
                        )
                social_ctx = "\n".join(social_lines) + "\n"
                mtf_context = (mtf_context or "") + social_ctx
                logger.debug(f"Social context: {len(self._social_cache)} symbols")
        except Exception as e:
            logger.debug(f"News/arxiv/social context build error: {e}")
            ctx.news_json = json.dumps({"sources": {}})

        # ── Research findings from feature backlog (validated arxiv rules) ──
        try:
            from data.feature_integrator import FeatureIntegrator

            integrator = FeatureIntegrator(state_dir=self.state_dir)
            feature_ctx = integrator.build_context(max_features=3)
            if feature_ctx:
                mtf_context = feature_ctx + "\n\n" + (mtf_context or "")
        except Exception as e:
            logger.debug(f"Feature integrator error: {e}")

        # ── Fundamentals & Valuation (SEC EDGAR) ─────────────────
        fund_ctx = val_ctx = ""
        try:
            from data.fundamentals import compute_fundamentals, fundamentals_to_context
            from data.valuation import compute_valuation_summary, valuation_to_context

            fund = compute_fundamentals(sym, price=cur if cur else None)
            if fund:
                fund_ctx = fundamentals_to_context(fund)
                ctx.fundamentals_json = fund_ctx
                val = compute_valuation_summary(fund, price=cur if cur else None)
                if val:
                    val_ctx = valuation_to_context(val)
                    ctx.valuation_json = val_ctx
                    mtf_context = (
                        fund_ctx + "\n" + val_ctx + "\n\n" + (mtf_context or "")
                    )
                else:
                    mtf_context = fund_ctx + "\n\n" + (mtf_context or "")
                self._fundamentals_coverage[sym] = "ok"
            else:
                self._fundamentals_coverage[sym] = "missing"
        except Exception as e:
            logger.debug(f"Fundamentals/valuation skipped for {sym}: {e}")
            if "CIK" in str(e):
                self._fundamentals_coverage[sym] = "no_cik"
            else:
                self._fundamentals_coverage.setdefault(sym, "missing")

        # ── Crypto microstructure (funding + depth) — wayfinder #22 ──
        # Crypto symbols carry "/" (e.g. BTC/USDT). Model-sees-data only.
        try:
            if "/" in sym:
                from data.market_ctx import (
                    fetch_funding,
                    funding_to_context,
                    depth_to_context,
                )

                funding = fetch_funding([sym])
                fctx = funding_to_context(funding)
                depth = None
                if hasattr(self.exchange, "get_order_book_depth"):
                    depth = self.exchange.get_order_book_depth(sym, limit=10)
                dctx = depth_to_context(depth)
                if fctx or dctx:
                    block = (fctx + dctx).strip() + "\n\n"
                    mtf_context = block + (mtf_context or "")
                    ctx.funding_json = fctx
                    ctx.depth_json = dctx
        except Exception as e:
            logger.debug(f"Funding/depth context skipped for {sym}: {e}")

        # ── Multi-timeframe context (4h + primary) ──
        mtf_signal_bias = 0.0  # weighted composite: 1h×0.5 + 4h×0.3 = bias adjustment
        try:
            # Cache 4h bars per symbol (only updated on the hour, TTL=15min)
            mtf_cache_key = f"{sym}_4h"
            with self._mtf_lock:
                mtf_entry = self._mtf_cache.get(mtf_cache_key, {})
            mtf_age = time.time() - mtf_entry.get("ts", 0)

            if mtf_age < 900 and mtf_entry.get("bars"):
                bars = mtf_entry["bars"]
            else:
                bars = self.exchange.get_bars(sym, "4h", limit=20)
                if bars and len(bars) >= 5:
                    with self._mtf_lock:
                        self._mtf_cache[mtf_cache_key] = {
                            "bars": bars,
                            "ts": time.time(),
                        }

            if bars and len(bars) >= 5:
                closes = [b.close for b in bars]
                ret_full = closes[-1] / closes[0] - 1
                hi = max(b.high for b in bars[-5:])
                lo = min(b.low for b in bars[-5:])
                mtf_signal_bias += ret_full * 0.3
                mtf_context += (
                    f"  {sym} 4h: ${closes[-1]:,.2f} ({ret_full:+.1%}), "
                    f"range: {lo:.0f}-{hi:.0f}\n"
                )
            if mtf_context:
                mtf_context = f"Multi-Timeframe:\n{mtf_context}"
        except Exception:
            pass

        # Parse regime for adaptation
        regime_dict: Optional[dict] = None
        try:
            regime_dict = json.loads(ctx.regime_json or "{}")
        except Exception:
            pass

        # ── Produce signal (debate or single agent) ──
        signal = Signal(
            action="HOLD", symbol=sym, confidence=0.0, reason="debate unavailable"
        )
        debate_result = None
        if self.debate:
            try:
                # ── Fee-aware account context ──────────────────
                bal = self.exchange.get_balance()
                acct = AccountContext.from_harness(self)
                fees = acct.get_fees(sym)
                notional_preview = acct.cash_free * 0.05  # 5% preview
                _, _, rt_amt, rt_pct = acct.fee_impact(sym, notional_preview)
                account_context = (
                    f"[ACCOUNT] Capital: ${acct.capital:,.2f} | "
                    f"Free: ${acct.cash_free:,.2f} | "
                    f"Deployed: ${acct.capital_deployed:,.2f} | "
                    f"{acct.exchange}\n"
                    f"[FEES {sym}] Buy: ${fees.buy_cost(notional_preview):.2f} | "
                    f"Sell: ${fees.sell_cost(notional_preview):.2f} | "
                    f"Round-trip: ${rt_amt:.2f} ({rt_pct:.1f}% of {notional_preview:.0f} position)\n"
                    f"[ADVICE] {acct.position_advice(sym, notional_preview)}"
                )

                # ── Goal context ───────────────────────────────
                current_balance = bal.total_value
                progress_pct = (current_balance / max(GOAL_CAPITAL, 1)) * 100
                remaining = max(0, GOAL_CAPITAL - current_balance)
                goal_context = GOAL_DESCRIPTION.format(
                    goal_capital=GOAL_CAPITAL,
                    current_balance=current_balance,
                    progress_pct=progress_pct,
                    remaining=remaining,
                )

                extra_ctx = mtf_context
                if extra_ctx:
                    extra_ctx += "\n\n" + goal_context
                else:
                    extra_ctx = goal_context
                # ── Inject institutional memory ──────────────────
                trader_md_ctx = self.trader_md.to_context()
                if trader_md_ctx:
                    extra_ctx += "\n\n" + trader_md_ctx
                extra_ctx += "\n\n" + account_context

                logger.info(
                    f"  {sym}: [FEE] Round-trip=${rt_amt:.2f} ({rt_pct:.1f}% of ~${notional_preview:.0f} position) @ {acct.exchange}"
                )

                # Get regime-adaptive prompt instructions
                regime_instructions = get_regime_instructions(regime_dict)

                # Use debate mode: ADIR (independent) or fast (composite)
                if self.debate_mode == "adir":
                    debate_result = self.debate.independent_debate(
                        ohlcv_json=ctx.ohlcv_json,
                        portfolio_json=ctx.portfolio_json,
                        regime_json=ctx.regime_json,
                        economics_json=ctx.economics_json,
                        news_json=ctx.news_json,
                        extra_context=extra_ctx,
                        regime_instructions=regime_instructions,
                    )
                else:
                    debate_result = self.debate.fast_debate(
                        ohlcv_json=ctx.ohlcv_json,
                        portfolio_json=ctx.portfolio_json,
                        regime_json=ctx.regime_json,
                        economics_json=ctx.economics_json,
                        news_json=ctx.news_json,
                        regime_instructions=regime_instructions,
                        extra_context=extra_ctx,
                        parallel=self.parallel_debate,
                    )
                # NOTE: _cycle_debates now stored at call site where sym is guaranteed correct.
                signal = Signal(
                    action=debate_result.action,
                    symbol=sym,
                    confidence=debate_result.confidence,
                    reason=debate_result.reason,
                    position_pct=debate_result.position_pct,
                )
                signal.symbol = (
                    sym  # ensure symbol correctness (defense against stale bytecode)
                )
                # Record agent performance (thread-safe list appends under GIL)
                if self.scorer:
                    regime = (regime_dict or {}).get("regime", "unknown")
                    self.scorer.record(
                        "bull",
                        debate_result.bull_vote.action,
                        debate_result.bull_vote.confidence,
                        regime,
                        debate_result.action == debate_result.bull_vote.action,
                    )
                    self.scorer.record(
                        "bear",
                        debate_result.bear_vote.action,
                        debate_result.bear_vote.confidence,
                        regime,
                        debate_result.action == debate_result.bear_vote.action,
                    )
            except Exception as e:
                logger.error(f"  {sym}: debate error: {e}", exc_info=True)
        else:
            try:
                signal = self.agent.analyze(ctx)
            except Exception as e:
                logger.error(f"  {sym}: agent error: {e}", exc_info=True)
            signal.symbol = sym

        return sym, signal, ctx, regime_dict, debate_result

    def _scout_universe(self, focus: int = 6) -> tuple:
        """Three-tier debate roster: radar → agent rating → debate shortlist.

        Returns (top20_candidates, top6_debate_picks).
        Tier 1: Batch prices → industry radar → LLM picks top 20.
        Tier 2: Bull/Bear rate all 20 → composite score → top 6.
        Falls back to _scout_flat on error.
        """
        if not self.universe_mode or not self._universe_loaded:
            return list(self.symbols), list(self.symbols)[:focus]

        # ── Tier 1: Radar scan → top 20 ──
        try:
            from mot.industry_map import INDUSTRY_REGISTRY, get_universe_tickers

            all_tickers = get_universe_tickers()
        except Exception:
            return self._scout_flat(focus), self._scout_flat(focus)

        try:
            price_batch = self._get_cached_price_batch(all_tickers)
        except Exception:
            price_batch = {}

        radar = []
        for ind_name, tickers in sorted(INDUSTRY_REGISTRY.items()):
            ind_prices = [(t, price_batch[t]) for t in tickers if price_batch.get(t)]
            if not ind_prices:
                continue
            # Show up to 4 tickers per industry (highest + mid + lowest priced)
            # instead of only the single best — otherwise the LLM sees one
            # name per industry and falls back to name-recognition (bias toward
            # familiar tickers, e.g. A-names) rather than momentum.
            ind_prices.sort(key=lambda x: x[1])
            shown = ind_prices[-4:]
            shown_str = ", ".join(f"{t}=${p:.0f}" for t, p in shown)
            radar.append(f"  {ind_name}: {shown_str} ({len(ind_prices)}t)")

        if len(radar) < 10:
            return self._scout_flat(focus), self._scout_flat(focus)

        prompt = (
            f"Market radar - {len(radar)} industries, {len(price_batch)} tickers.\n"
            f"Pick top 20 tickers with the STRONGEST SHORT-TERM TRADING POTENTIAL. "
            f"Do not just pick well-known mega-caps — consider the full breadth "
            f"of the radar.\n\n"
            + "\n".join(radar[:50])
            + f'\n\nJSON: [{{"symbol":"NVDA","score":8,"reason":"..."}}, ...]'
        )

        top20 = []
        try:
            pick_dicts = self._llm_json_array(
                prompt, key="symbol", max_n=20, min_score=1
            )
            pick_dicts = sorted(
                pick_dicts, key=lambda d: d.get("score", 0), reverse=True
            )
            top20 = [d["symbol"] for d in pick_dicts if d.get("symbol")][:20]
        except Exception:
            pass

        if len(top20) < 3:
            f = self._scout_flat(focus)
            return f, f

        # ── Tier 2 (simplified): rank by the radar momentum score, skipping the
        #    two serial LLM bull/bear rating calls (saves ~2 LLM calls / scout) ──
        top6 = top20[:focus]

        self._last_universe_pick = pick_dicts if pick_dicts else []
        logger.info(f"Scout: top20={len(top20)}, top6={top6}")
        return top20, (top6 or top20[:focus])

    # ── Scout helpers (Wave 3, T8) ────────────────────────────

    def _llm_json_array(
        self, prompt: str, key: str = "symbol", max_n: int = 8, min_score: int = 5
    ) -> list:
        from urllib.request import Request, urlopen
        import json as _json, re

        payload = _json.dumps(
            {
                "model": self.debate_model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 512,
                "temperature": 0.3,
            }
        ).encode()
        req = Request(
            f"{self.llama_host}/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urlopen(req, timeout=30) as resp:
            body = _json.loads(resp.read().decode())
            response = body["choices"][0]["message"]["content"]
        array_match = re.search(r"\[.*]", response, re.DOTALL)
        if array_match:
            data = _json.loads(array_match.group(0))
            if isinstance(data, list):
                return [
                    d for d in data if d.get("score", 0) >= min_score and d.get(key)
                ]
        return []

    def _get_cached_price_batch(self, all_tickers: list, ttl: int = 1800) -> dict:
        """Batch price fetch cached for `ttl` seconds — the yfinance sweep over
        the full universe is the single biggest per-cycle cost (~100s), and a
        daily-bar strategy does not need fresher than ~30min quotes."""
        now = time.time()
        cached = getattr(self, "_price_batch_cache", None)
        if cached and now - cached.get("ts", 0) < ttl:
            return cached.get("data", {})
        data = (
            self.exchange.get_prices_batch(all_tickers)
            if hasattr(self.exchange, "get_prices_batch")
            else {}
        )
        self._price_batch_cache = {"ts": now, "data": data}
        return data

    def _scout_flat(self, focus: int = 6) -> List[str]:
        import json as _json, re
        from urllib.request import Request, urlopen

        # Radar fallback: use the full curated universe (industry registry),
        # not the crypto-only discovered set — otherwise the fallback scout
        # only ever sees crypto and never surfaces stocks.
        try:
            from mot.industry_map import get_universe_tickers

            universe = get_universe_tickers()
        except Exception:
            universe = self._tradable_universe
        lines = []
        # Bounded scan: per-symbol get_current_price (finnhub ~1s) + get_bars
        # (yfinance) over 500+ names is minutes-long. Price a representative
        # sample — the LLM only needs enough to pick a focus set.
        scan_list = universe[:80] + [s for s in universe if s in self.symbols]
        for sym in scan_list:
            try:
                price = self.exchange.get_current_price(sym)
            except Exception:
                price = None
            if price is None:
                continue
            bars = self.exchange.get_bars(sym, limit=5)
            change = ""
            if len(bars) >= 2:
                pct = (bars[-1].close - bars[-2].close) / bars[-2].close * 100
                change = f" {pct:+.2f}%"
            lines.append(f"  {sym}: ${price:,.2f}{change}")
        if not lines:
            return list(self.symbols)
        prompt = SCOUT_PROMPT.replace("{{n}}", str(focus)).replace(
            "{{snapshot}}", "\n".join(lines)
        )
        try:
            picks = self._llm_json_array(prompt, key="symbol", max_n=focus, min_score=5)
            if picks:
                return [p["symbol"] for p in picks if p.get("symbol") in universe]
        except Exception:
            pass
        scored = []
        for sym in scan_list:
            bars = self.exchange.get_bars(sym, limit=20)
            if len(bars) >= 5:
                cp = [b.close for b in bars[-5:]]
                vol = (max(cp) - min(cp)) / cp[-1] if cp[-1] else 0
                scored.append((vol, sym))
        scored.sort(reverse=True)
        return [s[1] for s in scored[:focus]] or list(self.symbols)

    def _rule_primary_signals(self, active_symbols: list) -> dict:
        """Generate signals from the validated rule config (the proven edge).

        BUY when the rule screen passes (regime ok AND score >= buy_thresh) for a
        symbol not held; SELL when a held symbol's score drops below sell_thresh;
        else HOLD (SL/TP manages risk). Daily-bar based, like the validated config.
        """
        from setup_search.rule_gate import screen, load_rule_config

        if self._rule_gate_cfg is None:
            self._rule_gate_cfg = load_rule_config()
        cfg = self._rule_gate_cfg
        import pandas as pd

        # VIX day-regime gate (the exogenous layer, wayfinder #92). Mode:
        #   strict (z>=0.5) — FALSIFIED as an edge 2026-08-15; in calm regimes
        #     it holds the book flat and starves the meta-layer (0 fills).
        #   soft (z>=0.0)   — open when VIX >= its 250d mean (~40% of days).
        #   off (neutralized) — removed from the fill path; regime is logged
        #     informationally only, never blocks entries. The rule floor's own
        #     regime_filter + buy_thresh remain the entry gate.
        # Any data-availability error degrades to allow (no gate), never block.
        try:
            from data.vix_gate import VixGate
            _mode = getattr(self, "vix_gate", "strict")
            _thr = {"strict": 0.5, "soft": 0.0, "off": 0.5}[_mode]
            if getattr(self, "_vix_gate", None) is None:
                self._vix_gate = VixGate(threshold=_thr)
            vix_note = self._vix_gate.describe()
            vix_allow = (True if _mode == "off"
                         else self._vix_gate.allow_trading())
            if _mode == "off":
                vix_note = f"vixgate NEUTRALIZED (informational {vix_note})"
        except Exception as _e:
            vix_allow, vix_note = True, f"vixgate disabled ({_e})"

        # Hive Mother Trader veto (#56 Phase 3): lazy init only; the actual
        # decision runs after closes are built (below).
        try:
            from setup_search.mother_trader import MotherTrader
            if getattr(self, "_mother_trader", None) is None:
                self._mother_trader = MotherTrader()
        except Exception:
            self._mother_trader = None
        mt_note = "mt disabled (no swarm)"
        self._mt_decision = None

        syms = list(set(active_symbols) | {"SPY"})
        closes, highs, lows, vols = {}, {}, {}, {}
        for s in syms:
            bars = self._daily_bars(s, 150)
            if not bars:
                continue
            idx = [self._bar_ts(b) for b in bars]
            closes[s] = pd.Series([b.close for b in bars], index=idx)
            highs[s] = pd.Series([b.high for b in bars], index=idx)
            lows[s] = pd.Series([b.low for b in bars], index=idx)
            vols[s] = pd.Series([b.volume for b in bars], index=idx)
        held = set(self.exchange.get_balance().positions.keys())

        # Hive Mother Trader (#56 Phase 3): the swarm votes on the state. The
        # result is MONITORING here — the veto applies ONLY to specialist-driven
        # entries at the MoT router point, never to the rule floor (audit
        # 2026-08-11: the old code gated ALL BUYs on the soft vote, so an
        # unproven swarm froze the floor too — a silent hold).
        try:
            if (self._mother_trader is not None
                    and len(self._mother_trader.registry.slots) > 0):
                mt_decision = self._mother_trader.decide(
                    _hive_feature_vector(closes, cfg), _hive_regime(closes))
                self._mt_decision = mt_decision
                mt_note = (f"mt soft={mt_decision['soft_vote']:.3f} "
                           f"({mt_decision['reason']})")
        except Exception as _e:
            self._mt_decision = None
            mt_note = f"mt disabled ({_e})"
        out = {}
        for sym in active_symbols:
            if sym not in closes or "SPY" not in closes:
                out[sym] = (Signal(action="HOLD", symbol=sym, reason="rule-primary: no data"), "", {})
                continue
            date = closes[sym].index[-1]
            ok, score = screen(closes, highs, lows, vols, sym, date, cfg)
            is_held = sym in held
            if not is_held and ok and vix_allow:
                sig = Signal(
                    action="BUY", symbol=sym,
                    confidence=min(1.0, max(0.0, (score + 1.0) / 2.0)),
                    position_pct=cfg["risk_pct"],
                    reason=f"rule-primary score={score:.3f} ({vix_note} {mt_note})",
                )
            elif not is_held and ok and not vix_allow:
                # VIX gate holds the book flat on calm days (the validated edge)
                sig = Signal(action="HOLD", symbol=sym,
                             reason=f"vix-gate calm {vix_note}")
            elif is_held and score < cfg["sell_thresh"]:
                sig = Signal(action="SELL", symbol=sym, confidence=0.6,
                             reason=f"rule-primary exit score={score:.3f}")
            else:
                sig = Signal(action="HOLD", symbol=sym,
                             reason=f"rule-primary score={score:.3f}")
            out[sym] = (sig, "", {})
            logger.info(f"  RuleSignal[{sym}]: {sig.action} (score={score:.3f}, held={is_held})")

        # ── Crypto leg: the validated crypto rule screen (BTC regime, % fee) ──
        # Runs alongside the US-stock leg so the book trades both markets.
        try:
            from setup_search.core import DEFAULT_CONFIG, clamp_config

            crypto_syms = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
            # Crypto leg: gate on BTC's own 96d trend, NOT SPY (decoupled) and
            # NOT un-gated (the pre-redo tail risk). regime_sym=BTC/USDT with
            # regime_filter=1 turns on the screen's regime check.
            crypto_cfg = clamp_config({**DEFAULT_CONFIG, "_fee_pct": 0.0016,
                                       "regime_filter": 1,
                                       "regime_sym": "BTC/USDT",
                                       "regime_window": 96})
            # RUNWAY: crypto sleeve capped at 12% of equity (per-class gross).
            # BTC/ETH/SOL are ONE correlated cluster (rho 0.7-0.9, ~4x stock
            # vol); the pre-redo sleeve could reach ~26% of equity.
            _bal = self.exchange.get_balance()
            _prices = {s: self.exchange.get_current_price(s) for s in crypto_syms}
            _sleeve_now = sum(_prices.get(s, 0.0) * q for s, q in _bal.positions.items() if s in crypto_syms)
            _sleeve_budget = max(0.0, (0.12 * _bal.total_value - _sleeve_now)) / max(_bal.total_value, 1.0)
            c_closes, c_highs, c_lows, c_vols = {}, {}, {}, {}
            for s in crypto_syms + ["BTC/USDT"]:
                bars = self._daily_bars(s, 150)
                if not bars:
                    continue
                idx = [self._bar_ts(b) for b in bars]
                c_closes[s] = pd.Series([b.close for b in bars], index=idx)
                c_highs[s] = pd.Series([b.high for b in bars], index=idx)
                c_lows[s] = pd.Series([b.low for b in bars], index=idx)
                c_vols[s] = pd.Series([b.volume for b in bars], index=idx)
            logger.debug(f"  Crypto bars fetched: { {s: len(c_closes.get(s, [])) for s in crypto_syms + ['BTC/USDT']} }")
            for sym in crypto_syms:
                if sym not in c_closes or "BTC/USDT" not in c_closes:
                    out.setdefault(sym, (Signal(action="HOLD", symbol=sym,
                                                reason="crypto: no data"), "", {}))
                    continue
                date = c_closes[sym].index[-1]
                ok, score = screen(c_closes, c_highs, c_lows, c_vols, sym, date,
                                   crypto_cfg, regime_sym="BTC/USDT")
                is_held = sym in held
                if not is_held and ok and _sleeve_budget >= 0.01:
                    pos_pct = min(crypto_cfg["risk_pct"], _sleeve_budget)
                    sig = Signal(action="BUY", symbol=sym,
                                 confidence=min(1.0, max(0.0, (score + 1.0) / 2.0)),
                                 position_pct=pos_pct,
                                 reason=f"crypto-rule score={score:.3f}")
                elif not is_held and ok:
                    sig = Signal(action="HOLD", symbol=sym,
                                 reason="crypto-rule sleeve cap (12% of equity)")
                elif is_held and score < crypto_cfg["sell_thresh"]:
                    sig = Signal(action="SELL", symbol=sym, confidence=0.6,
                                 reason=f"crypto-rule exit score={score:.3f}")
                else:
                    sig = Signal(action="HOLD", symbol=sym,
                                 reason=f"crypto-rule score={score:.3f}")
                out[sym] = (sig, "", {})
                logger.info(f"  CryptoRule[{sym}]: {sig.action} (score={score:.3f}, held={is_held})")
        except Exception as e:
            logger.warning(f"crypto rule screen skipped: {e}")
        return out

    def _hold_exit_date(self, sym):
        """Validated max_hold=14 TRADING days after the last daily close
        (the harness's cycle counter is 1h-based and cannot express daily
        holds; a raw max_position_cycles=14 at 60s cycles would exit in
        ~14 minutes). Returns ISO date or None."""
        try:
            from datetime import timedelta
            bars = self._daily_bars(sym, 1)
            if not bars:
                return None
            d = self._bar_ts(bars[-1]).date()
            n = 0
            while n < 14:
                d += timedelta(days=1)
                if d.weekday() < 5:
                    n += 1
            return d.isoformat()
        except Exception:
            return None

    def _daily_bars(self, sym: str, limit: int):
        """Fetch daily bars, DROPPING future-dated bars. The stock waterfall
        can emit a next-UTC-midnight placeholder bar; a future date keyed into
        other series' indexes raises KeyError(Timestamp) and crash-loops the
        harness (the 22:33->00:34 UTC marathon). Root fix: the bad date never
        enters any rule path."""
        bars = self.exchange.get_bars(sym, "1d", limit=limit)
        if not bars:
            return bars
        cutoff = datetime.now(timezone.utc) + timedelta(hours=1)
        clean = [b for b in bars if self._bar_ts(b) <= cutoff]
        if len(clean) != len(bars):
            logger.warning(
                f"  dropped {len(bars) - len(clean)} future-dated bar(s) for {sym}"
            )
        return clean

    @staticmethod
    def _bar_ts(b) -> "datetime":
        """Epoch-seconds -> UTC datetime for ANY bar type the exchanges emit:
        OHLCV (.timestamp, int seconds), LiveExchange/ccxt (.timestamp, int
        MILLISECONDS), dict bars, and SimpleBar (.t / .timestamp). The old
        direct fromtimestamp(b.timestamp) crashed on SimpleBar (no field) and
        misread ccxt ms timestamps."""
        if isinstance(b, dict):
            ts = b.get("timestamp", b.get("t", 0))
        else:
            ts = getattr(b, "timestamp", getattr(b, "t", None))
        if ts is None:
            return datetime.now(timezone.utc)
        ts = float(ts)
        if ts > 1e11:  # milliseconds (ccxt) -> seconds
            ts /= 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc)

    # ── MoT router monitor (runway) ──────────────────────────────
    def _record_router_impact(self, sym, entry_price, exit_price):
        """Record a closed trade's pnl_pct against the expert that entered it,
        into the persisted live_router_state.json. Monitoring only — the router
        does not gate anything on the runway."""
        try:
            from mot.mixture import RegimeRouter

            if self._mot_router is None:
                self._mot_router = RegimeRouter(rule_floor="rule", min_evidence=5)
                self._load_router_state()
            entry = self._sl_tp_levels.get(sym, {})
            regime = entry.get("entry_regime") or self._mot_regime(sym)
            expert = entry.get("entry_expert", "rule")
            if regime not in ("up", "down"):
                regime = "up" if self._mot_regime(sym) == "bull" else "down"
            impact = (exit_price - entry_price) / entry_price if entry_price > 0 else 0.0
            self._mot_router.record(regime, expert, float(impact))
            self._save_router_state()
            # Hive evidence feed (#56 Phase 4): a closed trade accrues
            # mean_impact to the slot whose specialist decided it. Floor
            # ("rule") and ADIR ("adir") trades are NOT specialist evidence
            # and are never recorded (audit 2026-08-11: the old feed
            # hardcoded "equities__10", polluting that slot with floor and
            # debate behavior).
            try:
                if getattr(self, "_mother_trader", None) is not None:
                    slot = self._expert_to_hive_slot(expert)
                    if slot is not None:
                        self._mother_trader.record_impact(
                            slot, "bull" if self._mot_regime(sym) == "bull" else "bear",
                            float(impact))
            except Exception:
                pass
        except Exception:
            pass

    def _expert_to_hive_slot(self, expert: str):
        """Map a deciding expert id to a registered hive slot, or None.

        Hive slots are the swarm registry keys (equities__10, crypto__21, ...).
        Only exact matches count — "rule" and "adir" are never specialist
        evidence."""
        try:
            slots = self._mother_trader.registry.slots
            if expert in slots:
                return expert
        except Exception:
            pass
        return None

    def _save_router_state(self):
        # Single-writer contract (#155): all writes of live_router_state.json
        # go through strategies/router_state.py (atomic, merge-preserving).
        try:
            from strategies.router_state import write_router_state

            write_router_state(
                {"track": self._mot_router.track,
                 "weights": self._mot_router.weights},
                state_dir=self.state_dir,
                merge=True,
            )
        except Exception:
            pass

    def _load_router_state(self):
        try:
            from strategies.router_state import read_router_state

            d = read_router_state(self.state_dir)
            self._mot_router.track = d.get("track", {})
            self._mot_router.weights = d.get("weights", {})
        except Exception:
            pass

    def _mot_regime(self, sym: str) -> str:
        """SPY vs 200d regime bucket for the MoT router."""
        try:
            import pandas as pd

            bars = self._daily_bars("SPY", 250)
            if not bars:
                return "unknown"
            idx = [self._bar_ts(b) for b in bars]
            spy = pd.Series([b.close for b in bars], index=idx)
            ma = spy.rolling(200, min_periods=60).mean()
            last = spy.index[-1]
            return "bull" if float(spy[last]) > float(ma[last]) else "bear"
        except Exception as e:
            logger.debug(f"mot regime failed for {sym}: {e}")
            return "unknown"

    def _rule_gate_ok(self, sym: str) -> bool:
        """Weaponized playbook: does a BUY for `sym` clear the validated rule
        screen (regime + technical score)? Fail-closed — if the screen can't be
        computed, the trade is blocked. Cached per symbol (20 min)."""
        try:
            cached = self._rule_gate_cache.get(sym)
            if cached and time.time() - cached[0] < 1800:
                return cached[1]
            from setup_search.rule_gate import screen, load_rule_config
            if self._rule_gate_cfg is None:
                self._rule_gate_cfg = load_rule_config()
            import pandas as pd  # already loaded by the exchange module

            closes, highs, lows, vols = {}, {}, {}, {}
            for s in (sym, "SPY"):
                bars = self._daily_bars(s, 150)
                if not bars:
                    continue
                index = [self._bar_ts(b) for b in bars]
                closes[s] = pd.Series([b.close for b in bars], index=index)
                highs[s] = pd.Series([b.high for b in bars], index=index)
                lows[s] = pd.Series([b.low for b in bars], index=index)
                vols[s] = pd.Series([b.volume for b in bars], index=index)
            ok = False
            if sym in closes and "SPY" in closes:
                date = closes[sym].index[-1]
                ok, _ = screen(closes, highs, lows, vols, sym, date, self._rule_gate_cfg)
            self._rule_gate_cache[sym] = (time.time(), ok)
            return ok
        except Exception as e:
            logger.debug(f"rule-gate screen failed for {sym}: {e}")
            return False

    def run_cycle(self) -> dict:
        """Execute one trading cycle across all active symbols.

        Phase 7 Multi-Symbol Flow:
          1. Push bars + check SL/TP guardrails
          2. Phase 1: Gather debate signals in parallel for ALL symbols
          3. Phase 2: Portfolio optimization (correlation-aware Kelly allocation)
          4. Phase 3: Execute trades based on optimized allocation
          5. Record state, flash train, reflection, adapter tracking
        """
        self.cycle += 1
        prices = {}
        self._cycle_debates = {}
        cycle_start = time.time()

        # ── Push new bars for price movement ─────────────────
        if self.synthetic_data and self.exchange and self.exchange.name in ("paper",):
            for sym in list(self.symbols):
                try:
                    self._push_new_bar(sym)
                except Exception as e:
                    logger.debug(f"Failed to push bar for {sym}: {e}")

        # ── Training lock: yield to scheduler ────────────────
        from pathlib import Path as _Path

        _training_lock = _Path(self.state_dir) / "training.lock"
        if _training_lock.exists():
            # A trainer that dies can leave a stale lock that HOLDs the harness
            # forever with no auto-cleanup. Anything older than 6h is stale.
            stale = False
            try:
                stale = time.time() - _training_lock.stat().st_mtime > 6 * 3600
            except OSError:
                stale = False
            if stale:
                try:
                    _training_lock.unlink()
                    logger.info(
                        f"Cycle {self.cycle}: removed stale training.lock (>6h)"
                    )
                except OSError:
                    pass
            else:
                # Training in progress — only check SL/TP, no new trades
                self._check_sl_tp()
                # HOLD ack: signal the trainer that the harness has seen the
                # lock and will not issue LLM calls this cycle. Fresh each
                # HOLD cycle so a dead harness's stale ack expires.
                try:
                    _ack = _Path(self.state_dir) / "training_hold_ack"
                    _ack.touch()
                except OSError:
                    pass
                logger.debug(
                    f"Cycle {self.cycle}: training lock active — HOLD only, {len(self.symbols)} symbols"
                )
                return {"cycle": self.cycle, "training_locked": True}

        # Periodic param re-optimization (every 100 cycles, or when portfolio moves)
        # RUNWAY: disabled under --pin-risk — these blocks rewrite SL/TP/sizing
        # from 15m crypto params (data/param_opt/params.json) and silently change
        # the risk profile mid-shadow.
        if not getattr(self, "_pin_risk", False) and self.cycle % 100 == 0 and self._optimal_params:
            bal = self.exchange.get_balance()
            new_params = self._load_optimal_params(bal.total_value)
            if new_params:
                self._optimal_params = new_params
                # Apply to risk config
                self.risk.config.max_position_pct = new_params.get(
                    "max_position_pct", 0.18
                )
                self.risk.config.kelly_fraction = new_params.get("kelly_fraction", 0.35)
                self.risk.config.stop_loss_pct = new_params.get("stop_loss_pct", 0.05)
                self.risk.config.take_profit_pct = new_params.get(
                    "take_profit_pct", 0.10
                )
                self.risk.config.max_total_exposure = new_params.get(
                    "max_total_exposure", 0.60
                )

        # ── 0. Progression check ─────────────────────────────
        progressed = self._check_progression()
        if self.universe_mode and self._universe_loaded:
            _scout_interval = getattr(self, "_scout_interval", 3)
            # Fresh scout every N cycles; reuse cached picks otherwise
            # Also force rescout if all cached picks produced HOLD last cycle
            cached = getattr(self, "_cached_scout_symbols", [])
            all_hold = False
            if cached:
                last_sigs = getattr(self, "_last_debated_signals", {})
                all_hold = all(
                    last_sigs.get(s, {}).get("action", "") == "HOLD" for s in cached
                )
            # Rescout only every `_scout_interval` cycles, or after a sustained
            # HOLD streak (>= 8) — a single HOLD cycle no longer forces the
            # expensive full-universe sweep every cycle.
            if all_hold:
                self._hold_streak = getattr(self, "_hold_streak", 0) + 1
            else:
                self._hold_streak = 0
            if (
                self.cycle % _scout_interval == 0
                or not cached
                or len(cached) < 4
                or (all_hold and getattr(self, "_hold_streak", 0) >= 8)
            ):
                top20, top6 = self._scout_universe(6)
                # Guard: deduplicate and validate
                seen_scout = set()
                deduped = []
                for s in top6:
                    if isinstance(s, str) and s not in seen_scout:
                        seen_scout.add(s)
                        deduped.append(s)
                active_symbols = deduped or list(self.symbols)
                self._cached_scout_symbols = active_symbols
                logger.info(
                    f"  [SCOUT] fresh pick: top20={len(top20)} top6={active_symbols}"
                )
            else:
                active_symbols = self._cached_scout_symbols
                logger.info(
                    f"  [SCOUT] deferred (cycle {self.cycle % _scout_interval}/{_scout_interval}): {active_symbols}"
                )
        else:
            active_symbols = list(self.symbols)
        # Sync self.symbols to the active set so every symbol in the debate
        # universe gets new bars pushed each cycle (stocks were previously
        # frozen at their initial price → 0% P&L on all stock trades).
        if active_symbols and self.symbols != active_symbols:
            self.symbols = list(active_symbols)
        multi_symbol = len(active_symbols) > 1
        logger.info(
            f"── Cycle {self.cycle} [Stage {self.stage}: {len(active_symbols)} symbols] ──"
        )

        # ── 0b. Circuit breaker with recovery ─────────────────
        bal = self.exchange.get_balance()
        # Dynamic focus: scale debate count by capital. With a PINNED surface
        # (--no-universe) the focus cap must not silently truncate the
        # validated symbol list (it capped stage-1 paper at 8 symbols while 19
        # were configured); the cap applies to scout-selected surfaces only.
        max_focus = max(2, min(8, int(bal.total_value / 50)))
        if not self.universe_mode:
            max_focus = max(max_focus, len(active_symbols))
        if len(active_symbols) > max_focus:
            active_symbols = active_symbols[:max_focus]
            logger.info(
                f"  Dynamic focus: {max_focus} symbols (capital=${bal.total_value:,.0f})"
            )
        if not self.risk.check_circuit_breaker(bal.total_value):
            if self._circuit_breaker_cycle == 0:
                self._circuit_breaker_cycle = self.cycle
                logger.warning(
                    f"CIRCUIT BREAKER — drawdown > "
                    f"{self.risk.config.portfolio_stop_pct * 100:.0f}%"
                )
            # Check if cooldown period has elapsed (~25 min at 15s/cycle)
            recovery_cycles = 100
            if self.cycle - self._circuit_breaker_cycle >= recovery_cycles:
                logger.info(
                    "Circuit breaker recovery: attempting resume after cooldown"
                )
                self._circuit_breaker_cycle = 0
                # Continue normally instead of returning halted
            else:
                return {
                    "cycle": self.cycle,
                    "status": "halted",
                    "reason": "circuit_breaker",
                }

        # ── SL/TP guardrails every cycle (audit F1: previously only enforced
        #    while training.lock was held — stops/trims never fired in live trading) ──
        self._check_sl_tp()

        # ═══════════════════════════════════════════════════════
        from agent.base import AgentContext

        all_signals: List[Signal] = []
        signal_contexts: Dict[str, AgentContext] = {}

        # ── Debate all symbols (cached-HOLD optimization disabled per multi-GPU refactor) ──
        debate_syms = list(active_symbols)

        results: Dict[str, Tuple[Signal, AgentContext, Optional[dict]]] = {}
        # Seed results with cached HOLDs from smart debate skip
        for sig in all_signals:
            if sig.symbol not in results:
                results[sig.symbol] = (sig, "", {})

        def _debate_wrapper(sym):
            try:
                _, signal, ctx, regime_dict, debate_result = self._debate_one_symbol(
                    sym,
                    self.cycle,
                    self.timeframe,
                    bal,
                )
                self._cycle_debates[sym] = {
                    "bull": {
                        "action": debate_result.bull_vote.action
                        if debate_result
                        else "HOLD",
                        "conf": debate_result.bull_vote.confidence
                        if debate_result
                        else 0,
                        "evq": getattr(debate_result.bull_vote, "evq", None)
                        if debate_result
                        else None,
                    },
                    "bear": {
                        "action": debate_result.bear_vote.action
                        if debate_result
                        else "HOLD",
                        "conf": debate_result.bear_vote.confidence
                        if debate_result
                        else 0,
                        "evq": getattr(debate_result.bear_vote, "evq", None)
                        if debate_result
                        else None,
                    },
                    "risk": {
                        "action": debate_result.action if debate_result else "HOLD",
                        "conf": debate_result.confidence if debate_result else 0,
                        "evq": None,
                    },
                }
                return (sym, signal, ctx, regime_dict)
            except Exception as e:
                signal = Signal(
                    action="HOLD",
                    symbol=sym,
                    confidence=0.0,
                    reason=f"debate error: {e}",
                )
                self._cycle_debates[sym] = {
                    "bull": {"action": "HOLD", "conf": 0, "evq": None},
                    "bear": {"action": "HOLD", "conf": 0, "evq": None},
                    "risk": {"action": "HOLD", "conf": 0, "evq": None},
                }
                return (sym, signal, "", {})

        # Run debates in parallel — only for symbols that need it
        # Cap at 4 workers: _API_SEMAPHORE(2) limits actual concurrency, but
        # extra workers handle non-API prep (news, bars, context building).
        if self.rule_primary:
            results.update(self._rule_primary_signals(active_symbols))
            logger.info("Rule-primary mode: signals from the validated rule config")
        else:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=min(len(debate_syms), 4)
            ) as executor:
                futures = {
                    executor.submit(_debate_wrapper, sym): sym for sym in debate_syms
                }
                for future in concurrent.futures.as_completed(futures):
                    sym, signal, ctx, regime_dict = future.result()
                    results[sym] = (signal, ctx, regime_dict)
                    logger.info(
                        f"  Signal[{sym}]: {signal.action} "
                        f"(conf={signal.confidence:.2f}, pos_pct={signal.position_pct:.3f}, {signal.reason[:80]})"
                    )

        # Store debate signals for next cycle's smart debate filter
        if not hasattr(self, "_last_debated_signals"):
            self._last_debated_signals = {}
        for sym in active_symbols:
            if sym in results:
                sig = results[sym][0]
                self._last_debated_signals[sym] = {
                    "action": sig.action,
                    "conf": sig.confidence,
                    "cycle": self.cycle,
                }

        # Preserve symbol order + collect per-symbol risk overrides
        symbol_risk_overrides: Dict[str, Dict[str, float]] = {}
        for sym in active_symbols:
            result_entry = results.get(sym)
            if result_entry is None:
                signal = Signal(
                    action="HOLD",
                    symbol=sym,
                    confidence=0.0,
                    reason="debate unavailable",
                )
                ctx = ""
                regime_dict = {}
            else:
                signal, ctx, regime_dict = result_entry
            all_signals.append(signal)
            signal_contexts[sym] = ctx
            logger.debug(
                f"  DBG-FOR-APPEND: {sym}={signal.action}({signal.confidence:.2f}) → all_signals len={len(all_signals)}"
            )
            # Store per-symbol regime overrides (applied per-check, not globally)
            if regime_dict:
                ov = get_regime_risk_overrides(regime_dict)
                if ov:
                    symbol_risk_overrides[sym] = ov
                    logger.debug(
                        f"  Regime override[{sym}]: {regime_dict.get('regime', '?')} "
                        f"→ {', '.join(f'{k}={v}' for k, v in list(ov.items())[:3])}"
                    )
                self._symbol_regimes[sym] = regime_dict

        # Prune regime ratings for symbols no longer in the (crypto) universe —
        # stops the dashboard showing stale stock convictions (JPM/MA/etc.).
        _universe = set(self._tradable_universe) | set(active_symbols)
        self._symbol_regimes = {
            s: r for s, r in self._symbol_regimes.items() if s in _universe
        }

        # ── Merge per-symbol optimized params into risk overrides ──
        # audit F2: removed the `for/else` block that re-ran the serial debate
        # path every cycle (it had no `break`, so `else` always fired and
        # duplicated every Bull/Bear/Risk LLM call + clobbered risk overrides).
        for sym in active_symbols:
            opt_ov = self.risk.get_symbol_overrides(sym)
            if opt_ov:
                existing = symbol_risk_overrides.get(sym, {})
                merged = dict(opt_ov)
                if existing:
                    merged.update(existing)
                symbol_risk_overrides[sym] = merged

        # ═══════════════════════════════════════════════════════
        # Phase 1.5: Record ALL symbol signals to history
        # ═══════════════════════════════════════════════════════
        for sig in all_signals:
            self.signal_history.append(
                {
                    "symbol": sig.symbol,
                    "action": sig.action,
                    "confidence": sig.confidence,
                    "reason": sig.reason,
                    "position_pct": sig.position_pct,
                    "timestamp": datetime.now(timezone.utc).isoformat(
                        timespec="seconds"
                    ),
                }
            )
        # Cap history at 500 entries
        if len(self.signal_history) > 500:
            self.signal_history = self.signal_history[-500:]

        logger.debug(
            f"  DBG-POST-DEBATE: all_signals={[f'{s.symbol}={s.action}({s.confidence:.2f})' for s in all_signals]}"
        )

        # ═══════════════════════════════════════════════════════
        # Phase 1.6: Asset Class Allocation (multi-asset stages)
        # ═══════════════════════════════════════════════════════
        # Only active when we have multiple asset classes (crypto + stocks/forex).
        # The allocator proposes macro-level weights; we scale per-symbol position
        # pcts so the portfolio optimizer respects class budgets.
        market_summary = {}
        self._asset_allocations: dict = {}
        if self.stage >= 3 and self.debate and all_signals:
            try:
                from state.context import AccountContext

                fee_ctx = AccountContext.from_harness(self)
                allocator = AssetClassAllocator(
                    llm_call_fn=self._llm_call_allocator
                    if hasattr(self, "_llm_call_allocator")
                    else None,
                    use_model=bool(self._llm_call_allocator)
                    if hasattr(self, "_llm_call_allocator")
                    else False,
                )

                bal = self.exchange.get_balance()
                alloc_classes = allocator.allocate(
                    signals=all_signals,
                    prices=prices,
                    portfolio_value=bal.total_value,
                    cash=bal.cash,
                    positions={k: float(v) for k, v in (bal.positions or {}).items()},
                    fee_context=fee_ctx,
                    regime_hint=market_summary.get("regime", ""),
                )

                if alloc_classes:
                    all_signals = allocator.adjust_signals(
                        all_signals,
                        alloc_classes,
                        bal.total_value,
                    )
                    self._asset_allocations = {
                        name: ac.weight for name, ac in alloc_classes.items()
                    }
                    logger.info(
                        f"  Asset allocator: "
                        + ", ".join(
                            f"{k}={v:.0%}"
                            for k, v in sorted(self._asset_allocations.items())
                        )
                    )
            except Exception as e:
                logger.warning(f"  Asset allocator failed: {e}")

        # ═══════════════════════════════════════════════════════
        # Phase 2: Portfolio Optimization (multi-symbol)
        # ═══════════════════════════════════════════════════════
        portfolio_result = None
        # Build signal map keyed by signal's own symbol (preserves debate-order attribution)
        _sig_map = {}
        logger.debug(
            f"  DBG-PRE-DEDUP: {len(all_signals)} signals: {[f'{s.symbol}={s.action}' for s in all_signals]}"
        )
        for sig in all_signals:
            _sig_map.setdefault(sig.symbol, sig)
        all_signals = list(_sig_map.values())
        logger.debug(
            f"  DBG-POST-DEDUP: {len(all_signals)} signals: {[f'{s.symbol}={s.action}({s.confidence:.2f})' for s in all_signals]}"
        )
        # DBG: log all signals pre-optimizer
        _dbg_signals = ", ".join(
            f"{s.symbol}={s.action}({s.confidence:.2f})" for s in all_signals
        )
        logger.info(f"  PRE-OPTIMIZER: {len(all_signals)} signals → {_dbg_signals}")

        if (
            multi_symbol
            and self.debate
            and all_signals
            and any(s.action in ("BUY", "SELL") for s in all_signals)
        ):
            try:
                # Get prices for all symbols
                for sym in active_symbols:
                    p = self.exchange.get_current_price(sym) or self._start_price(sym)
                    prices[sym] = p

                # Extract price history for correlation computation
                from risk.manager import RiskManager

                price_history = RiskManager.extract_price_history(
                    self.exchange,
                    active_symbols,
                    lookback=50,
                    timeframe=self.timeframe,
                )

                positions_flat = {}
                for k, v in (bal.positions or {}).items():
                    if isinstance(v, dict):
                        positions_flat[k] = float(v.get("quantity", 0))
                    else:
                        positions_flat[k] = float(v or 0)

                portfolio_dict = {
                    "total_value": bal.total_value,
                    "cash": bal.cash,
                    "positions": positions_flat,
                }

                # ── Deferred optimizer: run every 3 cycles, reuse cached weights ──
                _opt_interval = 3
                positions_changed = len(positions_flat) != len(
                    getattr(self, "_last_opt_positions", [])
                ) or set(positions_flat.keys()) != set(
                    getattr(self, "_last_opt_positions", [])
                )
                if (
                    self.cycle % _opt_interval == 0
                    or positions_changed
                    or not hasattr(self, "_cached_portfolio_result")
                ):
                    portfolio_result = self.risk.allocate_portfolio(
                        signals=all_signals,
                        portfolio=portfolio_dict,
                        prices=prices,
                        price_history=price_history,
                        current_positions=positions_flat,
                    )
                    self._cached_portfolio_result = portfolio_result
                    self._last_opt_positions = dict(positions_flat)
                else:
                    portfolio_result = self._cached_portfolio_result

                if portfolio_result:
                    logger.info(
                        f"  Portfolio: {len(portfolio_result.allocations)} allocations, "
                        f"VaR=${portfolio_result.portfolio_var:,.0f}, "
                        f"div_ratio={portfolio_result.diversification_ratio:.2f}, "
                        f"exposure={portfolio_result.total_exposure_pct:.1%}"
                    )
            except Exception as e:
                logger.warning(f"  Portfolio optimization failed: {e}")
                portfolio_result = None

        # ═══════════════════════════════════════════════════════
        # Phase 3: Execute trades per symbol
        # ═══════════════════════════════════════════════════════
        all_results: List[Optional[dict]] = []

        # Build allocation map from portfolio optimization
        alloc_map: Dict[str, dict] = {}
        if portfolio_result:
            for a in portfolio_result.allocations:
                # ── Weight floor for low-conviction BUYs (Kelly near-zero recovery) ──
                signal = next((s for s in all_signals if s.symbol == a.symbol), None)
                if (
                    a.weight_pct < 0.0005
                    and signal
                    and signal.action == "BUY"
                    and signal.confidence > 0.15
                    and portfolio_dict.get("total_value", 0) > 0
                ):
                    floor_weight = min(0.01, signal.confidence * 0.03)
                    a.weight_pct = max(a.weight_pct, floor_weight)
                alloc_map[a.symbol] = {
                    "side": a.side,
                    "weight_pct": a.weight_pct,
                    "quantity": a.quantity,
                    "reason": a.reason,
                }

        for sym in active_symbols:
            signal = next((s for s in all_signals if s.symbol == sym), None)
            if signal is None:
                all_results.append(None)
                continue

            order_result = None
            bal = self.exchange.get_balance()
            price = self.exchange.get_current_price(sym) or self._start_price(sym)

            # Determine effective action and size
            effective_action = signal.action
            effective_position_pct = signal.position_pct

            # Override with portfolio optimizer allocation if available
            alloc = alloc_map.get(sym)
            if alloc:
                effective_action = alloc["side"]
                effective_position_pct = alloc["weight_pct"]
                logger.info(
                    f"  {sym}: alloc {effective_action} wt={effective_position_pct:.4f} qty={alloc.get('quantity', 0):.6f}"
                )

            # Rule-playbook gate (weaponized discipline): a BUY must clear the
            # validated rule screen (regime + technical score) or it becomes HOLD.
            if self.rule_gate and effective_action == "BUY":
                if not self._rule_gate_ok(sym):
                    effective_action = "HOLD"
                    effective_position_pct = min(effective_position_pct, 0.0)
                    logger.info(
                        f"  {sym}: RULE-GATE blocks BUY (failed the validated screen)"
                    )

            # Mixture of Traders: route through the regime router. With the
            # rule-floor prior, the router picks "rule" until an expert earns
            # weight, so behavior == the rule floor today.
            # RUNWAY: under rule_primary the router is upstream of this gate
            # (decisions come from the validated rule directly), so this veto
            # is redundant — keep it only for non-rule_primary mode.
            if self.mixture and not self.rule_primary and effective_action == "BUY":
                if self._mot_router is None:
                    from mot.mixture import RegimeRouter

                    self._mot_router = RegimeRouter(rule_floor="rule", min_evidence=5)
                regime = self._mot_regime(sym)
                expert = self._mot_router.pick(regime)
                # Swarm veto (#56 Phase 3): gates SPECIALIST entries only —
                # never the rule floor ("rule") or the ADIR debate ("adir"),
                # which are not hive slots (audit 2026-08-11: the old veto sat
                # upstream of this path and froze the floor whenever an
                # unproven swarm existed). Until the router is wired to hive
                # slots, this branch never blocks.
                if expert not in ("rule", "adir"):
                    mt_d = getattr(self, "_mt_decision", None)
                    if mt_d is None or mt_d["action"] != "ALLOW":
                        effective_action = "HOLD"
                        effective_position_pct = min(effective_position_pct, 0.0)
                        logger.info(
                            f"  {sym}: MoT->{expert} ({regime}) blocked by swarm veto"
                        )
                if expert != "adir":
                    if not self._rule_gate_ok(sym):
                        effective_action = "HOLD"
                        effective_position_pct = min(effective_position_pct, 0.0)
                        logger.info(
                            f"  {sym}: MoT->{expert} ({regime}) blocks BUY (rule floor)"
                        )

            # ── SL/TP guard: block debate-driven SELL when SL/TP is active ──
            # The debate engine should BUY/HOLD; exits are SL/TP's job.
            # Only allow thesis-driven SELL if SL/TP levels are NOT set (e.g.
            # the position was opened without SL/TP, or SL/TP was already hit).
            if sym in self._sl_tp_levels:
                # Clear stale SL/TP from positions that no longer exist
                current_qty = self.exchange.get_balance().positions.get(sym, 0)
                if current_qty <= 0:
                    del self._sl_tp_levels[sym]
            # ── SL/TP guard: only block DEBATE-DRIVEN SELL when SL/TP active ──
            # Optimizer-driven SELL (trim of above-Kelly position) should NOT
            # trigger this guard — only explicit debate votes for SELL are blocked
            # so SL/TP guardrails can handle the exit.
            if signal.action == "SELL" and sym in self._sl_tp_levels:
                levels = self._sl_tp_levels[sym]
                sl = levels.get("stop_loss")
                tp = levels.get("take_profit")
                if sl or tp:
                    debate = self._cycle_debates.get(sym, {})
                    bear_conf = debate.get("bear", {}).get("conf", 0)
                    risk_data = debate.get("risk", {})
                    risk_action = risk_data.get("action", "")
                    risk_conf = risk_data.get("conf", 0)
                    # rule-primary: the rule's own SELL is the validated thesis
                    # exit (_cycle_debates stays {} — no debate pool — so the
                    # conviction gate below would block it forever).
                    rule_primary_exit = self.rule_primary and signal.action == "SELL"
                    if rule_primary_exit or bear_conf >= 0.40 or (
                        risk_action == "SELL" and risk_conf >= 0.4
                    ):
                        logger.info(
                            f"  {sym}: high-conviction SELL override "
                            f"(bear={bear_conf:.2f}, risk={risk_conf:.2f}) — clearing SL/TP"
                        )
                        del self._sl_tp_levels[sym]
                        effective_action = "SELL"
                        if alloc:
                            alloc["side"] = "SELL"
                            pos_qty = portfolio_dict.get("positions", {}).get(sym, 0)
                            if pos_qty > 0:
                                alloc["quantity"] = float(pos_qty)
                    else:
                        logger.info(
                            f"  {sym}: SELL blocked (SL/TP active: SL={sl or 'N/A'}, "
                            f"TP={tp or 'N/A'}) — low conviction (bear={bear_conf:.2f})"
                        )
                        effective_action = "HOLD"
                        effective_position_pct = 0
                        if alloc:
                            alloc["side"] = "HOLD"
                            alloc["quantity"] = 0

            # ── Committee review: adjust confidence by historical accuracy ──
            if effective_action in ("BUY", "SELL"):
                exposure = sum(
                    float(v)
                    * (self.exchange.get_current_price(k) or self._start_price(k))
                    for k, v in (bal.positions or {}).items()
                ) / max(bal.total_value, 1)
                committee = self.committee.review(
                    sym,
                    effective_action,
                    signal.confidence,
                    effective_position_pct,
                    exposure,
                )
                if not committee.approved:
                    logger.info(f"  {sym}: committee veto — {committee.notes}")
                    order_result = {"status": "rejected", "error": committee.notes}
                    all_results.append(order_result)
                    self.agent.cycle_complete(signal, order_result)
                    continue
                if committee.adjusted_confidence < signal.confidence:
                    logger.info(
                        f"  {sym}: committee ↓ conf {signal.confidence:.0%}→"
                        f"{committee.adjusted_confidence:.0%} "
                        f"(×{committee.committee_multiplier:.2f}), "
                        f"pos_pct {effective_position_pct:.3f}→{committee.adjusted_position_pct:.3f}"
                    )
                    signal.confidence = committee.adjusted_confidence
                    signal.position_pct = committee.adjusted_position_pct
                    effective_position_pct = committee.adjusted_position_pct

            if effective_action in ("BUY", "SELL"):
                try:
                    prices = {sym: price}
                    positions = {k: float(v) for k, v in (bal.positions or {}).items()}
                    portfolio = {
                        "total_value": bal.total_value,
                        "cash": bal.cash,
                        "positions": positions,
                    }

                    # Use portfolio-optimized position_pct if available
                    signal.position_pct = effective_position_pct

                    risk_result = self.risk.check(
                        signal,
                        portfolio,
                        prices,
                        current_positions=positions,
                        overrides=symbol_risk_overrides.get(sym),
                    )
                    if risk_result.approved and symbol_risk_overrides.get(sym):
                        logger.debug(
                            f"  {sym}: risk check with regime overrides "
                            f"({', '.join(f'{k}={v}' for k, v in list(symbol_risk_overrides[sym].items())[:3])})"
                        )
                    if not risk_result.approved:
                        logger.info(
                            f"  {sym}: risk rejected — {risk_result.reason} "
                            f"(pos_pct_in={effective_position_pct:.3f}, "
                            f"adj_size={risk_result.adjusted_size:.3f})"
                        )
                        order_result = {
                            "status": "rejected",
                            "error": risk_result.reason,
                        }
                    else:
                        qty = (risk_result.adjusted_size * bal.total_value) / max(
                            price, 1
                        )
                        logger.debug(
                            f"  {sym}: qty_raw={qty:.6f} (adj_size={risk_result.adjusted_size:.3f}*{bal.total_value:.0f}/{price:.2f})"
                        )
                        # If signal is HOLD but portfolio optimizer wants action, use alloc direction
                        # with risk-computed quantity (pure rebalancing).
                        # If signal has direction (BUY/SELL), use signal's risk-computed qty
                        # — the alloc quantity is a rebalance delta, not an absolute size cap.
                        if alloc and alloc.get("quantity", 0) > 0:
                            if effective_action in ("HOLD",) and alloc.get("side") in (
                                "BUY",
                                "SELL",
                            ):
                                next_action = alloc["side"]
                                qty = min(
                                    alloc["quantity"], qty
                                )  # cap at rebalance delta
                            else:
                                next_action = effective_action
                                # Don't override signal qty with rebalance delta
                                logger.debug(
                                    f"  {sym}: using signal qty={qty:.6f} (ignoring alloc delta={alloc['quantity']:.6f})"
                                )
                        else:
                            next_action = effective_action

                        if qty <= 0:
                            order_result = {
                                "status": "rejected",
                                "error": "zero quantity",
                            }
                        else:
                            order = self.exchange.place_order(
                                sym,
                                next_action.upper(),
                                round(qty, 8),
                                "market",
                                None,  # None → force _fetch_ticker_live (OB midpoint)
                            )
                            order_result = {
                                "status": order.status,
                                "order_id": order.order_id,
                                "symbol": order.symbol,
                                "side": order.side,
                                "quantity": order.quantity,
                                "price": order.price,
                                "stop_loss": risk_result.adjusted_stop,
                                "take_profit": risk_result.adjusted_tp,
                                "reason": alloc["reason"] if alloc else signal.reason,
                                "position_pct": effective_position_pct,
                                "portfolio_weight": effective_position_pct,
                            }
                            # Calculate actual fill size as % of portfolio (may differ from risk cap)
                            actual_size = (
                                (order.quantity * price / bal.total_value)
                                if bal.total_value > 0
                                else 0
                            )
                            logger.info(
                                f"  {sym}: {order.status} id={order.order_id} "
                                f"({next_action} {order.quantity:.6f} @ ${price:.2f}, "
                                f"size={risk_result.adjusted_size:.1%} risk, {actual_size:.2%} actual)"
                            )

                            if order.status == "filled":
                                if next_action == "BUY":
                                    risk_cfg = self.risk.config
                                    # ATR-based stops (Fallback: risk_result defaults)
                                    bars_raw = (
                                        self.exchange.get_bars(sym, self.timeframe, 80)
                                        if hasattr(self.exchange, "get_bars")
                                        else []
                                    )
                                    atr = (
                                        self._compute_atr_14(bars_raw)
                                        if bars_raw
                                        else 0.0
                                    )
                                    atr_mult = 3.0
                                    # RUNWAY: reproduce the VALIDATED exits
                                    # (sl 12.28% / tp 17.81%); ATR exits are a
                                    # different strategy (measured -6.8% vs
                                    # +22.2% on identical signals).
                                    if atr > 0 and not getattr(self, "_runway_mode", False):
                                        sl_atr = price - (atr * atr_mult)
                                        tp_atr = price + (atr * atr_mult * 2)
                                    else:
                                        sl_atr = price * (1 - risk_cfg.stop_loss_pct)
                                        tp_atr = price * (1 + risk_cfg.take_profit_pct)
                                    existing = self._sl_tp_levels.get(sym, {})
                                    old_qty = existing.get("qty", 0)
                                    old_entry = existing.get("entry_price", 0)
                                    if old_qty > 0 and old_entry > 0:
                                        new_qty = old_qty + order.quantity
                                        avg_price = (
                                            old_entry * old_qty + price * order.quantity
                                        ) / new_qty
                                        entry_price_val = avg_price
                                        if atr > 0 and not getattr(self, "_runway_mode", False):
                                            sl_atr = avg_price - (atr * atr_mult)
                                            tp_atr = avg_price + (atr * atr_mult * 2)
                                        else:
                                            sl_atr = avg_price * (1 - risk_cfg.stop_loss_pct)
                                            tp_atr = avg_price * (1 + risk_cfg.take_profit_pct)
                                    else:
                                        new_qty = order.quantity
                                        entry_price_val = price
                                    self._sl_tp_levels[sym] = {
                                        "stop_loss": sl_atr,
                                        "take_profit": tp_atr,
                                        "entry_price": entry_price_val,
                                        "qty": new_qty,
                                        "highest_price": price,
                                        "entry_expert": getattr(self, "_runway_mode", False) and "rule" or "adir",
                                        "entry_regime": self._mot_regime(sym),
                                        "cycle_opened": self.cycle,
                                        "exit_date": self._hold_exit_date(sym) if getattr(self, "_runway_mode", False) else None,
                                        "trailing_stop_pct": risk_cfg.trailing_stop_pct,
                                        "trailing_activation": risk_cfg.trailing_stop_activation,
                                        "max_position_cycles": risk_cfg.max_position_cycles,
                                        "position_stop_pct": risk_cfg.position_stop_pct,
                                        "portfolio_weight": effective_position_pct,
                                        "atr": atr,
                                        "atr_mult": atr_mult if atr > 0 else 0,
                                    }
                                    # ── Onchain swap routing (Uniswap V3) ──
                                    if self._onchain and self._onchain.ready:
                                        try:
                                            base, quote = (
                                                sym.split("/")
                                                if "/" in sym
                                                else (sym, "USDC")
                                            )
                                            swap_result = self._onchain.swap(
                                                from_token="USDC",
                                                to_token=base,
                                                amount=order.quantity * price,
                                            )
                                            if (
                                                swap_result
                                                and swap_result.get("status")
                                                == "success"
                                            ):
                                                logger.info(
                                                    f"  {sym}: onchain swap — "
                                                    f"{order.quantity:.6f} {base} "
                                                    f"tx={swap_result.get('tx_hash', '?')[:10]}..."
                                                )
                                        except Exception as _oe:
                                            logger.debug(
                                                f"  {sym}: onchain swap skipped ({_oe})"
                                            )
                                elif next_action == "SELL":
                                    # Record trade to journal
                                    entry_price = None
                                    entry_cycle = None
                                    if sym in self._sl_tp_levels:
                                        entry_price = self._sl_tp_levels[sym].get(
                                            "entry_price"
                                        )
                                        entry_cycle = self._sl_tp_levels[sym].get(
                                            "cycle_opened"
                                        )
                                    if entry_price and entry_price > 0:
                                        pnl_pct = (price - entry_price) / entry_price
                                        notional = order.quantity * entry_price
                                        rt_fee = self.exchange.get_fee_schedule(
                                            sym
                                        ).round_trip_cost(notional)
                                        pnl_dollar = pnl_pct * notional - rt_fee
                                        pnl_pct = (
                                            pnl_dollar / notional if notional > 0 else 0
                                        )
                                        self._trade_journal.append(
                                            {
                                                "symbol": sym,
                                                "entry_price": round(entry_price, 2),
                                                "exit_price": round(price, 2),
                                                "quantity": round(order.quantity, 8),
                                                "pnl_pct": round(pnl_pct, 4),
                                                "pnl_dollar": round(pnl_dollar, 2),
                                                "fees_paid": round(rt_fee, 2),
                                                "entry_cycle": entry_cycle
                                                or self.cycle,
                                                "exit_cycle": self.cycle,
                                                "duration_cycles": self.cycle
                                                - (entry_cycle or self.cycle),
                                                "timestamp": datetime.now(
                                                    timezone.utc
                                                ).isoformat(),
                                                "exit_reason": f"manual_{signal.reason[:40]}"
                                                if signal.reason
                                                else "manual_SELL",
                                                "signal_action": signal.action,
                                                "override_source": "portfolio_optimizer"
                                                if effective_action != signal.action
                                                else "signal",
                                            }
                                        )
                                        logger.info(
                                            f"  Trade closed [{sym}]: "
                                            f"entry=${entry_price:.2f} exit=${price:.2f} "
                                            f"PnL={pnl_pct:+.4%} (${pnl_dollar:+.2f})"
                                        )
                                        # Score: skip zero-PnL flip-flops (no skill), only score meaningful outcomes
                                        # Use effective_action (may differ from signal.action due to portfolio optimizer override)
                                        scored_action = (
                                            effective_action
                                            if effective_action in ("BUY", "SELL")
                                            else signal.action
                                        )
                                        if abs(pnl_pct) > 0.0001:
                                            self._score_prediction(
                                                sym, scored_action, pnl_pct
                                            )
                                            self.committee.record_outcome(
                                                sym, scored_action, pnl_pct > 0
                                            )
                                    # Resolve reflection on close
                                    if self.reflection:
                                        entry_price = None
                                        if sym in self._sl_tp_levels:
                                            entry_price = self._sl_tp_levels[sym].get(
                                                "entry_price"
                                            )
                                        if entry_price and entry_price > 0:
                                            pnl_pct = (
                                                price - entry_price
                                            ) / entry_price
                                            self.reflection.update_outcome(
                                                "BUY", pnl_pct
                                            )
                                            logger.info(
                                                f"  Reflection resolved: BUY on {sym} → {pnl_pct:+.4%}"
                                            )
                                    if sym in self._sl_tp_levels:
                                        pos = self.exchange.get_balance().positions.get(
                                            sym, 0
                                        )
                                        if float(pos) <= 0:
                                            del self._sl_tp_levels[sym]
                except Exception as e:
                    logger.error(f"  {sym}: order error: {e}", exc_info=True)
                    order_result = {"status": "error", "error": str(e)}

            all_results.append(order_result)

            # Notify agent per symbol
            self.agent.cycle_complete(signal, order_result or {})

        # ═══════════════════════════════════════════════════════
        # Phase 4: Post-cycle — state, flash train, reflection
        # ═══════════════════════════════════════════════════════
        primary_signal = all_signals[0] if all_signals else None
        primary_result = all_results[0] if all_results else None
        if primary_signal is None:
            primary_signal = Signal(
                action="HOLD",
                symbol=self.symbols[0],
                confidence=0.0,
                reason="no symbols",
            )

        # ── Flash trainer ──────────────────────────────────────
        if self.flash_trainer:
            if primary_signal.action == "HOLD":
                self.flash_trainer.on_hold()
            else:
                self.flash_trainer.on_trade()

            # ── Behavioral RL check (during idle/stuck cycles) ──
            # When all signals are HOLD for many consecutive cycles,
            # the agent is likely stuck in a behavioral loop. Trigger
            # reward-weighted SFT to break the paralysis.
            if self.flash_trainer.should_rl_train():
                logger.info(
                    f"Behavioral RL trigger: HOLD streak detected "
                    f"(cycle {self.cycle}), launching reward-weighted training"
                )
                try:
                    rl_result = self.flash_trainer.rl_step()
                    if rl_result.get("status") == "completed":
                        new_adapter = rl_result.get("adapter_path")
                        logger.info(
                            f"Behavioral RL: new adapter at {new_adapter} "
                            f"(version={rl_result.get('version')})"
                        )
                        # Register the new adapter so ATDL can evaluate it
                        if self.adapter_registry and new_adapter:
                            version = rl_result.get("version", "RL-V1")
                            self.adapter_registry.register(
                                version=version,
                                path=new_adapter,
                            )
                            logger.info(f"Adapter registry: registered {version}")
                except Exception as e:
                    logger.warning(f"Behavioral RL step failed: {e}")

        # ── Debate reflection ────────────────────────────────
        if self.reflection:
            self.reflection.record(
                debate_action=primary_signal.action,
                debate_confidence=primary_signal.confidence,
                regime="",
                bull_action="BUY",
                bear_action="HOLD",
                risk_verdict=primary_signal.action,
                outcome="pending",
            )

        # ── Record state with portfolio metrics ────────────────
        # Attach portfolio metrics to state
        if portfolio_result:
            bal = self.exchange.get_balance()
            import json as _json

            portfolio_metrics = {
                "diversification_ratio": portfolio_result.diversification_ratio,
                "portfolio_var": round(portfolio_result.portfolio_var, 2),
                "total_exposure_pct": portfolio_result.total_exposure_pct,
                "correlation_matrix": {
                    s: {t: round(c, 3) for t, c in pairs.items()}
                    for s, pairs in portfolio_result.correlation_matrix.items()
                },
                "kelly_fractions": {
                    s: round(w, 4) for s, w in portfolio_result.kelly_fractions.items()
                },
                "allocations": [
                    {
                        "symbol": a.symbol,
                        "side": a.side,
                        "weight_pct": a.weight_pct,
                        "quantity": a.quantity,
                        "reason": a.reason,
                    }
                    for a in portfolio_result.allocations
                ],
            }
            # Attach to the primary signal meta
            primary_signal.meta["portfolio"] = portfolio_metrics

        state = self._record_state(primary_signal, primary_result)

        # ── Adapter performance tracking ─────────────────────
        if all_signals and all_results:
            for sig, res in zip(all_signals, all_results):
                self._adapter_update_performance(sig, res)

        # ── Persist agent state every cycle (positions survive restarts)
        self._save_agent_state()

        # ── Real pattern extraction (every 10 cycles) ────────
        if self.cycle - self._last_pattern_extract >= 10:
            try:
                pats = self._real_pattern_bank.extract_patterns(
                    skip_be=True, reload=True
                )
                if pats:
                    s = self._real_pattern_bank.summary()
                    logger.debug(
                        f"RealTradePatterns: {s['count']} patterns, "
                        f"{s['win_rate']:.0%} win rate ({s['wins']}W/{s['losses']}L)"
                    )
                self._last_pattern_extract = self.cycle
            except Exception as e:
                logger.debug(f"Real pattern extraction skipped: {e}")

        # ── arXiv feature extraction (every 50 cycles) ──────
        if self.cycle - self._last_arxiv_extract >= 50:
            try:
                from data.arxiv import extract_features

                features = extract_features(
                    llama_host=self.debate.llama_host
                    if self.debate
                    else self.llama_host
                )
                if features:
                    logger.info(f"arXiv: extracted {len(features)} new trading rules")
                # Run feature validation and lifecycle maintenance
                from data.feature_integrator import validate_and_integrate

                validated, ctx = validate_and_integrate(
                    state_dir=self.state_dir,
                    trade_history=self.signal_history,
                )
                if validated:
                    logger.info(f"Feature integrator: validated {validated} features")
                self._last_arxiv_extract = self.cycle
            except Exception as e:
                logger.debug(f"arXiv feature extraction skipped: {e}")

        # ── Training scheduler evaluation (every 50 cycles) ──
        if self.cycle - self._last_training_eval >= 50:
            try:
                from training.train_scheduler import evaluate, is_idle

                decision = evaluate()
                if decision["can_train"]:
                    logger.info(
                        f"Training recommended: score={decision['score']:.2f} "
                        f"(wr={decision['metrics']['win_rate']:.0%}, "
                        f"data={decision['metrics']['examples']}, "
                        f"F&G={decision['metrics']['fear_greed']})"
                    )
                self._last_training_eval = self.cycle
            except Exception as e:
                logger.debug(f"Scheduler eval skipped: {e}")

        # ── Research idle sweep (every 200 cycles when not training) ──
        if not hasattr(self, "_last_research_sweep"):
            self._last_research_sweep = 0
        if self.cycle - self._last_research_sweep >= 200:
            try:
                from training.train_scheduler import is_idle
                from training.research_runner import should_research, run_sweep

                if is_idle() and should_research():
                    logger.info("Research idle sweep: system idle, starting sweep...")
                    result = run_sweep("data", distill=True)
                    if result.get("status") == "ok":
                        distilled = result.get("distilled", {})
                        logger.info(
                            f"Research sweep complete: manifest={result.get('manifest', 'N/A')} "
                            f"scenarios={distilled.get('total_scenarios', 0)} "
                            f"transforms={distilled.get('total_transforms', 0)} "
                            f"cumulative={distilled.get('cumulative_scenarios', '?')}"
                        )
                    elif result.get("status") == "no_findings":
                        logger.debug("Research sweep: no relevant findings this cycle")
                    else:
                        logger.warning(f"Research sweep: {result}")
                self._last_research_sweep = self.cycle
            except Exception as e:
                logger.debug(f"Research sweep skipped: {e}")
                self._last_research_sweep = self.cycle

        # ── MoT periodic evaluation (every REVIEW_HOURS) ─────
        if self.mot_coordinator and self.cycle >= 10:
            try:
                from mot.coordinator import REVIEW_HOURS

                last_review = self.mot_coordinator.state.last_review
                hours_since = 999
                if last_review:
                    try:
                        t = datetime.fromisoformat(last_review).replace(
                            tzinfo=timezone.utc
                        )
                        hours_since = (
                            datetime.now(timezone.utc) - t
                        ).total_seconds() / 3600
                    except Exception:
                        pass
                if hours_since >= REVIEW_HOURS:
                    eval_result = self.mot_coordinator.evaluate()
                    if eval_result.get("score", 0) > 0:
                        logger.info(
                            f"MoT Evaluation: score={eval_result['score']:.3f} "
                            f"decision={eval_result['decision']} v{eval_result['version']}"
                        )
                        # Apply decision to risk config
                        score = eval_result["score"]
                        decision = eval_result["decision"]
                        # ── Force-moj override ──
                        if self._mot_force and self._mot_force != "auto":
                            decision = self._mot_force
                            score = 0.85
                            logger.info(
                                f"MoT forced: {decision.upper()} — user override"
                            )
                        if decision == "iterate":
                            self.risk.config.max_position_pct = 0.03
                            self.risk.config.kelly_fraction = 0.10
                            self.risk.config.max_total_exposure = 0.20
                            self.risk.config.stop_loss_pct = 0.03
                            self.committee.risk_monitor.max_position_pct = 0.03
                            self.committee.risk_monitor.max_total_exposure = 0.20
                            logger.info(
                                "MoT applied: ITERATE — tight limits, small positions"
                            )
                        elif decision == "reduce":
                            self.risk.config.max_position_pct = 0.07
                            self.risk.config.kelly_fraction = 0.15
                            self.risk.config.max_total_exposure = 0.35
                            self.committee.risk_monitor.max_position_pct = 0.07
                            self.committee.risk_monitor.max_total_exposure = 0.35
                            logger.info("MoT applied: REDUCE — conservative sizing")
                        elif decision == "increase":
                            self.risk.config.max_position_pct = 0.20
                            self.risk.config.kelly_fraction = 0.35
                            self.risk.config.max_total_exposure = 0.70
                            self.committee.risk_monitor.max_position_pct = 0.20
                            self.committee.risk_monitor.max_total_exposure = 0.70
                            logger.info("MoT applied: INCREASE — aggressive deployment")
            except Exception as e:
                logger.debug(f"MoT evaluation skipped: {e}")

        cycle_time = time.time() - cycle_start
        self._last_cycle_time = cycle_time
        logger.info(f"Cycle {self.cycle} done in {cycle_time:.2f}s")
        logger.info(
            f"Portfolio: ${state.get('portfolio_value', 0):,.2f} "
            f"({len(state.get('positions', []))} positions)"
        )
        acc = self._signal_accuracy_summary()
        if acc["total_predictions"] >= 1:
            logger.info(
                f"Signal Accuracy: {acc['overall_accuracy_pct']:.0f}% "
                f"({acc['total_correct']}/{acc['total_predictions']})"
            )

        # ── Append ui_feed.jsonl for TUI debate/universe panels (Fork 1d) ──
        try:
            from datetime import timezone as _tz

            feed = {
                "cycle": self.cycle,
                "ts": datetime.now(_tz.utc).isoformat(),
                "universe": getattr(self, "_last_universe_pick", [])[:6],
                "debates": getattr(self, "_cycle_debates", {}),
                "signals": getattr(self, "_cycle_signals_summary", []) or [],
            }
            feed_path = Path(self.state_dir) / "ui_feed.jsonl"
            with open(feed_path, "a") as f:
                f.write(json.dumps(feed) + "\n")
            # Rotate: keep last 200 lines
            if feed_path.stat().st_size > 200 * 4096:
                lines = feed_path.read_text().splitlines()[-200:]
                feed_path.write_text("\n".join(lines) + "\n")
        except Exception as e:
            logger.debug(f"ui_feed append failed (non-critical): {e}")

        return state

    def _flash_training_step(self) -> None:
        """Run one flash-training step if conditions are right."""
        if not self.flash_trainer:
            return
        if not self.flash_trainer.should_train():
            return
        try:
            result = self.flash_trainer.step(mode="student")
            ck = self.flash_trainer.checkpoint
            logger.info(
                f"Flash-train: step={ck.total_steps} "
                f"score={result.get('score', 0):.2f} "
                f"avg={ck.avg_score:.2f} best={ck.best_score:.2f}"
            )
        except Exception as e:
            logger.debug(f"Flash-train step failed: {e}")

    def _check_auto_finetune(self) -> None:
        """Check if conditions are right for auto fine-tuning.

        Triggers when:
          1. Enough resolved reflections accumulated (>=500)
          2. No fine-tune already running
          3. Active adapter's eval_score is below threshold (<0.6)
          4. Cooldown period elapsed

        Launches finetune_cycle.py as a subprocess so it doesn't block.
        """
        # ── Poll subprocess first (before cooldown) for fast lock cleanup ──
        if self._finetune_process is not None:
            ret = self._finetune_process.poll()
            if ret is None:
                return  # still running
            self._finetune_process = None  # finished
            training_lock = Path(self.state_dir) / "training.lock"
            # Only unlink OUR OWN lock: if the scheduler holds it (age recent
            # and we never created it), leave it alone — racing would kill the
            # scheduler's retrain cycle (#47/#114).
            if training_lock.exists() and self._finetune_lock_owner:
                training_lock.unlink(missing_ok=True)
            self._finetune_lock_owner = False

        # Rate limit
        if self.cycle % self.finetune_cooldown_cycles != 0:
            return
        if self.cycle < 20:
            return

        # ── Gate on active adapter's eval_score from registry ──
        try:
            from mot.adapter_registry import AdapterRegistry

            active_reg = AdapterRegistry(self.state_dir).get_active()
            if active_reg and active_reg.eval_score >= 0.6:
                return  # active adapter is healthy, skip auto-finetune
        except Exception:
            pass

        # Don't hammer on failures
        from training.finetune_cycle import read_status, run_finetune

        status = read_status(self.state_dir)
        if status.get("status") == "training":
            return

        # The GPU scheduler owns training: if it holds training.lock (retrain
        # in progress), yield — never race the scheduler's cycle (#47/#114).
        training_lock = Path(self.state_dir) / "training.lock"
        if training_lock.exists():
            logger.info("Auto fine-tune deferred: scheduler holds training.lock")
            return

        # Get reflection stats — require >=500 resolved for real signal
        from training.data_builder import reflection_stats

        stats = reflection_stats(self.state_dir)
        resolved = stats.get("resolved", 0)
        if resolved < 500:
            return

        logger.info(f"Auto fine-tune triggered: {resolved} resolved reflections")

        # Launch subprocess
        training_lock = Path(self.state_dir) / "training.lock"
        try:
            training_lock.touch()
            self._finetune_lock_owner = True
            gpu_python = _find_gpu_python()
            proc = subprocess.Popen(
                [
                    gpu_python,
                    "-m",
                    "training.finetune_cycle",
                    "--state-dir",
                    self.state_dir,
                    "--epochs",
                    "1",
                    "--batch-size",
                    "1",
                    "--grad-accum",
                    "4",
                    "--log-level",
                    "INFO",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=str(Path(__file__).resolve().parent),
            )
            self._finetune_process = proc
            logger.info(
                f"Fine-tune subprocess started: PID={proc.pid} (python={gpu_python})"
            )
        except Exception as e:
            logger.warning(f"Failed to launch fine-tune subprocess: {e}", exc_info=True)
            if training_lock.exists():
                training_lock.unlink(missing_ok=True)

    def run(self):
        """Main event loop."""
        # Initialize progression
        self.symbols = list(STAGES[self.stage]["symbols"])
        self.stage_start = time.time()
        logger.info(
            f"OpenTrader Harness — Stage {self.stage}: {STAGES[self.stage]['label']}"
        )
        logger.info(f"Symbols: {self.symbols}")
        logger.info(f"Timeframe: {self.timeframe}")
        logger.info(f"Initial cash: ${self.initial_cash:,.2f}")
        logger.info(
            f"Agent: {self.agent.name} "
            f"{'(model)' if self.agent.config.get('use_model') else '(heuristic)'}"
        )
        if not self._llama_available:
            logger.warning(
                "MODEL UNAVAILABLE: llama endpoint %s unreachable — trading on "
                "heuristic MA signals. This is NOT model-driven trading.",
                self.llama_host,
            )

        # ── Apply MoT force immediately (don't wait 6 hours) ──
        if self._mot_force and self._mot_force != "auto":
            logger.info(f"MoT force: {self._mot_force.upper()} — applying at startup")
            if self._mot_force == "increase":
                self.risk.config.max_position_pct = 0.20
                self.risk.config.kelly_fraction = 0.35
                self.risk.config.max_total_exposure = 0.70
                self.committee.risk_monitor.max_position_pct = 0.20
                self.committee.risk_monitor.max_total_exposure = 0.70
            elif self._mot_force == "reduce":
                self.risk.config.max_position_pct = 0.07
                self.risk.config.kelly_fraction = 0.15
                self.risk.config.max_total_exposure = 0.35
                self.committee.risk_monitor.max_position_pct = 0.07
                self.committee.risk_monitor.max_total_exposure = 0.35
            elif self._mot_force == "iterate":
                self.risk.config.max_position_pct = 0.03
                self.risk.config.kelly_fraction = 0.10
                self.risk.config.max_total_exposure = 0.20
                self.committee.risk_monitor.max_position_pct = 0.03
                self.committee.risk_monitor.max_total_exposure = 0.20

        # Register signal handlers
        def _shutdown(*_):
            logger.info("Shutting down...")
            self.running = False

        signal.signal(signal.SIGINT, _shutdown)
        signal.signal(signal.SIGTERM, _shutdown)

        while self.running:
            try:
                if self.max_cycles > 0 and self.cycle >= self.max_cycles:
                    logger.info(f"Reached max cycles ({self.max_cycles})")
                    break

                self.run_cycle()
                self._consecutive_crashes = 0

                if self.running and self.cycle_interval > 0:
                    time.sleep(self.cycle_interval)

                # ── Flash-train during HOLD streaks ─────────────
                self._flash_training_step()

                # ── Coach review + Ensemble voting (every N cycles) ─
                self._coach_cycle_counter += 1
                if self.coach and self.coach.should_review(self.cycle):
                    logger.info("Coach: running periodic review...")
                    try:
                        report = self.coach.review(self.cycle)
                        if report:
                            grade = report.get("grade", "F")
                            logger.info(
                                f"  Coach grade: {grade} "
                                f"(win_rate={report.get('win_rate', 0)}%)"
                            )
                            if self.coach.is_training_needed() and grade in ("D", "F"):
                                logger.info(
                                    f"  Coach recommends retraining: "
                                    f"{self.coach.get_training_focus()}"
                                )
                            for etype, content, conf in distill_coach_report(
                                report, self.cycle
                            ):
                                self.trader_md.add_entry(
                                    etype, self.cycle, content, conf, source="coach"
                                )
                    except Exception as e:
                        logger.warning(f"Coach review failed (continuing): {e}")

                    self._coach_cycle_counter = 0

                # ── ATDL lifecycle step ──────────────────────────
                if hasattr(self, "atdl") and self.atdl:
                    try:
                        action = self.atdl.step(self.cycle)
                        if action:
                            logger.info(
                                f"ATDL action: {json.dumps(action, default=str)[:200]}"
                            )
                            for etype, content, conf in distill_atdl_action(
                                action, self.cycle
                            ):
                                self.trader_md.add_entry(
                                    etype, self.cycle, content, conf, source="atdl"
                                )
                    except Exception as e:
                        logger.warning(f"ATDL step failed (continuing): {e}")

                # ── Auto fine-tune check (every N cycles) ────
                self._check_auto_finetune()

                # ── Adapter lifecycle check (every N cycles) ─
                self._adapter_check_cycle += 1
                if self._adapter_check_cycle % 10 == 0:
                    self._check_adapter_lifecycle()

            except KeyboardInterrupt:
                logger.info("Interrupted by user")
                break
            except Exception as e:
                self._consecutive_crashes = getattr(self, "_consecutive_crashes", 0) + 1
                logger.error(
                    f"Cycle {self.cycle} crashed ({self._consecutive_crashes} consecutive): {e}",
                    exc_info=True,
                )
                self._save_agent_state()
                if self._consecutive_crashes >= 10:
                    logger.error(
                        "10 consecutive in-process crashes — exiting; systemd Restart=always will relaunch."
                    )
                    break
                time.sleep(5)

        self._summary()

    def _summary(self):
        """Print trading summary."""
        bal = self.exchange.get_balance()
        total_return = (bal.total_value - self.initial_cash) / self.initial_cash * 100
        elapsed = time.time() - self._start_time

        print("\n" + "=" * 60)
        print("OPENTRADER — Trading Summary")
        print("=" * 60)
        print(f"  Stage:        {self.stage} — {STAGES[self.stage]['label']}")
        print(f"  Symbols:      {', '.join(self.symbols)}")
        print(f"  Cycles:       {self.cycle}")
        print(f"  Duration:     {elapsed:.0f}s ({elapsed / 60:.1f}m)")
        print(f"  Initial:      ${self.initial_cash:,.2f}")
        print(f"  Final:        ${bal.total_value:,.2f}")
        print(f"  Return:       {total_return:+.2f}%")
        print(f"  Cash:         ${bal.cash:,.2f}")
        print(f"  Positions:    {len(bal.positions)}")
        print(f"  Peak:         ${self.peak_value:,.2f}")
        final_dd = (
            (self.peak_value - bal.total_value) / self.peak_value * 100
            if self.peak_value > 0
            else 0
        )
        print(f"  Max DD:       {final_dd:.2f}%")
        print("=" * 60)


def _hive_feature_vector(closes, cfg):
    """Feature vector for the Mother Trader vote, computed with the SAME
    engine features the rule screen uses (full config, real OHLCV)."""
    try:
        import numpy as np
        from setup_search.engine import _features
        if not closes:
            return np.zeros(9, dtype=np.float32)
        feat = _features(closes, closes, closes, closes, cfg)
        syms = [s for s in closes if s != "SPY"]
        if not syms:
            return np.zeros(9, dtype=np.float32)
        f = feat[syms[0]]
        row = f.iloc[-1]  # the latest bar's features — the vote's state
        return np.array([row[c] for c in
                         ["mom", "rev", "rsi", "brk", "z", "ma_dist",
                          "vol_spike", "vol_level", "momfilt"]],
                        dtype=np.float32)
    except Exception:
        return np.zeros(9, dtype=np.float32)


def _hive_regime(closes):
    """The regime clock the router uses (SPY vs its 96d MA, matching the rule)."""
    try:
        spy = closes.get("SPY")
        if spy is None or len(spy) < 96:
            return "unknown"
        ma = spy.rolling(96, min_periods=60).mean().iloc[-1]
        return "bull" if spy.iloc[-1] > ma else "bear"
    except Exception:
        return "unknown"




def main():
    # 🔧 Clear stale __pycache__ on every startup to prevent bytecode bugs
    import shutil as _shutil
    from pathlib import Path as _Path

    for _pc in _Path(__file__).parent.rglob("__pycache__"):
        _shutil.rmtree(_pc, ignore_errors=True)

    parser = argparse.ArgumentParser(description="OpenTrader Harness — event loop")
    parser.add_argument(
        "--symbol", default="BTC/USDT", help="Trading pair (for stage 1)"
    )
    parser.add_argument(
        "--symbols",
        default=None,
        help="Comma-separated symbols (overrides stage config)",
    )
    parser.add_argument("--timeframe", default="1h", help="Bar timeframe")
    parser.add_argument("--cash", type=float, default=100, help="Initial capital")
    parser.add_argument(
        "--exchange",
        default="paper",
        help="Exchange backend (paper|alpaca-paper|kraken|finnhub|coinbase|ibkr)",
    )
    parser.add_argument(
        "--stock-exchange",
        default=None,
        help="Stock exchange for multi-asset mode (ibkr|finnhub|alpaca-paper|paper). Overrides auto-detection.",
    )
    parser.add_argument(
        "--crypto-exchange",
        default=None,
        help="Crypto exchange for multi-asset mode (kraken|coinbase|paper). Overrides auto-detection.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Live trading mode: CCXT→Coinbase, real prices, paper settlement",
    )
    parser.add_argument(
        "--onchain",
        action="store_true",
        help="Route BUY signals to onchain swaps via Uniswap V3 (Base Sepolia)",
    )
    parser.add_argument(
        "--onchain-key",
        default=None,
        help="Private key for onchain wallet (generates new if not set)",
    )
    parser.add_argument(
        "--finnhub-key",
        default=None,
        help="Finnhub API key for stock data (or set FINNHUB_API_KEY env var)",
    )
    parser.add_argument("--agent", default="trading_agent", help="Agent name")
    parser.add_argument(
        "--mcp-url", default="http://127.0.0.1:8092", help="MCP server URL"
    )
    parser.add_argument(
        "--model", default=None, help="Model name for llama-swap (default from config)"
    )
    parser.add_argument(
        "--fast-model",
        default="hermes-3-llama-3.1-8b",
        help="Fast model for quicker inference",
    )
    parser.add_argument(
        "--llama-host",
        default="http://127.0.0.1:8080",
        help="llama-server direct URL (default: :8080)",
    )
    parser.add_argument(
        "--no-model", action="store_true", help="Disable model, use heuristic"
    )
    parser.add_argument("--state-dir", default=None, help="State directory")
    parser.add_argument(
        "--no-synthetic", action="store_true", help="Disable synthetic data"
    )
    parser.add_argument("--bars", type=int, default=500, help="Initial synthetic bars")
    parser.add_argument(
        "--max-cycles", type=int, default=0, help="Max cycles (0=unlimited)"
    )
    parser.add_argument(
        "--interval", type=float, default=2.0, help="Seconds between cycles"
    )
    parser.add_argument(
        "--max-daily-trades",
        type=int,
        default=500,
        help="Max trades per day (resets at UTC midnight)",
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed for data")
    parser.add_argument(
        "--backtest",
        action="store_true",
        help="Backtest mode (pre-load historical data)",
    )
    parser.add_argument(
        "--backtest-bars", type=int, default=500, help="Bars for backtest"
    )
    parser.add_argument(
        "--parallel-debate",
        action="store_true",
        help="Run Bull+Bear debate agents concurrently (~2x faster)",
    )
    parser.add_argument(
        "--debate-mode",
        default="fast",
        choices=["fast", "adir"],
        help="Debate engine mode: fast (composite, default) or adir (independent agents)",
    )
    parser.add_argument(
        "--universe-mode",
        action="store_true",
        default=True,
        help="Agent picks symbols from 50+ universe (default: on)",
    )
    parser.add_argument(
        "--no-universe",
        action="store_false",
        dest="universe_mode",
        help="Disable universe mode, use fixed stage symbols only",
    )
    parser.add_argument(
        "--universe-focus",
        type=int,
        default=6,
        help="Number of symbols to deep-debate per cycle (default: 6)",
    )
    parser.add_argument("--log-level", default="INFO", help="Log level")
    parser.add_argument(
        "--sidecar",
        action="store_true",
        help="Offload exchange and risk compute to Rust sidecar process",
    )
    parser.add_argument(
        "--sidecar-binary",
        default=None,
        help="Path to exchange-engine binary (auto-detected if not set)",
    )
    parser.add_argument(
        "--stage", type=int, default=0, help="Force progression stage (0=auto, 1-3)"
    )
    parser.add_argument(
        "--mot-force",
        default="auto",
        choices=["auto", "increase", "reduce", "maintain"],
        help="Force MoT decision (auto=let MoT decide)",
    )
    parser.add_argument(
        "--rule-gate",
        action="store_true",
        help="Weaponize the rule playbook: only act on BUY signals that pass the "
        "validated rule screen (regime + technical score). Default: off.",
    )
    parser.add_argument(
        "--mixture",
        action="store_true",
        help="Mixture of Traders: route decisions through the regime router with a "
        "rule-floor prior. The rule floor executes until another expert earns weight. "
        "Default: off (current behavior).",
    )
    parser.add_argument(
        "--rule-primary",
        action="store_true",
        help="The validated rule config is the PRIMARY signal source: it generates "
        "BUY/SELL from the validated screen (regime + score) instead of the LLM "
        "debate. The proven edge does the trading. Default: off.",
    )
    parser.add_argument(
        "--pin-risk",
        action="store_true",
        help="Runway mode: freeze the risk config. Disables the periodic param "
        "re-optimization blocks (100-cycle and 50-cycle) that silently rewrite "
        "SL/TP/sizing from crypto params — they invalidate 'live impact ~= "
        "backtest' comparisons. Default: off.",
    )
    parser.add_argument(
        "--vix-gate",
        default="strict",
        choices=["strict", "soft", "off"],
        help="VIX day-regime gate on the rule-primary fill path. strict: "
        "trade only when VIX z>=0.5 (FALSIFIED as an edge — blocks fills in "
        "calm markets). soft: z>=0.0. off: neutralized — regime logged only, "
        "never blocks entries (recommended until a generalizable gate exists). "
        "Default: strict (preserves legacy behavior).",
    )
    parser.add_argument(
        "--reset-portfolio",
        action="store_true",
        help="Explicitly wipe paper_state.json and fills_ledger.jsonl before "
        "starting. Without this flag, an existing paper_state.json is resumed "
        "(cash, positions, fills history are restored).",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )

    # Override stage symbols if --symbols provided
    _custom_symbols = False
    if args.symbols:
        custom_syms = [s.strip() for s in args.symbols.split(",")]
        for stage_num in STAGES:
            STAGES[stage_num]["symbols"] = custom_syms
        _custom_symbols = True
        logger.info(f"Custom symbols override all stages: {custom_syms}")

    # ── Live mode: shortcut for real prices + paper settlement ──
    if args.live:
        args.backtest = False
        args.no_synthetic = True
        if args.exchange == "paper":
            args.exchange = "coinbase"
        # Coinbase needs rate-limiting; other exchanges (Kraken, etc.) don't
        if args.exchange == "coinbase":
            args.interval = max(args.interval, 60.0)
            logger.info("LIVE MODE: real prices from Coinbase, paper settlement")
        else:
            logger.info(
                f"LIVE MODE: real prices from {args.exchange}, paper settlement"
            )

    # ── Onchain web3 adapter (Uniswap V3, no Coinbase) ──
    if args.onchain:
        from onchain_web3 import Web3Onchain

        _onchain = Web3Onchain(
            private_key=args.onchain_key,
            network="base-sepolia",
        )
        try:
            if _onchain.initialize():
                logger.info(
                    "ONCHAIN: Web3 wallet active on Base Sepolia — Uniswap V3 swaps enabled"
                )
                _onchain_wallet = _onchain
            else:
                logger.warning("ONCHAIN: Web3 wallet unavailable — paper-only mode")
                _onchain_wallet = None
        except Exception as _e:
            logger.warning(f"ONCHAIN: init failed ({_e}) — paper-only mode")
            _onchain_wallet = None
    else:
        _onchain_wallet = None

    harness = OpenTraderHarness(
        symbol=args.symbol,
        timeframe=args.timeframe,
        initial_cash=args.cash,
        exchange=args.exchange,
        agent_name=args.agent,
        mcp_url=args.mcp_url,
        state_dir=args.state_dir,
        synthetic_data=not args.no_synthetic,
        synthetic_bars=args.bars,
        synthetic_seed=args.seed,
        max_cycles=args.max_cycles,
        cycle_interval=args.interval,
        model=args.model,
        fast_model=args.fast_model,
        llama_host=args.llama_host,
        use_model=not args.no_model,
        backtest=args.backtest,
        backtest_bars=args.backtest_bars,
        backtest_symbol=args.symbol,
        stage=args.stage,
        mot_force=args.mot_force,
        max_daily_trades=args.max_daily_trades,
        parallel_debate=args.parallel_debate,
        debate_mode=args.debate_mode,
        universe_mode=args.universe_mode,
        universe_focus=args.universe_focus,
        sidecar=args.sidecar,
        sidecar_binary=args.sidecar_binary,
        stock_exchange=args.stock_exchange,
        crypto_exchange=args.crypto_exchange,
        rule_gate=args.rule_gate,
        mixture=args.mixture,
        rule_primary=args.rule_primary,
        vix_gate=args.vix_gate,
        reset_portfolio=args.reset_portfolio,
    )

    if _onchain_wallet:
        harness._onchain = _onchain_wallet
        logger.info("Onchain swap routing enabled for BUY signals")

    harness._pin_risk = args.pin_risk
    harness._runway_mode = True
    if args.pin_risk:
        # RUNWAY: replace the crypto-derived initial RiskConfig with the
        # VALIDATED risk contract (best.json) so live sizing/exits match the
        # backtest: risk 15%, sl 12.28%, tp 17.81%, 6 positions, 95% exposure,
        # trailing OFF, Kelly inputs = validated stats (64% win / 2.44 ratio
        # -> full Kelly ~0.49, so the 0.35-fraction cap ~0.17 does not clip 15%).
        rc = harness.risk.config
        rc.max_position_pct = 0.15
        rc.stop_loss_pct = 0.1228
        rc.take_profit_pct = 0.1781
        rc.max_total_exposure = 0.95
        rc.max_positions = 6
        rc.kelly_fraction = 0.35
        rc.default_win_prob = 0.64
        rc.default_wl_ratio = 2.44
        rc.trailing_stop_pct = 0.0
        rc.trailing_stop_activation = 0.0
        rc.position_stop_pct = 0.0
        rc.max_position_cycles = 0

    harness.run()

    if harness.sidecar_enabled and harness._sidecar_client:
        harness._sidecar_client.stop()
        logger.info("Sidecar process stopped")


if __name__ == "__main__":
    main()
