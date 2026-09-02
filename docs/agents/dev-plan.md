# Development Plan — Autonomous Loop, 2-Week Horizon

> Frozen 2026-08-10 via grilling session (all 12 framing decisions accepted).
> Living document: rolled weekly. Tracker tickets are the work items; this is the schedule + budget.

## 1. Scope

This plan governs **all open development efforts** on the opentrader tracker: momentum arena, epoch engine (continual learning), MoT agent fleet, hive-mind swarm, curriculum forge, exogenous regime-conditioned signal layer, both-GPUs-productive, monetization (FTMO / marketplace / open-source). Every ticket flows through the same autonomous loop, budget policy, and gates. The local researcher service is the execution vehicle.

## 2. Operating loop

- **Nightly (autonomous, via overnight pattern):** resolve AFK research tickets with subagents; run prototypes/experiments that have defined gates (arena walk-forward, epoch engine, researcher eval suite); write a morning report: what ran, actuals vs forecast burn, gates passed, new findings.
- **HITL tickets (grilling/task-with-decisions):** never resolved by the loop. The loop preps a decision memo (options, recommendation, budget to resolve); the human settles it at review.
- **Weekly review (human):** read the report rollup; settle HITL decisions (FTMO prop bet, marketplace listing, open-source scope, arena acceptance gate); reforecast the next 2 weeks (actuals vs forecast); promote/close tickets.
- **Escalation:** local researcher fails → cloud deepseek (capped); both fail → ticket blocked, reported, never fabricated.

## 3. Budget policy

- **Units:** input+output tokens per activity; GPU-hours for local tiers; $ for cloud (deepseek). One row per ticket; rolled up weekly.
- **Activity split (weekly):** Research 20% · Prototyping 30% · Experimenting (arena/epoch/eval runs) 35% · Maintenance+ops 15%.
- **Local vs cloud:** 75/25 local-first. Local: researcher tiers + overnight + subagents on the two GPUs. Cloud: HITL reviews, hard reasoning, local-failure escalation.
- **Per-ticket caps:** research ≤30k tokens · prototype ≤60k · experiment run ≤150k · task ≤80k · HITL prep memo ≤15k.
- **Enforcement:** overrun → auto-stop that ticket, log it in the morning report, move on. No surprise spend.
- **2-week forecast** (est. totals): ~650k tokens (≈490k local / ≈160k cloud), ~40-45 GPU-h across both tiers.

## 4. Per-ticket forecast (weeks 1-2)

| Ticket | Activity | Tier | Est. tokens | Est. GPU-h | Est. $ |
|---|---|---|---|---|---|
| Exogenous data falsifier — VIX day-regime (91, research) | research | deep + cloud | 35k | 1 | ~0.3 |
| Coordinate two GPU streams (49, research) | research | fast | 25k | 0.5 | — |
| GPU0's real simultaneous capacity (48, research) | research | fast | 25k | 1 | — |
| Prototype run: 5-slice walk-forward (88) | experimenting | deep | 150k | 15 | — |
| Prototype: epoch engine — 5y walk-forward (84) | experimenting | deep | 150k | 20 | — |
| C2 PlatformTransmit: paper-journal (82, task) | prototyping | fast | 70k | 2 | — |
| BFCL/RULER eval-gate measurement (112 follow-on) | experimenting | both | 60k | 5 | — |
| HITL preps: FTMO, marketplace, open-source, arena gate, fleet, hive (79-81, 50, 54, 60, 64, 65, 67) | grilling preps | cloud | 6 × 12k | — | ~1.5 |
| Researcher ops/maintenance | maintenance | both | 40k | 2 | — |
| **Totals** | | | **~650k** | **~46** | **~$2** |

## 5. Done gates (per type)

- **Research:** findings file + verdict, blocking decisions recorded → resolved.
- **Prototype:** working artifact + verdict (per prototype skill) → resolved.
- **Experiment:** eval-gate pass + results artifact → resolved.
- **Task:** work done + resulting facts recorded → resolved.
- **Grilling (HITL):** resolution comment records the human's decision → resolved.
- Every artifact is linked from its ticket. "Done" is only done when the tracker says so.

## 6. User-side follow-ons (no token budget; tracked in the weekly report)

REAP deep-tier upgrade (needs a valid HF token — all on-box tokens return 401) · key rotation at providers · revoke scrubbed PATs · ollama localhost bind · identify :20680 · opencode/mcp restarts to apply the localhost rebind.

## 7. Actuals — wave 1 (2026-08-10)

Resolved: **Exogenous data falsifier — VIX day-regime rule** (verified capturable edge, SIG at ≥0.5/≥1.5, OOS caveat) · **GPU0's real simultaneous capacity** (actual free VRAM 1.66 GiB, debate ruled out as GPU0 workload) · **Coordinate two GPU streams** (coexistence not safe as built: vacuous gate, pkill/orphan 5813, no HOLD ack).

Graduated: **VIX day-regime rule: out-of-sample re-validation** (#113) · **GPU-stream scheduler: live activity signal + two-card scheduler** (#114).

In progress: **Prototype: epoch engine — walk-forward over 5y archive, momentum expert** (#84). Recon: archives at `data/setup_search/ohlcv_5y.pkl` (+ftmo/international), pattern in `setup_search/walkforward.py` (5y/3-fold CPU), momentum expert in `arena/`. No dedicated epoch engine yet — the build is: expanding-window train loop over the archive, momentum expert per epoch, erosion check on prior-epoch holdouts, gate = +1% on both regime windows per the ADR.

Budget burn so far: research 95k/120k est. tokens (3 tickets), 0 cloud cost.

## 8. Actuals — wave 2 (2026-08-10)

Resolved (7 tickets): **Epoch engine prototype** (built + ran, 2×24-month epochs, no-promotion verdict, report `data/arena/epoch_report.json`; `best.json` seeded from DEFAULT_CONFIG) · **5-slice walk-forward run** (executed via the engine at ADR-corrected granularity — FAIL vs pre-committed bar, logged, automated retry) · **VIX OOS re-validation** (FAIL promotion: 1/3 eras survive, era-dependence confirmed) · **C2 PlatformTransmit** (hook `tools/c2_platform_transmit.py` + dormant service deployed, credential checklist handed to human) · plus wave-1 research (VIX falsifier verified, GPU0 capacity, GPU-stream coordination).

Next build queued: **GPU-stream scheduler fix** (#114) — recon done (gpu_scheduler.py:59-60/106-114 dead gate, train_scheduler.py:245 5813, harness.py:2941 debate skip, task_gpu0_finetune stops systemd). Needs a focused session on a live box.

## 9. Glossary (captured from this session)- **Autonomous loop** — nightly execution of AFK work by researcher/overnight/subagents.
- **Morning report** — daily artifact: ran items, burn vs forecast, gates, findings.
- **Weekly review / reforecast** — human checkpoint; settles HITL decisions and rolls the forecast.
- **Ticket types** — research (AFK), prototype (HITL artifact), experiment (eval-gated run), task, grilling (HITL decision).
- **Tiers** — fast (Hermes-3-8B, :5803) and deep (Qwen3.6-27B, :5802) researcher backends behind router :5810.
- **Budget units** — tokens (input+output), GPU-hours (local), $ (cloud).
- **Activity split** — 20/30/35/15 research/prototyping/experimenting/maintenance.
- **Local-first 75/25** — local tiers carry most work; cloud capped for review/escalation.
- **Caps + auto-stop** — per-ticket ceilings; overrun stops the ticket and logs it.
- **HITL decision** — a human-locked decision; the loop preps, never resolves.
