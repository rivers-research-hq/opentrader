# OANDA adapter + security guards — contract assessment (wayfinder #230)

**Ticket:** #230 (parent #228, cross-ref map #158).
**Date:** 2026-09-10. **Mode:** read-only static assessment. No orders placed, no
`--once`/REAL run, no service touched, nothing executed against the venue.

**Label discipline used below.** `VERIFIED` = code read at `file:line` (plus one
AST binding-order check and read-only `diff`). `READ-FROM-DOCS` = repo docs /
issue text. `CLAIMED` = asserted by a doc or commit message, not re-derived here.
`SHOULD-VERIFY` = cannot be settled without an act this ticket forbids (a venue
call, a REAL run, or a heavy probe).

---

## Scope

| Artifact | Path | Size | Git state |
|---|---|---|---|
| Live adapter | `/home/mrc/opentrader/exchange/oanda.py` | 522 L | clean, last commit `ffe3978` (2026-09-10) |
| Guards | `/home/mrc/opentrader/security/guards.py` | 183 L | clean, last commit `b5feba9` (2026-09-05) |
| Sandbox copy | `/home/mrc/opentrader-sandbox/exchange/oanda.py` | 462 L | mtime 2026-08-31 14:28 |

`VERIFIED` — `git status --porcelain` empty for both tracked files; sizes and
commit dates from `git log` / `stat`.

Contract sources: `AGENTS.md:86-96` (adapter rules + Adapter fork Q04),
`docs/ARCHITECTURE.md:111` (fork) and `:113` (no-TTL caches), ToC `Q04`/`Q05`
(`data/wayfinder/toc/TOC.md:33-34`), map #158 (closed; children #159-#173).

