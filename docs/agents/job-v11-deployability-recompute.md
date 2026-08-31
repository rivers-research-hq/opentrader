# JOB — Deployability recompute (ToC ledger V11) — recurring operator run

You are the OpenTrader operator (Qwen3.8-27B). This is a TRANSCRIPTION job,
not a research job: every number you emit must be copied from a ledger or
computed by a script you run — never from memory, never estimated. The output
feeds ADR-0002's deployability gate (the project's score function), so a
fabricated number here is the worst possible failure. When a datum is absent,
write null and add an open question.

## PRECONDITION — freshness

If there is ANY prior conversation above this message (state snapshot,
compressed history, earlier task), STOP and reply exactly:
"NOT A FRESH SESSION — open a new one and paste only this file."

## STEP 0 — Orient (≤4 calls)

```bash
cd /home/mrc/opentrader/data/wayfinder/toc && toc status && cat chapters/01-scope.md
cd /home/mrc/opentrader/data/wayfinder/toc && toc phase start v11-recompute --allowance 20000
```
Ledger V11 defines this job. Never contradict a [known] variable.

## STEP 0.5 — Reset-boundary check (added 2026-08-29, after the first run)

Harness restarts have RESET the paper portfolio before (2026-08-29:
initial_cash back to 500, fills history wiped, positions re-opened at a new
cycle). Before computing clauses 1 and 3:

1. Detect a reset boundary: `initial_cash` != 500.0-with-history, fills
   log starting later than `data/history/` mtimes imply, or a cycle-counter
   discontinuity vs `data/history/cycle_*.json`.
2. If found (or previously found — once true, always annotate): emit
   `"reset_boundary": {"detected_at": "<ts or last-known>", "evidence_pre_boundary": "lost_to_reset"}`
   in the output JSON, and state in clause 1/3 notes that pre-boundary trade
   evidence is LOST, not zero. Never count lost evidence as absence.

## THE WORK — three clauses of ADR-0002, from real ledgers only

Write ONE deliverable file: `/home/mrc/opentrader/data/wayfinder/deployability_status.json`
(plus echo a human summary). Compute each field as specified:

### Clause 1 — plumbing fidelity

```bash
python3 - <<'PY'
import json
s = json.load(open('/home/mrc/opentrader/data/paper_state.json'))
fills = s.get('fills', [])
print('fills_total:', len(fills))
for f in fills[-30:]:
    print(f.get('timestamp'), f.get('symbol'), f.get('side'), f.get('quantity'), f.get('price'), f.get('reason',''))
PY
```
- `closed_trades`: count CLOSED round trips (entry + exit) in the fills log —
  state your counting rule in the JSON.
- `exit_paths_seen`: distinct exit reasons among closes (stop_loss /
  take_profit / max_hold / manual). List them.
- `fatal_defects`: scan the last 500 lines of
  `journalctl --user -u opentrader-harness --since "7 days ago" --no-pager`
  for: silent-hold patterns (cycles with signal but no fill and no risk
  rejection), state corruption (traceback, JSONDecodeError), order rejection
  strings. Count each, quote one verbatim line per type found.
- `reconciliation_ok`: compare `paper_state.json` cash+positions vs
  `data/shadow_scaled/paper_state.json` — this is main vs shadow, note it is
  NOT an exchange reconciliation (field stays `null` until an exchange
  ledger exists; say so).

### Clause 2 — shadow edge persistence

The honest current state (ToC V02, V10): no validated wide edge exists; the
shadow engine's up-regime rule-floor impact history lives in
`data/live_router_state.json` → `track.up.rule` (`sum`, `n`).
- Report `rule_floor_impact_mean` = sum/n from that file (transcribe verbatim),
  `n`, and `window_note`: "forward lane evidence since 2026-08-14, not the
  ADR-0002 +0.9% shadow measure — clause status: NOT MEASURABLE until #157
  shadow driver runs" (V10).
- Do NOT compute a new edge. Do NOT run backtests. Transcribe only.

### Clause 3 — calendar floor

- `first_paper_ts`: earliest timestamp in `data/paper_state.json` fills, or if
  empty, the file's `cycle`/earliest `data/history/cycle_*.json` mtime.
- `continuous_days`: (now − first_paper_ts) in days, minus any gap > 24h you
  can evidence from `data/history/` mtimes (list gaps; if you cannot check
  cheaply, report the raw span and mark `gap_check: "not_done"`).
- `clause3_pass`: continuous_days ≥ 70 (10 weeks).

### Output schema (exact)

```json
{
  "generated": "<iso timestamp>",
  "generated_by": "qwen3.8-27b operator run v11",
  "reset_boundary": {"detected_at": "...", "evidence_pre_boundary": "lost_to_reset"},
  "clause1_plumbing": {"status": "pass"|"accruing"|"fail", "closed_trades": N,
    "exit_paths_seen": [...],
    "fatal_defects": {"silent_hold": N, "state_corruption": N, "order_rejection": N},
    "defect_quotes": ["...verbatim..."], "reconciliation_ok": null, "pass": bool},
  "clause2_edge": {"status": "pass"|"accruing"|"fail", "rule_floor_impact_mean": X,
    "n": N, "window_note": "...", "pass": null},
  "clause3_calendar": {"status": "pass"|"accruing"|"fail", "first_paper_ts": "...",
    "continuous_days": N, "gaps": [...], "pass": bool},
  "open_questions_added": ["Qxx ..."],
  "tool_calls_used": N
}
```

Recurrence note: this run repeats weekly (Friday reminder). Clause 3's
70-day clock only becomes meaningful once the fills-continuity ticket lands
(resets currently zero it); until then the run is monitoring, not gate
evidence.

## STATUS SEMANTICS (added 2026-08-31 — the TUI renders these verbatim)

Each clause carries `status`, not just `pass`. Derivation rules:
- `"fail"` = actively violated: C1 fatal_defects > 0; C2 measured AND below
  bar with n >= 5 forward windows; C3 a gap > 24h dated after the clock start
  (continuity fix, 2026-08-31).
- `"accruing"` = insufficient elapsed time/data, no violation. This is the
  normal state for the first weeks. Never report accruing clauses as "fail" —
  the deployability display renders FAIL only for active violations.
- `"pass"` = criterion met (C1: >=3 closed trades AND >=2 exit paths AND
  fatal 0; C3: >=70 continuous days).

## RULES

- ≤ 25 tool calls. Any number not from a command output this session → null.
- After writing the JSON: `cd /home/mrc/opentrader/data/wayfinder/toc && toc checkpoint --allowance 4000`
- Append one heartbeat line to `data/wayfinder/ultimate_chapter.md`:
  `v11 heartbeat <calls> did:<one line> pass:<c1/c2/c3 summary>`
- If a read returns "[File X unchanged since last read]" — the content is
  already in your context; do not re-read; proceed.
- NEVER repeat a tool call returning identical output twice — state why in
  one sentence and take a different action.
- Final reply: the JSON body verbatim + tool-call count. Nothing else.
