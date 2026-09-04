"""The portfolio-war referee — CPU-fast, between iterations.

Per research ticket 'Portfolio war referee: what to reuse + speed budget':
reuses setup_search.engine.run_backtest over the pkl OHLCV archives (~0.27 s
for a 2y 16-symbol replay), NOT the harness LLM backtest path. Each policy
(the value-head agent + the field) filters the rule config's executed trades
by its own vote at the trade's entry state; per-policy books emit portfolio
P&L, per-candidate drawdown contribution, per-regime decomposition, and
per-state relabels (advantage-style, per regime window).
"""

import statistics

import numpy as np
import pandas as pd

from setup_search.core import clamp_config
from setup_search.data import REGIME_SYM, load_ohlcv, align
from setup_search.engine import _features, _score_at, run_backtest
from arena.candidates import FEAT_COLS


def _entry_state(sym, entry_date, feat, closes, cfg, spy, spy_ma, macro_ctx=None):
    c = closes[sym]
    f = feat[sym]
    t = c.index.get_loc(entry_date)
    date = c.index[t]
    feats = {
        k: 0.0 if f.loc[date][k] != f.loc[date][k] else float(f.loc[date][k])
        for k in FEAT_COLS
    }
    score = float(_score_at({sym: f.loc[date]}, cfg, {sym: 0.0})[sym])
    regime_up = True
    if spy_ma is not None and date in spy_ma.index:
        regime_up = float(spy[date]) > float(spy_ma[date])
    spy_ratio = 1.0
    spy_ma200 = spy.rolling(200, min_periods=60).mean() if spy is not None else None
    if spy_ma200 is not None and date in spy_ma200.index and spy_ma200[date]:
        spy_ratio = float(spy[date] / spy_ma200[date])
    x = np.array([feats[k] for k in FEAT_COLS] + [score, spy_ratio], dtype=np.float32)
    if macro_ctx is not None:
        # macro expert: append mom_rank/rsi_rank/FF/T10/CPI/VIX/breadth at this
        # bar, in the same order as arena/candidates_macro.collect
        arr = macro_ctx["arrays"][sym]
        if t < len(arr[0]):
            extra = np.array([a[t] for a in arr], dtype=np.float32)
            x = np.concatenate([x, extra])
    return {
        "bar": t,
        "sym": sym,
        "date": date,
        "x": x,
        "feats": feats,
        "score": score,
        "regime_up": regime_up,
        "close": float(c.iloc[t]),
        "close_series": c,
    }


def build_macro_ctx(closes, feat):
    """Precompute per-symbol macro feature arrays (ranks + FRED + VIX +
    breadth), indexed by close-series position, so _entry_state can sample
    the macro expert's extra dims at any trade's entry date in O(1)."""
    from arena.candidates_macro import macro_state
    from setup_search.value_head_1m import breadth_series

    st = macro_state()
    fred, vix = st.get("fred"), st.get("vix")
    if fred is None or vix is None:
        return None
    mom_frame = pd.DataFrame({s: feat[s]["mom"] for s in closes if s != REGIME_SYM})
    rsi_frame = pd.DataFrame({s: feat[s]["rsi"] for s in closes if s != REGIME_SYM})
    mom_rank = mom_frame.rank(axis=1, pct=True)
    rsi_rank = rsi_frame.rank(axis=1, pct=True)
    breadth = breadth_series(closes, window=50)
    keys = ("FF", "T10", "CPI")
    arrays = {}
    for sym, c in closes.items():
        idx = c.index
        cols = [mom_rank[sym].reindex(idx).values,
                rsi_rank[sym].reindex(idx).values]
        for k in keys:
            s = fred.get(k)
            cols.append(s.reindex(idx, method="ffill").values if s is not None else np.full(len(idx), np.nan))
        cols.append(vix.reindex(idx.normalize(), method="ffill").values)
        cols.append(breadth.reindex(idx, method="ffill").values)
        arrays[sym] = [np.nan_to_num(a, nan=0.0) for a in cols]
    return {"arrays": arrays}


