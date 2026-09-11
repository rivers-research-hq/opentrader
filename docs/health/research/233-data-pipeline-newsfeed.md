# Data layer: newsfeed + event feeds + the FX accrual store (wayfinder #233)

Read-only assessment of `newsfeed/` (`store.py`, `dedup.py`, `sources/rss.py`, `sources/gdelt.py`,
`net.py`, `config.py`, `cli.py`, `__main__.py`, `model.py`), `scripts/fetch_event_feeds.py`,
`fetch_ff_upcoming.py`, `fetch_fred_cond.py`, `build_accrual_store.py`, `data/accrual`, and the
DuckDB store at `/home/mrc/opentrader-data`. No fetcher was run, no store was written, no service
was touched. Evidence is file reads plus read-only `sqlite3` / DuckDB `SELECT` queries against the
existing DBs.

Evidence labels: **VERIFIED** (seen in code or read out of a live artifact) · **READ-FROM-DOCS**
(project record: MANIFEST/DATA.md/issue text) · **CLAIMED** (asserted but not independently checked)
· **DERIVED** (arithmetic over a verified artifact, method stated).

---

## Scope

**In scope:** the three data substrates on the FX path — the item-level news store
(`data/newsfeed/newsfeed.db`), the accrual store (`/home/mrc/opentrader-data/store.duckdb` + its
Parquet mirrors + `manifest.json`), and the JSON feeds dir (`/home/mrc/opentrader-data/feeds/`);
the caches that seed them (`data/exog_cache.json`, `data/cache/ff_calendar.json`,
`data/cache/ff_history/releases_rows.json`, `data/fx_ledger.jsonl`); and how `fxexpert/data.py`
`build()` consumes the accrual store.

**Out of scope:** the crypto paper lane (AGENTS.md 2026-09-02); the OANDA adapter fork (ToC Q04);
lane execution internals; panel/model/training internals — covered by the sibling doc
`docs/health/research/232-fxexpert-alpha-loop.md`, cross-referenced here only at the store boundary.

**Path correction (ticket premise):** `data/accrual` **does not exist**. It is not on disk
(`find / -maxdepth 4 -name 'accrual*'` returns nothing beyond `scripts/build_accrual_store.py`), it
has never been a tracked path (`git log --all -- data/accrual` is empty), and the string
`data/accrual` appears nowhere in the repo (grep over all files, `.git` excluded). The accrual store
in reality is `/home/mrc/opentrader-data/{store.duckdb,*.parquet,manifest.json}`
(`scripts/build_accrual_store.py:67,344-347`). **VERIFIED.**

---

## Verified findings (file:line)

### 1. What is written where — three independent substrates

| Substrate | Location | Writer(s) | Evidence |
|---|---|---|---|
| **News item store** (SQLite/WAL) | `data/newsfeed/newsfeed.db` | `newsfeed/store.py` — declared "SOLE WRITER" | `newsfeed/store.py:1-7`; `docs/DATA.md:8` |
| **Accrual store** | `/home/mrc/opentrader-data/store.duckdb` + 10 `*.parquet` + `manifest.json` | **four** writers: `build_accrual_store.py` (full rebuild), `fetch_fred_cond.py` (exog), `strategies/fx_expert_lane.py` (bars), `scripts/fx_expand_universe.py` (bars) | `build_accrual_store.py:347,357-367`; `fetch_fred_cond.py:94-103`; `fx_expert_lane.py:102,118-121`; `fx_expand_universe.py:62` |
| **Feeds dir** (raw + normalized JSON) | `/home/mrc/opentrader-data/feeds/{mof_interventions,fed_speeches,fred_distillates,ff_upcoming,manifest}.json` | `fetch_event_feeds.py` (3 files + manifest), `fetch_ff_upcoming.py` (1 file) | `fetch_event_feeds.py:36,159,165,175,180`; `fetch_ff_upcoming.py:31,105-107` |

The store docstring states the design constraint "*the store is a CONSUMER of the ledger — never a
second writer*" and "*materialize datasets as zstd parquet (the durable artifacts; the duckdb file
is a convenience view layer over them)*" (`build_accrual_store.py:18,355-356`). **Both statements are
false as of 2026-09-10** — see D1/D2/D3 below.

`data/MANIFEST.json` declares **only** `data/newsfeed/newsfeed.db` (`data/MANIFEST.json:73-75`);
the accrual store, the feeds dir and the DuckDB file are declared nowhere in `data/MANIFEST.json`
or `docs/DATA.md` (grep for `accrual|opentrader-data|duckdb` in both returns no hit). That
contradicts the AGENTS.md STEP-ZERO rule that canonical locations are declared in
`data/MANIFEST.json`. **VERIFIED.**

### 2. Freshness — measured, not assumed (2026-09-10 ~20:55 UTC)

