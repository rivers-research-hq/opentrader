# OpenTrader — Architecture (canonical)

**Last verified:** 2026-08-05 | **Supersedes:** ARCHITECTURE-v1, ARCHITECTURE-v2-superseded (see `docs/archive/`)

This is the single source of truth. If a doc or config disagrees with this file, this file wins and the other is wrong.

---

## 1. Verified runtime reality (as of 2026-08-05)

Do NOT trust historical docs for ports/models. This is what `ss`/`pgrep` actually showed:

| Service | Port | Status | Notes |
|---|---|---|---|
| ollama serve | :11434 | **UP** | Only live LLM. Serves agent/architect models. |
| dashboard.py | :8097 | UP | Web UI. |
| mcp_server.py | :8092 | UP | `--exchange paper`. Imports `exchange/paper.py`, `exchange/base.py`, `risk/manager.py`, `data/regime_classifier.py`, `data/economics.py`. |
| gpu_sync.py | :5801 | UP (DEGRADED) | Proxy → backends :5802/:5803, both DOWN. No trading LLM loaded. |
| harness.py | — | **DEAD** | `health.json`: `"harness_state":"dead"`. Last launch targeted :5801 (dead proxy). |
| llama-swap | :8080 | NOT INSTALLED | `~/llama-swap/` missing; systemd unit is broken. |

**Consequence:** the live trading loop is down. The training/research stack (arena, value heads, setup_search) does NOT depend on it — it replays pkl archives via `setup_search.engine.run_backtest`.

## 2. Hardware

| GPU | Card | Backend | Role |
|---|---|---|---|
| GPU0 | RTX 3070 (8GB) | CUDA | "Mathematical arsenal" — setup_search search, value-head training, QLoRA distillation |
| GPU1 | RX 7900 GRE (16GB) | ROCm | 3-agent fleet / inference; freed VRAM reserved for the neural scenario generator |

**VRAM lock rule:** training and trading cannot coexist. Training runs in idle windows (see `training/idle_trainer.py`, `training/train_scheduler.py`).

## 3. Core architecture: MoT expert mixture with rule-floor prior

The current architecture is a **Mixture of Traders** (`mot/mixture.py`), NOT a single LLM debate engine.

```
                    ┌──────────────────────────────┐
                    │  RegimeRouter (rule-floor)   │
                    │  regime = SPY vs 200d MA     │
                    │  rule holds w=1.0 until an   │
                    │  expert EARNs weight (+0.1/  │
                    │  window, cap 0.5, reset on   │
                    │  failure)                    │
                    └──────────────┬───────────────┘
                                   │ picks per-regime
        ┌────────────┬─────────────┼──────────────┬──────────────┐
        ▼            ▼             ▼              ▼              ▼
   RuleExpert   AdirExpert   ValueHeadExpert  (future)      (future)
   (incumbent   (LLM debate   (tiny MLP V(s)→  sentiment    crypto /
    floor)       proposes)     E[fwd], TAKE if  expert       macro /
                               V(s)≥θ)                      international
```

- **Expert contract:** `ExpertDecision(action, size_pct, p_edge, evidence)` — `mot/mixture.py:17`.
- **Rule floor is primary.** An expert only gets weight after `n ≥ min_evidence` validated per-regime windows with `mean_impact > rule` (`mot/mixture.py:103`).
- **Deployable unit = tiny value-head MLPs** (929–2881 params, 3.6–11 KB). LLMs are the explainable/architect layer, not the edge.
- **Current wiring gap:** `RegimeRouter` is only exercised by the standalone demo `setup_search/mot_router.py`. No production path feeds it per-trade impacts.

## 4. The training loop: arena (adversarial self-play)

One arena iteration (`arena/train.py:24`): **battle → fit → war → relabel → gate**.

- **Candidates:** 11-dim feature rows (`mom, rev, rsi, brk, z, ma_dist, vol_spike, vol_level, momfilt, score, spy_ratio`) from 5y daily OHLCV (16 symbols + SPY regime).
- **Opponent field:** hedge-fund persona bots — Citadel (relative-value), Citron (adversarial fade), AHL (trend) — `arena/opponents.py`. Pure rules, no LLM.
- **Battle:** field-relative z-scored forward returns.
- **War:** portfolio war referee reusing `setup_search.engine.run_backtest` (~0.27s/2y, CPU). Relabels per-state advantage `δ = (r − V(s)) + (r − r_field)`, per regime window (`arena/war.py:175`).
- **Gate:** held-out discrimination `kept-mean − all-mean ≥ +1%` on BOTH regime windows (2022 bear + 2026). Currently FAILING (`+0.17% / −0.22%`).
- **Curriculum:** tiers 1–5, skill gating, carrot/stick (`arena/curriculum.py`).
- **LLM Architect:** Qwen2.5-7B+LoRA proposes the next skill (`arena/architect.py:302`), self-trained on synthetic supervisory data.

## 5. The five subsystems and their seams (the roadmap)

