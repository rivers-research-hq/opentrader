# Cross-cutting integrity — repo hygiene, doc drift, tests, harness, #216, ToC governance (wayfinder #236)

**Ticket:** #236 (parent #228, blocks #237; sibling map #230).
**Date:** 2026-09-10. **Mode:** read-only static assessment. No files modified
before this report was written, no service touched, no test executed, no order
placed, nothing added or committed.

**Label discipline used below.** `VERIFIED` = observed this session with a
read-only command (`git status/porcelain/log/ls-files/check-ignore`, `wc`, `du`,
`ls`, `ss`, `grep`/`glob`/`read`, `gh issue view`, `stat`, file reads at
`file:line`). `READ-FROM-DOCS` = repo docs / issue text. `CLAIMED` = asserted by
a doc, unit file or issue without re-derivation here. `UNVERIFIABLE-HERE` =
cannot be settled inside this sandbox (see §0 limits).

---

## 0. Method and the sandbox limits (read this before trusting any runtime claim)

`VERIFIED` — this session runs inside a bwrap sandbox (`ps aux` shows only
`bwrap --ro-bind / / --dev /dev --unshare-pid --proc /proc` and its children;
`ps aux | wc -l` = 5). Consequences:

1. **`ps` cannot see project processes.** Every `ps`-based "which service is
   running" claim in this report is therefore *not* made. Ports come from `ss`
   only, which does read the host network namespace (`ss -ltnp` lists
   11434/8097/8092/5801/5802/5804/… as `LISTEN`).
2. **`systemctl --user` is unavailable**: every query returns
   `Failed to connect to user scope bus via local transport: No data available`
   (`is-failed`, `is-enabled`, `is-active` all exit 1). So "unit X is
   failed/enabled/active" is `CLAIMED` from units + issue text, never `VERIFIED`.
3. **`crontab -l` is unavailable** (`You (mrc) are not allowed to access to
   (crontab) because of pam configuration`). The FX-lane and trained-lane cron
   contracts in AGENTS.md are `READ-FROM-DOCS` here, not re-verified.
4. `ss` gives **no process column** (no root), so a listener's owner is
   unattributed unless a unit file independently declares that port.

All file/`git`/`ss`/`wc`/`du` facts below are reproducible with read-only
commands from `/home/mrc/opentrader` at commit `ffe3978`
(`2026-09-10 08:18:01 -0500`), `2026-09-10 20:5x UTC`.

---

## Scope

| Area | What was assessed | Primary evidence |
|---|---|---|
| Repo hygiene | `git status --porcelain` (194 entries), the 172 untracked `data/fx_expert/*.npz`, the churning tracked caches, `.gitignore` (159 L) | `git status`, `git ls-files`, `git check-ignore`, `du`, `stat` |
| Doc drift | `docs/ARCHITECTURE.md` (114 L, "last verified 2026-08-05") vs the runtime `ss` actually shows; `docs/CONTEXT.md` (374 L) | `read`, `grep`, `ss`, `wc`, unit files |
| Test coverage | `tests/` (10 `.py`, 2263 L) vs a live-trading system | `ls`, `wc`, `grep` |
| Monolith | `harness.py` (4763 L) | `wc -l`, `grep -c`, `git log` |
| Defect #216 | `opentrader-daily-allocator.service` `AttributeError: _daily_laggard.target_weights` | `gh issue view 216`, unit file, sandbox source |
| Claims governance | `data/wayfinder/toc/` ledger + TOC.md, `docs/adr/0007-reground-victory-path.md` | read-only `json.load`, `read`, `ls` |

**Out of scope (per AGENTS.md, human 2026-09-02):** crypto paper lane. Where
crypto-lane dirt appears in shared repo state (`data/shadow_scaled/*`,
`data/paper_state.json`) it is counted for hygiene but not diagnosed.

**One-line answer.** The FX operating lane is alive and producing venue evidence
(tracked caches were rewritten during this very session, §1.4), but every
*governance* surface that is supposed to constrain it is failing its own written
rule: `.gitignore` ignores nothing that matters, the canonical architecture map
is 36 days stale and wrong on facts it is the "single source of truth" for,
there is no test runner and no CI, and the claims ledger has 22 open questions,
zero per-phase spend attribution, and no checkpoint in 10 days.

---

## Verified findings (file:line)

### 1. Repo hygiene

**1.1 `git status --porcelain` = 194 entries: 174 untracked + 20 modified.**
`VERIFIED` — run twice during this session, identical counts.

**1.2 The untracked `.npz` are 172 files, 439 M, all in `data/fx_expert/`, and
`.gitignore` does not cover them.**
`VERIFIED` —
- `git status --porcelain | grep -c '\.npz'` = **172**; all under
  `data/fx_expert/` (no other npz anywhere in porcelain).
- Breakdown by producer name: **164** `preds_g*.npz`, **7** `oos_scores_g*.npz`
  (incl. `oos_scores_gab1.npz`), **1** `panel.npz` = 172.
- `du -ch data/fx_expert/*.npz | tail -1` = **439 M** (`data/fx_expert/` total
  1.3 G; `data/` 3.4 G; repo 20 G).
- `.gitignore:28-34` lists `*.bin`, `*.safetensors`, `*.pth`, `*.pt`, `*.ckpt`,
  `*.h5`, `*.gguf` — **no `*.npz`**, and no `data/fx_expert/` entry:
  `grep -c npz .gitignore` = **0**, `git check-ignore -v
  data/fx_expert/oos_scores_g157.npz` **exits 1** (not ignored).
- `git ls-files '*.npz'` = **0** → none is tracked, i.e. these files are
  simultaneously *unmanaged* (never committed) and *unignored* (permanent
  `??` noise). Producers: `fxexpert/train.py:233,235`,
  `fxexpert/data.py:303`, `fxexpert/serve.py:33`, `fxexpert/loop.py:124`.
- The 2 non-npz untracked entries are `pwa/icon-192.png`, `pwa/icon-512.png`
  (see 1.7).

