# TASK — Continuity-3: stop fills duplication across restarts (≤10 tool calls, fresh session)

Restart #2 (15:36 today) proved the resume fix works — cash/positions/verification
all PASS — but paper_state fills DOUBLED (3→6, byte-identical copies of the same
three trades). Diagnosis is done; implement the fix. Sandbox only.

If any prior conversation exists above this message → STOP, reply exactly:
"NOT A FRESH SESSION — open a new one and paste only this file."

## THE TWO BUGS (verified in live `harness.py`, landed today)

1. `_restore_portfolio_state()` re-appends fills that are already loaded from
   paper_state at init → every restart doubles the fills list (3→6 this
   restart; will compound 12, 24…).
2. `_append_fills_to_ledger()` dedups by `f.get("order_id")` — but real fills
   carry no `order_id`, so every fill dedups against the sentinel `""` and the
   check is a no-op. Latent (ledger is 3 lines because append runs once per
   fill), but it will bite the moment append runs twice.

## THE FIX (sandbox `harness.py`)

1. **Composite fill key** (shared helper, used everywhere):
   `key = (timestamp, symbol, side, quantity, price)` — order_id is optional
   and may be absent.
2. `_append_fills_to_ledger`: dedup existing ledger lines by the composite key.
3. `_rebuild_fills_from_ledger(current)`: **replace, not merge** — whenever the
   ledger exists and is non-empty, return `ledger_fills` (the append-only
   ledger is the authoritative fills source; paper_state fills are a derived
   view). Keep the "ledger longer" log line for observability.
4. Ensure the restore path does not extend a fills list that already holds the
   same composite keys — after restore, `self._fills` must be the deduped
   union (which, post-fix, is just the ledger content).

## PROOF (paste verbatim)

Extend `tests/test_continuity.py` with a **Phase C: double-restart** —
simulate restart twice in a row; assert fills count is IDENTICAL after both
(3, not 6, not 12) and cash/positions unchanged. Then run the full test file.

## DELIVERABLES

1. `diff -u /home/mrc/opentrader/harness.py /home/mrc/opentrader-sandbox/harness.py > /home/mrc/opentrader/data/wayfinder/patches/continuity-3.patch`
2. Verbatim full test output (Phases 1, 2, A, B, C).
3. Heartbeat: `continuity3 heartbeat <N> did:<one line>` in ultimate_chapter.md.

## RULES

- ≤ 10 tool calls. Same output twice → STOP, ship what you have.
- Sandbox only. No service restarts. Only `harness.py` + `tests/test_continuity.py` change.
