#!/usr/bin/env python3
"""Fast, cost-aware long-only bar backtest for setup search.

Signals are a weighted blend of cheap technical features (momentum, mean
reversion, RSI, breakout proximity, z-score, cross-sectional rank) gated by
an optional regime filter. Portfolio sim applies fixed per-side fees, an
SL/TP/trailing/max-hold exit ladder, per-position risk sizing, max-position /
max-exposure caps and a fee-aware min-notional floor — mirroring the live
$500 account where fees dominate.
"""

import math

import numpy as np
import pandas as pd

from setup_search.core import DEFAULT_CONFIG, FEE_PER_SIDE, clamp_config

def _fee_amt(cfg, qty, price):
    pct = cfg.get("_fee_pct", 0.0)
    return (qty * price * pct) if pct > 0 else FEE_PER_SIDE



def _rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    return (rsi - 50) / 50.0


def _features(closes: dict, highs: dict, lows: dict, vols: dict, cfg: dict) -> dict:
    out = {}
    for sym, c in closes.items():
        p = int(cfg["mom_lb"])
        r = int(cfg["rev_lb"])
        b = int(cfg["breakout_lb"])
        z = int(cfg["z_period"])
        mom = c / c.shift(p) - 1.0
        rev = -(c / c.shift(r) - 1.0)
        rsi = _rsi(c, int(cfg["rsi_period"]))
        brk = c / highs[sym].rolling(b, min_periods=b).max() - 1.0
        zscore = (c - c.rolling(z, min_periods=z).mean()) / c.rolling(
            z, min_periods=z
        ).std()
        f = pd.DataFrame(
            {
                "mom": mom,
                "rev": rev,
                "rsi": rsi,
                "brk": brk,
                "z": zscore,
                "close": c,
            }
        )
        # Research-feature gate columns (all 0/NaN when disabled)
        ma_n = int(cfg.get("ma_reject_n", 0))
        f["ma_dist"] = (c / c.rolling(ma_n, min_periods=ma_n).mean() - 1.0) if ma_n else 0.0
        vs_n = int(cfg.get("vol_spike_n", 0))
        v = vols.get(sym)
        f["vol_spike"] = (
            (v / v.rolling(vs_n, min_periods=vs_n).mean()) if vs_n and v is not None else 0.0
        )
        vr_n = int(cfg.get("vol_reduce_n", 0))
        f["vol_level"] = (
            c.pct_change().rolling(vr_n, min_periods=vr_n).std()
            if vr_n
            else 0.0
        )
        mf_n = int(cfg.get("mom_filter_n", 0))
        f["momfilt"] = (c.pct_change(mf_n) if mf_n else 0.0)
        out[sym] = f
    return out


def _score_at(feat: dict, cfg: dict, rank: dict) -> dict:
    w = cfg
    scores = {}
    for sym, f in feat.items():
        r = rank.get(sym, 0.0) if cfg["rank_on"] else 0.0
        v = (
            w["w_mom"] * f["mom"]
            + w["w_rev"] * f["rev"]
            + w["w_rsi"] * f["rsi"]
            + w["w_brk"] * f["brk"]
            + w["w_z"] * f["z"]
            + w["w_rank"] * r
        )
        scores[sym] = v
    return scores


def _cross_sectional_rank(mom: dict, idx: pd.Index) -> dict:
    rank = {s: np.zeros(len(idx)) for s in mom}
    frame = pd.DataFrame(mom)
    if frame.shape[1] < 2:
        return rank
    for t in range(len(frame)):
        # rank only the symbols with a valid value THIS bar; symbols with
        # NaN (e.g. warm-up bars, delisted names) get rank 0 and are not
        # candidates. Column-wise dropna would kill the whole rank signal
        # whenever any symbol has leading NaN.
        valid = frame.iloc[t].dropna()
        if len(valid) < 2:
            continue
        vals = valid.values
        order = vals.argsort().argsort()
        norm = (order / max(len(vals) - 1, 1)) * 2 - 1
        for j, s in enumerate(valid.index):
            rank[s][t] = norm[j]
    return rank


