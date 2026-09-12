#!/usr/bin/env python3
"""fxexpert.data — build the training panel from the accrual store.

Per-pair per-day features (all causal: computed from bars/exog at or before
t), forward-return labels, and per-row metadata. The feature block covers the
classic indicator families (RSI/MACD/stoch/breakout/z/vol regime), carry,
policy-rate differentials, COT positioning and event proximity — the research
agent's candidate mechanisms (docs/agents/research/fx-alt-data-inventory +
#199) as far as the store holds them. Missing exog blocks are 0-filled with an
explicit mask feature so the model can learn pair-wise availability.

Output: data/fx_expert/panel.npz + panel_meta.json
"""

import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

STORE = "/home/mrc/opentrader-data/store.duckdb"
OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "fx_expert"

# Round-trip cost as a return fraction (heuristic, labeled as such): USD
# majors ~1.2 pips, G10 crosses ~1.8, EM/other ~5.0. Used by the gate, not
# by training.
COST_MAJORS = 0.00012
COST_CROSS = 0.00018
COST_EM = 0.00050
G10 = {"USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF"}

# ISO currency -> BIS policy-rate area (RATEBIS:* in the store; fetched by
# scripts/fetch_policy_rates.py). SGD is absent by design: Singapore's policy
# is the S$NEER band, not a rate — SGD pairs carry a masked carry block.
BIS_AREA = {"USD": "US", "EUR": "XM", "GBP": "GB", "JPY": "JP", "AUD": "AU",
            "NZD": "NZ", "CAD": "CA", "CHF": "CH", "SEK": "SE", "NOK": "NO",
            "CZK": "CZ", "HUF": "HU", "PLN": "PL", "TRY": "TR", "ZAR": "ZA",
            "CNH": "CN", "THB": "TH", "MXN": "MX"}

# Calendar-feed currency codes (nfs.faireconomy.media) -> ISO. The event join
# used ISO codes against these codes, so it never matched (17,960 high-impact
# events invisible). SP/BE/WW are not traded here and are ignored.
FF_CCY = {"US": "USD", "EZ": "EUR", "UK": "GBP", "JN": "JPY", "SZ": "CHF",
          "CH": "CNH", "CA": "CAD", "AU": "AUD", "NZ": "NZD"}
ISO_FF = {iso: code for code, iso in FF_CCY.items()}

# Commodity terms-of-trade baskets (heuristic weights, labeled as such):
# net-export exposure per currency. Only currencies with an unambiguous
# commodity story carry weights; an empty basket means the pair's ToT block is
# masked rather than zero-filled.
TOT_BASKET = {
    "AUD": {"iron": 0.5, "copper": 0.5},
    "NZD": {"dairy": 1.0},
    "CAD": {"oil": 1.0},
    "NOK": {"oil": 1.0},
    "ZAR": {"gold": 0.5, "iron": 0.5},
    "JPY": {"oil": -1.0},       # classic commodity importer
}


def pair_cost(pair):
    a, b = pair.split("_")
    g10 = a in G10 and b in G10
    if g10 and "USD" in (a, b):
        return COST_MAJORS
    if g10:
        return COST_CROSS
    return COST_EM