| Artifact | Bytes | Last write | Data span inside | Verdict |
|---|---|---|---|---|
| `store.duckdb` bars (1h) | — | store `mtime` 2026-09-09 21:26 CDT | 2008-01-01 → 2026-09-10 01:00, 6,796,973 rows | current |
| `store.duckdb` bars (1d) | — | " | 2008-09-25 → 2026-09-08 21:00, 289,351 rows, **58 pairs** | current |
| `store.duckdb` exog | — | " | 179,695 rows, 35 series | current-ish |
| `store.duckdb` **ledger** | — | frozen at build | **126 rows, max ts 2026-09-04 20:59** | **5.6 d stale** |
| `store.duckdb` **fills / txns** | — | frozen at build | fills 119, txns 429, max ts 2026-09-04 20:59 | **5.6 d stale** |
| `data/fx_ledger.jsonl` (source) | 188,965 | 2026-09-10 07:00 CDT | **1,003 lines**, latest `2026-09-10T11:56:44Z` | live |
| `bars.parquet` (durable mirror) | 40,095,635 | 2026-09-06 00:56 | 1,960,635 rows | **−5.1 M rows vs duckdb** |
| `exog.parquet` (durable mirror) | 185,093 | 2026-09-06 00:56 | 92,795 rows | **−86,900 rows vs duckdb** |
| `manifest.json` (store) | 527 | 2026-09-06 00:56 | counts = the **parquet** counts | **stale vs store.duckdb** |
| `feeds/ff_upcoming.json` | 56,210 | **2026-09-05 02:14** | 3 weeks from week of Sep 1 | **5 d stale, expiring** |
| `feeds/{mof,fed,fred}*.json` + feeds manifest | — | 2026-09-09 08:38-08:39 | manifest `fetched_at 2026-09-09T13:39Z` | 1.4 d stale |
| `data/newsfeed/newsfeed.db` | 5,959,680 | 2026-09-09 00:39 | items 5,500, newest `first_seen` 2026-09-09T05:38Z, newest `published_utc` 2026-09-09T05:00Z | **1.6 d stale** |
| `data/fx_expert/panel.npz` / `panel_meta.json` | 34.3 MB | 2026-09-09 21:26 | 289,351 rows, 2008-09-25 → **2026-09-08** | current (matches duckdb 1d bars) |

Store/DB counts and ranges: read-only DuckDB `SELECT` on `store.duckdb` (read_only=True) and
`sqlite3 file:...?mode=ro`. File sizes/mtimes: `ls -la`. Ledger line count: `wc -l
data/fx_ledger.jsonl` = 1003; newest ledger row read at `data/fx_ledger.jsonl:1003`
(`2026-09-10T11:56:44.666105887Z`, `EUR_USD` venue-reconciliation). **VERIFIED / DERIVED.**

**Freshness conclusion (the headline):** the store's *bar* path is fresh and the store's
*ledger/journal* path is frozen at the last full rebuild. The ledger table is **12.6 % of the
ledger** (126 / 1003 **DERIVED**) and has not moved in 5.6 days while the live ledger grew to today.
Nothing schedules `build_accrual_store.py`: grep across `~/.config/systemd/user/`, `*.py`, `*.js`,
`*.md` finds no invoker — the only references are in a `.mimosa/reports/` review artifact.
`crontab -l` is **not readable** in this session (`You (mrc) are not allowed to access to (crontab)
because of pam configuration`), so a system crontab entry cannot be excluded. **VERIFIED** (with that
caveat stated).

### 3. The newsfeed store — schema and the raw/canonical split

| Fact | Evidence |
|---|---|
| 4 tables: `sources`, `runs`, `items` (mutable current view), `observations` (append-only) + FTS5 external-content index with 3 triggers | `newsfeed/store.py:12-85` |
| `items` 5,500 rows / `observations` 8,000 rows → 2,500 repeat observations, consistent with append-only design | read-only `sqlite3` COUNT |
| **`canonical_url` is populated on 0 of 5,500 rows** | read-only `sqlite3`: `SELECT COUNT(canonical_url), COUNT(*) FROM items` → `0|5500`; ingest always writes `"canonical_url": None` at `cli.py:62,82,137` |
| `is_canonical=1` → 4,199 rows; of those **1,257 have `cluster_id IS NULL`** (never passed through dedup) | read-only `sqlite3` GROUP BY |
| `dedup_version`: 1,257 rows at version 0 / 4,243 rows at version 1 | read-only `sqlite3` GROUP BY |
| Only **one** source is live: all 5,500 items are `source_id=1` (`gdelt-fx`, tier 3, query `(dollar OR euro OR yen OR inflation OR "central bank")`). `source_id=2` (`dailyfx` RSS, `https://www.dailyfx.com/feeds/market-news`, tier 4) has **0 items and `last_fetched_utc` NULL** | read-only `sqlite3` on `sources` + `items` |
| `runs`: 2 `ok` (n_new 2746 + 758) and **2 stuck at `status='running'` with NULL `finished_utc`** (started 2026-09-09T04:50:14 / 04:50:32) | read-only `sqlite3` on `runs` |
| 1,996 items have `first_seen_utc` **before** the first `ok` run started (05:00:44) → ingested by a process that never recorded a finished run | read-only `sqlite3` COUNT + `runs` |
| `journal_mode=wal` (persisted in the file); `connect()` sets `foreign_keys` only — no `busy_timeout` is set, so the effective wait is the Python `sqlite3.connect` default | `store.py:88-92`; `PRAGMA journal_mode` → `wal` |
| `upsert_items` commits **per call** (one transaction per fetch of a whole feed, FTS triggers inside it) | `store.py:103-138` (commit at :137) |
| No code path ever moves a run out of `running` except `finish_run` | `store.py:198-212`; grep for a reaper finds none |

