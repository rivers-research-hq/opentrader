# V1 Salvage Audit — what survives the V2 rebuild (and the Rust quant ecosystem)

**Ticket:** #331 (wayfinder:research, parent #326) | **Date:** 2026-10-06 | **Author:** research subagent
**Method:** local audit of docs/ARCHITECTURE.md, docs/CONTEXT.md, docs/adr/, and key code surfaces (`setup_search/engine.py`, `strategies/experts.py`, `strategies/lane_attribution.py`, `strategies/epoch_registry.py`, `strategies/expert_lifecycle.py`, `strategies/fx_expert_lane.py`, `strategies/fx_warden.py`, `exchange/oanda.py`, `fxexpert/gate.py`); web survey of Rust crates (crates.io API + project repos, fetched 2026-10-06).

**Provenance banner (binding):** every V1 numeric claim in this dossier is
**recorded-provenance only** — it traces to the cited doc/file and was NOT
re-run this session (hard rule: no backtest re-runs). Per ToC claims
governance, repeat any number only via the registry or a fresh probe. The one
directly-verified live read is the epoch-registry lifecycle snapshot noted in
§4.6.

---

## 1. Executive summary

V1 is two systems wearing one repo: an **equity research program** that
falsified nearly every edge it tested and kept honest records of the failures,
and an **FX practice-trading arm** whose *operational discipline* (venue
authoritative, tag-attributed lanes, lifecycle state machine, forward-accrual
promotion) is genuinely battle-tested. The human's 2026-10-06 verdict —
"an unprofitable mess" — is accurate for P&L and for the equity side's
*outputs*, but the *method* and the FX arm's *plumbing discipline* are the
salvage. What should NOT carry: the dead equity harness, the crypto paper
lane, the rule-floor-as-edge, the arena/MoT machinery as built, and the LLM
trader roles (revoked 2026-08-31). The Rust ecosystem offers no turnkey
FX-first replacement for V1's semantics — the no-lookahead backtest contract
and the OANDA adapter semantics are small, well-specified, and best
clean-room ported; the only full framework candidate (NautilusTrader) is
LGPL-3.0-only with a Python control plane and no OANDA adapter, a poor fit
for a sellable clean-room product.

The map (#326) is explicit that the V2 spec must **accommodate** the running
FX arm (lanes, lifecycle, ledger rules), not disrupt it — so FX lane logic
shapes are not optional salvage; they are constraints.

---

## 2. KEEP — verified and worth carrying into V2

### 2.1 The `run_backtest` no-lookahead contract
- **What:** decisions (score, regime, gates, exits) use the PREVIOUS bar's
  close (`master[t-1]`); fills execute at the CURRENT bar's close. Warm-up
  starts one bar later so the first signal bar is fully formed. A date-guard
  makes a symbol whose series doesn't cover the signal bar inactive (not
  scored). Delisted names force-exit at their last close. Exits: TP/SL
  evaluated against the same bar's high/low, trailing peak from highs,
  max-hold, signal exit, RSI exit.
- **Where in V1:** `setup_search/engine.py:118` (`run_backtest`), the
  NO-LOOKAHEAD comment block at `setup_search/engine.py:148-153`,
  per-bar-dropna cross-sectional rank at `setup_search/engine.py:98-117`
  (the commit 9b7301a fix — column-wise dropna silently killed `rank_on`),
  delist handling at `setup_search/engine.py:196-200`.
- **Why:** this is the single most load-bearing piece of V1 engineering. The
  pre-1718f33 same-bar-execution bug inflated every earlier metric by ~4-5pp
  (docs/CONTEXT.md "Engine integrity"); the fix is the reason any V1 number
  can be trusted at all. It is small (~200 lines of core loop), fully
  specified, and directly portable to Rust as a property test suite
  (prior-close decision / current-close fill is exactly the kind of
  invariant Rust's type system and `proptest` express well).
- **Cost note:** prior-close-decision/current-close-fill is a *semantic
  choice*, not the only honest one — V2's backtest contract ticket (map
  "Not yet specified") should re-affirm it explicitly, including the
  same-bar-high/low exit evaluation.

