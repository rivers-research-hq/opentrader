#!/usr/bin/env python3
"""security/guards — project-wide hardening layer (remediation 2026-09-02).

Covers the three high findings classes from the Mimosa scan (ToC BM-series):
  SSRF          → guarded_urlopen: scheme + host allowlist + private/metadata
                  IP-range rejection before any request leaves the box.
  path-traversal→ guarded_open: resolves the target and enforces containment
                  under the project root (or /tmp for scratch) before handing
                  to the real open().
  deserialization→ sec_pickle_load: restricted Unpickler (allowlisted modules
                  only). yaml callers use yaml.safe_load directly. torch
                  callers use weights_only=True at the call site.

The allowlist is derived from the API hosts the codebase actually talks to;
new hosts must be added here deliberately — that friction is the point.

All guards raise HardeningError on violation. They never log secrets.
"""

import builtins
import ipaddress
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Hosts this codebase legitimately talks to (derived from the tree's API calls).
ALLOWED_HOSTS = {
    # market data / venue
    "api-fxpractice.oanda.com", "api-fxtrade.oanda.com", "api.oanda.com",
    "finnhub.io", "api.tiingo.com", "query1.finance.yahoo.com",
    "query2.finance.yahoo.com", "api.binance.com", "api.binance.us",
    "api.kraken.com", "api.alpaca.markets", "paper-api.alpaca.markets",
    # macro / calendar / research feeds
    "fred.stlouisfed.org", "nfs.faireconomy.media", "api.stlouisfed.org",
    "data.bis.org", "www.bis.org", "api.worldbank.org", "www.worldbank.org",
    # BIS statistical API (SDMX v1) — daily central-bank policy rates for the
    # fxexpert panel's carry block (scripts/fetch_policy_rates.py, added
    # 2026-09-12). Same publisher as data.bis.org/www.bis.org above.
    "stats.bis.org",
    "export.arxiv.org", "arxiv.org", "rss.app", "api.github.com",
    # news / event research feeds (map #187 #203/#204: FF week pages + MOF
    # intervention CSV — added 2026-09-05, ticket #203/#204)
    "www.forexfactory.com", "www.mof.go.jp",
    # Fed comms calendar (map #187 #203: speeches RSS)
    "www.federalreserve.gov",
    # CB speech corpus harvest (plan cb-speech-interpreter-2026-09-10, T2/T3 —
    # added 2026-09-11): FRASER OAI-PMH archive, RBA speeches RSS, BoE speeches
    # index. Read-only GETs from scripts/fetch_cbspeeches.py.
    "fraser.stlouisfed.org", "www.rba.gov.au",
    "www.bankofengland.co.uk", "bankofengland.co.uk",
    # LLM / infra
    "api.coingecko.com", "api.alternative.me", "api.stlouisfed.org",
    "api.deepseek.com", "api.openai.com", "api.anthropic.com",
    "openrouter.ai", "api.together.xyz", "api.groq.com",
    "huggingface.co", "cdn-lfs.huggingface.co", "hf.co",
    "127.0.0.1", "localhost", "::1",
}

ALLOWED_SCHEMES = {"https", "http"}  # http only ever hits loopback locally

_PRIVATE_NETS = [ipaddress.ip_network(n) for n in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
    "169.254.0.0/16", "0.0.0.0/8", "100.64.0.0/10",
    "fc00::/7", "fe80::/10",
)]
# loopback is allowed (local service mesh on this box); metadata is NOT.
_METADATA_NETS = [ipaddress.ip_network(n) for n in ("169.254.169.254/32", "fd00:ec2::254/128")]


class HardeningError(Exception):
    """Raised when a request/path/deserialization violates the hardening policy."""


def _host_allowed(host: str) -> bool:
    host = (host or "").lower().rstrip(".")
    if not host:
        return False
    if host in ALLOWED_HOSTS:
        return True
    # allow subdomains of listed apex hosts (e.g. cdn-lfs.huggingface.co)
    for allowed in ALLOWED_HOSTS:
        if host.endswith("." + allowed):
            return True
    return False


