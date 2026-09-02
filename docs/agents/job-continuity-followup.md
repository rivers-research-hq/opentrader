# TASK — Continuity follow-up: multi-router restore splits cash wrong (≤12 tool calls, fresh session)

The #157-class continuity fix landed on live (harness restart 14:36 today) and
its own verification assert caught a residual bug. Fix it, prove it, hand back
a clean patch. **Diagnosis is done — do not re-derive it. Do NOT touch the
live tree. Sandbox only.**

If any prior conversation exists above this message → STOP, reply exactly:
"NOT A FRESH SESSION — open a new one and paste only this file."

## THE BUG (verified against the live error)

`MultiExchangeRouter.restore_ledger` (`exchange/multi_router.py:156`) splits
saved cash 50/50 ("matching init") and skips children without
`restore_ledger`. The stock child (`FinnhubExchange`) has NO `restore_ledger`
(only `exchange/paper.py:227` and `alpaca_paper.py:435` do) → its half is
silently skipped → aggregate = crypto-half + stock's untouched init cash =
**$427.32 vs saved $354.64** → harness logs
"Portfolio restore FAILED verification" on every startup.

## THE FIX (sandbox: `exchange/stock_finnhub.py` + `exchange/multi_router.py`)

1. `FinnhubExchange.restore_ledger(cash, positions, cost_basis, fills)` —
   mirror the paper.py:227 implementation (set `_cash`, `_positions`,
   `_cost_basis`, `_fills`; it is always a paper book).
2. `MultiExchangeRouter.restore_ledger`: replace the blind 50/50 split with
   **proportional distribution** — read each child's current cash first
   (`child.get_balance().cash`), distribute `saved_cash` in proportion to
   each child's share of the pre-restore aggregate (guard division by zero →
   fall back to 50/50). Route every child through `restore_ledger` once
   Finnhub has it; keep the `hasattr` guard as defense.
3. Positions/cost-basis routing by `_is_crypto`/`_is_stock` stays as-is.

## PROOF (paste verbatim)

1. Sandbox restart simulation (reuse/extend `tests/test_continuity.py`):
   - phase A: crypto-heavy book (e.g. crypto cash 104, stock cash 250,
     aggregate 354) → restore → assert children sum to 354 AND each child's
     share matches its pre-restore proportion (±$1).
   - phase B: the explicit `--reset-portfolio` path still wipes cleanly.
2. `python3 -c "import strategies.anything"` not needed — but
   `ast.parse` both touched exchange files and paste OK.
3. `diff -u` live-vs-sandbox for the two exchange files → that IS the patch.

## DELIVERABLES

1. `diff -u /home/mrc/opentrader/exchange/stock_finnhub.py /home/mrc/opentrader-sandbox/exchange/stock_finnhub.py > /home/mrc/opentrader/data/wayfinder/patches/continuity-2-finnhub.patch` and the same for `multi_router.py` into `continuity-2-router.patch` (two files, absolute-path labels are fine — human lands by copy).
2. Report: verbatim test output, call count, blockers.
3. Heartbeat: `continuity2 heartbeat <N> did:<one line>` in ultimate_chapter.md.

## RULES

- ≤ 12 tool calls. Same output twice → STOP, ship what you have.
- Sandbox only. No service restarts. No edits to `harness.py` (its hunks are
  already landed and correct — this is exchange-layer only).
- Do not modify `data/paper_state.json` in the live tree.