### 2.2 The honest-negative research record (V1's biggest asset)
- **What:** the corpus of falsifications: the rule floor does not generalize
  (recorded: −45.95% on the 511-registry, −41.07% wide, docs/CONTEXT.md);
  no existing signal family generalizes under realistic fees; the `ff_falling`
  macro gate is a loss-reducer, not an edge (OOS-walkforward disproved,
  1/4 folds); buy-and-hold SPY beats every long-horizon cross-asset timing
  variant; no regime metric passes a fold-consistent screen; the transferable
  effects are *diversification*, *drawdown control*, and *regime-switching*
  (ADR-0007 decision 2 — the only thing that verified OOS).
- **Where in V1:** `docs/CONTEXT.md` (Rule floor / probes entries),
  `docs/adr/0007-reground-victory-path.md`, repro entry points
  `data/evidence/rule_floor_honest.py`, `scripts/universe_contract_test.py`,
  `scripts/signal_family_probe.py`, `scripts/macro_regime_probe.py`.
- **Why:** V1's most expensive finding is that there is no cheap edge in this
  feature space. For a *sellable* V2 platform this is product-defining
  knowledge: sell the tool/infrastructure, not a claimed edge — which aligns
  with the map's positioning. These priors prevent V2 from re-burning months
  on already-falsified searches.
- **Boundary:** all numbers recorded-provenance only; several probe scripts
  were LOST to /tmp cleanup (2026-08-23) — findings stand as recorded,
  not re-runnable (docs/CONTEXT.md "Probe provenance").

### 2.3 The OOS-verified experts roster (as research record, not live code)
- **What:** 9 prototype experts with recorded OOS transfer Calmar — bayes
  1.148, spectral 1.000, kalman 0.988, hurst 0.967, wavelet 0.803, entropy
  0.667, momtrend 0.938, multiasset 1.289, laggard 1.666 (bench intl basket
  0.501) — plus two honest OOS failures (hmm, copula) with diagnoses.
- **Where in V1:** `strategies/experts.py:38-64` (VERIFIED registry + failure
  notes), committed strategy ports `strategies/{momtrend,multiasset,spectral,
  laggard,entropy,bayes,kalman,hurst}.py`, wiring `strategies/handoff.py`,
  `strategies/seed_router.py`, `strategies/evolve_weights.py`.
- **Why:** the roster is the arena's starting evidence and the only
  fold-consistent benchmark-beating result of the project (docs/CONTEXT.md
  R1/R2/R1c/R1d). The *structural lesson* — gate-entries-only, breadth gates,
  vol-scaled multi-asset as drawdown tool, under-participation fix
  (laggard) — is a durable design prior for any V2 strategy layer.
- **Honest boundaries (must carry with the roster):** (a) daily-bar universe
  allocators, never validated on live order flow — ROUTING/MONITORING only
  (`strategies/experts.py:1-16`); (b) swarm data + scripts LOST — the
  committed ports reference lost `.pkl` data and are currently unimportable
  (AGENTS.md); (c) all numbers recorded-provenance only.

### 2.4 FX lane attribution — the shared resolver
- **What:** tag-based attribution of venue ORDER_FILLs via the chain
  clientExtensions → orderID → tradesClosed/tradeReduced/tradeOpened, with a
  LOUD `unattributed` bucket instead of silent default-crediting; the
  fill-size matcher (100u→mom-k5 etc.) survives only as a grandfathered
  fallback for pre-2026-08-31 legacy rows.
- **Where in V1:** `strategies/lane_attribution.py:54` (`resolve_fill_tag`),
  `strategies/lane_attribution.py:20` (`realized_by_tag`, full-journal walk
  with pagination — the sinceid-caps-at-1000 fix), legacy matcher
  `strategies/lane_attribution.py:82`.
- **Why:** this is the FX arm's hardest-won plumbing (mis-attribution
  corrupted the experts' evidence base, #229 D3/#250/#252). One account,
  many lanes, venue truth — any multi-strategy V2 product has exactly this
  problem. Carry the semantics verbatim.

