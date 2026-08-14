# CONTEXT — OpenTrader's shared language

Terms as this project actually uses them. When agents or issues name a concept,
use the term below; don't drift to synonyms the glossary avoids.

## The trader

- **Rule floor** — the long-only rule (data/setup_search/best.json).
  The incumbent. Holds all weight until an expert earns it.
  The 08-12 falsification (−2.73%/503 trades) is REVERSED 2026-08-13: it
  measured DEFAULT_CONFIG, because best.json had been clobbered to the default
  (2026-08-10, agent run af1e6d83 seeded it during epoch_engine testing).
  The actual contract (ledger iter-74, restored to best.json) measures
  **+2.27%/trade, +23.1% net over the full 5y** (17-sym incl. SPY) on the repo's
  own run_backtest. **BUT it does not generalize** (2026-08-13, universe test
  `/tmp/opentrader/universe_contract_test.py`): same contract on the 511-symbol
  harness registry = **−37.8% net (PF 0.71)**; on the 7.3k-symbol survivorship-
  honest fullcross archive = **−40.4% (PF 0.83)**; DEFAULT_CONFIG on the same
  wide archive = −60.6% (engine sanity). It is also window- and data-source
  fragile on the 17 syms themselves: +23.1% over the full ohlcv_5y window vs
  +16.9% when cut at 2026-06-11, and +7.7% (60 trades) when the same window is
  fed from fullcross.pkl (sources disagree ~1.5–2% on identical dates — data
  provenance reconciliation outstanding). The edge is a mega-cap-window
  artifact: the setup_search loop optimizes on the 17 names, so selection
  pressure never forced generalization. The walkforward reference rows
  −3.04/−5.74/−8.24 are DEFAULT_CONFIG's, never the contract's. NOTE:
  walkforward.py excludes SPY from the aligned set, so its contract rows
  (incl. the +40.12% full-archive) ran regime-OFF; the +23.1%/+16.9% figures
  above are the regime-ON, live-faithful ones. Reproduce:
  `/tmp/opentrader/rule_floor_honest.py` and `/tmp/opentrader/universe_contract_test.py`.
  **Signal-family probe (2026-08-13, `/tmp/opentrader/signal_family_probe.py`)**
  — no feature family in the engine's existing space generalizes on the 5y-wide
  universe under realistic fees: mom/rev/rsi/brk/z blends, cross-sectional rank
  (`rank_on`), vol-adaptive sizing, RSI/momentum/MA filters all lose (best of
  class: cross-sectional rank, PF 0.84, still negative). The search's gate
  (`setup_search/loop.py --wide-eval`, 5y wide, ≥8 trades, fees ≤50%) is now
  the standing promotion requirement — nothing promotes without passing it.
  The remaining honest paths: new signal inputs (macro FRED/VIX — VIX series
  only spans 2y in macro_series.pkl; sector-relative via mot/industry_map.py).
  **Macro-regime probe (2026-08-13, `/tmp/opentrader/macro_regime_probe.py`)** —
  FRED state gates (FF level/falling, 10Y falling, curve non-inverted) added
  as an entry condition in `run_backtest(macro_gate=...)` (default off;
  regression-verified). ONE positive result: **incumbent + "ff_falling"**
  (long only while Fed Funds < its 60d-ago level) flips the wide universe from
  **−41.8% → +6.2%** (124 trades, PF 1.07, fees 18%). **OOS walkforward
  (2026-08-13, `/tmp/opentrader/macro_lead_walkforward.py`) DISPROVES it as an
  edge**: only 1/4 folds positive (−0.7%, +1.8%, −3.0%, −1.2%). The gate is a
  loss-REDUCER, not an edge (ungated control is −17.1/−15.8/−3.9/−0.6% per
  fold). Net honest conclusion: the rule floor has no validated wide-universe
  edge in any feature family or macro regime tested; nothing should be promoted
  to best.json until a genuinely generalizing signal is found and OOS-validated.
  Macro data provenance verified against known history (FF 5.33% peak 2023 →
  3.62% mid-2026). **Cross-asset test (2026-08-13,
  `/tmp/opentrader/cross_asset_test.py`)** — long-horizon (60d trend / 60d
  hold) timing across 13 liquid proxies (equity indices, TLT, GLD/SLV/USO/DBC,
  currencies), with/without ff_falling and SPY>SMA gates, benchmarked against
  SPY buy-and-hold net of costs: **buy-and-hold (+78.6% 5y) beats every
  variant** (best: rank+ff_falling +5.3%, PF 1.18, fees 12%; worst −22.5%).
  Also fixed a real engine bug: `_cross_sectional_rank` used
  `dropna(axis=1)`, which dropped every symbol whenever ANY bar had NaN —
  `rank_on` was silently dead (0 trades) until 2026-08-13 (commit 9b7301a).
  **Cumulative honest verdict: nothing on this data beats passive SPY
  buy-and-hold net of costs — not the 17-name contract, any feature family,
  any macro regime, or long-horizon cross-asset timing. The system's edge is
  not in daily-rule long-only allocation.**   **International test (2026-08-13,
  `/tmp/opentrader/international_test.py`)** — 10 international assets
  (N225/FTSE/GDAXI/HSI, EEM/EFA, FX, gold/oil), no-lookahead, same gates:
  no active variant beats buy-and-hold (best rank_vix +8.5% vs basket 10.0%),
  BUT the equal-weight international basket has better risk-adjusted returns
  than SPY (Calmar 0.733 vs 0.472, Sharpe 1.03 vs 0.75) — international
  diversification reduces drawdown; US mega-cap concentration is the risk.
  **Metric screen (2026-08-13, `/tmp/opentrader/metric_screen.py`)** — tests
  whether ANY regime metric (breadth50/200, cross-sectional momentum
  dispersion, SPY/MA50/200, VIX, FEDFUNDS, DGS10, yield curve, CPI YoY)
  separates good forward periods from bad (quintile spread of 20d/60d basket
  forward returns, fold-consistent over 2008→2026). Result: **no metric
  passes** — VIX and curve show the largest raw spreads but flip sign across
  folds (one-window luck); a promising-looking dispersion lead was a
  PENNY-STOCK ARTIFACT in the first-400-symbol alphabetical slice and
  vanishes on a clean liquid universe (±0.4% noise). The infra for a rich
  metric set exists (value_head_1m.collect(), data/economics.py FRED client
  + FRED_SERIES) but no single metric in it has demonstrated predictive
  power; treat any claim that "adding metric X unlocks the edge" as an
  hypothesis to screen, not a conclusion.
  **Contrarian within-industry selection (2026-08-13, "the plus something")** —
  the arsenal experiment the user asked for: 4 within-industry selection rules
  (momentum-top, contrarian-bottom, blended, equal-weight) x macro-gate on/off,
  57 liquid large-caps 2008→2026, no-lookahead, 0.35% fees. **Contrarian
  (long the WORST-5 by 60d momentum) with NO macro gate beats buy-and-hold
  3/4 folds (9.1% ann vs 6.8% BH; Calmar 0.165 vs 0.126)**; wins crisis/rotation
  windows (2008-11 +13.3% vs −17.7%, 2019-24 +134%, 2024-26 +82.6%), loses the
  smooth bull (2011-19 −14.9% vs +53.8%). Momentum-top is the bull tool (5.3%
  ann); contrarian is the rotation tool. Adding a macro gate or stop-loss made
  contrarian WORSE — confirming the user's point that the single-gate framing
  (VIX/FF) was wrong and the combination matters. The arena's job is now
  concrete: learn the regime SWITCH between momentum-top and contrarian, using
  the metric library as switch inputs.
  **RESEARCH-SWARM TOURNAMENT R1 (2026-08-13, `/tmp/opentrader/swarm/`) — the
  turning point.** 6 parallel research agents, shared scorer
  (`swarm/scorer.py`, no-lookahead, 0.35%/side), escalating bars (R1 beat
  basket BH ann+Calmar; R2 beat SPY Sharpe+Calmar+>2/4 folds; R3 positive in
  2024-26 AND maxDD > −50%). **FOUR strategies passed ALL THREE bars and beat
  both benchmarks on every risk-adjusted axis** (all verified by re-run):
  `r1_momtrend` ann 27.5%/Calmar 0.682/maxDD −40% (momentum-top K=5 + market-
  breadth entry gate, no forced exits); `r1_shortrev` ann 26.8%/Calmar 0.579
  (extreme-short 2-3d look + 36-40d hold, top-7 worst); `r1_blend` ann 25.2%/
  Calmar 0.507 (composite −z(mom60) − z(industry-relative), top-3/25 bars);
  `r1_multiasset` ann 7.2%/Sharpe 0.81/maxDD −18.5% (momentum top-10 of 13
  assets, vol-scaled — the drawdown tool). Convergence: "buy weakness" is the
  common core; market breadth is the drawdown key. Failed & logged: forced
  exits, trailing stops, RSI-oversold filters, vol-targeting overlays,
  dispersion tilt, sector-split without industry gate. This is the first
  reproducible, fold-consistent, benchmark-beating result of the project.
  **TOURNAMENT R2 — OOS TRANSFER (2026-08-13)**: survivors re-run with FIXED
  parameters on the international archive (2021-2026, symbols never seen in
  selection), scored vs intl basket BH (Calmar 0.501). **TWO transfer
  (verified): `r1_multiasset` OOS Calmar 1.289 / maxDD −9.0% (momentum top-8
  of 10 + 60% inverse-vol, rebal 63 — the drawdown tool) and `r1_momtrend`
  OOS Calmar 0.852 / maxDD −13.0% (momentum K=5 + market-breadth entry gate —
  the regime tool).** Two FAIL with clear diagnosis: `shortrev` (US single-
  stock 2d-bounce microstructure absent on indices/FX/commodities) and
  `blend` (industry-relative reference group doesn't exist on 10 instruments).
  Conclusion: the transferable edge is STRUCTURAL (breadth-regime + momentum;
  vol-scaled multi-asset), not symbol-specific. These two are the arena
  substrate.
  **TOURNAMENT R1c — ABSTRACT MATHEMATICS SWARM (overnight, 12 agents, all
  verified by re-run, 2026-08-13)**: the abstract frameworks decisively beat
  the price-threshold gates. Leaders (US 2008-26, Calmar): **spectral (FFT
  low-freq gate × breadth) 1.071** (ann 34%, maxDD −31.7%), **copula
  (lower-tail-dependence sleeve) 0.904**, **hurst (persistence gate) 0.884**,
  entropy 0.832 (hypothesis REVERSED: high entropy gates, low = quiet grind),
  bayes/BOCPD 0.818, wavelet 0.766, hmm 0.666, kalman 0.603. Floors for
  reference: momtrend 0.469, hedge 0.678. Universal lesson confirmed by every
  agent independently: **gate-entries-only; forced exits / trailing stops /
  soft de-risk always destroy returns.** Honest negatives: online ensemble
  does NOT beat its best member (static 1/3 blend wins); long-only
  cointegration edge < fees (needs shorts the harness doesn't price); per-name
  Kelly too noisy. All agents reproduced their floor bit-for-bit before
  modifying (integrity). Roster now has 6 prototype experts from R1/R1b/R1c:
  momtrend, multiasset, spectral, copula, hurst, entropy — the arena's
  starting substrate.
  **Engine integrity (commit 1718f33)**: `run_backtest` no longer executes at
  the same close that generated the signal — decisions use master[t-1], fills
  use bar t close; iter-74 honest number +23.1%→+18.6% (17-sym); all
  conclusions re-verified unchanged.
- **Rule config** — the incumbent "playbook" = ledger iter-74 config
  (w_mom −0.56, w_rev −0.54, w_rsi 0.90, buy_thresh 0.28, sell_thresh −0.2).
  Its risk contract: 15% per position, 6 concurrent positions, 95% exposure,
  12.28% stop, 17.81% target, 14-day max hold, SPY-vs-96d regime gate. Under
  this contract the floor measures **+2.27%/trade (53 trades, +23.1% net 5y,
  Sharpe 1.12, maxDD 3.5%)**; positive 2024–26, −0.65% 2023, no trades 2021–22
  (regime gate closed the bear — by design). The 08-12 "−2.66%/501 trades"
  number came from swapping only sl/tp/hold into DEFAULT (5% risk, no regime,
  thresh 0.2) — a mis-specified variant, not this contract. Caveat: the
  +23.1% holds only for the 17-name universe it was selected on; see the
  generalization test result in the Rule floor entry above.
- **Regime** — the market state the rule trades on: SPY above or below its 96-day
  average. "Up" or "down". One regime clock for equities; crypto gates on BTC's
  own trend, not SPY.
- **MoT router** — the Mixture-of-Traders selector. Picks the expert per regime;
  the floor holds until an expert's recorded per-trade impact beats the floor's.
  Time-keyed since ADR-0006: best expert per (epoch, regime), prior experts stay
  eligible with recency-weighted evidence decay; all checkpoints kept.
- **Reasoning track** — the LLM's separate gated pilot (ADR-0006, phase 3):
  Qwen2.5-7B trained with GRPO + a reasoning reward, R1-minted cold-start
  traces, verifiable reward = war-outcome edge. Gated on proposer quality
  (beats the ADIR/debate baseline), never on becoming the edge. Delivers a
  competing proposer whose traces derive new value-head features.
- **Expert** — a deployable edge: a tiny value-head MLP (momentum, macro,
  international). LLMs are the explainable layer, never the edge. Each expert is
  instantiated per **epoch**.
- **Epoch** — one window of the continual-learning loop (ADR-0006). Spawns a new
  expert on the versioned-fidelity cadence: archive append / quarterly
  re-validation / sustained shadow drift. Trained with rehearsal of prior-epoch
  data. Orthogonal to **regime** (market state), which stays binary.
- **Rehearsal** — replay of prior-epoch data (plus ≤25% multiverse worlds,
  phase 2) mixed into a new epoch's training so the fit retains old behavior.
- **Erosion** — the anti-forgetting measure: an epoch-N expert's edge on
  epoch-N-1's holdout must stay within 0.5% (half-gate) of epoch-N-1's recorded
  edge on that window. The counterweight to the gate.
- **Selector sharpness** — the prototype finding (ADR-0006) that the edge lives
  in a sharp ~1% tail of the composite score, and a smooth regression value
  head dilutes it. The selector (score screen) and the orderer (value head /
  classifier) are distinct roles; the score screen selects, the head orders
  within the tail.
- **Classifier orderer** — the ADR-0006 candidate expert (roster id
  `classifier-orderer`): a BCE classifier on top-10%-fwd tail membership that
  orders within the score tail (keep top 25%). Beats random within the tail on
  2024-25 across seeds; degrades on 2022-23. Registered as prototype, not
  promoted.

## How edge is built and measured

- **Arena** — the adversarial training loop: battle → fit → war → relabel → gate.
- **Gate** — the held-out discrimination test: an expert's kept-trades mean minus
  the candidate mean must clear +1% on both regime windows. Real data only.
- **Multiverse** — generated market worlds (neural + parametric samplers) used to
  stress-test the agent and to augment training. Synthetic rows never enter the
  gate, the war, or the evidence. From ADR-0006 phase 2, worlds also serve as
  rehearsal (≤25% of an epoch's replay mix), adversarially rotated against the
  tail library.
- **Tail library** — curated crisis worlds (US debt ceiling, COVID crash, 2022
  bear, yen unwind, flash crash). GANs under-sample tails; this is the
  countermeasure.
- **Fidelity war** — replay of the real 5-year archive. The headline gate.
- **Multiverse war** — survival test across generated worlds; a world is "ruined"
  below −25% net or −30% drawdown.
- **Shadow** — the daily-archive evidence engine (setup_search/shadow_mot.py).
  Where edge evidence actually accrues; thousands of candidates per run.
- **Paper shadow** — the live harness on real prices, paper settlement.
  Infrastructure validation, not edge validation.
- **GRPO** — group-relative policy optimization; the arena's refinement step.

## The deployment program

- **Runway** — the phased plan: paper shadow → first real money at 1% → ladder to
  15%, gated on shadow evidence and infra cleanliness. Capital ceiling $10k,
  funded by work income + prop-challenge rewards (ADR-0005). Sizing ramps
  1% → 15% gated on fidelity; the absolute-$ stop is 10% of account → halt +
  review.
- **Prop account** — the FTMO 2-Step challenge (ADR-0005), the project's
  revenue vehicle: firm capital traded on a slow compounding clock
  (~939 days to target at current cadence), 90% split at funding, sizing ≤20%
  during the challenge, and a news/gap entry ban the rule engine must encode.
- **Inactivity clock** — a firm's deactivation timer (The5ers 30d, FundedNext
  60d): the system's 102-day no-trade gap disqualifies any firm with one; only
  FTMO has none.
- **Deployable** — the pre-committed gate for first real money: ≥3 closed paper
  trades spanning at least two exit paths, zero fatal defects, ≤15bps realized
  slippage; the shadow's up-regime rule-floor edge un-decayed; ≥10 weeks
  continuous paper. Rare exits are force-tested in the sandbox, not awaited
  live. Returns are deliberately not part of the criterion (see ADR-0002).
- **Fatal defect** — a plumbing failure that disqualifies the paper phase on any
  single occurrence: silent hold, state corruption, order rejection, >15bps
  slippage, exit-ladder deviation.
- **Three-tier structure** — how the system handles scale (ADR-0003): the live
  loop trades a pinned liquid subset; the offline cross-section (the 35M-row
  dataset) ranks all symbols; the portfolio ranker (later, gated) trades the
  top-N. Offline rank, live trade top-N.
- **Portfolio ranker** — Tier 3: an offline daily cross-sectional ranking over
  the full universe; the live loop trades the top-N. Arrives after first real
  money, re-gated under the faithful-replica principle.
- **Versioned fidelity** — the promoted ladder is a snapshot, not scripture:
  re-validation on the appended archive quarterly (or on sustained shadow
  drift), promoted through the same gates; the old config retires. Since
  ADR-0006 this is the **epoch engine**: the walk-forward over archive slices
  that spawns, freezes, gates, and measures erosion for each epoch.
- **Rotation detector** — the rank-based layer (cross-sectional mom/RSI
  percentiles) that reacts to sector rotation; lives in Tier 2 (the macro
  expert's feature set today, the offline cross-section tomorrow). The
  16-name rule's screen is absolute, not rank-based — it catches
  rotation only within its universe.
- **Sandbox** — opentrader-sandbox, an isolated copy of the repo. All changes are
  proven here before touching the live tree or the GPU.
- **Faithful replica** — the principle that live must reproduce the validated
  strategy exactly (same exits, sizing, risk contract) or live-vs-backtest
  comparisons are meaningless.

## Avoid

- "The AI trading model" — say which expert.
- "More data" — say which model consumes which feature space.
- "Validated" — only for things that passed the gate or walkforward.
