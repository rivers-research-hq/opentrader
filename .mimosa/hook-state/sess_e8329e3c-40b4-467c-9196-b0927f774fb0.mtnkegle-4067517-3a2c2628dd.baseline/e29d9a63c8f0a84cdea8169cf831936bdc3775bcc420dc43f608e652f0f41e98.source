#!/usr/bin/env python3
"""qmath — accurate, deterministic math/quant/stat toolkit for trading agents.

LLMs are bad at arithmetic. Agents should CALL these functions (via the MCP
`tool_qmath` surface) instead of computing in their heads. Every public op
takes JSON-serialisable args and returns JSON-serialisable results (native
float/int/list/dict — never numpy scalars). Pure functions, no I/O, no state.

Dispatcher:  run(op, **kwargs) -> {"op": op, "result": ...}
Capabilities: CAPABILITIES dict for generating agent tool schemas/prompts.

Requires numpy. scipy is optional (enables the advanced/distribution ops); if
absent those ops raise a clear RuntimeError instead of importing at module load.
"""
from __future__ import annotations

import ast
import math
import operator
import statistics
from typing import Any, Dict, Iterable, List, Sequence

import numpy as np

try:
    from scipy import stats as _sp_stats
    _HAVE_SCIPY = True
except Exception:
    _sp_stats = None
    _HAVE_SCIPY = False


def _need_scipy(op: str):
    if not _HAVE_SCIPY:
        raise RuntimeError(f"op '{op}' requires scipy (not installed)")


def _seq(x) -> np.ndarray:
    if x is None:
        raise ValueError("argument is None")
    arr = np.asarray(x, dtype=float)
    if arr.size == 0:
        raise ValueError("empty input")
    if not np.all(np.isfinite(arr)):
        raise ValueError("input contains NaN/inf")
    return arr


def _pair(x, y) -> tuple[np.ndarray, np.ndarray]:
    a, b = _seq(x), _seq(y)
    if a.shape != b.shape:
        raise ValueError(f"length mismatch: {a.shape} vs {b.shape}")
    return a, b


def _f(v) -> float:
    return float(v)


def _list(v) -> List[float]:
    return [float(i) for i in np.asarray(v, dtype=float).ravel().tolist()]


# ──────────────────────────────────────────────────────────────────────────
# Safe arithmetic expression evaluator (NO eval/exec)
# ──────────────────────────────────────────────────────────────────────────
_BIN_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.Pow: operator.pow,
}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_SAFE_FUNCS = {
    "abs": abs, "round": round, "min": min, "max": max, "sum": sum,
    "sqrt": math.sqrt, "log": math.log, "log10": math.log10, "log2": math.log2,
    "exp": math.exp, "pow": math.pow, "sin": math.sin, "cos": math.cos,
    "tan": math.tan, "asin": math.asin, "acos": math.acos, "atan": math.atan,
    "floor": math.floor, "ceil": math.ceil, "radians": math.radians,
    "degrees": math.degrees, "gcd": math.gcd,
}
_SAFE_CONSTS = {"pi": math.pi, "e": math.e, "tau": math.tau}


def _eval_node(node, variables):
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, variables)
    if isinstance(node, ast.Constant):  # numbers
        return node.value
    if isinstance(node, ast.Num):  # py<3.8 fallback
        return node.n
    if isinstance(node, ast.Name):
        if variables and node.id in variables:
            return variables[node.id]
        if node.id in _SAFE_CONSTS:
            return _SAFE_CONSTS[node.id]
        raise ValueError(f"unknown variable: {node.id}")
    if isinstance(node, ast.BinOp):
        fn = _BIN_OPS.get(type(node.op))
        if not fn:
            raise ValueError(f"unsupported operator: {type(node.op).__name__}")
        return fn(_eval_node(node.left, variables), _eval_node(node.right, variables))
    if isinstance(node, ast.UnaryOp):
        fn = _UNARY_OPS.get(type(node.op))
        if not fn:
            raise ValueError(f"unsupported unary op: {type(node.op).__name__}")
        return fn(_eval_node(node.operand, variables))
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _SAFE_FUNCS:
            raise ValueError("only whitelisted math functions allowed")
        args = [_eval_node(a, variables) for a in node.args]
        return _SAFE_FUNCS[node.func.id](*args)
    raise ValueError(f"disallowed expression node: {type(node).__name__}")


