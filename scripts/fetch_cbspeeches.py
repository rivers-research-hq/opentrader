#!/usr/bin/env python3
"""fetch_cbspeeches — central-bank speech corpus harvesters (plan T2 + T3).

Spec: docs/agents/research/cb-speech-interpreter-plan-2026-09-10.md
  T2 — FRASER OAI-PMH harvester (MODS v3.5, resumptionToken paging, from=
       incremental, retry on HTTP 500) into the normalized schema.
  T3 — per-bank fetchers (RSS / HTML / API) into the same schema.

Normalized schema (plan §4, exactly these 11 top-level keys):
  {bank, doc_type, date, decision_vintage_date, speaker, role, title, text,
   source_url, harvest_ts}
`doc_type` ∈ {speech, minutes, transcript, report}.
Extra per-row diagnostics live under the non-schema key `_meta`.

Field semantics (decided 2026-09-11 — see the harvest status note):
  date                  — the document's own date: speech delivery date; FOMC
                          meeting END date for minutes.
  decision_vintage_date — when the text became PUBLICLY KNOWN (the
                          leakage-discipline date): == date for a speech read
                          from a podium, but the RELEASE date for minutes
                          (~3 weeks after the meeting). Falls back to `date`
                          when no release date is published.
  text                  — full official body text when the source is HTML.
                          Empty with `_meta.needs_text_extraction=true` when
                          the source is a scanned PDF (FRASER items, FOMC
                          transcripts) — that is T4's bounded job, not T2/T3.

Sources (2026-09-11 reachability, all via security.guards):
  fed_rss       www.federalreserve.gov/feeds/speeches.xml   VERIFIED 200
  fed_archive   www.federalreserve.gov/newsevents/speech/<year>-speeches.htm
                per-year index + full text; VERIFIED 2011→present (2010 and
                earlier 404 — pre-2011 Fed speeches are a FRASER-only gap)
  fed_minutes   www.federalreserve.gov/monetarypolicy/fomchistorical<year>.htm
                index → HTML minutes; VERIFIED 2007→present. Transcripts on
                those pages are PDF-only → left to T4.
  rba_rss       www.rba.gov.au/rss/rss-cb-speeches.xml      VERIFIED 200
  boe_api       www.bankofengland.co.uk/_api/News/RefreshPagedNewsList
                POST form API discovered in /scripts/boe.min.js; the public
                /speeches page renders 0 results server-side. VERIFIED 200.
  fraser_oai    fraser.stlouisfed.org/oai/  — BLOCKED from this host on
                2026-09-11: TCP+TLS handshake succeeds, then HTTP/2 resets
                (RST_STREAM INTERNAL_ERROR) and HTTP/1.1 returns zero bytes
                forever (0/12 attempts). The whole stlouisfed.org Akamai
                property is affected (fred.stlouisfed.org too). Code is
                implemented and parser-verified offline (`--selftest`); the
                live harvest is unverified until egress to that edge works.

TODO (DISCOVERY, plan T1 — deliberately not chased here): BIS CB speech
aggregate, ECB speeches, BoJ English speeches. See the status note.

Read-only toward the trading system: GETs/POSTs to public archives, writes
feed files under /home/mrc/opentrader-data/feeds/cbspeeches/ only. No orders,
no REAL-mode runs, no training.

Usage:
  python3 scripts/fetch_cbspeeches.py --selftest
  python3 scripts/fetch_cbspeeches.py --sources fed_rss,rba_rss,boe_api
  python3 scripts/fetch_cbspeeches.py                       # everything
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import date, datetime, timezone
from html import unescape
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from security.guards import guarded_requests_post, guarded_urlopen  # noqa: E402

PROJECT = Path(__file__).resolve().parent.parent
STORE = Path("/home/mrc/opentrader-data/feeds/cbspeeches")
CORPUS = STORE / "corpus.jsonl"

# browser UA mandatory on federalreserve.gov / forexfactory-style hosts (403 plain clients)
UA = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

SCHEMA_KEYS = ("bank", "doc_type", "date", "decision_vintage_date", "speaker",
               "role", "title", "text", "source_url", "harvest_ts")

FED_RSS = "https://www.federalreserve.gov/feeds/speeches.xml"
FED_YEAR_SPEECHES = "https://www.federalreserve.gov/newsevents/speech/{year}-speeches.htm"
FED_FOMC_YEAR = "https://www.federalreserve.gov/monetarypolicy/fomchistorical{year}.htm"
# fomchistorical<year>.htm 404s for the current year, so recent meetings come
# from the rolling calendar page (same fomcminutes<date>.htm targets).
FED_FOMC_CALENDARS = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
RBA_RSS = "https://www.rba.gov.au/rss/rss-cb-speeches.xml"
BOE_SPEECHES_PAGE = "https://www.bankofengland.co.uk/news/speeches"
BOE_NEWS_API = "https://www.bankofengland.co.uk/_api/News/RefreshPagedNewsList"
FRASER_OAI = "https://fraser.stlouisfed.org/oai/"


class FetchError(RuntimeError):
    pass


def now_ts() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _log(msg: str) -> None:
    print(msg, flush=True)


# --------------------------------------------------------------------------
# HTTP (all egress through security.guards; retry on 5xx + transient sockets)
# --------------------------------------------------------------------------

def http_get(url: str, timeout: int = 40, retries: int = 3, backoff: float = 1.5,
             allow_404: bool = False) -> str | None:
    """GET via guarded_urlopen with browser UA. Retries 5xx/timeouts.

    Returns None for a 404 when allow_404 (absent archive years are data, not
    errors). Raises FetchError otherwise.
    """
    last = None
    for attempt in range(1, max(1, retries) + 1):
        try:
            req = Request(url, headers=UA)
            with guarded_urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf8", "replace")
        except HTTPError as e:
            if e.code == 404 and allow_404:
                return None
            last = f"HTTP {e.code}"
            if e.code < 500 and e.code != 429:
                break  # non-retryable client error
        except (URLError, TimeoutError, OSError) as e:
            last = f"{type(e).__name__}: {e}"
        if attempt < retries:
            time.sleep(backoff * attempt)
    raise FetchError(f"GET {url[:110]} failed after {retries} attempts: {last}")


def http_post_form(url: str, fields, timeout: int = 40, retries: int = 3,
                   backoff: float = 1.5) -> str:
    """POST urlencoded form via guarded_requests_post (BoE news API)."""
    last = None
    for attempt in range(1, max(1, retries) + 1):
        try:
            hdrs = dict(UA)
            hdrs["X-Requested-With"] = "XMLHttpRequest"
            hdrs["Referer"] = BOE_SPEECHES_PAGE
            r = guarded_requests_post(url, data=list(fields), headers=hdrs, timeout=timeout)
            if r.status_code >= 500:
                last = f"HTTP {r.status_code}"
            else:
                r.raise_for_status()
                return r.text
        except Exception as e:  # requests exceptions + guards.HardeningError
            last = f"{type(e).__name__}: {e}"
        if attempt < retries:
            time.sleep(backoff * attempt)
    raise FetchError(f"POST {url[:110]} failed after {retries} attempts: {last}")


# --------------------------------------------------------------------------
# HTML / text helpers
# --------------------------------------------------------------------------

def html_to_text(fragment: str) -> str:
    """Strip markup to paragraphs; drops comments, script/style, entities."""
    h = re.sub(r"<!--.*?-->", " ", fragment, flags=re.S)
    h = re.sub(r"<(script|style|noscript)\b.*?</\1>", " ", h, flags=re.S | re.I)
    h = re.sub(r"<br\s*/?>", "\n", h, flags=re.I)
    h = re.sub(r"</(p|div|li|tr|h[1-6]|section|article|table|blockquote)\s*>", "\n\n", h, flags=re.I)
    h = re.sub(r"<(p|div|li|tr|h[1-6]|section|article|table|blockquote)\b[^>]*>", "\n", h, flags=re.I)
    h = re.sub(r"<[^>]+>", "", h)
    h = unescape(h).replace("\xa0", " ")
    h = re.sub(r"[ \t\r\f\v]+", " ", h)
    h = re.sub(r" *\n *", "\n", h)
    h = re.sub(r"\n{3,}", "\n\n", h)
    return h.strip()


def clean_text(s: str | None) -> str:
    if not s:
        return ""
    s = unescape(re.sub(r"\s+", " ", s)).strip()
    return s


_ROLE_PREFIXES = (
    "Vice Chair for Supervision", "Vice Chairman for Supervision",
    "First Vice President", "Senior Vice President", "Executive Vice President",
    "Vice Chair", "Vice Chairman", "Chairman", "Chairwoman", "Chair",
    "Deputy Governor", "Governor", "President", "Director", "Secretary",
    "Treasurer", "Assistant Secretary", "General Counsel", "Economist",
)


def split_role(speaker_line: str | None) -> tuple[str | None, str | None, str | None]:
    """'Governor Adriana D. Kugler' -> ('Adriana D. Kugler', 'Governor', None).

    Returns (speaker, role, affiliation). Longest role prefix wins, so
    'Vice Chair for Supervision X' never degrades to 'Vice Chair'. A trailing
    ', Federal Reserve Bank of ...' clause becomes the affiliation.
    """
    line = clean_text(speaker_line)
    if not line:
        return None, None, None
    affiliation = None
    m = re.match(r"^(.*?),\s*(Federal Reserve Bank of .+|Board of Governors.*)$", line)
    if m:
        line, affiliation = m.group(1).strip(), m.group(2).strip()
    for p in sorted(_ROLE_PREFIXES, key=len, reverse=True):
        if line.lower().startswith(p.lower() + " "):
            return line[len(p):].strip().rstrip(","), p, affiliation
    return line, None, affiliation


def norm_date(value: str | None) -> str | None:
    """Best-effort date normalization to YYYY-MM-DD from common formats."""
    if not value:
        return None
    v = clean_text(value)
    if not v:
        return None
    v = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", v, flags=re.I)
    v = v.replace("Sept ", "Sep ").replace("Sept.", "Sep.")
    try:  # ISO (with or without timezone) via fromisoformat
        return datetime.fromisoformat(v.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(v, fmt).date().isoformat()
        except ValueError:
            pass
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y", "%m/%d/%Y", "%B %Y", "%Y"):
        try:
            return datetime.strptime(v, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def make_row(bank: str, doc_type: str, doc_date: str | None, title: str | None,
             text: str | None, source_url: str, harvest_ts: str,
             speaker: str | None = None, role: str | None = None,
             vintage: str | None = None, **meta) -> dict:
    row = {
        "bank": bank,
        "doc_type": doc_type,
        "date": doc_date,
        "decision_vintage_date": vintage or doc_date,
        "speaker": speaker,
        "role": role,
        "title": clean_text(title) or None,
        "text": text or "",
        "source_url": source_url,
        "harvest_ts": harvest_ts,
    }
    meta["text_chars"] = len(row["text"])
    row["_meta"] = {k: v for k, v in meta.items() if v is not None}
    return row


# --------------------------------------------------------------------------
# Fed — RSS (live feed, recent window)
# --------------------------------------------------------------------------

def _rss_field(item: str, tag: str) -> str | None:
    m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", item, re.S)
    if not m:
        return None
    v = re.sub(r"^\s*<!\[CDATA\[|\]\]>\s*$", "", m.group(1).strip())
    return clean_text(v) or None


def fed_rss_rows(harvest_ts: str, fetch_text: bool = True, timeout: int = 40) -> list[dict]:
    xml = http_get(FED_RSS, timeout=timeout)
    rows = []
    for m in re.finditer(r"<item>(.*?)</item>", xml, re.S):
        item = m.group(1)
        link = _rss_field(item, "link")
        title = _rss_field(item, "title") or ""
        pub = _rss_field(item, "pubDate")
        desc = _rss_field(item, "description") or ""
        if not link:
            continue
        # RSS titles are 'Waller, The Economic Outlook and ...' → speaker = first token
        speaker_line, rest = (title.split(",", 1) + [""])[:2]
        if re.fullmatch(r"[A-Z][A-Za-z'\-]+", speaker_line or ""):
            speaker, role = speaker_line.strip(), None
            speech_title = rest.strip() or title
        else:
            speaker, role, speech_title = None, None, title
        # description 'Speech At Reuters NEXT Newsmaker Interview, Washington, D.C.'
        location = re.sub(r"^Speech\s+", "", desc).strip() or None
        doc_date = None
        if pub:
            try:
                doc_date = datetime.strptime(pub, "%a, %d %b %Y %H:%M:%S %Z").date().isoformat()
            except ValueError:
                doc_date = norm_date(pub)
        text, warn = "", None
        if fetch_text:
            try:
                body = fed_speech_body(http_get(link, timeout=timeout))
                if body:
                    text = body
                else:
                    warn = "no_body_extracted"
            except FetchError as e:
                warn = f"body_fetch_failed: {e}"
        rows.append(make_row("FED", "speech", doc_date, speech_title, text, link,
                             harvest_ts, speaker=speaker, role=role,
                             source="fed_rss", location=location, warning=warn))
    return rows


# --------------------------------------------------------------------------
# Fed — per-year speech archive 2011→present (full text; 2007-2010 not served)
# --------------------------------------------------------------------------

def fed_speech_body(html: str) -> str:
    """Extract the official body from a modern Board article page.

    Speeches: <div id="article"> → heading div (time/title/speaker/location) →
    body div (same col classes) → <div class='lastUpdate'>. The body is the LAST
    col-xs-12 col-sm-8 col-md-8 div before the lastUpdate marker.
    Minutes: <div id="article" class="…col-md-9"> → <h3>title</h3> → prose, with
    no inner body div, so the h3 block is cut instead.
    Both slices start on a '<' — slicing at an attribute name leaves a partial
    tag that tag-stripping would leave behind as literal text.
    """
    i = html.find('id="article"')
    if i < 0:
        return ""
    i = html.rfind("<", 0, i)
    j = html.find("lastUpdate", i)
    if j > i:
        j = html.rfind("<", i, j)
    seg = html[i:j] if j > i else html[i:]
    k = seg.rfind('<div class="col-xs-12 col-sm-8 col-md-8">')
    if k >= 0:
        seg = seg[k:]
    else:
        hm = re.search(r"</h3>", seg)
        if hm and hm.end() < 800:
            seg = seg[hm.end():]
    seg = re.sub(r'<a[^>]*id="back-top".*?</a>', " ", seg, flags=re.S)
    return html_to_text(seg)


def parse_fed_year_index(html: str, year: int) -> list[dict]:
    """Split a year index on its <time> rows → {date,url,title,speaker,location}."""
    start = html.find('class="row eventlist"')
    region = html[start:] if start >= 0 else html
    parts = re.split(r"<time>([^<]+)</time>", region)
    out = []
    for n in range(1, len(parts) - 1, 2):
        raw_date, chunk = parts[n], parts[n + 1]
        m = re.search(r'<a\s+href="(/newsevents/speech/[^"]+)"[^>]*>(.*?)</a>', chunk, re.S)
        if not m:
            continue
        url, title = m.group(1), re.sub(r"<[^>]+>", "", m.group(2))
        sp = re.search(r'<p class="news__speaker">(.*?)</p>', chunk, re.S)
        # location = the first <p> AFTER the speaker paragraph (the title <p> is
        # sometimes followed by a watch-live <p>, so anchoring on the speaker
        # line is what keeps this from grabbing the video link)
        loc = None
        if sp:
            lm = re.search(r"<p>(.*?)</p>", chunk[sp.end():], re.S)
            if lm:
                loc = clean_text(re.sub(r"<[^>]+>", "", lm.group(1)))
        speaker, role, affiliation = split_role(re.sub(r"<[^>]+>", "", sp.group(1))) if sp else (None, None, None)
        # board pages sometimes omit the speaker paragraph → fall back to URL slug
        if not speaker:
            sm = re.match(r"([a-z]+)(\d{8})", url.rsplit("/", 1)[-1])
            speaker = sm.group(1).capitalize() if sm else None
        # URL slug date is authoritative if the index date is malformed
        url_date = None
        um = re.search(r"(\d{8})", url.rsplit("/", 1)[-1])
        if um:
            try:
                url_date = datetime.strptime(um.group(1), "%Y%m%d").date().isoformat()
            except ValueError:
                url_date = None
        out.append({
            "date": norm_date(raw_date) or url_date,
            "url": "https://www.federalreserve.gov" + url,
            "title": clean_text(title),
            "speaker": speaker, "role": role, "affiliation": affiliation,
            "location": clean_text(loc) or None,
        })
    return out

def fed_archive_rows(harvest_ts: str, since_year: int, until_year: int,
                     per_year_limit: int = 0, timeout: int = 40,
                     pause: float = 0.25) -> tuple[list[dict], dict]:
    rows, stats = [], {"years_ok": [], "years_unavailable": [], "per_year": {}}
    for year in range(since_year, until_year + 1):
        try:
            html = http_get(FED_YEAR_SPEECHES.format(year=year), timeout=timeout, allow_404=True)
        except FetchError as e:
            stats["years_unavailable"].append({"year": year, "error": str(e)[:120]})
            continue
        if html is None:
            stats["years_unavailable"].append({"year": year, "error": "HTTP 404"})
            continue
        entries = parse_fed_year_index(html, year)
        if per_year_limit:
            entries = entries[:per_year_limit]
        ok = 0
        for e in entries:
            try:
                text = fed_speech_body(http_get(e["url"], timeout=timeout))
            except FetchError as ex:
                rows.append(make_row("FED", "speech", e["date"], e["title"], "", e["url"],
                                     harvest_ts, speaker=e["speaker"], role=e["role"],
                                     source="fed_archive", location=e["location"],
                                     affiliation=e["affiliation"],
                                     warning=f"body_fetch_failed: {ex}"))
                continue
            rows.append(make_row("FED", "speech", e["date"], e["title"], text, e["url"],
                                 harvest_ts, speaker=e["speaker"], role=e["role"],
                                 source="fed_archive", location=e["location"],
                                 affiliation=e["affiliation"],
                                 warning=None if text else "no_body_extracted"))
            ok += 1
            time.sleep(pause)
        stats["years_ok"].append(year)
        stats["per_year"][str(year)] = len(entries)
        _log(f"[cbspeeches] fed_archive {year}: {len(entries)} speeches ({ok} with text)")
    return rows, stats


# --------------------------------------------------------------------------
# Fed — FOMC minutes 2007→present (HTML only; transcripts are PDF → T4)
# --------------------------------------------------------------------------

_MINUTES_LINK_RE = re.compile(
    r'href="(?P<url>/(?:monetarypolicy/fomcminutes|fomc/minutes/)(?P<ymd>\d{8})\.htm)"')


def parse_fomc_year_index(html: str, year: int) -> list[dict]:
    """Meeting panels on fomchistorical<year>.htm.

    Anchored on the minutes LINK, not on the heading tag or the link text: three
    layouts are live and only the link pattern is common to all —
      2007       <h5>Jan 30-31 Meeting - 2007</h5> +
                 <p><a href="/fomc/minutes/20070131.htm">Minutes</a> (Released Feb 21, 2007)</p>
      2008-2010  <h5>…</h5> + <p>Minutes (Released Feb 20, 2008):<br/>
                 <a href="/monetarypolicy/fomcminutes20080130.htm">HTML</a> | PDF</p>
      2011+      <h5 class="panel-heading panel-heading--shaded">…</h5> + same
                 'Minutes (Released <date>):' paragraph with link text 'HTML'
    The heading carries a class attribute from 2011 on and the link text is never
    the word 'Minutes' after 2007 — matching on either silently yields 0 rows
    (measured 2026-09-11: 6 minutes for 2007, 0 for every year 2008-2020).
    """
    out, seen = [], set()
    for m in _MINUTES_LINK_RE.finditer(html):
        url, ymd = m.group("url"), m.group("ymd")
        if url in seen:
            continue
        try:
            meeting_date = datetime.strptime(ymd, "%Y%m%d").date().isoformat()
        except ValueError:
            continue
        # release date: the enclosing <p> is the reliable scope for all three
        # layouts ('(Released …)' sits before the link in 2008+, after it in 2007)
        pstart = html.rfind("<p", 0, m.start())
        pend = html.find("</p>", m.end())
        para = html[pstart:pend] if (pstart >= 0 and pend > m.end()) else ""
        rl = re.search(r"\(Released\s+([^)]+)\)", para, re.I) or \
            re.search(r"\(Released\s+([^)]+)\)", html[max(0, m.start() - 400):m.end() + 300], re.I)
        label = None
        for hm in re.finditer(r"<h[1-6][^>]*>([^<]*?[Mm]eeting[^<]*?)</h[1-6]>", html[:m.start()]):
            label = clean_text(hm.group(1))
        seen.add(url)
        out.append({
            "date": meeting_date,
            "vintage": norm_date(rl.group(1)) if rl else meeting_date,
            "url": "https://www.federalreserve.gov" + url,
            "title": f"Minutes of the Federal Open Market Committee, {label or meeting_date}",
            "released_raw": clean_text(rl.group(1)) if rl else None,
        })
    return out


def parse_fomc_calendars_index(html: str) -> list[dict]:
    """Rolling calendar page: fomc-meeting__minutes blocks carry the HTML
    minutes link plus '(Released <date>)' — the vintage date."""
    out = []
    for m in re.finditer(r'<div class="[^"]*fomc-meeting__minutes[^"]*">(.*?)</div>', html, re.S):
        block = m.group(1)
        mm = re.search(r'<a\s+href="(/monetarypolicy/fomcminutes(\d{8})\.htm)"', block)
        if not mm:
            continue
        url, ymd = mm.group(1), mm.group(2)
        rl = re.search(r"\(Released\s+([^)]+)\)", block, re.I)
        try:
            meeting_date = datetime.strptime(ymd, "%Y%m%d").date().isoformat()
        except ValueError:
            continue
        out.append({
            "date": meeting_date,
            "vintage": norm_date(rl.group(1)) if rl else meeting_date,
            "url": "https://www.federalreserve.gov" + url,
            "title": f"Minutes of the Federal Open Market Committee, {meeting_date}",
            "released_raw": clean_text(rl.group(1)) if rl else None,
        })
    return out


def fed_minutes_rows(harvest_ts: str, since_year: int, until_year: int,
                     timeout: int = 40, pause: float = 0.25,
                     limit: int = 0) -> tuple[list[dict], dict]:
    """Historical year pages (2007→last completed year) + the rolling calendar
    page (recent years). Deduped by minutes URL; transcripts on those pages are
    PDF-only and left to T4."""
    stats = {"per_year": {}, "years_unavailable": [], "routes": {}}
    entries: dict[str, dict] = {}
    for year in range(since_year, until_year + 1):
        try:
            html = http_get(FED_FOMC_YEAR.format(year=year), timeout=timeout, allow_404=True)
        except FetchError as e:
            stats["years_unavailable"].append({"year": year, "error": str(e)[:120]})
            continue
        if html is None:
            stats["years_unavailable"].append({"year": year, "error": "HTTP 404"})
            continue
        got = parse_fomc_year_index(html, year)
        stats["per_year"][str(year)] = len(got)
        for e in got:
            e["route"] = "fomchistorical"
            entries.setdefault(e["url"], e)
        _log(f"[cbspeeches] fed_minutes {year}: {len(got)} minutes (fomchistorical)")
    try:
        cal = http_get(FED_FOMC_CALENDARS, timeout=timeout)
        got = [e for e in parse_fomc_calendars_index(cal)
               if since_year <= int(e["date"][:4]) <= until_year]
        for e in got:
            e["route"] = "fomccalendars"
            entries.setdefault(e["url"], e)
        stats["routes"]["fomccalendars_entries"] = len(got)
        _log(f"[cbspeeches] fed_minutes: {len(got)} recent minutes from fomccalendars")
    except FetchError as e:
        stats["years_unavailable"].append({"route": "fomccalendars", "error": str(e)[:120]})

    stats["routes"]["unique_minutes"] = len(entries)
    rows = []
    for e in sorted(entries.values(), key=lambda x: x["date"], reverse=True):
        if limit and len(rows) >= limit:
            break
        text = ""
        try:
            text = fed_minutes_body(http_get(e["url"], timeout=timeout))
        except FetchError as ex:
            e["warning"] = f"body_fetch_failed: {ex}"
        rows.append(make_row("FED", "minutes", e["date"], e["title"], text, e["url"],
                             harvest_ts, vintage=e["vintage"], speaker=None, role=None,
                             source="fed_minutes", meeting_label=e["title"], route=e["route"],
                             release_date_raw=e["released_raw"],
                             warning=e.get("warning") or (None if text else "no_body_extracted")))
        time.sleep(pause)
    return rows, stats


def fed_minutes_body(html: str) -> str:
    """Modern Board layout (2011+) else the pre-2011 flat-HTML minutes page."""
    body = fed_speech_body(html)
    if body:
        return body
    txt = html_to_text(html)
    i = txt.find("Minutes of the Federal Open Market Committee")
    if i >= 0:
        txt = txt[i:]
    for end in ("Return to top", "Last Update:"):
        j = txt.rfind(end)
        if j > 500:
            txt = txt[:j]
    return txt.strip()


# --------------------------------------------------------------------------
# RBA — RSS 1.0 / RDF (items are <item rdf:about>, not bare <item>)
# --------------------------------------------------------------------------

def parse_rba_rdf(xml: str) -> list[dict]:
    out = []
    for m in re.finditer(r"<item\s+rdf:about=\"[^\"]*\">(.*?)</item>", xml, re.S):
        item = m.group(1)
        title = _rss_field(item, "title")
        link = _rss_field(item, "link")
        desc = _rss_field(item, "description")
        dcdate = None
        dm = re.search(r"<dc:date>([^<]+)</dc:date>", item)
        if dm:
            dcdate = norm_date(dm.group(1))
        name = rm = None
        nm = re.search(r"<cb:nameAsWritten>([^<]+)</cb:nameAsWritten>", item)
        if nm:
            name = clean_text(nm.group(1))
        rl = re.search(r"<cb:jobTitle>([^<]+)</cb:jobTitle>", item)
        if rl:
            rm = clean_text(rl.group(1))
        aff = re.search(r"<cb:affiliation>([^<]+)</cb:affiliation>", item)
        loc = re.search(r"<cb:locationAsWritten>([^<]+)</cb:locationAsWritten>", item)
        simple = re.search(r"<cb:simpleTitle>([^<]+)</cb:simpleTitle>", item)
        if not link:
            continue
        out.append({
            "date": dcdate, "url": link,
            "title": clean_text(simple.group(1) if simple else title),
            "speaker": name, "role": rm,
            "affiliation": clean_text(aff.group(1)) if aff else None,
            "location": clean_text(loc.group(1)) if loc else None,
            "summary": desc,
        })
    return out


def rba_body(html: str) -> str:
    """RBA speech pages: the article prose sits in <div id="content">."""
    i = html.find('id="content"')
    if i < 0:
        return ""
    i = html.rfind("<", 0, i)  # rewind to the start of the tag (mid-tag slices
    #                            leave a partial tag that survives tag-stripping)
    seg = html[i:]
    for end in ('id="footer"', 'class="page-footer"', "<footer", 'class="footnotes"'):
        j = seg.find(end, 200)
        if j > 0:
            seg = seg[:seg.rfind("<", 0, j)]
    return html_to_text(seg)


RBA_YEAR_INDEX = "https://www.rba.gov.au/speeches/{year}/"


def parse_rba_year_index(html: str) -> list[dict]:
    """RBA /speeches/<year>/ listing — schema.org microdata, one entry per
    speech. The feed at rss-cb-speeches.xml only ever carries the LATEST item
    (measured 2026-09-11: 1 item), so the year index is what gives RBA any
    history at all. Years run 1990→present; the plan scopes RBA to 2000→.

    Anchored on the 'rss-speech-item' class token rather than on the container
    tag or on the rss-speech-* helper classes: the container is <article> in
    recent years but <div> in the older ones (2015 has 50 entries and zero
    <article> tags), and the speaker helper classes gained author-name/
    author-position aliases over time. Splitting on the token keeps one entry
    per segment across all vintages.
    """
    out = []
    for seg in html.split("rss-speech-item")[1:]:
        lm = re.search(r'<a\s+href="(/speeches/\d{4}/[^"]+\.html)"[^>]*\sclass="rss-speech-html"', seg) \
            or re.search(r'<h3[^>]*>\s*<a\s+href="(/speeches/\d{4}/[^"]+\.html)"', seg, re.S) \
            or re.search(r'href="(/speeches/\d{4}/[^"]+\.html)"', seg)
        if not lm:
            continue
        tm = re.search(r'<span itemprop="headline">(.*?)</span>', seg, re.S)
        dm = re.search(r'<time[^>]*datetime="([^"]+)"', seg)
        sm = re.search(r'class="(?:author-name|rss-speech-speaker)[^"]*">(.*?)</strong>', seg, re.S)
        pm = re.search(r'class="(?:author-position|rss-speech-position)[^"]*">(.*?)</span>', seg, re.S)
        em = re.search(r'<span class="event-type">(.*?)</span>', seg, re.S)
        loc = re.search(r'<span class="location">(.*?)</span>', seg, re.S)
        out.append({
            "url": "https://www.rba.gov.au" + lm.group(1),
            "title": clean_text(re.sub(r"<[^>]+>", "", tm.group(1))) if tm else None,
            "date": norm_date(dm.group(1)) if dm else None,
            "speaker": clean_text(re.sub(r"<[^>]+>", "", sm.group(1))) if sm else None,
            "role": clean_text(re.sub(r"<[^>]+>", "", pm.group(1))) if pm else None,
            "event_type": clean_text(re.sub(r"<[^>]+>", "", em.group(1))) if em else None,
            "location": clean_text(re.sub(r"<[^>]+>", "", loc.group(1))) if loc else None,
        })
    return out


def rba_year_rows(harvest_ts: str, since_year: int, until_year: int,
                  limit_per_year: int = 0, timeout: int = 40, pause: float = 0.25,
                  fetch_text: bool = True) -> tuple[list[dict], dict]:
    rows, stats = [], {"per_year": {}, "years_unavailable": []}
    for year in range(since_year, until_year + 1):
        try:
            html = http_get(RBA_YEAR_INDEX.format(year=year), timeout=timeout, allow_404=True)
        except FetchError as e:
            stats["years_unavailable"].append({"year": year, "error": str(e)[:120]})
            continue
        if html is None:
            stats["years_unavailable"].append({"year": year, "error": "HTTP 404"})
            continue
        entries = parse_rba_year_index(html)
        if limit_per_year:
            entries = entries[:limit_per_year]
        ok = 0
        for e in entries:
            text = ""
            if fetch_text:
                try:
                    text = rba_body(http_get(e["url"], timeout=timeout))
                except FetchError:
                    pass
                time.sleep(pause)
            rows.append(make_row("RBA", "speech", e["date"], e["title"], text, e["url"],
                                 harvest_ts, speaker=e["speaker"], role=e["role"],
                                 source="rba_year_index", event_type=e["event_type"],
                                 location=e["location"],
                                 warning=None if text else "no_body_extracted"))
            ok += 1 if text else 0
        stats["per_year"][str(year)] = len(entries)
        _log(f"[cbspeeches] rba_year {year}: {len(entries)} speeches ({ok} with text)")
    return rows, stats


def rba_rows(harvest_ts: str, timeout: int = 40, fetch_text: bool = True) -> list[dict]:
    xml = http_get(RBA_RSS, timeout=timeout)
    rows = []
    for e in parse_rba_rdf(xml):
        text = ""
        if fetch_text:
            try:
                text = rba_body(http_get(e["url"], timeout=timeout))
            except FetchError:
                pass
        rows.append(make_row("RBA", "speech", e["date"], e["title"], text, e["url"],
                             harvest_ts, speaker=e["speaker"], role=e["role"],
                             source="rba_rss", location=e["location"],
                             affiliation=e["affiliation"], summary=e["summary"],
                             warning=None if text else "no_body_extracted"))
    return rows


# --------------------------------------------------------------------------
# BoE — /news/speeches is JS-rendered (0 server-side results); use the API
# the page's own JS calls: POST /_api/News/RefreshPagedNewsList
# --------------------------------------------------------------------------

def parse_boe_page_config(html: str) -> dict:
    """Read the data-source id / news-type GUIDs / page size off /news/speeches
    so the harvester never hardcodes ids that the site can rotate."""
    cfg = {}
    m = re.search(r'CP\.BOE\.NewsPageDataSourceID\s*=\s*"([^"]+)"', html)
    if m:
        cfg["Id"] = m.group(1)
    m = re.search(r'CP\.BOE\.NewsPageSize\s*=\s*"?(\d+)"?', html)
    if m:
        cfg["PageSize"] = int(m.group(1))
    m = re.search(r'CP\.BOE\.NewsTypes\s*=\s*\[([^\]]*)\]', html)
    if m:
        cfg["NewsTypes"] = re.findall(r'"([^"]+)"', m.group(1))
    return cfg


def parse_boe_results(html: str) -> list[dict]:
    out = []
    for m in re.finditer(r'<a\s+href="(/speech/[^"]+)"[^>]*class="release[^"]*"\s*>(.*?)</a>',
                         html, re.S):
        url, block = m.group(1), m.group(2)
        tm = re.search(r'<time[^>]*datetime="([^"]+)"[^>]*>(.*?)</time>', block, re.S)
        h3 = re.search(r'<h3[^>]*class="[^"]*\blist\b[^"]*"[^>]*>(.*?)</h3>', block, re.S)
        if not h3:
            h3 = re.search(r"<h3[^>]*>(.*?)</h3>", block, re.S)
        tag = re.search(r'<div class="release-tag">(.*?)</div>', block, re.S)
        speaker = None
        if tag:
            t = clean_text(re.sub(r"<[^>]+>", "", tag.group(1)))
            if "//" in t:
                speaker = t.split("//", 1)[1].strip()
        out.append({
            "date": norm_date(tm.group(1)) if tm else None,
            "url": "https://www.bankofengland.co.uk" + url,
            "title": re.sub(r"\s*-\s*speech.*$", "",
                            clean_text(re.sub(r"<[^>]+>", "", h3.group(1)))).strip(),
            "speaker": speaker,
            "kind": clean_text(re.sub(r"<[^>]+>", "", tag.group(1))).split("//")[0].strip().lower() if tag else None,
        })
    return out


def boe_detail_meta(html: str) -> dict:
    """Full title + published date from a BoE speech detail page. The list view
    truncates titles with '...', so the og:title here is authoritative."""
    out = {}
    m = re.search(r'<meta\s+property="og:title"\s+content="([^"]*)"', html)
    if m:
        t = unescape(m.group(1)).strip()
        t = re.sub(r"\s*\|\s*Bank of England\s*$", "", t).strip()
        # '… challenges - speech by Andrew Bailey' → '… challenges'
        t = re.sub(r"\s*[-–—]\s*(speech|remarks?|keynote|lecture|address|panel)\b.*$", "",
                   t, flags=re.I).strip()
        out["title"] = t or None
    m = re.search(r'<div class="published-date">(.*?)</div>', html, re.S)
    if m:
        out["date"] = norm_date(re.sub(r"Published on\s*", "", re.sub(r"<[^>]+>", " ", m.group(1))).strip())
    sp = re.search(r'itemprop="author"[^>]*>(.*?)<', html, re.S) or re.search(r'<span class="speaker">(.*?)</span>', html, re.S)
    if sp:
        out["speaker"] = clean_text(re.sub(r"<[^>]+>", "", sp.group(1))) or None
    return {k: v for k, v in out.items() if v}


def boe_body(html: str) -> str:
    """CMS wraps the prose between '<!-- Start HTML Snippet-->' and End marker."""
    i = html.find("Start HTML Snippet")
    if i >= 0:
        gt = html.find(">", i)  # skip the rest of the opening comment
        i = gt + 1 if gt > i else i
    j = html.find("End HTML Snippet", i + 1) if i >= 0 else -1
    if j > i:
        j = html.rfind("<!--", i, j)  # cut the closing comment too
    seg = html[i:j] if (i >= 0 and j > i) else (html[i:] if i >= 0 else html)
    k = seg.find('id="output"')
    if k >= 0:
        seg = seg[seg.rfind("<", 0, k):]  # rewind to the tag start
    return html_to_text(seg)


def boe_rows(harvest_ts: str, limit: int = 60, since: str | None = None,
             timeout: int = 40, pause: float = 0.25) -> tuple[list[dict], dict]:
    page = http_get(BOE_SPEECHES_PAGE, timeout=timeout)
    cfg = parse_boe_page_config(page)
    if not cfg.get("Id"):
        raise FetchError("BoE page config (NewsPageDataSourceID) not found — site layout changed")
    page_size = cfg.get("PageSize", 30)
    stats = {"total_reported": None, "pages": 0, "config": cfg}
    rows, seen, page_no = [], set(), 1
    while len(rows) < limit and page_no <= 60:
        fields = [("SearchTerm", ""), ("Id", cfg["Id"]), ("PageSize", str(page_size))]
        for n, guid in enumerate(cfg.get("NewsTypes", [])):
            fields.append((f"NewsTypes[{n}]", guid))
        fields += [("Page", str(page_no)), ("Direction", "1"),
                   ("Grid", "false"), ("InfiniteScrolling", "false")]
        raw = http_post_form(BOE_NEWS_API, fields, timeout=timeout)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as e:
            raise FetchError(f"BoE API returned non-JSON: {e}") from e
        results = payload.get("Results", "")
        if stats["total_reported"] is None:
            tm = re.search(r"resultCount[^>]*>\s*([\d,]+)\s*results", results)
            if tm:
                stats["total_reported"] = int(tm.group(1).replace(",", ""))
        batch = parse_boe_results(results)
        stats["pages"] += 1
        if not batch:
            break
        stop = False
        for e in batch:
            if e["kind"] and e["kind"] != "speech":
                continue
            if since and e["date"] and e["date"] < since:
                stop = True
                continue
            if e["url"] in seen:
                continue
            seen.add(e["url"])
            text, detail = "", {}
            try:
                page = http_get(e["url"], timeout=timeout)
                text = boe_body(page)
                detail = boe_detail_meta(page)
            except FetchError:
                pass
            rows.append(make_row("BOE", "speech", detail.get("date") or e["date"],
                                 detail.get("title") or e["title"], text, e["url"],
                                 harvest_ts, speaker=detail.get("speaker") or e["speaker"],
                                 role=None, source="boe_api",
                                 list_title=e["title"] if detail.get("title") else None,
                                 warning=None if text else "no_body_extracted"))
            time.sleep(pause)
            if len(rows) >= limit:
                break
        if stop or len(rows) >= limit:
            break
        page_no += 1
    _log(f"[cbspeeches] boe_api: {len(rows)} speeches over {stats['pages']} page(s) "
         f"(site reports {stats['total_reported']} total)")
    return rows, stats


# --------------------------------------------------------------------------
# T2 — FRASER OAI-PMH harvester (MODS v3.5)
# --------------------------------------------------------------------------

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _kids(el, name: str) -> list:
    return [c for c in el.iter() if _local(c.tag) == name]


def _text(el) -> str:
    return clean_text("".join(el.itertext())) if el is not None else ""


def classify_doc_type(title: str | None, genre: str | None, set_spec: str | None = None):
    """Return (doc_type, inferred). Explicit genre wins; otherwise title/set
    keywords; otherwise 'report' + inferred=True (never silently 'speech')."""
    g = (genre or "").lower()
    for key, val in (("transcript", "transcript"), ("minute", "minutes"), ("speech", "speech"),
                     ("report", "report"), ("statement", "report")):
        if key in g:
            return val, False
    s = " ".join(filter(None, [(title or "").lower(), (set_spec or "").lower()]))
    if "transcript" in s:
        return "transcript", True
    if "minutes" in s or re.search(r"\bminute", s):
        return "minutes", True
    if any(k in s for k in ("speech", "remarks", "address", "testimony", "lecture")):
        return "speech", True
    return "report", True


def parse_mods(mods_el, header_el) -> dict:
    """MODS v3.5 record → flat dict. Namespace-agnostic (local-name matching)
    so a MODS version bump or prefix change cannot silently zero the harvest."""
    title = None
    for ti in _kids(mods_el, "titleInfo"):
        if (ti.get("type") or "") == "alternative":
            continue
        parts = [_text(_kids(ti, "title")[0]) if _kids(ti, "title") else ""]
        if _kids(ti, "subTitle"):
            parts.append(_text(_kids(ti, "subTitle")[0]))
        cand = ": ".join(p for p in parts if p)
        if cand:
            title = cand
            break
    speaker = role = None
    for nm in _kids(mods_el, "name"):
        if (nm.get("type") or "personal") != "personal":
            continue
        nps = [_text(x) for x in _kids(nm, "namePart") if (x.get("type") in (None, "family", "given"))]
        nps = [x for x in nps if x]
        # FRASER uses 'Bernanke, Ben S.' in a single untyped namePart
        if not nps and _kids(nm, "namePart"):
            nps = [_text(_kids(nm, "namePart")[0])]
        if not nps:
            continue
        speaker = nps[0] if len(nps) == 1 else f"{nps[-1]}, {' '.join(nps[:-1])}"
        rts = [_text(x) for x in _kids(nm, "roleTerm")]
        role = next((x for x in rts if x), None)
        if speaker:
            break
    doc_date = None
    for oi in _kids(mods_el, "originInfo"):
        for k in ("dateIssued", "dateCreated", "dateOther"):
            for d in _kids(oi, k):
                doc_date = norm_date(_text(d))
                if doc_date:
                    break
            if doc_date:
                break
        if doc_date:
            break
    genre = next((_text(g) for g in _kids(mods_el, "genre") if _text(g)), None)
    abstract = next((_text(a) for a in _kids(mods_el, "abstract") if _text(a)), None)
    pdf_url = landing = None
    urls = []
    for u in _kids(mods_el, "url"):
        href = clean_text(u.text or "")
        if not href:
            continue
        urls.append(href)
        access = (u.get("access") or "").lower()
        note = (u.get("note") or "").lower()
        if access == "raw object" or note == "raw object":
            pdf_url = pdf_url or href
        elif (u.get("usage") or "") == "primary display":
            landing = landing or href
    if not landing:
        for ident in _kids(mods_el, "identifier"):
            if (ident.get("type") or "").lower() in ("uri", "url") and clean_text(ident.text or ""):
                landing = clean_text(ident.text)
                break
    ident = _text(_kids(header_el, "identifier")[0]) if _kids(header_el, "identifier") else None
    set_spec = next((_text(s) for s in _kids(header_el, "setSpec") if _text(s)), None)
    datestamp = _text(_kids(header_el, "datestamp")[0]) if _kids(header_el, "datestamp") else None
    return {
        "title": title, "speaker": speaker, "role": role, "date": doc_date,
        "genre": genre, "abstract": abstract, "pdf_url": pdf_url, "landing": landing,
        "urls": urls, "identifier": ident, "set_spec": set_spec, "datestamp": datestamp,
        "subjects": [x for x in (_text(s) for s in _kids(mods_el, "topic")) if x][:12],
    }


def parse_oai_list_records(xml: str) -> tuple[list[dict], str | None, str | None]:
    """→ (records, resumption_token, error). Handles OAI error envelopes."""
    try:
        root = ET.fromstring(xml.encode("utf8"))
    except ET.ParseError as e:
        return [], None, f"XMLParseError: {e}"
    err = [c for c in root.iter() if _local(c.tag) == "error"]
    if err:
        return [], None, f"OAI error {err[0].get('code')}: {_text(err[0])[:200]}"
    records = []
    for rec in (c for c in root.iter() if _local(c.tag) == "record"):
        header = next((c for c in rec if _local(c.tag) == "header"), None)
        meta = next((c for c in rec if _local(c.tag) == "metadata"), None)
        mods = next((c for c in meta.iter() if _local(c.tag) == "mods"), None) if meta is not None else None
        if header is None:
            continue
        status = header.get("status")
        if mods is None or status == "deleted":
            # deleted / header-only record — surfaced so the caller can count it,
            # never emitted into the corpus
            ident = next((_text(x) for x in _kids(header, "identifier") if _text(x)), None)
            records.append({"identifier": ident, "header_status": status or "no_metadata",
                            "deleted": True})
            continue
        row = parse_mods(mods, header)
        if status:
            row["header_status"] = status
        records.append(row)
    token = None
    for tok in (c for c in root.iter() if _local(c.tag) == "resumptionToken"):
        token = clean_text("".join(tok.itertext())) or None
    return records, token, None


def fraser_oai_request(verb: str, params: dict, timeout: int, retries: int) -> str:
    q = {"verb": verb}
    q.update({k: v for k, v in params.items() if v not in (None, "")})
    return http_get(FRASER_OAI + "?" + urlencode(q), timeout=timeout, retries=retries)


def fraser_rows(harvest_ts: str, since: str | None, until: str | None,
                sets: list[str] | None, max_pages: int, timeout: int,
                retries: int) -> tuple[list[dict], dict]:
    """ListRecords with resumptionToken paging + from=/until= incremental.

    Sets: ListSets advertises only author:* but unlisted theme:* setSpecs work
    as filters (plan §3). Set names could not be re-verified 2026-09-11 (host
    unreachable), so they are caller-supplied via --fraser-set rather than
    hardcoded; with no set we harvest broadly and classify by MODS genre.
    """
    stats = {"pages": 0, "records": 0, "errors": [], "sets": sets or [],
             "since": since, "until": until, "reachable": False}
    try:
        ident = fraser_oai_request("Identify", {}, timeout, retries)
        stats["reachable"] = True
        repo = re.search(r"<repositoryName>(.*?)</repositoryName>", ident, re.S)
        stats["repository"] = clean_text(repo.group(1)) if repo else None
        _log(f"[cbspeeches] fraser_oai Identify OK: {stats.get('repository')}")
    except FetchError as e:
        stats["errors"].append(f"Identify failed: {e}")
        _log(f"[cbspeeches] fraser_oai UNREACHABLE: {e}")
        return [], stats

    token = None
    rows = []
    for page in range(1, max_pages + 1):
        params = {} if token else {"set": (sets or [None])[0] if sets else None,
                                   "metadataPrefix": "mods", "from": since, "until": until}
        if token:
            params = {"resumptionToken": token}
        try:
            xml = fraser_oai_request("ListRecords", params, timeout, retries)
        except FetchError as e:
            stats["errors"].append(f"page {page}: {e}")
            _log(f"[cbspeeches] fraser_oai page {page} failed: {e}")
            break
        records, token, err = parse_oai_list_records(xml)
        if err:
            stats["errors"].append(f"page {page}: {err}")
            _log(f"[cbspeeches] fraser_oai page {page} parse error: {err}")
            break
        stats["pages"] += 1
        stats["records"] += len(records)
        for r in records:
            if r.get("deleted") or r.get("header_status"):  # deleted record
                continue
            doc_type, inferred = classify_doc_type(r["title"], r["genre"], r["set_spec"])
            url = r["landing"] or (f"https://fraser.stlouisfed.org/oai/?verb=GetRecord&identifier={r['identifier']}"
                                   if r["identifier"] else "")
            rows.append(make_row(
                "FED", doc_type, r["date"], r["title"], r["abstract"] or "", url,
                harvest_ts, speaker=r["speaker"], role=r["role"],
                source="fraser_oai", doc_id=r["identifier"], set_spec=r["set_spec"],
                mods_genre=r["genre"], pdf_url=r["pdf_url"], subjects=r["subjects"],
                datestamp=r["datestamp"], doc_type_inferred=inferred,
                needs_text_extraction=not (r["abstract"] or ""),
            ))
        _log(f"[cbspeeches] fraser_oai page {page}: {len(records)} records "
             f"(token={'yes' if token else 'none'})")
        if not token:
            break
        time.sleep(0.3)
    return rows, stats


# --------------------------------------------------------------------------
# Corpus writer (dedup + per-bank dirs + single normalized JSONL)
# --------------------------------------------------------------------------

def row_key(row: dict) -> tuple:
    return (row.get("bank"), row.get("doc_type"), row.get("source_url"))


def load_seen() -> tuple[set, int]:
    seen = set()
    n = 0
    if CORPUS.exists():
        with CORPUS.open(encoding="utf8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                n += 1
                try:
                    seen.add(row_key(json.loads(line)))
                except json.JSONDecodeError:
                    continue
    return seen, n


def write_corpus(rows_by_bank: dict, stats: dict) -> dict:
    STORE.mkdir(parents=True, exist_ok=True)
    seen, before = load_seen()
    written, dupes = [], 0
    for bank, rows in rows_by_bank.items():
        bank_dir = STORE / bank.lower()
        bank_dir.mkdir(parents=True, exist_ok=True)
        bank_added = 0
        for row in rows:
            k = row_key(row)
            if k in seen or not row.get("source_url"):
                dupes += 1
                continue
            seen.add(k)
            written.append(row)
            bank_added += 1
        if bank_added:
            with (bank_dir / "corpus.jsonl").open("a", encoding="utf8") as fh:
                for row in written[-bank_added:]:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        (bank_dir / "manifest.json").write_text(json.dumps({
            "bank": bank, "harvest_ts": now_ts(), "rows_this_run": len(rows),
            "rows_new": bank_added, "stats": stats.get(bank, {}),
        }, indent=1, ensure_ascii=False), encoding="utf8")
    if written:
        with CORPUS.open("a", encoding="utf8") as fh:
            for row in written:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    manifest = {
        "harvest_ts": now_ts(),
        "corpus": str(CORPUS),
        "rows_before": before, "rows_new": len(written), "duplicates_skipped": dupes,
        "rows_total": before + len(written),
        "by_bank_new": {b: sum(1 for r in written if r["bank"] == b) for b in sorted({r["bank"] for r in written})},
        "by_source_new": {s: sum(1 for r in written if r["_meta"].get("source") == s)
                          for s in sorted({r["_meta"].get("source", "?") for r in written})},
        "by_doc_type_new": {d: sum(1 for r in written if r["doc_type"] == d) for d in sorted({r["doc_type"] for r in written})},
        "sources": stats,
    }
    (STORE / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf8")
    return manifest


# --------------------------------------------------------------------------
# Offline self-test (parsers only — FRASER's live endpoint is unreachable)
# --------------------------------------------------------------------------

_FRASER_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
 <responseDate>2026-09-11T12:00:00Z</responseDate>
 <request verb="ListRecords">https://fraser.stlouisfed.org/oai/</request>
 <ListRecords>
  <record>
   <header>
    <identifier>oai:fraser.stlouisfed.org:item:22462</identifier>
    <datestamp>2009-05-14</datestamp>
    <setSpec>theme:fed-speeches</setSpec>
   </header>
   <metadata>
    <mods:mods xmlns:mods="http://www.loc.gov/mods/v3" version="3.5">
      <mods:titleInfo>
        <mods:title>Reflections on the Financial Crisis</mods:title>
        <mods:subTitle>Remarks at the Federal Reserve Bank of Atlanta</mods:subTitle>
      </mods:titleInfo>
      <mods:name type="personal">
        <mods:namePart>Bernanke, Ben S.</mods:namePart>
        <mods:role><mods:roleTerm type="text">Chairman</mods:roleTerm></mods:role>
      </mods:name>
      <mods:typeOfResource>text</mods:typeOfResource>
      <mods:genre>Speeches</mods:genre>
      <mods:originInfo><mods:dateIssued encoding="w3cdtf">2009-04-14</mods:dateIssued></mods:originInfo>
      <mods:abstract>Remarks on the origins of the crisis and the policy response.</mods:abstract>
      <mods:subject><mods:topic>Financial crises</mods:topic></mods:subject>
      <mods:location>
        <mods:url access="raw object" usage="primary display">https://fraser.stlouisfed.org/files/docs/historical/bernanke/bernanke_20090414.pdf</mods:url>
        <mods:url usage="primary display">https://fraser.stlouisfed.org/title/reflections-22462</mods:url>
      </mods:location>
    </mods:mods>
   </metadata>
  </record>
  <record>
   <header status="deleted">
    <identifier>oai:fraser.stlouisfed.org:item:99999</identifier>
    <datestamp>2001-01-01</datestamp>
   </header>
  </record>
  <resumptionToken>abc123</resumptionToken>
 </ListRecords>
</OAI-PMH>"""

