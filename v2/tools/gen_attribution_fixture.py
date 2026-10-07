#!/usr/bin/env python3
"""W1 attribution-parity fixture generator — runs V1's REAL resolver chain
(strategies/fx_runner._trade_tags + _trade_tags walk, and
strategies/lane_attribution.resolve_fill_tag / realized_by_tag) over a
synthetic venue journal whose transaction shapes are copied from the real
OANDA journal (recorded shapes: tagged MARKET_ORDERs, tagless ORDER_FILLs
linking via orderID, server-side SL/TP closes with tradesClosed, per-trade
partial closes with tradeReduced, direct clientExtensions fills, legacy
pre-cutoff tagless rows, unattributable post-cutoff rows).

The generator asserts V1's own outputs match the documented expectations
(self-check), then writes the fixture for the Rust parity harness.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, "/home/mrc/opentrader")  # live tree = source of truth for the resolver chain

TODAY = "2026-10-07"

JOURNAL = [
    # tagged entries: tag lives on the MARKET_ORDER's tradeClientExtensions
    {"id": "1001", "type": "MARKET_ORDER", "instrument": "EUR_USD",
     "tradeClientExtensions": {"id": "mom-k5-EUR_USD", "tag": "mom-k5", "comment": "mom-k5"}},
    {"id": "1002", "type": "ORDER_FILL", "orderID": "1001", "instrument": "EUR_USD",
     "tradeOpened": {"tradeID": "9001"}, "pl": "0.0000", "time": "2026-10-06T17:15:00.123456Z"},
    {"id": "1003", "type": "MARKET_ORDER", "instrument": "GBP_JPY",
     "tradeClientExtensions": {"id": "h1-mom-GBP_JPY", "tag": "h1-mom", "comment": "h1-mom"}},
    {"id": "1004", "type": "ORDER_FILL", "orderID": "1003", "instrument": "GBP_JPY",
     "tradeOpened": {"tradeID": "9002"}, "pl": "0.0000", "time": "2026-10-06T18:00:00.000000Z"},
    {"id": "1005", "type": "MARKET_ORDER", "instrument": "USD_JPY",
     "tradeClientExtensions": {"id": "crash-USD_JPY", "tag": "crash", "comment": "crash"}},
    {"id": "1006", "type": "ORDER_FILL", "orderID": "1005", "instrument": "USD_JPY",
     "tradeOpened": {"tradeID": "9003"}, "pl": "0.0000", "time": "2026-10-06T19:30:00.000000Z"},
    # server-side SL close of trade 9001: tagless fill, tradesClosed
    {"id": "1007", "type": "ORDER_FILL", "instrument": "EUR_USD",
     "tradesClosed": [{"tradeID": "9001", "units": "-100"}], "pl": "-5.2500",
     "time": "2026-10-06T20:00:00.000000Z"},
    # per-trade partial close of 9002: tagless fill, tradeReduced (#250)
    {"id": "1008", "type": "ORDER_FILL", "instrument": "GBP_JPY",
     "tradeReduced": {"tradeID": "9002", "units": "-50"}, "pl": "2.5000",
     "time": "2026-10-06T21:00:00.000000Z"},
    # server-side TP close of 9003
    {"id": "1009", "type": "ORDER_FILL", "instrument": "USD_JPY",
     "tradesClosed": [{"tradeID": "9003", "units": "100"}], "pl": "12.7500",
     "time": "2026-10-06T22:00:00.000000Z"},
    # legacy pre-cutoff tagless fill → legacy-smoke
    {"id": "1010", "type": "ORDER_FILL", "instrument": "EUR_USD", "units": "100",
     "pl": "0.5000", "time": "2026-08-30T10:00:00.000000Z"},
    # post-cutoff tagless, no links → unattributed (LOUD)
    {"id": "1011", "type": "ORDER_FILL", "instrument": "EUR_USD", "units": "100",
     "pl": "-1.5000", "time": "2026-10-07T09:00:00.000000Z"},
    # direct clientExtensions on the fill → resolves immediately
    {"id": "1012", "type": "ORDER_FILL", "instrument": "EUR_USD", "units": "100",
     "clientExtensions": {"id": "mom-k5-EUR_USD-r2", "tag": "mom-k5", "comment": "mom-k5"},
     "pl": "3.0000", "time": "2026-10-07T09:05:00.000000Z"},
    # untagged MARKET_ORDER → ignored for tags
    {"id": "1013", "type": "MARKET_ORDER", "instrument": "AUD_USD"},
    # close of an UNKNOWN trade → unattributable
    {"id": "1014", "type": "ORDER_FILL", "instrument": "USD_CAD",
     "tradesClosed": [{"tradeID": "9999"}], "pl": "0.2500",
     "time": "2026-10-07T09:10:00.000000Z"},
    # filler non-fill transaction types are skipped
    {"id": "1015", "type": "DAILY_FINANCING", "pl": "-0.7500"},
]

EXPECTED_TAGS = {"9001": "mom-k5", "9002": "h1-mom", "9003": "crash"}
EXPECTED_ORDER_TAG = {"1001": "mom-k5", "1003": "h1-mom", "1005": "crash"}
EXPECTED_RESOLVE = {
    "1002": "mom-k5", "1004": "h1-mom", "1006": "crash",
    "1007": "mom-k5", "1008": "h1-mom", "1009": "crash",
    "1010": None,  # pre-cutoff tagless → resolve returns None; caller
                   # grandfathers to legacy-smoke
    "1011": None,  # post-cutoff tagless → unattributed
    "1012": "mom-k5",
    "1014": None,  # unknown trade → unattributable
}
EXPECTED_REALIZED_ALL = {
    "mom-k5": -5.25 + 3.0,
    "h1-mom": 2.5,
    "crash": 12.75,
    "legacy-smoke": 0.5,
    "unattributed": -1.5 + 0.25,
}
EXPECTED_REALIZED_TODAY = {"mom-k5": 3.0, "unattributed": -1.5 + 0.25}


class FakeEx:
    """Minimal `ex` stub: _account_id + _request returning the journal in
    one batch (V1's _walk_transactions handles both pagination shapes; a
    single short batch exercises the simple path)."""

    _account_id = "101-004-1234567-001"

    def _request(self, method, path, body=None):
        assert method == "GET"
        return {"transactions": JOURNAL, "lastTransactionID": "1015"}


def main():
    from strategies.fx_runner import _trade_tags
    from strategies.lane_attribution import resolve_fill_tag, realized_by_tag, size_attribution_legacy

    ex = FakeEx()
    tags, order_tag = _trade_tags(ex)
    assert tags == EXPECTED_TAGS, f"V1 _trade_tags tags mismatch: {tags}"
    assert order_tag == EXPECTED_ORDER_TAG, f"V1 order_tag mismatch: {order_tag}"

    resolve_out = {}
    for t in JOURNAL:
        if t.get("type") != "ORDER_FILL":
            continue
        resolve_out[t["id"]] = resolve_fill_tag(t, tags, order_tag)
    assert resolve_out == EXPECTED_RESOLVE, f"resolve mismatch: {resolve_out}"

    # realized via V1's own journal walk (the FakeEx supplies the journal)
    realized_all, realized_today = realized_by_tag(ex)
    assert {k: round(v, 4) for k, v in realized_all.items()} == {
        k: round(v, 4) for k, v in EXPECTED_REALIZED_ALL.items()
    }, f"realized_all mismatch: {realized_all}"
    assert {k: round(v, 4) for k, v in realized_today.items()} == {
        k: round(v, 4) for k, v in EXPECTED_REALIZED_TODAY.items()
    }, f"realized_today mismatch: {realized_today}"

    # legacy size matcher sanity
    assert size_attribution_legacy(5000) == "crash"
    assert size_attribution_legacy(2000) == "h1-mom"
    assert size_attribution_legacy(100) == "mom-k5"

    fixture = {
        "desc": "attribution journal (V1 shapes; V1 resolver computed the expect side)",
        "today": TODAY,
        "transactions": JOURNAL,
        "expect_tags": EXPECTED_TAGS,
        "expect_order_tag": EXPECTED_ORDER_TAG,
        "expect_resolve": EXPECTED_RESOLVE,
        "expect_realized_all": EXPECTED_REALIZED_ALL,
        "expect_realized_today": EXPECTED_REALIZED_TODAY,
    }
    out = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "attribution_journal.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(fixture, indent=1))
    print(f"V1 resolver verified against expectations; fixture written to {out}")


if __name__ == "__main__":
    main()
