"""newsfeed — standalone item-level news store (v1 library, no HTTP).

Sources: RSS 2.0, Atom 1.0, GDELT DOC 2.0. Store: SQLite with an
append-only observations layer (point-in-time queries) and external-content
FTS5 search. Dedup: canonical URL -> SimHash -> shingle Jaccard, union-find
clustering. All egress through newsfeed.net (SSRF guard, conditional GET,
per-host rate limit).

This package is standalone: no imports from trading code, no writes to any
existing data/ path. Store declared in data/MANIFEST.json + docs/DATA.md.
"""

__version__ = "0.1.0"
