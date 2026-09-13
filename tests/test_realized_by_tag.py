"""Unit tests for the shared realized walk (#251/#252).

The #251 defect: the scoreboard/warden consumers read ONE sinceid call —
which caps at 1000 txns with no pagination (#252) — and resolved tags
without the tradesClosed/tradeReduced chain, so the trained lanes' closes
were invisible and their realized rendered as a silent 0.0 masking a real
loss. lane_attribution.realized_by_tag() is the shared full-walk source;
these tests pin it on a synthetic journal — no venue calls, no file writes.
"""
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from strategies.lane_attribution import (  # noqa: E402
    LEGACY_SMOKE, UNATTRIBUTED, realized_by_tag,
)


def _fill(i, pl, ext=None, closed_trade=None, time="2026-09-01T12:00:00Z"):
    t = {"type": "ORDER_FILL", "id": str(i), "time": time, "pl": pl}
    if ext:
        t["clientExtensions"] = ext
    if closed_trade:
        t["tradesClosed"] = [{"tradeID": closed_trade}]
    return t


class TestRealizedByTag(unittest.TestCase):
    def _run(self, txns, tags=None, order_tag=None):
        fake_ex = mock.Mock()
        fake_ex._account_id = "000"
        with mock.patch("strategies.fx_runner._trade_tags",
                        return_value=(tags or {}, order_tag or {})), \
             mock.patch("strategies.fx_runner._walk_transactions",
                        return_value=txns):
            return realized_by_tag(fake_ex)

    def test_close_beyond_txn_1000_still_counts(self):
        # the #252 shape: 1500 journal rows; the lane's PnL-carrying fill
        # sits past the single-call window — a first-page reader reports 0.0
        filler = [{"type": "ORDER_FILL", "id": str(i), "pl": 0.0,
                   "time": "2026-09-01T00:00:00Z"} for i in range(1500)]
        close = _fill(1501, -12.5, ext={"tag": "fxexp-g151"})
        realized, _ = self._run(filler + [close])
        self.assertAlmostEqual(realized["fxexp-g151"], -12.5)

    def test_tagless_server_close_resolves_through_trades_closed_chain(self):
        # server-side SL/TP closes carry no extensions of their own
        txns = [_fill(1, 0.0, ext={"tag": "fxexp-g137"}),   # opening fill
                _fill(2, 3.25, closed_trade="1")]           # tagless close
        realized, _ = self._run(txns, tags={"1": "fxexp-g137"})
        self.assertAlmostEqual(realized["fxexp-g137"], 3.25)

    def test_post_cutoff_tagless_fill_is_loud_unattributed(self):
        realized, _ = self._run([_fill(1, -0.68, time="2026-09-10T12:00:00Z")])
        self.assertAlmostEqual(realized[UNATTRIBUTED], -0.68)

    def test_pre_cutoff_tagless_fill_grandfathers_to_legacy_smoke(self):
        realized, _ = self._run([_fill(1, 2.0, time="2026-08-30T12:00:00Z")])
        self.assertAlmostEqual(realized[LEGACY_SMOKE], 2.0)

    def test_opening_fills_and_non_fills_do_not_distort(self):
        txns = [{"type": "MARKET_ORDER", "id": "9"},
                _fill(1, 0.0, ext={"tag": "fxexp-g138"}),   # entry, pl 0.0
                _fill(2, -5.0, ext={"tag": "fxexp-g138"})]
        realized, today = self._run(txns)
        self.assertAlmostEqual(realized["fxexp-g138"], -5.0)
        self.assertAlmostEqual(today.get("fxexp-g138", 0.0), 0.0)

    def test_today_split_follows_the_fill_dates(self):
        today = datetime.now(timezone.utc).date().isoformat()
        txns = [_fill(1, -2.0, ext={"tag": "fxexp-g137"},
                      time=f"{today}T10:00:00Z"),
                _fill(2, 1.0, ext={"tag": "fxexp-g137"},
                      time="2026-09-01T10:00:00Z")]
        realized, today_map = self._run(txns)
        self.assertAlmostEqual(today_map["fxexp-g137"], -2.0)
        self.assertAlmostEqual(realized["fxexp-g137"], -1.0)


if __name__ == "__main__":
    unittest.main()