_FED_YEAR_FIXTURE = """<div class="row eventlist">
 <div class="row">
  <div class="col-xs-3 col-md-2 eventlist__time"><time>12/3/2024</time></div>
  <div class="col-xs-9 col-md-10 eventlist__event">
   <p><a href="/newsevents/speech/kugler20241203a.htm"><em>A Year in Review: A Tale of Two Supply Shocks</em></a></p>
   <p class="news__speaker">Governor Adriana D. Kugler</p>
   <p>At the Detroit Economic Club, Detroit, Michigan</p>
  </div>
 </div>
 <div class="row">
  <div class="col-xs-3 col-md-2 eventlist__time"><time>11/14/2024</time></div>
  <div class="col-xs-9 col-md-10 eventlist__event">
   <p><a href="/newsevents/speech/williams20241114a.htm">Some Title</a></p>
   <p class="news__speaker">President John C. Williams, Federal Reserve Bank of New York</p>
   <p>At New York</p>
  </div>
 </div>
</div>"""

_FOMC_YEAR_FIXTURE = """<div class="panel-heading"><h5>January 30-31 Meeting - 2007</h5></div>
<div class="panel-body">
 <p><a href="/fomc/minutes/20070131.htm">Minutes</a> (Released Feb 21, 2007)</p>
 <p><a href="/monetarypolicy/files/FOMC20070131meeting.pdf">Transcript (982 KB PDF)</a></p>
</div>
<div class="panel-heading"><h5>March 20-21 Meeting - 2007</h5></div>
<div class="panel-body">
 <p><a href="/fomc/minutes/20070321.htm">Minutes</a> (Released Apr 11, 2007)</p>
</div>"""

