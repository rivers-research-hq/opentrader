# AGENTS — OpenTrader

Two live systems. Know which one you are touching.

1. **V2 — the product build (active focus, 2026-10-07 →).** An all-Rust,
   thinkorswim-class multi-venue trading platform: the `v2/` Cargo workspace.
   Locked spec: **`v2/SPEC.md`** — every decision in it is human-locked in its
   ticket. Execution epic: **map #347** (waves W0→W5+).
2. **V1 — the research corpus + the running FX arm.** The Python engine/arena
   (`strategies/`, `scripts/`, `data/`) and the five live OANDA practice lanes.
   **Continuity only** — V1 runs untouched while V2 builds; no new V1 strategy
   work. V2 must replay V1's lane ledger through the V2 engine (**venue-parity
   gate**, SPEC §10) before any live cutover.

Read first, by area: V2 → `v2/SPEC.md`; FX → `docs/agents/fx-ops.md`;
V1 design/language → `docs/ARCHITECTURE.md` + `docs/CONTEXT.md`.

**Crypto paper-lane work is out of scope** (human decision 2026-09-02; map
#159/#160 closed out-of-scope) — do not restart it.

---

## Local model stack — the dispatch lane (2026-10-12; replaces `opentask`)

**The `opentask` card loop is dead** (retired 2026-08-31). The local-model
mechanism is now the **smart-router dispatch lane**, and it is the default home
for bounded, mechanical work — cards, memos, transcriptions, recomputes.

**Router:** `http://127.0.0.1:8080/v1` (OpenAI-compatible), managed by
`~/ai/smart-router/` (`router.py` + `model_manager.py`, one model resident at a
time on port 9099). Models:

| Model ID | Host | Context | Notes |
|---|---|---|---|
| `qwen36-35b-agentic` | GRE, MoE offload | 32K | **default**; fast, tool-calling verified |
| `qwen38-27b-agentic` | GRE, hybrid dense | 96K | bigger ctx; do NOT shrink below 98304 |

`deepseek-v4-flash` / `deepseek-v4-pro` are the paid fallback behind the router.
Verified 2026-10-13: streaming SSE ✓, tool-call deltas ✓, first token ~0.3s.

**Dispatch:** `python3 ~/ai/smart-router/dispatch_one.py <card.md> <out.json>`
— reads the card **from disk** so card text never touches a shell (backticks in
a card previously caused `EMIT:: command not found`). Artifacts land in
`~/ai/smart-router/dispatch-artifacts/`. Also reachable as the MCP tool
`dispatch` (server `smart-router`, registered in `~/.pi/agent/mcp.json`).

**The GPU serves ONE request at a time.** A second concurrent dispatch queues
behind the first and can trip the router's 600s timeout — run cards serially.

### The card contract — binding for every dispatch (`v2/tools/dispatch/`)

Every card MUST carry these sections; the integrator checks the artifact against
them **before** merging. Template: `v2/tools/dispatch/card-template.md`.

- **TASK** — one sentence + exact output path.
- **SCOPE** — ALLOWED FILES (the only files the worker may emit), FORBIDDEN
  DEPS (the worker has no network and will invent plausible ones), FORBIDDEN
  CHANGES.
- **EXACT APIS** — real signatures/field names **copied from source**, never
  paraphrased. Field names verbatim (`sym`, not `symbol`).
- **OUTPUT CONTRACT** — `EMIT: blocks` (named `=== BLOCK A ===` blocks; default)
  or `EMIT: full-file` (only when the worker was shown the complete current
  file). Say which.
- **STANDING RULES** are pre-baked in the template — do not restate them.

**Gate every artifact before integrating:**
`python3 v2/tools/dispatch/check-artifact.py <artifact.json> <card.txt> --deps "serde serde_json"`.
It **fails closed** — an unreadable artifact is a refusal, never a pass. It
catches: out-of-scope deps (including inline `nix::sys::...` paths with no `use`
line), whole-file emission when the card said blocks, dropped MUST-KEEP symbols,
and files outside ALLOWED FILES.

### The defect classes — assume all four are present in raw worker output

| Class | What it looks like | Defense |
|---|---|---|
| **Hallucinated skeleton** | Worker invents a standalone module, invents APIs (`BarsStore::new()` with no args), drops the real struct fields | `EMIT: blocks` + EXACT APIS in the card; checker catches whole-file emission |
| **Dropped symbols** | Worker rewrites a file and silently deletes existing functions | NEVER overwrite a real file with worker output — integrate manually |
| **Out-of-scope deps** | `nix`, or any crate absent from Cargo.toml | checker `--deps`; inline-path scan |
| **Fail-open gate** | A verifier that reports "clean" without reading the artifact | The #393 rule: read the artifact or refuse; unreadable ⇒ rc=1 |

**Integration is manual, always.** The worker proposes; the subscription agent
reconciles against the real APIs and compiles. A worker artifact has never once
merged unmodified.

---

## V2 build — rules of engagement

**Workspace:** `v2/` (7 crates, ~16.4k lines Rust). `cargo test --workspace`
from `v2/` is the gate — currently green.

| Crate | Responsibility |
|---|---|
| `ot-core` | deterministic event-driven engine — the engine truth (SPEC §4 contract) |
| `ot-venues` | venue-abstraction trait + `oanda` / `alpaca` adapters; attribution resolver; lane replay |
| `ot-v1-parity` | parity harness — V2 engine vs V1's recorded `run_backtest` contract |
| `ot-script` | v2script series-native DSL: lexer/parser/eval, scanner, Cranelift JIT seam |
| `ot-terminal` | egui/eframe desktop terminal (chart, scanner, Analyze, ladder) |
| `ot-mcp` | hosted MCP server — tool surface, API-key auth, per-customer metering |
| `ot-updater` | staged in-app updater — manifests, atomic swap, rollback, channels |

**Landed:** W0 engine truth · W1 FX on V2 (OANDA semantic port, ledger replay
parity) · W2 terminal alpha + DSL + Alpaca · W3 MCP server + metering · W4
Tier-3 parity (scanner, ladder/DOM, Analyze, Cranelift JIT, release pipeline).
**Next:** W5+ expansion (top-10 venue waves, desktop binaries, Pine import).

**Binding invariants:** engine contract verbatim from V1 (decisions at `t-1`,
fills at current close, per-bar dropna rank, delist force-exit) and it lands as
**proptests** — the pre-1718f33 same-bar bug inflated metrics ~4–5pp, property
tests are the defense. Backtest/live parity is a spec invariant. Clean-room RE
posture; `ThinkScript`/`think*`/`swim` naming prohibited. Access-rental, never
profit-share.

---

## GPU devices — binding (2026-09-13; CORRECTED 2026-09-15 by the human)

**Both GPUs are compute targets. The only constraint on the RX 7900 GRE is that
it must be free while the human is gaming** — that is the whole rule. A previous
session recorded this as "never a compute target", which was a misreading and
has been costing us model capability ever since.

- **RX 7900 GRE (16GB, gfx1100) — a first-class compute target, same standing as
  the 3070. Use it by default.** (Restated 2026-09-18 after TWO agent
  misreadings: "never a compute target" was wrong, and so is "keep the GRE free
  by default". The ONLY constraint: free while the human is gaming — enforced
  automatically by `game-arbiter` (Sunshine client-session detection), which
  stops and restores scoped GRE units. `warden-gre` is the exception: the human
  restarts it MANUALLY; agents must not start it.) The GRE hosts the
  smart-router models — `qwen36-35b-agentic` and `qwen38-27b-agentic` — and the
  Dream-RSI lane's Qwen3.8-27B (`:5810`, `opentrader-dream-serve.service`).
  Model file: `/var/tmp/llama-models/Qwen3.8-27B-UD-Q3_K_XL.gguf` (13.4GB).
- **RTX 3070 (8GB)** — the always-on compute GPU, via `.venv-cuda`
  (torch 2.11.0+cu128). **It is currently free**: the old residents
  (`opentrader-llama-gpu1`, `qwen3-embed`, warden) are all **masked** and
  inactive as of 2026-10-13 — `systemctl --user start` on them FAILS (masked
  units are symlinked to /dev/null). The llama/smart-router models now run on
  the GRE. So the 3070 needs no pausing before a big job; if a job needs the
  whole 8GB, just confirm nothing is resident with `gpu-run --list`.
- **Declare your device — never inherit it.** The real lesson of the 2026-09-13
  incident was a job silently landing on the GRE through the wrong venv, not the
  GRE being forbidden: the default `.venv` torch is a ROCm build whose `cuda`
  device IS the GRE, while `.venv-cuda` is CUDA/3070. Scripts must state (log or
  assert) which device they intend before initializing.
- `/etc/pip.conf` sets a global `extra-index-url` to the ROCm wheelhouse — pin
  exact variants (`torch==2.11.0+cu128`) or pip silently installs ROCm wheels
  over CUDA ones.

---

## Role division — binding

1. **Subscription agents implement the critical path directly** — V2 code,
   adapters, landings, integration — one session each. The card→review→revise
   cycle for critical-path work costs more paid tokens than doing it directly
   (measured across #155/#157/continuity, 2026-08-31).
2. **The local model owns the bounded lanes** — dispatched cards via the
   smart-router lane above. Its envelope is one bounded task per card; it is not
   an interactive implementer. **Offload aggressively**: cards, memos, recomputes,
   transcriptions, research briefs — anything mechanical. Integration of its
   output stays with the subscription agent.
3. **The human decides and gates** — ledger promotions, ADRs, live-tree
   landings, spec/decision locks. Unchanged.

**History:** the 2026-08-31 postmortem revoked Qwen3.8-27B as a *trader or coder
in the trading lanes* after three multi-day collapses; that revocation stands for
order flow and promotion authority. The dispatch lane above is a **bounded worker**
role — fresh session per card, structured output, human-integrated — and the
Dream-RSI lane (ADR-0015) is its scoped research variant. Neither opens a gate.

**Standing process rules from that postmortem (still binding):**

- Every cron/systemd job must name a recent artifact it produced, or be removed.
- **One lane, one gate** — the FX first-trader evidence path (epoch registry,
  `strategies/epoch_registry.py`) is the only active gate until Experts #0/#1 accrue.
- `headroom-proxy.service` is a *context-compression proxy* fronting `:5804` —
  NOT a Qwen trader/coder role, so the 2026-08-31 revocation does not apply to it.
  The 2026-09-07 human decision stands: it is **enabled+active**. A 2026-09-28 agent
  disabled it citing the revocation, without telling the human; that was reverted.
  `qwen38-serve.service` stays retired.

**Economics:** subscription-tier tokens are this project's scarce resource. The
local models are free and always-on but bounded — one card per session, ≤~25 tool
calls. Multi-day interactive implementer sessions are **outside that envelope**
(3 collapses, 2026-08-28..30) and no tooling extends it. Hence the split above:
mechanical work goes to the lane; integration stays with the subscription agent.

---

## Session safety — binding (incident 2026-10-12)

Full note: `docs/agents/incident-2026-10-12-tmux-view-hijack.md`.

1. **Never create tmux windows/panes in a session the human is attached to**, and
   never send keys into a pane without explicit human go-ahead for that action.
   Interactive pi testing happens ONLY in a detached agent-owned tmux server
   (`tmux -L agent-test`).
2. **Never launch a bare `pi`** — it resumes the most recent session file, which
   may be the human's live session. Use `pi --no-session` or an explicit fresh
   session for agent-side tests.
3. Two pi processes on one session file = corruption risk. If it happens: kill
   the agent-side instance FIRST, verify the file parses, tell the human.

---

## The FX arm — OANDA practice (continuity; binding rules from 2026-09-02)

**The five V1 lanes keep running untouched while V2 builds.** Cutover only after
the V2 venue-parity gate passes. Read `docs/agents/fx-ops.md` FIRST — it is the
operations map (cron/timer schedule, lifecycle contract, state-file writers,
recovery procedures). **Do not re-derive it by grepping** — that is how the
crontab got clobbered twice. Binding rules from it:

- Never rewrite the crontab wholesale — golden reference
  `data/ops/golden_crontab.txt`, drift alarms via `ops-schedule-check.timer`.
- Lifecycle changes ONLY via `strategies/expert_lifecycle.transition()`.
- **Deployment policy is ONE expert at a time at full notional** (ADR-0011).
- A cut requires flatten FIRST (`scripts/fx_lane_flatten.py`) or positions are
  orphaned.

- **Venue is authoritative.** `data/fx_state.json`, `data/fx_crashtest.json`,
  `data/fx_intraday.json` are write-through caches ("cache only" in-file).
  Positions/balance/PnL are answered from OANDA (openTrades, transactions), never
  from a cache. The dashboard `/api/fx` (FastAPI :8097) reads the venue live.
- **Lanes** (one account, owner tags via clientExtensions): `mom-k5` (daily 17:10
  UTC, 100u momentum top-2), `c08-fade` (daily 17:25, armed), `h1-mom` (hourly
  :00, 2000u H1 momentum), `crash` (hourly :30, 5000u max-margin $300-model,
  unprotected by design), `watchdog` (15 min, response-only).
  **Cron contract: `--once` means REAL mode; no flag = dry.** Never pass `--once`
  to "test".
- **Ledger**: `data/fx_ledger.jsonl` is append-only. Server-side SL/TP closes
  arrive as tagless `venue-reconciliation` rows and are attributed by the shared
  resolver (`strategies/lane_attribution.py` `resolve_fill_tag`: clientExtensions
  → orderID → tradesClosed/tradeReduced/tradeOpened chain), NOT by fill size. The
  fill-size matcher survives only as a grandfathered fallback for pre-08-31 rows;
  unresolved rows land in a loud `unattributed` bucket. The crash lane's realized
  comes from the venue journal `pl` (full-lane-epoch recompute), NOT ledger FIFO.
- **Adapter rules (`exchange/oanda.py`)**: `place_order` is truthful — no
  `orderFillTransaction` in the response means REJECTED. `get_current_price`
  always fetches fresh (a write-once never-expiring price cache caused the
  2026-09-02 phantom entries — the same no-TTL disease as the crypto lane's #159).
- **Adapter fork (ToC Q04, unresolved)**: live `exchange/oanda.py` has the
  security guards + `tag` kwarg; the sandbox copy has a server-truth
  `get_balance` the live tree lacks. Merging them is a human-gated decision.
  The V2 port (`v2/crates/ot-venues/src/oanda.rs`) carries the *semantics*, not
  the file — do not blind-sync either Python tree against it.
- **Defect log**: `data/defect_log.json` under `fx_defects`.

---

## TUI clients — the human runs the npm/Ink one (binding, 2026-09-02)

- **V1's human TUI is `tui/index.js`** (Ink/React, plain JS, zero-build): `npm
  start` in `tui/` (also `--forex`, `--calendar`). Renders `data/*` + dashboard
  `/api/fx` and `/api/calendar`. Per-lane colors/sizes/attribution live in
  `tui/index.js` (`laneStats`, `buildForex`).
- **`tui.py` (Textual, repo root) is NOT the human's client.** It is a
  replacement artifact from a prior session, restored over once already (commit
  ab66167). Editing it and reporting "the TUI is fixed" repeats the 2026-09-02
  wrong-client mistake (#166, #167 amendment).
- **V2's terminal is separate**: `v2/crates/ot-terminal` (egui). V1 TUI rules do
  not apply to it — but do not confuse the two when reporting a fix.
- Before claiming any UI fix, **confirm which artifact the human actually runs**.
- Do not delete, replace, or rename the npm client. Detail: `docs/agents/tui.md`.

---

## Agent tooling in this repo (pi extensions)

Installed at `~/.pi/agent/extensions/`; these are session infrastructure, not
project code:

| Extension | Purpose |
|---|---|
| `supervisor.ts` | work ledger — appends `~/.pi/agent/supervisor/events.jsonl`, snapshots `state.json` (calls/errors/ctx/model), renders the SUPERVISOR pane |
| `ticket-loop.ts` | ticket filing/verification/closure; hard rails — never touches `ready-for-human`/`wontfix`/maps, max 3 auto-closures per sweep, journaled to `ticket_log.jsonl` |
| `todo` | durable repo-scoped todo ledger (`~/.pi/agent/todo/<repo>.jsonl`); injected into the system prompt each turn |
| `question`, `web-fetch`, `web-search` | interactive question tool + fetch/search |

**Subagents** (`subagents_list` / `subagent`) load profiles from the installed
`pi-interactive-subagents` package. Profiles currently default to a paid
OpenRouter model — **route bounded work to the smart-router dispatch lane
instead** (rule above), or override per spawn.

---

## Agent skills

- **Issue tracker**: GitHub issues on `rivers-research-hq/opentrader` (gh CLI).
  See `docs/agents/issue-tracker.md`.
- **Triage labels**: five canonical roles — `needs-triage`, `needs-info`,
  `ready-for-agent`, `ready-for-human`, `wontfix`. See
  `docs/agents/triage-labels.md`.
- **Domain docs**: single-context — `docs/CONTEXT.md` (glossary, V1) + `docs/adr/`
  + `docs/ARCHITECTURE.md` (V1 canonical design). V2's canonical design is
  `v2/SPEC.md`. See `docs/agents/domain.md`.

---

## Quantitative claims — verify before repeating (binding)

No numeric claim about the rule floor, a config, a gate, or an "edge" is trusted
from prose. Before repeating or acting on one, re-run it. **The V1 claims below
are the historical research corpus** — V2's engine truth is the `ot-core`
proptest suite + `ot-v1-parity`; do not quote V1 backtest numbers as V2 results.

- **Rule floor / any config on the full archive**: `PYTHONPATH=/home/mrc/opentrader-sandbox /home/mrc/opentrader/.venv/bin/python3 /home/mrc/opentrader/data/evidence/rule_floor_honest.py` (repo's own `run_backtest`, 5y, all configs side by side).
- **Universe generalization**: `PYTHONPATH=/home/mrc/opentrader-sandbox /home/mrc/opentrader/.venv/bin/python3 /home/mrc/opentrader/scripts/universe_contract_test.py` — same contract on the 511-registry (466 ∩ archive) and the 7.3k-symbol fullcross archive (~25 min). The contract does NOT generalize beyond the 17 search names (−45.95% registry, −41.07% wide — re-verified 2026-08-23); treat any "edge" claim as universe-bound until proven otherwise.
- **Signal-family probe**: `PYTHONPATH=/home/mrc/opentrader-sandbox /home/mrc/opentrader/.venv/bin/python3 /home/mrc/opentrader/scripts/signal_family_probe.py` — screens every feature family the engine already has on the 5y-wide universe (~20 min). Result (2026-08-13): NO existing family generalizes under realistic fees; only new signal inputs (macro/sector-relative) are untested paths.
- **Macro-regime probe**: `PYTHONPATH=/home/mrc/opentrader-sandbox /home/mrc/opentrader/.venv/bin/python3 /home/mrc/opentrader/scripts/macro_regime_probe.py` — FRED entry gates across the promising families. ONE lead: incumbent + `ff_falling` flips 5y-wide −41.8% → +6.2% (PF 1.07, 124 trd). **OOS walkforward DISPROVES it as an edge (1/4 folds positive) — a loss-reducer, not a validatable edge.** Do NOT repeat as a claim of edge. (Script LOST to /tmp cleanup 2026-08-23 — verdict stands as recorded, closed.)
- **Wide-gated search**: `setup_search/loop.py --wide-eval --wide-min 0.0 --wide-min-trades 8 --wide-max-fee-ratio 0.5` — standing promotion requirement (5y-wide net ≥ 0, ≥ 8 wide trades, fees ≤ 50% of account). No config may become best.json without passing it. Run from the sandbox; `data/setup_search/wide_aligned_1300b.pkl` is the cached wide set.
- **Cross-asset test** (2026-08-13; script LOST — not re-runnable): 60d trend/hold across 13 asset-class proxies vs SPY buy-and-hold net of costs. Buy-and-hold beats every variant. THE benchmark is SPY buy-and-hold net of costs, not "beat iter-74".
- **International test** (2026-08-13; script LOST — not re-runnable): 10 intl assets, no-lookahead. No active edge, BUT intl basket BH beats SPY BH risk-adjusted (Calmar 0.73 vs 0.47) — diversification, not selection, is the measurable edge.
- **Engine integrity (commit 1718f33)**: `run_backtest` decisions use prior close, fills use current close (no same-bar lookahead). Any metric computed with the pre-1718f33 engine is optimistic by up to ~4–5pp. Re-verify before quoting old numbers. This contract is what V2's `ot-core` ports verbatim.
- **Contrarian finding** (2026-08-13; script LOST — not re-runnable): long the WORST-5 by 60d momentum within liquid large-caps beats buy-and-hold 3/4 folds over 2008-26 (9.1% vs 6.8% ann). It is a ROTATION tool — wins crises, loses smooth bulls. The arena should learn the regime switch, NOT a single signal.
- **Tournament swarm (R1/R1b/R1c)** (2026-08-13; swarm data + scripts LOST — not re-runnable): escalating-bar cull + OOS gauntlet. Verified leaders (US 2008-26, Calmar): spectral 1.071, copula 0.904, hurst 0.884, entropy 0.832, momtrend 0.469→0.938 OOS, multiasset 0.39→1.289 OOS. The committed `strategies/` ports are the durable artifacts — they reference the lost swarm `.pkl` data and are currently unimportable (defect, plumbing ticket). Key rule all agents confirmed: **gate-entries-only; forced exits / trailing stops / soft de-risk destroy returns.** NOT wired to the live harness.
- **R2 OOS gauntlet** (2026-08-13): 6/8 abstract winners transfer to intl symbols (fixed params). PASS: bayes 1.148, spectral 1.000, kalman 0.988, hurst 0.967, wavelet 0.803, entropy 0.667. FAIL: hmm, copula (marginal). Universal transfer = drawdown control, not raw return. Details file LOST — the PASS/FAIL list stands as recorded.
- **Arena handoff** (2026-08-13, committed): 8 OOS-verified strategies wired into the MoT layer (`strategies/experts.py`, `handoff.py`, `seed_router.py`, `shadow.py`). REGIME KEYS MUST BE `'up'`/`'down'`. HONEST BOUNDARY: daily-bar universe allocators, NOT validated on the harness's real-time 19-symbol universe — ROUTING/MONITORING only, not live order flow.
- **R1d participation round** (2026-08-13, VERIFIED): new verified expert `laggard` (momentum k5 + one 10-day laggard catch-up, both in confirmed bull breadth>0.7) — OOS Calmar 1.666, maxDD −7.5%, beats intl basket 2023-26 (+71.8% vs +64.5%). Script LOST; the committed port `strategies/laggard.py` is the durable artifact.
- **Weight evolution** (2026-08-13, committed): `strategies/evolve_weights.py` evolves the MoT weight schedule from verified OOS Calmar. Router now picks `laggard` in both regimes. ROUTING evolution, not live order flow. State: `data/live_router_state.json`.
- **`_cross_sectional_rank` fix (commit 9b7301a)**: `rank_on` configs were silently dead (0 trades) because `dropna(axis=1)` removed all columns whenever any bar had NaN. Fixed to per-bar dropna. Any prior "rank inactive" reading is invalid.
- **Walkforward report**: `PYTHONPATH=/home/mrc/opentrader-sandbox /home/mrc/opentrader/.venv/bin/python3 -m setup_search.walkforward` — its `references` rows include the ledger contract, and a `full_archive` section reports every reference over the whole span (fold-only views hide sparse regime-gated configs).
- **best.json provenance**: the ledger (`data/setup_search/ledger.jsonl`, max-score config) is the source of truth for the rule floor; `best.json` was clobbered once (2026-08-10, run af1e6d83) and is restored from the ledger. If the two disagree, flag it — do not silently trust either.
- **Probe provenance (STEP ZERO, 2026-08-23)**: canonical probe locations are declared in `data/MANIFEST.json`. `/tmp` is scratch — nothing durable references it. Probes lost to /tmp cleanup are marked LOST: their findings stand as recorded but are not re-runnable.

History: the 08-12 "rule floor falsified" report measured DEFAULT_CONFIG (5% risk, no regime), not the documented contract (15% risk, 96d regime, thresh 0.28). The contract measures +23.1% net / 5y. See `docs/CONTEXT.md` and `~/overnight-reports/opentrader-2026-08-12-session.md`.

---

## Audit gate — binding, every session (no exceptions)

1. **Verify before consuming.** Any ledger/state/DB file you read or write
   (paper_state.json, catalog.db, alt_data_cache.db, live_router_state_*,
   `dispatch-artifacts/*.json`): enumerate its writers, confirm atomicity and
   locking, identify the single source of truth. Never trust a state file's
   provenance unverified.
2. **Audit before building.** No consumer of a ledger without first auditing that
   ledger's writer set. Never extend a system whose integrity you haven't checked.
3. **Reconcile before reporting "done".** Confirm the ledgers you touched agree —
   or document the drift explicitly.
4. **No fabricated metrics.** Computed values must trace to real outcomes;
   heuristics must be labeled as heuristics. A dispatched worker's self-report is
   a claim, not evidence — the checker + `cargo test` are the evidence.
5. **Surface contradictions immediately.** If findings contradict a prior report,
   say so in the first message. Never bury it.
6. **Resource discipline.** rcheck check_environment before heavy steps;
   run_sandboxed for anything risky; never disturb running services without cause.
7. **Claims governance (ToC, 2026-08-28).** The epistemic ledger at
   `data/wayfinder/toc/` (CLI: `toc`, source `/home/mrc/ai/table-of-context/`) is
   the claims registry: repeat a number only if a `[known]` variable covers it and
   cite its bounds; otherwise run the probe (`[computable]`), record it as an open
   question (`[unknowable]`), or quarantine it as `[explore]`. Agents may add
   explore/open entries; only the human promotes a variable to `[known]`. Scope:
   `docs/adr/0007-reground-victory-path.md` — work that moves no ADR-0007 gate
   must not be started.
