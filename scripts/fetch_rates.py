#!/usr/bin/env python3
"""fetch_rates — central-bank policy/overnight rates into the gym's exogenous
from security.guards import guarded_urlopen, guarded_open, guarded_requests_get, sec_pickle_load  # noqa: E402  (hardening layer)
urlopen = guarded_urlopen  # hardening shadow
cache (data/exog_cache.json), same point-in-time discipline as COT.

Sources (probed 2026-09-01, all free, no keys):
  FRED keyless CSV (fredgraph.csv):
    RATE:US  DFF      — effective federal funds rate, DAILY (published T+1 → 1d lag)
    RATE:EA  ECBDFR   — ECB deposit facility rate, DAILY (announced in advance, lag 0)
    RATE:GB  IUDSOIA  — SONIA overnight, DAILY (published T+1 → 1d lag)
  Bank of Canada valet API:
    RATE:CA  V39079   — target overnight rate, business daily (lag 0)

Missing legs (source hunt continues, see ToC BM3): JPY, CHF, AUD, NZD — the
four FRED BIS/OECD monthly series are discontinued (end 2013–2023), RBNZ site
was down, SNB cube guesses returned the wrong dataset, RBA's daily CSV URL
404'd. Carry is computed only where BOTH legs exist; the US rate cycle
features (us_rate_lvl / us_rate_chg90) have full coverage via DFF since every
major has a USD leg.

Publication-lag handling: each daily series is shifted so value[D] was public
knowledge on day D — DFF and SONIA by one day, ECB/BoC policy rates by zero
(decision-day announcements).
"""
from security.guards import guarded_urlopen, guarded_open, guarded_requests_get, sec_pickle_load  # noqa: E402  (hardening layer)
urlopen = guarded_urlopen  # hardening shadow

import json
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
CACHE = PROJECT / "data" / "exog_cache.json"
START = "2008-01-01"


def _fred(sid):
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"
    with urllib.request.urlopen(url, timeout=60) as r:
        rows = r.read().decode().splitlines()[1:]
    out = {}
    for row in rows:
        parts = row.split(",")
        if len(parts) != 2 or not parts[1]:
            continue
        try:
            out[date.fromisoformat(parts[0])] = float(parts[1])
        except ValueError:
            continue
    return out


def _boc(sid):
    url = (f"https://bankofcanada.ca/valet/observations/{sid}/json"
           f"?start_date={START}&end_date={date.today().isoformat()}")
    with urllib.request.urlopen(url, timeout=60) as r:
        obs = json.load(r).get("observations", [])
    return {date.fromisoformat(o["d"]): float(o[sid]["v"]) for o in obs if sid in o}


def _shift(daily, lag_days):
    """Value for day D becomes usable at D+lag (point-in-time)."""
    return {d + timedelta(days=lag_days): v for d, v in daily.items()}


def main():
    cache = json.load(open(CACHE)) if CACHE.exists() else {}
    today = date.today()
    series = {
        "RATE:US": _shift(_fred("DFF"), 1),
        "RATE:EA": _shift(_fred("ECBDFR"), 0),
        "RATE:GB": _shift(_fred("IUDSOIA"), 1),
        "RATE:CA": _shift(_boc("V39079"), 0),
    }
    for key, daily in series.items():
        usable = {d.isoformat(): v for d, v in daily.items() if d <= today}
        first, last = min(usable), max(usable)
        cache[key] = usable
        print(f"  {key}: {len(usable)} days  {first}..{last}  latest={usable[last]}")

    # per-pair carry (base policy rate minus quote) for the gym candidates —
    # only pairs whose BOTH legs exist are written (honest missingness)
    CUR_KEY = {"USD": "US", "EUR": "EA", "GBP": "GB", "CAD": "CA"}
    for sym in ("EUR_USD", "GBP_USD", "USD_JPY", "USD_CHF", "GBP_JPY",
                "AUD_USD", "USD_CAD", "EUR_GBP", "EUR_JPY", "EUR_CHF", "EUR_AUD",
                "EUR_CAD", "EUR_NZD", "GBP_JPY", "GBP_CHF", "AUD_JPY", "AUD_CAD",
                "AUD_CHF", "NZD_JPY", "NZD_CHF", "NZD_USD", "CAD_JPY", "CAD_CHF",
                "CHF_JPY", "GBP_AUD", "GBP_CAD", "GBP_NZD"):
        base, quote = sym.split("_")
        if base not in CUR_KEY or quote not in CUR_KEY:
            continue
        kb, kq = "RATE:" + CUR_KEY[base], "RATE:" + CUR_KEY[quote]
        carry = {}
        for d, v in series[kb].items():
            if d in series[kq]:
                carry[d.isoformat()] = round(v - series[kq][d], 4)
        if carry:
            cache["CARRY:" + sym] = carry
    cache["meta"]["rates_sources"] = ("FRED DFF/ECBDFR/IUDSOIA + BoC valet V39079; "
                                      "lags: DFF/SONIA +1d, policy rates 0; "
                                      "missing legs JPY/CHF/AUD/NZD (ToC BM3)")
    cache["meta"]["fetched"] = datetime.now(timezone.utc).isoformat()
    CACHE.write_text(json.dumps(cache, indent=1))
    print(f"cache written: {CACHE}")


if __name__ == "__main__":
    main()