# 2008-2010 layout: <h5>, and the link text is 'HTML' with the release date in
# the same <p> BEFORE the link
_FOMC_YEAR_FIXTURE_2008 = """<div class="panel panel-default">
 <h5 class="panel-heading panel-heading--shaded">January 29-30 Meeting - 2008</h5>
 <div class="row divided-row"><div class="col-xs-12 col-md-6">
  <p>Minutes (Released Feb 20, 2008):
    <br /><a href="/monetarypolicy/fomcminutes20080130.htm">HTML</a> | <a href="/monetarypolicy/files/fomcminutes20080130.pdf">364 KB PDF</a>
  </p>
 </div></div>
</div>
<h3>2008</h3>
<div class="panel panel-default">
 <h5 class="panel-heading panel-heading--shaded">March 18 Meeting - 2008</h5>
 <p>Minutes (Released Apr 08, 2008):<br><a href="/monetarypolicy/fomcminutes20080318.htm">HTML</a></p>
</div>"""

_BOE_RESULTS_FIXTURE = """<div class="release-result"><p id="resultCount" aria-hidden="true">
  1531 results
</p></div>
<div class="col3">
 <a href="/speech/2026/september/andrew-bailey-keynote-speech-at-lse-trium-anniversary-conference" class="release release-speech " >
  <div class="release-tag-wrap"><div class="release-tag">Speech // Andrew Bailey</div></div>
  <div class="release-content"><div class="release-copy"><div class="release-meta">
   <time class="release-date" itemprop="datePublished" datetime="2026-09-04">04 September 2026</time>
  </div><h3 itemprop="name" class="grid-view exclude-navigation">The institutional form of...</h3>
  <h3 itemprop="name" class="list exclude-navigation">The institutional form of independent central banks - speech at LSE</h3>
  </div></div>
 </a>
</div>"""

