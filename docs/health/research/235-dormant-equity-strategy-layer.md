# Research — the "dormant" equity/strategy layer: what is wired to order flow, what is routing-only, what is broken

- **Ticket:** #235 (research), parent map #228 (whole-project health assessment).
- **Repo state at read time:** branch `main`, HEAD `ffe3978` (2026-09-10 08:18 -0500, "New Dashboard and Warden Implementation"). Read window 2026-09-10 ~15:45–16:05 CDT.
- **Method:** read-only. `read`/`grep`/`glob`, `gh issue view`, read-only bash (`ls`, `git log`, `wc`, `ss`, `pm2 list`, `systemctl list-timers`), and read-only import/compile checks with `.venv/bin/python3`. No harness run, no backtest, no order, no service touched, no file outside `docs/health/research/` written.
- **Provenance discipline:** every factual claim is labelled **VERIFIED (file:line)** (I read it), **READ-FROM-DOCS** (a document states it; I did not re-derive it) or **CLAIMED** (asserted somewhere, not confirmed). No number below is invented.

---

## Scope

In scope (the ticket's list, plus what it implied):

- `strategies/` — the committed tournament ports (`experts.py`, `handoff.py`, `seed_router.py`, `shadow.py`, `evolve_weights.py`, `epoch_registry.py`, `laggard.py`, `macro_features.py`, the abstract-maths ports `bayes/entropy/hurst/kalman/spectral/wavelet`, the scorers, and the 13 `fx_*.py` modules).
- `mot/` — `mixture.py`, `experts.py` and the rest of the package.
- `harness.py` (4763 lines, `wc -l`).
- `arena/`.
- The question asked: **what is wired to live order flow vs ROUTING/MONITORING-only; the honest "no validated wide-universe edge" record; which modules are importable vs dead.**

Out of scope per the ticket and AGENTS.md: the crypto paper lane, and the live↔sandbox OANDA adapter fork (ToC Q04, human-gated).

**Honest boundary on my own evidence.** The read-only bash sandbox runs under `bwrap --unshare-pid`, so `pgrep`/`ps` cannot see host processes — I could **not** observe running processes directly. Everything below about "what is running" is inferred from cron definitions, file mtimes and log tails, and I say so where it matters.

---

## Verified findings (file:line)

### F1 — PREMISE CORRECTION: `harness.py` is not dormant. It is executing right now, on synthetic prices.

The ticket frames harness.py as a dormant artifact. It is not running-idle: it is **running**, continuously, and it is a *simulation*, not live order flow.

| claim | evidence |
|---|---|
| `data/paper_state.json` was written at `2026-09-10T20:54:28Z` (≈15:54 local, i.e. minutes before this read), `cycle=37313` | VERIFIED — file content read this session |
| `data/agent_state.json` mtime `Sep 10 15:54`, `_cycle=37313`, `_stage=3`, `_initial_cash=500.0` | VERIFIED — `ls -la`; content read |
| harness.py is the writer of `agent_state.json` | VERIFIED — `harness.py:912-938` (`_save_agent_state`, `json.dump` + `os.replace`) |
| harness.py is the writer of `paper_state.json` via `StateManager` | VERIFIED — `harness.py:429` (`self.state_mgr = StateManager(state_dir)`), `harness.py:1777` (`self.state_mgr.write(...)`), `state/manager.py:27,36` (`paper_state.json` → `self.state_path`) |
| the prices are synthetic | VERIFIED — `paper_state.json.data_provenance = {"mode": "synthetic", "exchange": "paper", "synthetic_data": false, "note": "SYNTHETIC random-walk prices — NOT real market data."}` |
| the run is 19 symbols, 42 lifetime fills, 26.44% drawdown, peak $506.72, signal accuracy 4.8% (1/21) | VERIFIED — `paper_state.json.metrics` |

**Consequence.** "Dormant" is the wrong word for harness.py; the correct words are *running, on synthetic data, and not on the critical path*. The equity loop is alive and consuming cycles while producing nothing that gates anything (see F3).

**Not verified:** the supervision mechanism. There is no OpenTrader systemd unit (`systemctl list-units` shows none) and it is not under pm2 (`pm2 list` shows only `moonberg-bot`, `moonberg-dashboard`). The dashboard listener on `:8097` (AGENTS.md's FastAPI dashboard) is up (`ss -ltn`). I could not determine which process owns the harness loop — recorded as an open question (OQ-1).

### F2 — What IS wired to live order flow: the FX arm, and only the FX arm

Order-submitting modules (grep `place_order` across `strategies/`):

| module | order path | schedule |
|---|---|---|
| `fx_runner.py` | `place_order` at `:394`, `:429`, `:507`, `:547` | cron `10 17 * * 1-5` (mom-k5), `0 * * * 1-5` (`--intraday`, h1-mom) |
| `fx_challenger.py` | `:106`, `:160` | cron `25 17 * * 1-5` (c08-fade) |
| `fx_h1rev.py` | `:86`, `:133` | cron `15 * * * 1-5` |
| `fx_h4brk.py` | `:80`, `:126` | cron `30 */4 * * 1-5` |
| `fx_d1mom10.py` | `:117`, `:149` | cron `30 17 * * 1-5` |
| `fx_expert_lane.py` | `:376`, `:395` | cron `25/35/45 21 * * 1-5` (g151/g138/g137) |
| `fx_watchdog.py` | `:89` (shock-flatten) | cron `*/15 * * * 1-5` |
| `fx_crashtest.py` | `:161`, `:193` | **RETIRED 2026-09-03** — line commented out in crontab |

All VERIFIED: `place_order` call sites by grep; cron lines read from `/var/spool/cron/mrc` (lines 11, 12, 19, 22, 28, 33-commented, 39, 40, 41, 43-45). Every one of these is the **OANDA practice account** (demo money), never the equity harness universe.

Not order-submitting: `fx_shadow.py` (PURE PAPER by design, docstring `:18`), `fx_warden.py` (READ-ONLY venue access, docstring `:12-15`), `fx_review.py`, `fx_traj.py`, `fx_trail_check.py`.

**Execution corroborated** (log mtimes, same day as this read): `data/logs/fx_h1rev.log` `Sep 10 15:15` (hourly :15), `fx_watchdog.log` `Sep 10 15:45` (`*/15`), `fx_intraday.log` `Sep 10 15:00` (hourly :00), `fx_h4brk.log` `Sep 10 12:30` (`*/4` :30). VERIFIED by `ls -lat data/logs/` — the minute offsets match the cron expressions exactly.

**Zero of the equity modules (`experts.py`, `handoff.py`, `seed_router.py`, `shadow.py`, `evolve_weights.py`, `laggard.py`, `macro_features.py`, the abstract ports) contain any order path.** VERIFIED — the `place_order` grep returns only `strategies/fx_*.py` files.

### F3 — The MoT router on the harness path is monitoring-only, confirmed in code, and inert under the live config

- `harness.py:2760-2763` — docstring of `_record_router_impact`: *"Record a closed trade's pnl_pct … into the persisted live_router_state.json. **Monitoring only — the router does not gate anything on the runway.**"* VERIFIED.
- `harness.py:1618-1624` — the call site, on a closed trade, with the same comment. VERIFIED.
- `harness.py:3446` — the **only** place the router could gate a decision: `if self.mixture and not self.rule_primary and effective_action == "BUY":`. Under `rule_primary` — the live configuration per map #150 ("harness live (`rule-primary`, 0 fills)") — this branch is skipped. `harness.py:3443-3445` states this in-line: *"RUNWAY: under rule_primary the router is upstream of this gate (decisions come from the validated rule directly), so this veto is redundant — keep it only for non-rule_primary mode."* VERIFIED.
- Both router functions are wrapped in bare `except Exception: pass` (`harness.py:2793-2794`, `:2822-2823`), so any failure is silent. VERIFIED.
- `strategies/experts.py:19` — *"Status: MONITORING/ROSTER — NOT wired to live order flow."* VERIFIED.
- `strategies/lanes.py:20-22` — *"This is PAPER — no live order flow."* VERIFIED.

### F4 — But the equity *paper* lane and its accrual driver ARE running on cron, and the "improvement loop" does now close (on paper)

This is the other half of the premise correction: the strategy layer is not frozen — a scheduled paper loop accrues evidence daily.

- crontab line 5: `30 18 * * 1-5 … python3 -m strategies.lanes --write >> data/logs/lanes.log` — VERIFIED.
- crontab line 13: `35 18 * * 1-5 … python3 -m strategies.shadow_driver --once >> data/wayfinder/shadow_driver.log` — VERIFIED.
- Both ran on the last weekday: `data/logs/lanes.log` mtime `Sep 9 18:30`, `data/lanes_state.json` `Sep 9 18:30`, `data/wayfinder/shadow_driver.log` `Sep 9 18:35`, `data/live_router_state.json` `Sep 9 18:35` — the mtimes land exactly on the two cron minutes. VERIFIED (`ls -la`). (Today's 18:30/18:35 runs had not fired yet at read time — it was 16:00 local.)
- The driver's own log tail shows accrual + `RegimeRouter.step()` + weight deltas, ending `[shadow] wrote /home/mrc/opentrader/data/live_router_state.json`. Its last run reported `validated windows (n>=5): 8` (line 102 of the log) versus `0` on earlier runs (lines 50/63/76/89) — i.e. the `fwd_n ≥ min_evidence` gate has now been met for 8 (regime, expert) pairs and `step()` has actually shifted weights. VERIFIED — `grep -n` over the log.
- `data/live_router_state.json` therefore holds **live paper attribution**, not just a static seed: e.g. `track.up.rule = {sum: -3.076, n: 24}` alongside per-expert records carrying `fwd_n`. VERIFIED (file content).
- Consequence: **V10's "improvement loop … does not close" and the promotion memo's "the seam is dead code until #157 lands" are both stale.** #157 landed 2026-08-30 (`git log -1 --format=%ad -- strategies/shadow_driver.py` → 2026-08-30, commit `730d029`) and the driver is on cron. READ-FROM-DOCS for the ToC text (`data/wayfinder/toc/ledger.json`, V10); VERIFIED for the code and schedule.

**What "closes" means here, precisely:** paper lanes → `lanes_state.json` → per-lane forward 1-day return → router track → `RegimeRouter.step()` → weights. It does **not** mean live order flow, and it does **not** mean any expert is promoted: all lanes run on yfinance daily bars over the strategies' own universes (`lanes.py:4-8, 42-50`), and `epoch_registry` has no equity entry at all (F6).

### F5 — Importability / deadness matrix (read-only checks, `.venv/bin/python3 -c "import …"`)

Ticket-listed modules:

| module | import | note |
|---|---|---|
| `strategies.experts` | OK |  |
| `strategies.handoff` | OK | lazy swarm loading works |
| `strategies.seed_router` | OK | **runtime-broken**, see D1 |
| `strategies.shadow` | OK | **runtime-broken**, see D2 |
| `strategies.evolve_weights` | OK |  |
| `strategies.epoch_registry` | OK |  |
| `strategies.laggard` | OK |  |
| `strategies.macro_features` | OK |  |
| all 13 `strategies.fx_*.py` | OK | 13/13 |
| `strategies.lanes`, `lane_claims`, `expert_lifecycle`, plus `bayes`/`entropy`/`hurst`/`kalman`/`spectral`/`wavelet`/`momtrend`/`multiasset`/`scorer`/`scorer_intl`/`verify`/`evaluate`/`router_state`/`shadow_driver`/`shadow_current_alloc`/`valuehead` | OK | 29 non-FX `strategies/*.py` present; every one I tested imports |

`mot/`:

| module | import | note |
|---|---|---|
| `mot.mixture`, `mot.experts`, `mot.ensemble`, `mot.pool`, `mot.roster`, `mot.lifecycle`, `mot.coordinator`, `mot.scoring`, `mot.monitors`, `mot.coach`, `mot.adapter_registry`, `mot.dynamic_discovery`, `mot.tradable_universe`, `mot.industry_map`, `mot.reflection`, `mot.finetuned_agent`, `mot.trader_md` | OK | 17/17 |
| **`mot.hive`** | **FAIL** | `SyntaxError: from __future__ imports must occur at the beginning of the file` |

`arena/`: **19/19 OK** (`agent`, `architect`, `battle`, `curriculum`, `epoch_engine`, `grpo`, `loop`, `opponents`, `train`, `war`, `tech`, `candidates`, `export`, `view`, `build_architect_dataset`, `candidates_fullcross`, `candidates_international`, `candidates_macro`, `architect_probe`). The arena is not dead by import — it is dead by *usage*: outside `arena/` itself, the only importers are `tests/break_scenarios.py`, `tests/break_deep.py`, and `mot/experts.py:55,82` (lazy, inside functions). VERIFIED by grep.

Repo-wide compile sweep (`.venv/bin/python3` + `compile()`, read-only; `ast.parse` is *not* sufficient here because future-import placement is a compile-time, not parse-time, error — I ran both and only `compile()` caught it): **7 files in the repo cannot be compiled at all**, all for the same reason:

```
data/acquire.py:11         data/falsify.py:11      data/gpu_falsify.py:13
data/vix_gate.py:29        mot/hive.py:23          scenarios/neural.py:23
scenarios/train_generator.py:14
```

This matters because the breakage propagates: `data/refresh.py:21` imports `data.acquire`, `data/refresh.py:26` imports `data.falsify` → **`data.refresh` itself raises the SyntaxError** (VERIFIED by import check), and `data/accumulator_run.sh:8` runs `data/refresh.py` as **step 1 of a weekday 14:30 cron** under `set -euo pipefail` (`data/accumulator_run.sh:3`). Corroborating: `/tmp/opencode/accumulator.log` — the file the script appends to — **does not exist**, and `data/accumulator/catalog.db` mtime is `Sep 1 14:30`, i.e. no accumulator write in nine days. Shared root cause: the mechanical `from security.guards import …` hardening line (`# noqa: E402`, "hardening layer") was inserted *above* the existing `from __future__ import annotations` line — e.g. `mot/hive.py:21` (guards) before `mot/hive.py:23` (future).

### F6 — The promotion path exists on paper and is empty of equity

`data/epoch_registry.json` — 11 entries, **all FX**, `venue: oanda-practice*`: `fx_mom_k5_top2` (incumbent), `fx_mr_fade_ma20`, `fx_mr_fade_ma20_cot`, `fx_h1_rev_rsi2`, `fx_h4_donchian20`, `fx_mom_k10_top2`, `fx-expert-g13`/`g15` (status `fail`), `fx-expert-g151`/`g137`/`g138` (accruing). **Zero equity/strategy-layer entries.** VERIFIED (file content). The ADR-0009 registry — which AGENTS.md calls "the only active gate" — has no equity expert in it, so nothing in `strategies/experts.py::VERIFIED` or the arena can be promoted through it today.

### F7 — The honest "no validated wide-universe edge" record

All of the following are **READ-FROM-DOCS** (I did not re-run the probes; AGENTS.md forbids quoting them without re-running, so I quote them as the project's recorded verdict, not as my measurement):

- `docs/CONTEXT.md:49-51` — *"Net honest conclusion: the rule floor has no validated wide-universe edge in any feature family or macro regime tested; nothing should be promoted to best.json until a genuinely generalizing signal is found and OOS-validated."*
- `docs/CONTEXT.md:62-65` — *"Cumulative honest verdict: nothing on this data beats passive SPY buy-and-hold net of costs — not the 17-name contract, any feature family, any macro regime, or long-horizon cross-asset timing. The system's edge is not in daily-rule long-only allocation."*
- `docs/CONTEXT.md:45-48` — the one positive lead (`ff_falling` flips 5y-wide −41.8% → +6.2%) is explicitly *"DISPROVES it as an edge … a loss-REDUCER, not an edge"* (OOS walkforward 1/4 folds positive).
- `docs/CONTEXT.md:68-71` — the measurable international result is *diversification, not selection* (intl basket Calmar 0.733 vs SPY 0.472).
- ToC ledger `data/wayfinder/toc/ledger.json`: **V02** (status `known`) — universe contract does not generalize (−45.95% on 511-registry, −41.07% on 7.3k fullcross, re-verified 2026-08-23). **V06** (`known`) — *"9 prototype experts OOS-verified; laggard is champion … ROUTING/MONITORING only, never live order flow. Swarm pkl data lost; committed ports in strategies/ are the durable artifacts."* **V10** (`known`) — arena gate failing −0.57%/+0.20% vs the +1% bar (the live-accrual half of V10 is stale, see F4). **V07** (`known`) — epoch engine verdict `no-promotion`, margins +0.945%/+0.533% vs the +1% gate, epoch-2 erosion 1.006% > 0.5%.
- Independently corroborated from the artifacts themselves (VERIFIED): `data/research_gate/value_head_report.json` → `pass: false`, margins `-0.005686` and `+0.002009`; `data/arena/epoch_report.json` → epoch 1 `own_margin 0.00945`, `beats_baseline false`, `PASS false`.

So the record is consistent across four independent places (CONTEXT.md, the ToC ledger, the arena gate report, the epoch report): **the equilibrium of this project is that no equity edge has been validated, and the strategy layer's own status string says it is not wired to orders.**

### F8 — The "strategies/ ports are unimportable because the swarm .pkl was lost" defect is RESOLVED — AGENTS.md is stale

- AGENTS.md (repo instructions, "Tournament swarm" bullet) — **CLAIMED**: *"The committed `strategies/` ports (entropy/bayes/kalman/spectral/laggard) … reference the lost swarm .pkl data and are currently unimportable (defect, plumbing ticket)."*
- `data/MANIFEST.json:59-70` (`resolved_2026_08_29`) contradicts it — **READ-FROM-DOCS**: for `strategies/ (evaluate, macro_features, scorer, shadow_current_alloc, lanes)`, *"was: durable /tmp/opentrader/swarm dependencies — unimportable/hard-failing → now: all executable /tmp references removed; graceful lost-data degradation per MANIFEST (#155)"*. `data/MANIFEST.json:58` records `"known_defects": []`.
- VERIFIED, and the manifest is right: all 29 non-FX `strategies/*.py` modules import cleanly (F5). No executable `/tmp` path remains in `strategies/`; the remaining references are (a) data-tier paths under `data/evidence/swarm/` — `handoff.py:39`, `evaluate.py:33-34`, `verify.py:23-24`, `scorer.py:21-26` — and (b) prose in docstrings (`experts.py:17-19` still names `/tmp/opentrader/swarm/results/*.json`, `laggard.py:25` still names `/tmp/opentrader/swarm/agents/r1d_laggard.py`). `data/evidence/swarm/` **does not exist** (`ls`), so those modules degrade exactly as designed: import fine, raise an honest `FileNotFoundError` when asked to score. `strategies/scorer.py:37-38` is the pattern (`raise FileNotFoundError("swarm_data.pkl not found in " + …)`).

**Net:** the port modules are *importable but not re-runnable* — the distinction the ticket asked for. "Dead" is wrong; "live code over a missing evidence tier" is right.

### F9 — Other verified drifts and small breaks in the ticket's named modules

- **Stale line citation in AGENTS.md.** AGENTS.md says the bull/bear→up/down mapping is at `harness.py:2636`; it is at `harness.py:2773-2774` (`if regime not in ("up", "down"): regime = "up" if self._mot_regime(sym) == "bull" else "down"`). The same drift appears in `docs/CONTEXT.md:172` and `data/wayfinder/promotion-path-memo.md:30-35` (which cites `mot/mixture.py:66` for `RegimeRouter`; it is at `mot/mixture.py:80`). VERIFIED by reading both.
- **Regime-key duality survives.** `mot/mixture.py:96` (`regime_of`) still returns `"bull"`/`"bear"`; the persisted state is keyed `"up"`/`"down"` (`seed_router.py:60`, `shadow.py:58`, `shadow_driver.py:76`, `harness.py:2773-2774`). `mot/experts.py:96` maps `"up" if reg == "up" else "down"` — i.e. it silently coerces anything else to `down`. `RegimeRouter.regime_of` is dead in practice: only 3 references repo-wide (`mot/mixture.py:92` definition; no caller in the live tree). VERIFIED by grep.
- **Two router types still coexist** (audit defect #4 of `docs/agents/research/self-improvement-loop-audit.md:70-72` is unfixed): `mot.mixture.RegimeRouter` (impact track + `step()`) and `strategies.experts.StrategyRouter` (OOS-Calmar `pick()`), with separate state and no shared contract. VERIFIED.
- **`_intl_archive` does not exist.** `strategies/lanes.py:79` returns `_intl_archive()` in the yfinance-failure path, but no such function is defined anywhere in the file (`grep` → 1 hit, the call itself). `lanes.py:81-84` (the body that *looks* like the fallback) sits after the `try/except` and is unreachable. So the documented "falls back to the static archive" behaviour is a latent `NameError`. VERIFIED.
- **`strategies/macro_features.py:82-89`** — the `__main__` block unconditionally raises `SystemExit` ("intl_data.pkl lost to /tmp cleanup …") and the two `print` lines after it are unreachable dead code. Importable, honest, but not a runnable CLI. VERIFIED.
- **"19-symbol universe"** in strategy docstrings (`experts.py:12,87`, `lanes.py:6`, `shadow.py:24`) is accurate for the harness's *traded symbol set* (19 names in `paper_state.json.models.symbols`, consistent with `harness.py:504 self.symbols = list(STAGES[self.stage]["symbols"])`), but it is not the scout universe: `mot.industry_map.get_universe_tickers()` returns **510** names and `mot.tradable_universe.TRADABLE_UNIVERSE` is **66**. Three different counts are in circulation; the docstrings name only the narrowest one. VERIFIED by direct calls.

### F10 — The exogenous gate on the equity rule-primary fill path is wired and silently disabled

Map #92's remaining step is "wire the VIX gate into the rule_primary path". It is already wired, and it does nothing:

- `harness.py:2553-2573` constructs the gate inside `_rule_primary_signals`; `harness.py:2630-2633` uses it (`elif not is_held and ok and not vix_allow:` → HOLD, "VIX gate holds the book flat on calm days").
- `harness.py:2563-2564` selects the mode (`strict` → z ≥ 0.5, `soft` → z ≥ 0.0, `off` → neutralized); the CLI default is `strict` (`harness.py:4632-4639`).
- The construct imports `from data.vix_gate import VixGate` at `harness.py:2562`, **inside** `try: … except Exception as _e: vix_allow, vix_note = True, f"vixgate disabled ({_e})"` (`:2572-2573`). `data/vix_gate.py` fails to compile (`:27` guards import precedes `:29` `from __future__`), so **`vix_allow` is always `True`** and the gate never blocks. VERIFIED by reading all four regions plus the failed import.
- Independent of the breakage, the mode itself is contested in-file: `harness.py:2553-2559` records that the `strict` default *"FALSIFIED as an edge 2026-08-15; in calm regimes it holds the book flat and starves the meta-layer (0 fills)"*, and the CLI help (`:4636-4638`) recommends `off` *"until a generalizable gate exists"* — which is also CONTEXT.md's verdict (F7).

So the exogenous gate on the equity rule-primary fill path is (a) wired, (b) currently a no-op because of a syntax error two modules away, and (c) set to a mode the project has already documented as non-generalizing. (The rule floor's own screen — `setup_search/rule_gate.screen`, `harness.py:2546-2549` — is a separate and unaffected gate; F10 is about the exogenous layer only.) That is the sharpest illustration of this layer's health: it is not merely unused — one of its live decision inputs is off by accident.

---

## Health assessment

**Verdict: the equity/strategy layer is not dormant — it is *superseded and unterminated*.** It runs (harness on synthetic data; lanes + shadow driver on cron; arena importable), it accrues paper evidence, and none of that touches order flow. The live order flow belongs entirely to the FX arm. The honest position — no validated wide-universe edge — is recorded consistently in four places and is not contradicted by anything I read.

By group:

| group | state | basis |
|---|---|---|
| `strategies/fx_*.py` (13) | **LIVE order flow** (OANDA practice) | F2 — `place_order` call sites + cron + today's logs |
| `strategies/lanes.py`, `shadow_driver.py`, `router_state.py` | **LIVE paper accrual**, on cron, loop closed | F4 |
| `harness.py` (4763 lines) | **RUNNING**, synthetic-only; MoT seam monitoring-only and inert under `rule_primary` | F1, F3 |
| `strategies/experts.py`, `handoff.py`, `evolve_weights.py`, `seed_router.py`, `shadow.py`, `laggard.py`, `macro_features.py`, abstract-maths ports | **ROUTING/MONITORING only**; importable; not re-runnable (evidence tier absent) | F3, F5, F8 |
| `strategies/epoch_registry.py` | **LIVE registry**, but contains no equity expert | F6 |
| `mot/mixture.py`, `mot/experts.py` | importable; `RegimeRouter` reachable only from the inert harness branch and from tests; `ValueHeadExpert` is wired to `data/arena/arena_value_head.pt` but has no importer outside tests | F3, F5 |
| `mot/hive.py` | **BROKEN** (SyntaxError) | F5 |
| `arena/` (20 files) | importable, **no runtime consumer**; artifacts frozen since 2026-08-10; gate FAILING | F5, F7 |
| `data/refresh.py` + accumulator cron | **BROKEN** (SyntaxError, propagates) | F5 |

**Debt characterisation.** The interesting thing is not that the equity layer is unused — that is a legitimate decision (AGENTS.md: one lane, one gate). It is that the equity layer is *unused but scheduled and paid for*: `harness.py` burns cycles on a synthetic random walk; a 14:30 accumulator cron fails at step 1; a paper lanes + driver pair writes a router state that nothing reads for decisions. Per the 2026-08-31 postmortem rule (*"every cron/systemd job must name a recent artifact it produced or be removed … A 'loop' that emits logs but no artifacts is dead"*), the accumulator job is already condemned by the project's own rule, and the lanes/driver pair passes it only by writing `lanes_state.json`/`live_router_state.json` — artifacts with no consumer on the order path.

---

## Defects & risks

Ranked by risk to the FX arm + live account first, then quick hygiene wins, then structural debt (the parent map's ordering).

### R1 — HIGH: the 2026-08-29 hardening sweep broke 7 modules — and two live harness gates are therefore silently OFF

`data/acquire.py:11`, `data/falsify.py:11`, `data/gpu_falsify.py:13`, `data/vix_gate.py:29`, `mot/hive.py:23`, `scenarios/neural.py:23`, `scenarios/train_generator.py:14` — all `SyntaxError: from __future__ imports must occur at the beginning of the file`, caused by the `from security.guards import …` hardening line being inserted *above* the `from __future__ import annotations` line (e.g. `data/vix_gate.py:27` guards import, `:29` future import; `mot/hive.py:21` guards, `:23` future).

Three verified propagation chains:

1. **The accumulator cron is dead.** `data/refresh.py:21` imports `data.acquire`, `:26` imports `data.falsify` → `python3 -c "import data.refresh"` raises the SyntaxError → `data/accumulator_run.sh:8` (cron `30 14 * * 1-5`) fails at step 1 under `set -euo pipefail` (`data/accumulator_run.sh:3`) → the whole refresh *and* the GPU-falsify step never run. Corroboration: `/tmp/opencode/accumulator.log` (the script's log target) **does not exist**, and `data/accumulator/catalog.db` is untouched since `Sep 1 14:30`.
2. **The wayfinder-#92 VIX gate is silently neutralized on the live rule-primary fill path.** The gate *is* wired: `harness.py:2553-2573` constructs `VixGate` and computes `vix_allow`, and `harness.py:2630-2633` uses it to hold the book flat (`elif not is_held and ok and not vix_allow:`). But the construction sits behind `from data.vix_gate import VixGate` (`harness.py:2562`) inside `try: … except Exception as _e: vix_allow, vix_note = True, f"vixgate disabled ({_e})"` (`:2572-2573`). Because `data/vix_gate.py` cannot compile, **`vix_allow` is permanently `True`** on every run: the gate degrades to a no-op rather than a failure. This contradicts map #92's "Not yet specified" item, which asks for the gate to be wired into the rule-primary path — it already is, and the wiring is dead. (Independent of the breakage, `harness.py:4632-4639` and `:2553-2559` record that the `strict` mode default was itself FALSIFIED as an edge on 2026-08-15 and starves the book to 0 fills; the CLI recommends `off`. So the correct fix is a *decision* about the gate's mode, not just an import repair.)
3. **The hive / Mother-Trader veto is silently off.** `mot/hive.py` → `setup_search/mother_trader.py:38` → `harness.py:2577-2582`, which is wrapped in `try: … except Exception: self._mother_trader = None` with the note `"mt disabled (no swarm)"` at `:2583`. Confirmed firsthand: the failure is silent, not fatal. (This also answers OQ-2, now closed.)

*Fix is mechanical and low-risk (move the guards import below the `from __future__` line, or drop the now-redundant future import). Owning maps: #206 (exogenous mining loop) for the `data/` half, #92 for the VIX gate, #83/#115 for the hive half. Recommendation: repair + a regression check that asserts these modules compile, because a silent `except Exception` around an import is exactly how this went unnoticed for twelve days.*

### R2 — MEDIUM: two "port" modules import fine but are runtime-dead

- `strategies/seed_router.py:82,84` — writes to `open(p, "w")` where `p` is never assigned anywhere in the module (`grep` for an assignment returns nothing). `import strategies.seed_router` succeeds; `seed(...)` raises `NameError` on the write path. VERIFIED by reading the whole file.
- `strategies/shadow.py:72,74` — identical undefined `p`. VERIFIED. Worse: `--dry` is `store_true` with no default change and the call is `shadow(args.state_dir, dry=args.dry)`, so the **default invocation** (`python -m strategies.shadow`, dry=False) takes the broken branch. Only `--dry` works.
- Both modules post-date the single-writer refactor that introduced `router_state.py` (`evolve_weights.py:96-98` and `shadow_driver.py:153` use the correct API); they look like the two call sites the refactor missed. Neither is on cron, so there is no live blast radius — but both are referenced by AGENTS.md and CONTEXT.md as the arena handoff, so the docs currently point at two commands that crash.

### R3 — MEDIUM: `strategies/lanes.py` fallback path is a latent `NameError`

`lanes.py:79` calls `_intl_archive()`, which is not defined; `lanes.py:81-84` is unreachable. This module **is on cron** (weekdays 18:30) and it is the accrual source for the router. Today it works because yfinance succeeds (or the 24h cache is warm, `lanes.py:54-62`); on a network/TTL failure the cron fails instead of falling back to the static archive as its docstring promises. The `_load_basket` sibling (`lanes.py:87-122`) does this correctly with a stale-cache fallback — the pattern to copy.

### R4 — LOW/INFORMATIONAL: documentation drift that will mislead the next agent

- AGENTS.md's "unimportable ports" claim is 12 days stale (F8) — it is the kind of claim that gets repeated into a ticket, as it nearly did here.
- AGENTS.md/CONTEXT.md cite `harness.py:2636` for the regime mapping; it is at `:2773-2774` (F9). `promotion-path-memo.md` cites `mot/mixture.py:66/113/137` where the current lines are `:80/:113/:141` (`pick`/`step` moved with the file's growth).
- ToC **V10**'s second clause ("improvement loop … does not close") is stale as of 2026-08-30/09-09 (F4). The arena-gate clause is still true. V10 is `[known]`, so it can only be corrected by the human — flagging, not editing.
- `strategies/experts.py:17-19` and `lanes.py:6` still reference `/tmp/opentrader/swarm/...` and the "19-symbol universe" in prose.

### R5 — LOW: harness.py's MoT seam is unobservable when it fails

`harness.py:2793-2794` and `:2822-2823` swallow every exception (`except Exception: pass`) around the router record/save. During the period when `mot.hive` (and anything else) breaks, the harness emits nothing. Since the seam is monitoring-only this cannot hurt trading, but it does mean a silent monitoring outage is indistinguishable from "the router had nothing to record".

### Not a defect — the honest record

To be explicit, because tickets like this tend to drift into "the strategy layer must be wired up": **the absence of equity order flow is a documented decision, not a bug.** `strategies/experts.py:19`, `lanes.py:20-22`, ToC V06, and map #150's "Honest boundaries" all state routing/monitoring-only. The defects above are hygiene and latent-breakage items, not evidence that the equity layer should be reconnected.

---

## Links to existing maps

| map | relationship to this finding |
|---|---|
| **#228** (parent) | This is sub-ticket 235 of 9; the FX arm + governance + committed strategy layer scope is stated there, and its "existing maps referenced, not restated" list matches the cross-refs below. |
| **#150** (ultimate / self-improving regime switch) | Owns the destination this layer was built for. Its notes carry the same honest boundaries I verified (routing/monitoring-only; run the probes before quoting an edge) and the claim "harness live (`rule-primary`, 0 fills)" that F3 confirms in code. Its own decision list already records the loop as DISCONNECTED (#154); F4 updates that: the *accrual* half now runs. |
| **#115** (breeder redesign) | The breeder (`setup_search/evolution.py`) is the specialist source the hive cannot populate ("the swarm currently cannot be populated by any means"). F5 shows the hive's own registry module `mot/hive.py` is currently unimportable, which is a harder blocker underneath that map's premise — worth a line in #115 or a standalone hygiene ticket. |
| **#83** (epoch engine) | Owns `arena/epoch_engine.py` and the (epoch, expert) registry concept. F6 shows `strategies/epoch_registry.py` exists and is exercised — but entirely by FX; and F7 shows the epoch verdict is `no-promotion` (`data/arena/epoch_report.json`, epoch 1 `own_margin 0.00945`, `PASS false`). |
| **#92** (exogenous regime layer) | Its "Not yet specified" item is to wire the VIX gate into `harness.py:2420`'s rule_primary path. **Finding for that map: the gate is already wired** — `harness.py:2553-2573` (construct) and `:2630-2633` (blocks BUY) — **and is silently disabled**, because its import `from data.vix_gate import VixGate` (`:2562`) sits inside a bare `except Exception` (`:2572-2573`) and `data/vix_gate.py:27/29` cannot compile (R1). The map's remaining step is therefore not "wire it" but "decide the mode, then un-break the import": `strict` was falsified as an edge (0 fills) per `harness.py:2553-2559` and the CLI recommends `off`. |
| **#39** (MoT expert interface / router / evaluation — CLOSED) | The design this layer implements. Its decisions (minimal `ExpertDecision` interface, regime router with rule-floor prior, per-trade impact evaluation) are all present: `mot/mixture.py:26,33,80`. Its open item — "the router learning/updating mechanism" — is exactly the piece F4 shows now runs, on paper, via #157. |
| **#155 / #157** | The fixes that made `live_router_state.json` single-writer and closed the accrual loop. F4 verifies both are landed and running; F8 verifies the #155 lost-data degradation is real. |
| **#154** (self-improvement loop audit) | The audit whose 4 defects I re-checked: #2 (three writers) and #3 (/tmp dependency) are **fixed**; #1 (regime-key mismatch) is **partially** fixed (`handoff.py` now uses `up`/`down`; `mot/mixture.py:96` still emits `bull`/`bear`); #4 (two router types) is **unfixed**. |

---

## Open questions

1. **Who supervises the harness loop, and should it be?** `paper_state.json`/`agent_state.json` advance (cycle 37313, 2026-09-10T20:54Z) but there is no systemd unit and nothing in pm2, and the read-only sandbox's PID namespace hides host processes. Which process owns it, since when, and under which of the postmortem's cron-artifact rules does it survive? (A `ps`/`systemctl` check from outside the sandbox settles it in one command — outside my permission scope.)
2. ~~Is `harness.py:2578` inside a try/except?~~ **CLOSED during this research:** yes — `harness.py:2577-2582` catches everything and sets `self._mother_trader = None`, noting `"mt disabled (no swarm)"` (`:2583`). The `mot.hive` SyntaxError is silent on the harness path. Retained here only because that silent-except pattern is the mechanism behind R1.
3. **How many of the 7 uncompilable files remain reachable from a live path?** I traced `data/refresh.py` (cron — confirmed dead) and `mot/hive.py` (harness — silent, R1 chain 3). `data/vix_gate.py` is confirmed reachable (R1 chain 2, the silent VIX-gate no-op). `scenarios/neural.py`, `scenarios/train_generator.py` and `data/gpu_falsify.py` have references but I did not trace each to a live path — the accumulator's GPU step uses the *sandbox* copy `gpu_falsify_v2.py` (`data/accumulator_run.sh:13-14`), so the live-tree `data/gpu_falsify.py` may be unreferenced.
4. **Is the `ff_falling` / VIX-gate line of work still considered open by the human?** #92's map says the VIX gate is "the solution" and its remaining step is wiring it into rule_primary — but R1 shows it *is* wired and silently disabled, and `harness.py:2553-2559` records `strict` as falsified (0 fills) while recommending `off`. CONTEXT.md's honest verdict says no macro regime generalizes. Three different positions now sit on this one gate; the resolution is a human call, not a research one.
5. **Does anything consume `data/live_router_state.json` for a decision today?** My reading says no (F3: the only decision-point use is behind `not self.rule_primary`). If that is right, the lanes+driver cron is paying for an artifact with no downstream consumer — which the postmortem rule would put on the removal list. Worth confirming with whoever owns the harness config.
6. **Should the stale AGENTS.md/CONTEXT.md claims be corrected in this pass or filed separately?** (the "unimportable ports" claim, the `harness.py:2636` citation, ToC V10's loop clause.) I did not edit them: they are binding-rule documents, and V10 in particular is `[known]` and human-promoted only.
