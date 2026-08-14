#!/usr/bin/env python3
"""Macro features bridge: World Bank + economic calendar -> per-bar strategy
features. This is what Round 1e agents consume.

Produces, aligned to a master DatetimeIndex:
  cal_next_in_days     : days until the next economic release
  cal_since_last_days  : days since the last release
  cal_density_14       : # releases in the trailing 14 days
  cal_proximity        : 0..1 proximity feature (peak on release day)
  cal_fomc_soon        : 1 if an FOMC decision lands within 7 days
  wb_us_gdp_growth     : World Bank US GDP growth (annual, ffill)
  wb_us_inflation      : World Bank US CPI inflation (annual, ffill)
  wb_cn_gdp_growth     : China GDP growth (annual, ffill)
  wb_em_gdp_growth     : average EM (BR/IN/ID/MX/ZA) GDP growth (annual, ffill)

HONEST LABELING: calendar features are forward-looking-but-scheduled (the
release DATE is known; the VALUE is not) — legitimate, no lookahead on
outcomes. WB features are annual with publication lag (ffill'd; they lag
reality by ~a year) — labeled regime CONTEXT, not a daily signal.
"""

import datetime as dt

import pandas as pd

from data import economic_calendar as cal
from data import world_bank as wb


def build_features(master: pd.DatetimeIndex, wb_bundle: dict = None,
                   use_world_bank: bool = True) -> pd.DataFrame:
    if wb_bundle is None:
        wb_bundle = wb.load_world_bank()
    wb_frame = wb.world_bank_to_frame(wb_bundle) if use_world_bank else pd.DataFrame()

    n = len(master)
    out = pd.DataFrame(index=master)
    dates = [d.date() if hasattr(d, "date") else d for d in master]

    cal_next, cal_since, dens, prox, fomc = [], [], [], [], []
    for d in dates:
        cal_next.append(cal.days_until_next(d))
        cal_since.append(cal.days_since_last(d))
        dens.append(cal.release_density(d, 14))
        prox.append(cal.release_proximity(d))
        fomc.append(1 if (cal.next_release(d)[1] == "FOMC decision"
                          and cal.days_until_next(d) <= 7) else 0)

    out["cal_next_in_days"] = pd.Series(cal_next, index=master)
    out["cal_since_last_days"] = pd.Series(cal_since, index=master)
    out["cal_density_14"] = pd.Series(dens, index=master)
    out["cal_proximity"] = pd.Series(prox, index=master)
    out["cal_fomc_soon"] = pd.Series(fomc, index=master)

    if not wb_frame.empty:
        # ffill annual WB data onto the master index (no lookahead: a year's
        # value is only known after publication, so use last FULL year <= date)
        for col in wb_frame.columns:
            s = wb_frame[col]
            s = s[~s.index.duplicated(keep="last")]
            # reindex to master with method='ffill' is NOT enough (annual
            # year-end timestamps) — shift so a year's value applies from the
            # FOLLOWING year (publication lag) then ffill.
            shifted = s.copy()
            shifted.index = shifted.index + pd.DateOffset(years=1)  # publish next year
            aligned = shifted.reindex(master, method="ffill")
            out["wb_" + col.replace("__", "_")] = aligned
    return out


def summary(features: pd.DataFrame) -> str:
    lines = ["[macro-features]"]
    cols = list(features.columns)
    latest = features.iloc[-1]
    for c in cols:
        v = latest.get(c)
        if pd.notna(v):
            lines.append(f"  {c}: {v:.4f}")
    return "\n".join(lines)


if __name__ == "__main__":
    import pickle
    INT = pickle.load(open("/tmp/opentrader/swarm/intl_data.pkl", "rb"))
    f = build_features(INT["master"])
    print(f"features: {len(f.columns)} cols x {len(f)} bars")
    print(summary(f))