### 2.5 Venue-authoritative state model + truthful adapter semantics
- **What:** positions/balance/PnL are answered from the venue (OANDA
  openTrades/transactions), never from write-through caches
  (`fx_state.json` etc. say "cache only" in-file). The adapter is *truthful*:
  no `orderFillTransaction` in the POST response means REJECTED (a venue
  cancels on `STOP_LOSS_ON_FILL_*` instead of filling) — a POST succeeding
  is never assumed to be a fill; `get_current_price` always fetches fresh
  (the never-expiring price cache caused the 2026-09-02 phantom entries);
  realized PnL from venue journal `pl`, NOT ledger FIFO (the venue closes
  the newest position; FIFO pairs the wrong legs).
- **Where in V1:** `exchange/oanda.py:303` (`place_order`),
  `exchange/oanda.py:411-433` (orderFillTransaction truth check),
  `exchange/oanda.py:251` (`get_current_price`), `exchange/oanda.py:502`
  (`get_balance`); the venue-authoritative rule is stated in
  docs/CONTEXT.md (FX arm section) and docs/ARCHITECTURE.md §6.
- **Why:** these are live-incident-derived invariants (phantom entries,
  orphaned positions, tagless closes), and they are exactly the class of
  bug a rebuild re-introduces unless written down as contract. There is no
  mature Rust OANDA SDK (§5) — V1's adapter is the most battle-tested OANDA
  integration we own; a clean-room Rust port of these *semantics* is the
  right move.

### 2.6 FX lifecycle discipline (state machine, promotion gates, cuts)
- **What:** the trained-expert lifecycle: registration → accruing →
  pass/cut via a single transition function; ONE expert deployed at a time
  at full notional (ADR-0011), the sole deployed expert never auto-capped;
  cut REQUIRES flatten-first (cut-before-flatten orphans positions);
  forward-accrual promotion (backtest metrics establish eligibility only;
  promotion is forward shadow accrual or human directive); the statistical
  gate design (PF/Sharpe/mean are the same statistic, cross-generation
  ranking does not persist → coherence checks + white-reality-check deflated
  bar, not a PF threshold); cadence is generation-specific (ADR-0013's
  30d→5d revert with both-metric validation at deployment time).
- **Where in V1:** `strategies/expert_lifecycle.py:134` (`transition`),
  `strategies/epoch_registry.py:65` (register; single writer, atomic
  tmp+rename, append-only log), `docs/adr/0009-expert-promotion-seam.md`,
  `docs/adr/0011-one-expert-at-a-time.md`,
  `docs/adr/0012-server-side-exits-and-live-trail.md`,
  `docs/adr/0013-rebalance-cadence-30d-and-trail-closed.md`,
  `fxexpert/gate.py:1-46` (gate redesign rationale),
  `scripts/fx_lane_flatten.py`.
- **Direct verification (2026-10-06):** epoch registry shows
  `fx-expert-hpo_c_3070` the sole `accruing` trained expert; every g-series
  expert (g13/g15/g151/g137/g138) is `cut` — consistent with the docs.
- **Why:** this is the arm's institutional memory of how not to lose
  control of a live book. The map requires V2 to *accommodate* it; the
  state-machine semantics (single writer, append-only event log,
  human-gated shadow→live boundary) translate cleanly to Rust types/traits.

### 2.7 Append-only fills ledger + ops-map-as-deliverable
- **What:** `data/fx_ledger.jsonl` is append-only with composite-key dedup;
  server-side SL/TP closes arrive as tagless `venue-reconciliation` rows
  attributed by the resolver (§2.4). Ops knowledge is a first-class
  deliverable: the operations map (schedule, writers, recovery), golden
  crontab + drift alarm (the crontab was clobbered twice).
- **Where in V1:** `docs/agents/fx-ops.md`, `data/ops/golden_crontab.txt`,
  ADR-0011 §5 ("Ops knowledge is a deliverable"), ledger contract in
  docs/CONTEXT.md.
- **Why:** V2 is specced as a *sellable multi-venue platform* — auditable
  ledgers and operator runbooks are product features, not internal notes.