**1.3 `data/fx_expert/` *is* tracked — as 341 JSON files, mostly per-generation
artifacts.** `VERIFIED` — `git ls-files data/fx_expert | wc -l` = 341, of which
**163** `gate_g*.json` and **164** `train_g*.json` (`g00`…`g162`) plus
`lane_state_g{137,138,151}.json`, `claims*.json`, `signals.json`,
`loop_state.json`, `refresh_state.json`, `panel_meta.json`, three
`trail_state_fxexp-*.json`. So the loop's *small* per-generation JSON is
committed (163+164 ≈ one commit-worthy file per generation) while its *large*
binary sibling is not — the ignore policy matches neither side.

**1.4 The "churning state files" are tracked write-through caches; at least 8 FX
lane caches were dirty, and 6 files changed while this report was being
written.** `VERIFIED` — dirty set (20 modified): 8 FX lane caches
(`data/fx_h1rev.json`, `data/fx_h4brk.json`, `data/fx_intraday.json`,
`data/fx_reconcile_cursor.json`, `data/fx_watchdog_state.json`,
`data/fx_expert/trail_state_fxexp-g{137,138,151}.json`), `data/TRADER.md`,
9 `data/shadow_scaled/*` (crypto lane, out of scope), 2 `data/warden/*`.
`stat` mtimes (`-0500`, session ran ≈15:45–15:56): `fx_watchdog_state.json`
15:45:10, `warden/*` 15:45:13, `shadow_scaled/*` 15:50:37,
`trail_state_fxexp-g151` 15:51:53, `-g138` 15:52:16, `-g137` 15:52:39. Tracked
in git while documented as caches: `docs/ARCHITECTURE.md:96-98` ("`data/fx_state.json`
… **Cache only — venue (OANDA) is authoritative**"; same for `fx_crashtest.json`,
`fx_intraday.json`, `fx_watchdog_state.json`). A "cache only, never authoritative"
file that is version-controlled turns every lane tick into a tree-dirtying write.

**1.5 `.gitignore` is cosmetic for 286 *tracked* files.** `VERIFIED` —
`git ls-files -i -c --exclude-standard | wc -l` = **286**, incl.
257 `data/shadow_scaled/history/*`, 15 `.mimosa/*` session-hook files
(`tui/.mimosa/*`, `data/wayfinder/toc/.mimosa/*`), 8 `data/research/eval_transforms/*`,
`tests/pty_resize_test.py`, `data/gpu_scheduler/adapters/momentum-agent/*`.
The file says so itself: `.gitignore:142-144` "Session-hook churn (mimosa) —
per-session baselines, never project code. Untracked 2026-09-05: 829 tracked
files were polluting every git status." An ignore rule never untracks; the
cleanup was declared in a comment and never executed for these paths.
`tests/pty_resize_test.py` is the cheapest proof: `.gitignore:158` ignores it
**and** `git ls-files tests/` lists it.

**1.6 `data/TRADER.md` is a tracked runtime-written file.** `VERIFIED` —
`git diff data/TRADER.md` = 1 line, the self-timestamp
`Last updated: 2026-09-10T12:47:37Z` → `2026-09-10T19:45:27Z`, mtime 14:45:27
(`-0500`). The harness rewrites a committed file every few hours by design
(`data/TRADER.md:1-6`, "Pruned and consolidated automatically").

**1.7 Two served PWA icons are untracked → a fresh clone serves a broken icon.**
`VERIFIED` — `pwa/icon-192.png` and `pwa/icon-512.png` are `??` and
`git ls-files pwa/` lists only `manifest.webmanifest`, `sw.js`;
`dashboard.py:894-901` serves `/icon-192.png` and `/icon-512.png` via
`FileResponse(_PWA / "icon-192.png")`, and `dashboard.html:9` is
`<link rel="icon" type="image/png" href="/icon-192.png">`. (mtime 2026-09-07
22:16 — they were created with the PWA ship commit `ffe3978` and left behind.)

**1.8 Repo scale context.** `VERIFIED` — `git ls-files | wc -l` = 1752 tracked
files, of which **929 (53%) live under `data/`**; `du -sh .` = 20 G,
`data/` 3.4 G (largest: `data/fx_expert` 1.3 G, `data/setup_search` 1.2 G,
`data/cache` 430 M).

### 2. Doc drift — ARCHITECTURE.md vs the runtime `ss` shows

**2.1 The canonical doc is 36 days stale by its own header.** `VERIFIED` —
`docs/ARCHITECTURE.md:3` "**Last verified:** 2026-08-05"; current date
2026-09-10 UTC. `:5` claims "This is the single source of truth. If a doc or
config disagrees with this file, this file wins" — while `:20` says
"`llama-swap` :8080 NOT INSTALLED" and the file inventories no FX lane at all,
though AGENTS.md (2026-09-02) makes the FX arm the only active focus.

**2.2 The monolith line count in the doc is wrong by 503 lines.**
`VERIFIED` — `docs/ARCHITECTURE.md:109` "`harness.py` is 4260 lines — the
biggest maintainability debt (deferred split)"; actual `wc -l harness.py` =
**4763** (+503, +11.8% understated). Same file was last touched by `ffe3978`
(2026-09-10) — the doc drifted while it was being called the authority.

**2.3 Two docs disagree about whether the harness is alive, and neither matches
the on-disk evidence.** `VERIFIED`
- `docs/ARCHITECTURE.md:19` "`harness.py` | — | **DEAD** | `health.json`:
  `"harness_state":"dead"`. Last launch targeted :5801 (dead proxy)."
- `.opencode/skills/next-session/SKILL.md:3,12` ("verified 2026-09-07")
  "`opentrader-harness.service` | — | running — stock/crypto paper … quiet book".
- Ground truth available read-only: `data/health.json` says
  `"harness_state": "running"` with **mtime 2026-08-27 12:30** (14 days stale),
  and the newest snapshot `data/history/cycle_32970.json` has **mtime
  2026-09-07 15:01**. So health.json contradicts ARCHITECTURE.md *and* is itself
  stale, while the cycle snapshots prove activity up to 2026-09-07 — long after
  the doc's 2026-08-05 "DEAD".
- Coverage gap: `docs/ARCHITECTURE.md:93` literally excuses the stale artifact
  ("`data/history/cycle_*.json` | Live cycle snapshots (harness dead → stale)")
  instead of fixing the state file it cites as truth.