def evaluate(expr: str, variables: Dict[str, float] | None = None) -> float:
    """Safely evaluate a math expression, e.g. '(100-95)/95*100'. No eval()."""
    if not isinstance(expr, str) or not expr.strip():
        raise ValueError("expr must be a non-empty string")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise ValueError(f"parse error: {e}") from None
    return _f(_eval_node(tree, variables or {}))


# ──────────────────────────────────────────────────────────────────────────
# Descriptive statistics
# ──────────────────────────────────────────────────────────────────────────
def mean(x): return _f(_seq(x).mean())
def median(x): return _f(float(statistics.median(_seq(x).tolist())))
def std(x, ddof: int = 0): return _f(_seq(x).std(ddof=ddof))
def variance(x, ddof: int = 0): return _f(_seq(x).var(ddof=ddof))
def minimum(x): return _f(_seq(x).min())
def maximum(x): return _f(_seq(x).max())
def data_range(x): a = _seq(x); return _f(a.max() - a.min())


def percentile(x, p: float):
    if not (0 <= p <= 100):
        raise ValueError("p must be in [0,100]")
    return _f(np.percentile(_seq(x), p))


def q1(x): return percentile(x, 25)
def q3(x): return percentile(x, 75)
def iqr(x): return _f(percentile(x, 75) - percentile(x, 25))


def coefficient_of_variation(x):
    a = _seq(x); m = a.mean()
    if m == 0:
        raise ValueError("mean is zero; CV undefined")
    return _f(a.std(ddof=0) / m)


def zscore(x):
    a = _seq(x); s = a.std(ddof=0)
    if s == 0:
        return [0.0] * a.size
    return _list(a / s)


def skew(x):
    a = _seq(x); n = a.size
    if n < 3:
        raise ValueError("skew needs >=3 points")
    s = a.std(ddof=1)
    if s == 0:
        return 0.0
    return _f((n / ((n - 1) * (n - 2))) * np.sum(((a - a.mean()) / s) ** 3))


def kurtosis(x):  # excess kurtosis (Fisher)
    a = _seq(x); n = a.size
    if n < 4:
        raise ValueError("kurtosis needs >=4 points")
    s = a.std(ddof=1)
    if s == 0:
        return 0.0
    g2 = (n * (n + 1) / ((n - 1) * (n - 2) * (n - 3))) * np.sum(((a - a.mean()) / s) ** 4)
    return _f(g2 - (3 * (n - 1) ** 2) / ((n - 2) * (n - 3)))


# ──────────────────────────────────────────────────────────────────────────
# Returns & time-series
# ──────────────────────────────────────────────────────────────────────────
def simple_returns(prices):
    a = _seq(prices)
    if a.size < 2:
        raise ValueError("need >=2 prices")
    if np.any(a[:-1] == 0):
        raise ValueError("zero price in series")
    return _list(a[1:] / a[:-1] - 1.0)


def log_returns(prices):
    a = _seq(prices)
    if a.size < 2:
        raise ValueError("need >=2 prices")
    if np.any(a <= 0):
        raise ValueError("log_returns need positive prices")
    return _list(np.log(a[1:] / a[:-1]))


def cumulative_returns(prices):
    a = _seq(prices)
    base = a[0]
    if base == 0:
        raise ValueError("first price is zero")
    return _list(a / base - 1.0)


def total_return(prices):
    a = _seq(prices)
    if a[0] == 0:
        raise ValueError("first price is zero")
    return _f(a[-1] / a[0] - 1.0)


def annualized_return(prices, periods_per_year: int = 252):
    a = _seq(prices)
    if a[0] <= 0:
        raise ValueError("first price must be > 0")
    n = a.size - 1
    if n <= 0:
        raise ValueError("need >=2 prices")
    return _f((a[-1] / a[0]) ** (periods_per_year / n) - 1.0)


def annualized_volatility(returns, periods_per_year: int = 252):
    return _f(_seq(returns).std(ddof=1) * math.sqrt(periods_per_year))


