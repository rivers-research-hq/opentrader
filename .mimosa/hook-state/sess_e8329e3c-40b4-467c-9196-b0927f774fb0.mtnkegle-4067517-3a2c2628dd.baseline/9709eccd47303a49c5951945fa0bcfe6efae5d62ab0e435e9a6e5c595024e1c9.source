"""Unit tests for the three parallel lane runners (map #174 #179/#180/#181).
Pure signal logic — no venue calls, no file writes.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from exchange.base import OHLCV  # noqa: E402
from strategies.fx_h1rev import rsi2  # noqa: E402
from strategies.fx_h4brk import channel  # noqa: E402
from strategies.fx_d1mom10 import rank_momentum  # noqa: E402


def bars(closes, h=None, l=None):
    out = []
    for i, c in enumerate(closes):
        hi = h[i] if h else c + 0.001
        lo = l[i] if l else c - 0.001
        out.append(OHLCV(timestamp=i, open=c, high=hi, low=lo, close=c, volume=1))
    return out


class TestRsi2(unittest.TestCase):
    def test_pure_downtrend_is_deeply_oversold(self):
        # two consecutive full losses -> avg_loss > 0, avg_gain = 0 -> RSI 0
        self.assertEqual(rsi2([100.0, 99.0, 98.0]), 0.0)

    def test_pure_uptrend_saturated(self):
        self.assertEqual(rsi2([98.0, 99.0, 100.0]), 100.0)

    def test_flat_window_is_no_signal(self):
        self.assertIsNone(rsi2([100.0, 100.0, 100.0]))

    def test_short_series_is_no_signal(self):
        self.assertIsNone(rsi2([100.0, 99.0]))

    def test_mixed_move_stays_out_of_fade_zone(self):
        # one loss then a bigger gain -> RSI well above 10
        self.assertGreater(rsi2([100.0, 99.0, 101.0]), 50.0)


class TestDonchian(unittest.TestCase):
    def test_channel_excludes_signal_bar(self):
        # 22 bars: channel over bars[-21:-1] — the last bar must not set the high
        closes = [100.0] * 21 + [200.0]
        hi = [100.5] * 21 + [200.5]
        lo = [99.5] * 21 + [199.5]
        ch_high, ch_low = channel(bars(closes, hi, lo))
        self.assertEqual(ch_high, 100.5)
        self.assertEqual(ch_low, 99.5)

    def test_close_at_high_is_not_a_breakout(self):
        closes = [100.0] * 21 + [100.0]  # equal to the prior channel high
        hi = [101.0] * 22
        lo = [99.0] * 22
        ch_high, _ = channel(bars(closes, hi, lo))
        self.assertFalse(closes[-1] > ch_high)

    def test_close_above_high_is_a_breakout(self):
        closes = [100.0] * 21 + [101.5]
        hi = [101.0] * 21 + [102.0]
        lo = [99.0] * 22
        ch_high, _ = channel(bars(closes, hi, lo))
        self.assertTrue(closes[-1] > ch_high)

    def test_opposite_channel_breach_exits(self):
        closes = [100.0] * 21 + [98.5]
        hi = [101.0] * 22
        lo = [99.0] * 21 + [98.0]
        _, ch_low = channel(bars(closes, hi, lo))
        self.assertTrue(closes[-1] < ch_low)


class TestRankMomentum(unittest.TestCase):
    def _bars(self, start, end, n=15):
        step = (end - start) / (n - 1)
        return bars([start + i * step for i in range(n)])

    def test_k10_vs_k5_change_the_ranking(self):
        # sym A: strong last 5 days, flat before; sym B: steady climber.
        # Over K=5, A wins; over K=10, B wins — the moved parameter matters.
        a = [100.0] * 10 + [100.0, 102.0, 104.0, 106.0, 108.0]
        b = [100.0 + i * 1.0 for i in range(14)]  # +13 over 14 bars
        bars_by = {"A": bars(a), "B": self._bars(100.0, 113.0, 15)}
        k5 = dict(rank_momentum(bars_by, 5))
        k10 = dict(rank_momentum(bars_by, 10))
        self.assertGreater(k5["A"], k5["B"])
        self.assertGreater(k10["B"], k10["A"])

    def test_short_history_symbol_is_dropped(self):
        bars_by = {"A": self._bars(100.0, 110.0, 15), "B": self._bars(100.0, 105.0, 8)}
        ranked = rank_momentum(bars_by, 10)
        self.assertEqual([s for s, _ in ranked], ["A"])

    def test_negative_momentum_excluded_by_caller_convention(self):
        bars_by = {"C": self._bars(120.0, 100.0, 15)}  # falling
        ranked = rank_momentum(bars_by, 10)
        self.assertLess(ranked[0][1], 0.0)


if __name__ == "__main__":
    unittest.main()
