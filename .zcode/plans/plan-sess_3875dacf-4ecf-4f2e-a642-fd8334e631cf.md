Finish the GUI/launcher work:

1. **Verify the launch** (read-only checks first, restart via `opentrader` if down):
   - `curl http://127.0.0.1:8097/health` and `/` — confirm the new "FX Practice Book" GUI is served by the restarted process.
   - `ss -tln | grep 8097` — confirm binding is `127.0.0.1:8097` (loopback-only; never `0.0.0.0`).
   - Sanity-check `/api/fx-lanes` returns the venue-derived lane scoreboard.
   - If down: diagnose from `data/logs/dashboard.log`, fix, relaunch via `opentrader`.

2. **Retroactive paper trail** (the wayfinder gap called out earlier):
   - Two closed tickets under prop map #150: (a) GUI v3 + `/api/fx-lanes` — what shipped and why venue-derived realized replaced ledger FIFO; (b) the `opentrader` launcher + loopback-only binding fix (the 0.0.0.0 default was the flagged security flaw), with resolutions and file refs.
   - One decision line appended to map #150: GUI/launcher shipped; legacy Mission-Control page preserved at `dashboard_legacy.html` pending the human's deletion call.
   - Re-run the 31-test suite for regression sanity.

**Not in scope unless requested:** deleting the legacy page, TUI retirement, dashboard auth (loopback-only now), news-gate stopgap in the hourly lanes.