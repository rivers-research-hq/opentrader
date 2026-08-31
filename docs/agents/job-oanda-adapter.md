# TASK — OANDA v20 FX adapter (Track B venue, sandbox + practice API, fresh session)

You are the OpenTrader implementer (Qwen3.8-27B). ONE bounded task: build
`exchange/oanda.py` — an `ExchangeBase` implementation for OANDA v20 REST —
and prove it against the **practice** account. Sandbox tree only.

If any prior conversation exists above this message → STOP, reply exactly:
"NOT A FRESH SESSION — open a new one and paste only this file."

## STEP 0 — Orient (≤4 calls)

```bash
cd /home/mrc/opentrader-sandbox && git status --short | head
cd /home/mrc/opentrader/data/wayfinder/toc && toc status
cd /home/mrc/opentrader/data/wayfinder/toc && toc phase start oanda --allowance 25000
```
Then read: `exchange/paper.py` + `exchange/stock_finnhub.py` (the interface +
`restore_ledger` pattern, esp. paper.py:227), `exchange/multi_router.py`
(`_is_crypto`/`_is_stock` routing — your adapter is the FX child),
`exchange/base.py`.

## CREDENTIALS — hard security rules

- Read at runtime from `/home/mrc/opentrader/config/oanda_keys.json`
  (fields: token, account_id, host). It is gitignored.
- **NEVER print, log, echo, embed, or copy the token into any file, output,
  patch, or the ToC workspace.** Code references the path; that is all.
- Host is `https://api-fxpractice.oanda.com` (practice env — real API, demo
  money; hitting it is the paper-validation the gates require).
- Account: `101-001-40262644-001`, USD, 68 instruments (EUR_USD, GBP_USD,
  USD_JPY confirmed; XAU_USD absent).

## THE WORK

### 1. `exchange/oanda.py` — OandaExchange(ExchangeBase)

- `__init__(config)`: reads the keys file; base instrument list = the 7 FX
  majors present (EUR_USD, GBP_USD, USD_JPY, USD_CHF, GBP_JPY, AUD_USD,
  USD_CAD — intersect with the account's 68).
- `get_balance()` → Balance(cash=account balance, positions=net units per
  instrument, total_value). FX has no "cash vs positions" split like a broker
  book — the account balance IS the cash; positions are net units.
- `get_prices_batch(symbols)` / bar fetch → v3 `/v3/instruments/{inst}/candles`
  (granularity D, count per interface convention).
- Market order placement → `POST /v3/accounts/{id}/orders` (market, units ±,
  timeInForce FOK) and market-if-touched/limit for the exit ladder. OANDA is
  netted per instrument — long/short via negative units.
- `restore_ledger(cash, positions, cost_basis, fills)` from day one —
  paper semantics (set the local mirror), PLUS the lesson from continuity-2:
  restore_ledger must exist on EVERY child.
- Interface parity: match the method signatures the multi-router and harness
  already call (mirror `stock_finnhub.py` structure; do not invent new
  interface surface).

### 2. Prove it (sandbox test script `tests/test_oanda.py`, output verbatim)

- connectivity: account query prints balance + currency (NO token anywhere).
- prices: fetch D1 candles for EUR_USD (last 5 closes).
- trade round-trip: market BUY 100 units EUR_USD → verify position exists →
  market CLOSE it → verify position net 0 → print both fills.
- restore_ledger: set a synthetic ledger, read back through get_balance.
- Print `order_id`-style identifiers if OANDA returns them (the continuity
  ledger dedup learned this lesson — capture whatever unique ID OANDA gives).

### 3. Patch

`diff -u` per touched file into `data/wayfinder/patches/oanda-adapter.patch`
(labels may be absolute; the human lands by copy).

## RULES

- ≤ 30 tool calls; heartbeat every ~10 to `data/wayfinder/ultimate_chapter.md`
  (`oanda heartbeat <N> did:<one line> next:<one line>`).
- Sandbox tree only; no service restarts; no crontab edits.
- The practice account is the proving ground — trades there are free; still
  keep order sizes tiny (100 units) and close everything you open.
- Numbers from API responses you ran this session only.
- Blocked >3 attempts → report blocker, ship partial.
- End: `toc checkpoint --allowance 5000`. If it times out, note it and finish —
  the orchestrator will run the checkpoint.

## DELIVERABLES

1. Patch file. 2. Verbatim test output (all four proofs). 3. Instrument list
intersection (majors the adapter will trade). 4. Heartbeat. 5. Proposed gh
comment (do not post).