**2.4 The port table is stale, and one documented backend is documented as down
while listening.** `VERIFIED` (`ss -ltnp`, 2026-09-10)
| Doc claim | `ss` now | Verdict |
|---|---|---|
| `docs/ARCHITECTURE.md:15` ollama :11434 UP, "**Only live LLM**" | :11434 LISTEN | UP, but "only" is false — :5802, :5804 also LISTEN and llama.cpp units exist (`opentrader-llama-gpu1.service:9`, `opentrader-warden-gre.service:9`, `opentrader-warden-qwen.service:6`) |
| `:17` mcp_server :8092 UP | :8092 LISTEN | consistent |
| `:16` dashboard :8097 UP | :8097 LISTEN (127.0.0.1 **and** tailnet 100.124.30.55) | consistent |
| `:18` gpu_sync :5801 UP (DEGRADED), "backends :5802/:5803, both DOWN" | :5801 LISTEN, **:5802 LISTEN**, :5803 nothing | **stale**: :5802 is up; and no unit declares 5801 (`grep` over `~/.config/systemd/user/opentrader-*.service`), while `opentrader-gpu-sync.service` is a **symlink to /dev/null** (masked) → the documented owner of :5801 is not backed by a live unit. The :5801 owner is `UNVERIFIABLE-HERE`. |
| `:20` llama-swap :8080 NOT INSTALLED | :8080 nothing | consistent |
| (absent) | :3080, :3420, :4096, :4173, :5810, :5830, :8085, :8086, :8787, :20680, :45211 … | undocumented in ARCHITECTURE.md; some documented *elsewhere* (`docs/agents/dev-plan.md:74` router :5810; `docs/agents/handoff-ultimate.md:162` headroom :8787) |

**2.5 AGENTS.md's own "stopped and disabled" claim conflicts with listening
sockets.** `VERIFIED` (socket) vs `READ-FROM-DOCS` (text) — AGENTS.md
(amendment 2026-08-31) states "`qwen38-serve.service` and
`headroom-proxy.service` are stopped and disabled"; `docs/agents/handoff-ultimate.md:162`
declares headroom :8787 the "**mandatory front for agent sessions**". `ss` shows
**:8787 and :5804 both LISTEN**. Which unit owns them is `UNVERIFIABLE-HERE`
(no dbus/ps) — but the two written statements cannot both be current.

**2.6 Four unit files declare the same port 5802.** `VERIFIED` (file evidence)
— `opentrader-llama-gpu1.service:9` (Qwen3.8-4B, CUDA),
`opentrader-warden-gre.service:9` (Granite-4.2-8B, Vulkan),
`opentrader-fleet-qwythos-9b-mtp.service:8`, `opentrader-fleet-test.service:11`
all pass `--port 5802`. Exactly one listener exists on :5802. TOC Q16
(`data/wayfinder/toc/TOC.md:44`) says Granite-on-GRE owns :5802 with Qwen on
:5804 as the fallback — i.e. `opentrader-llama-gpu1.service` is a stale unit
that will fight the warden for the port if it is ever started. Which units are
enabled is `UNVERIFIABLE-HERE`.

**2.7 CONTEXT.md: 374 lines, of which one bullet is 214 (57%).** `VERIFIED` —
`wc -l docs/CONTEXT.md` = 374 (read returned 374; the bullet-span script counts
375 with the trailing newline). 36 top-level bullets; the `- **Rule floor**`
bullet spans `docs/CONTEXT.md:8-221` = **214 lines** — it is a decade-log of
2026-08-13 research findings (rule floor, generalization, macro probe,
cross-asset, intl, metric screen, contrarian, R1/R1b/R1c, R2, R1d, data
integration, weight evolution, engine integrity) pasted into a *glossary*.
No other bullet exceeds 20 lines. The doc's own purpose statement is
`docs/CONTEXT.md:1-4`: "Terms as this project actually uses them … don't drift
to synonyms" — entry length is the drift.

**2.8 Three ADR-0007-mandated reconciliations in CONTEXT.md were never made.**
`VERIFIED`
- `docs/adr/0007-reground-victory-path.md:80-82`: "The Runway ladder is
  **1% → 10%** per ADR-0002; CONTEXT.md's '15%' is drift to be reconciled in
  CONTEXT.md". Still unreconciled: `docs/CONTEXT.md:224` "15% per position";
  `docs/CONTEXT.md:293` "ladder to 15%".
- `docs/adr/0007-reground-victory-path.md:31-32`: "the '19-symbol universe'
  phrase in CONTEXT.md/AGENTS.md/`experts.py` is stale boilerplate". Still
  present: `docs/CONTEXT.md:162` "not validated on the harness's real-time
  19-symbol universe".
- Wide-universe numbers contradict the binding section of AGENTS.md:
  `docs/CONTEXT.md:17-18` says "−37.8% net (PF 0.71)" / "−40.4% (PF 0.83)",
  while AGENTS.md ("Universe generalization", binding) and
  `docs/adr/0007-reground-victory-path.md:7-8` say **−45.95% registry /
  −41.07% wide, re-verified 2026-08-23 on the regenerated archive**. Two
  different truths for the project's central falsification number, in two docs
  that both claim authority.

**2.9 CONTEXT.md contradicts itself on the same number.** `VERIFIED` —
`docs/CONTEXT.md:10` "The 08-12 falsification (−2.73%/503 trades)" vs
`docs/CONTEXT.md:228` "The 08-12 '−2.66%/501 trades' number". Same event, two
numbers, 220 lines apart.

**2.10 A cross-file line citation in CONTEXT.md is stale.** `VERIFIED` —
`docs/CONTEXT.md:172` cites "`harness.py:2636-2639` maps bull/bear→up/down";
in the current file the mapping is at `harness.py:2774` / `:2789` and the
regime function at `harness.py:2847` (`:2636` is now a `Signal` construction
inside the rule screen). With `harness.py` at 4763 lines, every absolute line
citation into it is a time bomb.

