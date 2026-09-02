# Self-improvement loop audit — arena → epoch → weight-evolution wiring

Code-read 2026-08-23. The three loop stages each exist but are **disconnected** —
there is no closed loop that turns a gate-passing MLP into an active expert, and
"weight evolution" is a one-shot static seed, not a live process.

## 1. Arena (`arena/train.py`) — the edge generator

- Loop: battle → fit → war → relabel → gate (iterations written to a report).
- **The gate is FAILING.** `data/research_gate/value_head_report.json`: `pass=false`,
  margins −0.57% (window 0–500) and +0.20% (1000–1250) — neither +1%. The
  momentum value-head MLP does not discriminate its kept trades at +1%.
- Consequence: no arena-trained expert is ever promoted; the gate write
  (`momentum_gate.json`) only fires on pass, so it stays empty.

## 2. Epoch engine (`arena/epoch_engine.py`) — standalone, not wired

- ADR-0006 prototype (ticket #84). 24-month epochs, momentum-only, CPU.
- `data/arena/epoch_report.json`: verdict `no-promotion`, both epochs FAIL
  (`gate_pass False`; margins +0.00945 / +0.00533 — under +1%, erosion OK but
  own-gate never clears).
- **Not imported by the arena loop** — it's a standalone `main()`. Its output
  feeds nothing downstream.

## 3. Breeder (`setup_search/evolution.py`) — separate GA, not wired to MoT

- Genetic specialist breeder (hive Phase 1): GA over value-head hyper-params,
  fitness on SELECT windows, gate on a HOLDOUT window. Breeds MLPs; no path
  hands a winner to the MoT roster.

## 4. Weight evolution (`strategies/evolve_weights.py`) — static, not evolving

- Computes a **one-shot** schedule from VERIFIED OOS Calmar (floor 0.174, cap
  0.5), writes `data/live_router_state.json`. There is no recurring driver; the
  only live "evolution" is `RegimeRouter.step()` (+0.1/window on validated
  windows), which requires **live attribution = closed trades** — at 0 fills it
  never fires.

## 5. The roster is hardcoded, not fed by the loop

- `strategies/experts.py::VERIFIED` = 9 experts with OOS Calmar/Sharpe/maxDD
  **hardcoded from the tournament (R1/R1c/R2)**. Nothing adds a new expert to
  it at runtime. Even if the arena/epoch/breeder gate passed, there is **no
  promotion path** from a gate-passing MLP into `VERIFIED` or
  `mot/experts.py::ValueHeadExpert`.

## 6. The harness seam (`harness.py`) — monitoring-only, 0 fills

- `_record_router_impact` (harness.py:2638) records a closed trade's pnl into
  `live_router_state.json` — explicitly "Monitoring only — the router does not
  gate anything on the runway." The `RegimeRouter` is only even instantiated on
  a closed trade; harness is `rule-primary` with 0 fills, so it never loads.

## 7. Defects / inconsistencies found (flag)

1. **Regime-key mismatch (latent bug).** `mot/mixture.RegimeRouter.regime_of()`
   returns `bull`/`bear`, but the persisted state is keyed `up`/`down`
   (`seed_router.py`, `shadow.py`, `evolve_weights.py`, and harness's
   `_record_router_impact` remaps bull→up). `handoff.py` instead uses
   `bull`/`bear`. `pick("bull")` on a state keyed `up`/`down` returns the floor
   → the seeded evidence is inert for the router's native naming.
2. **Three writers to one path.** `live_router_state.json` is written by
   `seed_router.py`, `evolve_weights.py`, AND `harness._save_router_state` —
   violating the single-writer-per-path convention (only `shadow.py` correctly
   uses the separate `live_router_state_strategies.json`). Risk of clobber.
3. **Non-durable dependency.** `handoff.py` does
   `pickle.load(open("/tmp/opentrader/swarm/swarm_data.pkl"))` at import and
   reads `/tmp/opentrader/swarm/results/*.json` — evidence lives in /tmp, not
   `data/`; a cleared /tmp breaks the handoff.
4. **Two router types.** `mot/mixture.RegimeRouter` (impact track + step) vs
   `strategies/experts.StrategyRouter` (OOS-Calmar pick) — separate state, no
   shared contract.

## 8. What "running end-to-end" minimally requires

1. A **promotion path**: gate-passing MLP (arena/epoch/breeder) → registered as
   an expert the router can select (mot/experts.py / VERIFIED).
2. **One canonical regime key** (bull/bear or up/down) across all writers + the
   router.
3. **Single writer** for `live_router_state.json` (or per-universe files).
4. A **recurring shadow driver** that accrues per-regime impact daily and calls
   `step()` — turning the static seed into actual live evolution.
5. **Durable evidence** under `data/` (move the /tmp swarm scores).

Net: the pieces are all present and individually honest, but nothing closes the
loop — today "self-improving" is "seeded once from static OOS evidence."