### 2.8 Claims governance / epistemic hygiene
- **What:** the ToC epistemic ledger (known/computable/unknowable/explore
  statuses, human promotes to known), "validated" reserved for
  gate/walkforward-passed, honest-boundary labels on every artifact,
  lifecycle-vs-status lint, defect log discipline.
- **Where in V1:** `docs/adr/0007-reground-victory-path.md` §6,
  `data/wayfinder/toc/` (CLI `toc`), `scripts/epoch_lint.py`,
  `data/defect_log.json`, docs/CONTEXT.md "Avoid" section.
- **Why:** V1's one unambiguous success is that it stopped lying to itself
  (the 08-12 falsification reversal, the 08-13 re-grounding, the 08-31
  postmortem). A platform that vendors trading tools needs this as product
  discipline (never ship a number without provenance).

---

## 3. DROP — wreckage not worth carrying

1. **`harness.py` (4,260 lines)** — the equity live harness; dead since
   2026-09 (docs/ARCHITECTURE.md §1), never deployed to real money, the
   biggest maintainability debt on record (docs/ARCHITECTURE.md §7 item 6).
   Nothing in V2 needs a line of it.
2. **The crypto paper lane** — out of scope since 2026-09-02 (human
   decision); defects #159/#160 closed out-of-scope; the no-TTL
   `_price_cache` in `exchange/live.py` still unfixed by choice. Rebuilding
   it is explicitly out of scope for V2 (map "Out of scope").
3. **The rule floor as an edge** — `data/setup_search/best.json` (iter-74)
   does not generalize and the honest verdict is recorded; carry the
   *verdict* (§2.2), not the config, into V2. The MoT's "floor holds all
   weight" prior can survive conceptually (§4) without carrying the config.
4. **The arena/MoT training loop as built** — the +1% discrimination gate is
   currently FAILING (recorded: +0.17%/−0.22%, docs/ARCHITECTURE.md §4);
   the improvement loop is "seeded once from static OOS evidence" and does
   not close (docs/adr/0007-reground-victory-path.md context); two
   divergent value-head checkpoints remain unreconciled
   (docs/ARCHITECTURE.md §5 seam c). The adversarial-arena *concept* can be
   revisited later, but this code feeds no V2 gate.
5. **All LLM trader/coder roles and their plumbing** — Qwen2.5-7B roles
   revoked 2026-08-31 (docs/agents/postmortem-2026-08-31.md); phantom models
   in `config/model_roles.json`, dead `:5801` proxy references,
   `llama-swap.service` ghosts, `connections.json` status disagreement
   (docs/ARCHITECTURE.md §7 items 1-4). The only surviving LLM role is the
   Dream-RSI proposal-writer (ADR-0015) — §4.5.
6. **Prop/monetization plumbing as built** — FTMO demoted to conditional
   scaling (ADR-0010: the fee is paid only on a demonstrated edge; #183
   matrix shelved). Keep the economics lesson (edge is the binding
   constraint, not capital), drop the challenge-fee plumbing. C2 transmit
   hooks stay dormant (ADR-0007 §6).
7. **`tui.py` (Textual) and the V1 TUI layer generally** — `tui.py` is a
   twice-restored wrong-client artifact (docs/agents/tui.md); the human's
   real client (`tui/index.js`, npm/Ink) renders V1 state files and polls
   V1 endpoints — it is coupled to V1's shape, and V2 has its own GUI-stack
   decision pending. The *product lesson* (a fast local terminal view of
   live state) carries; the code does not.
8. **The live/sandbox `exchange/oanda.py` fork** — ToC Q04: live tree has
   security guards + `tag` kwarg, sandbox has server-truth `get_balance`;
   merge is human-gated. V2 gets one adapter with both properties by
   construction; do not replicate the fork.
9. **Stale-doc drift artifacts** — e.g. `strategies/fx_expert_lane.py:8`
   docstring still says "REBAL=30" while `REBAL = 5` at line 63 (ADR-0013
   documented the revert). Harmless, but a warning for V2: keep code docs
   generated or linted, because prose drift already misled operations once.

---

## 4. UNCERTAIN — human decides at the salvage lock

