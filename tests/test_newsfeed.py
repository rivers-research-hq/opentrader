"""newsfeed package tests — zero network, tmpdir DBs, fixtures replayed."""

import json
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FIX = Path(__file__).resolve().parent / "fixtures" / "newsfeed"


class TestModel(unittest.TestCase):
    def test_canonicalize_strips_tracking(self):
        from newsfeed.model import canonicalize_url
        url = "https://WWW.Example.com/a/b?utm_source=x&id=42&fbclid=z&b=2&a=1/"
        self.assertEqual(canonicalize_url(url),
                         "https://example.com/a/b?a=1&b=2&id=42")

    def test_canonicalize_rejects_non_http(self):
        from newsfeed.model import canonicalize_url
        self.assertEqual(canonicalize_url("ftp://example.com/x"), "")
        self.assertEqual(canonicalize_url("file:///etc/passwd"), "")

    def test_same_article_different_tracking_same_hash(self):
        from newsfeed.model import Item, content_hash_for
        a = Item(kind="rss", url="https://x.com/s?utm_source=a", title="Fed cuts rates")
        b = Item(kind="rss", url="https://x.com/s?utm_source=b", title="Fed cuts rates")
        self.assertEqual(content_hash_for(a), content_hash_for(b))

    def test_near_dupe_shingle_share(self):
        # SimHash Hamming<=3 does NOT hold at news scale (1-word change flips
        # 5/20 shingles -> hamming ~13); the load-bearing candidate signal at
        # this scale is a shared 4-word shingle (dedup layer 2)
        from newsfeed.model import _shingles
        t1 = "Fed cuts rates by 25bp and signals more cuts are coming this year amid soft inflation data"
        t2 = "Fed cuts rates by 25bp and signals more cuts are coming next year amid soft inflation data"
        t3 = "Completely unrelated text about wheat harvests in Saskatchewan and canola seed exports"
        s1, s2, s3 = _shingles(t1, 4), _shingles(t2, 4), _shingles(t3, 4)
        self.assertTrue(s1 & s2)                       # near-dupe shares shingles
        self.assertGreater(len(s1 & s2) / len(s1 | s2), 0.5)  # high jaccard
        self.assertEqual(len(s1 & s3), 0)              # unrelated shares none


class TestRssParsing(unittest.TestCase):
    def test_rss20(self):
        from newsfeed.sources import rss as rss_src
        items = rss_src.parse((FIX / "rss20.xml").read_bytes(), "RSS Test Feed")
        self.assertEqual(len(items), 2)
        self.assertIn("rate path", items[0].title)
        self.assertIn("Full", items[0].summary)  # content:encoded wins
        self.assertEqual(items[0].published_utc, "2026-09-09T10:00:00Z")
        self.assertEqual(items[0].published_precision, "sec")

    def test_atom10(self):
        from newsfeed.sources import rss as rss_src
        items = rss_src.parse((FIX / "atom10.xml").read_bytes(), "Atom Test Feed")
        self.assertEqual(len(items), 1)
        self.assertIn("MOF", items[0].title)

    def test_messy(self):
        from newsfeed.sources import rss as rss_src
        items = rss_src.parse((FIX / "messy.xml").read_bytes(), "Messy")
        self.assertEqual(len(items), 3)
        self.assertTrue(all(it.content_hash for it in items))
        self.assertTrue(any(not it.title for it in items))  # no-title item tolerated


class TestGdeltParsing(unittest.TestCase):
    def test_sample(self):
        from newsfeed.sources import gdelt as gdelt_src
        arts = json.loads((FIX / "gdelt_sample.json").read_text())["articles"]
        items = gdelt_src.to_items(arts, "gdelt")
        self.assertEqual(len(items), 5)  # the real probe returned 5 (fixture is ground truth)
        self.assertIsNone(items[0].body)          # body NULL by design
        self.assertEqual(items[0].published_precision, "crawl")
        self.assertEqual(items[0].published_utc, "2026-09-09T01:00:00Z")
        self.assertIsNotNone(items[0].seen_utc)


