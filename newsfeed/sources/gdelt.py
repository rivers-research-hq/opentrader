"""newsfeed.sources.gdelt — GDELT DOC 2.0 artlist -> Items.

Confirmed live (2026-09-09 probe): GET
  https://api.gdeltproject.org/api/v2/doc/doc
    ?query=<url-encoded>&mode=artlist&maxrecords<=250&format=json
    [&timespan=3d | &startdatetime=YYYYMMDDHHMMSS&enddatetime=...]
Response: {"articles": [{"url", "url_mobile", "title", "seendate"
  (YYYYMMDDHHMMSS), "socialimage", "domain", "language", "sourcecountry"}]}
Rate limit: "one every 5 seconds" (enforced; 429 text says so verbatim).

Honest caveat: `seendate` is when GDELT SAW the article, not publication.
Items carry published_precision='crawl' and seen_utc separately so
downstream code can never treat a crawl time as a publish time.
"""

import json
import urllib.parse
from datetime import datetime, timedelta, timezone

from ..model import Item, content_hash_for
from .. import net

API = "https://api.gdeltproject.org/api/v2/doc/doc"


def _seendate_to_utc(raw: str) -> str | None:
    try:
        dt = datetime.strptime(raw, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return None


def fetch_artlist(query: str, timespan: str = "24h",
                  startdt: str | None = None, enddt: str | None = None,
                  maxrecords: int = 250, rate_s: float | None = None) -> tuple[bool, object]:
    """One DOC 2.0 artlist request. Returns (True, list[dict]) articles or
    (False, error-string). Respects net.rate limiting via net.fetch."""
    q = urllib.parse.quote(query)
    url = f"{API}?query={q}&mode=artlist&maxrecords={min(maxrecords, 250)}&format=json"
    if startdt and enddt:
        url += f"&startdatetime={startdt}&enddatetime={enddt}"
    else:
        url += f"&timespan={timespan}"
    ok, res = net.fetch(url, rate_s=rate_s or 5.0)
    if not ok:
        return False, res
    if res.get("status") == 304:
        return True, []
    try:
        d = json.loads(res["content"])
        return True, d.get("articles", [])
    except Exception as e:
        return False, f"gdelt parse failed: {e}"


def to_items(articles: list[dict], source_name: str) -> list[Item]:
    items = []
    for a in articles:
        item = Item(
            kind="gdelt", url=a.get("url", ""), title=a.get("title", ""),
            summary="", body=None,
            lang=a.get("language") or None,
            published_utc=_seendate_to_utc(a.get("seendate", "") or ""),
            published_precision="crawl",
            source=a.get("domain") or source_name,
            raw_url=a.get("url", ""), raw_title=a.get("title", ""),
            raw_summary="",
            seen_utc=_seendate_to_utc(a.get("seendate", "") or ""),
        )
        item.content_hash = content_hash_for(item)
        items.append(item)
    return items


def backfill_windows(days: int = 90, chunk_days: int = 3) -> list[tuple[str, str]]:
    """startdatetime/enddatetime pairs covering the last `days` days, oldest
    first (chunked under the 250-record cap)."""
    end = datetime.now(timezone.utc)
    out = []
    t = end - timedelta(days=days)
    while t < end:
        t2 = min(t + timedelta(days=chunk_days), end)
        out.append((t.strftime("%Y%m%d%H%M%S"), t2.strftime("%Y%m%d%H%M%S")))
        t = t2
    return out