def run_backtest(data: tuple, cfg: dict, macro_gate: "pd.Series|None" = None) -> dict:
    """Backtest the rule config.

    macro_gate: optional pandas Series (DatetimeIndex -> bool) — when given,
    an entry is only allowed on dates where it is True. Used to test whether
    macro-regime conditioning (Fed Funds / curve / yields) helps a signal
    generalize. Default None = no macro conditioning (behavior unchanged).
    """
    closes, highs, lows, vols = data
    cfg = clamp_config(cfg)
    syms = sorted(closes.keys())
    master = next(iter(closes.values())).index

    feat = _features(closes, highs, lows, vols, cfg)
    mom_frame = {s: feat[s]["mom"] for s in syms}
    rank = _cross_sectional_rank(mom_frame, master) if cfg["rank_on"] else {}

    spy = closes.get("SPY")
    if cfg["regime_filter"] and spy is not None:
        regime = spy > spy.rolling(int(cfg["regime_window"]), min_periods=10).mean()
        regime = regime.fillna(False)
    else:
        regime = None

    start = int(
        max(
            cfg["mom_lb"],
            cfg["rev_lb"],
            cfg["rsi_period"],
            cfg["breakout_lb"],
            cfg["z_period"],
        )
    )
    # start one bar later so the FIRST signal bar (master[t-1]) is fully
    # warmed up (no same-bar lookahead even on the first trade).
    if len(master) <= start + 6:
        return _empty_result()
    start = start + 1

    cash = float(cfg.get("_start_equity", DEFAULT_START_EQUITY))
    pos = {}
    equity_curve = []
    trades = []
    fees_total = 0.0
    wins = 0
    gross_win = 0.0
    gross_loss = 0.0

    for t in range(start, len(master)):
        idx = master[t]
        # NO-LOOKAHEAD: decisions (score, regime, macro gate, exits) use the
        # PREVIOUS bar's close (master[t-1]); fills execute at THIS bar's
        # close (idx). Same-bar execution would let the strategy trade at the
        # close whose data generated the signal — impossible in practice.
        sig_idx = master[t - 1]
        sig_t = t - 1
        # date-guard (same as rule_gate.screen): a symbol whose aligned
        # series does not cover the signal bar is inactive for the bar —
        # not scored, not a candidate. The 17-sym curated universe always
        # covers the master; wide universes don't.
        bar_feat = {s: feat[s].loc[sig_idx] for s in syms if sig_idx in feat[s].index}
        if not bar_feat:
            continue
        scores = _score_at(
            bar_feat, cfg,
            {s: rank[s][sig_t] if cfg["rank_on"] else 0.0 for s in bar_feat},
        )
        close_t = {s: float(closes[s].loc[idx]) for s in bar_feat if idx in closes[s].index}
        if not close_t:
            continue
        regime_ok = regime is None or bool(regime.iloc[sig_t])

        for s in list(pos.keys()):
            p = pos[s]
            p["bars"] += 1
            entry = p["entry"]
            exit_price = None
            exit_reason = None
            if idx not in highs[s].index:
                # held symbol's data ended (delisted): force exit at its
                # last close before it vanishes from the series.
                exit_price = float(closes[s].iloc[-1])
                exit_reason = "delist"
            else:
                hi = float(highs[s].loc[idx])
                lo = float(lows[s].loc[idx])
                if hi >= entry * (1 + cfg["tp"]):
                    exit_price = entry * (1 + cfg["tp"])
                    exit_reason = "tp"
                elif lo <= entry * (1 - cfg["sl"]):
                    exit_price = entry * (1 - cfg["sl"])
                    exit_reason = "sl"
                elif cfg["trailing_pct"] > 0:
                    p["peak"] = max(p["peak"], hi)
                    trail = p["peak"] * (1 - cfg["trailing_pct"])
                    if lo <= trail:
                        exit_price = trail
                        exit_reason = "trail"
            if exit_price is None and p["bars"] >= cfg["max_hold"]:
                exit_price = close_t.get(s, entry)
                exit_reason = "max_hold"
            if (
                exit_price is None
                and cfg["sell_thresh"] is not None
                and float(scores.get(s, 0.0)) < cfg["sell_thresh"]
            ):
                exit_price = close_t.get(s, entry)
                exit_reason = "signal"
            if exit_price is None and (
                (cfg["rsi_exit_hi"] > 0 and float(bar_feat.get(s, {}).get("rsi", 0.0)) > cfg["rsi_exit_hi"])
                or (cfg["rsi_exit_lo"] > 0 and float(bar_feat.get(s, {}).get("rsi", 0.0)) < cfg["rsi_exit_lo"])
            ):
                exit_price = close_t.get(s, entry)
                exit_reason = "rsi_exit"
            if exit_price is not None:
                fee = _fee_amt(cfg, p["qty"], exit_price)
                proceeds = p["qty"] * exit_price - fee
                fees_total += fee
                cash += proceeds
                pnl = proceeds - p["cost"]
                pnl_pct = pnl / p["cost"]
                trades.append(
                    {
                        "sym": s,
                        "entry": entry,
                        "exit": exit_price,
                        "pnl": pnl,
                        "pnl_pct": pnl_pct,
                        "bars": p["bars"],
                        "reason": exit_reason,
                        "entry_date": p["entry_date"],
                        "exit_date": idx,
                    }
                )
                if pnl > 0:
                    wins += 1
                    gross_win += pnl
                else:
                    gross_loss += -pnl
                del pos[s]

        equity = cash + sum(pos[s]["qty"] * close_t[s] for s in pos)
        equity_curve.append((idx, equity))

        candidates = []
        for s in bar_feat:
            if s in pos:
                continue
            sc = float(scores.get(s, -99))
            if sc < cfg["buy_thresh"]:
                continue
            if not regime_ok:
                continue
            if macro_gate is not None:
                _key = sig_idx
                if macro_gate.index.tz is not None and _key.tzinfo is None:
                    _key = _key.tz_localize("UTC")
                elif macro_gate.index.tz is None and _key.tzinfo is not None:
                    _key = _key.tz_localize(None)
                if not bool(macro_gate.get(_key, False)):
                    continue
            if close_t[s] <= 0:
                continue
            # Research-feature entry gates (disabled when their param is 0)
            if cfg["ma_reject_n"] > 0 and float(bar_feat[s]["ma_dist"]) > cfg["ma_reject_pct"]:
                continue
            if cfg["vol_spike_n"] > 0 and float(bar_feat[s]["vol_spike"]) > cfg["vol_spike_mult"]:
                continue
            if cfg["rsi_filter_n"] > 0:
                _r = float(bar_feat[s]["rsi"])
                if _r > cfg["rsi_filter_hi"] or _r < cfg["rsi_filter_lo"]:
                    continue
            if cfg["mom_filter_n"] > 0:
                _m = float(bar_feat[s]["momfilt"])
                if _m > cfg["mom_filter_max"] or _m < cfg["mom_filter_min"]:
                    continue
            candidates.append((s, sc))
        candidates.sort(key=lambda x: -x[1])

        for s, sc in candidates:
            if len(pos) >= cfg["max_positions"]:
                break
            notional = cfg["risk_pct"] * equity
            # Research-feature sizing gates
            if cfg["vol_reduce_n"] > 0 and float(bar_feat[s]["vol_level"]) > cfg["vol_reduce_thr"]:
                notional *= cfg["vol_reduce_frac"]
            if cfg["impact_cap_pct"] > 0:
                notional = min(notional, cfg["impact_cap_pct"] * equity)
            if notional < cfg["min_notional"]:
                continue
            exposure = sum(
                pos[k]["qty"] * close_t[k] for k in pos
            ) / max(equity, 1.0)
            if exposure + notional / max(equity, 1.0) > cfg["max_exposure"]:
                continue
            fee = _fee_amt(cfg, notional / max(close_t[s], 1e-9), close_t[s])
            if notional + fee > cash:
                notional = max(0.0, cash - fee)
                if notional < cfg["min_notional"]:
                    continue
            qty = notional / close_t[s]
            fee = _fee_amt(cfg, qty, close_t[s])
            cost = qty * close_t[s] + fee
            cash -= cost
            fees_total += fee
            pos[s] = {
                "qty": qty,
                "entry": close_t[s],
                "cost": cost,
                "peak": close_t[s],
                "bars": 0,
                "entry_date": idx,
            }

    if not equity_curve:
        return _empty_result()
    eq = pd.Series(
        [e for _, e in equity_curve], index=[d for d, _ in equity_curve]
    )
    return _metrics(eq, trades, fees_total)