**2.11 The two runtime maps that exist agree on nothing but the dashboard.**
`READ-FROM-DOCS`/`VERIFIED` — `docs/ARCHITECTURE.md:13-20` (2026-08-05) vs
`.opencode/skills/next-session/SKILL.md:9-20` (2026-09-07): the maps disagree
on harness state (2.3), on the owner of :5801/:5802 (2.4), and ARCHITECTURE.md
does not mention the FX lanes, the trained lanes, or the warden at all, while
the skill map does not mention the arena/setup_search stack ARCHITECTURE.md
leads with. §1 of ARCHITECTURE.md opens with "Do NOT trust historical docs for
ports/models" — the file that says that is now a historical doc.

### 3. Test coverage vs a live-trading system

**3.1 Inventory.** `VERIFIED` — `tests/` holds 10 `.py` files, **2263 lines**:
6 pytest-named (`test_continuity.py` 152, `test_fx_lanes.py` 104,
`test_fx_runner_reconcile.py` 263, `test_newsfeed.py` 185,
`test_oanda_price_precision.py` 101, `test_prop_gate.py` 58 = 863 lines) plus 4
script-style (`break_deep.py` 605, `break_scenarios.py` 475,
`pty_resize_test.py` 52, `smoke_multi_gpu.py` 268 = 1400 lines). Fixtures:
`tests/fixtures/newsfeed/` only (5 files).

**3.2 There is no test runner and no CI.** `VERIFIED` — no `pyproject.toml`,
`pytest.ini`, `setup.cfg`, `tox.ini` at repo root (all four `ls` = "No such
file"); **no `conftest.py` anywhere outside `.venv`** (`glob **/conftest.py`
returns only site-packages hits); **no `.github/` directory at all**. `pytest
9.1.1` is installed in `.venv`, so tests *can* run — nothing runs them. For a
system whose AGENTS.md defines a "fatal defect" class (`docs/CONTEXT.md:309-311`:
silent hold, state corruption, order rejection, >15 bps slippage) there is no
gate that runs on change.

**3.3 The FX live paths are essentially untested.** `VERIFIED` — per-module
reference counts in `tests/`: `fx_crashtest` **0**, `fx_watchdog` **0**,
`fx_trail_check` **0**, `fx_warden` **0**, `fx_expert_lane` **0**,
`fx_shadow` **0**, `fx_review` **0**, `fx_traj` **0**, `fx_challenger` **0**,
`lane_claims` **0**, `lanes` **0**; only `fx_h1rev`, `fx_h4brk`, `fx_d1mom10`
(1 each — pure signal functions: `rsi2`, `channel`, `rank_momentum`,
`tests/test_fx_lanes.py:11-13`) and `fx_runner` (1 —
`tests/test_fx_runner_reconcile.py`, which drives reconciliation with a
`FakeEx`). Untested are exactly the things AGENTS.md calls load-bearing:
per-lane size attribution & FIFO-vs-venue `pl` for the crash lane
(`docs/ARCHITECTURE.md:111`, AGENTS.md ledger rules), the trail-check surgical
closes (TOC Q24), the warden verifier (TOC Q14), and the assertion that
`--once` means REAL (contract stated only in AGENTS.md prose) — a bug in that flag
is the highest-consequence defect in the repo and has no test.

**3.4 Test style is split, so "run the tests" is ambiguous.** `VERIFIED` —
`test_fx_lanes.py`, `test_fx_runner_reconcile.py`, `test_newsfeed.py`,
`test_oanda_price_precision.py`, `test_prop_gate.py` have `__main__` blocks
(script-runnable); `test_continuity.py` defines `test_restart_survival()` /
`test_forced_reset()` with **no** `__main__` (pytest-only) and imports
`harness.OpenTraderHarness` (`tests/test_continuity.py:20`);
`test_prop_gate.py` has **no `test_` functions** at all (a `main()` with
`check(name, cond)`). Unittest-style classes dominate. This mixed convention
plus no config is *why* there is no runner.

**3.5 The one tracked-ignored test file is the resize regression test.**
`VERIFIED` — `tests/pty_resize_test.py` is listed in `.gitignore:158` *and*
tracked; `git check-ignore -v` on it exits 1 (tracked files are not ignored),
so the entry is inert. Either the file is test infrastructure (unignore it) or
it is not (delete it).

**3.6 What is *not* in the gap.** `VERIFIED` (positive) — the recent FX work
does have real unit coverage of the two highest-risk *pure* boundaries:
price precision / order body construction
(`tests/test_oanda_price_precision.py:32,48,73` → `TestPriceDigits`,
`TestFmtPrice`, `TestPlaceOrderBody` against `exchange/oanda.py`) and runner
reconciliation with a fake exchange (263 lines). The gap is the process-level
half (services, timers, attribution, `--once`), which no test can reach without
a harness the repo does not have.

### 4. The `harness.py` monolith

`VERIFIED` — `wc -l harness.py` = **4763**, `wc -c` = 221,543 bytes,
**1 class**, **51** `def`/method definitions, last modified by `ffe3978`
(2026-09-10 08:18 -0500). `docs/ARCHITECTURE.md:109` still says 4260 (see 2.2);
its "deferred split" has been deferred across at least one further 503-line
growth. Structure/behaviour notes: the regime mapping and attribution live at
`harness.py:2774`/`:2789`/`:2847`, and the rule screen at `:2630-2645` — i.e.
the hot decision path is buried mid-file, ~1000 lines past where the
cross-reference in `docs/CONTEXT.md:172` says it is. Two systemd units
ExecStart this same file with different flags and state dirs
(`opentrader-harness.service:12`, 19 symbols, `--cash 500`;
`opentrader-shadow.service:12`, 28 symbols + `--state-dir
/home/mrc/opentrader/data/shadow_scaled`), so a single edit to `harness.py`
lands on both lanes at once.

### 5. Defect #216 — `_daily_laggard.target_weights` (and its true blast radius)

