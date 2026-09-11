# Governance & monitoring layer — Warden, lifecycle, registry, claims, trail, scoreboard (ticket #231, map #218)

Read-only assessment. Every claim below is labelled **VERIFIED** (file:line, from the
committed tree — `git status` shows all six modules unmodified relative to HEAD
`d297357`), **READ-FROM-DOCS** (a repo document, not re-run), or **CLAIMED** (asserted
by a map/issue, not independently reproduced here). No orders placed, no REAL-mode run,
no service touched, no probe executed.

## Scope

In scope (the six files named by ticket #231, plus their direct consumers):

| Artifact | Size |
|---|---|
| `strategies/fx_warden.py` | 880 lines |
| `strategies/expert_lifecycle.py` | 231 lines |
| `strategies/epoch_registry.py` | 179 lines |
| `strategies/lane_claims.py` | 90 lines |
| `strategies/fx_trail_check.py` | 170 lines |
| `scripts/fx_scoreboard.py` | 133 lines |

(VERIFIED: `wc -l`.) Live state read as evidence: `data/epoch_registry.json`,
`data/warden/{game_plan,scorecard,warden_state,friday_scoreboard,instability}.json`,
`data/warden/{records,notes}.jsonl`, `data/fx_expert/trail_state_fxexp-*.json`.

Out of scope: crypto paper lane; the OANDA adapter fork (ToC Q04); any mutating probe.
Cross-referenced map: **#218** (gh issue view 218, OPEN, sub-issues 8/9 complete).

---

## Verified findings (file:line)

### 1. The lifecycle state machine — implemented, and genuinely wired

States and the transition table are exactly as documented:
`candidate → registered → accruing → probation → cut → archived`, with
`cut → archived` the only terminal edge (**VERIFIED** `strategies/expert_lifecycle.py:37-45`).
`transition()` is the only mutator: it validates the edge, writes the registry via
tmp+rename, fsyncs an append-only log, and fires side effects
(**VERIFIED** `:134-172`, `:66-69`, `:52-57`).

Derived contract, all implemented:
- `active_lanes()` = `accruing + probation` (**VERIFIED** `expert_lifecycle.py:120-123`).
- `notional_cap()` = the entry's `notional_cap`, default 1.0 (**VERIFIED** `:126-131`).
- `registry_tag_index()` maps the three live spellings of one expert — registry id
  `fx-expert-g151`, lane/venue tag `fxexp-g151`, legacy alias `mom-k5` — in one place
  (**VERIFIED** `:99-117`, alias table `:89-96`).
- `cut` releases claims under both spellings and warns loudly when nothing matched
  (**VERIFIED** `:175-207`; the `fx-expert-*` vs `fxexp-*` release bug and its fix are
  recorded in `:178`, and in map #218's decision for #222).

Consumers actually wired to the machine (**VERIFIED** by grep, not by claim):

| Consumer | Wiring |
|---|---|
| Lane start gate | `strategies/fx_expert_lane.py:219-229` — refuses to start on `cut`/`archived`; reads the cap at `:227` and **applies it to sizing** at `:320` (`w * NOTIONAL * ncap`) |
| Trail check | `strategies/fx_trail_check.py:132-142` — per-lane skip when the expert is not in `active_lanes()` |
| Claims auction | `strategies/lane_claims.py:57-68` — `load_scores()` admits only `fxexp-{id}` tags whose expert is active; non-owners are locked out of order flow at `fx_expert_lane.py:315-319` |
| Mid-train warm start | `fxexpert/loop.py:141-150` — a `cut`/`archived` warm source is quarantined and the generation falls back to no warm start |
| Warden observe | `strategies/fx_warden.py:361-373` — orphan-tag filter via `registry_tag_index()`, plus a TERMINAL-STATE anomaly when a `cut`/`archived` expert holds positions |
| Warden score | `strategies/fx_warden.py:553-566` — probation syncs the registry with `cap 0.5`; a reprieve syncs back to `accruing` with `cap 1.0` |
| Dashboard | `dashboard.py:694-700`, `:712-766` (`/api/lifecycle`), `:838-852` (lifecycle panel), `:1227-1272` (agent-registry view) |
| Friday scoreboard | `scripts/fx_scoreboard.py:57`, `:85-88` — lifecycle + cap column |

Not wired: `tui/index.js` (the client the human actually runs, per AGENTS.md) renders no
lifecycle/warden/scoreboard state (**VERIFIED**: no `lifecycle`/`warden`/`scorecard`
matches in `tui/index.js`); and `migrate_existing()` has no caller outside its own
`__main__` (**VERIFIED** `expert_lifecycle.py:210`, `:228`).

The state machine is **not** enforced as a permission model: `transition()` takes
`actor` as a free-form label and performs no authorization check, so any caller can cut
an expert (**VERIFIED** `:134-151`). Human-gating of `cut` (ADR-0009 §4) is procedure,
not code.

Registry reality (**VERIFIED** by reading `data/epoch_registry.json`): 11 experts, all
carrying both `lifecycle` and the older three-state `status`; `fx-expert-g151/g137/g138`
are `accruing/accruing` at cap 1.0; `fx-expert-g13` and `fx-expert-g15` are
`status=fail → lifecycle=cut`; `fx-expert-g137` carries `lifecycle_reason "test reverted"`.

### 2. The expectation-adjusted scoreboard (QB/RB, MFE/give-back, sizing fidelity)

**QB/RB rule** — implemented exactly as the docstring claims. The Warden sets each
active lane's expected weekly P&L in account % (**VERIFIED** `fx_warden.py:288-296`,
written at `:486-495`), and `score()` computes

```
miss    = actual_pct − expected
penalty = miss                      if miss >= 0
penalty = miss − HARSHNESS*|expected|   otherwise      (HARSHNESS = 1.0)
```
(**VERIFIED** `:63`, `:535-537`). Live arithmetic match: `data/warden/warden_state.json:45-51`
holds `h1-rev` 2026-09-08 with `expected 0.05`, `miss −0.049`, `score −0.099` —
precisely `miss − 1.0 × 0.05`.

**Probation/escalation** — a bad score (`< −0.05` account %, `:547`) increments
`bad_periods`; 1 → `probation` (+ registry cap 0.5), 2 → `escalate`, both printed as the
shadow cut list (**VERIFIED** `:544-569`, `:595-600`). `cut` itself is never called from
the Warden (human-gated by design, `:553-558`).

**MFE / give-back** — the hourly observe tracks per-lane peak uPL, persisted in
`warden_state.json` under `mfe`, reset on period change (**VERIFIED** `:386-404`), and
`score()` reports `peak_upl`, `current_upl`, `give_back = (peak − cur)/peak if peak > 0`
(**VERIFIED** `:570-579`). The weekly anchor that keeps the peak stable across the
Friday-to-Friday period is `_week_anchor()` (**VERIFIED** `:72-86`), and `plan()` keeps
the period snapshot while refreshing expectations only (**VERIFIED** `:466-502`).

**Sizing-fidelity audit** — per-leg actual USD notional (venue truth) vs intended
`|weight| × NOTIONAL`, `within` band 0.65–1.35, dust legs excluded at `MIN_UNITS`,
`$0` non-dust legs counted `missing` (**VERIFIED** `:764-831`). The claim-filter fix
(a lane is only accountable for pairs it won in the auction) is present
(**VERIFIED** `:789-797`). Live output corroborates map #218's numbers:
g137 94.4 %, g138 86.4 %, g151 83.3 % (**VERIFIED** `data/warden/scorecard.json:120,90,60`;
map #218 decision for #225 says 94/86/83 — consistent).

### 3. The mid-train corpus quarantine filter (`corpus_records`)

The intended contract: read-time exclusion of records whose lanes include a
`cut`/`archived` expert, with an honest exclusion count (**VERIFIED** docstring
`fx_warden.py:302-307`; lifecycle side `expert_lifecycle.py:15-18`, `:168-169`).

**It does not work, for two independent reasons** (see D5): it has no caller anywhere in
the tree, and its lookup is in the wrong namespace.

What *is* wired on the corpus path: every run appends `{ts, model, mode, headlines,
news_refs, lane_states, plan/model_out}` to `data/warden/records.jsonl`
(**VERIFIED** `:423-424`, `:503-504`, `:588-589`, `:837`), 98 records on disk today
(**VERIFIED** `wc -l data/warden/records.jsonl` = 98), and the dashboard reports corpus
composition (**VERIFIED** `dashboard.py:814+`).

### 4. Live instrumentation status (venue-truth read, no probes run)

- Warden scheduled hourly: `~/.config/systemd/user/fx-warden.timer`
  `OnCalendar=*-*-* *:45:00 UTC`, oneshot `python3 -m strategies.fx_warden --auto`
  (**VERIFIED** unit files; records at :45:xx hourly, e.g.
  `data/warden/records.jsonl:96-98`).
- Trail check scheduled every 5 minutes with `--once` (= REAL per the cron contract)
  `~/.config/systemd/user/fx-trail-check.service` + `.timer` (`OnUnitActiveSec=300`)
  (**VERIFIED** unit files; `fx_trail_check.py:169` defines `dry = "--once" not in argv`).
- Halt persistence gate is live: `halt_streak` = 6 for TRY/JPY/EUR/USD
  (**VERIFIED** `data/warden/warden_state.json:115-120`), matching the last Warden flag
  "JPY, TRY, EUR have CRITICAL HALTED status" (**VERIFIED** `data/warden/notes.jsonl:288`).
- Notes are being number-audited: 288 note/flag rows on disk (**VERIFIED**
  `wc -l data/warden/notes.jsonl` = 288); recent note rows carry
  `"verified": true, "note": null` (**VERIFIED** `notes.jsonl:281-283`).
- No trail close has ever been recorded: zero `trail-close` rows in
  `data/fx_ledger.jsonl` (1003 rows) (**VERIFIED** grep-tool search: no matches).
- `friday_scoreboard.json` was produced manually 2026-09-10T12:48Z
  (**VERIFIED** `data/warden/friday_scoreboard.json:2`) and is referenced nowhere but its
  own writer (**VERIFIED**: the string `friday_scoreboard` occurs only at
  `scripts/fx_scoreboard.py:26`; no systemd unit and no `dashboard.py` reference).

---

## Health assessment

**Verdict: enforcement-wired, supervision-grade. The control plane is real; the reporting
plane is where the integrity problems are.**

What is genuinely healthy:

1. The state machine is small, single-purpose, validated, atomic and logged, and it is
   consumed by five independent components (lane, trail, auction, loop warm start,
   dashboard) — this is not a decorative registry (**VERIFIED**, consumer table above).
2. The three defect classes the map's tickets targeted were really fixed, and I could
   reproduce the fix in the artifacts rather than take it on trust: tag-spelling
   namespace (`registry_tag_index()`, `expert_lifecycle.py:99-117`), claim release on cut
   (`:175-207`), claim-filtered sizing fidelity (`fx_warden.py:789-797`).
3. Warden bounds hold as designed: venue reads only, no order placement anywhere in
   `fx_warden.py` (grep: only GET requests, `:144-145`, `:163`, `:687`), proposals-only
   authority, one bounded model call per mode with endpoint failover
   (**VERIFIED** `:248-274`).
4. The self-audit idea (verifying the monitor's own numbers against venue truth before
   they enter the corpus) is the right design, and it is implemented and running
   (**VERIFIED** `:329-348`, `:405-417`).

What is not healthy:

1. The Warden's own scoring path has an **unhandled crash branch** on the exact code
   path that exists to suppress false halts (D1), and a **duplicated vestigial block**
   in `score()` (D2 — the block the ticket suspected).
2. The map's #223 deliverable — the mid-train corpus quarantine — is **dead code and
   namespace-broken**; the map records it as done (D5). The documented corpus guarantee
   "verified records only" is not implemented anywhere (D6).
3. All three expectation-adjusted metrics produce **misleading numbers in live data**:
   give-back above 1.0 (2.822) and below 0 (−0.097), QB/RB inert because every live
   expectation is 0.0, and a planned lane with no MFE tracking at all (D8, D9, D14).
4. The cut/probation loop leaks: a renamed lane's probation is immortal (D11), and the
   sizing audit self-destructs the moment probation lowers the cap (D15) — i.e. the two
   halves of the same control loop fight each other.
5. The live tree runs a risk-machinery component whose own measured verdict says it
   should not exist (D4). That is a governance contradiction, not a code bug, and it
   belongs to the human.

Scale check: with the account at NAV 99,633.79 (**VERIFIED** `friday_scoreboard.json:4`)
and per-lane realized P&L of 0.0 (below), the "scoreboard" currently ranks lanes on
sub-0.02 % account moves — the ordinal signal is far finer than the measurement noise,
which is why D12/D14 matter more than they look.

---

## Defects & risks

Severity is my judgement; each item is reproducible from the cited lines.

### D1 — HIGH — `instability()` raises `UnboundLocalError` on the venue-wide maintenance branch
`fx_warden.py:698` writes `out["maintenance_window"] = True`, but `out` is first bound at
`:726`. `out` is a local of `instability()`, so the assignment at 698 is an
`UnboundLocalError` — every exception path in this function is swallowed by callers
(`observe()`/`plan()` call it unconditionally at `:379`, `:446`, with no try/except), so
a venue-wide stale-price window (the daily ~21:00–22:00 UTC maintenance the branch was
written for, trigger condition `:697`) would abort the Warden run rather than set the
flag. **VERIFIED by reading** (no other assignment to `out` exists between `:622` and
`:726`); **should verify** against the service journal whether it has ever fired.
Note the branch is also semantically dead as written: it sets a key on an object that
does not yet exist.

### D2 — HIGH (dead code, ticket-named) — duplicated block in `fx_warden.score()`
`fx_warden.py:561-563` and `:567-569` are the identical three-line assignment

```python
prob[tag] = {"bad_periods": 0, "status": "reprieved",
             "note": f"recovered {s['score_pct']:+.2f} — shadow cut lifted"}
```

with the `_sync_lifecycle(... "accruing" ...)` call wedged between them (`:564-566`).
The second assignment is pure dead code (nothing between them mutates `prob[tag]`); it is
a copy-paste artefact of the lifecycle-sync patch. Effect is benign today, but it means
the reprieve path was edited twice and is a live edit hazard for the next change — the
enforcement decision (sync) and the state write are no longer adjacent.

### D3 — HIGH — `check_trails()` ignores `my_tag` when selecting trades → cross-lane mis-attribution
`fx_trail_check.py:58-62` accepts `my_tag` but filters only on the global prefix:
`fx = [t for t in trades if tag.startswith("fxexp-")]`. Every call therefore evaluates and
(closes) **every** `fxexp-*` trade, while the close record and ledger row are stamped with
the caller's tag (`:112-116`, `"tag": my_tag`) and the peak state is written to
`trail_state_<my_tag>.json` (`:67`, `:127`). `run_all()` calls it once per active lane
(`:138-143`), and `fx_expert_lane.py:253` calls it during lane runs — so g151's pass
closes/claims g137's and g138's triggered legs. Supporting evidence: g151's peak file has
~80 peak entries (**VERIFIED** `data/fx_expert/trail_state_fxexp-g151.json`, 336 lines /
4 lines per entry) against ~17–19 open g151 positions (**VERIFIED**
`friday_scoreboard.json:20`). Impact is currently **latent**: zero `trail-close` rows exist
in `data/fx_ledger.jsonl`, so nothing has triggered yet. **Should verify** against the
venue which tradeIDs live in each peak file before treating it as realized corruption.

### D4 — HIGH (governance) — live risk machinery contradicts its own measured verdict
`fx-trail-check.timer` runs the simulated trail/TP closer every 5 minutes in **REAL** mode
(`--once`; unit files + `fx_trail_check.py:169`), and the lanes call it live
(`fx_expert_lane.py:253`). The project's own A/B on ~28k leg-periods over 3 OOS folds
concludes "**Every risk-machinery variant loses to hold-to-rebalance**" and "the live book
keeps hold-to-rebalance" (**READ-FROM-DOCS**
`docs/agents/research/fx-warden-2026-09-08.md:105-127`). The module's docstring justifies
running it anyway on the grounds that the A/B tested *uniform* stops while this is a
*selective* per-leg version (**VERIFIED** `fx_trail_check.py:4-7`) — a variant the cited
A/B does not cover. Either that variant needs its own measurement before it is allowed to
touch a live book, or the closer should be dry. Ticket scope: surface to the human.

### D5 — MEDIUM — `corpus_records()` quarantine is dead code *and* namespace-broken
1. **No caller.** `corpus_records` appears exactly once in the tree, at its definition
   (**VERIFIED** grep over the repo, pycache/binary excluded) — nothing builds the
   mid-train corpus from it. Map #218 records #223 as delivered ("`corpus_records()`
   read-time filter + warm-start quarantine in the loop") — the loop half is wired
   (`fxexpert/loop.py:141-150`), the corpus half is not.
2. **Wrong namespace.** `fx_warden.py:308-309` builds `lc = all_lifecycles()`, whose keys
   are **expert ids** (`"fx-expert-g151"`, `expert_lifecycle.py:81-84`), and then tests
   `lc.get(t)` for `t` drawn from the record's `lane_states` keys (`:320-321`), which are
   **venue tags** — `"fxexp-g137"`, `"fxexp-g138"`, `"fxexp-g151"` (**VERIFIED**
   `data/warden/records.jsonl:96-98`). Every lookup returns `None`, so the predicate
   `in ("cut", "archived")` is never true: even if wired, the filter would exclude nothing.
This is the *same* bug class fixed in `observe()` on 2026-09-10 via `registry_tag_index()`
(commit `d297357`, `fx_warden.py:363-367`) — the fix was not propagated to the corpus
reader. `expert_lifecycle.py:169` even asserts "records.jsonl filtering happens at
mid-train read time", so the lifecycle layer believes this filter exists.

### D6 — MEDIUM — the documented "verified records only" corpus guarantee is unimplemented
`docs/agents/research/fx-warden-2026-09-08.md:101` states the mid-train trigger is
"~2 weeks of records.jsonl (**verified records only**)" (**READ-FROM-DOCS**), and the TOC
entry says the verifier "gates corpus" (**READ-FROM-DOCS** `data/wayfinder/toc/TOC.md:42`).
`corpus_records()` never reads a `verified` field (**VERIFIED** `fx_warden.py:302-325`),
and the `verified` verdict is written only to `notes.jsonl` (`:412-417`) — the per-note
verdict is *not* persisted into `records.jsonl` (`:423-424` stores raw `model_out`), so a
corpus reader cannot apply it without joining the two files.

### D7 — MEDIUM — the numeric verifier's guarantee is weaker than its name
`_verify_note_numbers()` returns `True` immediately when the text contains no `%` token
(**VERIFIED** `fx_warden.py:334-336`), so a note citing counts or ratios is stamped
`verified: true` without any check — live examples "has 19 positions across 17 pairs"
(**VERIFIED** `data/warden/notes.jsonl:281-283`). Flags bypass verification entirely
(`verified: None`, `:415-417`) although the model is explicitly instructed to cite
concrete numbers (`:284-286`) — and flags land in `records.jsonl` `model_out`.

### D8 — MEDIUM — the give-back ratio is not a ratio: it can exceed 1 and can be negative
`fx_warden.py:576` (`gb = (p − cur)/p if p > 0 else 0.0`) and its duplicate
`fx_scoreboard.py:93` are unbounded. Live: `peak_upl 7.17`, `current_upl −13.06` →
`give_back 2.822` (**VERIFIED** `data/warden/scorecard.json:12-14`). And because the
scoreboard pairs a peak read from `warden_state.json` (written hourly) with a **live** uPL
(**VERIFIED** `fx_scoreboard.py:80-83`), the peak can be below current, producing a
*negative* give-back: `−0.097` for g151 and `−0.099` for g137 (**VERIFIED**
`data/warden/friday_scoreboard.json:16-17`, `:46-47`). A lane that started negative has a
negative peak and reports `0.0` (**VERIFIED** `scorecard.json:23-25`, peak −9.62 →
give_back 0.0). The metric does not currently separate exit skill from selection skill —
it mixes both with a cache-timing artefact.

### D9 — MEDIUM — MFE is tracked only for `fxexp-*`, so planned lanes report a fake peak
`fx_warden.py:395-396` skips any tag not starting with `fxexp`. The plan and scorecard
include legacy lanes (`h1-mom`, `mom-k5`, `c08-fade` — `data/warden/game_plan.json:30-35`),
so those lanes keep `peak_upl 0.0` forever: live `h1-mom` `peak_upl 0.0` with
`current_upl 1.06` (**VERIFIED** `scorecard.json:44-47`, `warden_state.json:96-106`).

### D10 — MEDIUM — registry coverage gap: a live, planned lane is classified as an unregistered orphan
`registry_tag_index()` is built from the registry's expert ids plus `LEGACY_LANE_ALIASES`
(**VERIFIED** `expert_lifecycle.py:89-117`); the alias table maps
`fx_mom_k5_top2→mom-k5`, `fx_mr_fade_ma20→c08-fade`, `fx_h1_rev_rsi2→h1-rev`,
`fx_h4_donchian20→h4-brk`, `fx_mom_k10_top2→d1-mom10` — and nothing maps **`h1-mom`**
(registry contents: 6 legacy ids + `fx-expert-g13/g15/g137/g138/g151`, **VERIFIED** by
reading `data/epoch_registry.json`). `observe()` therefore treats the h1-mom lane's book as
an orphan, **drops it from `st["lanes"]`** and sets `st["anomaly"]`
(**VERIFIED** `fx_warden.py:364-367`) — while the plan (unfiltered `lane_states()`, `:436`)
and the scorecard keep scoring it. The same holds for the `crash`
(`strategies/fx_crashtest.py:51`) and `watchdog` lanes. Additionally the anomaly string is
never persisted: `RECORDS` stores only `lane_states` and `model_out` (`:423-424`), so the
"unregistered lanes trading" signal is print-only and invisible to the dashboard.

### D11 — MEDIUM — probation state is keyed by plan lane tags with no reaping → immortal stale entries
`prob` is only ever touched for tags present in the current plan (**VERIFIED**
`fx_warden.py:546-569`). Live: `warden_state.json:5-10` (and `scorecard.json:50-55`) carry
`probation: {"h1-rev": {bad_periods: 1, status: "probation"}}` while the current plan and
scores use **`h1-mom`** (`game_plan.json:30`, `scorecard.json:38`, `:96-106`); the entry
survived the 2026-09-08 → 09-09 tag change and is reprinted as "probation (one week to
improve)" on every score run (`:599-600`). `_sync_lifecycle()` cannot repair it: it looks
up `lifecycle_of("h1-rev")` — an expert-id lookup that the *alias* string will never match
(**VERIFIED** `:607-609` vs `expert_lifecycle.py:72-78`), and the LEGACY alias maps
`fx_h1_rev_rsi2 → h1-rev` in the opposite direction anyway. The Friday cut list can
therefore name a lane that no longer exists.