_RBA_FIXTURE = """<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
 xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:cb="http://www.cbwiki.net/wiki/index.php/Specification_1.2/"
 xmlns="http://purl.org/rss/1.0/">
<item rdf:about="https://www.rba.gov.au/speeches/2026/sp-so-2026-08-25.html">
 <link>https://www.rba.gov.au/speeches/2026/sp-so-2026-08-25.html</link>
 <title>The Road to Ample</title>
 <dc:date>2026-08-25T10:14:00+10:00</dc:date>
 <cb:speech rdf:parseType="Resource">
  <cb:simpleTitle>The Road to Ample - Towards a Demand-driven Liquidity Regime</cb:simpleTitle>
  <cb:person rdf:parseType="Resource">
   <cb:nameAsWritten>David Jacobs</cb:nameAsWritten>
   <cb:role rdf:parseType="Resource"><cb:jobTitle>Head of Domestic Markets</cb:jobTitle></cb:role>
  </cb:person>
 </cb:speech>
</item>
</rdf:RDF>"""


_RBA_YEAR_FIXTURE = """<article id="sp-ag-2025-12-16" itemscope itemtype="https://schema.org/PublicationIssue" class="item event-category-speeches event-type-speech speech rss-speech-item y2025 jones ag
	">
	<h3 class="title rss-speech-title">
	<a href="/speeches/2025/sp-ag-2025-12-16.html" class="rss-speech-html" itemprop="url">
		<span itemprop="headline">Resilience, Innovation and the Future of the Payments System</span>
	</a>
	</h3>
	<div class="meta">
		<span class="date rss-speech-date" itemprop="datePublished">
			<time class="datetime" itemprop="datePublished" datetime="2025-12-16T09:15+11:00">
				16&nbsp;December 2025</time>
		</span>
		<span class="event-type">Speech</span>
		<span class="location">Sydney</span>
	</div>
	<p class="content" itemprop="author">
		<strong class="author-name rss-speech-speaker">Ellis Connolly</strong>,
		<span class="author-position rss-speech-position">Head of Payments Policy Department</span>
	</p>
</article>"""


