# Session pass-off — 2026-09-16

## Stop state / continuity

- The local GRE coding worker was intentionally unloaded for gaming:
  `local-worker.service` is **inactive**.
- It remains **enabled** for later restart, but its `ExecCondition` still gates on
  `scripts/gpu_pick.py --want gre`; do not start it while gaming.
- GRE llama process is gone and port `5808` is closed.
- The RTX 3070 fallback remains online:
  `opentrader-warden-qwen.service` is active and `http://127.0.0.1:5804/health`
  returned `{"status":"ok"}`.
- Both dashboards remain online on `:8097`; the health endpoint returned:
  cycle `41454`, cash `372.75`, portfolio value `372.75`, 3 positions,
  drawdown `26.44%`, paper/synthetic mode.
- No FX service was stopped or restarted during unload.

## Coding workhorse

The local worker is the preferred bounded coding agent when the GRE is available:

```bash
scripts/local_coder.sh "one bounded coding task with a checkable end state"
# sandbox-first:
scripts/local_coder.sh --dir /home/mrc/opentrader-sandbox "..."
```

Relevant files:

- `.opencode/agents/local-coder.md` — model prompt and 30-call budget.
- `scripts/local_coder.sh` — fresh opencode session, repo venv on `PATH`.
- `scripts/local_coder_verify.py` — re-runs safe `PROOF:` commands and rejects
  missing or inconsistent proof. It does not validate free-form read-only prose;
  independently spot-check those reports.
- `docs/agents/local-coder.md` — operating guide and measured benchmark results.

Do not use it unattended for gate-feeding ledger artifacts. It previously produced
wrong aggregate values and fabricated `tool_calls_used`; the artifact was restored.
Use it for bounded code edits, test-driven fixes, and read-only code location tasks.

## Verified coding performance

- Synthetic coding benchmark: **30/30** across five consecutive full runs after
  fixing the PATH/pytest trap and revising the prompt.
- Real repository read-only tasks: **8/8**, including lane attribution and expert
  lifecycle inspection, with no tree changes.
- FX test suite: **39 passed**; full suite: **92 passed** at the time of testing.
- The faster Ornith Q4 model is not the default: it needed more turns despite higher
  token throughput. The MoE worker was more efficient end-to-end.

## FX / OpenTrader state

- Current git HEAD before this session: `a47483d` (`data: exog pipeline audit —
  schedule the unscheduled, close the COT loop, #217 survivorship gate PASS`).
- The working tree already had extensive pre-existing modifications. Do not reset,
  clean, or overwrite them.
- Current FX schedule and deployment rules are in `docs/agents/fx-ops.md`.
  Deployment policy: one expert at full notional, currently `fx-expert-g151`;
  g137/g138 are paper competitors after the netted-account constraint.
- The crash lane cache currently reports realized `-24.1`, max drawdown `26.0298`,
  and open cache positions `USD_CHF` and `USD_CAD`, each 5000 units. The cache is
  not authoritative; venue state must answer live position questions.
- `fx_intraday.json` currently has no positions and was updated at
  `2026-09-16T17:00:05Z`.
- `fx_expert/lane_state_g151.json` is stale cache-only state (`last_period 1045`,
  `last_traded 2026-09-10`, updated `2026-09-12`).

## Deployability recompute completed

`data/wayfinder/deployability_status.json` was recomputed from real ledgers this
session and is intentionally newer than the Aug 29 artifact:

- Clause 1: **accruing**, 19 closed BUY/SELL pairs from 42 fills, no detected
  fatal defects, but no qualifying exit paths; pass false.
- Clause 2: **accruing**, rule-floor mean `-0.1282`, n=24; not measurable until
  #157 shadow driver evidence exists.
- Clause 3: **accruing**, first fill `2026-08-30T19:36:54.884300+00:00`,
  computed continuous span `6.6` days after four >24h gaps; pass false.
- A heartbeat was appended to `data/wayfinder/ultimate_chapter.md`.
- `toc checkpoint --allowance 4000` still fails because the configured endpoint
  advertises/accepts only 8192 context while the request is 10526 tokens. This is
  an open infrastructure defect, not a successful checkpoint.

## Recommended next-session sequence

1. Confirm gaming is over before restarting the GRE worker:
   `scripts/gpu_pick.py --want gre`, then `systemctl --user start local-worker.service`.
2. Run one bounded FX coding task through `scripts/local_coder.sh` in the sandbox.
3. Keep live-tree landing and venue-facing changes human-gated.
4. Fix the ToC checkpoint endpoint/context mismatch before another governed operator
   run; do not claim a checkpoint succeeded while it returns the 8192-context error.
5. Reconcile venue truth before reporting crash-lane or g151 positions; caches are
   explicitly non-authoritative.

## Today's performance (2026-09-16) — warden observations

Source: `data/warden/warden_state.json`, `data/warden/notes.jsonl`, `data/warden/friday_scoreboard.json`.

### Deployed expert g151 (accruing, escalate-only probation)

- Throughout today g151 held **14–16 positions**, net short exposure
  increased from **−2,797 units to −3,993 units**.
- Unrealised P&L trended **down** over the day: started at **+$37.14**,
  fluctuated through the day, settled at **+$8.82** by 18:45 UTC — a
  decline of roughly **−$28 from the open** (intraday market moves against
  the short book on a day when USD volatility was critical).
- Friday scoreboard (Sep 14): realised **−$87.40**, uPL **+$40.61**,
  peak MFE **$69.06**, give-back ratio **0.291**, 17 positions,
  17% sizing fidelity, warden score **−0.059%**.
- Warden probation: 1 bad period, **escalate-only** — scored for the
  Friday list, not auto-capped under ADR-0011 because it is the sole
  deployed expert.

### Other experts

- **g138** (cut): realised **−$171.23**, 0 positions, warden score −0.177%.
- **g137**: paper competitor; peak MFE $34.06 (Sep 11), give-back 2.822.

### Account-level

- **NAV**: $99,631.02, **balance**: $99,590.49, unrealised: +$40.52.
- **Financing**: −$29.17 / today (accounts carry significant overnight cost).
- **Crash lane**: actively churning today — multiple USD_CAD, USD_CHF,
  AUD_USD entries and reconciliation closes totalling 5,000 u per leg
  on the $300 margin budget. Realised −$24.10, max DD $26.03.
- Dashboard snapshot at task time: cycle 41,454, cash $372.75,
  3 positions, drawdown 26.44%.

### Warden flags (persistent today)

| flag | detail |
|---|---|
| critical | **USD** volatility at **61**, vol_ratio **1.46**, 5d-shock **0.65** — entire day |
| elevated | **JPY** volatility at **53**, 5d-shock **0.46** — persistent hourly |
| anomaly | **Crash lane trading while unregistered** — flagged every observation cycle |
| risk | Oil approaching **$100/barrel**, Middle East tensions affecting USD long |
| elevated | **GBP** 5d-shock 0.57, **NZD** vol_ratio 1.34 (intermittent) |

### Verdict

g151 is accruing on-paper evidence but the intraday P&L has been eroding
today as USD critical volatility reversed some of the prior short-book gains.
The crash lane continues operating as designed (unprotected, unregistered).
The warden (Qwen3.8-4B fallback on the RTX 3070) ran hourly observations
throughout the day with verified notes.
