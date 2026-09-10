"""newsfeed.dedup — cross-source dedup, cheapest first, ±36h window.

1. canonical URL exact match -> duplicate
2. SimHash 64-bit, Hamming <= 3 -> candidate
3. word 5-gram Jaccard >= 0.70 -> duplicate
Union-find collapses candidates into clusters; canonical pick = earliest
published_utc, tie-break source tier then longest text. Non-canonical rows
are KEPT (cluster_id + is_canonical=0) so the archive stays complete and
dedup can be re-run. Separate idempotent pass — never inline in ingest.
"""

import sqlite3
from collections import defaultdict

from .model import simhash64, hamming, jaccard, simhash_text_for, _shingles

WINDOW_S = 36 * 3600
HAMMING_MAX = 3
JACCARD_MIN = 0.70


def _union_find(parent: dict, a, b):
    ra, rb = a, b
    while parent[ra] != ra:
        ra = parent[ra]
    while parent[rb] != rb:
        rb = parent[rb]
    if ra != rb:
        parent[ra] = rb


def run(con: sqlite3.Connection, dedup_version: int) -> dict:
    rows = con.execute(
        """SELECT id, content_hash, canonical_url, title, summary, source_id,
                  published_utc, simhash FROM items ORDER BY id""").fetchall()
    items = [dict(r) for r in rows]
    for it in items:
        if not it.get("simhash"):
            it["simhash"] = str(simhash64(simhash_text_for(it)))

    by_hash = defaultdict(list)
    for it in items:
        by_hash[it["content_hash"]].append(it)

    # union-find over item ids
    parent = {it["id"]: it["id"] for it in items}
    items_by_id = {it["id"]: it for it in items}
    done_pairs = {}

    # layer 1: exact canonical-URL match
    by_url = defaultdict(list)
    for it in items:
        if it.get("canonical_url"):
            by_url[it["canonical_url"]].append(it["id"])
    for url, ids in by_url.items():
        for i in ids[1:]:
            _union_find(parent, ids[0], i)

    # layers 2+3: shared-shingle candidates then Jaccard confirm, ±36h window.
    # (SimHash Hamming<=3 was the planned filter but does not hold at
    # news-item scale: a 1-word change flips 5 of ~20 shingles -> hamming 13.
    # A shared 4-word shingle is the load-bearing candidate signal at this
    # scale; Jaccard >= 0.70 confirms. simhash stays on items for analytics.)
    inv = defaultdict(list)  # shingle -> [item ids], within-window pairs only
    sh_of = {}
    for it in items:
        sh = _shingles(_text(it), 4)
        sh_of[it["id"]] = sh
        for s in sh:
            inv[s].append(it["id"])
    pairs_checked = 0
    for root_sh, ids in inv.items():
        if len(ids) < 2:
            continue
        for x in range(len(ids)):
            for y in range(x + 1, len(ids)):
                a, b = items_by_id[ids[x]], items_by_id[ids[y]]
                ta = a["published_utc"] or ""
                tb = b["published_utc"] or ""
                if not ta or not tb:
                    continue
                dt = abs(_parse_s(tb) - _parse_s(ta))
                if dt > WINDOW_S:
                    continue
                if ids[y] in done_pairs.get(ids[x], set()):
                    continue
                done_pairs.setdefault(ids[x], set()).add(ids[y])
                pairs_checked += 1
                if jaccard(_text(a), _text(b)) >= JACCARD_MIN:
                    _union_find(parent, a["id"], b["id"])

    # cluster canonical pick: earliest published, tie source tier, longest text
    clusters = defaultdict(list)
    for it in items:
        root = it["id"]
        while parent[root] != root:
            root = parent[root]
        clusters[root].append(it)

    n_dup = 0
    for root, members in clusters.items():
        members.sort(key=lambda m: (m["published_utc"] or "9999",
                                    -_source_tier(con, m["source_id"]),
                                    -len((m["title"] or "") + (m["summary"] or ""))))
        canon = members[0]
        for m in members:
            con.execute("UPDATE items SET cluster_id = ?, is_canonical = ?, "
                        "dedup_version = ? WHERE id = ?",
                        [canon["id"], 1 if m["id"] == canon["id"] else 0,
                         dedup_version, m["id"]])
            n_dup += 0 if m["id"] == canon["id"] else 1
    con.commit()
    return {"items": len(items), "clusters": len(clusters),
            "duplicates": len(items) - len(clusters), "pairs_checked": pairs_checked}


def _text(it):
    return (it["title"] or "") + " " + (it["summary"] or "")[:200]


def _parse_s(ts: str) -> float:
    from datetime import datetime
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()


def _source_tier(con: sqlite3.Connection, source_id) -> int:
    r = con.execute("SELECT tier FROM sources WHERE id = ?", [source_id]).fetchone()
    return r["tier"] if r else 9