1. **The 9-expert roster's *strategies* as V2 seed content vs pure research
   record.** Ports are unimportable today (lost .pkl data); numbers are
   recorded-provenance; boundary is routing-only. Fixing the ports and
   re-validating on V2's engine is real work with unclear payoff.
2. **The fxexpert generation pipeline** (transformer scoring ~340k params,
   `fxexpert/train.py`, HPO batch scripts, `scripts/fxexp_round_v2.py`).
   Deployed output hpo_c_3070 is accruing, but the human's 2026-10-06
   "unprofitable mess" verdict is fresh; recorded deploy metrics (PF
   1.0907 / IC 0.03177, 2/3 folds — recorded-provenance only) are thin. The
   *statistical-gate discipline* (§2.6) is a clear keep; whether the model
   family and training loop carry into V2 is not.
3. **The MoT concept (rule-floor prior + experts earn weight).** Sound
   idea, never closed the loop end-to-end (§3.4). If V2 has a strategy
   weighting layer, the *invariant* (floor holds weight until forward
   evidence; `rule = 1 − expert` clamp) is worth porting as a design rule —
   the Python implementation is not.
4. **Data assets** — `ohlcv_{1y,2y,5y}.pkl` archives, the 7.3k fullcross
   archive, wide-eval cached set `wide_aligned_1300b.pkl`, FX accrual store.
   Whether they carry depends on the V2 data-vendor/licensing decision
   (map "Not yet specified": feed strategy).
5. **Dream-RSI lane (ADR-0015)** — active research corridor, proposal-only,
   its serving unit (`opentrader-dream-serve.service`) is scoped to V1 ops.
   No V2 decision needed until the human re-affirms or retires the lane.
6. **ADR-0002's deployability criterion** — the "faithful losing system is
   deployable at 1% size; returns are not the criterion" philosophy.
   Philosophically excellent; whether V2's own deployment program adopts it
   is a product/decisions question for the human.

---

## 5. Rust quant ecosystem survey (fetched 2026-10-06)

| Crate/project | License | Activity (verified) | What it is | Fit for V2 |
|---|---|---|---|---|
| **NautilusTrader** (`nautilus_trader`, crates `nautilus-core`) | **LGPL-3.0-only** (CLA; cargo-deny enforces) | Rust-native v2 in RC (`2.0.0rcN`, `master`/`nightly`/`develop`, bi-weekly releases; corporate-backed Nautech Systems; OpenSSF scorecard, SLSA-attested artifacts) | Production-grade deterministic event-driven engine: research → simulation → live with the SAME strategy code; PyO3 Python control plane; adapters incl. Interactive Brokers, Databento, crypto venues, Betfair; nanosecond backtests; **no OANDA adapter** | The only credible full-framework candidate, but: LGPL-3.0-only is a real constraint for a closed-source sellable product (Rust static linking + LGPL is legally awkward), Python remains the composition plane, and it does not speak OANDA. Adopt ideas (deterministic event-driven core, backtest/live parity), not the platform. |
| **barter-rs** ecosystem (`barter` 0.14.0, `barter-data` 0.13.0, `barter-execution` 0.9.0, `barter-instrument` 0.3.3, `barter-integration` 0.12.0) | MIT | All crates updated 2026-08-20 (crates.io API); high recent downloads (66k/59k on integration/execution) | Event-driven live/paper/backtest ecosystem; plug-in Strategy + RiskManager; mock MarketStream/ExecutionClient gives "backtest on a near-identical trading system as live" — architecturally the same idea as V1's faithful-replica principle (ADR-0001) | Best *pattern* donor for V2's paper/live parity. Caveats: `barter-data`/`barter-execution` are crypto-exchange focused (OANDA would be a custom adapter via `barter-integration`), and the repo carries an explicit educational-purpose disclaimer ("not intended for commercial deployment, live trading, or production use") — a legal flag for a sellable V2 embedding it. |
| **hftbacktest** (nkaz001) 0.9.4 | MIT | 2025-12-10 release; steady cadence since 2024; modest downloads (~25k) | HFT/market-making backtester with L2/L3 order books, queue positions, latencies; live feature with Binance/Bybit examples | Execution-realism reference (latency/order models), but L2/L3 crypto microstructure is far beyond V1's daily/H1-bar semantics. Consult, don't adopt. |
| **polars** 0.55.2 | MIT | 2026-08-06 release; 15.3M downloads, ~2.7M recent | Arrow-based DataFrame engine | The obvious Rust data layer for V2's research/backtest data plane. Mature, no reservations. |
| **OANDA Rust clients** (`oanda` 0.1.0, `oanda-rs` 0.2.2, `oanda-v20-openapi` 0.2.1, `oanda-v20-rs` 0.1.2, `fxoanda` 0.2.0) | various | All tiny: `oanda` dead since 2023; `oanda-rs` created 2026-07 (unproven, ~77 downloads); `fxoanda` 2019 conversion-focused; generated OpenAPI clients at best | OANDA v20 REST/streaming wrappers | **None is mature.** V1's `exchange/oanda.py` (truthful fill semantics, fresh prices, clientExtensions tagging, venue-truth balance — §2.5) is the best OANDA integration knowledge in the building. Clean-room Rust port of its semantics beats adopting any of these. |
| **bottom-dollar** | — | **Does not exist on crates.io** (checked 2026-10-06; it is a Python framework inspired by barter) | — | Listed to preempt confusion in later tickets. |
| **lfest** 0.138.4 | — | 202 versions, single-maintainer, active | Leveraged perpetual-futures exchange simulator for backtesting | Crypto-perp niche, not FX; not a candidate. |

