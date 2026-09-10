# Data store declarations (writer-per-path, per repo audit gate)

## data/newsfeed/newsfeed.db — item-level news store (SQLite/WAL)

| | |
|---|---|
| Purpose | Point-in-time news archive: items (current view) + observations (append-only fetch history) + sources + runs. Full-text via FTS5 external-content index. |
| Sole writer | `newsfeed/store.py` (via `python -m newsfeed {fetch,backfill,add-source}`) |
| Readers | `python -m newsfeed search/stats`, dashboard (future) |
| Writers by path | `data/newsfeed/newsfeed.db` ← store.py only; `data/newsfeed/` dir ← config.ensure_dir |
| Sources | RSS 2.0 / Atom 1.0 feeds + GDELT DOC 2.0 artlist (90-day backfill, 3-day chunks) |
| Feeds fetched | `sources` table is the registry (`python -m newsfeed list-sources`) |
| Git | `data/newsfeed/` is gitignored (rebuildable: backfill is idempotent by content_hash) |
| Point-in-time | `observations.fetched_at_utc` is the no-lookahead clock; PIT query in `store.pit_query()` |
| Dedup | `newsfeed/dedup.py` — canonical URL → shared-shingle → Jaccard ≥0.70, union-find, ±36h window; separate idempotent pass |
| Stands alone | No imports from trading code; egress via own `newsfeed/net.py` guard (SSRF, allowlist, rate limits) |