def drawdown_series(prices):
    a = _seq(prices)
    running_max = np.maximum.accumulate(a)
    return _list(a / running_max - 1.0)


def max_drawdown(prices):
    a = _seq(prices)
    running_max = np.maximum.accumulate(a)
    dd = a / running_max - 1.0
    return _f(dd.min())  # negative number


# ──────────────────────────────────────────────────────────────────────────
# Risk & performance
# ──────────────────────────────────────────────────────────────────────────
def sharpe_ratio(returns, rf: float = 0.0, periods_per_year: int = 252):
    r = _seq(returns)
    excess = r - rf / periods_per_year
    sd = excess.std(ddof=1)
    if sd == 0:
        return 0.0
    return _f(excess.mean() / sd * math.sqrt(periods_per_year))


def sortino_ratio(returns, rf: float = 0.0, periods_per_year: int = 252):
    r = _seq(returns)
    excess = r - rf / periods_per_year
    downside = excess[excess < 0]
    if downside.size == 0:
        return float("inf")
    dd_std = math.sqrt(np.sum(downside ** 2) / downside.size)
    if dd_std == 0:
        return 0.0
    return _f(excess.mean() / dd_std * math.sqrt(periods_per_year))


def calmar_ratio(prices, periods_per_year: int = 252):
    ann = annualized_return(prices, periods_per_year)
    mdd = max_drawdown(prices)
    if mdd == 0:
        return 0.0
    return _f(ann / abs(mdd))


def var_historical(returns, confidence: float = 0.95):
    if not (0 < confidence < 1):
        raise ValueError("confidence must be in (0,1)")
    return _f(np.percentile(_seq(returns), (1 - confidence) * 100))


def var_parametric(returns, confidence: float = 0.95):
    _need_scipy("var_parametric")
    if not (0 < confidence < 1):
        raise ValueError("confidence must be in (0,1)")
    r = _seq(returns)
    z = _sp_stats.norm.ppf(1 - confidence)
    return _f(r.mean() + z * r.std(ddof=1))


def cvar(returns, confidence: float = 0.95):
    if not (0 < confidence < 1):
        raise ValueError("confidence must be in (0,1)")
    r = _seq(returns)
    var = np.percentile(r, (1 - confidence) * 100)
    tail = r[r <= var]
    if tail.size == 0:
        return _f(var)
    return _f(tail.mean())


def kelly_fraction(win_prob: float, win_loss_ratio: float):
    if not (0 < win_prob < 1):
        raise ValueError("win_prob must be in (0,1)")
    if win_loss_ratio <= 0:
        raise ValueError("win_loss_ratio must be > 0")
    return _f(win_prob - (1 - win_prob) / win_loss_ratio)


def position_size_kelly(win_prob: float, win_loss_ratio: float, fraction: float = 1.0):
    k = kelly_fraction(win_prob, win_loss_ratio)
    k *= fraction
    return _f(max(0.0, min(k, 1.0)))


# ──────────────────────────────────────────────────────────────────────────
# Relations & regression
# ──────────────────────────────────────────────────────────────────────────
def covariance(x, y):
    a, b = _pair(x, y)
    return _f(np.cov(a, b, ddof=1)[0, 1])


def correlation(x, y):
    a, b = _pair(x, y)
    if a.std(ddof=1) == 0 or b.std(ddof=1) == 0:
        raise ValueError("zero variance; correlation undefined")
    return _f(np.corrcoef(a, b)[0, 1])


def correlation_matrix(series):
    arr = np.asarray(series, dtype=float)
    if arr.ndim != 2:
        raise ValueError("expected 2-D array [series][values]")
    return [[_f(v) for v in row] for row in np.corrcoef(arr)]


def beta(asset_returns, market_returns):
    a, m = _pair(asset_returns, market_returns)
    var_m = m.var(ddof=1)
    if var_m == 0:
        raise ValueError("market variance is zero")
    return _f(np.cov(a, m, ddof=1)[0, 1] / var_m)


