# 234 — Human-facing surface: dashboard (:8097), npm/Ink TUI, PWA

Read-only research for wayfinder ticket #234 (parent map #218). No service was
restarted, no dashboard/TUI file was modified. Method: file reads (`read`/`grep`/
`glob`), read-only shell (`ls`, `git log/status/show`, `wc`, `ss -tlnp`), a small
number of GETs to `http://127.0.0.1:8097/api/...`, one non-TTY render of
`tui/index.js` (non-TTY execution is explicitly supported, `tui/index.js:679`),
and read-only re-execution of the repo's own ledger function
(`from tui import ledger_performance` — the same import the dashboard performs at
`dashboard.py:636`).

Labels used throughout: **VERIFIED (file:line)** = read in the repo and/or
observed live; **READ-FROM-DOCS** = stated in repo docs, not independently
reproduced; **CLAIMED** = asserted somewhere without evidence I could reproduce.

## Scope

In scope: the human-facing surface of the FX practice arm on OANDA —
`dashboard.py` (FastAPI + dashboard HTML, `/fx`, `/api/fx`, `/api/calendar`,
`/api/fx-lanes`, `/api/lifecycle`, `/api/warden`, stale-while-revalidate cache),
`dashboard.html`, `tui/index.js` (the human's npm/Ink client), `tui.py` (legacy
Textual artifact), and `pwa/`. Crypto paper-lane work is out of scope per
AGENTS.md; crypto content still *rendered* by the client is noted only where it
occupies the human's screen.

Environment limits that bound this report (see Open questions):
- My shell runs under `bwrap --unshare-pid`, so `ps` sees only sandbox processes —
  **I could not observe which TUI process the human is running**.
- `systemctl --user` cannot reach the user bus from that sandbox
  (`Failed to connect to user scope bus via local transport: No data available`),
  so **service state could not be read**; the listening socket plus live HTTP
  responses are the ground truth I used instead.

## Verified findings (file:line)

### 1. The surface is live and serving real venue data

- Two dashboard processes listen on :8097 — `127.0.0.1:8097` and
  `100.124.30.55:8097` (tailnet) — **VERIFIED** (`ss -tlnp`). This matches the two
  user units: `~/.config/systemd/user/opentrader-dashboard.service:9`
  (`--host 127.0.0.1 --port 8097`, interpreter `/home/mrc/opentrader/.venv/bin/python3`)
  and `opentrader-dashboard-tail.service:9` (`--host 100.124.30.55 --port 8097`).
- GETs returned 200 with live OANDA practice data: `/api/fx` 3.5 ms,
  `/api/fx-lanes` 1.35 s, `/api/calendar` 0.33 s; `/health` and `/api/lifecycle` 200
  — **VERIFIED** (live).
- Live account snapshot at check time: `balance 99619.0822`, `nav ~99626–99639`,
  `realized_today 0.0`, `financing_today -26.2502`, `book 57` open trades,
  `fills 25` ledger rows, `registry 11` experts — **VERIFIED** (`/api/fx`,
  `/api/fx-lanes`; `_compute_fx` populates these at `dashboard.py:228-283`: book
  235-244, balance/NAV 245-247, day window 251-258, fills 264-273, registry 274-276).
- `/api/calendar` returned 7 bank decisions in the 45-day window and a populated
  ForexFactory release list (`decisions` built at `dashboard.py:526-535`, primary
  week-scrape parse 544-562, legacy fallback 563-573) — **VERIFIED** (live).

### 2. What each surface renders

**`dashboard.py` routes** (all **VERIFIED** by grep): `/fx` 400, `/api/calendar`
519, `/api/fx` 579, `/api/fx-lanes` 628, `/api/lifecycle` 712, `/api/warden` 768,
`/` 870, `/manifest.webmanifest` 883, `/sw.js` 888, `/icons` 894/899, `/health`
904, `/pva` 922, `/state` 927, plus history/positions/trades/regimes/benchmark/
lanes/expert-router/stream/registry routes 932-1276.