def _book_metrics(kept, start_equity=500.0):
    if not kept:
        return {
            "net_return": 0.0,
            "n_trades": 0,
            "win_rate": 0.0,
            "pnl": 0.0,
            "max_dd": 0.0,
            "equity": [start_equity],
        }
    pnls = [t["pnl"] for t in kept]
    eq = [start_equity]
    for p in pnls:
        eq.append(eq[-1] + p)
    peak = start_equity
    max_dd = 0.0
    for v in eq:
        peak = max(peak, v)
        max_dd = max(max_dd, (peak - v) / peak)
    dd_by_sym = {}
    run = start_equity
    for t in kept:
        run += t["pnl"]
        dd_by_sym[t["sym"]] = max(dd_by_sym.get(t["sym"], 0.0), (peak - run) / peak)
    return {
        "net_return": eq[-1] / start_equity - 1.0,
        "n_trades": len(kept),
        "win_rate": sum(1 for t in kept if t["pnl"] > 0) / len(kept),
        "pnl": sum(pnls),
        "max_dd": round(max_dd, 4),
        "dd_by_sym": dd_by_sym,
        "equity": [round(v, 2) for v in eq],
    }


def run_war(
    rows,
    field,
    agent_fn,
    cfg,
    period="2y",
    eta=0.5,
    cfg_override=None,
    bar_lo=0,
    bar_hi=None,
    data=None,
    macro_ctx=None,
    data_source=None,
):
    cfg = clamp_config(cfg)
    if cfg_override:
        cfg = clamp_config({**cfg, **cfg_override})
    if data is None:
        data = (data_source or load_ohlcv)(period)
    al = align(data, [s for s in data if s != REGIME_SYM])
    closes, highs, lows, vols = al
    feat = _features(closes, highs, lows, vols, cfg)
    spy = closes.get(REGIME_SYM)
    spy_ma = None
    if cfg["regime_filter"] and spy is not None:
        spy_ma = spy.rolling(int(cfg["regime_window"]), min_periods=10).mean()

    result = run_backtest(al, cfg)
    trades = result.get("trades", [])
    master = next(iter(closes.values())).index

    policies = [("agent", None)] + [(b.name, b) for b in field]
    books = {}
    for name, bot in policies:
        kept = []
        for t in trades:
            state = _entry_state(
                t["sym"], t["entry_date"], feat, closes, cfg, spy, spy_ma, macro_ctx
            )
            if bar_hi is not None and not (bar_lo <= state["bar"] < bar_hi):
                continue
            if bot is not None:
                take = bot.vote(state)
                value = 0.0
            else:
                take, value = agent_fn(state)
            if not take:
                continue
            t2 = dict(t)
            t2["regime_up"] = state["regime_up"]
            t2["entry_bar"] = state["bar"]
            t2["value"] = value
            kept.append(t2)
        books[name] = _book_metrics(kept)
        books[name]["trades"] = [
            {
                k: t[k]
                for k in (
                    "sym",
                    "pnl",
                    "pnl_pct",
                    "bars",
                    "reason",
                    "regime_up",
                    "value",
                )
            }
            for t in kept
        ]

    field_mean = {}
    base_states = {}
    sel_trades = []
    for t in trades:
        state = _entry_state(t["sym"], t["entry_date"], feat, closes, cfg, spy,
                             spy_ma, macro_ctx)
        if bar_hi is not None and not (bar_lo <= state["bar"] < bar_hi):
            continue
        base_states[(t["sym"], t["entry_date"])] = state
        sel_trades.append(t)
    for reg in ("up", "down"):
        vals = [
            t["pnl_pct"]
            for t in sel_trades
            if (
                "up"
                if base_states[(t["sym"], t["entry_date"])]["regime_up"]
                else "down"
            )
            == reg
        ]
        field_mean[reg] = statistics.mean(vals) if vals else 0.0
    relabels = []
    for t in sel_trades:
        state = base_states[(t["sym"], t["entry_date"])]
        _, value = agent_fn(state)
        reg = "up" if state["regime_up"] else "down"
        r_field = field_mean[reg]
        delta = (t["pnl_pct"] - value) + (t["pnl_pct"] - r_field)
        relabels.append(
            {
                "bar": state["bar"],
                "sym": t["sym"],
                "pnl_pct": t["pnl_pct"],
                "value": value,
                "r_field": r_field,
                "delta": delta,
                "tilde": t["pnl_pct"] + eta * delta,
            }
        )

    regime_decomp = {}
    for name, bot in policies:
        up = [t["pnl_pct"] for t in books[name]["trades"] if t["regime_up"]]
        down = [t["pnl_pct"] for t in books[name]["trades"] if not t["regime_up"]]
        regime_decomp[name] = {
            "up": {"n": len(up), "mean_pnl_pct": statistics.mean(up) if up else 0.0},
            "down": {
                "n": len(down),
                "mean_pnl_pct": statistics.mean(down) if down else 0.0,
            },
        }

    return {
        "books": books,
        "relabels": relabels,
        "regime_decomp": regime_decomp,
        "base_net_return": result["net_return"],
        "base_n_trades": result["n_trades"],
    }