**Ecosystem verdict:** there is no turnkey Rust crate that covers an
FX-first, OANDA-speaking, no-lookahead-semantics trading platform. V1's
core pieces are small and well-specified precisely because the semantics
(not the frameworks) were the work: the backtest loop (~200 LOC of logic),
the OANDA adapter semantics, the attribution resolver, the lifecycle state
machine. The build-vs-buy question reduces to licensing and product surface:
if V2 is closed-source commercial, Nautilus (LGPL) and barter (educational
disclaimer) are effectively excluded as embedded dependencies; if V2 is
open-core or the human accepts those terms, barter's mock-execution parity
architecture is the strongest donation candidate.

---

## 6. Open questions for the salvage-lock grilling ticket

1. **Roster status:** does the 9-expert OOS roster carry into V2 as seed
   strategies (requiring port-repair + re-validation on the V2 engine), or
   as research-record only (§4.1)?
2. **Backtest contract:** does V2 adopt the prior-close-decision /
   current-close-fill contract verbatim, including same-bar high/low
   exit evaluation and the per-bar rank/date-guard semantics (§2.1)? This
   graduates the map's "V2 backtest engine contract" item.
3. **Licensing stance:** is V2 closed-source commercial? This single answer
   decides Nautilus/barter viability (§5) and therefore most of the
   build-vs-buy surface.
4. **FX-arm bridge:** the running V1 FX arm must be accommodated, not
   disrupted — does V2 speak its protocols (clientExtensions tagging,
   resolver semantics, append-only ledger schema, lifecycle registry), or
   wrap them at a seam? What is the interop story while both run?
5. **Edge vs tool positioning:** do V1's honest negatives (nothing beat
   buy-and-hold under fees) become explicit V2 product constraints — sell
   the platform, never a claimed edge (§2.2)? This aligns with the map's
   "sellable, multi-venue platform" destination.
6. **Data carry-over:** which V1 archives (ohlcv/fullcross/accrual store)
   move to V2, pending the data-vendor strategy ticket?
7. **fxexpert pipeline:** keep the generation/training pipeline, or only
   its statistical-gate discipline (deflated bar, coherence checks,
   forward accrual) (§4.2)?
8. **MoT concept:** does the rule-floor-prior/experts-earn-weight invariant
   carry as a V2 design rule, or drop with the arena (§4.3)?
9. **Dream-RSI lane:** re-affirm or retire in the V2 world (§4.5)?

---

*All V1 numeric claims above are recorded-provenance (see banner). Local
claims cite file paths; ecosystem claims cite crates.io API / project repos
fetched 2026-10-06. This dossier is a recommendation set only — the human
locks the salvage list.*
