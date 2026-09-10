"""newsfeed.cli — python -m newsfeed {init,add-source,fetch,backfill,dedup,search,stats}"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config, store, dedup as dedup_mod
from .net import fetch
from .sources import rss as rss_src
from .sources import gdelt as gdelt_src


def _open():
    config.ensure_dir()
    store.init_db(config.DB_PATH)
    return store.connect(config.DB_PATH)


def _source_by_name_or_id(con, ident):
    for s in store.list_sources(con):
        if str(s["id"]) == str(ident) or s["name"] == ident:
            return s
    return None


def cmd_init(args):
    con = _open()
    n = len(store.list_sources(con))
    print(f"init: db at {config.DB_PATH} | sources: {n}")


def cmd_add_source(args):
    con = _open()
    sid = store.add_source(con, args.kind, args.name, args.url_or_query,
                           tier=args.tier, rate_limit_s=args.rate_limit)
    print(f"added source id={sid} ({args.kind}: {args.name})")


def cmd_list_sources(args):
    con = _open()
    for s in store.list_sources(con):
        print(f"{s['id']:3d} [{s['kind']:5s}] {s['name']:28s} tier {s['tier']} "
              f"enabled={s['enabled']} :: {s['url_or_query'][:70]}")


def _fetch_rss(con, src, dry=False):
    ok, res = fetch(src["url_or_query"], etag=src["etag"],
                    last_modified=src["last_modified"], rate_s=src["rate_limit_s"])
    if not ok:
        return None, res
    if res.get("not_modified"):
        return 0, None
    items = rss_src.parse(res["content"], src["name"])
    rows = []
    for it in items:
        rows.append({"content_hash": it.content_hash, "title": it.title,
                     "summary": (it.summary or "")[:4000], "body": it.body,
                     "lang": it.lang, "published_utc": it.published_utc,
                     "published_precision": it.published_precision,
                     "canonical_url": None, "simhash": None,
                     "raw_url": it.raw_url, "raw_title": it.raw_title,
                     "raw_summary": (it.raw_summary or "")[:2000]})
    return rows, res


def _fetch_gdelt(con, src, dry=False):
    ok, res = gdelt_src.fetch_artlist(src["url_or_query"],
                                      timespan=(json.loads(src["config_json"] or "{}").get("timespan", "24h")
                                                if src["config_json"] else "24h"),
                                      rate_s=src["rate_limit_s"])
    if not ok:
        return None, res
    items = gdelt_src.to_items(res, src["name"])
    rows = []
    for it in items:
        rows.append({"content_hash": it.content_hash, "title": it.title,
                     "summary": "", "body": None, "lang": it.lang,
                     "published_utc": it.published_utc,
                     "published_precision": it.published_precision,
                     "canonical_url": None, "simhash": None,
                     "raw_url": it.raw_url, "raw_title": it.raw_title,
                     "raw_summary": ""})
    return rows, res


def cmd_fetch(args):
    con = _open()
    sources = store.list_sources(con, enabled_only=True)
    if args.source:
        src = _source_by_name_or_id(con, args.source)
        sources = [src] if src else []
    total_new = 0
    for src in sources:
        fetcher = FETCHERS.get(src["kind"])
        if fetcher is None:
            continue
        run_id = store.start_run(con, src["id"])
        ok, res = fetch(src["url_or_query"], etag=src["etag"],
                        last_modified=src["last_modified"],
                        rate_s=src["rate_limit_s"])
        if not ok:
            store.finish_run(con, run_id, "error", 0, 0, error=str(res)[:300])
            print(f"[{src['name']}] ERROR: {res}")
            continue
        if res.get("not_modified"):
            store.finish_run(con, run_id, "not_modified", 0, 0)
            print(f"[{src['name']}] 304 not modified")
            continue
        if src["kind"] == "rss":
            items = rss_src.parse(res["content"], src["name"])
        else:
            items = gdelt_src.to_items(json.loads(res["content"]).get("articles", []),
                                       src["name"])
        rows = [_item_to_row(it) for it in items]
        n_new, n_unch, n_upd = store.upsert_items(con, rows, run_id, src["id"])
        con.execute("UPDATE sources SET etag = ?, last_modified = ?, last_fetched_utc = "
                    "strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ?",
                    [res.get("etag"), res.get("last_modified"), src["id"]])
        con.commit()
        store.finish_run(con, run_id, "ok", n_new, n_unch)
        total_new += n_new
        print(f"[{src['name']}] new {n_new}, unchanged {n_unch}")
    print(f"fetch complete: {total_new} new items")


def _item_to_row(it):
    from .model import simhash64, simhash_text_for
    from .model import content_hash_for as chf
    if not it.content_hash:
        it.content_hash = chf(it)
    return {"content_hash": it.content_hash, "title": it.title,
            "summary": (it.summary or "")[:4000], "body": it.body,
            "lang": it.lang, "published_utc": it.published_utc,
            "published_precision": it.published_precision,
            "canonical_url": None, "simhash": str(simhash64(simhash_text_for(it))),
            "raw_url": it.raw_url, "raw_title": it.raw_title,
            "raw_summary": (it.raw_summary or "")[:2000]}


def cmd_backfill(args):
    con = _open()
    src = _source_by_name_or_id(con, args.source)
    if src is None or src["kind"] != "gdelt":
        raise SystemExit("backfill needs a gdelt source")
    windows = gdelt_src.backfill_windows(days=args.days, chunk_days=args.chunk)
    print(f"backfill: {len(windows)} windows x <=250 records")
    run_id = store.start_run(con, src["id"])
    n_new = 0
    for startdt, enddt in windows:
        ok, res = gdelt_src.fetch_artlist(src["url_or_query"], startdt=startdt,
                                          enddt=enddt, rate_s=src["rate_limit_s"])
        if not ok:
            print(f"  {startdt[:8]}: error {str(res)[:80]}")
            continue
        items = gdelt_src.to_items(res, src["name"])
        rows = [_item_to_row(it) for it in items]
        n_new += store.upsert_items(con, rows, run_id, src["id"])[0]
        print(f"  {startdt[:8]}-{enddt[:8]}: {len(rows)} items (total new {n_new})")
    store.finish_run(con, run_id, "ok", n_new, 0)
    print(f"backfill complete: {n_new} new items")


def cmd_dedup(args):
    con = _open()
    res = dedup_mod.run(con, dedup_version=args.version)
    print(f"dedup: {res['items']} items -> {res['clusters']} clusters "
          f"({res['duplicates']} duplicates), {res['pairs_checked']} candidate pairs")


def cmd_search(args):
    con = _open()
    rows = store.search(con, args.query, since=args.since, until=args.until,
                        limit=args.limit)
    for r in rows:
        print(f"{(r['published_utc'] or '—')[:10]} [{r['id']:5d}] {r['title'][:90]}")
    print(f"({len(rows)} results)")


def cmd_stats(args):
    con = _open()
    n_items = con.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    n_obs = con.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    n_clusters = con.execute("SELECT COUNT(DISTINCT cluster_id) FROM items").fetchone()[0]
    n_sources = con.execute("SELECT COUNT(*) FROM sources WHERE enabled=1").fetchone()[0]
    span = con.execute("SELECT MIN(published_utc), MAX(published_utc) FROM items").fetchone()
    print(f"items {n_items} | observations {n_obs} | clusters {n_clusters} | "
          f"sources {n_sources} | span {span[0]} -> {span[1]}")


def main(argv=None):
    ap = argparse.ArgumentParser("newsfeed", description="standalone news store")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init").set_defaults(fn=cmd_init)
    p = sub.add_parser("add-source"); p.set_defaults(fn=cmd_add_source)
    p.add_argument("--kind", choices=["rss", "gdelt"], required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--url-or-query", required=True)
    p.add_argument("--tier", type=int, default=5)
    p.add_argument("--rate-limit", type=float, default=None)
    sub.add_parser("list-sources").set_defaults(fn=cmd_list_sources)
    p = sub.add_parser("fetch"); p.set_defaults(fn=cmd_fetch)
    p.add_argument("--source", default=None, help="source id or name")
    p = sub.add_parser("backfill"); p.set_defaults(fn=cmd_backfill)
    p.add_argument("--source", required=True)
    p.add_argument("--days", type=int, default=90)
    p.add_argument("--chunk", type=int, default=3)
    p = sub.add_parser("dedup"); p.set_defaults(fn=cmd_dedup)
    p.add_argument("--version", type=int, default=1)
    p = sub.add_parser("search"); p.set_defaults(fn=cmd_search)
    p.add_argument("query")
    p.add_argument("--since"); p.add_argument("--until")
    p.add_argument("--limit", type=int, default=50)
    sub.add_parser("stats").set_defaults(fn=cmd_stats)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
