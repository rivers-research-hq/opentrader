"""Unit tests for status-checked recording (#169) and the hourly reconcile
cursor (#172). Fake exchange only — no venue calls, no real files touched
(STATE/LEDGER/CURSOR/PROJECT are monkeypatched into a tmp dir).

Regression context: run_intraday recorded every place_order result as a
fill — after the truthful-adapter fix (#167) a reject returns
price=0/status=rejected and the runner wrote price-0 ledger rows plus an
entry=0 phantom into fx_intraday.json every hourly run (map #158).
"""
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from exchange.base import OHLCV, OrderResult  # noqa: E402


def _bars(n=20, rising=True):
    px = [1.0 + (i * 0.001 if rising else -i * 0.001) for i in range(n)]
    return [OHLCV(timestamp=i, open=p, high=p + 0.001, low=p - 0.001, close=p, volume=1)
            for i, p in enumerate(px)]


class FakeEx:
    """Just enough exchange surface for run_intraday and _reconcile."""

    def __init__(self, order_result, journal=None):
        self.order_result = order_result
        self.journal = journal or []
        self.connected = False
        self.orders = []
        self._account_id = "test-account"

    def connect(self):
        self.connected = True
        return True

    def discover_symbols(self):
        return ["USD_JPY"]

    def get_bars(self, symbol, timeframe, limit):
        return _bars()

    def get_current_price(self, symbol):
        return 158.5

    def place_order(self, symbol, side, qty, order_type, **kw):
        self.orders.append((symbol, side, qty, order_type, kw))
        return self.order_result

    def _request(self, method, path, body=None):
        if "openTrades" in path:
            return {"trades": []}
        if "transactions/sinceid" in path:
            since = int(path.split("id=")[1])
            return {"transactions": [t for t in self.journal if int(t["id"]) > since]}
        return {}


def _fill_result():
    return OrderResult(order_id="900", symbol="USD_JPY", side="BUY", quantity=2000,
                       price=158.5, status="filled",
                       timestamp=datetime.now(timezone.utc).isoformat(), raw={})


def _reject_result():
    return OrderResult(order_id="", symbol="USD_JPY", side="BUY", quantity=2000,
                       price=0, status="rejected",
                       timestamp=datetime.now(timezone.utc).isoformat(),
                       raw={"reason": "TAKE_PROFIT_ON_FILL_PRICE_PRECISION_EXCEEDED"})


class RunnerTest(unittest.TestCase):
    def setUp(self):
        import strategies.fx_runner as fr
        self.fr = fr
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        fr.PROJECT = self.tmp
        fr.STATE = self.tmp / "fx_state.json"
        fr.LEDGER = self.tmp / "fx_ledger.jsonl"
        fr.CURSOR = self.tmp / "fx_reconcile_cursor.json"
        (self.tmp / "data").mkdir(exist_ok=True)

    # — #169: rejected orders leave no residue —

    def test_rejected_open_writes_no_ledger_row_and_no_position(self):
        ex = FakeEx(_reject_result())
        self.fr.OandaExchange = lambda: ex
        self.fr.run_intraday(dry=False)
        ledger = self.fr.LEDGER.read_text() if self.fr.LEDGER.exists() else ""
        self.assertEqual(ledger, "")
        istate = json.loads((self.tmp / "data" / "fx_intraday.json").read_text())
        self.assertNotIn("USD_JPY", istate["positions"])

    def test_filled_open_records_ledger_row_and_position(self):
        ex = FakeEx(_fill_result())
        self.fr.OandaExchange = lambda: ex
        self.fr.run_intraday(dry=False)
        rows = [json.loads(l) for l in self.fr.LEDGER.read_text().splitlines() if l.strip()]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["reason"], "intraday-momentum")
        self.assertEqual(rows[0]["price"], 158.5)
        istate = json.loads((self.tmp / "data" / "fx_intraday.json").read_text())
        self.assertEqual(istate["positions"]["USD_JPY"]["entry"], 158.5)

    # — #172: monotonic sinceid cursor, idempotent replay —

    def test_reconcile_advances_cursor_and_dedups(self):
        journal = [
            {"id": "100", "type": "ORDER_FILL", "instrument": "USD_JPY", "time":
             "2026-09-03T00:30:11.000000000Z", "units": "-5000", "price": "1.39227",
             "transactionID": "100"},
            {"id": "101", "type": "ORDER_CANCEL", "time": "2026-09-03T00:30:11Z"},
        ]
        ex = FakeEx(_fill_result(), journal)
        self.fr._reconcile(ex, dry=False)
        rows = [json.loads(l) for l in self.fr.LEDGER.read_text().splitlines() if l.strip()]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["reason"], "venue-reconciliation")
        self.assertEqual(json.loads(self.fr.CURSOR.read_text())["last_id"], 101)

        # replay of the same journal window adds nothing
        self.fr._reconcile(ex, dry=False)
        rows = [json.loads(l) for l in self.fr.LEDGER.read_text().splitlines() if l.strip()]
        self.assertEqual(len(rows), 1)

    def test_reconcile_picks_up_only_new_fills(self):
        old = [{"id": "100", "type": "ORDER_FILL", "instrument": "USD_JPY", "time":
                "2026-09-03T00:30:11.000000000Z", "units": "-5000", "price": "1.39227",
                "transactionID": "100"}]
        ex = FakeEx(_fill_result(), old)
        self.fr._reconcile(ex, dry=False)
        new = old + [{"id": "105", "type": "ORDER_FILL", "instrument": "USD_JPY", "time":
                      "2026-09-03T01:05:56.000000000Z", "units": "-5000",
                      "price": "0.71615", "transactionID": "105"}]
        ex.journal = new
        self.fr._reconcile(ex, dry=False)
        rows = [json.loads(l) for l in self.fr.LEDGER.read_text().splitlines() if l.strip()]
        self.assertEqual([r["order_id"] for r in rows], ["100", "105"])
        self.assertEqual(json.loads(self.fr.CURSOR.read_text())["last_id"], 105)

    def test_reconcile_self_heals_from_lost_cursor(self):
        journal = [{"id": "100", "type": "ORDER_FILL", "instrument": "USD_JPY", "time":
                    "2026-09-03T00:30:11.000000000Z", "units": "-5000",
                    "price": "1.39227", "transactionID": "100"}]
        ex = FakeEx(_fill_result(), journal)
        self.fr._reconcile(ex, dry=False)
        self.fr.CURSOR.unlink()  # corrupt/lost cursor -> id 0 full rescan
        self.fr._reconcile(ex, dry=False)
        rows = [json.loads(l) for l in self.fr.LEDGER.read_text().splitlines() if l.strip()]
        self.assertEqual(len(rows), 1)  # tolerance dedup keeps it idempotent


if __name__ == "__main__":
    unittest.main()
