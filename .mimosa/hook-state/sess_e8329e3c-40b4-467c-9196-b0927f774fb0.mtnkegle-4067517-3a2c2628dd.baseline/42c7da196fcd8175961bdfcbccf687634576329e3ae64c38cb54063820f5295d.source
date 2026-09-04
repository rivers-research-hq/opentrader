#!/usr/bin/env python3
"""A/B diff: MAIN harness (19 syms) vs SHADOW (28 syms). Paper only, read-only.

Run:  python3 ab_diff.py
Compares equity, positions, and fills. Flags the 9 'new' symbols the shadow
added (XLF/XLE/XLI/XLB/XLRE/XLP/XLV/XLU/GLD) -- that is the experiment.
"""
import json
from pathlib import Path

MAIN = Path("/home/mrc/opentrader/data/paper_state.json")
SHADOW = Path("/home/mrc/opentrader/data/shadow_scaled/paper_state.json")
NEW9 = {"XLF", "XLE", "XLI", "XLB", "XLRE", "XLP", "XLV", "XLU", "GLD"}


def load(p):
    with open(p) as f:
        return json.load(f)


def summarize(name, st):
    pos = st.get("positions", [])
    held = {p["symbol"]: p for p in pos}
    print(f"=== {name} ===")
    print(f"  cycle={st.get('cycle')}  ts={st.get('timestamp')}")
    print(f"  cash=${st.get('cash', 0):.2f}  portfolio_value=${st.get('portfolio_value', 0):.2f}  (initial ${st.get('initial_cash', 0):.0f})")
    print(f"  positions ({len(pos)}):")
    for p in pos:
        qty = p.get("quantity", 0)
        entry = p.get("entry_price", 0)
        cur = p.get("current_price", 0)
        upnl = (cur - entry) * qty
        tag = "  [NEW9]" if p["symbol"] in NEW9 else ""
        print(f"    {p['symbol']:<10} qty={qty:.6g}  entry={entry:.6g}  now={cur:.6g}  uPnL=${upnl:+.2f}{tag}")
    print(f"  total fills: {len(st.get('fills', []))}")
    return held


def main():
    m = load(MAIN)
    s = load(SHADOW)
    mheld = summarize("MAIN (19 syms)", m)
    print()
    sheld = summarize("SHADOW (28 syms)", s)
    print()
    print("=== A/B COMPARISON ===")
    mv = m.get("portfolio_value", 0)
    sv = s.get("portfolio_value", 0)
    print(f"  equity:  main=${mv:.2f}   shadow=${sv:.2f}   diff=${sv - mv:+.2f}")
    shadow_only = sorted(set(sheld) - set(mheld))
    main_only = sorted(set(mheld) - set(sheld))
    print(f"  shadow-only positions: {shadow_only or 'none'}")
    print(f"  main-only positions:   {main_only or 'none'}")
    new9_held = sorted(x for x in sheld if x in NEW9)
    print(f"  shadow holding NEW9 (the experiment): {new9_held or 'none yet'}")
    new9_fills = [f for f in s.get("fills", []) if f["symbol"] in NEW9]
    print(f"  shadow fills on NEW9: {len(new9_fills)}")
    for f in new9_fills[-10:]:
        print(f"    {f['timestamp'][:16]}  {f['side']:<4} {f['symbol']:<6} @ {f['price']:.6g}")


if __name__ == "__main__":
    main()
