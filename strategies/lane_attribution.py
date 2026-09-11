#!/usr/bin/env python3
"""Single source of truth for FX lane attribution.

Resolves a venue ORDER_FILL's lane tag from the clientExtensions/orderID chain
(tradeID -> opening MARKET_ORDER tag, map #174/#175), with a LOUD "unattributed"
bucket instead of the old silent size-matcher default that credited every
tagless row to mom-k5 (mis-attributing the experts' evidence base, #229 D3).

The fill-size matcher survives ONLY for grandfathered pre-08-31 rows — the
ledger is append-only and those rows are never rewritten. ToC Q05: reconciliation
rows are stamped from the venue txn's clientExtensions, which this module is the
single place for.
"""

LEGACY_CUTOFF = "2026-08-31T18:00"
UNATTRIBUTED = "unattributed"


def resolve_fill_tag(t, tags, order_tag):
    """Resolve an ORDER_FILL transaction's lane tag via the chain.

    Returns the tag string, or None when unresolvable (caller decides the
    fallback: grandfathered legacy size-match vs "unattributed").

    `tags`      : tradeID -> tag  (from fx_runner._trade_tags)
    `order_tag` : orderID -> tag  (from fx_runner._trade_tags)
    """
    tag = (t.get("clientExtensions") or {}).get("tag") or order_tag.get(t.get("orderID"))
    if tag:
        return tag
    # Server-side SL/TP and the fxexp lane's per-trade partial closes land as
    # fills that carry NO extensions of their own — they resolve through the
    # closed/reduced/opened trade's OPENING-fill tag. tradesClosed is a list;
    # tradeReduced/tradeOpened are single objects (#250: tradeReduced was the
    # missing leg — 55 partial-close fills were wrongly "unattributed").
    for key in ("tradesClosed", "tradeReduced", "tradeOpened"):
        val = t.get(key)
        if not val:
            continue
        items = val if isinstance(val, list) else [val]
        for tc in items:
            tid = (tc or {}).get("tradeID")
            if tid:
                tag = tags.get(str(tid))
                if tag:
                    return tag
    return None


def size_attribution_legacy(qty):
    """Grandfathered pre-08-31 fill-size matcher (legacy rows only)."""
    q = abs(float(qty)) if qty is not None else 0.0
    if q >= 5000:
        return "crash"
    if q >= 2000:
        return "h1-mom"
    return "mom-k5"
