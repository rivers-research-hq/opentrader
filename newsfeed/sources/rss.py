"""newsfeed.sources.rss — RSS 2.0 + Atom 1.0 -> Items.

feedparser handles the messy reality (CDATA, missing dates, content:encoded,
namespaces); items carry raw_* fields verbatim so observations preserve what
the feed actually said at fetch time.
"""

from datetime import datetime, timezone

import feedparser

from ..model import Item, content_hash_for


def _utc_from_struct(st) -> str | None:
    if not st:
        return None
    try:
        dt = datetime(*st[:6], tzinfo=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return None


def parse(feed_bytes: bytes, source_name: str) -> list[Item]:
    parsed = feedparser.parse(feed_bytes)
    items = []
    for e in parsed.entries:
        title = e.get("title") or ""
        link = e.get("link") or ""
        # summary: content:encoded wins over description
        summary = ""
        if e.get("content"):
            summary = e["content"][0].get("value", "")
        summary = summary or e.get("summary", "")
        published = _utc_from_struct(e.get("published_parsed") or e.get("updated_parsed"))
        precision = "sec" if published else "crawl"
        lang = e.get("language") or None
        item = Item(
            kind="rss", url=link, title=title, summary=summary,
            lang=lang, published_utc=published, published_precision=precision,
            source=source_name, raw_url=link, raw_title=title,
            raw_summary=summary[:2000],
        )
        item.content_hash = content_hash_for(item)
        item.title_norm = title
        items.append(item)
    return items