**5.1 The failing unit runs sandbox code, not repo code.** `VERIFIED` —
`~/.config/systemd/user/opentrader-daily-allocator.service:15`:
`ExecStart=/home/mrc/opentrader/.venv/bin/python3
/home/mrc/opentrader-sandbox/strategies/daily_allocator.py --universe intl
--persist` with `WorkingDirectory=/home/mrc/opentrader-sandbox`. `grep -rn
"_daily_laggard"` over the repo returns exactly one hit — the map that records
the bug (`.opencode/skills/next-session/SKILL.md:19`) — so #216 is a
**sandbox-tree defect** that the repo's own defect log cannot see
(`data/defect_log.json` is gitignored, `.gitignore:91`).

**5.2 The AttributeError is real and is not laggard-specific.** `VERIFIED` by
static read of the sandbox copy:
- `strategies/daily_allocator.py:84` builds the module name:
  `return _load_module(f"_daily_{name}", os.path.join(here, f"{name}.py"))` →
  for `expert == "laggard"` this yields the module `_daily_laggard`.
- `strategies/daily_allocator.py:199-200`: `mod = _expert_module(expert)` then
  `targets = mod.target_weights(closes, **EXPERT_CFG[expert])`.
- **No module defines `target_weights`**: `grep -rn "def target_weights"
  /home/mrc/opentrader-sandbox` = **0 hits**; `strategies/laggard.py` defines
  only `run(closes, universe=None, *, ...)` at `laggard.py:34`.
- Therefore **every** expert selection path fails the same way, not only days
  when `pick_expert` chooses laggard (`EXPERT_CFG` at
  `strategies/daily_allocator.py:51` covers further experts). #216's "first
  read" (`gh issue view 216`) names the right line but understates the blast
  radius: the allocator API contract `run()` → `target_weights()` is broken
  wholesale, so "fix the call to the current API" must decide what
  `target_weights` even means (`run()` has a different signature and returns a
  different shape), not just rename a call.
- The timer is live and daily: `opentrader-daily-allocator.timer:8`
  `OnCalendar=*-*-* 18:35:00` (and `:9` `Persistent=true`) → a guaranteed daily
  failure into the journal, forever, with `StandardError=journal`
  (`…allocator.service:17`).
- Current unit state (`FAILED` / disabled since 2026-09-06 18:35 UTC) is
  `CLAIMED` from #216 and `.opencode/skills/next-session/SKILL.md:19`;
  `UNVERIFIABLE-HERE` (§0.2).
- Scope ruling holds: `READ-FROM-DOCS` — #216 and the skill map both state the
  FX lanes do not depend on this allocator; nothing in `strategies/fx_*.py`
  references it (`VERIFIED`: `grep -rn "daily_allocator" strategies/` in the
  repo = no hits).

**5.3 Repo-vs-sandbox visibility gap.** `VERIFIED` — the failing unit's
`ExecStart` pins a repo interpreter (`/home/mrc/opentrader/.venv/bin/python3`)
to a sandbox script, while the repo's defect log is gitignored
(`.gitignore:91` → `data/defect_log.json`). The only in-repo trace of the
failure is one line in an agent skill map
(`.opencode/skills/next-session/SKILL.md:19`) plus GitHub issue #216 — so a
sandbox-side breakage of a repo-scheduled job is invisible to the repo's own
audit surface (AGENTS.md audit gate 1: "enumerate its writers").

### 6. ToC claims-governance ledger

**6.1 Ledger census.** `VERIFIED` (`json.load` of `data/wayfinder/toc/ledger.json`)
— `version 1`, task "OpenTrader frontier under ADR-0007", `currentPhase
"oanda"`, created 2026-08-29, **33 variables** (15 `known`, 12 `computable`,
5 `explore`, 1 `unknowable`), **24 open questions** (22 `open`, 2 `closed`:
Q01, Q10), 8 history entries, `lastCheckpoint "checkpoints/ckpt-04.md"`,
totals `spent 51218 / checkpointed 51218 / compactionTokens 51218`.

**6.2 The budget table is inert: every phase reports `spent: 0` while the
lifetime total is 51,218.** `VERIFIED` — 8 phase records
(`155`, `v11-recompute`, `156-memo`, `157`, `157`, `continuity`, `oanda`,
`oanda`); **phases with `spent > 0`: 0**. `data/wayfinder/toc/TOC.md:9`
renders the active phase from that data: `| oanda | 25000 | 0 | 25000 | 0% |`
— i.e. the phase that produced Q11–Q24 (fourteen findings, 2026-09-06…09) is
recorded as having consumed **zero** tokens, while `TOC.md:10` shows lifetime
51218. Per-phase accounting cannot answer "which gate consumed the budget",
which is the whole point of the allowance.

**6.3 Phase bookkeeping is corrupt at the edges.** `VERIFIED` — duplicate
phase names (`157` twice, `oanda` twice) and **two phases open
simultaneously** (`157` has `endedAt: null` and `oanda` also has
`endedAt: null`); the second `157` record starts 2026-08-30T02:53:29 with
`checkpoints: 0` and never closed. An "allowance" whose phases never close
cannot gate anything.

**6.4 The binding governance repairs in ADR-0007 were not executed.**
`VERIFIED` — `docs/adr/0007-reground-victory-path.md:80-82` (15%→10% in
CONTEXT.md) and `:31-32` (stale "19-symbol universe") are both still
unreconciled, three weeks later (§2.8). ADR-0007 `:72-79` binds the ledger as
the claims registry; `:90-94` suspends non-feeding workstreams — CONTEXT.md's
glossary still carries all of the suspended research history (§2.7).

**6.5 The ledger is being used as a research journal, and the
findings-log layer it declares is empty.** `VERIFIED` — `TOC.md:20-23` declares
a "Raw findings log (append-only, never compacted away)" table with **zero
rows**, and `data/wayfinder/toc/chapters/04-raw/` is an **empty directory**
(`ls`, dir mtime 2026-08-28). Meanwhile **18 of the 22 open questions open with
a finding heading rather than a question** (counting the ledger's own texts:
Q06-Q09, Q11-Q24; 14 of the 22 were created 2026-09-06 or later) — e.g. Q12
"fxexpert tournament LIVE 2026-09-06 …", Q20 "Conviction auction LIVE: 53
symbols held …", Q24 "Simulated trail/TP LIVE …". So the append-only findings
channel is unused while the question channel absorbs findings it cannot close.

