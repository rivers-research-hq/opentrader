#!/usr/bin/env python3
"""fetch_deep_candles — extend the benchmark's training-data history.

Fetches ~5000 D1 candles per major from the SAME source as the benchmark
cache (OANDA practice v20, mid prices, NY-anchored daily bars, incomplete
bars filtered) and writes data/signal_gym/candles_deep.json in the identical
schema. Deep history = training data for the value head ONLY; the frozen
benchmark episodes stay pinned to candles.json, so every scoreboard remains
comparable. Verifies the overlap region against the short cache before
writing (closes must match to 1e-9 on sampled timestamps) — same vendor,
same endpoint, so drift here would mean a pipeline bug, not a data artifact.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))
from exchange.oanda import OandaExchange  # noqa: E402

SHORT = PROJECT / "data" / "signal_gym" / "candles.json"
DEEP = PROJECT / "data" / "signal_gym" / "candles_deep.json"


def fetch(ex, sym):
    data = ex._request("GET", f"/v3/instruments/{sym}/candles?granularity=D&count=5000&price=M")
    out = {}
    for c in data.get("candles", []):
        if not c.get("complete", True):
            continue
        m = c.get("mid") or {}
        if not m.get("c"):
            continue
        ts = int(datetime.fromisoformat(c["time"].replace("Z", "+00:00")).timestamp())
        out[ts] = [float(m["o"]), float(m["h"]), float(m["l"]), float(m["c"])]
    return out


def main():
    ex = OandaExchange()
    if not ex.connect():
        raise SystemExit("connect failed")
    deep = {}
    for sym in ex.discover_symbols():
        deep[sym] = fetch(ex, sym)
        first = datetime.fromtimestamp(min(deep[sym]), tz=timezone.utc).date()
        last = datetime.fromtimestamp(max(deep[sym]), tz=timezone.utc).date()
        print(f"  {sym}: {len(deep[sym])} bars  {first} -> {last}")

    short = json.load(open(SHORT))
    checked = mismatches = 0
    for sym, s in short.items():
        for ts, px in s.items():
            ts = int(ts)
            if ts in deep.get(sym, {}):
                checked += 1
                if max(abs(a - b) for a, b in zip(deep[sym][ts], px)) > 1e-9:
                    mismatches += 1
    print(f"overlap check: {checked} shared bars, {mismatches} mismatches")
    if checked == 0 or mismatches:
        raise SystemExit("OVERLAP VERIFICATION FAILED — not writing deep cache")

    DEEP.write_text(json.dumps(deep))
    print(f"deep cache written: {DEEP}")


if __name__ == "__main__":
    main()
