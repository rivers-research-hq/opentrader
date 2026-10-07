#!/usr/bin/env python3
"""W1-tails venue-parity generator — runs V1's REAL resolver chain
(strategies.fx_runner._trade_tags + strategies.lane_attribution) over the
EXPORTED LIVE OANDA journal (v2/tests/fixtures/live_journal.json — the
practice account's own 6,896-transaction journal, read-only export
authorized by the human), and records the expected realized-by-tag as the
fixture for the Rust parity gate.

This is the cutover prerequisite: V2's OANDA semantics must reproduce the
venue's own attribution on REAL data before any lane migration.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, "/home/mrc/opentrader")  # live tree = source of truth

JOURNAL = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "live_journal.json"


class FakeEx:
    """Minimal `ex` stub serving the exported journal (the sinceid walk
    sees one short-of-1000 batch and stops after the first call — exactly
    how the export was produced cursor-wise)."""

    _account_id = "101-001-40262644-001"

    def __init__(self, transactions):
        self._transactions = transactions

    def _request(self, method, path, body=None):
        assert method == "GET"
        return {"transactions": self._transactions, "lastTransactionID": "last"}


def main():
    from strategies.fx_runner import _trade_tags
    from strategies.lane_attribution import realized_by_tag, LEGACY_SMOKE, UNATTRIBUTED

    journal = json.loads(JOURNAL.read_text())
    transactions = journal["transactions"]
    ex = FakeEx(transactions)

    tags, order_tag = _trade_tags(ex)
    realized_all, realized_today = realized_by_tag(ex)

    # the expect side is V1's OWN output on the real journal — no hand math
    fixture = {
        "desc": (
            "venue-parity: V1's real resolver over the EXPORTED LIVE OANDA "
            "practice journal (read-only export, human-authorized). "
            f"{len(transactions)} transactions. Exported balance "
            f"{journal['balance']} {journal['currency']}."
        ),
        "n_transactions": len(transactions),
        "account_id": journal["account_id"],
        "expect_tags_count": len(tags),
        "expect_order_tag_count": len(order_tag),
        "expect_realized_all": realized_all,
        # realized_today is time-relative (V1 uses now()); the parity gate
        # compares realized_all — tag-for-tag, exact f64 (same journal
        # order, same parse → bit-identical sums)
    }
    out = JOURNAL.parent / "live_parity_expected.json"
    out.write_text(json.dumps(fixture, indent=1, sort_keys=True))
    print(f"V1 resolver over the live journal:")
    print(f"  tags: {len(tags)} tradeID->tag, {len(order_tag)} orderID->tag")
    print(f"  realized_all:")
    for tag in sorted(realized_all, key=lambda t: realized_all[t]):
        print(f"    {tag}: {realized_all[tag]:.4f}")
    print(f"  fixture written to {out}")


if __name__ == "__main__":
    main()