**6.6 No checkpoint in 10 days, with 14 questions accrued since.** `VERIFIED` —
ledger `lastCheckpoint = checkpoints/ckpt-04.md`; `stat` shows
`ckpt-04.md` mtime **2026-08-31 09:20** (ckpt-01/02/03: 08-29), and TOC.md:27
declares it "(verified)". Q11 (first of the accrual wave) is dated 2026-09-07.
The Q03 entry in TOC.md:32 documents the exact failure mode — an operator wrote
a question into `deployability_status.json` "but did not execute toc open add".

**6.7 Duplicate ledger entries.** `VERIFIED` — Q04 and Q05 (TOC.md:33-34;
ledger Q04/Q05) both state the `exchange/oanda.py` live/sandbox fork; Q05's text
opens by restating Q04 verbatim and then adds the venue-reconciliation tag idea.
ADR-0007 makes Q04 the human-gated merge decision; two rows for it is how a
governance backlog grows without a decision.

**6.8 The documented CLI is not on PATH.** `VERIFIED` — AGENTS.md (claims
governance) and `docs/adr/0007-reground-victory-path.md:73` name the CLI `toc`
(source `/home/mrc/ai/table-of-context/`); `which toc` → not found in this
shell's PATH; the executable exists at `/home/mrc/ai/table-of-context/toc`
(310 B, mode `-rwx--x--x`, mtime 2026-08-25). Whether an interactive shell
defines an alias is `UNVERIFIABLE-HERE`, but the ledger in this session was
readable only by `json.load` — the governed path (`toc add/open/promote`) could
not be exercised, which is consistent with 6.2/6.3 (programmatic writes that
bypass the CLI's accounting).

**6.9 The governance tree itself carries tracked session junk.** `VERIFIED` —
`git ls-files data/wayfinder/` includes 6 `.mimosa/*` hook-state/session files
inside `data/wayfinder/toc/`, plus `TOC.md`, `ledger.json`, the 4 chapters and
the 4 checkpoints. The ledger **is** version-controlled (good, and required for
promotion auditability) — the noise is the `.mimosa` payload (§1.5).

---

## Health assessment

| Dimension | Grade | Basis |
|---|---|---|
| FX lane liveness / evidence flow | **Green (observed)** | 8 tracked FX caches rewritten during the session (§1.4); venue-reconciled lane work is clearly running; `data/fx_expert/` accumulating generations `g00…g162` |
| Repo hygiene | **Red** | 194 porcelain entries; 172 unignored 439 M `.npz`; 286 tracked-but-ignored files; 8 tracked write-through caches dirty on every lane tick; 2 served PWA icons untracked (§1) |
| Doc truth (canonical map) | **Red** | ARCHITECTURE.md 36 d stale, wrong line count, stale port table, masked "owner" of :5801, contradicts the other runtime map and `data/health.json`, and predates the FX focus entirely (§2.1-2.6, 2.11) |
| Doc truth (glossary) | **Amber-Red** | CONTEXT.md 374 L with a 214-line bullet (57%); three ADR-mandated reconciliations unexecuted; two self-contradictions and one number contradicting AGENTS.md (§2.7-2.10) |
| Test coverage | **Red** | No runner, no CI, no `conftest.py`; 11 of 15 FX modules referenced by zero tests; the `--once`=REAL contract untested (§3) |
| Monolith debt | **Red (accepted debt, drifting)** | `harness.py` 4763 L / 221 KB / 51 defs, two units sharing it, doc understates by 503 L (§4) |
| Open defect load | **Amber** | #216 is a *sandbox* trap with a wider blast radius than recorded and a daily timer feeding it; correctly out of FX scope, wrongly invisible to the repo defect log (§5) |
| Claims governance | **Red** | Per-phase spend inert (0 vs 51,218 lifetime); two open phases; no checkpoint in 10 d; findings-log layer empty while 22 questions are open; ADR-0007 repairs unexecuted (§6) |

**Overall: Amber-Red / degraded.** The narrow FX question ("is the venue
evidence accruing?") answers yes. The cross-cutting question ("can this repo
tell the truth about itself?") answers no on four independent surfaces at once
— and the failure mode is consistent: *the written rule is stricter than the
executed practice* (ignore lists that do not ignore, budgets that record zero,
checkpoints that stop, a "single source of truth" that nothing checks). Note the
pattern in the small: `.gitignore:143` announces an untracking that
`git ls-files -i -c` proves was never run; `TOC.md:9` announces a budget that
the ledger records as zero; `ARCHITECTURE.md:5` announces supremacy over every
other doc while being wrong about the one thing it claims to have verified.

Nothing found here indicates the FX lane is trading on wrong numbers. The
integrity risks are of the kind that hide errors rather than create them: the
session that cannot see a dirty tree cannot notice a lane writing where it
should not; the session with no test runner cannot notice `--once` semantics
flipping; the session with a 36-day-stale port map cannot attribute a listener
to a lane.

---

## Defects & risks

| # | Defect | Evidence (`file:line`) | Severity | Fix shape |
|---|---|---|---|---|
| D1 | `*.npz` uncovered by `.gitignore`; 172 files / 439 M permanent `??` noise | `.gitignore:28-34` (no `*.npz`); `git check-ignore` exit 1; `git ls-files '*.npz'` = 0 (§1.2) | Med | Add `*.npz` (and/or `data/fx_expert/*.npz`) next to the other model-data extensions; decide deliberately whether `panel.npz` is regenerable (`fxexpert/data.py:303`) |
| D2 | 286 tracked files match `.gitignore`; the 2026-09-05 untracking was never done | `.gitignore:142-144`; `git ls-files -i -c --exclude-standard` = 286 (§1.5) | Med | `git rm --cached` the `.mimosa/*`, `data/shadow_scaled/history/*`, `data/research/eval_transforms/*` sets in one reviewable commit |
| D3 | Write-through caches are version-controlled → every lane tick dirties the tree | 8 dirty FX caches; `docs/ARCHITECTURE.md:96-98` calls them "cache only" (§1.4) | **High** (hides real changes in noise) | Untrack `data/fx_{state,crashtest,intraday,watchdog_state,h1rev,h4brk,d1mom10,reconcile_cursor}.json`, `data/fx_expert/trail_state_*.json`, `data/fx_shadow_state.json`, `data/warden/*_state.json` |
| D4 | `data/TRADER.md` rewritten by the harness on a timer | `git diff data/TRADER.md` (timestamp line); `data/TRADER.md:6` (§1.6) | Low | Untrack, or write to `data/state/TRADER.md` |
| D5 | Served PWA icons untracked → broken favicon/install on a fresh clone | `git status` `?? pwa/icon-*.png`; `dashboard.py:894-901`; `dashboard.html:9` (§1.7) | Low | `git add -f` the two PNGs (mtime 2026-09-07 22:16, same session as `ffe3978`) |
| D6 | ARCHITECTURE.md's `harness.py` size is wrong by 503 lines | `docs/ARCHITECTURE.md:109` vs `wc -l harness.py` = 4763 (§2.2) | Low | Re-verify header; stop citing line counts, cite symbols |
| D7 | Two runtime maps contradict each other on harness liveness; both contradict `data/health.json`, which itself is 14 d stale | `docs/ARCHITECTURE.md:19`, `.opencode/skills/next-session/SKILL.md:12`, `data/health.json` (mtime 2026-08-27), `data/history/cycle_32970.json` (mtime 2026-09-07) (§2.3) | **High** | One runtime map, generated; `health.json` stamped with a heartbeat and a staleness rule |
| D8 | Port table wrong: :5802 documented DOWN but listens; :5801 documented as gpu_sync but its unit is masked (`→ /dev/null`) and no unit declares 5801; ten listeners undocumented | `docs/ARCHITECTURE.md:17-20` vs `ss` (§2.4) | **High** | Regenerate §1 of ARCHITECTURE.md from `ss` + unit ExecStarts, keep it dated and short |
| D9 | Four units declare `--port 5802` | `opentrader-llama-gpu1.service:9`, `opentrader-warden-gre.service:9`, `opentrader-fleet-qwythos-9b-mtp.service:8`, `opentrader-fleet-test.service:11` (§2.6) | **High** | Retire or mask the superseded units (TOC Q16 says GRE Granite owns :5802, :5804 is the fallback) |
| D10 | AGENTS.md says headroom/qwen38 services are stopped and disabled while :8787 and :5804 listen | AGENTS.md (amendment 2026-08-31) vs `docs/agents/handoff-ultimate.md:162` vs `ss` (§2.5) | Med | Reconcile the three statements in one place; state which proxy is the mandatory front *today* |
| D11 | CONTEXT.md glossary-bloat: one bullet = 214 of 374 lines (57%) | `docs/CONTEXT.md:8-221` (§2.7) | Med | Move the log body to `docs/research-archive/` or the ToC chapter it belongs to; leave a 10-line term + pointer |
| D12 | ADR-0007's binding CONTEXT.md repairs unexecuted (15% → 10%; stale "19-symbol"; wide-universe numbers stale) | `docs/adr/0007-...md:31,80-82` vs `docs/CONTEXT.md:162,224,293,17-18` (§2.8) | **High** (a stale ceiling invites live sizing at the wrong level) | Execute the two edits; add the 2026-08-23 re-verified numbers or point at AGENTS.md as the single source |
| D13 | CONTEXT.md self-contradiction on the 08-12 falsification number | `docs/CONTEXT.md:10` (−2.73%/503) vs `:228` (−2.66%/501) (§2.9) | Low-Med | Keep one; cite the probe |
| D14 | No test runner, no CI, no `conftest.py`; 11/15 FX modules untested; `--once`=REAL contract untested | §3.2-3.4 | **High** | Add a minimal `pytest.ini`/`pyproject` + a `tests/test_once_flag.py` asserting dry-vs-REAL; a pre-push `pytest -q` hook if CI is too heavy |
| D15 | `harness.py` 4763 L / 51 defs servicing two lanes from one file | §4; `opentrader-harness.service:12`, `opentrader-shadow.service:12` | Med | Split the venue-agnostic runner from lane wiring; at minimum, extract the regime/attribution block out of the middle of the file |
| D16 | #216 blast radius understated: `target_weights` exists in **no** expert module, so the allocator cannot run for **any** expert, not just laggard; daily timer keeps firing into the journal | `opentrader-daily-allocator.service:15`, `.timer:8`, sandbox `strategies/daily_allocator.py:84,199-200`, `strategies/laggard.py:34`, `grep "def target_weights"` = 0 (§5.2) | Med (out of FX scope, but daily noise + a live paper lane silently dead) | Pick one of #216's three options; option (b) "retire the unit + timer" is the only one consistent with ADR-0007 §7 suspension and with the allocator's API being gone |
| D17 | FX/sandbox defects are invisible to the repo defect log (`data/defect_log.json` is gitignored) even when the failing unit lives in the sandbox and is started by a repo-pinned venv | `.gitignore:91`; `opentrader-daily-allocator.service:15` (§5.1, §5.3) | Med | Track a defects *log* file that is append-only and committed (or move the log under `docs/`) |
| D18 | ToC per-phase budget inert (all 8 phases `spent: 0` vs lifetime 51,218); two phases open at once; duplicate phase rows | `data/wayfinder/toc/ledger.json` phases; `TOC.md:9-10` (§6.2-6.3) | **High** for claims governance | Close `157`; make the CLI the only writer of phase spend; refuse a `toc` write if a prior phase is open |
| D19 | No checkpoint in 10 days (ckpt-04 = 2026-08-31) while 14 questions accrued; Q03 records exactly this operator failure | `TOC.md:27,32`; `stat ckpt-04.md` (§6.6) | **High** | Checkpoint gate: no new `[known]` promotion without a ckpt that covers the questions added since the last one |
| D20 | Findings log layer empty (`TOC.md:20-23` zero rows; `chapters/04-raw/` empty) while findings are written into `openQuestions` (Q11-Q24 are verdicts, not questions) | §6.5 | Med | Route findings to `04-raw`; keep openQuestions to decisions that need a human |
| D21 | Duplicate governance row (Q04/Q05 both the oanda fork; Q05 restates Q04) | `TOC.md:33-34`; ledger Q04/Q05 (§6.7) | Low | Merge; Q05's tag-stamping idea becomes its own row |
| D22 | Documented `toc` CLI not resolvable (`which toc` → not found); ledger written programmatically | `/home/mrc/ai/table-of-context/toc`; `docs/adr/0007-...md:73` (§6.8) | Med | Put the CLI on PATH (symlink in `~/.local/bin`) or state the exact invocation in AGENTS.md |

**Highest-leverage five, in order:** D3 (untrack the caches — this is what makes
the tree readable again), D7/D8 (one generated runtime map — this is what makes
"is the lane up?" answerable), D14 (`--once` test + runner — this is the only
defect class that loses money), D18/D19 (make the budget and checkpoints
actually gate), D12 (execute ADR-0007's own repairs before adding more rules).

---

## Links to existing maps

- **Tickets:** parent map **#228** (`wayfinder:map` — whole-project health
  assessment); successor **#237** (assemble the consolidated health report);
  this ticket **#236**; sibling map **#230** (OANDA adapter + guards —
  `docs/health/research/230-oanda-adapter-guards.md` in this same directory).
- **Out-of-scope crypto-lane maps (closed):** #159 (price source authority),
  #160 (paper-lane cash/ledger reconcile) — per AGENTS.md, do not restart.
- **Docs reconcile precedent:** #121 (rewrite `docs/agents/next-session` +
  arch skill entry point).
