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
  "clause1_plumbing": {"closed_trades": N, "exit_paths_seen": [...],
    "fatal_defects": {"silent_hold": N, "state_corruption": N, "order_rejection": N},
    "defect_quotes": ["...verbatim..."], "reconciliation_ok": null,
    "pass": true|false|null},
  "clause2_edge": {"rule_floor_impact_mean": X, "n": N, "window_note": "...",
    "pass": null},
  "clause3_calendar": {"first_paper_ts": "...", "continuous_days": N,
    "gaps": [...], "pass": true|false},
  "open_questions_added": ["Qxx ..."],
  "tool_calls_used": N
}
```

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