- **`/`** serves `dashboard.html` (read once at import — `dashboard.py:1199`).
  **VERIFIED** the served bytes are byte-identical to the working-tree file:
  `sha256 f6056d9c0f312c14…`, 28434 bytes both sides. The page renders: header
  strip (balance/NAV/venue-day realized/financing/uPL, `dashboard.html:234-237`,
  254), LANES table with realized + **realized_today** + open counts + uPL
  (238-253), registry control-plane table with lifecycle badge, notional cap and
  accrual bar (255-271), ownership matrix (274-308), open book by owner (311-323),
  fill tape (326-335), calendar table (337-348), and a Warden tab (370-448).
- **`/api/fx-lanes`** is the payload `dashboard.html` actually polls every 5 s
  (`dashboard.html:358-365`), plus every 15 s alongside `/api/warden`
  (450-457, 467). It carries `lanes`, `book`, `registry`, `fills` — i.e. the FX
  page's tables ride on this one endpoint, not on `/api/fx` (`dashboard.py:701-709`
  and the comment at 704-706 recording the earlier "panels rendered from a payload
  that never carried them" bug).
- **`/fx`** is a separate, self-contained server-rendered HTML page
  (`FX_PAGE` 386-397, handler 400-440) with `<meta http-equiv="refresh" content="60">`
  (line 387), balance/NAV/queue, open book, fills, and a registry table with
  `kind/status/closed` only. It is **not linked from any other surface** —
  the only references are its own route and docstring (`dashboard.py:443`, `581`)
  — **VERIFIED**.
