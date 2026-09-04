#!/usr/bin/env python3
"""fx_review — human preference store for the RLHF loop (data/fx_review.jsonl).

Every real event in the FX ledgers (incumbent fills, shadow fills, shadow
fires = counterfactual signals) is labelable. `show` lists events and their
label status; `label` appends an immutable preference row. Labels are the
human-feedback layer of the learning loop (docs/research/rlhf-spec.md):
    approve — the trade/signal matches what the human would have done
    veto    — the human would NOT have taken it (the high-value signal)

Keys are derived from ledger content (lane:ts:symbol:side:reason) and
verified against the ledgers before labeling — no fabricated events.

Usage:
    python3 -m strategies.fx_review show [--all] [--lane fx|shadow]
    python3 -m strategies.fx_review label KEY approve|veto [note...]
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
LEDGERS = {
    "fx": PROJECT / "data" / "fx_ledger.jsonl",
    "shadow": PROJECT / "data" / "fx_shadow_ledger.jsonl",
    "fire": PROJECT / "data" / "fx_shadow_fires.jsonl",
}
STORE = PROJECT / "data" / "fx_review.jsonl"


def load_events():
    events = {}
    # append-only ledger corrections (map #158 #171): a phantom-void row lists
    # the timestamps of fills the venue never executed — skip voids and voided
    _voided = set()
    _fx = LEDGERS.get("fx")
    if _fx and _fx.exists():
        for line in _fx.read_text().splitlines():
            if not line.strip():
                continue
            try:
                _r = json.loads(line)
            except Exception:
                continue
            if _r.get("reason") == "phantom-void":
                _voided.update(_r.get("voids") or [])
    for lane, path in LEDGERS.items():
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            if lane == "fx" and (r.get("reason") == "phantom-void"
                                 or r.get("timestamp") in _voided):
                continue
            if lane == "fire":
                key = f"fire:{r.get('ts')}:{r.get('symbol')}:SIGNAL:fade"
                ev = {"lane": lane, "ts": r.get("ts"), "symbol": r.get("symbol"),
                      "side": "SIGNAL", "price": None, "reason": "fade-signal",
                      "pnl": None, "fade_depth": r.get("fade_depth"),
                      "selected": r.get("selected")}
            else:
                ts = r.get("ts") or r.get("timestamp")  # fx_runner writes "timestamp"
                key = f"{lane}:{ts}:{r.get('symbol')}:{r.get('side')}:{r.get('reason')}"
                ev = {"lane": lane, "ts": ts, "symbol": r.get("symbol"),
                      "side": r.get("side"), "price": r.get("price"),
                      "reason": r.get("reason"), "pnl": r.get("pnl")}
            events[key] = ev
    return events


def load_labels():
    labels = {}
    if STORE.exists():
        for line in STORE.read_text().splitlines():
            if line.strip():
                try:
                    r = json.loads(line)
                    labels[r["key"]] = r
                except Exception:
                    pass
    return labels


def show(all_rows=False, lane_filter=None):
    events, labels = load_events(), load_labels()
    rows = [(k, e) for k, e in sorted(events.items())
            if (all_rows or k not in labels) and (not lane_filter or e["lane"] == lane_filter)]
    print(f"{len(rows)} unreviewed of {len(events)} events ({len(labels)} labeled)\n")
    hdr = f"{'lane':<7} {'ts':<12} {'symbol':<9} {'side':<7} {'price':>9} {'pnl':>9}  key"
    print(hdr)
    print("-" * len(hdr))
    for k, e in rows:
        ts = str(e.get("ts"))[:10] if e.get("ts") is not None else "?"
        price = f"{e['price']:.5f}" if isinstance(e.get("price"), float) else "-"
        pnl = f"{e['pnl']:+.2f}" if isinstance(e.get("pnl"), (int, float)) else "-"
        print(f"{e['lane']:<7} {ts:<12} {e['symbol']:<9} {str(e['side']):<7} "
              f"{price:>9} {pnl:>9}  {k}")


def label(key, verdict, note=""):
    if verdict not in ("approve", "veto"):
        raise SystemExit("verdict must be approve|veto")
    events = load_events()
    if key not in events:
        raise SystemExit(f"unknown key (must come from `show` output): {key}")
    if key in load_labels():
        raise SystemExit(f"already labeled: {key} (store is append-only)")
    row = {"ts": datetime.now(timezone.utc).isoformat(), "key": key,
           "label": verdict, "note": " ".join(note).strip(),
           "event": events[key], "human": "daryl"}
    with STORE.open("a") as f:
        f.write(json.dumps(row, default=str) + "\n")
        f.flush()
        os.fsync(f.fileno())
    print(f"[review] {verdict}: {key}")


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("show", "list"):
        show(all_rows="--all" in sys.argv,
             lane_filter=sys.argv[sys.argv.index("--lane") + 1] if "--lane" in sys.argv else None)
    elif sys.argv[1] == "label":
        label(sys.argv[2], sys.argv[3], sys.argv[4:])
    else:
        print(__doc__)
        sys.exit(2)


if __name__ == "__main__":
    main()
