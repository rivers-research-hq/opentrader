# FX live-lane surface — runners, schedules, and risk-to-account (wayfinder #229)

**Ticket:** #229 (parent #228, blocks #237). **Date:** 2026-09-10. **Mode:**
read-only static assessment. No orders placed, no `--once`/REAL run, no service
touched, **no call was made against the OANDA venue** — every venue-side
statement below is inferred from the local mirror (`data/fx_ledger.jsonl`), the
lane logs, and the code that writes them.

**Label discipline used below.** `VERIFIED` = read at `file:line` (or derived by
a read-only computation over the ledger/logs, stated as such). `READ-FROM-DOCS` =
repo docs or issue text, not independently re-derived. `CLAIMED` = asserted in
prose with no source read here. `SHOULD-VERIFY (probe X)` = cannot be settled
without an act this ticket forbids (a venue call, a `--once` run, or a heavy
probe).

**Sandbox limits (VERIFIED).** This session runs under `bwrap … --unshare-pid`
(`ps aux` shows only the sandbox's own 5 processes). Therefore **no claim about
which project process is currently running is made anywhere in this report** —
`ps`-based runtime state is unverifiable here. One limitation *from sibling
report #236 is lifted*: `crontab -l` is pam-denied, but the live crontab file
`/var/spool/cron/mrc` is `mrc`-owned mode 600 and was read directly, so the
schedules below are `VERIFIED` from the live file, not read-from-docs.

---

## Scope

**In scope.** The end-to-end FX live-lane surface on one OANDA **practice**
account: every cron/systemd job that can place or cancel an order, its real
schedule, the `--once`=REAL / no-flag=dry contract and its call sites, the
attribution of tagless `venue-reconciliation` fills by fill size, and the
consequences of both for the account and for the lane evidence.

Order-capable FX runners on this box (`VERIFIED` by `place_order(` call sites):

| Module | Lines | Order calls |
|---|---|---|
| `strategies/fx_runner.py` | 587 | `:394` close (daily, no tag), `:429` open `tag="mom-k5"`, `:507` close (intraday), `:547` open `tag="h1-mom"` |
| `strategies/fx_challenger.py` | 201 | `:106` close, `:160` open `tag="c08-fade"` |
| `strategies/fx_watchdog.py` | 124 | `:89` flatten `tag=info["owner"]` |
| `strategies/fx_crashtest.py` | 256 | `:161` close, `:193` open `tag="crash"` (**lane retired**, see below) |
| `strategies/fx_h1rev.py` | 158 | `:86` close, `:133` open `tag="h1-rev"` |
| `strategies/fx_h4brk.py` | 150 | `:80` close, `:126` open `tag="h4-brk"` |
| `strategies/fx_d1mom10.py` | 183 | `:117` close, `:149` open `tag="d1-mom10"` |
| `strategies/fx_expert_lane.py` | 425 | `:376`, `:395` `tag=my_tag` (fxexp-g137/g138/g151) |
| `strategies/fx_trail_check.py` | 170 | `:109` per-tradeID close (**not in cron**; called from the expert lane and runnable standalone) |

**Out of scope.** The crypto paper lane (AGENTS.md §"The FX arm": out of scope
until the human re-opens it). `strategies/fx_shadow.py`, `strategies/fx_warden.py`,
`strategies/lanes.py`, `scripts/proposal_loop.py`, `scripts/document_bugs.py` and
`data/accumulator_run.sh` were each checked for order placement and contain none
(`VERIFIED`: no `place_order(` and no `"POST"` in them; the Warden issues GETs
only — `fx_warden.py:141-163`, `:687`, `:774`).

---

## Verified findings (file:line)

### 1. The box runs on US/Central — every documented schedule is 5 h off

`VERIFIED`: `/etc/localtime -> /usr/share/zoneinfo/US/Central`; `date` =
`Thu Sep 10 03:54:05 PM CDT 2026`. The crontab carries no `CRON_TZ`, and cronie
runs (active since 2026-09-07), so every crontab time is **local (CDT, UTC−5)**.

Actual firing times, `VERIFIED` from log mtimes (`ls --time-style=full-iso`, all
`-0500`):

| Log | mtime | Cron line |
|---|---|---|
| `data/logs/fx_runner.log` | `2026-09-09 17:10:12 -0500` | `10 17 * * 1-5` |
| `data/logs/fx_challenger.log` | `2026-09-09 17:25:06 -0500` | `25 17 * * 1-5` |
| `data/logs/fx_intraday.log` | `2026-09-10 15:00:02 -0500` | `0 * * * 1-5` |
| `data/logs/fx_watchdog.log` | `2026-09-10 15:45:10 -0500` | `*/15 * * * 1-5` |
| `data/logs/fx_expert_lane.log` | `2026-09-09 21:45:05 -0500` | `45 21 * * 1-5` |

Consequently these documented schedules are wrong by the UTC−5 offset:

| Source | Says | Actually fires (`VERIFIED`) |
|---|---|---|
| `AGENTS.md:74-75`, `docs/CONTEXT.md:343` | mom-k5 daily **17:10 UTC** | 17:10 CDT = **22:10 UTC** |
| `docs/CONTEXT.md:344` | c08-fade daily 17:25 | 17:25 CDT = 22:25 UTC |
| `docs/CONTEXT.md:344-345` | h1-mom hourly :00 | :00 UTC — correct by accident (whole-hour offset) |
| `tui/index.js:408` (human's TUI text) | fxexp "rebalances every 5 trading days at 21:2x **UTC**" | 21:2x **CDT** = 02:2x UTC next day |
| `data/economic_calendar.py:216` (comment inside the entry gate) | "the daily 17:10 UTC run" | 22:10 UTC |

**Risk consequence.** `10 17 * * 1-5` fires Friday 17:10 CDT = **Friday 22:10
UTC**. Spot FX closes Friday 17:00 ET = 21:00 UTC (`CLAIMED` — standard market
hours, not re-derived here). If that holds, the Friday mom-k5 run orders into a
closed market once a week. `SHOULD-VERIFY (probe: place-a-day's bar/timestamp
audit of the Friday 22:1x UTC run, or a read-only OANDA instrument-status check)`.

### 2. Job inventory — every FX job that can place orders, as actually installed

Live crontab `/var/spool/cron/mrc` (`VERIFIED`; line numbers are of that file).
Times are local CDT; UTC = local + 5 h.

| Line | Schedule (local) | Job | Lane tag | Order-capable |
|---|---|---|---|---|
| 11 | `10 17 * * 1-5` | `fx_runner --once` | `mom-k5` | YES — 100 u entries + closes |
| 19 | `0 * * * 1-5` | `fx_runner --intraday --once` | `h1-mom` | YES — 2000 u entries + closes |
| 22 | `25 17 * * 1-5` | `fx_challenger --once` | `c08-fade` | YES — 100 u entries + closes |
| 28 | `*/15 * * * 1-5` | `fx_watchdog --once` | any except `crash` | YES — **closes only** |
| 33 | `30 * * * 1-5` — **COMMENTED OUT** | `fx_crashtest --once` | `crash` | **RETIRED 2026-09-03** (human decision, comment at crontab:31); re-arm = uncomment |
| 39 | `15 * * * 1-5` | `fx_h1rev --once` | `h1-rev` | YES — 2000 u (`fx_h1rev.py:38`) |
| 40 | `30 */4 * * 1-5` | `fx_h4brk --once` | `h4-brk` | YES — 2000 u (`fx_h4brk.py:38`) |
| 41 | `30 17 * * 1-5` | `fx_d1mom10 --once` | `d1-mom10` | YES — 2000 u (`fx_d1mom10.py:42`); has **never produced a ledger row** (0 rows, §12) |
| 43 | `25 21 * * 1-5` | `fx_expert_lane --expert g151 --once` | `fxexp-g151` | YES — var-size, **no SL/TP** (`fx_expert_lane.py:20-21`) |
| 44 | `35 21 * * 1-5` | `fx_expert_lane --expert g138 --once` | `fxexp-g138` | YES — var-size, no SL/TP |
| 45 | `45 21 * * 1-5` | `fx_expert_lane --expert g137 --once` | `fxexp-g137` | YES — var-size, no SL/TP |
| 12 | `20 17 * * 1-5` | `fx_shadow --apply` | — | **NO orders** (`fx_shadow.py:18` "PURE PAPER: this module places NO orders"; confirmed by call-site grep) |
| 13 | `35 18 * * 1-5` | `shadow_driver --once` | — | no `place_order` in the module (`VERIFIED`) |
| 5 | `30 18 * * 1-5` | `strategies.lanes --write` | — | no order code (`VERIFIED`) |
| 4 | `30 14 * * 1-5` | `data/accumulator_run.sh` | — | no order code (`VERIFIED`) |
| 16 | `0 9 * * 6` | `scripts/fetch_exog.py` | — | data only |
| 25 | `30 9 * * 0` | `scripts/proposal_loop.py --n 10` | — | no order code (`VERIFIED`) |
| 36 | `0 19 * * 1-5` | `scripts/document_bugs.py` | — | log scraper only |
| 8 | `0 8 * * *` | `/home/mrc/jobhunt/run_daily_scout.sh` | — | unrelated project |

**Eleven FX order-capable cron invocations per weekday** (10 active lanes + the
retired crash line), plus the watchdog's 96 runs/weekday.

**No FX systemd job exists.** `VERIFIED`: no `fx`/`oanda` unit on disk
(`/etc/systemd/system`), and the only OpenTrader units
(`opentrader-harness/gpu-sync/gpu-scheduler/llama-gpu0/llama-gpu1.service`) are
masked to `/dev/null`. `docs/systemd/opentrader-dashboard.service` is a repo copy
of an uninstalled unit; it passes no `--host`, but `dashboard.py:1208-1209`
defaults to `127.0.0.1`, so the loopback invariant claimed by the `opentrader`
launcher (`opentrader:3-4`, `:30`) holds either way (`VERIFIED`).

**Backup drift.** `~/.cache/crontab/crontab.bak` (the postmortem's recorded
backup, `docs/agents/postmortem-2026-08-31.md:55`) has **41 lines and predates
the fxexp lanes**; the live crontab has 45, adding lines 42-45 (the three
expert lanes). Restoring that backup would silently delete the three live
expert lanes (`VERIFIED` by diffing the two files).

### 3. The `--once` contract: no cron violation, but the token is overloaded

Contract (`AGENTS.md:78-79`, `fx_expert_lane.py:10-11`): *`--once` means REAL
mode; no flag = dry. Never pass `--once` to "test".*

Implementation is uniform across every FX runner and is the identity
`dry = "--once" not in sys.argv`: `fx_runner.py:567`, `fx_watchdog.py:110`,
`fx_challenger.py:187`, `fx_crashtest.py:242`, `fx_h1rev.py:153`,
`fx_h4brk.py:145`, `fx_d1mom10.py:178`, `fx_expert_lane.py:420` (via
`dry="--once" not in args`), `fx_trail_check.py:169`. `VERIFIED`.

**Verdict on call sites: no violation.** Every cron line that can place an order
passes `--once` (crontab:11, 19, 22, 28, 39, 40, 41, 43, 44, 45), and every cron
line that omits it either places no orders (`12`, `13`) or is not an FX runner
(`4`, `5`, `16`, `25`, `36`). The failure mode of forgetting the flag is
therefore *silence* (a dry run that logs "would OPEN"), not an accidental order.
`VERIFIED` by the table in §2 plus the identity above.

Three residual hazards, all `VERIFIED`:

1. **`--once` does not mean the same thing repo-wide.** In `shadow_driver.py:163`
   it is an argparse flag meaning "do one accrual cycle" (paper), and the same is
   true of `training/watchdog.py:148`, `setup_search/gpu_scheduler.py:159`,
   `setup_search/evolution.py:389`, `setup_search/shadow_live.py:164`,
   `tools/c2_platform_transmit.py:122`. Only the FX runners bind the token to
   real order flow. An operator who learns "`--once` = run once" from any of
   those will place real FX orders when they apply it to a lane.
2. **`fx_shadow` uses a third flag (`--apply`)** for its non-dry mode
   (`fx_shadow.py:49`, `:361`). Harmless today because it cannot trade, but it
   breaks the "one token, one meaning" property the contract relies on.
3. **`strategies/fx_trail_check.py:168-169` is a standalone live entry point with
   no lock and no cron line** — `python3 -m strategies.fx_trail_check --once`
   runs `run_all(dry=False)` and issues real per-tradeID closes across every
   fxexp lane (`:109`). Any operator applying "run it once to see" to this module
   places real closes (§10 for the additional defect in that path).

### 4. Tagless `venue-reconciliation` fills — five matchers, and what breaks

`fx_runner._reconcile` stamps a tag when it can resolve one (`fx_runner.py:298-308`:
the fill's own order tag, else the closed trade's opening-chain tag), and the
comment records the intent that the size matcher survives "only for legacy
(pre-2026-09-03) rows" (`fx_runner.py:308`). **That intent is not met.**

Ledger census over `data/fx_ledger.jsonl` (1003 rows, `VERIFIED` by computation):

- `venue-reconciliation` rows: **187** — **58 tagged, 129 tagless**.
- Tagless rows by date: 08-31 **8**, 09-02 **13**, 09-03 **12**, 09-08 **1**,
  **09-09 88, 09-10 7**.
- ⇒ **96 of the 129 tagless rows (74%) were written after the 09-03 upgrade**,
  i.e. in the era the code claims is tag-attributed.
- 10 of the 129 are exact duplicates of an already-recorded runner row (§9);
  119 exist in the ledger *only* as tagless venue rows.

**The size matcher is in five places, not two** (the docs name `fx_crashtest.py`
and `tui/index.js` — `AGENTS.md:76-77`, `docs/CONTEXT.md:347-350`):

| # | Site | Rule | Consumer |
|---|---|---|---|
| 1 | `tui/index.js:108-111` | `q>=5000→crash`, `q>=2000→h1-mom`, `q>0→mom-k5` | the human's TUI lane scoreboard (`laneStats`, `:84`) |
| 2 | `tui/index.js:456` | same rule | TUI fill stream |
| 3 | `dashboard.py:612-617` | same rule + a pre-08-31 `"legacy-smoke"` bucket | `/api/fx-lanes` per-lane realized, from venue `pl` |
| 4 | `tui.py:79-89` (`attribute_lane`) | same rule | `tui.py:99 ledger_performance` — and **the dashboard imports it** (`dashboard.py:636 from tui import ledger_performance`) for rounds/winrate |
| 5 | `scripts/build_accrual_store.py:143-145` | same rule + `"legacy-smoke"` | the **accrual store `fills.tag`** — the experts' evidence base |
| (6) | `fx_crashtest.py:78-85` | `abs(units)==5000 and units<0` | the crash lane's realized (lane retired; the code's own warning at `:78-79` says the matcher "must grow a tag filter" if another lane ever trades 5000) |

Where it breaks, concretely:

- **Every 2000 u lane collapses into `h1-mom`.** `h1-rev`, `h4-brk` and
  `d1-mom10` are all `UNITS = 2000` (`fx_h1rev.py:38`, `fx_h4brk.py:38`,
  `fx_d1mom10.py:42`). A tagless 2000 u close from any of them is credited to
  h1-mom. The ledger already contains 14 tagged `h1-rev` 2000 u venue rows
  (`VERIFIED`), which is exactly the population that would be miscredited if the
  tag resolution had failed on them.
- **`c08-fade` can never receive a tagless close.** `tui/index.js:111` sends every
  `q>0` remainder to `mom-k5` even though its own comment says "mom-k5/c08 100u"
  (`:104`). A 100 u c08 server-side SL/TP close is labelled mom-k5.
- **Any variable-size lane is split arbitrarily at 2000.** The fxexp lanes size by
  `target = round(w * 2000 * ncap / usd_per_base(sym))` (`fx_expert_lane.py:320`),
  which produces legs from dust to thousands of units. Observed tagless sizes
  include 2, 52, 138, 207, 621, 945, 1171, 1273, 1629, 1831, 2270, 2291
  (`VERIFIED`, sized histogram of the 129). Of the 09-08→09-10 tagless rows, **82
  land in the `mom-k5` bucket (<2000 u) and 14 in the `h1-mom` bucket (≥2000 u)** —
  neither of which is where the churn was: the same three days carry **697
  `rank-rebal` rows, all belonging to the fxexp lanes** (`VERIFIED`: 09-08 238,
  09-09 366, 09-10 93), i.e. the ledger's dominant activity in that window is
  attributed, by the fallback, to two lanes that barely traded.
- **A lane resize breaks it silently.** If mom-k5 moved from 100 u to 2000 u its
  closes would be credited to h1-mom; if h1-mom dropped to 1000 u its closes
  would be credited to mom-k5; a *partial* close (any lane's) lands in whichever
  bucket its remainder size matches. Nothing in the code detects the resize.
- **`fx_crashtest.py:85` mis-attributes any 5000 u fill** that is not the crash
  lane — reachable if an fxexp leg reaches 5000 units (needs |w|·2000/price ≥ 5000,
  i.e. |w| ≥ 2.5 — `SHOULD-VERIFY (probe: max leg size across `lane_state_g*.json`)`).

Downstream effect on the two consumers that matter:

- **The accrual store** (site 5) persists these tags into a `fills` table
  (`build_accrual_store.py:148-153`) that is the experts' training/gating
  evidence base — so a misattributed tag is not cosmetic UI, it is an input to
  per-lane metrics.
- **The TUI lane table** (site 1): reproducing `laneStats`' exact logic in Python
  over the ledger gives per-lane realized
  `h1-mom −29.55 · crash(−FIFO) −20.44 · reconciled −17.18 · fxexp-g137 −4.51 ·
  fxexp-g151 −4.00 · mom-k5 −2.12 · c08-fade −0.45 · fxexp-g138 −0.33 · h1-rev
  +0.00` (Σ −78.58). `VERIFIED-REPRODUCTION` — this is a re-implementation of
  `tui/index.js:84-142` (with `tui.py`'s identical FIFO), not the TUI itself; it
  relies on the same public ledger file. Two conclusions survive regardless of
  the tie-breaking details: mom-k5's number is built almost entirely from
  fallback-attributed rows (its own rows are just 4), and h1-mom/h1-rev carry
  volumes that the code shows belong elsewhere.

### 5. The watchdog cannot flatten a short — ACTIVE, and visible in the log

`fx_watchdog.py:63-66`:

```python
net = _venue_net(ex, sym)                      # SIGNED (lu + su)
if not net or abs(net - info["units"]) > 1e-9: # info["units"] is abs(currentUnits)
    print(f"[wd] {sym}: venue net {net} != book {info['units']} — deferred")
```

`_venue_book` stores `abs(currentUnits)` (`fx_runner.py:104`) while `_venue_net`
returns the **signed** net (`fx_runner.py:114-124`). For any short position
`net = −U`, `units = +U`, so `abs(net−units) = 2U` and the watchdog **defers
every short, every cycle, forever**. Live evidence in
`data/logs/fx_watchdog.log`: `USD_JPY: venue net -1241.0 != book 1241.0 —
deferred`, `GBP_JPY: venue net -1272.0 != book 1272.0 — deferred`, while longs
(`GBP_USD (fxexp-g151) long adverse 0.98xATR`) are evaluated normally.

This matters because the fxexp lanes are the only lanes that take shorts —
their ledger rows are 45% SELL (`rank-rebal` sides: g137 127 BUY/98 SELL, g138
124/99, g151 128/121, `VERIFIED`) — and those lanes deliberately carry **no
server-side SL/TP** (`fx_expert_lane.py:20-21`). Short fxexp exposure therefore
has *no* protection of any kind: no venue stop, and a watchdog that provably
cannot act on it. The same `abs(net − units)` shape appears latent in
`fx_runner.py:384`, `fx_challenger.py:95`, `fx_crashtest.py:148` and
`fx_runner.py:494` (`abs(net − 2000)`); those lanes only open BUY today, so the
bug is dormant there — until any of them takes a short.

A second, quieter deferral: `AUD_USD: venue net 1299.0 != book 1298.0 — deferred`
in the same log. A **one-unit** drift permanently disables the watchdog for that
symbol (`VERIFIED` log line; the 1-unit source `SHOULD-VERIFY`).

### 6. `_ensure_protection` reports "restored" when the re-attach failed

`fx_runner.py:147-152`:

```python
r = ex._request("PUT", f"/v3/accounts/{ex._account_id}/trades/{info['trade_id']}/orders", …)
ok = "stopLossOrderTransaction" in r or "stopLossOrderRejectTransaction" not in r
print(f"[fx] protection {'restored' if ok else 'FAILED'} on {sym} …")
```

`_request` returns `{}` on network/JSON failure (`exchange/oanda.py:136-139`) and
`{"_error": <venue body>, "_status": 400}` on an HTTP error (`:128-135`) — the
venue's `stopLossOrderRejectTransaction` key lands *inside* `_error`, never at the
top level. So for **both** a dead network and a venue rejection, the second
disjunct is `True` and the log line says **"protection restored"**. The only way
`ok` is False is a 200 response that contains `orderFillTransaction`-style keys
but not `stopLossOrderTransaction` — hard to produce.

Blast radius: `_ensure_protection` is called on every run for every book position
of mom-k5 (`fx_runner.py:359-360`), c08 (`fx_challenger.py:81-82`) and d1-mom10
(`fx_d1mom10.py:95`). A position that lost its SL/TP can therefore be logged as
re-protected while remaining naked, and nothing else re-checks it. The
"UNPROTECTED and no levels available — manual attention" branch at `:143` is the
only honest failure signal, and it fires only when price *and* ATR are missing.

Also `VERIFIED`: `fx_challenger.py:82` calls `_ensure_protection(…, hint={}, …)` —
an empty hint dict, so a re-attach always prices the stop off *current* price and
ATR rather than the original entry levels, i.e. the self-heal can silently move a
stop. (d1-mom10 passes a real hint, `fx_d1mom10.py:95`.)

### 7. fxexp lanes: no venue protection by design, no lock, and a latent `NameError` mid-rebalance

- **No SL/TP.** `fx_expert_lane.py:20-21`: "no server-side SL/TP (the backtest
  holds to rebalance); lane-initiated closes only". Both market-order paths
  (`:376`, `:395`) pass no `stop_loss`/`take_profit`. Combined with §5, short
  legs have no protection at all. The TUI displays this honestly per position
  (`tui/index.js:428` prints `SL✗!`), and `fx_runner.log`'s last line shows the
  book at `protection: {'EUR_USD': True, 'AUD_USD': False, 'USD_CAD': False,
  'USD_JPY': False, 'GBP_JPY': False, 'USD_CHF': False}` — one protected position,
  five naked (`VERIFIED` log line).
- **No lock.** `O_CREAT|O_EXCL` locking exists in `fx_runner.py:571-583`,
  `fx_watchdog.py:112-120`, `fx_challenger.py:189-197`, `fx_crashtest.py:244-252`
  and nowhere else. `fx_expert_lane.py`, `fx_h1rev.py`, `fx_h4brk.py`,
  `fx_d1mom10.py`, `fx_trail_check.py` and `shadow_driver` have none. Three
  expert lanes overlap by design (distinct tags), but a manual `--force` run
  concurrent with cron — the exact intervention map #218 records for 09-09→10 —
  can double-trade the same period: the period guard at `fx_expert_lane.py:252`
  reads `lane_state_{expert}.json`, which is only written *after* all orders
  (`:405-409`).
- **Latent `NameError` at `fx_expert_lane.py:373`.** The flip-remainder branch
  uses `net` before the only binding of that name in `run()` (`net = m + f_units`
  at `:384`, in the later add/open branch): `if f_units != 0 and net != 0 and …`.
  Python short-circuits on `f_units != 0`, so this is dormant while no foreign
  lane holds the symbol — and crashes the lane the moment one does, **after**
  orders in the same loop have already been sent and **before** `_append_ledger`
  (`:404`) and the state write (`:409`). That is precisely the signature of the
  119 ledger-orphan venue fills in §4: real orders, no runner rows.
  `SHOULD-VERIFY (probe: grep a historical lane log for `NameError: name 'net'`)`;
  the equivalent crash *was* real once — `data/logs/fx_expert_lane.log` carries
  `NameError: name 'check_simulated_exits' is not defined`, which map #218/#220
  records as fixed by renaming to `check_trails` (`fx_expert_lane.py:49`, `:253`).
- **`refresh_store` runs before every real rebalance and rebuilds a shared
  panel.** `fx_expert_lane.py:237-238` calls `refresh_store(ex)` only when not
  dry; that function opens `/home/mrc/opentrader-data/store.duckdb` **read-write**
  (`:102`), DELETE+INSERTs bars for every symbol, sleeps 0.25 s per call, then
  rebuilds `data/fx_expert/panel.npz` (`:126`). Three lanes 10 minutes apart share
  that artifact; the freshness gate is a single EUR_USD probe (`:133-144`), so a
  stale panel for a non-EUR pair passes the gate.

### 8. `fx_trail_check` closes *other* lanes' trades and stamps them with the caller's tag

`fx_trail_check.py:62`:

```python
fx = [t for t in trades if ((t.get("clientExtensions") or {}).get("tag") or "").startswith("fxexp-")]
```

The function's `my_tag` argument (`:58`) is **not** used in that filter, yet the
close it writes is stamped `"tag": my_tag` (`:116`). Since the lanes call it in
sequence (`fx_expert_lane.py:253`; `run_all` at `:131-144` loops g151→g138→g137),
whichever lane runs first evaluates **every** fxexp trade and books a triggered
g138/g137 close as its own. Peel-aware in principle (the loop is per tradeID and
`check_trails` uses the trade's own direction, `:71-100`), but the lane evidence
is misfiled by construction. No `trail-close` rows exist in the ledger yet
(`VERIFIED`: 0 of 1003), so this is latent — it fires the first time a trail
triggers.

### 9. Per-tradeID closes are recorded with `price = 0.0`, which breaks the reconcile dedup

`fx_expert_lane._record(sym, side, qty, price=0.0, oid="")` (`:306`) is called from
the close path as `_record(sym, side, c, oid=tid)` (`:368`) — **no price**. Result
(`VERIFIED` by computation): **128 `rank-rebal` rows carry `price == 0.0`** (g151
59, g138 29, g137 40), plus 3 `intraday-momentum` rows. `fx_runner._reconcile`
dedups a venue fill against existing rows by `symbol, side, quantity, price within
1e-9, timestamp within 5 s` (`fx_runner.py:274-277`). A stored `price = 0.0` can
never equal the venue's price, so **the same economic fill is appended twice**:
once as the `rank-rebal` row (price 0.0, tagged) and once as
`venue-reconciliation` (real price, tagless when the tag chain misses). `VERIFIED`:
10 tagless venue rows are exact symbol/side/quantity duplicates of a `rank-rebal`
row ≤5 s apart — so the dedup failed on price alone, not on time.

Two knock-on effects: the duplicate is attributed by size (§4), and the TUI's
FIFO drops the original because `tui/index.js:121` skips any row with a falsy
price — so the leg is invisible in the lane bucket that owns it while a
mis-attributed copy is counted elsewhere.

### 10. The ledger's own schema, as written

`VERIFIED` by enumerating the keys of all 1003 rows:

| reason | rows | keys |
|---|---|---|
| `rank-rebal` (fxexp) | 697 | timestamp, symbol, side, quantity, price, order_id, reason, `tag` |
| `venue-reconciliation` | 187 (58 tagged) | same 8 (tag present only on the 58) |
| `intraday-momentum` | 54 | timestamp, symbol, side, quantity, price, order_id, reason, `sl`, `tp` |
| `crash-entry` | 22 | + `paper`, `mid_before`, `slippage`, `tag` |
| `h1-rev-rsi2` | 21 | + `sl`, `tp` |
| `phantom-void` (correction) | 7 | timestamp, `detail`, `ticket`, `voids` |
| `intraday-max-hold-12h` | 5 | no sl/tp/tag |
| `h1-rev-maxhold` | 4 | idem |
| `momentum-entry` | 3 | + `sl`, `tp` |
| `out-of-target` | 1 | idem |
| `crash-12h-hold` | 1 | + `paper`, `tag` |
| `c08-entry` | 1 | + `sl`, `tp` |

Two schema defects: `tag` exists on only 4 of the 12 reason classes, and
`fx_runner.py:296` sets `"order_id": t.get("transactionID")` — the venue journal
field is `id`, so **every venue-reconciliation row has `order_id: null`**
(`VERIFIED`: all 187), removing the one stable identity a reconcile row could
carry and leaving 5-second tolerance matching as the only dedup. Note also that
`h4-brk` and `d1-mom10` have **zero** rows in the 1003 — the H4 breakout and the
D1-10 sibling have never traded (`VERIFIED`; `fx_d1mom10.log` and `fx_h4brk.log`
are "no signal" output only).

### 11. The watchdog's own rows are not in the schema it is read by

`fx_watchdog.py:93-98` writes `"owner": info["owner"]` — not `"tag"`. Every
consumer keys on `tag` (`tui/index.js:95`, `tui.py:66`, `dashboard.py:606`), so a
watchdog flatten would fall through to the reason branch (`reason.startswith
("watchdog")` — present at `tui/index.js:99`, absent from `tui.py:59-89`'s reason
list) or to `reconciled`. No `watchdog-shock-flatten` row exists yet
(`VERIFIED`: 0 of 1003; the log ends `cycle done: 0 flattening(s)`), so this is
latent.

### 12. Three more reading defects in the human's TUI lane table

`VERIFIED` in `tui/index.js`:

- **`laneStats` has no branch for `h1-rev`, `h4-brk` or `d1-mom10`** (`:94-114`),
  while the lane table renders rows for all three (`:394`). Their reason-tagged
  rows therefore land in the `reconciled` catch-all: 21 `h1-rev-rsi2` + 4
  `h1-rev-maxhold` = **all 25 h1-rev rows** go to `reconciled`, while its 14
  tagged venue closes go to `h1-rev` (which then has no opens to pair against and
  reads 0.00). The fill stream in the *same file* does map them (`:453-455`) — the
  two attributions disagree inside one artifact.
- **Short legs are invisible.** `:125` requires `book.qty > 1e-9` before matching a
  SELL, so a SELL that opens a short is dropped and its later covering BUY is
  counted as a new long. The dollar-neutral fxexp books (~45% shorts) are
  therefore long-only in the TUI's realized column.
- Both are shared with `tui.py:126-140`, which the dashboard calls for rounds and
  winrate (`dashboard.py:636`).
- `tui/index.js:129` converts quote-currency PnL to USD by dividing by **the exit
  price of the pair itself** (`pnl / price`). That is correct only for USD-base
  pairs (for `USD_JPY`, `price` *is* the USD_JPY rate). For a cross, the quote
  PnL must be divided by the **quote→USD** rate, not by the pair's own price: a
  `GBP_JPY` leg is divided by GBP_JPY instead of USD_JPY, so the divisor is too
  large by the GBP_JPY/USD_JPY ratio and the reported USD PnL comes out **low**
  (direction `VERIFIED` from the formula; the magnitude is level-dependent and
  not computed here). Same defect at `tui.py:134-135`.

---

## Health assessment

**What is sound.** The adapter's truthfulness contract holds: `place_order`
returns `rejected` with `price=0` whenever the venue response has no
`orderFillTransaction` (`exchange/oanda.py:400-421`), so a cancelled or refused
POST cannot enter a ledger. Every order-capable runner passes a lane `tag` on its
entry path, and the venue-account book is read from `openTrades` rather than from
a cache in every lane (`fx_runner.py:91-111`). No cron line violates the
`--once` contract, and no FX job is scheduled from systemd. The crash lane is
genuinely retired (only the config comment remains). The `--once` default is
fail-safe in the correct direction: forgetting it produces a dry run.

**What is not.** Three things dominate.

1. **The documented lane model no longer describes the running system.** The
   docs describe five lanes; eleven order-capable cron invocations run, four of
   them added 09-03 and three on 09-06 (`AGENTS.md:74-77`, `docs/CONTEXT.md:342-350`).
   Every documented time is 5 h off (§1). The attribution mechanism the docs
   describe as "if a lane resizes, the matcher breaks" has *already* broken in
   the other direction: it is not the lane that resized, it is three new
   2000 u lanes plus a variable-size trio that the matcher cannot distinguish
   (§4). The ledger agrees: 96 of 129 tagless rows postdate the upgrade that was
   supposed to retire the matcher.
2. **Protection of the newest, largest lanes is nominal.** The fxexp lanes carry
   no venue stops by design, take shorts, churn (697 ledger rows in three
   trading days,
   ≈$99.6k practice balance, `fx_expert_lane.log`), and the only out-of-band
   protection — the watchdog — is provably unable to act on a short (§5). The
   one self-healing path that could re-attach a stop reports success when it
   failed (§6).
3. **The lane evidence base is contaminated at the source.** Misattributed tags
   are not only rendered (TUI, dashboard) but *persisted* into the accrual
   store's `fills.tag` (§4 site 5), which is the corpus the expert metrics and
   the Friday scoreboard read. The 128 `price = 0.0` rows (§9) additionally
   double-book 10 fills in the ledger.

**Risk to a live account today: none directly — `data/fx_expert_lane.log` records
`balance $99,619.63`, an OANDA practice account (verified line; AGENTS.md:67
"demo money").** The material risk is that the three items above are all
*state-independent*: none of them is caused by the account being practice, and
each converts directly into money loss the moment this book is funded — naked
short exposure with a disabled watchdog, a self-heal that lies, and lane-level
PnL that a promotion decision would be made on.

---

## Defects & risks

Ranked by (risk to account once funded) × (probability of firing in the next
week).

| # | Severity | Defect | Evidence | Risk-to-account |
|---|---|---|---|---|
| D1 | **High** | Watchdog defers every short position (signed `net` vs `abs(units)`) | `fx_watchdog.py:63-66`; live log `USD_JPY venue net -1241.0 != book 1241.0 — deferred` | Short fxexp legs (45% of their flow) have no venue stop *and* no watchdog. A gap event on a short is unbounded in the book's own terms. |
| D2 | **High** | `_ensure_protection` logs "protection restored" on a failed/rejected PUT | `fx_runner.py:147-152` with `oanda.py:128-139` response shapes | A position believed protected is naked; no other code path re-checks. Fires whenever the venue rejects an SL/TP re-attach. |
| D3 | **High** | Tagless venue fills are size-attributed; 96 post-upgrade rows, miscredited in 5 consumers incl. the accrual store | `tui/index.js:108-111`, `dashboard.py:612-617`, `tui.py:79-89`, `build_accrual_store.py:143-145`, `fx_crashtest.py:85`; ledger census §4 | Per-lane realized/MFE/scoreboard wrong at the source; promotion and cut decisions read these. |
| D4 | **High** | Latent `NameError` on the fxexp flip path → run aborts after orders, before ledger/state write | `fx_expert_lane.py:373` vs `:384`; the §4 orphan population (119 tagless-only fills) has this shape | Real fills with no runner record; a re-run then re-derives deltas from the venue, so PnL is recoverable but lane evidence is not. |
| D5 | Medium-High | `price = 0.0` on 128 per-tradeID close rows defeats the reconcile dedup → double-booked fills | `fx_expert_lane.py:306`, `:368`; `fx_runner.py:274-277`; 10 verified duplicates §9 | Ledger no longer a faithful 1:1 mirror of venue fills; FIFO PnL in TUI/tui.py skewed (original row skipped at `tui/index.js:121`). |
| D6 | Medium-High | `fx_trail_check` closes every fxexp lane's trades and stamps them with the calling lane's tag | `fx_trail_check.py:62` vs `:116`; `fx_expert_lane.py:253` | Lane evidence misfiled at the first trail trigger; also a cross-lane close the arbitration rules elsewhere forbid. |
| D7 | Medium | No lock in `fx_expert_lane` (3 lanes + manual `--force`) nor in `--intraday`; the daily path is locked | locks only at `fx_runner.py:571-583`, `fx_watchdog.py:112`, `fx_challenger.py:189`, `fx_crashtest.py:244` | Double-run double-orders. The lock exists because a double-run already caused the 2026-09-01 FIFO incident (`fx_runner.py:571-572`). |
| D8 | Medium | One-unit venue/book drift permanently disables the watchdog for that symbol | `fx_watchdog.log` `AUD_USD venue net 1299.0 != book 1298.0 — deferred` | Same class as D1: silent loss of protection. |
| D9 | Medium | Every documented schedule is 5 h off; Friday's daily run lands after the FX week closes | `/etc/localtime`, log mtimes, `crontab:11`; `AGENTS.md:74-77`, `CONTEXT.md:343`, `tui/index.js:408`, `economic_calendar.py:216` | Friday orders into a closed market; calendar/blackout reasoning built on the wrong clock. |
| D10 | Medium | `--once` means "REAL orders" only in FX runners; it means "paper, run once" in 6 other modules; `fx_shadow` uses a third flag | `shadow_driver.py:163` et al.; `fx_shadow.py:361` | The one operator-error guard in the lane design does not generalise. |
| D11 | Low-Medium | `fx_trail_check` is a live, unlocked, unscheduled entry point | `fx_trail_check.py:168-169` | A "just run it once" test places real closes across all fxexp lanes. |
| D12 | Low-Medium | `order_id` always `null` on venue rows; dedup is 5-second tolerance only | `fx_runner.py:296`; 187/187 rows | Two genuine same-price fills within 5 s are indistinguishable and one may be dropped. |
| D13 | Low | TUI lane table: `h1-rev`/`h4-brk`/`d1-mom10` rows land in `reconciled`; shorts invisible; cross-pair PnL divided by the wrong rate | `tui/index.js:94-114` vs `:394` vs `:453-455`; `:125`; `:129`; `tui.py:126-140` | The human's only per-lane view is wrong in three independent ways. |
| D14 | Low | Watchdog writes `owner=` instead of `tag=` | `fx_watchdog.py:96` | Its future rows are unattributable by every tag-keyed consumer. |
| D15 | Low | `crontab.bak` restore would delete the three expert lanes | `~/.cache/crontab/crontab.bak` (41 lines) vs live (45) | Recovery procedure regresses the live surface. |

---

## Links to existing maps

- **map #174 — Parallel FX lanes (CLOSED).** Its two binding notes are exactly
  what §4 tests: "the tradeID attribution upgrade lands BEFORE any new lane goes
  live" and "the size-based close matcher … retires when tradeID attribution
  lands". Attribution landed (`fx_runner.py:298-308`) but 96 tagless rows postdate
  it, and the retiral is uneven across six consumers. #174 also fixed the new
  lanes at 2000 u — the decision that makes `h1-rev`/`h4-brk`/`d1-mom10`
  indistinguishable from `h1-mom` in the fallback. Child **#175** (attribute
  closes by tradeID) is the upgrade in question; **#176** (no-overlap arbitration)
  is implemented in `fx_runner.py:175-203` and respected by every BUY-only lane,
  but not by `fx_trail_check` (D6).
- **map #218 — FX pipeline completion (OPEN, 8/9).** Its "Not yet specified" item
  "claims change mid-period leaves lanes misaligned … observed live 2026-09-09→10;
  fixed by manual `--force`" is the best available explanation for the 09-09/09-10
  tagless burst (88 + 7 rows) and connects to D4/D7: a manual `--force` run is
  exactly the unlocked, double-runnable path that can abort after ordering.
  #220 (the `check_simulated_exits`→`check_trails` fix) is confirmed on disk
  (`fx_expert_lane.py:49`, `:253`); the traceback remains in the log.
- **map #158 — Ledger integrity (CLOSED).** Its destination was "no local record
  claims a fill the venue lacks, every venue fill lands in the ledger mirror
  within the agreed cadence (hourly), rejected orders leave no residue". The
  direction it did *not* close is the converse, now measurable: **119 venue fills
  are in the ledger only as tagless rows with no runner record** (§4), and 10
  fills are in it twice (§9). The hourly cadence itself holds — `_reconcile` runs
  in the daily lane (`fx_runner.py:327-328`) and in the intraday lane
  (`:472-473`), so the ≤1 h bound is intact. #169's "rejected orders leave no
  residue" holds at the order call sites, but `_ensure_protection` (D2) bypasses
  it.
- **#228 / sibling reports in this directory:** `230-oanda-adapter-guards.md`
  (adapter contract), `232-fxexpert-alpha-loop.md` (panel/training/gate). **This
  report lifts one of #236's stated limitations:** #236 §0.3 records `crontab -l`
  as pam-denied and the FX cron contracts as `READ-FROM-DOCS`; `/var/spool/cron/mrc`
  is readable by its owner and the schedules in §2/§1 are `VERIFIED` from the live
  file. Where this report and #236's "doc drift" section overlap (schedule text in
  `AGENTS.md`/`CONTEXT.md`), these findings supersede for the FX lane.

---

## Open questions

Each is stated with the act it needs; none was performed here.

1. **What writes the 119 orphan fills?** `SHOULD-VERIFY (probe: for one
   2026-09-09 01:35 UTC tagless row, walk the venue journal for that transaction
   id and read `orderID`, `clientExtensions`, `tradesClosed`, `tradeOpened`).`
   The candidate causes are (a) a crashed run that ordered before
   `_append_ledger` (D4), (b) fills whose opening fill never exposed a tradeID to
   `_trade_tags` (`fx_runner.py:233-239`), (c) orders placed outside these
   runners. The evidence in hand — dust sizes of 2 and 52 units, var-size legs
   matching `w·2000/price`, and map #218's 09-09→10 manual `--force` note —
   favours (a)/(c) but does not settle it.
2. **Is the tag chain truncated by pagination?** `_trade_tags` walks
   `sinceid?id=0` and reads `r["transactions"]` without following `pages`
   (`fx_runner.py:218-220`), unlike `_txns_since` (`:161`). The reconcile cursor
   is at `last_id 4103` (`data/fx_reconcile_cursor.json`). If the venue paginates
   that response, the walk sees only part of the journal and tag resolution
   degrades as the account ages. `SHOULD-VERIFY (probe: one read-only
   `sinceid?id=0` call, compare `len(transactions)` with `lastTransactionID` and
   the presence of a `pages` key).`
3. **Does the venue net more than one open trade per instrument?** `_venue_book`
   assigns `book[sym]` per trade in a loop (`fx_runner.py:99-110`), so a second
   trade on one symbol silently overwrites the first's units — which would
   produce exactly the `AUD_USD 1299 vs 1298` drift in D8 and the watchdog's
   `book` figure generally. `SHOULD-VERIFY (probe: count openTrades per
   instrument on the practice account).`
4. **Is the Friday 22:10 UTC run in a closed market?** Needs the venue's
   instrument status / a bar-timestamp read at that hour (§1).
5. **Can an fxexp leg reach 5000 units** (which would pollute the retired crash
   lane's realized matcher if it is re-armed)? `SHOULD-VERIFY (probe: max
   abs(target) over `data/fx_expert/lane_state_g*.json` and the panel weights).`
6. **Which lane actually owns the 82 `mom-k5`-bucketed and 14 `h1-mom`-bucketed
   tagless rows of 09-08→09-10?** Answering it is what makes D3's blast radius
   exact; it needs (1) and (3).
7. **Human decision inputs, out of scope here:** should the five size matchers be
   replaced by one shared resolver (with a loud "unattributed" bucket instead of a
   silent `mom-k5` default), and should the fxexp lanes carry venue stops at all?
   Both change live behaviour and belong to the human gate.