def _rsi(close, n=14):
    delta = close.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def _pair_features(pair, bars, carry_s, rate_base, rate_quote, cot_z, ev_cnt,
                   h1p=None, fred_map=None, carry_pv=None, tot_pair=None):
    c = bars["close"].astype(float)
    h = bars["high"].astype(float)
    lo = bars["low"].astype(float)
    ret = c.pct_change()

    f = pd.DataFrame(index=bars.index)
    f["ret_1d"] = ret
    for lb in (5, 10, 20, 60, 120):
        f[f"mom_{lb}d"] = c / c.shift(lb) - 1.0
    rsi = _rsi(c)
    f["rsi_14"] = rsi / 100.0 - 0.5
    f["rsi_slope_5"] = (rsi - rsi.shift(5)) / 50.0
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    f["macd_norm"] = macd / c
    f["macd_hist"] = (macd - signal) / c
    hh14, ll14 = h.rolling(14).max(), lo.rolling(14).min()
    f["stoch_k14"] = (c - ll14) / (hh14 - ll14).replace(0, np.nan) - 0.5
    hh20, ll20 = h.rolling(20).max(), lo.rolling(20).min()
    f["range_pos_20d"] = (c - ll20) / (hh20 - ll20).replace(0, np.nan) - 0.5
    f["brk_20d"] = c / hh20 - 1.0
    f["brk_60d"] = c / h.rolling(60).max() - 1.0
    f["z_20d"] = (c - c.rolling(20).mean()) / c.rolling(20).std()
    f["z_60d"] = (c - c.rolling(60).mean()) / c.rolling(60).std()
    vol20 = ret.rolling(20).std()
    vol60 = ret.rolling(60).std()
    f["vol_20d"] = vol20
    f["vol_ratio"] = vol20 / vol60 - 1.0
    f["atr_pct"] = (h - lo).rolling(14).mean() / c
    f["efficiency_20d"] = (c - c.shift(20)).abs() / (hh20 - ll20).replace(0, np.nan)
    dow = pd.Index(bars.index).dayofweek
    f["dow_sin"] = np.sin(2 * np.pi * dow / 7.0)
    f["dow_cos"] = np.cos(2 * np.pi * dow / 7.0)

    # exog blocks (sparse across pairs — always paired with a mask)
    f["carry"] = carry_s.reindex(bars.index) if carry_s is not None else np.nan
    if carry_s is not None:
        mu = carry_s.rolling(252, min_periods=60).mean()
        sd = carry_s.rolling(252, min_periods=60).std().replace(0, np.nan)
        f["carry_z"] = (carry_s - mu) / sd
    else:
        f["carry_z"] = np.nan
    f["carry_mask"] = f["carry"].notna().astype(float)

    rd = None
    if rate_base is not None and rate_quote is not None:
        rd = rate_base.reindex(bars.index) - rate_quote.reindex(bars.index)
    elif rate_base is not None:
        rd = rate_base.reindex(bars.index) * np.nan  # base-only: still masked
    f["rate_diff"] = rd
    f["rate_diff_chg20"] = rd.diff(20) if rd is not None else np.nan
    f["rate_mask"] = f["rate_diff"].notna().astype(float)

    # panel v2: policy-rate carry for every pair the rate table covers
    # (pre-registered 2026-09-12; the old CARRY:* block reached 6 pairs).
    if carry_pv is not None and len(carry_pv):
        cp = carry_pv.reindex(bars.index)
        f["pv_carry"] = cp
        mu = carry_pv.rolling(252, min_periods=60).mean()
        sd = carry_pv.rolling(252, min_periods=60).std().replace(0, np.nan)
        f["pv_carry_z"] = ((carry_pv - mu) / sd).reindex(bars.index)
        f["pv_carry_chg20"] = carry_pv.diff(20).reindex(bars.index)
    else:
        for col in ("pv_carry", "pv_carry_z", "pv_carry_chg20"):
            f[col] = np.nan
    f["pv_carry_mask"] = f["pv_carry"].notna().astype(float)

    # panel v2: commodity terms of trade, base vs quote basket
    if tot_pair is not None and len(tot_pair):
        tp = tot_pair.reindex(bars.index)
        f["pv_tot_diff"] = tp
        f["pv_tot_chg20"] = tot_pair.diff(20).reindex(bars.index)
    else:
        f["pv_tot_diff"] = np.nan
        f["pv_tot_chg20"] = np.nan
    f["pv_tot_mask"] = f["pv_tot_diff"].notna().astype(float)

    f["cot_z"] = cot_z.reindex(bars.index) if cot_z is not None else np.nan
    f["cot_mask"] = f["cot_z"].notna().astype(float)

    ec = ev_cnt.reindex(bars.index) if ev_cnt is not None else None
    if ec is not None:
        f["events_5d"] = ec.fillna(0).clip(upper=5) / 5.0
    else:
        f["events_5d"] = 0.0

    # intraday structure from H1 bars (new information vs D1 aggregates)
    if h1p is not None and len(h1p):
        idx = bars.index
        rng = (h1p["hi"] - h1p["lo"])
        f["h1_range_pct"] = (rng / h1p["c"]).reindex(idx)
        f["h1_close_pos"] = ((h1p["c"] - h1p["lo"]) / rng.replace(0, np.nan)).reindex(idx)
        f["h1_sess_am"] = (h1p["c_am"] / h1p["o_am"] - 1.0).reindex(idx)
        f["h1_sess_pm"] = (h1p["c"] / h1p["c_am"] - 1.0).reindex(idx)
        f["h1_vol24"] = h1p["hvol"].reindex(idx)
    else:
        for col in ("h1_range_pct", "h1_close_pos", "h1_sess_am",
                    "h1_sess_pm", "h1_vol24"):
            f[col] = np.nan

    # FRED macro conditioning (global risk/credit/policy/ToT state)
    for name, zser in (fred_map or {}).items():
        f[name] = zser.reindex(bars.index)

    lab = pd.DataFrame(index=bars.index)
    lab["fwd1"] = c.shift(-1) / c - 1.0
    lab["fwd5"] = c.shift(-5) / c - 1.0
    lab["fwd10"] = c.shift(-10) / c - 1.0
    lab["fwd20"] = c.shift(-20) / c - 1.0
    lab["vol20"] = vol20
    lab["rsi_raw"] = rsi
    lab["mom20"] = f["mom_20d"]
    return f, lab