### 4. Canonical-vs-raw dedup — the design, and what actually ran

Design (`newsfeed/dedup.py:1-9,32-114`, `docs/DATA.md:15`): three layers, cheapest first —
(1) exact canonical-URL match, (2) SimHash Hamming ≤ 3, (3) word 5-gram Jaccard ≥ 0.70 within a
±36 h window — union-find into clusters; canonical pick = earliest `published_utc`, tie-break source
tier, then longest text; non-canonical rows are **kept** with `cluster_id` + `is_canonical=0`;
separate idempotent pass, never inline in ingest.

What is true in the code:

- Layer 1 is **dead code in practice**: it indexes `items.canonical_url` (`dedup.py:51-57`) — a column
  that is 100 % NULL (above). URL-level identity is instead enforced indirectly by
  `content_hash TEXT NOT NULL UNIQUE` on `items` (`store.py:38`) where the hash is
  `sha256(canonicalize_url(url))` (`model.py:65-72`), so a repeat of the *same* URL becomes a second
  `observations` row, not a duplicate item. Cross-source URL dedup therefore never runs as designed.
- Layers 2/3 run off a **4-word shared shingle** candidate index, not SimHash — the docstring names
  the substitution and the reason (`dedup.py:59-63`); `simhash` is retained only for analytics and is
  populated at ingest (`cli.py:137`).
- The canonical pick is driven by `published_utc` (`dedup.py:102-104`), and for GDELT rows
  `published_utc` is the **crawl/`seendate`**, not a publication time (`sources/gdelt.py:11-13,64-65`,
  `published_precision='crawl'`). Canonicality is therefore decided by whichever source GDELT saw
  first. Jaccard text for GDELT rows is title-only (`raw_summary=""`, `summary=""` at
  `cli.py:79,84`; `_text()` at `dedup.py:117-118`).
- The observed production state: 1,301 non-canonical items and 2,942 canonical (all version 1) plus
  **1,257 items that no dedup pass has ever touched and that still carry the insert default
  `is_canonical=1`** (`store.py:40`). 1,257 / 5,500 = **22.9 % of the store defaults to "canonical"
  without having been deduped** (DERIVED).
- Nothing hooks dedup after ingest — it is a manual `python -m newsfeed dedup`
  (`cli.py:165-169,209-210`), so the unprocessed fraction grows with every fetch.

### 5. How fxexpert consumes the accrual store

`fxexpert/data.py:147-151` opens `duckdb.connect(store, read_only=True)` — correct read-only
consumer discipline. It reads **exactly three tables** and nothing else:

| Panel input | Store source | Evidence |
|---|---|---|
| pair universe | `SELECT DISTINCT symbol FROM bars WHERE timeframe='1d'` → **58 pairs** | `data.py:150-151`; read-only DuckDB: 58 distinct symbols at both 1d and 1h |
| D1 OHLCV per pair | `bars` (timeframe `1d`), skipped if `< 120` rows | `data.py:234-242` |
| H1 intraday aggregates | `bars` (timeframe `1h`) → day lo/hi, arg-min open, arg-max close, AM session, 24 h realized vol | `data.py:189-207` |
| exog features | `exog` by series name: `CARRY:<pair>`, `RATE:{US,EA,GB,CA}`, `COT:{EUR,GBP,JPY,CHF,CAD,AUD,NZD}`, `FRED:{VIXCLS,BAMLH0A0HYM2,USEPUINDXD,DCOILWTICO,PIORECRUSDM,PNGASEUUSDM}` | `data.py:153-186`; `exog_series()` returns `None` when a series is absent and the feature is then NaN+mask |
| event proximity | `releases_history WHERE impact='high'` grouped by date/currency → rolling 5-day count | `data.py:211-230` |
| output | `data/fx_expert/panel.npz` + `panel_meta.json` (`np.savez_compressed`, `write_text`) | `data.py:303,311` |

Consequences at the boundary (**VERIFIED**):

- **`fxexpert` does not read `ledger`, `fills`, `txns` or `voids` at all** — the 5.6-day staleness of
  the store's ledger/journal path does **not** contaminate the training panel. (Those tables are read
  by `strategies/fx_warden.py:631-640` (bars, exog), `scripts/news_drift_probe.py:53,75`,
  `scripts/fx_signal_sweep.py:72-81`, `scripts/build_training_data.py:82-132`.)
- `releases_history` contains **future scheduled** releases (max ts 2026-09-10 23:50, i.e. ahead of
  the 20:54 UTC query time). The consumption path is safe: `ev_count` uses a backward
  `rolling(5).sum()` (`data.py:230`), so a row at *t* only sees *t−4…t*.