### D12 — MEDIUM — "bad period" is actually a bad *day*, and `escalate` enforces nothing
`PROBATE_AFTER = 1`, `ESCALATE_AFTER = 2` are documented as periods
(**VERIFIED** `fx_warden.py:60-65`) but `auto()` calls `score()` at most once per day
(**VERIFIED** `:845-858`), so within one weekly anchor (`period_start`) a lane reaches
`escalate` after **two bad days**. `escalate` calls no enforcement at all — only the
`probation` branch syncs the registry (`:555-558`), and escalate exists solely as a print
(`:597-598`) and a scorecard field. There is no escalation artifact for the Friday list;
if the lane improves on day 3, `bad_periods` resets to 0 and the two-day history is lost
(`:559-563`).

### D13 — MEDIUM — expectation/actual time-base mismatch
`plan()` re-writes expectations daily (`last_plan_day`, `:851-852`) while `score()`
measures a **cumulative** actual from the weekly anchor (`realized_all − realized_at_plan`
+ current uPL, `:532-534`). A lane can therefore be scored against an expectation set
hours ago on a whole week's P&L — the QB/RB penalty compares quantities with different
horizons. The design is visible in the file's own comment block (`:527-531`) and is
labelled a "documented heuristic", but the horizon mismatch is not.

### D14 — MEDIUM — the QB/RB asymmetry is currently inert, and the `bad` threshold is mis-scaled
Every live expectation is `0.0` (**VERIFIED** `data/warden/game_plan.json:13,19,25,31`),
so `penalty == miss` and the expectation-conditioning term never fires (the model is
told "flat/exhausted lanes get ~0.0", `:291-292`). The `bad` threshold is a fixed
`−0.05` account % (**VERIFIED** `:547`) against observed moves of `−0.013`, `−0.005`,
`0.001` account % (**VERIFIED** `scorecard.json:6-11`). Consequence: the scoreboard's
ordinal ranking and the probation trigger operate on a scale where the model's own
expectations are pre-flattened to zero — the "expectation-adjusted" property is
structurally present but empirically untested in live data.

