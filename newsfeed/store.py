"""newsfeed.store — SOLE WRITER for newsfeed.db.

Schema: items (fast mutable current view), observations (append-only —
the point-in-time archive; never updated), runs (fetch bookkeeping),
sources (feed registry + conditional-GET state). FTS5 external-content
index kept in sync by triggers inside the same transaction as the upsert.
"""

import sqlite3
from pathlib import Path

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS sources (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,                -- 'rss' | 'gdelt'
  name TEXT NOT NULL,
  url_or_query TEXT NOT NULL,
  tier INTEGER NOT NULL DEFAULT 5,
  enabled INTEGER NOT NULL DEFAULT 1,
  etag TEXT, last_modified TEXT, last_fetched_utc TEXT,
  rate_limit_s REAL,
  config_json TEXT
);

CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY,
  source_id INTEGER NOT NULL REFERENCES sources(id),
  started_utc TEXT NOT NULL, finished_utc TEXT,
  status TEXT NOT NULL,
  n_new INTEGER, n_updated INTEGER, n_unchanged INTEGER, error TEXT
);

CREATE TABLE IF NOT EXISTS items (
  id INTEGER PRIMARY KEY,
  content_hash TEXT NOT NULL UNIQUE,
  cluster_id INTEGER,
  is_canonical INTEGER NOT NULL DEFAULT 1,
  canonical_url TEXT,
  source_id INTEGER NOT NULL REFERENCES sources(id),
  title TEXT, summary TEXT, body TEXT,
  lang TEXT,
  published_utc TEXT, published_precision TEXT NOT NULL DEFAULT 'crawl',
  first_seen_utc TEXT NOT NULL, last_seen_utc TEXT NOT NULL,
  dedup_version INTEGER NOT NULL DEFAULT 0,
  simhash TEXT
);
CREATE INDEX IF NOT EXISTS idx_items_published ON items(published_utc);
CREATE INDEX IF NOT EXISTS idx_items_cluster ON items(cluster_id);
CREATE INDEX IF NOT EXISTS idx_items_hash ON items(content_hash);

CREATE TABLE IF NOT EXISTS observations (
  id INTEGER PRIMARY KEY,
  item_id INTEGER NOT NULL REFERENCES items(id),
  source_id INTEGER NOT NULL REFERENCES sources(id),
  run_id INTEGER REFERENCES runs(id),
  fetched_at_utc TEXT NOT NULL,
  raw_url TEXT, raw_title TEXT, raw_summary TEXT,
  published_utc TEXT
);
CREATE INDEX IF NOT EXISTS idx_obs_item ON observations(item_id);
CREATE INDEX IF NOT EXISTS idx_obs_fetched ON observations(fetched_at_utc);

CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(
  title, summary, body,
  content='items', content_rowid='id',
  tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS items_ai AFTER INSERT ON items BEGIN
  INSERT INTO items_fts(rowid, title, summary, body)
  VALUES (new.id, new.title, new.summary, new.body);
END;
CREATE TRIGGER IF NOT EXISTS items_ad AFTER DELETE ON items BEGIN
  INSERT INTO items_fts(items_fts, rowid, title, summary, body)
  VALUES ('delete', old.id, old.title, old.summary, old.body);
END;
CREATE TRIGGER IF NOT EXISTS items_au AFTER UPDATE ON items BEGIN
  INSERT INTO items_fts(items_fts, rowid, title, summary, body)
  VALUES ('delete', old.id, old.title, old.summary, old.body);
  INSERT INTO items_fts(rowid, title, summary, body)
  VALUES (new.id, new.title, new.summary, new.body);
END;
"""


def connect(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init_db(db_path: Path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = connect(db_path)
    con.executescript(SCHEMA)
    con.commit()
    con.close()


def upsert_items(con: sqlite3.Connection, rows: list[dict], run_id: int,
                 source_id: int) -> tuple[int, int, int]:
    """rows: dicts with content_hash/title/summary/body/lang/published_utc/
    published_precision/raw_url/raw_title/raw_summary/url/simhash.
    New content_hash -> new item + observation. Existing hash -> new
    observation only (append-only archive; items.last_seen updated)."""
    n_new = n_updated = n_unchanged = 0
    now = con.execute("SELECT strftime('%Y-%m-%dT%H:%M:%fZ','now')").fetchone()[0]
    for r in rows:
        cur = con.execute("SELECT id FROM items WHERE content_hash = ?",
                          [r["content_hash"]]).fetchone()
        if cur is None:
            cur = con.execute(
                """INSERT INTO items (content_hash, canonical_url, source_id,
                   title, summary, body, lang, published_utc,
                   published_precision, first_seen_utc, last_seen_utc, simhash)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                [r["content_hash"], r.get("canonical_url"), source_id,
                 r["title"], r["summary"], r.get("body"), r.get("lang"),
                 r.get("published_utc"), r.get("published_precision", "crawl"),
                 now, now, r.get("simhash")])
            item_id = cur.lastrowid
            n_new += 1
        else:
            item_id = cur["id"]
            con.execute("UPDATE items SET last_seen_utc = ? WHERE id = ?", [now, item_id])
            n_unchanged += 1
        con.execute(
            """INSERT INTO observations (item_id, source_id, run_id,
               fetched_at_utc, raw_url, raw_title, raw_summary, published_utc)
               VALUES (?,?,?,?,?,?,?,?)""",
            [item_id, source_id, run_id, now, r.get("raw_url"),
             r.get("raw_title"), r.get("raw_summary"), r.get("published_utc")])
        n_updated += 0  # items never mutate text; observations carry versions
    con.commit()
    return n_new, n_unchanged, n_updated


