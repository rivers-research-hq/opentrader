#!/usr/bin/env python3
"""Chart Renderer — generate price charts for the dashboard.

Uses matplotlib with non-interactive Agg backend.
"""
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import FancyBboxPatch

logger = logging.getLogger("opentrader.charts")


def _to_dates(bars: List) -> List:
    """Convert bar timestamps to matplotlib datetimes."""
    import datetime as dt
    dates = []
    for b in bars:
        ts = getattr(b, "timestamp", None)
        if ts is None and isinstance(b, dict):
            ts = b.get("timestamp", 0)
        if ts:
            dates.append(dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc))
        else:
            dates.append(dt.datetime.now(dt.timezone.utc))
    return dates


def render_candlestick(bars: List, symbol: str = "BTC/USDT",
                       output_dir: str = None,
                       title: str = None) -> str:
    """Render a candlestick chart. Returns file path."""
    import datetime as dt

    output_dir = output_dir or "/tmp/opentrader_charts"
    os.makedirs(output_dir, exist_ok=True)

    closes = [getattr(b, "close", b.get("close", 0)) for b in bars]
    opens = [getattr(b, "open", b.get("open", 0)) for b in bars]
    highs = [getattr(b, "high", b.get("high", 0)) for b in bars]
    lows = [getattr(b, "low", b.get("low", 0)) for b in bars]
    volumes = [getattr(b, "volume", b.get("volume", 0)) for b in bars]
    dates = _to_dates(bars)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8),
                                   gridspec_kw={"height_ratios": [3, 1]},
                                   sharex=True)

    # Candlesticks
    for i in range(len(bars)):
        color = "green" if closes[i] >= opens[i] else "red"
        ax1.plot([dates[i], dates[i]], [lows[i], highs[i]], color=color, linewidth=1)
        ax1.plot([dates[i], dates[i]], [opens[i], closes[i]], color=color, linewidth=4 if closes[i] >= opens[i] else 4)

    # Moving averages
    if len(closes) > 9:
        ma5 = _sma(closes, 5)
        ma20 = _sma(closes, 20)
        ax1.plot(dates[-len(ma5):], ma5, label="MA5", color="blue", alpha=0.7, linewidth=1.5)
        ax1.plot(dates[-len(ma20):], ma20, label="MA20", color="orange", alpha=0.7, linewidth=1.5)

    ax1.set_title(title or f"{symbol} — Price Chart", fontsize=14, fontweight="bold")
    ax1.set_ylabel("Price ($)")
    ax1.legend(loc="best")
    ax1.grid(True, alpha=0.3)

    # Volume
    vol_colors = ["green" if closes[i] >= opens[i] else "red" for i in range(len(bars))]
    ax2.bar(dates, volumes, color=vol_colors, alpha=0.6, width=0.8)
    ax2.set_ylabel("Volume")
    ax2.set_xlabel("Date")
    ax2.grid(True, alpha=0.3)

    # Format x-axis dates
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d %H:%M"))
    plt.xticks(rotation=45)

    plt.tight_layout()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(output_dir, f"{symbol.replace('/', '_')}_{ts}.png")
    plt.savefig(path, dpi=100, bbox_inches="tight")
    plt.close(fig)
    logger.info(f"Chart saved: {path}")
    return path


def render_dashboard(equity_curve: List[float], drawdowns: List[float],
                     bars: List, output_dir: str = None) -> str:
    """Render a trading dashboard with equity curve and drawdown."""
    output_dir = output_dir or "/tmp/opentrader_charts"
    os.makedirs(output_dir, exist_ok=True)

    fig, axes = plt.subplots(3, 1, figsize=(12, 10),
                             gridspec_kw={"height_ratios": [2, 1, 1]})

    # Equity curve
    if equity_curve:
        axes[0].plot(equity_curve, color="blue", linewidth=2)
        axes[0].fill_between(range(len(equity_curve)), equity_curve, alpha=0.1)
        axes[0].set_title("Portfolio Equity Curve", fontsize=13, fontweight="bold")
        axes[0].set_ylabel("Portfolio Value ($)")
        axes[0].grid(True, alpha=0.3)
        if equity_curve:
            axes[0].axhline(y=equity_curve[0], color="gray", linestyle="--", alpha=0.5)

    # Drawdown
    if drawdowns:
        axes[1].fill_between(range(len(drawdowns)), 0, [d * 100 for d in drawdowns],
                              color="red", alpha=0.3)
        axes[1].plot([d * 100 for d in drawdowns], color="red", linewidth=1)
        axes[1].set_title("Drawdown (%)", fontsize=13, fontweight="bold")
        axes[1].set_ylabel("Drawdown %")
        axes[1].grid(True, alpha=0.3)

    # Price
    closes = [getattr(b, "close", b.get("close", 0)) for b in bars[-100:]]
    if closes:
        axes[2].plot(closes, color="black", linewidth=1.5)
        axes[2].set_title("Recent Price", fontsize=13, fontweight="bold")
        axes[2].set_ylabel("Price ($)")
        axes[2].set_xlabel("Bar")
        axes[2].grid(True, alpha=0.3)

    plt.tight_layout()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(output_dir, f"dashboard_{ts}.png")
    plt.savefig(path, dpi=100, bbox_inches="tight")
    plt.close(fig)
    logger.info(f"Dashboard saved: {path}")
    return path


def _sma(data: List[float], window: int) -> List[float]:
    """Simple moving average."""
    if len(data) < window:
        return data
    result = []
    for i in range(window - 1, len(data)):
        result.append(sum(data[i - window + 1:i + 1]) / window)
    return result