def selftest() -> int:
    """Offline proof that the parsers/extractors work. Live FRASER is
    unreachable from this host, so its parsing is verified against the fixture
    above (modelled on OAI-PMH 2.0 + MODS 3.5, NOT a captured response)."""
    fails = []

    def check(name, cond, detail=""):
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}{'' if cond else ' — ' + str(detail)}")
        if not cond:
            fails.append(name)

    print("== FRASER OAI-PMH / MODS ==")
    recs, token, err = parse_oai_list_records(_FRASER_FIXTURE)
    check("no error envelope", err is None, err)
    check("2 records parsed (incl. deleted header)", len(recs) == 2, len(recs))
    check("resumptionToken read", token == "abc123", token)
    r = recs[0]
    check("identifier", r["identifier"] == "oai:fraser.stlouisfed.org:item:22462", r["identifier"])
    check("title + subTitle joined", r["title"] == "Reflections on the Financial Crisis: Remarks at the Federal Reserve Bank of Atlanta", r["title"])
    check("MODS dateIssued → date", r["date"] == "2009-04-14", r["date"])
    check("personal name", r["speaker"] == "Bernanke, Ben S.", r["speaker"])
    check("roleTerm → role", r["role"] == "Chairman", r["role"])
    check("raw-object PDF url", (r["pdf_url"] or "").endswith(".pdf"), r["pdf_url"])
    check("primary-display landing url", r["landing"] == "https://fraser.stlouisfed.org/title/reflections-22462", r["landing"])
    check("abstract captured", "policy response" in (r["abstract"] or ""), r["abstract"])
    check("genre-speech classification", classify_doc_type(r["title"], r["genre"], r["set_spec"]) == ("speech", False))
    check("no-genre fallback is NOT silently speech",
          classify_doc_type("Board memo", None, None) == ("report", True))
    check("deleted header flagged", recs[1].get("header_status") == "deleted", recs[1].get("header_status"))

    print("== schema ==")
    row = make_row("FED", "speech", "2024-12-03", "T", "body", "https://x", now_ts())
    check("exactly the 11 plan keys + _meta",
          set(row) == set(SCHEMA_KEYS) | {"_meta"}, sorted(set(row) ^ (set(SCHEMA_KEYS) | {"_meta"})))
    check("vintage defaults to date", row["decision_vintage_date"] == "2024-12-03")

    print("== Fed year index ==")
    fed = parse_fed_year_index(_FED_YEAR_FIXTURE, 2024)
    check("2 events", len(fed) == 2, len(fed))
    check("date parsed", fed[0]["date"] == "2024-12-03", fed[0]["date"])
    check("title parsed", fed[0]["title"] == "A Year in Review: A Tale of Two Supply Shocks", fed[0]["title"])
    check("role split from speaker line", (fed[0]["speaker"], fed[0]["role"]) == ("Adriana D. Kugler", "Governor"),
          (fed[0]["speaker"], fed[0]["role"]))
    check("bank affiliation split", (fed[1]["speaker"], fed[1]["role"], fed[1]["affiliation"]) ==
          ("John C. Williams", "President", "Federal Reserve Bank of New York"),
          (fed[1]["speaker"], fed[1]["role"], fed[1]["affiliation"]))
    check("absolute url", fed[0]["url"].startswith("https://www.federalreserve.gov/"), fed[0]["url"])

    print("== FOMC minutes index ==")
    mins = parse_fomc_year_index(_FOMC_YEAR_FIXTURE, 2007)
    check("2 minutes rows", len(mins) == 2, len(mins))
    check("meeting date from url", mins[0]["date"] == "2007-01-31", mins[0]["date"])
    check("release date → vintage", mins[0]["vintage"] == "2007-02-21", mins[0]["vintage"])
    check("title carries meeting label", "January 30-31 Meeting" in mins[0]["title"], mins[0]["title"])
    # 2008+ regressed to 0 rows once (heading class attr + 'HTML' link text)
    mins8 = parse_fomc_year_index(_FOMC_YEAR_FIXTURE_2008, 2008)
    check("2008 layout (h5 w/ class, 'HTML' link text) parses", len(mins8) == 2, len(mins8))
    check("2008 meeting date", mins8[0]["date"] == "2008-01-30", mins8[0]["date"])
    check("2008 release date (released-before-link)", mins8[0]["vintage"] == "2008-02-20", mins8[0]["vintage"])
    check("2008 label not the page <h3> year", "January 29-30 Meeting" in mins8[0]["title"], mins8[0]["title"])

    print("== BoE API fragment ==")
    boe = parse_boe_results(_BOE_RESULTS_FIXTURE)
    check("1 result", len(boe) == 1, len(boe))
    check("date from datetime attr", boe[0]["date"] == "2026-09-04", boe[0]["date"])
    check("speaker from release-tag", boe[0]["speaker"] == "Andrew Bailey", boe[0]["speaker"])
    check("kind = speech", boe[0]["kind"] == "speech", boe[0]["kind"])
    check("title de-suffixed", boe[0]["title"] == "The institutional form of independent central banks", boe[0]["title"])

    print("== RBA RSS 1.0/RDF ==")
    rba = parse_rba_rdf(_RBA_FIXTURE)
    check("1 item (rdf:about form)", len(rba) == 1, len(rba))
    check("cb:simpleTitle preferred", rba[0]["title"] == "The Road to Ample - Towards a Demand-driven Liquidity Regime", rba[0]["title"])
    check("cb:nameAsWritten → speaker", rba[0]["speaker"] == "David Jacobs", rba[0]["speaker"])
    check("cb:jobTitle → role", rba[0]["role"] == "Head of Domestic Markets", rba[0]["role"])
    check("dc:date → date", rba[0]["date"] == "2026-08-25", rba[0]["date"])

    print("== RBA year index ==")
    ry = parse_rba_year_index(_RBA_YEAR_FIXTURE)
    check("1 article (multi-line class attr)", len(ry) == 1, len(ry))
    check("headline → title", ry[0]["title"] == "Resilience, Innovation and the Future of the Payments System", ry[0]["title"])
    check("datetime → date", ry[0]["date"] == "2025-12-16", ry[0]["date"])
    check("author-name → speaker", ry[0]["speaker"] == "Ellis Connolly", ry[0]["speaker"])
    check("author-position → role", ry[0]["role"] == "Head of Payments Policy Department", ry[0]["role"])
    check("event-type captured", ry[0]["event_type"] == "Speech", ry[0]["event_type"])
    check("absolute url", ry[0]["url"] == "https://www.rba.gov.au/speeches/2025/sp-ag-2025-12-16.html", ry[0]["url"])

    print("== text extraction ==")
    txt = html_to_text("<p>One</p><p>Two&nbsp;&amp; three</p><!--x--><script>var a=1</script>")
    check("paragraphs + entities + script dropped", txt == "One\n\nTwo & three", repr(txt))
    modern = fed_speech_body(
        '<div id="article"><div class="heading col-xs-12 col-sm-8 col-md-8">'
        "<p class='article__time'>December 03, 2024</p><h3 class='title'><em>T</em></h3></div>"
        '<div class="col-xs-12 col-sm-8 col-md-8"><p>Thank you, Jason.</p></div>'
        '<div class="col-xs-12 col-sm-4 col-md-4"></div></div>'
        '<div class="lastUpdate" id="lastUpdate">Last Update: December 03, 2024</div>')
    check("modern Fed body = prose only", modern == "Thank you, Jason.", repr(modern))
    check("BoE snippet extraction",
          boe_body("<!-- Start HTML Snippet--><div class='page-content' id='content'>"
                   "<div id='output'><p>Speech</p><p>Body text.</p></div></div>"
                   "<!-- End HTML Snippet--><p>foot</p>").startswith("Speech"),
          repr(boe_body("<!-- Start HTML Snippet--><div id='output'><p>X</p></div><!-- End HTML Snippet-->")))
    check("norm_date variants",
          [norm_date(x) for x in ("2024-12-03", "December 03, 2024", "12/3/2024", "Feb 21, 2007", "3 September 2026")]
          == ["2024-12-03", "2024-12-03", "2024-12-03", "2007-02-21", "2026-09-03"],
          [norm_date(x) for x in ("2024-12-03", "December 03, 2024", "12/3/2024", "Feb 21, 2007", "3 September 2026")])

    print(f"\nselftest: {'ALL PASS' if not fails else str(len(fails)) + ' FAILED: ' + ', '.join(fails)}")
    return 0 if not fails else 1


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="Central-bank speech corpus harvesters (plan T2/T3).")
    ap.add_argument("--selftest", action="store_true", help="run offline parser tests and exit")
    ap.add_argument("--sources", default="fed_rss,fed_archive,fed_minutes,rba_rss,rba_year,boe_api,fraser_oai",
                    help="comma-separated subset of: fed_rss,fed_archive,fed_minutes,rba_rss,rba_year,boe_api,fraser_oai")
    ap.add_argument("--since-year", type=int, default=2007, help="earliest year (speeches/minutes/FRASER)")
    ap.add_argument("--until-year", type=int, default=datetime.now(timezone.utc).year)
    ap.add_argument("--fed-archive-since", type=int, default=2007,
                    help="first year to try on the Board per-year index (2011+ exists; earlier 404s)")
    ap.add_argument("--fed-speech-limit-per-year", type=int, default=0, help="0 = all")
    ap.add_argument("--minutes-limit-per-year", type=int, default=0, help="0 = all")
    ap.add_argument("--boe-limit", type=int, default=60)
    ap.add_argument("--rba-since-year", type=int, default=2000,
                    help="RBA year-index start (index runs 1990→; plan scopes RBA to 2000→)")
    ap.add_argument("--rba-limit-per-year", type=int, default=0, help="0 = all (~70/yr)")
    ap.add_argument("--boe-since", default=None, help="YYYY-MM-DD lower bound (client-side filter)")
    ap.add_argument("--fraser-since", default="2007-01-01", help="OAI-PMH from= (incremental)")
    ap.add_argument("--fraser-until", default=None)
    ap.add_argument("--fraser-set", action="append", default=None,
                    help="OAI setSpec filter (repeatable); unverified 2026-09-11")
    ap.add_argument("--fraser-max-pages", type=int, default=5)
    ap.add_argument("--fraser-timeout", type=int, default=20)
    ap.add_argument("--fraser-retries", type=int, default=2)
    ap.add_argument("--timeout", type=int, default=40)
    ap.add_argument("--no-text", action="store_true", help="metadata only, skip body fetches")
    ap.add_argument("--dry-run", action="store_true", help="harvest but do not write the corpus")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    harvest_ts = now_ts()
    wanted = [s.strip() for s in args.sources.split(",") if s.strip()]
    rows_by_bank: dict[str, list[dict]] = {}
    stats: dict[str, dict] = {}

    def add(rows: list[dict]) -> None:
        for r in rows:
            rows_by_bank.setdefault(r["bank"], []).append(r)

    if "fed_rss" in wanted:
        rows = fed_rss_rows(harvest_ts, fetch_text=not args.no_text, timeout=args.timeout)
        add(rows)
        stats["fed_rss"] = {"rows": len(rows)}
        _log(f"[cbspeeches] fed_rss: {len(rows)} rows")

    if "fed_archive" in wanted:
        rows, st = fed_archive_rows(harvest_ts, args.fed_archive_since, args.until_year,
                                    per_year_limit=args.fed_speech_limit_per_year,
                                    timeout=args.timeout)
        add(rows)
        stats["fed_archive"] = st | {"rows": len(rows)}

    if "fed_minutes" in wanted:
        rows, st = fed_minutes_rows(harvest_ts, args.since_year, args.until_year,
                                    timeout=args.timeout, limit=args.minutes_limit_per_year)
        add(rows)
        stats["fed_minutes"] = st | {"rows": len(rows)}

    if "rba_rss" in wanted:
        rows = rba_rows(harvest_ts, timeout=args.timeout, fetch_text=not args.no_text)
        add(rows)
        stats["rba_rss"] = {"rows": len(rows)}
        _log(f"[cbspeeches] rba_rss: {len(rows)} rows")

    if "rba_year" in wanted:
        rows, st = rba_year_rows(harvest_ts, args.rba_since_year, args.until_year,
                                 limit_per_year=args.rba_limit_per_year,
                                 timeout=args.timeout, fetch_text=not args.no_text)
        add(rows)
        stats["rba_year"] = st | {"rows": len(rows)}

    if "boe_api" in wanted:
        rows, st = boe_rows(harvest_ts, limit=args.boe_limit, since=args.boe_since, timeout=args.timeout)
        add(rows)
        stats["boe_api"] = st | {"rows": len(rows)}

    if "fraser_oai" in wanted:
        rows, st = fraser_rows(harvest_ts, args.fraser_since, args.fraser_until,
                               args.fraser_set, args.fraser_max_pages,
                               args.fraser_timeout, args.fraser_retries)
        add(rows)
        stats["fraser_oai"] = st | {"rows": len(rows)}
        stats["fraser_oai"]["host_reachable"] = st.get("reachable", False)
        if not st.get("reachable"):
            _log("[cbspeeches] NOTE: FRASER host unreachable from this box (see docstring) — "
                 "0 FRASER rows; parser verified via --selftest")

    total = sum(len(v) for v in rows_by_bank.values())
    _log(f"[cbspeeches] harvested {total} rows: "
         + ", ".join(f"{b}={len(v)}" for b, v in sorted(rows_by_bank.items())))

    if args.dry_run:
        _log("[cbspeeches] dry-run: corpus not written")
        print(json.dumps({k: v for k, v in stats.items()}, indent=1, default=str))
        return 0

    manifest = write_corpus(rows_by_bank, stats)
    _log(f"[cbspeeches] wrote {manifest['rows_new']} new rows "
         f"(dupes skipped {manifest['duplicates_skipped']}); corpus now {manifest['rows_total']} rows")
    _log(f"[cbspeeches] by_source_new={manifest['by_source_new']}")
    _log(f"[cbspeeches] by_doc_type_new={manifest['by_doc_type_new']}")
    _log(f"[cbspeeches] store={STORE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
