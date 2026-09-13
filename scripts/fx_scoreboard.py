#!/usr/bin/env python3
"""fx_scoreboard — the pre-cut evaluation table (map #218 ticket: Friday
scoreboard). Composes venue-truth per trained lane into one file:

  realized PnL (venue journal, tag-attributed) + current uPL + peak uPL
  (MFE) + give-back ratio + financing costs + sizing fidelity + lifecycle
  state. This is the evidence the human's Friday cut decision reads.

NOTHING here writes to the venue; the cut itself is human-gated
(ADR-0009 §4 + expert_lifecycle cut state).

Usage: python3 scripts/fx_scoreboard.py [--out PATH]
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))
from exchange.oanda import OandaExchange  # noqa: E402

LANES = ("g151", "g138", "g137")
OUT_DEFAULT = PROJECT / "data" / "warden" / "friday_scoreboard.json"


def _financing_by_tag(ex):
    """Per-lane financing from TRADE_FINANCING transactions, attributed via
    the shared tradeID->tag chain. Full-journal walk (#252): a single
    sinceid call caps at 1000 txns with no pagination — the old first-page
    read hid most of the financing history."""
    from strategies.fx_runner import _trade_tags, _walk_transactions
    tags, _ = _trade_tags(ex)
    fin = {}
    for t in _walk_transactions(
            ex, f"/v3/accounts/{ex._account_id}/transactions/sinceid?id=0"):
        if t.get("type") != "TRADE_FINANCING":
            continue
        tg = tags.get(str(t.get("tradeID"))) or "unknown"
        fin[tg] = fin.get(tg, 0.0) + float(t.get("pl", 0) or 0)
    return fin


def build():
    from strategies.fx_warden import lane_states, audit_sizing
    from strategies.expert_lifecycle import lifecycle_of
    from strategies.lane_attribution import realized_by_tag
    ex = OandaExchange()
    if not ex.connect():
        raise SystemExit("[scoreboard] venue unreachable")
    st = lane_states()
    if st is None:
        raise SystemExit("[scoreboard] lane truth unavailable")
    # sizing audit (fresh, live — writes scorecard/records as a side effect;
    # scoreboard reads its return value, not the cache)
    audit = audit_sizing(dry=True) or {}
    fin = _financing_by_tag(ex)
    # realized straight from the venue journal per tag (#251): the open-book
    # lanes map drops a trained lane the moment it goes flat and used to
    # render its realized as a silent 0.0; a tag with NO journal fills is an
    # anomaly and shows as None, never as 0.00.
    realized_all, realized_today = realized_by_tag(ex)

    state = json.loads((PROJECT / "data" / "warden" / "warden_state.json").read_text()) \
        if (PROJECT / "data" / "warden" / "warden_state.json").exists() else {}
    mfe = state.get("mfe", {})
    sc = json.loads((PROJECT / "data" / "warden" / "scorecard.json").read_text()) \
        if (PROJECT / "data" / "warden" / "scorecard.json").exists() else {}
    last_scores = sc.get("last_scores", {})

    rows = {}
    for expert in LANES:
        tag = f"fxexp-{expert}"
        eid = f"fx-expert-{expert}"
        lane = st["lanes"].get(tag, {})
        m = mfe.get(tag, {})
        peak = m.get("peak_upl", lane.get("upl", 0.0))
        cur = lane.get("upl", 0.0)
        s = last_scores.get(tag, {})
        lc = lifecycle_of(eid) or {}
        rz = realized_all.get(tag)
        rows[tag] = {
            "lifecycle": lc.get("lifecycle", "unregistered"),
            "notional_cap": lc.get("notional_cap", 1.0),
            "realized_all": None if rz is None else round(rz, 2),
            "realized_all_source": ("venue-journal" if rz is not None
                                    else "NO JOURNAL FILLS FOR TAG"),
            "realized_today": round(realized_today.get(tag, 0.0), 2),
            "upl": round(cur, 2),
            "peak_upl": round(peak, 2),
            "give_back": round((peak - cur) / peak, 3) if peak > 0 else 0.0,
            "financing": round(fin.get(tag, 0.0), 2),
            "gross_usd": round(lane.get("gross_usd", 0.0), 0),
            "positions": lane.get("positions", 0),
            "sizing_fidelity_pct": audit.get(tag, {}).get("fidelity_pct"),
            "warden_score_pct": s.get("score_pct"),
            "warden_miss_pct": s.get("miss_pct"),
        }
    total_pnl = sum((r["realized_all"] or 0.0) + r["upl"] for r in rows.values())
    return {"asof": datetime.now(timezone.utc).isoformat(),
            "account": {"nav": st.get("nav"), "balance": st.get("balance"),
                        "unrealized": st.get("unrealized"),
                        "financing_today": st.get("financing_today")},
            "lanes": rows,
            "total_pnl_all_lanes": round(total_pnl, 2),
            "note": "venue truth; cut is human-gated (Friday 2026-09-11 close, bottom two)"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUT_DEFAULT))
    a = ap.parse_args()
    sb = build()
    Path(a.out).write_text(json.dumps(sb, indent=1))
    print(f"[scoreboard] {sb['asof']}  (NAV ${sb['account']['nav']:,.2f}, "
          f"total lanes PnL {sb['total_pnl_all_lanes']:+.2f})")
    hdr = (f"{'lane':14s} {'life':10s} {'realized':>10s} {'uPL':>9s} {'peak':>9s} "
           f"{'gback':>6s} {'fin':>7s} {'fid%':>6s} {'w-score':>8s}")
    print(hdr)
    print("-" * len(hdr))
    for tag, r in sorted(sb["lanes"].items()):
        ws = "—" if r["warden_score_pct"] is None else f"{r['warden_score_pct']:+.2f}"
        fid = "—" if r["sizing_fidelity_pct"] is None else f"{r['sizing_fidelity_pct']:.0f}"
        rz = "—" if r["realized_all"] is None else f"{r['realized_all']:>+10.2f}"
        print(f"{tag:14s} {r['lifecycle']:10s} {rz:>10s} "
              f"{r['upl']:>+9.2f} {r['peak_upl']:>+9.2f} "
              f"{r['give_back'] * 100:>5.1f}% {r['financing']:>+7.2f} {fid:>6s} {ws:>8s}")
    print(f"\n[scoreboard] saved -> {a.out}")


if __name__ == "__main__":
    main()