- The **surprise** values that `build_accrual_store.py:299` computes (`actual − forecast`) are stored
  and are **not consumed by the panel** — only the high-impact *count* is (`data.py:211-230`). The
  surprise column is consumed by `scripts/news_drift_probe.py:53`.
- FRED conditioning is a causal rolling z (252 d, min 60) with an explicit publication lag of 1 d
  (daily) / 15 d (`{"PIORECRUSDM","PNGASEUUSDM"}`) applied *before* the z-window (`data.py:169-186`)
  — the lag discipline the `fetch_fred_cond.py:14-17` docstring promises is implemented at the
  consumer, as documented.
- `RATE:{EA,GB,CA}` and `COT:*` are present, but `CARRY:*` exists for only **6 pairs**
  (`EUR_USD, EUR_GBP, EUR_CAD, GBP_USD, GBP_CAD, USD_CAD`) out of 58 — 52 of 58 pairs get a 0-filled
  `carry` with `carry_mask=0` (`data.py:91-98`; read-only DuckDB series list).

### 6. `net.py` — the newsfeed egress layer (what is actually guarded)

`net.py:20-50` validates scheme/host and rejects private/loopback/link-local/reserved/multicast and
`169.254.169.254`, with `_resolve_and_check` re-checking every resolved address at fetch time;
`net.py:72-122` does conditional GET (ETag/Last-Modified, 304 honoured), a per-host token bucket
(`config.DEFAULTS["rate_limit_s"] = {"default": 2.0, "api.gdeltproject.org": 5.0}`,
`config.py:13`), retry with backoff, `Retry-After` on 429 (capped 120 s), 15 s timeout, 3 attempts,
and returns `(False, reason)` instead of raising. It is a deliberate standalone port and does **not**
touch `security/guards.py` (`net.py:1-8`). This module is **not** the layer the other three scripts
use — they use `security.guards.guarded_urlopen` (`fetch_event_feeds.py:33`,
`fetch_ff_upcoming.py:28`) or a bare `urllib.request.urlopen` (`fetch_fred_cond.py:57-58`, which
imports `guarded_urlopen` at :32 but never calls it). The hosts involved **are** in the guards
allowlist (`security/guards.py:29-50`: `www.forexfactory.com`, `www.mof.go.jp`,
`www.federalreserve.gov`, `fred.stlouisfed.org`). **VERIFIED.**

### 7. The feeds dir and its consumers' key contract

Producer shape vs consumer expectations — the two consumers disagree, and one of them is a live lane:

| Feed | Producer keys | Consumer | Consumer's keys | Match? |
|---|---|---|---|---|
| `ff_upcoming.json` | `{week, date_label, time_label, country, name, impact(lowercase), forecast, previous, actual}` inside `{"fetched_at","weeks","events"}` (`fetch_ff_upcoming.py:59-66,106-107`) | `dashboard.py:548-560` (`/api/calendar`) | `events`, `date_label`, `time_label`, `name`, `country`, `impact ∈ ("high","medium")` | **yes** |
| `ff_upcoming.json` | same | `strategies/fx_warden.py:718-723` | `date`, `currency`, `impact ∈ ("High","Med")` | **no** |
| `mof_interventions.json` | `{year, month, day, amount_jpy_100m, direction, kind}` (`fetch_event_feeds.py:86-92`) | `fx_warden.py:229-232` | `date`, `note` | **no** |
| `fed_speeches.json` | `{ts, currency, kind, speaker, title, url}` (`fetch_event_feeds.py:116-118`) | `fx_warden.py:236-239` | `date`, `title` | date only: **no** |
| `fred_distillates.json` | `{DGS2,T5YIE,T10YIE}: {date: value}` (`fetch_event_feeds.py:44-45,175-177`) | — | **no consumer found in the repo** (grep `fred_distillates` → producer only) | **dead** |

Live evidence from the warden's own records (read-only grep of `data/warden/records.jsonl:55-66`)
confirms the mismatch is not theoretical — every prompt sent to the local model on 2026-09-09
contains:

- `"news_refs": "ECON   low \nECON   medium \nECON   holiday …"` — date and currency fields **empty**;
- `MOF  {'year': 1991, 'month': 'May', 'day': 13, 'amount_jpy_100m': 139.0, 'direction':` — the raw
  dict repr (`e.get('note', e)` falling through to the whole row);
- `FED  Waller, The Economic Outlook and S` — empty date;
- `"event_48h": false` for **all 13 currencies in every record**, while the code at
  `fx_warden.py:733-735` adds `10.0 if events.get(c)` to the currency stress score. **VERIFIED.**

---

## Health assessment