class TestStorePit(unittest.TestCase):
    def _con(self):
        import tempfile
        from newsfeed import store
        d = Path(tempfile.mkdtemp(prefix="nf_pit_"))
        db = d / "test.db"
        store.init_db(db)
        return store.connect(db), d

    def test_point_in_time(self):
        from newsfeed import store
        con, _ = self._con()
        sid = store.add_source(con, "rss", "test", "http://localhost/feed")
        T1 = "2026-09-09T10:00:00Z"
        con.execute(
            """INSERT INTO items (content_hash, source_id, title, summary,
               first_seen_utc, last_seen_utc) VALUES ('h1', ?, 'v1 title', 's', ?, ?)""",
            [sid, T1, T1])
        iid = con.execute("SELECT id FROM items").fetchone()["id"]
        con.execute(
            """INSERT INTO observations (item_id, source_id, fetched_at_utc,
               raw_title, raw_summary) VALUES (?, ?, ?, 'v1 title', 's')""", [iid, sid, T1])
        T2 = "2026-09-09T12:00:00Z"
        con.execute("UPDATE items SET title = 'v2 title (edited)' WHERE id = ?", [iid])
        con.execute(
            """INSERT INTO observations (item_id, source_id, fetched_at_utc,
               raw_title, raw_summary) VALUES (?, ?, ?, 'v2 title (edited)', 's')""",
            [iid, sid, T2])
        con.commit()
        rows_t15 = store.pit_query(con, "2026-09-09T11:00:00Z")
        rows_t3 = store.pit_query(con, "2026-09-09T13:00:00Z")
        self.assertEqual(len(rows_t15), 1)
        self.assertEqual(rows_t15[0]["raw_title"], "v1 title")   # T1 version
        self.assertEqual(rows_t3[0]["raw_title"], "v2 title (edited)")

    def test_fts_search(self):
        from newsfeed import store
        con, _ = self._con()
        sid = store.add_source(con, "rss", "test", "http://localhost/feed")
        con.execute(
            """INSERT INTO items (content_hash, source_id, title, summary,
               published_utc, first_seen_utc, last_seen_utc)
               VALUES ('h-a', ?, 'ECB holds rates', 's', '2026-09-01T00:00:00Z', ?, ?)""",
            [sid, "2026-09-01T00:00:00Z", "2026-09-01T00:00:00Z"])
        con.execute(
            """INSERT INTO items (content_hash, source_id, title, summary,
               published_utc, first_seen_utc, last_seen_utc)
               VALUES ('h-b', ?, 'Yen slides', 's', '2026-09-02T00:00:00Z', ?, ?)""",
            [sid, "2026-09-02T00:00:00Z", "2026-09-02T00:00:00Z"])
        con.commit()
        rows = store.search(con, "ECB")
        self.assertEqual(len(rows), 1)
        self.assertIn("ECB", rows[0]["title"])
        rows = store.search(con, "yen", since="2026-09-02T00:00:00Z")
        self.assertEqual(len(rows), 1)


class TestDedup(unittest.TestCase):
    def _seed(self, con):
        from newsfeed import store
        sid = store.add_source(con, "gdelt", "g", "query")
        now = "2026-09-09T10:00:00Z"
        arts = json.loads((FIX / "syndicated.json").read_text())["articles"]
        from newsfeed.sources import gdelt as gdelt_src
        items = gdelt_src.to_items(arts, "g")
        for it, a in zip(items, arts):
            con.execute(
                """INSERT INTO items (content_hash, source_id, title, summary,
                   published_utc, first_seen_utc, last_seen_utc, simhash)
                   VALUES (?,?,?,?,?,?,?,?)""",
                [it.content_hash, sid, it.title, "", it.published_utc,
                 now, now, "0"])
        return sid

    def test_syndicated_pair_one_cluster(self):
        import tempfile
        from newsfeed import store, dedup as dedup_mod
        d = Path(tempfile.mkdtemp(prefix="nf_dd_"))
        db = d / "t.db"
        store.init_db(db)
        con = store.connect(db)
        self._seed(con)
        res = dedup_mod.run(con, dedup_version=1)
        self.assertEqual(res["duplicates"], 1)  # the two syndicated copies merge
        # re-run idempotent
        res2 = dedup_mod.run(con, dedup_version=1)
        self.assertEqual(res2["duplicates"], 1)
        canon = con.execute("SELECT COUNT(*) c FROM items WHERE is_canonical=1").fetchone()["c"]
        self.assertEqual(canon, 2)  # 3 items -> 2 clusters


class TestFailoverSafety(unittest.TestCase):
    def test_ssrf_guard_blocks_private(self):
        from newsfeed.net import fetch
        ok, err = fetch("http://127.0.0.1:8097/api/fx")
        self.assertFalse(ok)
        self.assertIn("egress blocked", err)
        ok, err = fetch("http://169.254.169.254/latest/meta-data")
        self.assertFalse(ok)
        self.assertIn("egress blocked", err)


if __name__ == "__main__":
    unittest.main()