def run_bear_war(
    rows,
    field,
    agent_fn,
    cfg,
    period="5y",
    eta=0.5,
    bar_lo=0,
    bar_hi=250,
    buy_thresh=0.15,
    macro_ctx=None,
    data_source=None,
):
    """Down-regime relabels: war the 2022 bear segment with the regime filter
    off and a looser entry threshold so the rules actually execute there. The
    resulting trades give the value head bear-window (down-regime) signal it
    otherwise never sees (the validated config trades only up-regimes)."""
    override = {"regime_filter": 0, "buy_thresh": buy_thresh}
    out = run_war(
        rows,
        field,
        agent_fn,
        cfg,
        period=period,
        eta=eta,
        cfg_override=override,
        bar_lo=bar_lo,
        bar_hi=bar_hi,
        macro_ctx=macro_ctx,
        data_source=data_source,
    )
    return {
        "relabels": out["relabels"],
        "n_base_trades": out["base_n_trades"],
        "regime_decomp": out["regime_decomp"],
    }


def run_multiverse_war(
    worlds,
    field,
    agent_fn,
    cfg,
    eta=0.5,
    cfg_override=None,
    ruin_net_return=-0.25,
    ruin_max_dd=0.30,
    period="5y",
    macro_ctx=None,
):
    """The tail-robustness gate: run the agent through every generated World and
    flag worlds where it is ruined (portfolio net return below the ruin floor or
    max drawdown above the ruin ceiling).

    The fidelity war (run_war on the real archive) is still the headline gate;
    this is the SECOND gate that catches single-path memorization: a value head
    that profits on the one realized path but blows up in the debt-crisis world
    must not pass. Consumes World objects from scenarios/ — same relabel schema,
    CPU-fast per world (~0.3 s at 2y, ~0.7 s at 5y).
    """
    out = {}
    for i, w in enumerate(worlds):
        try:
            res = run_war(
                None, field, agent_fn, cfg, period=period, eta=eta,
                cfg_override=cfg_override, data=w.data, macro_ctx=macro_ctx,
            )
            book = res["books"].get("agent", {})
        except Exception as e:
            book = {"net_return": 0.0, "max_dd": 0.0, "n_trades": 0, "win_rate": 0.0, "error": str(e)}
        net_return = book.get("net_return", 0.0)
        max_dd = book.get("max_dd", 0.0)
        out[f"world_{i}"] = {
            "spec": w.spec.__dict__,
            "generated_by": w.generated_by,
            "net_return": net_return,
            "max_dd": max_dd,
            "n_trades": book.get("n_trades", 0),
            "win_rate": book.get("win_rate", 0.0),
            "error": book.get("error"),
            "ruined": (net_return <= ruin_net_return) or (max_dd >= ruin_max_dd),
        }
    worlds_out = [out[k] for k in out if k.startswith("world_")]
    out["n_worlds"] = len(worlds_out)
    out["n_ruined"] = sum(1 for r in worlds_out if r["ruined"])
    out["pass"] = out["n_worlds"] > 0 and out["n_ruined"] == 0
    out["mean_net_return"] = float(np.mean([r["net_return"] for r in worlds_out]))
    out["mean_max_dd"] = float(np.mean([r["max_dd"] for r in worlds_out]))
    return out
