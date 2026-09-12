# Table of Context — OpenTrader frontier under ADR-0007

> Index of what context costs. Load only what is cheap and relevant.

## Budget

| phase | allowance | spent | remaining | used |
|---|--:|--:|--:|--:|
| oanda | 25000 | 0 | 25000 | 0% |
| _lifetime_ | — | 51218 | — | — |

## Chapters (context cost)

| chapter | est. tokens | size | staleness | status |
|---|--:|--:|--:|---|
| 01-scope.md | 699 | 2.8 KB | 14d ago | hand-written |
| 02-variables.md | 4074 | 16.0 KB | just now | rendered from ledger |
| 03-plan.md | 266 | 1.0 KB | 9d ago | hand-written |

## Raw findings log (append-only, never compacted away)

| file | est. tokens |
|---|--:|

## Checkpoints

last: `checkpoints/ckpt-04.md` (verified)

## Open questions

- Q02: Human decision queued: challenge-mode risk contract (per small-capital plan 1.3) — requires its own ADR + sandbox walkforward per ADR-0008 s4 before any E8/FTUK purchase. Proposed params (0.04 breaker / 0.02 stop / 0.04 target / 0.10 pos / 0.25 kelly) are HEURISTIC, unvalidated
- Q03: Q03 (from V11 run, added by orchestrator 2026-08-29 — operator wrote it in deployability_status.json but did not execute toc open add): paper harness has 0 closed round trips since 2026-08-01 (3 open BUY positions only) — clause 1 cannot pass on trade evidence; is the harness expected to close positions at this stage, or is the 70-day calendar clock the binding constraint (clause 3, currently 0 continuous days due to gaps)?
- Q04: exchange/oanda.py diverged between live tree (security guards + tag kwarg) and sandbox (server-truth get_balance): which is canonical, and should the fixes be merged before landing the FX tickets (#162/#163)?
- Q05: exchange/oanda.py fork (live: security guards + tag kwarg; sandbox: server-truth get_balance) — Q04 open. NEW related: should venue-reconciliation rows carry the originating lane tag stamped from the venue txn clientExtensions at reconcile time (kills size inference + the 100u ambiguity)?
- Q06: fxexpert loop v0.1: warm-start recursion lifted OOS IC 0.004->0.029 over 12 gens (hp B, 339k params), but no generation passed the gate (net PF 0.90-1.00 vs bar 1.05; buy-hold 1.17). Gross PF 1.038 with ~0.5bps/day cost drag. Open: does cost-aware training (turnover penalty / wider thresholds / longer holds) convert the gross edge to net? Ref docs/agents/research/fx-expert-loop-2026-09-06.md, data/fx_expert/history.jsonl
- Q07: fxexpert loop v0.2: warm-start future-leak found+fixed (per-fold chains); contaminated g12-35 era invalidated (2 registrations set fail). Clean 24-gen run g36-59: honest convergence to IC ~0.015 / net PF ~0.98, 0 PASSes, plateau by ~g45. Data-bound ceiling at 16-pair daily breadth. Open: do multi-horizon panel + longer targets (10-20d) + fold-chain ensembles clear the 1.05 bar? Ref docs/agents/research/fx-expert-loop-2026-09-06.md §v0.2
- Q08: fxexpert v0.3 100-gen verdict: recursion stable and reproducible, converges to N-family (340k params, 10d horizon, hysteresis) IC ~0.021 / net PF ~1.02 / Sharpe + / 3-3 folds — below the 1.05 gate bar and buy-hold 1.165. Ceiling is information-limited at 16 pairs x daily decisions (340k param optimum, bigger degrades). Decision open: expand data engine vs shadow-accrue the N signal under caps vs declare daily panel exhausted. Ref docs/agents/research/fx-expert-loop-2026-09-06.md §v0.3
- Q09: fxexpert v0.4: 58-pair universe (3.6x breadth, 289k pair-days) lifted N-family OOS IC 0.021->0.032 (+54%), best 0.0354 with regime-uniform fold ICs [0.035,0.037,0.034] — a real cross-sectional factor. But threshold rule converts none of it: PF flat ~1.00-1.02, 0 PASSes, Sharpe down. Bottleneck = construction at breadth: rank-weighted sizing, vol targeting, pair cost selection. Ref docs/agents/research/fx-expert-loop-2026-09-06.md §v0.4
- Q11: fx-expert-g151 registered accruing (first gate-PASSing trained FX expert, amended bar): PF 1.0846 Sharpe 0.281 IC 0.0309 3/3 folds, weekly rank-rebalanced dollar-neutral book, shadow signals emitting to data/fx_expert/signals.json. OPEN: does the forward shadow accrual ledger confirm the backtested edge? (the only test that matters now; live = human signoff per ADR-0009 §4)
- Q12: fxexpert tournament LIVE 2026-09-06 (human signoff, demo funds): fx-expert-g137/g138/g151 wired as OANDA practice lanes (cron 21:25/21:35/21:45 UTC weekdays, --once=real, 2000u/unit weight, tagged orders, weekly rank rebal). First real trades Monday 21:25 UTC on Monday's D1 close. Bottom two cut Friday 2026-09-11 close (human). Legacy lanes will sit mostly flat (netted-account arbitration vs 57-leg books). OPEN: forward accrual vs backtest edge; tournament PnL per fxexp-* tag. Ref docs/agents/research/fx-expert-loop-2026-09-06.md
- Q13: equity agent #2 SKETCH pre-registered 2026-09-07 (before gen 0, build gated on Friday 09-11): avenue = US equities cross-sectional rank book on data/setup_search/fullcross.pkl (9267 syms x 1300 daily bars 5y, verified). Gate bars pre-registered: OOS Sharpe>=0.8 AND Calmar>=SPY-BH, >=3/4 folds IC>0, beat 12-1 momentum + all baselines, measured neutrality <=0.2, gross-vs-net cost honesty, survivorship check before gen 0, amendments only via logged human call. Ref docs/agents/research/equity-expert-sketch-2026-09-07.md
- Q14: fx-warden v0.1 live (local Qwen3.8-4B on 3070, :5802): hourly observe + daily plan/score, expectation-conditioned reward (QB/RB rule, arithmetic in code), shadow-cut probation state machine, notes verified against venue truth (4B invents derived % ~100% of rate — verifier gates corpus). Mid-train trigger ~2 weeks of records.jsonl. OPEN: does expectation-adjusted scoring separate lane skill from regime? Ref docs/agents/research/fx-warden-2026-09-08.md
- Q15: Warden model A/B (2026-09-08, same 7 prompts from records): Qwen3.8-4B JSON 6/7, plan 1/1, grounding 18/18, 4.8s | Granite-4.0-H-Tiny 3/7 (fails JSON contract) | Granite-4.2-8B with --reasoning off 6/7, 1/1, 16/16, 4.9s — TIE on bar, but 8B weights + qwen3-embed don't co-exist safely on the 8GB 3070 (OOM under concurrent load). Decision: keep Qwen3.8-4B live; Granite 4.2 file kept for mid-train era. NOTE: reasoning-style models need --reasoning off or they burn tokens in reasoning_content (eval-harness lesson).
- Q16: Warden model swap LIVE: Granite 4.2 8B on RX 7900 GRE via llama.cpp Vulkan/RADV (:5802, opentrader-warden-gre.service), records stamped warden-4.2-8b, 3070 freed to embedding-only. A/B tie on bar; swap won on VRAM coexistence. Path: HIP on gfx1101 core-dumps in ROCm 7.2.4 (dead end), Vulkan build needed 3 configure rounds (SPIRV headers no longer vendored). TRY legs still missing (OANDA halt) — tracked in warden audit daily. Ref docs/agents/research/fx-warden-2026-09-08.md
- Q17: Warden v0.2 instability watch LIVE: per-currency composite (halt 30 + vol-spike 25 + shock 25 + events 10 + global bond/vix stress 10) from DGS10/T10Y2Y/EM-HY-OAS bond panel + FX vol from store + venue halt status. Wired into plan/observe prompts; plan stores non-calm snapshot. Robustness: halt = stale price >30min + persists 2 consecutive runs; plan lane-coverage backfill. First real catch: JPY/EUR/USD/TRY critical during rollover flicker, TRY genuine (8h frozen). Ref docs/agents/research/fx-warden-2026-09-08.md
- Q18: Warden GPU-eviction failover LIVE: Granite(GRE,5802) primary + Qwen(3070,5804) on-demand fallback, supervisor timer 5min VRAM-aware (never fights gaming — if 3070 busy, warden skips runs), endpoint chain in llm_json, failover records stamped warden-qwen-fallback. Loop tested: evict->catch->serve->restore. Ref docs/agents/research/fx-warden-2026-09-08.md
- Q19: fxexpert ARCHITECTURAL CONSTRAINT confirmed live: one netted OANDA account = one net position per instrument; three sibling books FIFO-corrupt each other (evidence: off-target 26->40, gross 67k overshoot, cross-lane deferrals). Resolution: g151 = sole live book, g137/g138 = paper competitors (same cost model, disclosed), separate OANDA accounts = the true multi-live option (human-gated). Lane exits now per-tradeID closes; anti-churn drift filter shipped. Friday scoreboard: g151 live fills + g137/g138 paper-vs-live disclosed. Ref fx-expert-loop doc
- Q20: Conviction auction LIVE: 53 symbols held, ZERO overlapping pairs (18/22/18 per lane), claims registry frozen per period, execution core rewritten (tradeID closes surgical, foreign guard on adds). Trade-offs disclosed: per-lane neutrality broken (account residual ~10k net-long), sibling correlation limits differentiation. PUSHBACK recorded: one-week cut on 19-leg books = noise; recommend 2wk or IC-based scoring. Ref fx-warden doc
- Q21: TP/SL A/B (8 variants x 3 OOS folds x ~28k leg-periods, fxexpert/trailing_ab.py): EVERY trailing-stop and TP variant loses to hold-to-rebalance (best trail-3ATR PF 0.594 vs baseline 0.604; Sharpe all worse). Structural: rank-weighted both-side books — stops realize adverse marks the horizon recovers, TPs cap winners. Independently re-confirms the R1-era 'forced exits destroy returns' rule. Lane design decision: no SL/TP is now MEASURED, not assumed. Harness stays for future variants.
- Q22: newsfeed v1 wired into Warden: newsfeed_digest() reads canonical items from data/newsfeed/newsfeed.db (deduped, 25 recent), injected as 'headlines:' block into plan/observe prompts alongside FF/MOF/Fed feeds. Records carry headlines for PIT audit. The plan now conditions on actual GDELT headlines (Brent 00, ECB rate path, BOJ/JPY) not just scheduled events. Verified live: plan ran with 3 trained lanes, observe 3/3 verified notes. Ref fx-warden doc
- Q23: MFE tracker + give-back ratio live on warden scoreboard: hourly observe persists per-lane peak uPL, daily score computes give-back = (peak−current)/peak. First verified readings: g151 peak +1.15 uPL +0.93 (2.0% GB), g137 peak +.17 uPL +.48 (9.6% GB). Separates selection skill from exit-policy cost on the scoreboard. Ref fx-warden doc §MFE
- Q24: Simulated trail/TP LIVE: fx_trail_check.py every 5min via systemd timer. Per-leg peak/trough tracked in trail state, ATR from store, closes triggered legs via per-tradeID surgical close (no server-side SL/TP orders). Defaults: trail 2ATR, TP 3ATR. First run 0 exits (expected — fresh book). The A/B tested uniform stops; this is the per-leg selective version. Ref fx-warden doc
- Q25: fxexpert search continuation: the 2026-09-11 round (g167-g188) plateaued at PF ~1.28-1.29 and NO generation survives the deflated bar (WRC p(PF)=0.119, needs >=2.00 bps/day vs 1.12). Stop the search vs change the information set (new inputs) vs accept ledger-accrual-only evidence? Human decision. Ref V-WRC, docs/health/hardening-backlog-2026-09-11.md item 1.
- Q26: Search-history reproducibility: 10 of 153 clean-era generations (g124-g136, the mid-search thr_cont/rank fix boundary) have recorded PFs that do not reproduce from their own stored artifacts (deltas +0.10..+0.17). Annotate the stale rows (sidecar, never rewrite history.jsonl) and add a re-score assertion to the loop write path. Ref hardening backlog item 7.
- Q27: GATE BAR (HITL): the fxexpert promotion bar PF>=1.05 is dominated by variance unrelated to signal quality — corr(IC,PF)=0.168 over 101 generations, and within an IC quartile PF spans 0.76-1.29 (two models at IC 0.0291/0.0298 score PF 1.034 and 1.286). The weight-transfer test (g221: IC 0.0291, PF 1.034) shows the same signal quality converting to wildly different PF. Decide: replace/augment the bar with a lower-variance criterion (IC-based, or IC+PF composite, or a longer-horizon book with lower PF variance), and re-specify what the deflated correction then evaluates. Ref V-PANEL2, V-WRC.

---

_generated 2026-09-12T05:17:45.702Z · governor: qwen38 @ http://127.0.0.1:5804/v1 · ctxCap 60000 tok_

