# TUI clients — which one, and how not to confuse them (2026-09-02)

There are TWO terminal clients in this repo. This file exists because two
separate sessions confused them, and the second confusion cost a full round of
"fixed but not actually fixed" reports.

## The human's client: npm/Ink — `tui/index.js`

- Launch: the npm command in `tui/` (`npm start`; flags `--forex`, `--calendar`).
- Stack: Ink 5 + React 18, plain JS (`React.createElement`, no build step),
  `cli-boxes` for the rounded panels. Entry `tui/index.js`, 540-ish lines.
- Data sources (polled):
  - `data/*` state files re-read every 2s (`loadState()`: ab_equity.csv,
    paper_state.json ×2, epoch_registry.json, live_router_state.json,
    fx_crashtest.json, fx_watchdog_state.json, fx_ledger.jsonl via
    `laneStats()`).
  - dashboard `http://127.0.0.1:8097/api/fx` every 5s (venue-authoritative:
    openTrades + account + last 25 ledger rows + per-lane flat reasons).
  - `/api/calendar` every 20s.
- Pages: `[1]` Home (agent aggregation + portfolio strip + boards +
  deployability + router + calendar/queue), `[2]` Forex (OPEN BOOK by owner
  tag / LANES scoreboard / FILL STREAM / CRASH-TEST $300 panel), `[3]`
  Calendar. Keys `1/2/3/r/q`.
- Lane attribution rule (in `laneStats()` `laneOf` AND the fill-stream
  mapper): reason-prefix first; `venue-reconciliation` rows (tagless SL/TP
  closes) attribute by fill size — ≥5000u `crash`, ≥2000u `h1-mom`, >0
  `mom-k5`. If a lane changes size, both mappers must change.
- Crash lane realized comes from the venue-derived tracker
  (`data/fx_crashtest.json` `realized`, recomputed from venue ORDER_FILL `pl`
  over the full lane epoch), not ledger FIFO — FIFO pairs closes to the oldest
  open buy while the venue closes the newest position.
- Known caveat: mom-k5's RT count includes three 100u EUR_USD reconciliation
  dust pairs from Aug 31 (−0.065) — size attribution can't separate them.

## The other client: Textual — `tui.py` (repo root)

- A Python Textual app from a prior session. **It replaced the npm client
  once** (the human lost their TUI) and was restored from git history
  (commit `ab66167`). It is kept only because deleting things has its own
  risk; it is NOT what the human runs.
- 2026-09-02 a second incident: fixes for the stale-lanes complaint were
  implemented and reported as landed in `tui.py` while the human was looking
  at `tui/index.js` (#166, #167 amendment). The same fixes were then ported
  to `tui/index.js`. The Textual copy also carries the fixes now, but it is
  not the target.

## Rules

1. TUI/UI work targets `tui/index.js` unless the human says otherwise.
2. Never delete/replace/rename the npm client or change its launch command.
3. Before reporting a UI fix landed, confirm the artifact the human runs
   (ask, or check `ps` for the running process).
4. The dashboard (`opentrader-dashboard.service`, FastAPI :8097) is shared
   infrastructure for both clients — `/api/fx` and `/api/calendar` are its
   endpoints; it reads the OANDA venue live with a 30s stale-while-revalidate
   cache.

## Related tickets

- #166 — tui.py `PROJECT = parent.parent` bug (file panels read
  `/home/mrc/data`): fixed in BOTH clients' trees (tui.py landed; index.js
  never had it — it uses absolute `BASE`).
- #167 amendment — the wrong-client miss and the index.js port.