PIT_SQL = """
SELECT i.id, i.title, i.canonical_url, i.published_utc, i.lang,
       o.raw_title, o.raw_summary, o.raw_url, o.fetched_at_utc
FROM items i
JOIN (
  SELECT item_id, id AS oid,
         ROW_NUMBER() OVER (PARTITION BY item_id
                            ORDER BY fetched_at_utc DESC, id DESC) rn
  FROM observations WHERE fetched_at_utc <= :as_of
) l ON l.item_id = i.id AND l.rn = 1
JOIN observations o ON o.id = l.oid
WHERE (:as_of >= i.first_seen_utc)
ORDER BY i.published_utc DESC NULLS LAST
"""


def pit_query(con: sqlite3.Connection, as_of_utc: str, limit: int = 200) -> list[dict]:
    rows = con.execute(PIT_SQL + " LIMIT ?", [as_of_utc, limit]).fetchall()
    return [dict(r) for r in rows]


SEARCH_SQL = """
SELECT i.id, i.title, i.canonical_url, i.published_utc, i.lang,
       snippet(items_fts, 0, '<b>', '</b>', '…', 12) AS snip,
       bm25(items_fts) AS rank
FROM items_fts
JOIN items i ON i.id = items_fts.rowid
WHERE items_fts MATCH :q
  AND (:since IS NULL OR i.published_utc >= :since)
  AND (:until IS NULL OR i.published_utc <= :until)
ORDER BY rank LIMIT :limit
"""


def search(con: sqlite3.Connection, query: str, since: str | None = None,
           until: str | None = None, limit: int = 50) -> list[dict]:
    rows = con.execute(SEARCH_SQL, {"q": query, "since": since, "until": until,
                                    "limit": limit}).fetchall()
    return [dict(r) for r in rows]


def add_source(con: sqlite3.Connection, kind: str, name: str, url_or_query: str,
               tier: int = 5, rate_limit_s: float | None = None,
               config_json: str | None = None) -> int:
    cur = con.execute(
        "INSERT INTO sources (kind, name, url_or_query, tier, enabled, rate_limit_s, config_json)"
        " VALUES (?,?,?,?,1,?,?)",
        [kind, name, url_or_query, tier, rate_limit_s, config_json])
    con.commit()
    return cur.lastrowid


def list_sources(con: sqlite3.Connection, enabled_only: bool = False) -> list[dict]:
    q = "SELECT * FROM sources" + (" WHERE enabled = 1" if enabled_only else "")
    return [dict(r) for r in con.execute(q).fetchall()]


def start_run(con: sqlite3.Connection, source_id: int) -> int:
    now = con.execute("SELECT strftime('%Y-%m-%dT%H:%M:%fZ','now')").fetchone()[0]
    cur = con.execute("INSERT INTO runs (source_id, started_utc, status) VALUES (?,?, 'running')",
                      [source_id, now])
    con.commit()
    return cur.lastrowid


def finish_run(con: sqlite3.Connection, run_id: int, status: str, n_new: int,
               n_unchanged: int, error: str | None = None):
    now = con.execute("SELECT strftime('%Y-%m-%dT%H:%M:%fZ','now')").fetchone()[0]
    con.execute("UPDATE runs SET finished_utc = ?, status = ?, n_new = ?, "
                "n_unchanged = ?, error = ? WHERE id = ?",
                [now, status, n_new, n_unchanged, error, run_id])
    con.commit()