### D15 — MEDIUM — the sizing-fidelity audit ignores `notional_cap` → faith in the audit collapses exactly when probation is applied
`audit_sizing()` intends `abs(w) * NOTIONAL` with no cap (**VERIFIED** `fx_warden.py:808`),
while the lane sizes to `w * NOTIONAL * ncap` with `ncap` from the lifecycle registry
(**VERIFIED** `fx_expert_lane.py:320`, `:227`). A probation lane (cap 0.5, written by
`fx_warden.py:558`) therefore lands at ratio ≈ 0.5, outside the 0.65–1.35 band (`:814`),
so every leg is reported as an outlier and fidelity drops to ~0 % — at the exact moment
the Warden is assembling evidence for a cut. Also the expert list is hardcoded to
`("g151","g138","g137")` (`:789`), so legacy and future lanes are never audited
(the scoreboard then prints `"—"`, `fx_scoreboard.py:97`).

### D16 — LOW/MEDIUM — two modules claim single-writer ownership of one registry and share one temp path
`epoch_registry.py:20` claims "Single writer: this module", but `expert_lifecycle.py:161`
also writes `data/epoch_registry.json`. Both use the **identical** temp path
(`REGISTRY.with_suffix(".json.tmp")` → `epoch_registry.json.tmp`,
`epoch_registry.py:52-54` vs `expert_lifecycle.py:66-69`), so a concurrent
`register()` from the training loop (`fxexpert/loop.py:102`) and a `transition()` from the
Warden (`fx_warden.py:611`) can interleave on the same temp file — lost update, or a
rename of another process's content, or `FileNotFoundError` on the second rename. No lock
in either module. Low probability (hourly Warden vs occasional registration), high impact
(the control-plane registry). **Should verify** by checking `epoch_registry_log.jsonl` for
duplicate/gapped transitions.

