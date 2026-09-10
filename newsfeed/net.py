"""newsfeed.net — egress for the newsfeed package only.

Standalone port of the SSRF-guard idea (NOT an edit to security/guards.py —
widening the trading system's allowlist for an unrelated module would loosen
its egress policy). Adds: conditional GET (etag/last_modified, 304 honored),
per-host token bucket, retry with backoff + Retry-After, bounded timeout.
Network errors are returned as (False, reason) — never raised into callers.
"""

import ipaddress
import socket
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from . import config


def validate_url(url: str) -> str:
    """Scheme + host checks only (cheap). Raises ValueError on violation."""
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https"):
        raise ValueError(f"scheme not allowed: {parts.scheme!r}")
    if not parts.netloc:
        raise ValueError("no host")
    host = parts.hostname
    if not host:
        raise ValueError("no hostname")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return url  # hostname: DNS-checked at fetch time (rebinding)
    _reject_ip(ip)
    return url


def _reject_ip(ip):
    bad = (ip.is_private or ip.is_loopback or ip.is_link_local
           or ip.is_reserved or ip.is_multicast)
    if bad:
        raise ValueError(f"private/reserved address not allowed: {ip}")
    if ip.exploded.startswith("169.254.169.254"):
        raise ValueError("metadata endpoint not allowed")


def _resolve_and_check(host: str):
    for fam, _, _, _, sa in socket.getaddrinfo(host, None):
        ip = ipaddress.ip_address(sa[0])
        _reject_ip(ip)


class TokenBucket:
    """Per-host rate limiter."""

    def __init__(self):
        self._last = {}

    def wait(self, host: str, rate_s: float | None = None):
        rate = rate_s if rate_s is not None else config.DEFAULTS["rate_limit_s"].get(
            host, config.DEFAULTS["rate_limit_s"]["default"])
        last = self._last.get(host, 0.0)
        delta = time.time() - last
        if delta < rate:
            time.sleep(rate - delta)
        self._last[host] = time.time()


_bucket = TokenBucket()


def fetch(url: str, etag: str | None = None, last_modified: str | None = None,
          rate_s: float | None = None) -> tuple[bool, object]:
    """Fetch a URL with SSRF checks, conditional GET, rate limit, retries.
    Returns (True, dict) on any completed HTTP exchange (including 304) or
    (False, error-string). Never raises into the caller."""
    try:
        validate_url(url)
        host = urlsplit(url).hostname
        _resolve_and_check(host)
    except ValueError as e:
        return False, f"egress blocked: {e}"

    _bucket.wait(host, rate_s)
    headers = {"User-Agent": config.DEFAULTS["user_agent"]}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified

    attempts = config.DEFAULTS["retries"]
    delay = 1.0
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=config.DEFAULTS["timeout_s"]) as resp:
                if resp.status == 304:
                    return True, {"status": 304, "not_modified": True}
                content = resp.read()
                return True, {"status": resp.status, "content": content,
                              "etag": resp.headers.get("ETag"),
                              "last_modified": resp.headers.get("Last-Modified")}
        except urllib.error.HTTPError as e:
            if e.code == 304:
                return True, {"status": 304, "not_modified": True}
            if e.code == 429:
                ra = e.headers.get("Retry-After")
                wait = float(ra) if ra and ra.isdigit() else delay * 4
                time.sleep(min(wait, 120.0))
            elif e.code >= 500:
                time.sleep(delay)
                delay *= 2
            else:
                return False, f"http {e.code}: {e.reason}"
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last_err = str(e)
            if attempt < attempts - 1:
                time.sleep(delay)
                delay *= 2
                continue
            return False, f"network error: {last_err}"
    return False, "retries exhausted"