- **Doc sources:** `docs/ARCHITECTURE.md` (§1 runtime table, §6 data layout,
  §7 fix list items 6/8/11), `docs/CONTEXT.md` (glossary; §FX arm at
  `:335-363`), `docs/agents/tui.md` (which client is the human's — relevant to
  the `tui/.mimosa` tracked-junk finding in D2), `.opencode/skills/next-session/SKILL.md`
  (the other, newer runtime map), `docs/agents/postmortem-2026-08-31.md`
  (the one-lane/one-gate rule and the "every cron/systemd job must name a
  recent artifact it produced or be removed" rule — directly applicable to
  D16/D18).
- **Governance sources:** `docs/adr/0007-reground-victory-path.md` (claims
  ledger, suspension-by-default, §7), `docs/adr/0008-multi-venue-prop-bridge.md`,
  `docs/adr/0009-expert-promotion-seam.md`, `data/wayfinder/toc/TOC.md` +
  `data/wayfinder/toc/ledger.json` (the ledger under assessment),
  `data/wayfinder/promotion-path-memo.md`, `data/wayfinder/deployability_status.json`.
- **FX evidence maps:** `docs/agents/research/fx-expert-loop-2026-09-06.md`
  (Q06-Q12, Q19-Q21 source), `docs/agents/research/fx-warden-2026-09-08.md`
  (Q14-Q18, Q22-Q24 source), `docs/agents/research/fx-alt-data-inventory-2026-09-05.md`,
  `docs/agents/research/self-improvement-loop-audit.md`, `docs/agents/research/eval-gate-health.md`.