### D17 — LOW/MEDIUM — the two registries on one file are not kept in sync, and a fresh registration is invisible to the enforcement layer
`register()` writes `status` but **no `lifecycle` field** (**VERIFIED**
`epoch_registry.py:73-88`); `all_lifecycles()`/`active_lanes()` then see the new expert as
`candidate` (**VERIFIED** `expert_lifecycle.py:81-84`, `:120-123`), which excludes it from
the lane gate, trail check, and claims admission. The only repair is
`migrate_existing()` (**VERIFIED** `:210-224`), whose mapping `status="accruing"` →
`lifecycle="accruing"` would silently grant a brand-new shadow challenger **full
live-notional eligibility** — contradicting the same module's docstring that `accruing`
means full live trading and that promotion requires human signoff (`:12`, ADR-0009 §4).
Currently latent: no expert has been registered since the v2 migration (registry tops out
at g151; map #218 records gens 160–162 all failing the gate).

### D18 — LOW — duplicated/vestigial code
- `_model_cache = {}` defined twice, `fx_warden.py:89` and `:94` (**VERIFIED**).
- `from strategies.expert_lifecycle import all_lifecycles` imported twice in `observe()`,
  the first unused, `fx_warden.py:352` vs `:361` (**VERIFIED**).
- `prev_halted` survives in `data/warden/warden_state.json:109-114` with **no reader or
  writer anywhere in the tree** (**VERIFIED** repo-wide grep) — a vestigial key that
  `_save_state()` faithfully re-persists forever.
- `lane_claims.WARDEN_DIR` names the variable `WARDEN_DIR` but points at
  `data/fx_expert` (**VERIFIED** `lane_claims.py:21`) — misleading name in the claims path.

### D19 — LOW — `cut` does not close positions, contrary to the module's own docstring
`expert_lifecycle.py:15-16` says cut means "lane stops, positions close, claims released,
records quarantined"; `transition()` implements only claim release (`:166-167`). The lane
refuses to start on cut/archived (`fx_expert_lane.py:228-229`) — it never runs the code
that would exit the book — so a cut expert's positions stay open until something else
flattens them. That is precisely the failure the Warden's TERMINAL-STATE anomaly was added
to detect (**VERIFIED** `fx_warden.py:368-373`); detection is wired, remediation is not.
Map #218's decision for #219 ("refuses cut, applies cap, logs state") describes the gate
only.

### D20 — LOW — non-atomic writes on the enforcement path
`claims.json` has two writers and neither is atomic or locked: `lane_claims.recompute()`
(`lane_claims.py:83`) and `expert_lifecycle._release_claims()` (`expert_lifecycle.py:205`)
both `write_text` in place, while the registry on the same decision path uses tmp+rename.
A cut's claim release racing a lane's auction recompute can lose the release (or the
recompute) — the exact ambiguity map #218 flags for the human under "Claims change
mid-period".

### D21 — LOW — the Friday scoreboard has no consumer and no scheduler
The only reference to `friday_scoreboard` in the tree is the writer's own default path
(**VERIFIED** `scripts/fx_scoreboard.py:26`). No systemd unit references
`fx_scoreboard.py` (the only FX-governance units are `fx-warden*` and `fx-trail-check*`),
and `dashboard.py`'s `/api/warden` surfaces notes, plan, scorecard, instability,
proposals and corpus stats but not this file (**VERIFIED** `dashboard.py:768-814`). The
artifact the Friday cut decision is supposed to read is produced ad hoc and rendered
nowhere.

### D22 — LOW — the human's own client shows none of the control plane
`tui/index.js` has no `lifecycle`/`warden`/`scorecard` reference (**VERIFIED** grep) — the
lifecycle, cap, probation and scoreboard state are only visible through `dashboard.py`
(`/api/lifecycle`, `/api/warden`) and the dashboard's HTML panels.

### Data-quality flags (not code defects, but they change what the numbers mean)
- `realized_all` is `0.0` for **all three** trained lanes in both the scoreboard
  (**VERIFIED** `friday_scoreboard.json:13,27,42`) and the Warden's records
  (**VERIFIED** `records.jsonl:96-98`) on an account holding 57 legs. Either nothing has
  closed since the lanes opened, or the venue-journal tag attribution chain
  (`fx_warden.py:163-177`, `fx_scoreboard.py:29-52`) is not landing on `fxexp-*` tags.
  **Should verify** against `openTrades`/transactions before any cut decision reads
  "realized 0.0" as "flat performance".
- `game_plan.json` still carries `period_start "2026-09-09"` (**VERIFIED** `:2`), which is
  not a Friday-close anchor: today is Thursday 2026-09-10, so `_week_anchor()` yields
  2026-09-04. The file predates the `_week_anchor` fix (mtime Sep 9 08:39 vs commit
  `d297357` at 07:48), and `score()` reported `days_in_period 1`
  (**VERIFIED** `scorecard.json:3`) off the stale anchor. Expected behaviour at the next
  plan run: the anchor resets and the MFE peaks reset with it (`:476-485`, `:399-402`) —
  **should verify** after tonight's 21:45 UTC run.

---

## Links to existing maps

- **Map #218** — "FX pipeline completion: lifecycle enforcement, scoreboard, halt-gate"
  (gh issue view 218, OPEN, 8/9 sub-issues complete). Cross-check of its recorded
  decisions against this assessment:
  - #219 lane-start gate — **verified present** (`fx_expert_lane.py:219-229`);
    caveat D19 (cut does not flatten the book).
  - #220 trail check services only active lanes — **verified present**
    (`fx_trail_check.py:132-142`); the NameError fix is visible in the tag/filter wiring —
    but see **D3** (the filter ignores `my_tag`) and **D4**.
  - #221 warden observes registered lanes / flags unregistered tags — **verified present**
    (`fx_warden.py:361-373`); the terminal-state anomaly is not persisted (**D10**).
  - #222 claims admit only active lanes + namespace fix — **verified present**
    (`lane_claims.py:57-68`, `expert_lifecycle.py:175-207`).
  - #223 mid-train corpus excludes cut/quarantined records — **the loop half is wired**
    (`fxexpert/loop.py:141-150`); **the `corpus_records()` half is not** (**D5**).
  - #225 Friday scoreboard + fidelity metric — **verified present**
    (`scripts/fx_scoreboard.py`, `fx_warden.py:789-797`; 94.4/86.4/83.3 live); no
    scheduler or UI (**D21**), and the audit breaks under probation (**D15**).
  - #226 run-3 generations — **CLAIMED** (gens 160–162 FAIL gate, nothing promoted);
    consistent with the registry showing no expert past g151.
  - #227 lane-side halt-gate — **CLAIMED** works-as-designed; the Warden's own halt
    machinery carries **D1**.
  - Map's "Not yet specified" items I can now date: the claims-mid-period drift is
    compounded by the two non-atomic `claims.json` writers (**D20**).
- `docs/agents/research/fx-warden-2026-09-08.md` — Warden design + the TP/SL A/B verdict
  (**D4**, **D6**).
- `docs/agents/research/fx-expert-loop-2026-09-06.md:342` — claims expert_lifecycle v2 is
  wired into lane/trail/warden/auction/mid-train (**CLAIMED**; the mid-train half is the
  gap in D5).
- `docs/adr/0009-expert-promotion-seam.md` — human signoff for the shadow → live boundary
  (**READ-FROM-DOCS**; not enforced in `transition()`, §1 above, and contradicted by
  `migrate_existing()`, D17).
- `data/wayfinder/toc/TOC.md:42` (Q14) — warden v0.1 status, the "verifier gates corpus"
  claim (**D6**), and the open question "does expectation-adjusted scoring separate lane
  skill from regime?" — **D8/D13/D14 are that question's failure modes in code**.
- `AGENTS.md` — FX-arm scope, cron contract (`--once` = REAL, **D4**), venue-authoritative
  rule (honoured throughout the six files: all Warden reads are venue GETs).
- Parent research issue **#228** (ticket #231 is a sub-issue).

---

## Open questions

1. **D1**: has `instability()`'s maintenance branch ever fired in production? (journalctl
   on `fx-warden.service`; a single occurrence implies at least one lost Warden run.)
