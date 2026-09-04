#!/usr/bin/env python3
"""C2 PlatformTransmit hook (#82): after each fill in paper_state.json,
transmit to Collective2 so the paper runway auto-publishes as a
(hypothetical-labeled) C2 strategy.

- Idempotent: sent fill ids recorded in data/c2_transmit.json.
- Dormant without credentials: no C2_STRATEGY_ID / C2_API_KEY -> logs and skips
  (never crashes the trading loop, never transmits).
- Modes: --check (validate creds against C2), --dry-run (print what would send),
  default: poll-and-send loop.

C2 AutoTrade API: POST https://api.collective2.com/apiv2/... with strategy id +
key; fills map to OPEN (buy) / CLOSE (sell) trade signals. Hypothetical labeling
is configured on the C2 strategy side (strategy created as hypothetical).
"""

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

PROJECT = Path(__file__).resolve().parent.parent
PAPER_STATE = PROJECT / "data" / "paper_state.json"
LEDGER = PROJECT / "data" / "c2_transmit.json"
C2_BASE = os.environ.get("C2_BASE_URL", "https://api.collective2.com/apiv2")
STRATEGY_ID = os.environ.get("C2_STRATEGY_ID", "")
API_KEY = os.environ.get("C2_API_KEY", "")
POLL_SECS = 60


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_ledger() -> dict:
    if LEDGER.exists():
        return json.loads(LEDGER.read_text())
    return {"sent": []}


def save_ledger(ledger: dict) -> None:
    LEDGER.write_text(json.dumps(ledger, indent=2))


def _fill_key(fill: dict) -> str:
    ts = str(fill.get("timestamp") or fill.get("time") or "")
    sym = str(fill.get("symbol") or "")
    qty = str(fill.get("quantity") or fill.get("qty") or "")
    return f"{ts}|{sym}|{qty}"


def new_fills(state: dict, ledger: dict) -> list:
    sent = {f["key"] for f in ledger["sent"]}
    out = []
    for fill in state.get("fills", []):
        key = _fill_key(fill)
        if key and key not in sent:
            out.append((key, fill))
    return out


def _c2_payload(fill: dict) -> dict:
    sym = (fill.get("symbol") or "").split("/")[0]
    side = "BUY" if str(fill.get("side", "buy")).upper().startswith("B") else "SELL"
    return {
        "stratid": STRATEGY_ID,
        "apikey": API_KEY,
        "action": side,
        "symbol": sym,
        "qty": float(fill.get("quantity", 0.0)),
        "price": float(fill.get("price", 0.0)),
        "exchange": "Crypto",
    }


def transmit(fill: dict) -> dict:
    payload = _c2_payload(fill)
    r = httpx.post(f"{C2_BASE}/autotrade", json=payload, timeout=20.0)
    return {"status": r.status_code, "body": r.text[:200], "payload": payload}


def check_creds() -> dict:
    if not STRATEGY_ID or not API_KEY:
        return {"ok": False, "reason": "C2_STRATEGY_ID / C2_API_KEY not set (hook dormant)"}
    r = httpx.get(f"{C2_BASE}/strat/{STRATEGY_ID}?apikey={API_KEY}", timeout=20.0)
    return {"ok": r.status_code == 200, "status": r.status_code, "body": r.text[:200]}


def run_once(dry_run: bool = False) -> int:
    if not PAPER_STATE.exists():
        print(f"[c2] no {PAPER_STATE} yet — nothing to transmit")
        return 0
    state = json.loads(PAPER_STATE.read_text())
    ledger = load_ledger()
    pending = new_fills(state, ledger)
    if not pending:
        return 0
    if dry_run:
        for key, fill in pending:
            print(f"[c2][dry] would transmit {key} -> {_c2_payload(fill)}")
        return 0
    for key, fill in pending:
        try:
            res = transmit(fill)
        except Exception as e:
            print(f"[c2] transmit failed for {key}: {e}")
            continue
        ledger["sent"].append({"key": key, "at": _now(), "status": res["status"]})
        save_ledger(ledger)
        print(f"[c2] sent {key} -> status {res['status']}")
    return 0


def main():
    ap = argparse.ArgumentParser(description="C2 PlatformTransmit hook")
    ap.add_argument("--check", action="store_true", help="validate credentials against C2")
    ap.add_argument("--dry-run", action="store_true", help="print what would be transmitted")
    ap.add_argument("--once", action="store_true", help="single pass, then exit")
    args = ap.parse_args()

    if args.check:
        print(json.dumps(check_creds()))
        return 0
    if args.once:
        return run_once(dry_run=args.dry_run)

    print(f"[c2] polling {PAPER_STATE} every {POLL_SECS}s (creds: {'SET' if STRATEGY_ID and API_KEY else 'NOT SET - dormant'})")
    while True:
        try:
            run_once(dry_run=args.dry_run)
        except Exception as e:
            print(f"[c2] error: {e}")
        time.sleep(POLL_SECS)


if __name__ == "__main__":
    main()
