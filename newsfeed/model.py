"""newsfeed.model — Item dataclass, URL canonicalization, hashing, SimHash."""

import hashlib
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from . import config

# SimHash shingles over title + first 200 chars of summary
SHINGLE_K = 5
SIMHASH_BITS = 64


@dataclass
class Item:
    kind: str                       # "rss" | "gdelt"
    url: str
    title: str
    summary: str = ""
    body: str | None = None         # NULL by design for GDELT-only items
    lang: str | None = None
    published_utc: str | None = None
    published_precision: str = "crawl"   # 'sec' | 'day' | 'crawl'
    source: str = ""
    raw_url: str = ""
    raw_title: str = ""
    raw_summary: str = ""
    seen_utc: str | None = None          # GDELT crawl time, never publish time
    content_hash: str = field(default="")
    title_norm: str = field(default="")


_TRAILING_SLASH_RE = re.compile(r"/+$")
_WS_RE = re.compile(r"\s+")
_PUNCT_EDGES_RE = re.compile(r"^[^\w]+|[^\w]+$")


def canonicalize_url(url: str) -> str:
    """Lowercase scheme+host, drop www., fragment, trailing slash; strip
    tracking params; sort remaining params. Returns '' if not http(s)."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return ""
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return ""
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = _TRAILING_SLASH_RE.sub("", parts.path) or "/"
    q = [(k, v.rstrip("/")) for k, v in parse_qsl(parts.query, keep_blank_values=True)
         if k.lower() not in config.STRIP_PARAMS
         and not k.lower().startswith("utm_")]
    q.sort()
    query = urlencode(q)
    return urlunsplit((parts.scheme, host, path, query, ""))


def normalize_title(title: str) -> str:
    t = _WS_RE.sub(" ", (title or "").strip()).lower()
    return _PUNCT_EDGES_RE.sub("", t)


def content_hash_for(item: Item) -> str:
    """sha256 over canonical URL when present, else normalized title + day."""
    url = canonicalize_url(item.url or item.raw_url)
    if url:
        basis = url
    else:
        basis = (normalize_title(item.title) + "|" + (item.published_utc or "")[:10])
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def _shingles(text: str, k: int = SHINGLE_K) -> set[str]:
    words = re.findall(r"\w+", text.lower())
    if len(words) < k:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i:i + k]) for i in range(len(words) - k + 1)}


def simhash64(text: str) -> int:
    """64-bit SimHash over word shingles."""
    sh = _shingles(text)
    if not sh:
        return 0
    v = [0] * SIMHASH_BITS
    for s in sh:
        h = int.from_bytes(hashlib.sha1(s.encode("utf-8")).digest()[:8], "big")
        for b in range(SIMHASH_BITS):
            v[b] += 1 if (h >> b) & 1 else -1
    out = 0
    for b in range(SIMHASH_BITS):
        if v[b] > 0:
            out |= 1 << b
    return out


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def jaccard(a_text: str, b_text: str) -> float:
    a, b = _shingles(a_text), _shingles(b_text)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def simhash_text_for(item: Item) -> str:
    return (item.title or "") + " " + (item.summary or "")[:200]
