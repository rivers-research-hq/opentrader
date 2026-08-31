# Postmortem — 2026-08-31: where the process failed, and the binding rules for the next iteration

- **Trigger:** human verdict — "no progress for weeks, wasting tokens and compute";
  Qwen3.8-27B revoked as trader and coder; current iteration declared failed.
- **Method:** every finding below was re-verified against ledgers/logs on
  2026-08-31 (git log, crontab, systemd units, `data/training/`, `data/logs/`,
  `data/signal_gym/`, `data/paper_state.json`), not taken from prose.

## Root causes (each is now a binding rule)

1. **The self-improvement loop never ran, and nothing checked.** The single
   finetune attempt died on GPU OOM 2026-08-13 (`data/training/finetune_status.json`);
   zero model artifacts were ever produced; DPO data (Aug 3) was never consumed.
   The nightly trainer re-merged the same 2,787 examples with a broken version
   bump; the eval gate was stuck behind a stale lock no-op'ing every 30 min;
   the 12h scheduler failed on missing `unsloth`; the 5-min watchdog pointed at
   a venv that does not exist. Cron noise mimicked a living training loop.
   **Rule: every cron/systemd job must name a recent artifact it produced.
   No artifact, no job. A "loop" that emits logs but no artifacts is dead —
   treat logs as noise until an artifact exists.**
2. **Process replaced product (Aug 13–28).** Four agent campaigns produced
   dashboards, TUIs, mood boards, and agent tooling that fed zero deployability
   gates (ADR-0007's own confession); the course-corrections themselves became
   more process (three role-division amendments in three days, card systems,
   registries, heartbeats).
   **Rule: a session earns its tokens only by moving a named gate artifact
   (ledger, registry, verifier, adapter). Meta-work (plans, cards, dashboards,
   docs) does not count as progress and must not be scheduled while a gate is open.**
3. **Delegating implementation to the local model inverted the economics.**
   Binding 2026-08-29 morning, collapsed 3× by 08-30, reversed same day
   (commit `fd598b2`): the card→review→revise cycle cost more paid tokens than
   doing the work directly.
   **Rule (human decision, 2026-08-31): Qwen3.8-27B has no trader or coder
   role in any capacity. `qwen38-serve.service` + `headroom-proxy.service`
   stopped and disabled. Role division clause 2 is void.**
4. **"The first agent for the MoT" had nowhere to live.** The promotion seam
   (ADR-0009) landed only 2026-08-31 — until then there was no registry to
   enter a first trader into, so nothing could register as progress on it,
   and the 70-day calendar floor (equities paper) gated everything while
   resetting 10 times via harness gaps.
   **Rule: every strategy the project backs must have a registry entry, an
   accrual ledger, and a promotion bar from day one. If it can't be pointed to
   in a registry, it doesn't exist.**
5. **Parallel half-tracks starved the critical path.** Crypto paper, FX track,
   arena, epoch engine, hive, lanes, dashboards — none reached a gate.
   **Rule: one lane, one gate. The FX first-trader evidence path is the only
   active gate; everything else is frozen until Experts #0/#1 accrue or the
   human re-opens a lane.**

## What was executed today (human-approved: "Let's go")

- Zombie crons removed: `train_pipeline.sh` (2am), `eval_gate.sh` (30min),
  `training.harness_scheduler` (12h), `ops_watchdog.py` (5min), V11/Qwen card
  reminder. Kept: accumulator, lanes, fx_runner, shadow_driver, JobHunt, social.
  Backup: `~/.cache/crontab/crontab.bak`.
- `qwen38-serve.service` (27B, 265% CPU 24/7) and `headroom-proxy.service`
  stopped + disabled (units retained; `systemctl --user enable --now` restores).
- **Expert #0 registered**: `fx_mom_k5_top2` (incumbent, Track B FX runner v0,
  live on OANDA practice, real fills `data/fx_ledger.jsonl`, seed=null — no
  arena gate claimed). **First challenger registered**: `fx_mr_fade_ma20`
  (gym lead: IS PF 1.18 / OOS PF 2.27, positive in both windows; near-miss on
  the IS survival bar — a lead, not a proven edge).
- `strategies/epoch_registry.py` built (ADR-0009 seam): (epoch, expert_id)
  keyed, three-state status, atomic single-writer, append-only artifact log
  `data/epoch_registry_log.jsonl`.
- `strategies/fx_shadow.py` built: faithful port of gym candidate c04 under
  the gym's uniform risk shape; PURE PAPER (no orders, V06 boundary holds);
  per-symbol asof guard, idempotent; verified live against OANDA practice.
  Cron weekdays 17:20.

## The first-trader gate (replaces the equities calendar floor for FX)

`fx_mr_fade_ma20` promotes to live order flow only when ALL hold:

1. ≥30 closed shadow round trips in `data/fx_shadow_ledger.jsonl`;
2. PF > 1 over the full shadow window (spread-adjusted, conservative accounting);
3. reconciliation clean between shadow ledger and state;
4. **human signoff** at the shadow → live boundary (ADR-0009 §4 — the
   irreversible step).

The incumbent (`fx_mom_k5_top2`) accrues ADR-0002 clause evidence from real
venue fills in parallel. The equities 70-day paper clock continues in the
background but gates nothing in the FX lane.

## RLHF posture (decision recorded)

The market labels every trajectory with realized PnL — objective reward from
real venue fills — so environment-reward learning is the primary loop, not
human preference guessing. Human feedback enters where it has unique value:
vetoing degenerate behavior early, risk-shape constraints, and the promotion
signoff (already the ADR-0009 HITL seam). Preference data accumulates as
(state, action, human_label, outcome) rows from daily trade review; the value
head trains on realized outcomes once ≥50–100 labeled decisions and ≥30 shadow
trades per expert exist. The dead trainer skeleton is retired until then.