**Interview answer to the ticket question, in one paragraph.** The data layer is three separate,
individually-reasonable pipelines that have outgrown their single-writer premises. `newsfeed/` is the
most disciplined artifact in the set — append-only observations, a genuine PIT query
(`store.py:141-154`), ETag-aware egress with an SSRF guard, and a dedicated test file
(`tests/test_newsfeed.py`, fixtures in `tests/fixtures/newsfeed/`). The accrual store has correct
*consumer* discipline in its readers (`fxexpert/data.py:149` read-only) but **four writers**, no
declared owner, a durable Parquet mirror that is 5 days and 5.1 M rows behind the DuckDB file the
readers actually open, and a ledger/journal path frozen since the last full rebuild. The feeds dir is
the weakest link: hand-run scripts, non-atomic `write_text` into files a live lane reads, a
producer/consumer key contract that is broken for the **event-proximity term of the warden's stress
score**, and one fetched dataset with no reader at all.

**Freshness.** Bars/exog/panel are current (panel `date_max` 2026-09-08, rebuilt 2026-09-09 21:26 —
`data/fx_expert/panel_meta.json:464`). Everything else on the FX research path is between 1.4 and
5.6 days old, and **nothing is scheduled** to refresh any of it except `fetch_event_feeds.py` being
called inline by the warden (`fx_warden.py:430-433`). The two artifacts that decay by design —
`ff_upcoming.json` (future weeks) and `newsfeed.db` (rolling news) — have no refresher at all, and
both feed a live lane's prompt.

**Atomicity.** No writer in this layer uses an atomic pattern. Every JSON feed is written by
truncate-in-place `Path.write_text` (`fetch_event_feeds.py:159,165,175,180`;
`fetch_ff_upcoming.py:106`), so a reader (`dashboard.py:547`, `fx_warden.py:221,718`) can observe a
truncated or partially-written file; the consumers wrap reads in bare `except Exception: pass`
(`fx_warden.py:224-227,233-234,240-241`; `dashboard.py:553-554,561-562`), so a torn read degrades
**silently** to "no events" rather than raising. The store build does `CREATE OR REPLACE TABLE` per
dataset and `COPY … TO` per Parquet in sequence with no enclosing transaction
(`build_accrual_store.py:111-367`), and the two incremental writers do `DELETE` then `INSERT` as two
autocommitted statements (`fetch_fred_cond.py:95,101`; `fx_expert_lane.py:118,121`) — a crash, a
lock conflict or a reader between the statements sees a store missing that dataset's rows. The
ledger is read as a whole file (`build_accrual_store.py:88,224`) with `json.loads` failures silently
`continue`d (:93-94), so a partially-flushed final line — which the append-only writer at
`fx_expert_lane.py:82-84` guards against with `flush()+fsync()` — would be **dropped without a
warning** rather than reported.

**Locking.** `newsfeed.db` is WAL with per-call commits; the readers use plain
`sqlite3.connect` (`fx_warden.py:197`), which in WAL is non-blocking for readers. **CLAIMED (not
verified in this session):** Python's `sqlite3.connect` default `timeout=5.0` gives writers a 5 s
busy wait, and DuckDB permits a single write connection per file while `read_only=True` connections
coexist. I did not open a write connection to test either, and the practical consequence for DuckDB —
that a scheduled rebuild and the warden's incremental bar refresh cannot overlap — is therefore
**CLAIMED, SHOULD VERIFY**.

---

## Defects & risks

Ordered by risk to the FX arm, then hygiene. Each is independently actionable; severity is my
judgement, flagged as such.