- **Code touched by the hygiene findings:** `fxexpert/{data,train,loop,serve}.py`
  (npz producers), `fxexpert/trailing_ab.py:15` (hardcodes
  `data/fx_expert/oos_scores_gab1.npz`, an untracked 3.2 MB artifact — the Q21
  A/B evidence is not reproducible from a clone), `dashboard.py:894-901` +
  `dashboard.html:9` (PWA icons), `harness.py` (monolith), `strategies/fx_*.py`
  (untested live paths).

---

## Open questions

1. **Who owns the :5801 listener today?** `ss` shows it listening, no unit
   declares it, `opentrader-gpu-sync.service` is masked to `/dev/null`, and both
   `opentrader-harness.service:12` and `opentrader-shadow.service:12` point
   `--llama-host http://127.0.0.1:5801` at it. If it is a manual/stale process,
   the harness's LLM host is fragile; if it is a new service, the map is wrong.
   *(Needs `systemctl --user list-units` / `ps` outside the sandbox.)*
2. **Is `data/fx_expert/*.npz` regenerable or is it evidence?** If `panel.npz`
   is rebuildable from the data engine (`fxexpert/data.py`), the whole 439 M can
   be ignored+deleted; if the 7 `oos_scores_g*.npz` (incl. `gab1`, which
   `fxexpert/trailing_ab.py:15` hardcodes) are the *only* record of a Q21
   verdict, they are evidence and the ignore rule must be paired with a
   deliberate archive step.
3. **Which files under `data/` are truth vs cache vs junk?** D2/D3/D4 all
   reduce to one unanswered question; a single table (path → writer → truth
   status → tracked?) would let the hygiene backlog be executed mechanically.
   `docs/ARCHITECTURE.md:85-100` is a partial version of it.
4. **Does the daily-allocator paper lane still matter?** #216 offers three
   options; option (b) retire the unit+timer is consistent with ADR-0007 §7
   (suspension by default) and with the fact that `target_weights` exists in no
   module. Human-gated.
5. **Is the `toc` CLI meant to be on PATH for agents?** If yes, AGENTS.md's
   claims-governance rule is currently unexecutable as written; if no, the rule
   should name the exact invocation (or the programmatic write contract that
   D18/D19 show is silently dropping accounting).
6. **What is the correct per-phase allowance for the FX/`oanda` phase?**
   `TOC.md:9` advertises 25,000 with 0 spent; lifetime is 51,218 on a
   `_defaultAllowance` of 12,000. Without per-phase spend there is no way to
   answer "has the FX phase overspent?", which is the budget's purpose.
7. **Should checkpoints be tied to phases?** 14 questions accrued with no
   checkpoint, and two phases are open at once; the ledger has the fields but
   no invariant. Human decision on the invariant.
8. **Should `data/wayfinder/toc/.mimosa/**` and `tui/.mimosa/**` be removed
   from git?** `.gitignore:144` already declares them never-project-code; the
   only question is whether the hook history is wanted anywhere else first.
9. **Do the `break_*.py` / `smoke_multi_gpu.py` scripts still work?** 1400 of
   the 2263 test lines are in script-style files not referenced by any runner
   and not run by CI; nobody can currently say whether they pass. *(Not
   executed here — read-only ticket.)*
