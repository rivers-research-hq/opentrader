#!/usr/bin/env python3
"""fetch_exog — pull free public sentiment/positioning data into the gym's
exogenous cache (data/exog_cache.json).

Source: CFTC Commitments of Traders, Disaggregated Futures-Only report
(Socrata resource gpe5-46if, publicreporting.cftc.gov — no key needed).
Series: leveraged-money net positioning per FX futures contract, z-scored
against the trailing 52 weekly reports (≈1 year). Leveraged funds (hedge
 funds / CTAs) are the standard FX speculator-sentiment proxy.

Point-in-time discipline: the z stored at a report date uses ONLY reports up
to and including that report; consumers must apply the publication lag
(Tuesday-position report is public Friday → latest report ≤ trade_date − 3
days; enforced in the gym's Ctx.exog).

Usage:   python3 scripts/fetch_exog.py   (idempotent; rewrites the cache)
"""

import json
import statistics
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
CACHE = PROJECT / "data" / "exog_cache.json"
RESOURCE = "https://publicreporting.cftc.gov/resource/gpe5-46if.json"
Z_WINDOW = 52  # weekly reports ≈ 1 year

# CFTC contract market codes → currency key
CONTRACTS = {
    "099741": "EUR", "097741": "JPY", "096742": "GBP", "092741": "CHF",
    "090741": "CAD", "232741": "AUD", "112741": "NZD",
}


def fetch(code):
    url = (f"{RESOURCE}?%24limit=2000&%24order=report_date_as_yyyy_mm_dd%20ASC"
           f"&cftc_contract_market_code={code}"
           "&%24select=report_date_as_yyyy_mm_dd,lev_money_positions_long,lev_money_positions_short")
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)


def main():
    out = {"meta": {"fetched": datetime.now(timezone.utc).isoformat(),
                    "source": "CFTC disaggregated futures-only gpe5-46if, leveraged-money net",
                    "z_window": Z_WINDOW}}
    for code, cur in CONTRACTS.items():
        try:
            rows = fetch(code)
        except Exception as e:
            print(f"  COT:{cur}: FETCH FAILED ({e}) — skipped")
            continue
        if not rows:
            print(f"  COT:{cur}: no rows for code {code} — skipped")
            continue
        nets, zs = [], {}
        for row in rows:
            try:
                d = row["report_date_as_yyyy_mm_dd"][:10]
                net = int(row["lev_money_positions_long"]) - int(row["lev_money_positions_short"])
            except (KeyError, ValueError, TypeError):
                continue
            nets.append((d, net))
            window = [n for _, n in nets[-Z_WINDOW:]]
            if len(window) >= 26:  # need at least half a window before a z is meaningful
                sd = statistics.pstdev(window)
                zs[d] = round((net - statistics.mean(window)) / sd, 3) if sd else 0.0
        out[f"COT:{cur}"] = zs
        first, last = zs and min(zs), zs and max(zs)
        print(f"  COT:{cur}: {len(zs):4d} z-scores  {first}..{last}  latest={zs.get(last)}")
    CACHE.write_text(json.dumps(out, indent=1))
    print(f"cache written: {CACHE}")


if __name__ == "__main__":
    main()