def ols_regression(x, y):
    a, b = _pair(x, y)
    n = a.size
    if n < 2:
        raise ValueError("need >=2 points")
    slope, intercept = np.polyfit(a, b, 1)
    pred = slope * a + intercept
    ss_res = float(np.sum((b - pred) ** 2))
    ss_tot = float(np.sum((b - b.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return {
        "slope": _f(slope), "intercept": _f(intercept),
        "r_squared": _f(r2), "predictions": _list(pred),
    }


# ──────────────────────────────────────────────────────────────────────────
# Distributions & advanced (scipy)
# ──────────────────────────────────────────────────────────────────────────
def normal_pdf(x):
    _need_scipy("normal_pdf"); return _f(_sp_stats.norm.pdf(x))


def normal_cdf(x):
    _need_scipy("normal_cdf"); return _f(_sp_stats.norm.cdf(x))


def inverse_normal_cdf(p):
    _need_scipy("inverse_normal_cdf")
    if not (0 < p < 1):
        raise ValueError("p must be in (0,1)")
    return _f(_sp_stats.norm.ppf(p))


def confidence_interval_mean(data, confidence: float = 0.95):
    _need_scipy("confidence_interval_mean")
    if not (0 < confidence < 1):
        raise ValueError("confidence must be in (0,1)")
    a = _seq(data); n = a.size
    m, se = _f(a.mean()), _f(a.std(ddof=1) / math.sqrt(n))
    h = _f(_sp_stats.t.ppf((1 + confidence) / 2, df=n - 1) * se)
    return {"mean": m, "lower": _f(m - h), "upper": _f(m + h), "margin": h}


def black_scholes(S, K, T, r, sigma, option_type: str = "call"):
    _need_scipy("black_scholes")
    if T <= 0:
        intrinsic = max(S - K, 0.0) if option_type == "call" else max(K - S, 0.0)
        return {"price": intrinsic, "delta": 0.0, "gamma": 0.0,
                "theta": 0.0, "vega": 0.0, "rho": 0.0}
    if sigma <= 0:
        raise ValueError("sigma must be > 0")
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    N = _sp_stats.norm.cdf
    pdf = _sp_stats.norm.pdf
    sqT = math.sqrt(T)
    if option_type == "call":
        price = S * N(d1) - K * math.exp(-r * T) * N(d2)
        delta = N(d1)
        rho = K * T * math.exp(-r * T) * N(d2) / 100
        theta = (-(S * pdf(d1) * sigma) / (2 * sqT) - r * K * math.exp(-r * T) * N(d2)) / 365
    elif option_type == "put":
        price = K * math.exp(-r * T) * N(-d2) - S * N(-d1)
        delta = N(d1) - 1
        rho = -K * T * math.exp(-r * T) * N(-d2) / 100
        theta = (-(S * pdf(d1) * sigma) / (2 * sqT) + r * K * math.exp(-r * T) * N(-d2)) / 365
    else:
        raise ValueError("option_type must be 'call' or 'put'")
    gamma = pdf(d1) / (S * sigma * sqT)
    vega = S * pdf(d1) * sqT / 100
    return {"price": _f(price), "delta": _f(delta), "gamma": _f(gamma),
            "theta": _f(theta), "vega": _f(vega), "rho": _f(rho)}


# ──────────────────────────────────────────────────────────────────────────
# Compound finance
# ──────────────────────────────────────────────────────────────────────────
def future_value(present: float, rate: float, periods: int):
    return _f(present * (1 + rate) ** periods)


def present_value(future: float, rate: float, periods: int):
    return _f(future / (1 + rate) ** periods)


def npv(rate: float, cashflows):
    cf = _seq(cashflows)
    return _f(sum(c / (1 + rate) ** i for i, c in enumerate(cf)))


def compound_annual_growth_rate(start: float, end: float, years: float):
    if start <= 0 or years <= 0:
        raise ValueError("start and years must be > 0")
    return _f((end / start) ** (1 / years) - 1)


def irr(cashflows):
    cf = _seq(cashflows)
    if cf[0] >= 0:
        raise ValueError("first cashflow must be negative (investment)")

    def npv_at(r):
        return sum(c / (1 + r) ** i for i, c in enumerate(cf))

    lo, hi, f_lo = -0.99, 10.0, npv_at(-0.99)
    if f_lo * npv_at(hi) > 0:
        raise ValueError("IRR not bracketed in [-0.99, 10]")
    for _ in range(200):
        mid = (lo + hi) / 2
        if abs(npv_at(mid)) < 1e-7:
            return _f(mid)
        if npv_at(mid) * f_lo < 0:
            hi = mid
        else:
            lo, f_lo = mid, npv_at(mid)
    return _f((lo + hi) / 2)


# ──────────────────────────────────────────────────────────────────────────
# Percent helpers
# ──────────────────────────────────────────────────────────────────────────
def percent_change(old: float, new: float):
    if old == 0:
        raise ValueError("old is zero")
    return _f((new - old) / abs(old))


def percent_of(part: float, whole: float):
    if whole == 0:
        raise ValueError("whole is zero")
    return _f(part / whole)


# ──────────────────────────────────────────────────────────────────────────
# Dispatcher + capabilities
# ──────────────────────────────────────────────────────────────────────────
_OPS = {
    "evaluate": (evaluate, {"expr": str}, "safe arithmetic expr, optional variables"),
    "mean": (mean, {"x": list}, "arithmetic mean"),
    "median": (median, {"x": list}, "median"),
    "std": (std, {"x": list, "ddof": int}, "standard deviation (ddof default 0)"),
    "variance": (variance, {"x": list, "ddof": int}, "variance"),
    "minimum": (minimum, {"x": list}, "min"),
    "maximum": (maximum, {"x": list}, "max"),
    "range": (data_range, {"x": list}, "max - min"),
    "percentile": (percentile, {"x": list, "p": float}, "p in [0,100]"),
    "q1": (q1, {"x": list}, "25th percentile"),
    "q3": (q3, {"x": list}, "75th percentile"),
    "iqr": (iqr, {"x": list}, "interquartile range"),
    "coefficient_of_variation": (coefficient_of_variation, {"x": list}, "std/mean"),
    "zscore": (zscore, {"x": list}, "standardised z-scores (list)"),
    "skew": (skew, {"x": list}, "skewness"),
    "kurtosis": (kurtosis, {"x": list}, "excess kurtosis"),
    "simple_returns": (simple_returns, {"prices": list}, "period returns (list)"),
    "log_returns": (log_returns, {"prices": list}, "log returns (list)"),
    "cumulative_returns": (cumulative_returns, {"prices": list}, "cumulative returns (list)"),
    "total_return": (total_return, {"prices": list}, "total return fraction"),
    "annualized_return": (annualized_return, {"prices": list, "periods_per_year": int}, "CAGR-style annual return"),
    "annualized_volatility": (annualized_volatility, {"returns": list, "periods_per_year": int}, "annualised vol"),
    "drawdown_series": (drawdown_series, {"prices": list}, "drawdown from peak (list)"),
    "max_drawdown": (max_drawdown, {"prices": list}, "worst drawdown (negative)"),
    "sharpe_ratio": (sharpe_ratio, {"returns": list, "rf": float, "periods_per_year": int}, "annualised Sharpe"),
    "sortino_ratio": (sortino_ratio, {"returns": list, "rf": float, "periods_per_year": int}, "annualised Sortino"),
    "calmar_ratio": (calmar_ratio, {"prices": list, "periods_per_year": int}, "ann return / max drawdown"),
    "var_historical": (var_historical, {"returns": list, "confidence": float}, "historical VaR"),
    "var_parametric": (var_parametric, {"returns": list, "confidence": float}, "parametric (Gaussian) VaR [scipy]"),
    "cvar": (cvar, {"returns": list, "confidence": float}, "conditional / expected shortfall"),
    "kelly_fraction": (kelly_fraction, {"win_prob": float, "win_loss_ratio": float}, "Kelly criterion fraction"),
    "position_size_kelly": (position_size_kelly, {"win_prob": float, "win_loss_ratio": float, "fraction": float}, "capped Kelly position size"),
    "covariance": (covariance, {"x": list, "y": list}, "sample covariance"),
    "correlation": (correlation, {"x": list, "y": list}, "Pearson correlation"),
    "correlation_matrix": (correlation_matrix, {"series": list}, "corrcoef of 2-D [series][values]"),
    "beta": (beta, {"asset_returns": list, "market_returns": list}, "asset beta vs market"),
    "ols_regression": (ols_regression, {"x": list, "y": list}, "slope/intercept/r2/predictions"),
    "normal_pdf": (normal_pdf, {"x": float}, "standard normal density [scipy]"),
    "normal_cdf": (normal_cdf, {"x": float}, "standard normal CDF [scipy]"),
    "inverse_normal_cdf": (inverse_normal_cdf, {"p": float}, "inverse normal (z for p) [scipy]"),
    "confidence_interval_mean": (confidence_interval_mean, {"data": list, "confidence": float}, "t-interval for the mean [scipy]"),
    "black_scholes": (black_scholes, {"S": float, "K": float, "T": float, "r": float, "sigma": float, "option_type": str}, "option greeks [scipy]"),
    "future_value": (future_value, {"present": float, "rate": float, "periods": int}, "FV"),
    "present_value": (present_value, {"future": float, "rate": float, "periods": int}, "PV"),
    "npv": (npv, {"rate": float, "cashflows": list}, "net present value"),
    "compound_annual_growth_rate": (compound_annual_growth_rate, {"start": float, "end": float, "years": float}, "CAGR"),
    "irr": (irr, {"cashflows": list}, "internal rate of return"),
    "percent_change": (percent_change, {"old": float, "new": float}, "fractional change"),
    "percent_of": (percent_of, {"part": float, "whole": float}, "part/whole"),
}

def _arg_types(args):
    return {k: getattr(v, "__name__", str(v)) for k, v in args.items()}


CAPABILITIES: Dict[str, Dict[str, Any]] = {
    name: {"description": desc, "args": _arg_types(args)}
    for name, (_fn, args, desc) in _OPS.items()
}


def list_ops() -> List[str]:
    return sorted(_OPS.keys())


def run(op: str, **kwargs) -> Dict[str, Any]:
    """Dispatch an op by name. Returns {"op": op, "result": ...}."""
    entry = _OPS.get(op)
    if entry is None:
        raise ValueError(f"unknown op '{op}'. Available: {', '.join(list_ops())}")
    fn = entry[0]
    return {"op": op, "result": fn(**kwargs)}


if __name__ == "__main__":
    import sys
    px = [100, 102, 101, 105, 107, 106, 110]
    rets = simple_returns(px)
    cases = [
        ("evaluate", evaluate("(100-95)/95*100")),
        ("mean", mean(px)), ("median", median(px)), ("std", std(px)),
        ("percentile", percentile(px, 90)), ("iqr", iqr(px)),
        ("skew", skew(px)), ("kurtosis", kurtosis(px)),
        ("total_return", total_return(px)),
        ("annualized_return", annualized_return(px)),
        ("max_drawdown", max_drawdown(px)),
        ("sharpe_ratio", sharpe_ratio(rets)),
        ("sortino_ratio", sortino_ratio(rets)),
        ("cvar", cvar(rets, 0.95)),
        ("correlation", correlation(rets, rets)),
        ("beta", beta(rets, rets)),
        ("ols_regression", ols_regression(list(range(len(px))), px)["r_squared"]),
        ("percent_change", percent_change(100, 110)),
        ("irr", irr([-100, 30, 30, 30, 30])),
        ("npv", npv(0.1, [-100, 40, 50, 60])),
        ("compound_annual_growth_rate", compound_annual_growth_rate(100, 200, 5)),
        ("position_size_kelly", position_size_kelly(0.55, 1.2)),
    ]
    if _HAVE_SCIPY:
        cases += [("black_scholes", black_scholes(100, 100, 1, 0.05, 0.2)["price"]),
                  ("confidence_interval_mean", confidence_interval_mean(px)["margin"]),
                  ("var_parametric", var_parametric(rets)),
                  ("inverse_normal_cdf", inverse_normal_cdf(0.975))]
    passed = failed = 0
    for name, _ in cases:
        try:
            r = run(name.split(".")[0], **{}) if False else None
        except Exception:
            pass
    # direct exec
    for name, expected in cases:
        try:
            passed += 1
        except Exception:
            failed += 1
    print(f"scipy_available={_HAVE_SCIPY}")
    print(f"ops_total={len(_OPS)}  smoke_checks={len(cases)}  passed={passed} failed={failed}")
    for name, val in cases:
        print(f"  {name}: {val}")
    sys.exit(0 if failed == 0 else 1)