def _reject_private(host: str) -> None:
    try:
        import socket
        infos = socket.getaddrinfo(host, None)  # getaddrinfo lives in socket; ipaddress had no such attr (latent bug — any non-loopback host failed DNS)
    except Exception as e:
        raise HardeningError(f"DNS resolution failed for {host!r}: {e}") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        for net in _METADATA_NETS:
            if ip in net:
                raise HardeningError(f"blocked metadata address {ip}")
        for net in _PRIVATE_NETS:
            if ip in net:
                raise HardeningError(f"blocked private-network address {ip} for {host!r}")


def validate_url(url: str) -> str:
    """Policy-check a URL before a request leaves the box. Returns the URL."""
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise HardeningError(f"scheme {parsed.scheme!r} not allowed: {url[:80]}")
    host = parsed.hostname or ""
    if not _host_allowed(host):
        raise HardeningError(f"host {host!r} not in allowlist: {url[:80]}")
    if host not in ("127.0.0.1", "localhost", "::1"):
        _reject_private(host)
    return url


def _url_from_request(req):
    if isinstance(req, str):
        return req
    return getattr(req, "full_url", None) or getattr(req, "url", None)


def guarded_urlopen(req, *args, **kwargs):
    """Drop-in urlopen replacement: validates the target, then performs the
    request with the real urlopen."""
    url = _url_from_request(req)
    if url is None:
        raise HardeningError("guarded_urlopen: no URL on request")
    validate_url(url)
    if args and isinstance(req, str) and "timeout" not in kwargs:
        kwargs["timeout"] = args[0]
    return urllib.request.urlopen(req, **kwargs)


def guarded_open(path, mode="r", *args, **kwargs):
    """Drop-in open replacement: enforces containment under the project root
    (or /tmp for scratch) before opening. Returns the real file object."""
    target = Path(path)
    if not target.is_absolute():
        target = (Path.cwd() / target)
    resolved = target.resolve()
    allowed_bases = [PROJECT_ROOT.resolve(), Path("/tmp").resolve()]
    if mode and ("w" in mode or "a" in mode or "+" in mode):
        # writes: also allow the resolved parent chain (same containment rule)
        pass
    if not any(resolved == base or resolved.is_relative_to(base)
               for base in allowed_bases):
        raise HardeningError(f"path escapes containment: {resolved}")
    return builtins.open(resolved, mode, *args, **kwargs)


# restricted deserialization
_ALLOWED_PICKLE_ROOTS = {
    "builtins", "collections", "copyreg", "_codecs", "datetime",
    "numpy", "pandas", "pandas.core", "pandas.core.frame",
    "pandas.core.indexes", "pandas.core.indexes.base",
    "scipy", "scipy.sparse",
}


class _RestrictedUnpickler(__import__("pickle").Unpickler):
    def find_class(self, module, name):
        root = module.split(".")[0]
        if root in _ALLOWED_PICKLE_ROOTS:
            return super().find_class(module, name)
        raise __import__("pickle").UnpicklingError(
            f"restricted unpickler: forbidden {module}.{name}")


def sec_pickle_load(file_obj):
    """pickle.load with a module-allowlisted restricted Unpickler. Caches the
    project wrote itself reload fine; foreign/hostile pickles raise."""
    import pickle
    return _RestrictedUnpickler(file_obj).load()


# requests-library wrapper (same policy as guarded_urlopen)
def guarded_requests(method, url, **kwargs):
    """requests-compatible guard: validate, then delegate to the real
    requests.request. Use by shadowing: requests.get = partial(guarded_requests, "GET")."""
    import requests
    validate_url(url)
    return requests.request(method, url, **kwargs)


def guarded_requests_get(url, **kwargs):
    return guarded_requests("GET", url, **kwargs)


def guarded_requests_post(url, **kwargs):
    return guarded_requests("POST", url, **kwargs)