In scope: the four contract clauses — live/sandbox fork, `place_order`
truthfulness, `get_current_price` always-fresh, the `tag` kwarg — plus the
guard layer the adapter imports. Crypto paper lane (#159/#160/#161) untouched.

---

## Verified findings (file:line)

### 1. Clause-by-clause verdict

| Contract clause (source) | Verdict | Evidence |
|---|---|---|
| `place_order` truthful — no `orderFillTransaction` ⇒ REJECTED | **PASS** (live) | `exchange/oanda.py:410-421` |
| `get_current_price` always fetches fresh (no no-TTL cache) | **PARTIAL** | `exchange/oanda.py:243-256` |
| `tag` kwarg = ownership stamp | **PASS for market orders** (latent gap on limit/mit) | `:301-302, :331-337` vs `:345-380` |
| Live/sandbox fork as documented, no blind-sync | **ACCURATE but incomplete** | `diff` of the two files (table in §3) |
| Guards (`security/guards.py`) protect adapter egress | **FAIL as deployed** | `:13-14` defeated by `:25` |

**1a. `place_order` truthfulness — PASS (live tree).**
`VERIFIED` — `exchange/oanda.py:410-421`: the POST response at `:389-391` is
checked; when `orderFillTransaction` is absent the adapter returns
`status="rejected"`, `price=0`, extracting `orderCancelTransaction.reason` or
`orderRejectTransaction.rejectedReason` (`:411-413`) and passing
`lastTransactionID` through (`:415, :420`). An HTTP-level error short-circuits to
rejected earlier (`:392-398`). The comment at `:400-409` records the 2026-09-02
phantom-fill incident as the reason. Fill accounting only runs on the fill
branch (`:422-463`). This matches `AGENTS.md:86-89` exactly.

**1b. `get_current_price` always-fresh — PARTIAL.**
`VERIFIED` — the cache-first read is gone: `:243-254` unconditionally issues
`GET /v3/accounts/{id}/pricing?instruments={symbol}` and returns the venue price
when present (`:252-254`). The old no-TTL read path is genuinely removed.
Residual defect: `:256` `return self._price_cache.get(symbol)` — when the venue
returns nothing (any `_request` error path returns `{}` at `:136-139`, or an
error-shaped dict at `:128-135`; `_parse_pricing` at `:223-241` then yields an
empty map), the caller silently receives the last written mark. `_price_cache` is
`Dict[str, float]` (`:88`) with **no timestamp and no TTL** — writes at `:212`,
`:253`, `:270`, reads only at `:256`. The configured `_cache_ttl` (`:89`) is
consulted **only** at `:179`, for the bar cache. `_last_fetch` (`:90`) is keyed by
the bar `cache_key` (`:176, :179, :211`), never by symbol.
Sharpest path: `get_bars` writes `self._price_cache[symbol] = bars[-1].close`
(`:212`). For a `1d` request — which is what the daily runner asks for
(`strategies/fx_runner.py:334`) — that is a *daily close*, potentially ~a day
old, which `:256` can then hand out as "current price". The documented failure
mode (`AGENTS.md:89-92`: stale mark → stops set off it → `STOP_LOSS_ON_FILL_LOSS`
cancellations) is therefore narrowed but not closed, and it fails **open and
silently**: the error is logged inside `_request` (`:134, :138`) but nothing marks
the returned price as stale.

**Why the fallback is load-bearing.** `VERIFIED` — 10 lane scripts call
`get_current_price` at 13 call sites, mostly to compute attached SL/TP levels
(`fx_runner.py:140/419/542`, `fx_crashtest.py:187/216`, `fx_d1mom10.py:139`,
`fx_h1rev.py:125`, `fx_h4brk.py:120`, `fx_challenger.py:146`,
`fx_expert_lane.py:272`, `fx_watchdog.py:75`, `fx_trail_check.py:82`,
`fx_warden.py:780`) — several callers *do* handle
`None` (`strategies/fx_runner.py:142`, `strategies/fx_h1rev.py:127`,
`strategies/fx_challenger.py:150`: `if not px or not atr: … continue`), but
`strategies/fx_runner.py:419-425` does not: `px = ex.get_current_price(sym)`
followed by `sl = round(px - ATR_STOP * atr, d) if atr else None` — a `None` with
a truthy `atr` raises `TypeError`. So deleting `:256` is **not** a safe one-line
fix; the call site needs a `None` guard first (see D2).

**1c. `tag` kwarg — PASS, with a latent gap.**
`VERIFIED` — signature `:301-302` (`tag`, plus `client_id` added by `ffe3978`);
the tag is written as `tradeClientExtensions = {"id": client_id or f"{tag}-{symbol}",
"tag": tag, "comment": tag}` at `:331-337`, inside the **market** branch only. The
`limit` branch (`:345-362`) and the `mit` branch (`:363-380`) build orders with no
`tradeClientExtensions` at all. All 17 live call sites pass `"market"`
(`strategies/fx_runner.py:394/429/507/547`, `fx_crashtest.py:161/193`,
`fx_d1mom10.py:117/149`, `fx_h1rev.py:86/133`, `fx_h4brk.py:80/126`,
`fx_challenger.py:106/160`, `fx_expert_lane.py:376/395`,
`fx_watchdog.py:89`) — so the gap is latent, not active. Only
`tests/test_oanda_price_precision.py:96` exercises a limit order.

The tag is load-bearing, not cosmetic: `VERIFIED` — it is read back from venue
`openTrades` as the lane owner (`strategies/fx_runner.py:108`), and drives
no-overlap arbitration (`fx_runner.py:175-189` `held_by_other_tags`, `:192-203`
`foreign_holds`), plus `strategies/fx_warden.py:168` and
`scripts/fx_scoreboard.py:37`. Note the tag is **metadata, not an enforcement
mechanism**: OANDA nets per instrument, so the guarantee "zero cross-closing"
comes from the client-side pre-trade checks in `fx_runner.py:175-203` and
`fx_expert_lane.py:370-388` — the tag is what makes those checks possible.
`READ-FROM-DOCS` — netting consequences are map #174/#176/#177 territory.

**1d. Consumers of the mirror (why `get_balance` matters little today).**
`VERIFIED` — `get_balance()` is called only at `strategies/fx_runner.py:324` and
`strategies/fx_expert_lane.py:233`, and both use only `.cash` (`:325` and
`:234-235`), which both trees take from the venue. No FX code reads
`Balance.positions` (grep for `.positions` in `strategies/` → none), and no FX
lane calls `restore_ledger` (only `harness.py:1132` does), so in every one-shot
cron process the live adapter's local `_positions` mirror starts empty and is
populated only by orders placed in that same process. The sandbox's server-truth
positions leg is therefore real but currently unexercised (see §3, D-note).

### 2. Guard layer — installed, then uninstalled (`VERIFIED`)

`exchange/oanda.py:13` imports the guards and `:14` installs the shadow:

```
13  from security.guards import guarded_urlopen, guarded_open, guarded_requests_get, sec_pickle_load
14  urlopen = guarded_urlopen  # hardening shadow
25  from urllib.request import Request, urlopen
...
124 with urlopen(req, timeout=15) as resp:
```

Line 25 rebinds the module global `urlopen` back to stock `urllib.request.urlopen`,
and `:124` resolves that global. An AST scan of top-level bindings of the name
`urlopen` in this file returns exactly `line 14: Assign urlopen = guarded_urlopen`
then `line 25: ImportFrom urllib.request -> binds urlopen` — the last binding wins,
so the adapter's HTTP path is **unguarded**. `security/__init__.py` is empty (0 L)
and nothing monkeypatches `exchange.oanda.urlopen` afterwards (grep: no hits).

Consequences: `security/guards.py:96-106` (`validate_url`) never runs for adapter
traffic, so the SSRF allowlist (`guards.py:29-50`), the loopback/metadata
rejection (`:54-60, :80-93`) and the scheme check (`:52, :99-100`) are inert for
this file. The request host is taken from the (gitignored) keys file —
`exchange/oanda.py:102` `self._host = keys.get("host", …)` — and the Bearer token
is attached to whatever that is (`:107, :120`). A tampered/unexpected
`config/oanda_keys.json` therefore turns the adapter into an authenticated
request forwarder to an arbitrary host, including `169.254.169.254` — precisely
the class the guard exists to stop.

The other three names imported at `:13` (`guarded_open`, `guarded_requests_get`,
`sec_pickle_load`) appear **only** on `:13` in this file — dead imports.

**Not oanda-specific.** `VERIFIED` — the same AST check over every repo file that
installs the shadow: **17 of 31 files are defeated** the same way (guarded assign
followed by a later `from urllib.request import …, urlopen`): `exchange/oanda.py`,
`exchange/stock_finnhub.py`, `exchange/alpaca_paper.py`, `alpaca_paper.py`,
`harness.py` is **intact**, `data/news.py`, `data/arxiv.py`, `data/economics.py`,
`data/fundamentals.py`, `data/vix_gate.py`, `data/acquire.py`,
`data/alt_data_mcp.py`, `data/social_sentiment.py`, `agent/mcp_client.py`,
`agent/trading_agent.py`, `mot/dynamic_discovery.py`, `mot/agents/debate.py`,
`scripts/load_adapter.py`. Intact examples: `harness.py:13`, `connections.py:18`,
`dashboard.py:8`. `security/guards.py` has no tests (grep for `guards` in
`tests/` → no file).

### 3. The fork, as it actually is (`VERIFIED` via read-only `diff`)

`diff -u /home/mrc/opentrader-sandbox/exchange/oanda.py /home/mrc/opentrader/exchange/oanda.py`
→ 203 diff lines, 11 changed regions. Everything the sandbox has that live lacks
is inside **one function**; everything live has that the sandbox lacks is safety
behaviour:

| Behaviour | Sandbox (462 L, 08-31) | Live (522 L) |
|---|---|---|
| Fill truthfulness | **absent** — `orderFillTransaction` read with `or {}` and `status="filled"` returned unconditionally (`sandbox:352-396`; `:393`) | present (`:410-421`) |
| `get_current_price` | **cache-first, no TTL** (`sandbox:231-233` return cached before fetching) | always fetch (`:243-254`), stale fallback only (`:256`) |
| SL/TP price formatting | `f"{stop_loss:.5f}"` / `str(price)` (`sandbox:340, 343, 328`) | `_fmt_price` @ venue `displayPrecision` (`:275-290, :338-343`) |
| `displayPrecision` capture at connect | absent (`sandbox:156`) | present (`:156-161`) |
| `tag` + `client_id` kwargs | absent | present (`:301-302, :331-337`) |
| `get_balance().positions` | **server truth** from `account.positions` (`sandbox:415-419`) | local in-memory mirror (`:483`) |
| Guards import | absent — **the sandbox has no `security/` package at all** | present but defeated (§2) |

The sandbox is a **2026-08-31 snapshot taken before** the 09-02/09-03/09-08/09-10
landings; `VERIFIED` — `ls /home/mrc/opentrader-sandbox/security` → *No such file
or directory*, so the live file's `from security.guards import …` cannot even be
copied into the sandbox unchanged (it would `ModuleNotFoundError` at import).

**Verdict on ToC Q04's framing.** `AGENTS.md:93-96` / `ARCHITECTURE.md:111` say the
sandbox has "a server-truth `get_balance` the live tree lacks". That is
`VERIFIED` but imprecise in two ways worth recording: (i) it is the **positions
leg** that is server-truth — both copies fetch `/v3/accounts/{id}` for
`balance`/`NAV` (`live:472-479`, `sandbox:407-414`); (ii) the delta is not
symmetric — the sandbox is behind live on **three** safety behaviours (fill
truthfulness, fresh price, price precision) plus guard import. So "merging them"
is really a ~10-line **port of the positions leg into live**; the reverse
direction would reintroduce the 2026-09-02 phantom-fill bug, the hourly USD_JPY
reject loop and the no-TTL cache disease. The "do not blind-sync" rule is
correct, and the evidence now says the direction is settled by safety alone —
only the *decision* remains human-gated.

### 4. Provenance drift in the record (`VERIFIED`)

- The #158 Notes say the adapter's truthful `place_order` fix is "uncommitted,
  human-landed 09-02". It **is committed**: the truthfulness block arrived in
  `2561796` (2026-09-03, "docs(agents): bind FX arm focus …"); `ffe3978`
  (2026-09-10) added `client_id`. Working tree clean. `READ-FROM-DOCS` — no
  fixture/commit directly labelled "#167", so the mapping of the fix to a commit
  is by content (`git log -S`), not by message.
- `ARCHITECTURE.md:113` correctly warns about cache-first reads, and correctly
  scopes the remaining crypto `_price_cache`; it does not mention that the
  OANDA adapter retains a (narrower) untimestamped price fallback — see D2.

---

## Health assessment

**The live tree is the safe artifact and honours the written contract on the two
clauses that caused real money-side damage.** `place_order` truthfulness and
unconditional fresh-fetch are both implemented, documented in-line with the
incident they came from, and consumed correctly by all lanes (every lane checks
`status` before recording: `fx_runner.py:395/431`, `fx_expert_lane.py:378/397`,
and the #169 pattern). The `tag` kwarg is present and is genuinely load-bearing
for the netting-arbitration design.

**Residual risk is concentrated in three places, in this order:**
1. the guard layer is dead in the adapter (and in 16 other files) — a security
   item, not a trading item, but it is the only *confirmed* exploit-shaped defect
   found here;
2. the stale-price fallback at `oanda.py:256`, which is the same disease as the
   one the contract declares fixed, at lower probability and with no freshness
   bound;
3. the unexercised fork leg (`get_balance().positions`) plus a truthfulness branch
   with zero regression tests.

**Fork health: stable and correctly fenced.** Doc, code and the 203-line diff
agree; the sandbox is an 08-31 snapshot, not a parallel development line. No
evidence was found of anyone syncing it — `exchange/oanda.py` mtime (2026-09-08)
is older than its last commit (2026-09-10), consistent with a sweep-up commit of
already-written content rather than recent edits. Nothing here is urgent enough
to justify breaking the human gate.

**Not assessed (out of scope / not run):** whether any *venue-side* order is
currently mis-tracked (requires venue reads — `SHOULD-VERIFY`, the #173
venue-agreement check is the right instrument); live lane PnL or attribution
correctness (#174-#177); crypto lane (`exchange/live.py`).

---

## Defects & risks

Ranked. "Latent" = no current caller reaches it. Fixes are **not** applied —
this ticket is read-only.

**D1 — Hardening shadow defeated; adapter egress is unguarded. Severity:
medium-high (security).** `exchange/oanda.py:14` installs `guarded_urlopen`, then
`:25` rebinds `urlopen` to stock urllib and `:124` uses it. `validate_url` never
runs; host comes from the keys file (`:102`) with the Bearer token attached
(`:107`). Systemic: 17/31 files affected (`harness.py` is intact). Minimal fix:
move `from urllib.request import …` above the guard import, or install the shadow
after all stdlib imports; add a test asserting
`exchange.oanda.urlopen is security.guards.guarded_urlopen`. Owner question in
Open questions Q3. `VERIFIED`.

**D2 — `get_current_price` fails open to an untimestamped mark. Severity:
medium.** `:256` returns `_price_cache.get(symbol)` with no age bound; the
non-`:253` writer is a **bar close** (`:212`), which for the `1d` bars the daily
runner requests is up to a day old. This is the documented `STOP_LOSS_ON_FILL_LOSS`
mechanism at reduced probability, and it is silent. Removing the fallback alone
is unsafe: `strategies/fx_runner.py:419-425` would raise `TypeError` on `None`
with a truthy ATR (other lanes guard it — `fx_runner.py:142`, `fx_h1rev.py:127`,
`fx_challenger.py:150`). Correct shape: None-guard at `fx_runner.py:419` **and**
drop or timestamp-bound the fallback. `VERIFIED` (code); blast radius on live
stops `SHOULD-VERIFY` (needs a venue read).

**D3 — A created-but-unfilled resting order is reported as `rejected`. Severity:
medium, latent.** The truthfulness check `:410-421` is applied to **all** order
types identically. For a GTC `LIMIT`/`MIT` that does not fill immediately, the
venue response carries `orderCreateTransaction` and no fill/cancel/reject, so the
adapter returns `status="rejected"` with reason `"no fill"`. Under the #169 rule
(reject ⇒ no ledger row, no cache row — `fx_runner.py:395-397`,
`fx_expert_lane.py:397-399`) a genuinely live venue order would go untracked.
`VERIFIED` that the code path is order-type-blind; the OANDA v20 response shape
is `READ-FROM-DOCS`/`SHOULD-VERIFY` (cannot confirm without placing an order).
Latent today: no live caller uses `limit`/`mit`. Suggested shape: distinguish
"no fill transaction but `orderCreateTransaction` present" from cancel/reject.

**D4 — `tag` is not applied to `limit`/`mit` orders. Severity: low, latent.**
`:345-380`. Same trigger condition as D3; if a lane ever rests orders it loses
both the ownership stamp and the arbitration key (`fx_runner.py:187`).

**D5 — The truthfulness fix has no test. Severity: low.** `tests/` contains
`test_oanda_price_precision.py` (8 precision tests) and no case where a POST
response lacks `orderFillTransaction`; the only occurrence of
`orderFillTransaction` in the test tree is the happy-path fixture at
`test_oanda_price_precision.py:24`. The #167 fix is regression-unprotected.

**D6 — `client_id` is second-resolution and wraps daily. Severity: low.**
`strategies/fx_expert_lane.py:377, 396` build
`f"{my_tag}-{sym[:8]}-{int(time.time()) % 100000}"`. Two same-tag same-symbol
orders inside one second collide (`CLIENT_TRADE_ID_ALREADY_EXISTS` — the failure
mode documented at `exchange/oanda.py:332-335`), and the suffix repeats every
~27.8 h. The lane sleeps 0.3 s between orders (`fx_expert_lane.py:402`), so the
window is narrow but not structurally closed.

**D7 — Doc drift around the fork. Severity: low.** (i) #158 Notes call the 09-02
adapter fix uncommitted (it is committed — §4). (ii) `AGENTS.md:93-96` /
`ARCHITECTURE.md:111` describe the sandbox delta as a single missing capability
without noting that the sandbox is *behind* live on three safety behaviours; a
reader could conclude the sandbox is the better merge base. Recommend one
sentence added to `ARCHITECTURE.md:111` after the Q04 decision.

**D8 — `guards.py` internals. Severity: low.** `guarded_open` containment covers
the entire project root plus `/tmp` (`guards.py:134-141`) and the write-mode
branch at `:135-137` is a no-op `pass` (dead code). `_reject_private` performs a
fresh DNS resolution per request (`:80-87`) — a per-call `getaddrinfo` that would
be paid on every OANDA request once D1 is fixed. No test file references
`guards`. `VERIFIED`.

**Observation (adapter-adjacent, not a contract clause).** `fx_runner.py:424-425`
attaches SL/TP only when `atr` is truthy, so an entry whose ATR resolves to 0
would be placed **unprotected**. Reachability is `SHOULD-VERIFY` (a flat 14-bar
series is required); noted only because it is the same "stop attaches at order
time" surface as D2.

---

## Links to existing maps

- **#158 — map `wayfinder:map — Ledger integrity: reconcile last night's runs to
  their venues` (CLOSED, 15/15 children).** Its Leg 2 destination was the
  venue-agreement invariant; every contract clause assessed here is a *landing*
  of that map: **#167** (truthful `place_order` + fresh price fetch — the direct
  parent of clauses 1a/1b), **#168** + **#170** (SL/TP price precision — the
  `_fmt_price` code at `oanda.py:275-290`), **#169** (rejected orders leave no
  residue — the reason D3 matters), **#171/#172/#173** (void rows, hourly
  reconcile, end-to-end venue-agreement check). #158's own "Out of scope" line
  names the adapter fork as human-gated — this ticket is registered for it.
- **ToC Q04** (`data/wayfinder/toc/TOC.md:33`) — "which is canonical, should the
  fixes be merged": still open; §3 supplies the direction evidence, not the
  decision.
- **ToC Q05** (`TOC.md:34`, map #174/#175/#177) — stamping reconcile rows from
  venue `clientExtensions`: depends on the `tag` kwarg being complete across
  order types (D4).
- **#174/#176/#177** — netting, no-overlap arbitration, tag resolution through
  the fill chain (`fx_runner.py:206-230` `_trade_tags`) — the consumer side of the
  `tag` contract.
- **#159** — the crypto lane's no-TTL `_price_cache` (`exchange/live.py`), named
  in `AGENTS.md:91-92` as the same disease; out of scope here.
- Docs: `AGENTS.md:86-96`, `docs/ARCHITECTURE.md:111` (fork), `:113` (no-TTL).
- Defect log: `data/defect_log.json` → `fx_defects` (19 entries; the
  `2026-09-02T16:40 phantom_fills` entry is the incident clause 1a closes).

---

## Open questions

1. **Direction of the fork (human gate, ToC Q04).** Is the sanctioned shape a
   ~10-line port of the sandbox's server-truth **positions** leg into live
   (`sandbox:415-419` → `live:467-484`), rather than a file merge? Note the
   sandbox added that leg on 2026-08-31 to fix *its* held-detection; live instead
   solves the same problem venue-side via `_venue_net`/`_venue_book`
   (`fx_runner.py:91-124`) — so the port may be unnecessary rather than pending.
   Who decides, and is the leg still wanted once D2 pushes `get_balance` toward
   venue truth anyway?
2. **Is the `:256` stale fallback load-bearing or leftover?** If it exists only to
   paper over the missing `None` guard at `fx_runner.py:419`, the correct fix is
   that guard plus deletion of the fallback. Any caller that *relies* on a
   never-None price would need to be named first.
3. **Who owns the guard shadow (D1)?** 17 files, one mechanical fix, but it is a
   live-security item with no ticket on it — a new wayfinder ticket rather than a
   change carried by #230? Does it move an ADR-0007 gate (the ToC scope rule)?
4. **Does a GTC resting order exist at the venue right now** (from a manual
   action or an older adapter)? If yes, D3 may already have hidden an untracked
   venue order. The #173 venue-agreement check is the right read-only instrument.
5. **What is `client_id` required to be unique across — open trades or all
   time?** The comment at `oanda.py:332-335` asserts the former (`SHOULD-VERIFY`
   against the v20 docs); the answer determines whether D6's daily-repeating
   suffix is a real collision risk.
6. **Should `place_order` distinguish "no fill transaction" from "created,
   resting"?** (D3) — a contract clause for `AGENTS.md:86-89` if resting orders
   ever ship.