- **`tui/index.js`** (the human's client — see §3): page `[1] home`
  (`buildHome` 270-365), page `[2] forex` (`buildForex` 367-480), page `[3] calendar`
  (`buildCalendar` 494-648); keys `1/2/3/r/q` (673-679); default page is `home`
  unless `--forex`/`--calendar` (`663-664`). Polls: state files 2 s, `/api/fx` 5 s,
  `/api/calendar` 20 s (680-687). Forex page renders header bar (379), LANES table
  with per-lane open counts (390-412), OPEN BOOK with an `SL✓/SL✗!` protection
  column (414-430), FILL STREAM with lane tags (440-467), CRASH-TEST $300 panel
  (470-478).
- **`pwa/`**: `manifest.webmanifest` (`name "OpenTrader FX Monitor"`, `start_url "/"`,
  standalone, 2 icons), `sw.js` (shell network-first with cache fallback;
  `/api/*` explicitly network-only, `pwa/sw.js:12-14`), registered from the
  dashboard page (`dashboard.html:367`), served by `dashboard.py:883-901`.
  **The PWA is the dashboard page, not a separate app** — **VERIFIED**.
- **`tui.py`** renders one Textual screen with two toggled containers
  (256-266): Home (portfolio strip, agents DataTable, system/event-gate line) and
  Forex (book line, positions DataTable, lane block, fills DataTable, crash panel);
  refresh every 45 s (462) and per-screen 30 s (279). It reads `/api/fx` first and
  falls back to a direct OANDA call (`fetch_fx` 174-202).

### 3. Which TUI is authoritative — confirmed against the docs

- **The human's client is `tui/index.js`** — READ-FROM-DOCS, and consistent with
  every artifact I checked: `docs/agents/tui.md:7-10` ("The human's client:
  npm/Ink — `tui/index.js`", launch `npm start`, flags `--forex`/`--calendar`),
  `docs/agents/tui.md:35-45` (`tui.py` "is NOT what the human runs"; it replaced
  the npm client once and was restored in commit `ab66167`), and the binding rule
  `docs/agents/tui.md:49-52` + AGENTS.md ("TUI clients — the human runs the
  npm/Ink one"). `tui/package.json:14-16` confirms `npm start` = `node index.js`
  — **VERIFIED**.
- **`tui.py` contradicts the docs in its own docstring**: line 2 —
  *"OpenTrader TUI — terminal mission control (replaces the Ink/Node tui)"* — while
  `tui.py:18` tells the reader to run it with `/home/mrc/rocm_venv/bin/python3 tui.py`
  — **VERIFIED**. This is a live re-infection vector for the #166/#167
  wrong-client mistake.
- **`tui.py` is nevertheless a live import dependency of the dashboard**:
  `dashboard.py:636 from tui import ledger_performance` (called at 638) — so
  deleting `tui.py` breaks `/api/fx-lanes` (the endpoint `dashboard.html` polls every
  5 s). It is imported successfully in the installed interpreter, which is the same
  `/home/mrc/opentrader/.venv/bin/python3` named in the unit file — **VERIFIED**
  (unit line 9; both venvs ship `textual`, but the checked-in unit at
  `scripts/systemd/opentrader-dashboard.service:9` points at
  `/home/mrc/rocm_venv/bin/python3` instead).
- I could **not** independently confirm which client is running (see Scope limits).
  No launcher, desktop entry, shell alias or hyprland keybind referencing either
  client was found in the readable config paths — **VERIFIED** (no matches), which
  is absence of evidence, not evidence of absence.

### 4. Venue-live vs cache boundary

Measured on the running service; every row traced to code.

| Surface / datum | Source | Freshness at check time |
|---|---|---|
| `/api/fx` `book`, `balance`, `nav`, `realized_today`, `financing_today`, `fills`, `registry` | OANDA REST + ledger/registry files, computed in `_compute_fx` (`dashboard.py:228-283`) and served from `_FX_CACHE` | stale-while-revalidate: instant serve, background refresh when older than 30 s (`dashboard.py:206-227`, threshold at 216); cold cache returns a `{"warming": true, … "balance": null}` payload (225-227) |
| `/api/fx` `flat` (per-lane reasons) | `_flat_reasons()` on top of the cached snapshot | own 300 s TTL (`dashboard.py:288-291`, attached at 220) |
| `/api/fx-lanes` `lanes[*].realized`, `realized_today` | **live venue journal walk per request** — `transactions/sinceid?id=0` over the account's whole history (`_venue_lane_realized`, `dashboard.py:587-623`, called unconditionally at 639) | fresh per request; measured 1.35 s per call vs 3.5 ms for `/api/fx` |
| `/api/fx-lanes` `lanes[*].rounds`, `winrate` | `tui.ledger_performance()` — the **ledger file** re-read and re-parsed per request (`dashboard.py:636-638`; algorithm `tui.py:99-148`) | file-fresh, FIFO-derived, not venue-derived |
| `/api/fx-lanes` `open_n`, `open_upl`, `balance`, `nav` | the **30 s SWR snapshot** (`dashboard.py:637, 641-645, 701-703`) | up to 30 s stale — one payload mixes fresh realized with ≤30 s-stale uPL |
| `/api/fx-lanes` `crash.realized` | `data/fx_crashtest.json` (`dashboard.py:646-651, 668-669`) | `last_venue_sync = 2026-09-03T11:30:01Z` — **frozen ~7 days** (retired lane, labelled "retired 09-03 — scorecard from venue journal", `dashboard.py:677`) |
| `/api/fx-lanes` `registry[*].lifecycle/_cap/accrual` | registry file read fresh (`dashboard.py:693-700`; `strategies/expert_lifecycle.py:60-63` `_load_registry` has no cache) | uncached |
| `/api/calendar` | `ff_upcoming.json` parsed per request (544-562), else `_ff_events()` legacy feed with a 6 h file cache (449-462) | cold-read per request; legacy path 6 h |
| `/api/lifecycle` | registry + claims + log tail, all read per request (`712-765`) | uncached — **and consumed by no client** (see D1) |
| `/api/warden` | warden JSONL/JSON files read per request (768-867) | file-fresh |
| `dashboard.html` | `/api/fx-lanes` 5 s, `/api/calendar` 60 s, `/api/warden`+`/api/fx-lanes` 15 s (`dashboard.html:358-365, 467`) | — |
| `tui/index.js` | state files 2 s, `/api/fx` 5 s, `/api/calendar` 20 s (`tui/index.js:680-687`) | inherits the 30 s SWR staleness for book/balance |
| `pwa/sw.js` | shell network-first + cache fallback; `/api/*` **never cached** (`pwa/sw.js:12-14`) | PWA API reads are as fresh as the endpoint |

Net boundary: **queued/lane realized are venue-live; open-position uPL, balance,
NAV, fills and registry on both clients are ≤30 s old; the crash scorecard is
7 days old by design; the TUI's lane table is ledger-derived, not venue-derived
(§5).**

### 5. The human's TUI lane scoreboard disagrees with the venue on 6 of 8 lanes

I rendered one real frame of page `[2] forex` (non-TTY) and compared it with the
same instants from `/api/fx-lanes`:

| Lane | TUI `laneStats()` rendered | `/api/fx-lanes` (venue journal) | Verdict |
|---|---|---|---|
| `h1-rev` | **realized +0.00, 0 RT, WR —** | realized **−24.42**, **18 RT**, WR 16.7% | TUI shows the lane as dead |
| `fxexp-g151` | −4.00, 11 RT | 0.00, 47 RT | disagrees (both fields) |
| `fxexp-g137` | −4.51, 13 RT | 0.00, 28 RT | disagrees |
| `fxexp-g138` | −0.33, 6 RT | 0.00, 19 RT | disagrees |
| `h1-mom` | −29.55, 51 RT | −19.87, 51 RT | realized disagrees |
| `mom-k5` | −2.12, 34 RT | −0.68, 34 RT | realized disagrees |
| `c08-fade` | −0.45, 1 RT | 0.00, 1 RT | realized disagrees |
| `crash` | −18.40, 18 RT | −18.40, 18 RT | agrees (both override from `fx_crashtest.json`: `tui/index.js:396-401`, `dashboard.py:668-669`) |

A `reconciled` pseudo-lane (−17.18, 4 RT) also appears in the TUI and is not a lane
at all. The Forex header bar asserts **"venue authoritative"** (`tui/index.js:379`)
directly above a table that is ledger-derived — **VERIFIED** (rendered frame +
`tui/index.js:689 const lanes = laneStats();`).

**Root cause of the `h1-rev` zeroing — a laneOf() gap.** `laneStats()`'s `laneOf`
(`tui/index.js:94-114`) matches `c08/mr-fade`, `intraday`, `watchdog`, `crash`,
`momentum-entry|out-of-target|max-hold` and `venue-reconciliation`, then falls
through to `"reconciled"` — it has **no `h1-rev` and no `h4-brk` branch**, unlike
(a) the same file's FILL STREAM mapper (`tui/index.js:454-455`: `h1-rev`, `h4-brk`)
and (b) `tui.py:69-70 attribute_lane` (which does map `h1-rev`). The ledger confirms
the asymmetry: of the 39 h1-rev-related rows, **21 are untagged BUYs with reason
`h1-rev-rsi2`** and **4 are untagged `h1-rev-maxhold` SELLs** — all routed to
`reconciled` by the JS — while only the **14 tagged `venue-reconciliation` SELLs**
land in `h1-rev`; a lane with sell legs but no buy legs books 0 rounds — **VERIFIED**
(ledger histogram + executed `laneStats()` + rendered frame).

**Root cause of the RT divergence:** `laneStats()` skips any row with a falsy
price (`tui/index.js:121 if (!qty || !price) continue;`), while
`tui.ledger_performance` does not guard price (`tui.py:122`). The ledger contains
**138 zero-price rows of 1003 (13.8 %)** — 128 of them `rank-rebal` legs across the
three trained lanes (59/40/29 by tag), dated 09-09 and 09-10 — so the TUI silently
discards ~13 % of the ledger's legs while the web scoreboard counts them —
**VERIFIED**.

### 6. `tui.py`'s ledger FIFO produces a physically impossible number

Running the repo's own function in the dashboard's interpreter:

```
fxexp-g151 {'realized':  3876.910639931278, 'rounds': 47, 'winrate': 17.02}
fxexp-g137 {'realized':   202.48505551789046, 'rounds': 28, 'winrate': 10.71}
fxexp-g138 {'realized':  -357.76570275172594, 'rounds': 19, 'winrate': 5.26}
```

+3876.91 for a single lane exceeds any plausible P&L on an account whose whole
balance is 99,619.08. Mechanism, re-derived read-only from the ledger: the
`fxexp-g151` book contains **25 zero-price BUY legs totalling 48,597 units**; a
BUY booked at price 0 contributes `cost += qty * 0`, so the paired SELL books the
*entire notional* as realized — AUD_JPY +1621.84, GBP_JPY +1170.96,
EUR_JPY +1126.00 from single round trips, summing to exactly 3876.91 —
**VERIFIED** (ledger replay of `tui.py:117-140`). The JS client is immune because of
the `!price` guard in §5.

Today this is **masked** on the web page, because `_venue_lane_realized` returns
`0.0` (not `None`) for these lanes so the ledger fallback at
`dashboard.py:665-667` is skipped. It becomes visible the moment the venue walk
fails: `_venue_lane_realized` returns `{}, {}` on any exception
(`dashboard.py:624-625`), and then **every** lane falls back to the ledger — i.e.
one OANDA hiccup puts "+3876.91" on the human's web scoreboard.

### 7. `/api/lifecycle` and the #224 lifecycle panel

- The control-plane data exists and is **uncached as #224 required**:
  `/api/lifecycle` (`dashboard.py:712-765`) returns 11 experts with `lifecycle`,
  `notional_cap`, `accrual`, `active`, `claims` and a 26-row transition log;
  `_load_registry()` has no cache (**VERIFIED**, `strategies/expert_lifecycle.py:60-63`).
- `dashboard.html:255-271` **already renders** lifecycle state (colour-coded badge,
  `⛔` for inactive, `opacity:.45` rows), notional cap and the accrual bar
  (`accrual_closed/accrual_bar`), fed by `/api/fx-lanes:683-700`; verified live:
  `fx_mom_k5_top2 accruing cap 1.0 closed 34/30`, `fx-expert-g13 cut cap 1.0`,
  `fx-expert-g151 accruing closed 47/30` — **VERIFIED**.
- **Gap vs #224's text:** the ticket asks for "lifecycle state, notional cap,
  accrual counts, **and claims**". Claims are exposed only by `/api/lifecycle`
  (`dashboard.py:725-734, 753`) and **no client fetches that endpoint** — grep for
  `api/lifecycle` across `*.js`/`*.html`/`*.py` matches only its own definition, and
  the string `claims` appears nowhere in `dashboard.html` or `tui/index.js` —
  **VERIFIED**. The transition log tail is likewise invisible.

### 8. Other surfaces present in the tree

- `dashboard_legacy.html` (105 KB, 2026-09-04) and `docs/dashboard.html` (68 KB,
  2026-07-31) are distinct files, **served by no route** and referenced by nothing
  except a `.zcode` plan note ("preserved at `dashboard_legacy.html` pending the
  human's deletion call") — **VERIFIED**. The served page is `dashboard.html` only
  (`dashboard.py:1199`).
- `static/` (three.min.js, rough.min.js) is mounted at `/static`
  (`dashboard.py:182-185`) for a "3D neural-network visualization" that the current
  `dashboard.html` does not contain — vestigial, harmless.
- `/health` reports the **crypto paper lane** (`exchange "paper"`, `data_mode
  "synthetic"`, `initial_cash 500`, `cash 372.75`) while the FX page is the active
  focus — **VERIFIED** (live GET; handler `dashboard.py:904-919` reading
  `data/paper_state.json`).

## Health assessment

The **web surface is in good shape**. The server is up on both interfaces and
serving real OANDA practice data; `/api/fx`'s stale-while-revalidate cache does
exactly what its docstring claims (3.5 ms cached serves, background refresh, a
`warming` payload instead of blocking on the ~15-20 s cold compute); the lane
scoreboard takes realized from the venue journal rather than ledger FIFO, which is
the right call per AGENTS.md; the crash lane is consistently venue-derived on both
clients; the PWA correctly refuses to cache `/api/*`; and the #224 lifecycle panel
is already implemented with lifecycle/cap/accrual. `/api/lifecycle` satisfies the
"no cache" requirement and even carries claims and an audit log.

The **human's own client is the weakest surface**, and it is the one the human
looks at. Its LANES table is presented under a "venue authoritative" banner but is
computed locally from `data/fx_ledger.jsonl` by FIFO with a quote→USD approximation
(`tui/index.js:124-132`) that is only correct for USD-base pairs, it silently drops
13.8 % of ledger rows, and one lane (`h1-rev`) is rendered as permanently dead
(+0.00 / 0 RT) against a venue truth of −24.42 / 18 RT. The divergence is not
cosmetic: it is the difference between "this lane has never traded" and "this lane
has 18 closed round trips and a −$24 loss". The route to a venue-authoritative
per-lane scoreboard **already exists** — `/api/fx-lanes` carries `realized`,
`realized_today`, `rounds`, `winrate` and per-lane open uPL — and the TUI simply
does not poll or render it, even though the `laneRow()` helper already has a
`realized_today` slot for it (`tui/index.js:256-259`) that nothing ever fills.

Second-order health concern: the dashboard's lane scoreboard depends on a legacy
artifact (`from tui import ledger_performance`) whose FIFO is provably wrong on the
current ledger, and the only thing preventing that wrongness from reaching the
human's screen is a venue call succeeding. That is a coupling worth breaking
deliberately rather than by accident.

## Defects & risks

| # | Defect | Evidence | Severity |
|---|---|---|---|
| D1 | `h1-rev` lane renders as dead (+0.00, 0 RT, WR —) vs venue −24.42 / 18 RT. Cause: `laneOf()` lacks `h1-rev` (and `h4-brk`) branches that exist in the same file's fill mapper and in `tui.py`. | `tui/index.js:94-114` vs `454-455`, `tui.py:69-70`; ledger 21 untagged `h1-rev-rsi2` BUYs + 4 `h1-rev-maxhold` → `reconciled`; rendered frame confirms | **High** |
| D2 | TUI lane `realized` disagrees with the venue on 6 of 8 lanes; header bar still says "venue authoritative". | rendered frame vs `/api/fx-lanes` (§5 table) | **High** |
| D3 | `laneStats()` drops every zero-price row (138/1003 = 13.8 %), halving RT counts on trained lanes (11/13/6 vs 47/28/19). | `tui/index.js:121` vs `tui.py:122`; ledger histogram | **High** |
| D4 | `tui.ledger_performance()` books zero-price BUYs at cost 0 → phantom profit **+3876.91** for `fxexp-g151`; currently masked by the venue override, but exposed to the web scoreboard whenever the venue walk throws (`except: return {}, {}`). | `dashboard.py:624-625, 636-638, 665-667`; `tui.py:117-140`; replay of the ledger | **High** (latent) |
| D5 | The TUI renders no venue-error state: `/api/fx` failures are swallowed (`catch { /* keep last snapshot; page shows offline state */ }`) and the claim in that comment is false — the page shows `balance $— … 0 pos` and `(no fills yet)`, indistinguishable from a genuinely flat book. The first rendered frame on start-up looks exactly like this. The dashboard page does show a "VENUE DOWN" pill, so the two clients disagree about the same outage. | `tui/index.js:76-81` (no `.error` read anywhere in the file) vs `dashboard.html:232-233`; rendered cold-start frame | **High** |
| D6 | Per-lane `realized_today` never reaches the TUI: `laneRow()` supports the field but the TUI feeds it `laneStats()`, which does not compute it. The one venue-day figure the human sees is the account-level one in the header bar. | `tui/index.js:258-259`, `689`; rendered lane rows contain no "today" column | Medium |
| D7 | `dashboard.html:372` documents `/api/fx-lanes` as "5s-cached". It is not cached at all — every request walks the full account journal (`sinceid?id=0`) and takes ~1.35 s (383× the cached `/api/fx`). Polled every 5 s by the page plus every 15 s by the Warden poller (which fires even while the FX tab is active), and by **two** dashboard processes with independent caches. | `dashboard.html:362, 372, 467`; `dashboard.py:601-603, 639`; measured timings; `ss -tlnp` | Medium |
| D8 | `tui.py:2` claims it "replaces the Ink/Node tui" and line 18 instructs running it with `rocm_venv/python3` — the exact wrong-client framing that #166/#167 record. It must not be deleted blindly, because `dashboard.py:636` imports from it. | `tui.py:2, 18`; `dashboard.py:636`; `docs/agents/tui.md:35-52` | Medium |
| D9 | The TUI footer claims "60s (calendar)" while the code polls every 20 s. Visible only on terminals ≥117 columns (footer string is 125 chars; `"60s"` starts at index 111 and the renderer keeps at most `W−1 = min(cols−2,120)−1` chars, so 96 cols clips it and a 200-col terminal shows `… / 60s (cal`). | `tui/index.js:718` vs `683`; measured string/index geometry | Low |
| D10 | Claims and the lifecycle transition log are exposed by `/api/lifecycle` but rendered by no client — #224's text asks for claims in the panel. | `dashboard.py:725-734, 753`; no `api/lifecycle` consumer; no `claims` in `dashboard.html` / `tui/index.js` | Medium |
| D11 | The crash-lane scorecard both clients display is frozen at `last_venue_sync 2026-09-03T11:30:01Z` (~7 days). Labelled "retired 09-03" on both, so it is honest — but it is stale by construction and nothing ages it out. | `data/fx_crashtest.json`; `tui/index.js:396-401`; `dashboard.py:668-669, 677` | Low |
| D12 | The checked-in unit `scripts/systemd/opentrader-dashboard.service:9` differs from the installed one: it runs `/home/mrc/rocm_venv/bin/python3` and passes `--port 8097` with **no `--host`**, i.e. it would bind `0.0.0.0`. Current listeners are loopback + tailnet only, so there is no exposure today; installing the repo copy would create one. | both unit files; `ss -tlnp`; the `.zcode` plan's own "never 0.0.0.0" check | Medium |
| D13 | `dashboard.html` is read once at import (`dashboard.py:1199`), so HTML edits do not reach the browser until the service restarts. It is currently in sync (identical SHA), so this is a mechanism risk, not a present staleness. | `dashboard.py:1199`; byte-identical served page | Low |
| D14 | Orphan/stale HTML: `dashboard_legacy.html` and `docs/dashboard.html` are served by nothing and referenced by nothing; the `/fx` page is a third, unlinked human surface with its own 60 s meta-refresh and a thinner registry table. | rollout greps; `dashboard.py:400-440, 1199` | Low |
| D15 | Home page still devotes most of its area to out-of-scope crypto content (CRYPTO BOOK MAIN/SHADOW, BOARDS, ROUTER MoT, DEPLOYABILITY) while the FX arm is the only active focus. | `tui/index.js:320-363`; `/health` returning the paper lane | Low (human call) |

## Links to existing maps

- **#218** — `wayfinder:map — FX pipeline completion: lifecycle enforcement, scoreboard, halt-gate` (parent; 8/9 sub-issues complete).
- **#224** — `Dashboard lifecycle panel` (this ticket's cross-ref): its requested data layer exists and is uncached; the panel is rendered in `dashboard.html`; **claims remain unrendered** (D10).
- **`docs/agents/tui.md`** — authoritative statement of which client the human runs, and the two recorded wrong-client incidents (#166, #167 amendment, commit `ab66167`).
- **AGENTS.md** — "The FX arm — OANDA practice" (venue authoritative, write-through caches, lane/ledger contract) and "TUI clients — the human runs the npm/Ink one" (binding).
- Peer research in this directory: `docs/health/research/230-oanda-adapter-guards.md`, `232-fxexpert-alpha-loop.md`, `236-cross-cutting-integrity.md`.
- Related closed-out context: #159/#160 (crypto-lane cache-first disease, out of scope), #158/#171/#174/#175 (ledger void rows and venue attribution), map #187/#204 (ForexFactory feed).

## Open questions

1. **Why does the venue walk return exactly `0.0` for all three trained lanes?**
   `fxexp-g151` has 47 closed round trips and a 17 % win rate; an exactly-flat
   cumulative realized is not credible, and the ledger-based alternatives are wrong
   too (+3876.91 / −4.00 depending on the implementation). Resolving this needs a
   raw venue-journal fetch (`transactions/sinceid?id=0`) and a per-tag sum, which I
   deliberately did not do here. Until then the trained lanes' `realized` column
   should be treated as unknown on **both** surfaces, not as zero.
2. **Does the per-lane picture reconcile to the account at all?** Summed lane
   realized is −63.4 from the venue payload and −76.5 as the TUI renders it
   (after the `crash` override to −18.40), against a balance of 99,619.08. Taking a
   100,000 opening balance, account P&L is −380.92, of which −26.25 is financing —
   so ≈ −354.67 of trading P&L, of which only −63.4 is attributed to any lane.
   `_venue_lane_realized` has a `legacy-smoke` bucket for pre-2026-08-31 untagged
   fills (`dashboard.py:613-617`) that **no surface shows**, and the account's
   opening balance is not recorded anywhere I could read. Who owns the missing
   ~$290, and should a `legacy-smoke`/`unattributed` row be surfaced so the columns
   add up?
3. **Are the 138 zero-price rows a writer bug or a deliberate placeholder?**
   They are all `rank-rebal`/trained-lane legs (plus 3 `intraday-momentum` legs from
   09-02, which is also when the phantom-entry incident was investigated). Either
   way both renderers need one shared rule — today the JS skips them and the Python
   books them at cost 0.
4. **Which client is the human actually running right now?** Not verifiable from
   this session (`ps` is PID-isolated; `systemctl --user` cannot reach the user bus).
   Worth one `ps` check from an unsandboxed shell before any UI fix is reported
   landed — this is exactly the check `docs/agents/tui.md` rule 3 demands.
5. **Should `tui.py` stay?** It is simultaneously a documented trap and a live
   import dependency of `/api/fx-lanes`. The cheap, non-destructive direction is to
   move `ledger_performance` (and `attribute_lane`) into a proper module — e.g.
   alongside `strategies/expert_lifecycle.py` — so the dashboard stops importing the
   legacy client, and then let the human decide `tui.py`'s fate. Any deletion or
   replacement of `tui/index.js` remains forbidden by `docs/agents/tui.md:50`.
6. **Does the human want the crypto panels off page 1?** The Home page spends most
   of its area on the out-of-scope paper lane; moving FX to the default page would
   be a one-line change (`tui/index.js:663-664`) but is a human call.
7. **Should the TUI poll `/api/fx-lanes` instead of computing lanes locally?** It is
   venue-authoritative, already carries `realized_today` and per-lane open uPL, and
   the `laneRow()` slot for the venue-day figure already exists. Cost: 1.35 s per
   call on the server, so a 5 s poll without adding a cache would triple the venue
   journal traffic — the TUI should probably poll it at a slower cadence, or the
   endpoint should get one.