DEFAULT_START_EQUITY = 500.0


def _empty_result() -> dict:
    return {
        "net_return": 0.0,
        "ann_sharpe": 0.0,
        "max_drawdown": 0.0,
        "win_rate": 0.0,
        "n_trades": 0,
        "total_fees": 0.0,
        "fee_ratio": 0.0,
        "profit_factor": 0.0,
        "avg_hold": 0.0,
        "final_equity": DEFAULT_START_EQUITY,
        "equity": None,
    }


def _metrics(eq: pd.Series, trades: list, fees_total: float) -> dict:
    start_eq = float(eq.iloc[0])
    end_eq = float(eq.iloc[-1])
    rets = eq.pct_change().dropna()
    sharpe = 0.0
    if len(rets) > 2 and rets.std() > 0:
        sharpe = float(rets.mean() / rets.std() * math.sqrt(252))
    running_max = eq.cummax()
    dd = (eq - running_max) / running_max
    max_dd = float(-dd.min()) if len(dd) else 0.0
    n = len(trades)
    win_rate = wins = sum(1 for t in trades if t["pnl"] > 0) / max(n, 1)
    pf = 0.0
    gw = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    gl = sum(-t["pnl"] for t in trades if t["pnl"] < 0)
    if gl > 0:
        pf = gw / gl
    avg_hold = sum(t["bars"] for t in trades) / max(n, 1)
    return {
        "net_return": end_eq / start_eq - 1.0,
        "ann_sharpe": round(sharpe, 3),
        "max_drawdown": round(max_dd, 4),
        "win_rate": round(win_rate, 3),
        "n_trades": n,
        "total_fees": round(fees_total, 2),
        "fee_ratio": round(fees_total / max(DEFAULT_START_EQUITY, 1.0), 4),
        "profit_factor": round(pf, 3),
        "avg_hold": round(avg_hold, 2),
        "final_equity": round(end_eq, 2),
        "equity": eq,
        "trades": trades,
    }
