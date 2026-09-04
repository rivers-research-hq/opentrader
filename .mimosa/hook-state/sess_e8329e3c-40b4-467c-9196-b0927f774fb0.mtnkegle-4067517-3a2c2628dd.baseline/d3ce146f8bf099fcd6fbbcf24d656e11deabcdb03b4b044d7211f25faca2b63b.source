"""Labeled candidate rows for the arena.

Mirrors setup_search/value_head.collect() but keeps the raw feature row,
regime flag, and score so opponent bots and the war referee can vote on the
same states the value head trains on.
"""

from pathlib import Path

import numpy as np

from setup_search.core import clamp_config
from setup_search.data import REGIME_SYM, load_ohlcv, align
from setup_search.engine import _features, _score_at

PROJECT = Path(__file__).resolve().parent.parent
FORWARD = 10
FEAT_COLS = [
    "mom",
    "rev",
    "rsi",
    "brk",
    "z",
    "ma_dist",
    "vol_spike",
    "vol_level",
    "momfilt",
]


def collect(
    period="5y", gen_score_min=-0.5, cfg_path=PROJECT / "data/setup_search/best.json"
):
    base = clamp_config(__import__("json").loads(cfg_path.read_text())["config"])
    data = load_ohlcv(period)
    return collect_from_data(data, base, gen_score_min=gen_score_min)


def collect_from_data(data, base, gen_score_min=-0.5, bar_offset=0):
    """Build arena candidate rows from ANY aligned-ready OHLCV dict
    ({symbol: DataFrame}, SPY = regime marker) — real archives or generated
    multiverse worlds. bar_offset shifts synthetic rows outside the real
    bar range so the gate windows and war relabels never see them."""
    al = align(data, [s for s in data if s != REGIME_SYM])
    closes, highs, lows, vols = al
    feat = _features(closes, highs, lows, vols, base)
    spy = closes.get(REGIME_SYM)
    spy_ma = None
    if base["regime_filter"] and spy is not None:
        spy_ma = spy.rolling(int(base["regime_window"]), min_periods=10).mean()
    spy_ma200 = spy.rolling(200, min_periods=60).mean() if spy is not None else None
    master = next(iter(closes.values())).index
    rows = []
    for sym in sorted(closes.keys()):
        if sym == REGIME_SYM:
            continue
        c, f = closes[sym], feat[sym]
        for t in range(len(c)):
            if t + FORWARD >= len(c):
                break
            # data hygiene: delisted/suspended symbols in broad datasets carry
            # zero/NaN closes — a zero close divides by zero in the label
            c0, c1 = float(c.iloc[t]), float(c.loc[c.index[t + FORWARD]])
            if not (np.isfinite(c0) and np.isfinite(c1) and c0 > 0 and c1 > 0):
                continue
            date = c.index[t]
            if date not in master:
                continue
            s = float(_score_at({sym: f.loc[date]}, base, {sym: 0.0})[sym])
            if s != s or s < gen_score_min:
                continue
            regime_up = True
            if spy_ma is not None and date in spy_ma.index:
                regime_up = float(spy[date]) > float(spy_ma[date])
            v = [
                0.0 if f.loc[date][k] != f.loc[date][k] else float(f.loc[date][k])
                for k in FEAT_COLS
            ]
            spy_ratio = 1.0
            if spy is not None and date in spy_ma200.index and spy_ma200[date]:
                spy_ratio = float(spy[date] / spy_ma200[date])
            v += [s, spy_ratio]
            rows.append(
                {
                    "bar": master.get_loc(date) + bar_offset,
                    "sym": sym,
                    "date": date,
                    "x": np.array(v, dtype=np.float32),
                    "fwd": float(c.loc[c.index[t + FORWARD]]) / float(c.iloc[t]) - 1.0,
                    "feats": {
                        k: 0.0
                        if f.loc[date][k] != f.loc[date][k]
                        else float(f.loc[date][k])
                        for k in FEAT_COLS
                    },
                    "score": s,
                    "regime_up": regime_up,
                    "close": float(c.iloc[t]),
                    "close_series": c,
                }
            )
    return rows, base


def rows_in_window(rows, lo, hi):
    return [r for r in rows if lo <= r["bar"] < hi]