| # | Subsystem | File(s) | Status |
|---|---|---|---|
| a | Scenario/multiverse generator | `scenarios/` + `arena/war.py::run_multiverse_war` | **CLOSED** (2026-08-05). Parametric + neural (DoppelGANger-style) generator, tail-event library (incl. US debt ceiling), multiverse war gate wired into the arena. |
| b | Real GRPO | `arena/grpo.py` | **CLOSED**. DeepSeekMath/R1 GRPO (group-relative advantage, KL-in-loss, μ=1 form) consuming the war's deltas; wired into `arena/train.py`. |
| c | Arena → value-heads | `arena/` | PARTIAL. Arena trains + refines the MLP; two divergent checkpoints remain (`data/arena/arena_value_head.pt` is canonical for the arena; `data/research_gate/value_head.pt` is the setup_search path). Reconcile when wiring the expert roster. |
| d | Value-head → MoT roster | `mot/experts.py::ValueHeadExpert` | **CLOSED**. Wraps the arena MLP as an `Expert`. |
| e | MoT rule-floor feedback | `mot/mixture.py` + `_update_regime_router` | **CLOSED**. War per-regime impacts feed a persisted `RegimeRouter`; `momentum_gate.json` is now written on gate pass → skill `s15` reachable. |

Seams a, b, d, e are closed. Seam c (checkpoint reconciliation + the expert
*roster* generalization, Phase 4) remains.

## 6. Data & state layout

| Path | Content |
|---|---|
| `data/setup_search/ohlcv_{1y,2y,5y}.pkl` | Replay archive (16 symbols + SPY). Primary war data. |
| `data/setup_search/ledger.jsonl`, `best.json` | Config search ledger; validated rule config. |
| `data/arena/` | Arena state (code in `arena/`). Runtime artifacts gitignored. |
| `data/research_gate/` | Gate verdicts (`value_head_report.json`, `trap_holdout.json`). |
| `data/history/cycle_*.json` | Live cycle snapshots (harness dead → stale). |
| `data/models/finetune/` | LoRA adapters. `current_adapter` symlink → opentrader-data. |
| `data/fx_ledger.jsonl` | FX fills, append-only (composite-key dedup). SL/TP closes arrive as tagless `venue-reconciliation` rows via the daily runner's reconcile pass. |
| `data/fx_state.json` | mom-k5 book cache. **Cache only — venue (OANDA) is authoritative.** |
| `data/fx_crashtest.json` | Crash-lane $300-equivalent tracker. realized recomputed from venue ORDER_FILL `pl` each run (full lane epoch); unrealized from venue `unrealizedPL`. |
| `data/fx_intraday.json`, `data/fx_watchdog_state.json` | h1-mom lane cache; watchdog status cache. Venue authoritative. |
| `tui/` | The human's terminal client (npm/Ink, `tui/index.js`, `npm start`). `tui.py` at repo root is a legacy Textual artifact, NOT the human's client — see `docs/agents/tui.md`. |
| `data/defect_log.json` | Harness crash episodes (`defects`) + FX lane defects (`fx_defects`, 2026-09-02). |

## 7. Known broken/messy items (fix list)

1. `config/model_roles.json` references 6 phantom models — rewrite or delete.
2. `data/connections.json` `base_url`/`url` disagree; statuses read "disconnected" for live services.
3. `config/harness_config.json` `llama_host` points at :5801 (dead proxy).
4. Systemd units reference `llama-swap.service` but `~/llama-swap/` doesn't exist.
5. `data/health.json` `eval_lock: held_no_holder` — stale `/tmp/opentrader_eval_gate.lock` (>2h old); `ops_watchdog.py` auto-clears.
6. `harness.py` is 4260 lines — the biggest maintainability debt (deferred split).
7. Duplicate code: `onchain.py` vs `onchain_web3.py` (only `harness.py` imports `onchain`); `report_overnight.*`; `repro_volatility.py`.
8. **`exchange/oanda.py` is forked between the live tree and `opentrader-sandbox`**: live has the security guards (`security/guards.py`) + `tag` kwarg; the sandbox copy has a server-truth `get_balance` the live tree lacks (ToC Q04). Merge is a human-gated decision — do not blind-sync.
9. **Two TUI clients** (`tui/index.js` npm/Ink = the human's; `tui.py` Textual = legacy replacement artifact). Fixed twice for the wrong one — see `docs/agents/tui.md`. Candidate for deletion after human sign-off.
10. **Price-feed caches**: any cache-first price read must carry a TTL — the never-expiring pattern caused phantom entries in both the crypto lane (#159) and the OANDA adapter (#167). `exchange/live.py` `_price_cache` still has no TTL on its single-symbol path (crypto lane, out of scope until re-opened).
11. **FX lane-size attribution**: venue-reconciliation closes attribute to lanes by fill size (100/2000/5000u). If a lane changes size or a new lane trades an existing size, the matchers in `fx_crashtest.py` and `tui/index.js` silently mis-attribute. Long-term fix: stamp the originating tag onto reconciliation rows from the venue txn's `clientExtensions` (ToC Q05).