def _lake_series(name):
    """Daily series from the local accumulator lake (parquet, DatetimeIndex,
    `value` column). Used for gold — FRED discontinued its gold fix series."""
    p = Path(__file__).resolve().parent.parent / "data" / "accumulator" / "lake" / f"{name}.parquet"
    if not p.exists():
        return None
    try:
        df = pd.read_parquet(p)
        s = pd.Series(df["value"].to_numpy(dtype=float),
                      index=pd.DatetimeIndex(df.index).floor("D"))
        return s.groupby(level=0).last()
    except Exception:
        return None


def build(store=STORE, out_dir=OUT_DIR, out_name="panel.npz"):
    out_dir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(store, read_only=True)
    pairs = [r[0] for r in con.execute(
        "SELECT DISTINCT symbol FROM bars WHERE timeframe='1d' ORDER BY 1").fetchall()]

    def exog_series(name):
        rows = con.execute(
            "SELECT CAST(date AS DATE) d, value FROM exog "
            "WHERE series = ? AND value IS NOT NULL ORDER BY d",
            [name]).fetchall()
        if not rows:
            return None
        s = pd.Series({pd.Timestamp(d): float(v) for d, v in rows})
        return s.groupby(level=0).last()

    # Policy rates for every traded currency. BIS daily legs are primary; the
    # older FRED-derived RATE:* legs are a fallback only. The v1 panel keyed
    # this table US/EA/GB/CA while pairs carry ISO codes, so `rate_diff` was
    # dead for every pair (0.0% non-zero) — fixed 2026-09-12.
    rates = {}
    for iso, area in BIS_AREA.items():
        s = exog_series(f"RATEBIS:{area}")
        if s is not None:
            rates[iso] = s
    for cc, iso in (("US", "USD"), ("EA", "EUR"), ("GB", "GBP"), ("CA", "CAD")):
        if iso not in rates:
            s = exog_series(f"RATE:{cc}")
            if s is not None:
                rates[iso] = s
    # lag 1 day: the BIS file is compiled from central banks and published
    # after the fact; the value in effect on day T is used for day T+1
    # decisions (same discipline as the FRED conditioning block).
    rates = {iso: s.shift(1) for iso, s in rates.items()}
    print(f"[data] policy rates for {len(rates)} currencies: "
          f"{', '.join(sorted(rates))}")
    cots = {cc: exog_series(f"COT:{cc}")
            for cc in ("EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD")}

    # FRED conditioning: causal rolling z on the calendar, then the
    # publication lag (daily series 1d, monthly prints 15d — a monthly value
    # for month M is public mid-M+1; conservative either way)
    MONTHLY = {"FRED:PIORECRUSDM", "FRED:PNGASEUUSDM", "FRED:PCOPPUSDM"}
    FRED_NAMES = {"FRED:VIXCLS": "fred_vix_z", "FRED:BAMLH0A0HYM2": "fred_hy_z",
                  "FRED:USEPUINDXD": "fred_epu_z", "FRED:DCOILWTICO": "fred_wti_z",
                  "FRED:PIORECRUSDM": "fred_iron_z", "FRED:PNGASEUUSDM": "fred_ttf_z",
                  # panel v2 (pre-registered 2026-09-12): dollar / policy-path
                  # state. DGS10 and T10Y2Y were in the store but never wired
                  # into the panel; DGS2 and DFII10 are new legs.
                  "FRED:DGS2": "fred_dgs2_z", "FRED:DGS10": "fred_dgs10_z",
                  "FRED:T10Y2Y": "fred_curve_z", "FRED:DFII10": "fred_real10_z"}
    cal = pd.date_range("2005-01-01", "2026-12-31", freq="D").as_unit("ns")

    def _z(ser, monthly=False):
        sd = ser.reindex(cal).shift(15 if monthly else 1)
        mu = sd.rolling(252, min_periods=60).mean()
        sds = sd.rolling(252, min_periods=60).std().replace(0, np.nan)
        return (sd - mu) / sds

    fred_map = {}
    for sid, name in FRED_NAMES.items():
        ser = exog_series(sid)
        if ser is not None:
            fred_map[name] = _z(ser, sid in MONTHLY)
    if "fred_wti_z" in fred_map:
        wti = exog_series("FRED:DCOILWTICO").reindex(cal).shift(1)
        fred_map["fred_wti_chg20"] = wti.pct_change(20).clip(-0.5, 0.5)

    # panel v2: commodity prices for the terms-of-trade baskets. Same lag
    # discipline as the FRED block (daily 1d, monthly 15d).
    comm = {}
    for key, sid in (("oil", "FRED:DCOILWTICO"), ("copper", "FRED:PCOPPUSDM"),
                     ("iron", "FRED:PIORECRUSDM"), ("dairy", "FRED:PNGASEUUSDM")):
        ser = exog_series(sid)
        if ser is not None:
            comm[key] = _z(ser, sid in MONTHLY)
    gld = _lake_series("etf.GLD")
    if gld is not None:
        comm["gold"] = _z(gld)
    print(f"[data] commodity legs: {', '.join(sorted(comm))}")

    def tot_index(weights):
        """Weighted z-composite of a currency's commodity basket; None when
        any leg is unavailable (masked downstream rather than zero-filled)."""
        if not weights or any(k not in comm for k in weights):
            return None
        out = None
        for k, w in weights.items():
            term = comm[k] * w
            out = term if out is None else out + term
        return out

    # H1-derived daily aggregates (intraday structure the D1 bars hide)
    h1 = con.execute("""
        SELECT symbol, CAST(ts AS DATE) d, MIN(low) lo, MAX(high) hi,
               arg_min(open, ts) o, arg_max(close, ts) c,
               arg_max(CASE WHEN extract(hour from ts) < 12 THEN close END, ts) c_am,
               arg_min(CASE WHEN extract(hour from ts) < 12 THEN open END, ts) o_am
        FROM bars WHERE timeframe = '1h' GROUP BY 1, 2
    """).fetchall()
    h1_df = pd.DataFrame(h1, columns=["symbol", "d", "lo", "hi", "o", "c",
                                      "c_am", "o_am"])
    h1_df["d"] = pd.DatetimeIndex(pd.to_datetime(h1_df["d"])).as_unit("ns")
    h1_df = h1_df.set_index(["symbol", "d"])
    h1c = con.execute("SELECT symbol, ts, close FROM bars WHERE timeframe='1h' "
                      "ORDER BY symbol, ts").fetchall()
    hdf = pd.DataFrame(h1c, columns=["s", "ts", "c"])
    hdf["d"] = pd.DatetimeIndex(pd.to_datetime(hdf["ts"])).as_unit("ns").floor("D")
    hdf["lr"] = np.log(hdf["c"].astype(float)).groupby(hdf["s"]).diff()
    hvol = (hdf.groupby(["s", "d"])["lr"].std() * np.sqrt(24.0)).rename("hvol")
    hvol.index = hvol.index.set_names(["symbol", "d"])
    h1_df = h1_df.join(hvol, how="left")
    h1_by_pair = {sym: sub for sym, sub in h1_df.groupby(level=0)}
    h1_by_pair = {sym: sub.droplevel(0) for sym, sub in h1_by_pair.items()}

    ev = con.execute("""
        SELECT CAST(ts AS DATE) d, currency, COUNT(*) n FROM releases_history
        WHERE impact = 'high' GROUP BY 1, 2
    """).fetchall()
    ev_daily = {}
    for d, cur, n in ev:
        ev_daily.setdefault(cur, {})[pd.Timestamp(d)] = float(n)
    cal = pd.date_range("2008-01-01", "2026-12-31", freq="D").as_unit("ns")

    def ev_count(currencies):
        total = pd.Series(0.0, index=cal)
        hit = False
        for cur in currencies:
            code = ISO_FF.get(cur)  # calendar feed codes, not ISO (v1 joined
            if code in ev_daily:    # ISO against these -> events_5d was all 0)
                s = pd.Series(ev_daily[code]).groupby(level=0).sum()
                total = total.add(s.reindex(cal).fillna(0), fill_value=0)
                hit = True
        if not hit:
            return None
        return total.rolling(5).sum().dropna()

    feats, labs, meta_rows = [], [], []
    for pi, pair in enumerate(pairs):
        rows = con.execute("""
            SELECT ts, open, high, low, close FROM bars
            WHERE symbol = ? AND timeframe = '1d' ORDER BY ts
        """, [pair]).fetchall()
        if len(rows) < 120:
            continue
        bars = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close"])
        bars["ts"] = pd.DatetimeIndex(pd.to_datetime(bars["ts"])).as_unit("ns").floor("D")
        bars = bars.groupby("ts").last()
        base, quote = pair.split("_")
        carry_s = exog_series(f"CARRY:{pair}")
        rate_base, rate_quote = rates.get(base), rates.get(quote)
        # panel v2: carry (policy-rate differential) for every covered pair;
        # the legacy pair-level CARRY leg is a fallback where BIS has no rate.
        carry_pv = (rate_base - rate_quote) if (rate_base is not None and
                                                rate_quote is not None) else carry_s
        tb, tq = TOT_BASKET.get(base), TOT_BASKET.get(quote)
        tot_pair = None
        if tb or tq:
            sb = tot_index(tb) if tb else pd.Series(0.0, index=cal)
            sq = tot_index(tq) if tq else pd.Series(0.0, index=cal)
            if sb is not None and sq is not None:
                tot_pair = sb - sq
        cot = None
        if base in cots:
            cot = cots[base]
        elif quote in cots:
            cot = -cots[quote]
        evc = ev_count({base, quote})

        f, lab = _pair_features(pair, bars, carry_s, rate_base, rate_quote,
                                cot, evc, h1p=h1_by_pair.get(pair),
                                fred_map=fred_map, carry_pv=carry_pv,
                                tot_pair=tot_pair)
        feats.append(f)
        lab["pair_idx"] = pi
        lab["cost"] = pair_cost(pair)
        labs.append(lab)
        meta_rows.append({"pair": pair, "idx": pi, "rows": len(bars),
                          "start": str(bars.index.min().date()),
                          "end": str(bars.index.max().date())})

    F = pd.concat(feats)
    # cross-sectional (common-factor) features: FX is dominated by the USD
    # leg — a per-pair-only model cannot express "dollar strong everywhere".
    # Same-date means across all traded pairs; causal by construction.
    xs = F[["mom_5d", "mom_20d", "mom_60d", "vol_20d", "rsi_14"]].groupby(level=0).mean()
    xs.columns = ["xs_mom5", "xs_mom20", "xs_mom60", "xs_vol20", "xs_rsi_mean"]
    F = F.join(xs, how="left")
    # panel v2: cross-sectionally demeaned carry and ToT — what a
    # dollar-neutral rank book actually harvests (levels include the common
    # USD leg, which nets out of a neutral book).
    F["pv_carry_xs"] = (F["pv_carry"]
                        - F["pv_carry"].groupby(level=0).transform("mean"))
    F["pv_tot_xs"] = (F["pv_tot_diff"]
                      - F["pv_tot_diff"].groupby(level=0).transform("mean"))
    L = pd.concat(labs)
    dates = F.index
    feat_names = list(F.columns)
    X = F.to_numpy(dtype=np.float32)
    nan_before = int(np.isnan(X).sum())
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

    panel = {
        "features": X,
        "feature_names": np.array(feat_names),
        # day numbers since epoch (unit-proof; pandas 3 stores us, not ns)
        "date": ((dates - pd.Timestamp(1970, 1, 1)) // pd.Timedelta(days=1))
                .to_numpy(dtype=np.int64),
        "pair_idx": L["pair_idx"].to_numpy(dtype=np.int32),
        "fwd1": L["fwd1"].to_numpy(dtype=np.float32),
        "fwd5": L["fwd5"].to_numpy(dtype=np.float32),
        "fwd10": L["fwd10"].to_numpy(dtype=np.float32),
        "fwd20": L["fwd20"].to_numpy(dtype=np.float32),
        "vol20": L["vol20"].to_numpy(dtype=np.float32),
        "rsi_raw": L["rsi_raw"].to_numpy(dtype=np.float32),
        "mom20": L["mom20"].to_numpy(dtype=np.float32),
        "cost": L["cost"].to_numpy(dtype=np.float32),
    }
    np.savez_compressed(out_dir / out_name, **panel)
    meta = {
        "pairs": meta_rows, "n_rows": len(X), "n_features": len(feat_names),
        "feature_names": feat_names, "nan_filled": nan_before,
        "date_min": str(dates.min().date()), "date_max": str(dates.max().date()),
        "cost_model": {"majors": COST_MAJORS, "em": COST_EM,
                       "note": "heuristic round-trip return cost"},
        "policy_rate_currencies": sorted(rates),
        "commodity_legs": sorted(comm),
    }
    meta_path = out_dir / out_name.replace(".npz", "_meta.json")
    meta_path.write_text(json.dumps(meta, indent=1))
    print(f"[data] panel: {len(X)} rows x {len(feat_names)} features, "
          f"{len(meta_rows)} pairs, {meta['date_min']} -> {meta['date_max']}, "
          f"nan-filled {nan_before} -> {out_dir / out_name}")
    return meta


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Build the fxexpert training panel")
    ap.add_argument("--out", default="panel.npz",
                    help="output file under data/fx_expert (panel_v2.npz for the "
                         "pre-registered 2026-09-12 round; panel.npz is the live "
                         "panel the running lanes' checkpoints match)")
    ap.add_argument("--store", default=STORE)
    a = ap.parse_args()
    build(store=a.store, out_name=a.out)
