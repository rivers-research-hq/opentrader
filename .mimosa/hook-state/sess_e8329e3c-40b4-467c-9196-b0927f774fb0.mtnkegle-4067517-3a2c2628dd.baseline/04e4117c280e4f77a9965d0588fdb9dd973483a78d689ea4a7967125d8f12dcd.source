"""Unit tests for OANDA price-precision formatting (map #158, ticket #168).

Regression for TAKE_PROFIT_ON_FILL_PRICE_PRECISION_EXCEEDED: the adapter
hard-formatted SL/TP as :.5f — a 5-decimal string on a 3-decimal JPY pair is
an invalid price and the venue rejects the WHOLE order (txns 158/159/160,
2026-09-02/03). No venue calls here: _request is mocked.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from exchange.oanda import OandaExchange


def make_ex():
    ex = OandaExchange()
    captured = {}

    def fake_request(method, path, body=None):
        captured["method"], captured["path"], captured["body"] = method, path, body
        return {
            "orderFillTransaction": {"orderID": "999", "price": "158.500"},
            "lastTransactionID": "1000",
        }

    ex._request = fake_request
    return ex, captured


class TestPriceDigits(unittest.TestCase):
    def test_heuristic_without_connect(self):
        ex = OandaExchange()
        self.assertEqual(ex._price_digits("USD_JPY"), 3)
        self.assertEqual(ex._price_digits("GBP_JPY"), 3)
        self.assertEqual(ex._price_digits("EUR_USD"), 5)
        self.assertEqual(ex._price_digits("GBP_USD"), 5)
        self.assertEqual(ex._price_digits("USD_CAD"), 5)

    def test_venue_metadata_wins(self):
        ex = OandaExchange()
        ex._precision = {"USD_JPY": 3, "EUR_USD": 5}
        self.assertEqual(ex._price_digits("USD_JPY"), 3)
        self.assertEqual(ex._price_digits("EUR_USD"), 5)


class TestFmtPrice(unittest.TestCase):
    def test_historical_rejects_now_format_to_grid(self):
        ex = OandaExchange()
        # the three rejected h1-mom USD_JPY orders (txns 158/159/160)
        self.assertEqual(ex._fmt_price("USD_JPY", 159.12433333333334), "159.124")
        self.assertEqual(ex._fmt_price("USD_JPY", 158.43544444444447), "158.435")
        self.assertEqual(ex._fmt_price("USD_JPY", 159.3178333333333), "159.318")
        # the accepted GBP_USD 10-dp float truncates to a valid 5dp price
        self.assertEqual(ex._fmt_price("GBP_USD", 1.3509216666666666), "1.35092")
        self.assertEqual(ex._fmt_price("GBP_USD", 1.34887), "1.34887")

    def test_half_up_rounding(self):
        ex = OandaExchange()
        self.assertEqual(ex._fmt_price("EUR_USD", 1.100005), "1.10001")
        self.assertEqual(ex._fmt_price("USD_JPY", 159.1245), "159.125")
        # trailing-zero float (the mom-k5 style that used to pass by luck)
        self.assertEqual(ex._fmt_price("USD_JPY", 158.435), "158.435")

    def test_old_format_produced_invalid_jpy_string(self):
        ex = OandaExchange()
        old = f"{159.12433333333334:.5f}"
        self.assertEqual(old, "159.12433")  # what the venue rejected
        self.assertNotEqual(old, ex._fmt_price("USD_JPY", 159.12433333333334))


class TestPlaceOrderBody(unittest.TestCase):
    def test_market_order_jpy_sl_tp_are_3dp_strings(self):
        ex, captured = make_ex()
        r = ex.place_order(
            "USD_JPY", "BUY", 2000, "market",
            stop_loss=158.43544444444447, take_profit=159.12433333333334,
            tag="h1-mom",
        )
        order = captured["body"]["order"]
        self.assertEqual(order["stopLossOnFill"]["price"], "158.435")
        self.assertEqual(order["takeProfitOnFill"]["price"], "159.124")
        self.assertEqual(r.status, "filled")

    def test_market_order_majors_are_5dp_strings(self):
        ex, captured = make_ex()
        ex.place_order("GBP_USD", "BUY", 2000, "market",
                       stop_loss=1.3474855555555556, take_profit=1.3509216666666666)
        order = captured["body"]["order"]
        self.assertEqual(order["stopLossOnFill"]["price"], "1.34749")
        self.assertEqual(order["takeProfitOnFill"]["price"], "1.35092")

    def test_limit_price_formatted(self):
        ex, captured = make_ex()
        ex.place_order("USD_JPY", "SELL", 100, "limit", price=159.12433333333334)
        self.assertEqual(captured["body"]["order"]["price"], "159.124")


if __name__ == "__main__":
    unittest.main()