| # | Sev | Defect | Evidence | Impact |
|---|---|---|---|---|
| **D1** | **High** | `python -m newsfeed fetch` cannot run: `FETCHERS` is referenced at `cli.py:96` and **is not defined anywhere** in the module namespace (verified by import: `hasattr(newsfeed.cli,'FETCHERS') == False`; grep finds the single occurrence). Introduced already-broken in `ffe3978` (the commit that added the whole `newsfeed/` tree, 2026-09-10 08:18 CDT). | `newsfeed/cli.py:96`; `git show ffe3978 --stat -- newsfeed/`; no `cli`/`cmd_fetch` coverage in `tests/test_newsfeed.py` | The declared "sole writer" path for the news store is dead code. The 5,500-row DB predates the commit (`newsfeed.db` mtime 2026-09-09 00:39 < commit time) so it was produced by code that is **not** in git — the store as it stands is not reproducible from the committed fetcher. `backfill` (which does not use `FETCHERS`) remains the only working ingest path. |
| **D2** | **High** | Warden's event-proximity guard is silently dead. `fetch_ff_upcoming.py:59-66` emits `date_label`/`country`/`impact(lowercase)`; `fx_warden.py:721-722` reads `date`/`currency`/`impact ∈ ("High","Med")`. `d` is always `""` and `impact` is never `"High"`, so the predicate can never be true. | `fx_warden.py:718-723`; `fetch_ff_upcoming.py:59-66`; live `data/warden/records.jsonl:56-66` → `event_48h: false` for all 13 currencies in every record | The `+10.0` event-proximity component of the currency stress score (`fx_warden.py:733-735`) never fires, so `event_48h` is permanently false and high/medium-impact releases are invisible to the lane's risk tiers. |
| **D3** | **High** | `fetch_fred_cond.py:95` runs `DELETE FROM exog WHERE series LIKE 'FRED:%'` and then re-inserts only its own `SERIES` list (:47-52, via `fetched_rows`). The store currently holds **17** `FRED:*` series; the script's list covers **8** of them and names one series (`BAMLEMHYHYLCRPIOAS`) that does not exist in the store at all. The next run would **delete 9 series it never restores** — including `FRED:BAMLEMHYHYLCRPIUSOAS`, which `fx_warden.py:637` reads for the EM-HY stress block (the read is guarded by `if not rows: continue` at :641, so the block vanishes silently), and the policy-rate series `ECBDFR/FEDFUNDS/IUDSOIA/IR*`. | `fetch_fred_cond.py:47-52,85-101`; read-only DuckDB `SELECT series … WHERE series LIKE 'FRED:%'` (17 rows); `fx_warden.py:636-641` | A single run of a maintenance script silently strips the warden's EM-stress input and 8 other series from the store. The 5-day gap since the last full rebuild (`build_accrual_store.py:318-334` is the only thing that restores them from cache) widens the exposure window. |
| **D4** | **High** | The durable/authoritative artifact is ambiguous and drifted. Readers open `store.duckdb` (`fxexpert/data.py:22,149`; `fx_warden.py:631`), while the docstring calls the Parquet "the durable artifacts" and `manifest.json` records Parquet-era counts. Measured drift: `bars.parquet` 1,960,635 rows vs duckdb 7,086,324 (−5.13 M, DERIVED); `exog.parquet` 92,795 vs 179,695 (−86,900, DERIVED); store manifest `built_at` 2026-09-06T05:56Z vs duckdb mtime 2026-09-09. | `build_accrual_store.py:355-375`; Parquet row counts via read-only `read_parquet()`; `/home/mrc/opentrader-data/manifest.json` | Any consumer or auditor that trusts the Parquet mirror or the manifest gets 4-5-day-old bars and half the exog series. Map #187's rendered summary ("9 datasets, 165k rows, 10s rebuild") describes that stale Sep-5/6 snapshot. |
| **D5** | **Medium** | Four writers on one DuckDB file with no declared owner and no locking protocol: full rebuild (`build_accrual_store.py:347`), exog `DELETE`+`INSERT` (`fetch_fred_cond.py:94-103` — self-described "documented deviation from single-writer"), bars `DELETE`+`INSERT` + panel rebuild (`fx_expert_lane.py:102,118-126`), bars insert (`fx_expand_universe.py:62`). The docstring's "the store is a CONSUMER of the ledger — never a second writer" (:18) no longer describes the system. | as cited | The audit gate (AGENTS.md #1/#2) cannot be satisfied for this store: no single source of truth, and `data/MANIFEST.json` / `docs/DATA.md` declare neither the store nor its writers. |
| **D6** | **Medium** | Store ledger/journal staleness: 126 ledger rows (max ts 2026-09-04 20:59) vs 1,003 lines in `data/fx_ledger.jsonl` (max ts 2026-09-10 11:56). Same for `fills`/`txns`. | read-only DuckDB vs `wc -l` + `data/fx_ledger.jsonl:1003` | Anything using the store's `ledger`/`fills` for realized-PnL or lane attribution (e.g. `news_drift_probe`, `fx_signal_sweep`, `build_training_data` inputs) sees a 5.6-day-old, 12.6 %-complete view. Note #187's recorded finding "journal fills carry pl, the ledger does not" is *about* this table, so the defect is load-bearing for that map's acceptance query. |
| **D7** | **Medium** | `build_accrual_store.py --skip-venue` is documented as "reuse existing venue tables (offline rebuild)" (:339) but the code takes the empty `fills`/`txns` lists from the skipped branch and does `CREATE OR REPLACE TABLE` + `COPY … TO fills.parquet` anyway (`build_journal` :119-160 → :350, 359-360). A `--skip-venue` run therefore **wipes** the venue tables and their Parquet mirrors instead of reusing them. | `build_accrual_store.py:119-160,339,350,357-367` | A presumed-safe offline rebuild destroys venue data. Not exercised since the last build, so no damage done yet — it is a live foot-gun. |
| **D8** | **Medium** | `ff_upcoming.json` has no refresher and its data expires. Last written 2026-09-05 02:14; the warden's inline refresh only calls `fetch_event_feeds.py` (`fx_warden.py:430-433`), and `fetch_ff_upcoming.py` has no invoker anywhere in the repo. `--weeks 3` from the week of 2026-09-01 bounds the file's newest week to **the week of 2026-09-15**. | `ls -la` mtime; `fetch_ff_upcoming.py:78-107`; grep for invokers (none) | `/api/calendar` (the human's TUI calendar) silently falls back to the dead legacy nextweek feed after the last covered week (`dashboard.py:555,563-573`) and then goes **empty** with no error. Combined with D2 the whole event-avoidance story currently rests on one 5-day-old manual file. |
| **D9** | **Medium** | Dedup is unexercised at the cross-source level and self-reports misleadingly. Layer 1 (canonical URL) is dead because `canonical_url` is NULL on every row; the only live source is GDELT, so the 1,301 "duplicates" are all GDELT-vs-GDELT; 1,257 items (22.9 %) still carry the insert default `is_canonical=1` without ever being deduped; `fx_warden.py:202` filters on `is_canonical = 1` (so they are admitted) while the block is labelled "canonical items" / "newest canonical" (`:206,:210`), and its docstring promises "deduped" (`:190`). 1,257 of 4,199 `is_canonical=1` rows = **29.9 %** of what that filter admits (DERIVED). | `store.py:40`; `cli.py:62,82,137`; read-only `sqlite3` counts; `fx_warden.py:189-210`; `dedup.py:51-57` | The warden's "deduped headlines" block (the one thing it was designed to give the model) can be up to ~30 % un-deduped, and the canonical/raw distinction is asserted in docs (`docs/DATA.md:15`) but partly not in force. |
| **D10** | **Low** | `fetch_fred_cond.py` never calls the `guarded_urlopen` it imports (`:32`), using a bare `urllib.request.urlopen` (`:57-58`) instead — the only one of the four fetchers outside the guards allowlist path. `net.py`'s SSRF work applies only to `newsfeed/`, which does not touch FRED. | `fetch_fred_cond.py:32,55-59`; `security/guards.py:29-50` | Egress-policy inconsistency; `fred.stlouisfed.org` is allowlisted, so no live exposure, but the guard is not in the path. |
| **D11** | **Low** | `fred_distillates.json` (487 KB: DGS2, T5YIE, T10YIE) has **no consumer**; meanwhile the store's `exog` carries `DGS10`/`T10Y2Y` but not `DGS2`/`T5YIE`. So map #205's "policy-cycle distillates" are fetched, written, and read by nothing. | `fetch_event_feeds.py:44-45,168-177`; grep for `fred_distillates` (producer only); read-only DuckDB series list | Wasted fetch work and a misleading appearance of landed #205 scope. |
| **D12** | **Low** | Junk row in `exog`: the cache's `meta` dict has one numeric member (`z_window: 52`), and `build_exog` materialises any numeric member as a data point (`build_accrual_store.py:323-328`), producing a row `series='meta', date='z_window'` (verified: `SELECT MIN(date),MAX(date) FROM exog` → `'1954-07-01','z_window'`). | read-only DuckDB; `data/exog_cache.json["meta"]` | Any `MIN/MAX(date)` or ungrouped date-range query over `exog` returns a nonsense maximum. Consumer queries are per-series and ordered, so no live consumer is broken — but any new probe doing a naive range query will be. |
| **D13** | **Low** | Housekeeping: 2 `runs` rows stuck at `status='running'` with NULL `finished_utc` (no reaper, `store.py:198-212`), and 1,996 items ingested in a run that never finished (before 2026-09-09T05:00:44). | read-only `sqlite3` on `runs`/`items` | Run bookkeeping cannot be used to bound what was ingested; a killed fetch is indistinguishable from an in-flight one forever. |
| **D14** | **Low** | Dead/duplicated code in the pipeline scripts: duplicate `def get` (`fetch_event_feeds.py:49-52` then `:61-62` — the second shadows the first), unused closure `field()` (`fetch_event_feeds.py:103-109`), duplicate `def fetch_week_html` (`fetch_ff_upcoming.py:44-48` then `:113-119` — the validation-bearing second definition wins), unused `_fetch_rss`/`_fetch_gdelt` (`cli.py:48-85`), dead `n_dup` counter (`dedup.py:100,111`), `register_df` **undefined** at its only call site (`build_accrual_store.py:180`, in the `not connected` branch). | as cited | Cosmetic except the last: the no-venue-connection path of `build_bars` would raise `NameError` instead of writing empty bars. Docstrings also overstate: `fetch_event_feeds.py:20` documents a `--skip-ff` flag that no argparse block implements (the script has no argparse at all, so the flag is silently ignored rather than rejected). |

**Contradictions with prior records (surfaced per AGENTS.md audit gate #5):**

1. `build_accrual_store.py:18` and `docs/DATA.md`'s single-writer framing no longer hold for the
   accrual store (D5) — the store has four writers.
2. `docs/DATA.md:8,13` says the news store's writer is `python -m newsfeed fetch` and that
   `data/newsfeed/` is "rebuildable: backfill is idempotent by content_hash". The rebuild path is
   only reachable via `backfill`, and the source registry (`sources`: the GDELT query string and the
   dailyfx URL) lives **only inside the gitignored DB** (`git check-ignore` → `data/newsfeed/`), so it
   is not reproducible from the repo. **VERIFIED** (grep for `dailyfx`/`gdelt-fx` in tracked files
   finds no config record).
3. Map #187's decision text ("store live …, 9 datasets, 165k rows, 10s rebuild") describes the
   2026-09-06 Parquet snapshot, not the store readers open today (D4).

---

## Links to existing maps

| Map / ticket | Relationship to these findings |
|---|---|
| **#187** (data pipeline groundwork: queryable accrual store + root-disk triage) | Parent of the store. Its destination — "accrual data lands in a queryable columnar store on the data drive" — is **met**, but its two design constraints ("consumer, never a second writer"; Parquet as the durable artifact) are contradicted today → D4/D5/D7. Its `#189` acceptance query ("journal fills carry pl"; h1-mom −13.15 → +3.34 NFP-excluded) runs against the `fills`/`releases_history` tables that are **5.6 days stale** → D6. |
| **#198** (FX strategy-discovery sweep over the accrual store) | The sweep's grounding line says "store at /home/mrc/opentrader-data (70k bars D1+H1 full history, exog 92k rows: COT z 2006+, rates 1954+, carry 1997+, events 87k)". Measured today: **7.09 M bars** (1h) + 289 k (1d), exog **179,695** rows, releases_history 83,115. The sweep's premise numbers are stale by an order of magnitude on bars → D4. `scripts/fx_signal_sweep.py:72-81` reads `exog` directly, so it inherits D3's series-deletion risk. |
| **#206** (exogenous alpha-mining loop) | Its "not yet specified" note — "depends on the exogenous feature enumeration from #205/#203 landing in the store" — is only partly true: #205's FRED distillates (DGS2/T5YIE/T10YIE) are in `feeds/` with **no reader** and are **not** in the store (D11); #203's MOF/Fed feeds land in `feeds/` but reach the warden's prompt malformed (D2 table). The surprise values (`releases_history.surprise`, `build_accrual_store.py:299`) exist and are probe-ready. |
| **#204** (GUI calendar + live-feed avoidance windows) | Its recorded decision — "the week-view scrape becomes the upcoming-events source for BOTH the GUI display and the avoidance windows" — is implemented for the GUI (`dashboard.py:544-560`, keys match) and **broken** for the avoidance windows (D2) and unrefreshed for both (D8). This is the single highest-value fix in this doc. |
| **#203** (MOF interventions + Fed comms calendar) | Feeds land (`feeds/mof_interventions.json` 40 rows, `fed_speeches.json` 15 rows per the feeds manifest) but are consumed with the wrong keys (D2 table), so the "political layer" reaches the model as dict reprs. |
| **#228 / #237** (health map / report assembly) | This doc is the #233 child. Its D1-D4 are candidate backlog items; D2/D3/D8 are quick wins; D5/D4 are structural debt. |
| `docs/health/research/232-fxexpert-alpha-loop.md` | Sibling: owns panel/model/training internals. This doc owns only the store→panel boundary (§5). |
| `docs/health/research/236-cross-cutting-integrity.md` | Sibling: likely overlaps on the "which artifact is authoritative" question (D4) and the append-only ledger discipline (D6). |

---

## Open questions

1. **Who owns `store.duckdb`?** Should the design intent be restored (one rebuild script, readers
   only elsewhere — moving `fetch_fred_cond`'s and `fx_expert_lane`'s writes into the rebuild, or
   into a cache that the rebuild consumes), or is incremental multi-writer now the design and the
   docs should say so? Human-gated: it changes the freshness contract for every research probe.
2. **Parquet or DuckDB — which is authoritative?** If Parquet is meant to be durable, the 5.13 M-row
   gap means the mirror is not being maintained; if DuckDB is authoritative, `manifest.json` and the
   docstring are lying to future readers.
3. **Is the dailyfx RSS source supposed to be live?** It is registered (tier 4) and never fetched, so
   no cross-source dedup has ever run in production. If yes, the `FETCHERS` fix is a prerequisite
   *and* dedup needs a post-ingest hook; if no, the source should be disabled and the cross-source
   dedup claim withdrawn from `docs/DATA.md`.
4. **`data/accrual` (the ticket's premise):** nothing in the repo, git history, or disk. Was this an
   intended path that was never created, or a mis-transcription of the `/home/mrc/opentrader-data`
   store root? Worth one line of confirmation from whoever wrote the ticket so no future searcher
   chases it.
5. **Which of the 9 at-risk `FRED:*` series are load-bearing?** `BAMLEMHYHYLCRPIUSOAS` is (warden EM
   stress). Are `ECBDFR/FEDFUNDS/IUDSOIA/IR*` consumed anywhere, or are they superseded by the
   derived `RATE:*` series (`RATE:US` 26,357 rows etc.)?
6. **Scheduling.** AGENTS.md's postmortem rule says every cron/systemd job must name a recent
   artifact it produced. If these four scripts are meant to run on a schedule, which unit produces
   which artifact — and if they are hand-run, what is the freshness guarantee the FX arm is relying
   on? (`crontab -l` was unreadable in this session, so a system crontab entry is not excluded.)
7. **Should the store's `ledger`/`fills` tables exist at all?** Given `data/fx_ledger.jsonl` is the
   append-only source of truth and AGENTS.md says venue answers come from OANDA, the store copy is a
   third representation of realized PnL — map #187 already flags "retention policy for venue
   transaction snapshots vs. the ledger" as unspecified. That decision now has a staleness number
   attached to it (D6).