2. **D3**: which venue tradeIDs actually live in each `trail_state_fxexp-*.json`, and does
   the peak file for one lane contain another lane's trades? (Requires a venue read.)
3. **D4**: does the *selective* per-leg trail (fx_trail_check) have its own measurement,
   or is it running live on the strength of a variant the 28k-leg-period A/B did not
   test? If not measured, should the 5-minute timer be switched to dry?
4. **Data flag**: is `realized_all = 0.0` for g137/g138/g151 genuine (no closes) or a
   tag-attribution break in the journal walk? This number is the scoreboard's headline.
5. **D5**: when the mid-train actually starts (TOC Q14: "~2 weeks of records.jsonl"), who
   is the consumer — is a trainer script planned, and will it call `corpus_records()`?
   Until then, the quarantine filter is a promise, not a control.
6. **D6**: should the corpus gate be on `verified` (current design intent, unimplemented)
   or is the lifecycle filter sufficient? The two are different guarantees.
7. **D17**: what is the intended lifecycle of a newly registered challenger — `candidate`
   (then who promotes it?) or `accruing` (then migration is a live-trading grant)?
8. **D10**: are `h1-mom`, `crash` and `watchdog` deliberately outside the registry, or a
   coverage gap? If deliberate, `observe()`'s orphan alarm will keep firing on them.
9. **Anchor transition**: after tonight's plan run, confirm `period_start` becomes
   2026-09-04 and the `mfe` peaks reset (expected: peaks shrink, give-back recomputes).
10. **Scope**: does the human want the Warden's probation/escalate to keep a shadow-cut
    artifact (a file the Friday decision reads), given `escalate` currently enforces and
    records nothing (**D12**)?
