# Ticket Run — 2026-08-13

Brief for the delegated model. Targets GitHub issues **#118–#122** on `darylerivers/opentrader`.
Complete all five, attach one proof artifact per ticket, and report back for verification.

## Hard rules (binding — violation = ticket fails)

1. **Sandbox-first.** Make every code change in `/home/mrc/opentrader-sandbox` (a full copy of the repo) and prove it there. Only copy a change into `/home/mrc/opentrader` when its proof has passed. Never work directly in the live tree.
2. **No commits or pushes, ever.** Produce working trees + diffs. #122 is the sole exception: it asks you to stage a proposed set, then STOP (see below).
3. **Do not disturb live services.** The host runs systemd user units: `gpu-sync` (:5802), `opentrader-llama-gpu1` (:5802), `opentrader-harness` (harness.py, PID 3523381), `opentrader-dashboard` (:8097), `opentrader-mcp-server` (:8092). Do not kill, restart, or reconfigure any of them. Running a second harness instance for testing is forbidden unless it targets a separate state file.
4. **Ledger reconciliation after any state-file write.** If your work touches `paper_state.json` (it should not), you must diff cash/positions/fills before vs after and report.
5. **Proofs must be real command output.** Screenshots, `py_compile` results, grep hits, backtest excerpts, API replies. Heuristic claims are acceptable only if labeled "heuristic".
6. **Report format.** One section per ticket: what changed, where, the proof command run, its verbatim key output, and DoD check-off. Finish with a line stating whether each of the 5 tickets is DONE (proof attached) or BLOCKED (why).

## Environment

- Sandbox: `/home/mrc/opentrader-sandbox` (update it first: `rsync -a --delete /home/mrc/opentrader/ /home/mrc/opentrader-sandbox/ --exclude .git`).
- Live tree: `/home/mrc/opentrader` (68 files dirty at HEAD 0742f67 — do not add to the dirt; verify with `git status --short` at start and end).
- Python: `python3 -m py_compile <file>` is the minimum syntax gate for every edited file.
- `gh` CLI is authorized. Read-only use only.

---

## #118 — Deprecate `--reset-portfolio` + retire `run_harness.py` (ready-for-agent)

**Why:** `run_harness.py` is a redundant wrapper whose default previously wiped the portfolio on every auto-restart; the default was removed 2026-08-12 but the flag still exists in `harness.py` as a footgun. The truth: `opentrader-harness.service` runs `harness.py` directly. Nothing else should be run by hand.

**Current code (verified):**
- `harness.py:151` — `reset_portfolio: bool = False` param (wipe positions + SL/TP on startup)
- `harness.py:229` — `if reset_portfolio:` wipe branch
- `harness.py:456` — `if reset_portfolio:` (second use — find both)
- `harness.py:4467-4471` — argparse flag `--reset-portfolio` ("Wipe positions and SL/TP levels on startup")
- `harness.py:4582` — `reset_portfolio=args.reset_portfolio`
- `run_harness.py` — wrapper that injects `harness.py` via subprocess (its default injection already removed; file still exists)

**Steps (in sandbox):**
1. `grep -n "reset_portfolio" harness.py` and `grep -rn "run_harness" . --include="*.py" --include="*.md" --include="*.service"` to map every consumer.
2. Remove the `--reset-portfolio` argument and all its plumbing in `harness.py` (param default, both wipe branches, argparse entry, call site). Wipe logic may be moved nowhere — startup wipe must not exist as a flag anymore. Fresh-start state management should be documented in a comment pointing to `state/manager.py` (which already has safe tmp-file state handling).
3. Delete `run_harness.py` from the sandbox. Do not delete it in the live tree — leave that to the #122/human step.
4. Fix any references (docs, skills, systemd notes) that tell humans to use `run_harness.py` or `--reset-portfolio`.

**Proof:**
- `grep -rn "reset.portfolio\|run_harness" /home/mrc/opentrader-sandbox --include="*.py"` → no hits except historical comments you intentionally keep (quote them).
- `python3 -m py_compile harness.py` in sandbox → exit 0.
- Show the diff: `diff -u /home/mrc/opentrader/harness.py /home/mrc/opentrader-sandbox/harness.py | head -100`.

**DoD:** flag gone from argparse + all call sites; wrapper deleted in sandbox; py_compile clean; no live-service config references the wrapper.

---

## #119 — Fee-guard fails open on unknown exchanges (ready-for-agent)

**Why:** `risk/manager.py` silently skips the fee guard when the exchange isn't in `FEE_TABLES`. `FEE_TABLES.get(exchange, {})` returns `{}` → `fees` becomes `None` → guard passes everything through. The comment at `risk/manager.py:404` claims a "default" fallback that does not exist for unknown exchanges. A config typo ("papr") would disable fee protection without a log line.

**Current code (verified):**
- `risk/manager.py:395-415` — the fee resolution + 20% cap + min-notional guard
- `state/context.py` — `FEE_TABLES` (source of truth for fee schedules)

**Steps (in sandbox):**
1. Add a fail-closed branch: if `FEE_TABLES.get(getattr(self.config, "_exchange", "paper"))` returns nothing (unknown exchange name), log at WARNING with the exchange name and reject the trade with a clear reason (`"unknown exchange 'papr': no fee table — refusing"`). Decide with a test whether paper default should remain open (recommended: unknown names are hard-fail; the literal `"paper"` key stays the only open route).
2. Keep the existing route-aware resolution (crypto/stock/default) intact for known exchanges.
3. Add a unit-style check: instantiate a fake config with `_exchange="papr"` and assert the risk call returns `approved=False`.

**Proof:**
- `python3 -m py_compile risk/manager.py state/context.py` → exit 0.
- Show the new branch + the failing test output (e.g. a small `python3 -c` snippet exercising the fake config; quote output showing `approved=False` and the reason).
- `diff -u` of `risk/manager.py` between live tree and sandbox.

**DoD:** unknown exchange → logged + rejected; known exchanges unchanged (spot-check one crypto and one stock route still pass); py_compile clean.

---

## #120 — Remote branch cleanup (ready-for-agent)

**Why:** `prototype/doob-inequality` and stale research branches linger on origin. Cleanup must use **`git push origin --delete`** — never force-push, never delete local branches of the live tree without listing them for human review.

**Steps:**
1. `git ls-remote --heads origin` → list all remote branches.
2. Identify candidates: `prototype/doob-inequality` plus any branch whose tip commit is contained in the default branch's history (`git branch -r --merged origin/main` — check what the default branch actually is with `gh repo view --json defaultBranchRef`).
3. Present the list in your report as a table: branch | last commit | merged? | recommendation (delete/keep).
4. **Do not execute any deletion.** #122-style: propose and stop. The `gh` deletion commands belong in your report for human approval.

**Proof:** the `ls-remote` output and the merged-status table (paste both).

**DoD:** full inventory + per-branch recommendation; no branch deleted by you.

---

## #121 — Docs reconcile: next-session + arch skills (ready-for-agent)

**Why:** `.opencode/skills/next-session/SKILL.md` describes a dead stack (ports :5809/:8098, kraken, $100 cash, run_harness.py). `.opencode/skills/arch/SKILL.md:227` calls `run_harness.py` the "CLI entry point" — wrong after #118.

**Reality to write in (verified 2026-08-13):**
- Ports: harness runs directly via `opentrader-harness.service`; dashboard 8097; MCP server 8092; gpu-sync 5801; llama backend 5802.
- Cash/PV: 500.0 flat, 0 positions, 0 fills, cycle 2028 (`paper_state.json`).
- Entry point: `harness.py` (direct), stage 3 rule-primary, finnhub.
- Priority: rule floor is measuring −2.73%/trade negative every year (see #116) — that is the #1 open item.

**Steps (in sandbox):**
1. Rewrite `.opencode/skills/next-session/SKILL.md` to match reality (use `.opencode/skills/handoff/SKILL.md` — already rewritten — as the source of truth; keep the same file structure/format).
2. Fix `arch/SKILL.md:227` (and any other stale lines in arch) to say `harness.py` is the CLI entry point.
3. Do not touch the managed `AGENTS.md` header block (`rcheck setup` owns it).

**Proof:** `diff -u` for both files + `grep -n "8098\|5809\|kraken\|run_harness"` inside the two skill files after the edit → no hits.

**DoD:** both skills describe the live stack; no references to dead services/flags.

---

## #122 — Land the 2026-08-12 audit fixes as a commit/PR (ready-for-human)

**Why:** Ten verified fixes sit uncommitted in a 68-file dirty tree. They must land without dragging in the 62+ unrelated dirty files.

**The ten fixes (files + what changed, all proven 2026-08-12/13 — see `/tmp/opencode/flash0731_apply_report.md`):**
1. `docs/CONTEXT.md` — falsified performance claims struck
2. `.opencode/AGENTS.md` — override rewritten (no llama-server kill; systemd truth)
3. `dashboard.py` — slice bug `[:num_points]`/`[:50]` + logging on corrupt state
4. `run_harness.py` — `--reset-portfolio` default removed (superseded by #118, which deletes the file)
5. `state/manager.py` — `_unique_tmp()` PID+time_ns + cleanup
6. `data/vix_gate.py` — fail-closed prose + falsified +12.47% claim struck
7. `exchange/stock_finnhub.py` — dead line removed + 24h-TTL `_dead_symbols` delisting filter
8. `risk/manager.py` — SELL notional = qty×price + BUY defaulted 5% + 3 bare `except:pass`→logged + $0.35 documented
9. `gpu_sync.py` — default backends "5802" + WARNING exclusion alert
10. deleted local branch `doob-inequality` (note for remote: #120)

**Steps:**
1. `git -C /home/mrc/opentrader status --short` → confirm the ten files above are still dirty and nothing else got added by this run.
2. Propose a staging plan in your report: the exact `git add -- <paths>` list for the ten files (exclude `run_harness.py` if #118 will delete it — say which you chose and why).
3. **Do not run `git add` on the live tree, do not commit, do not push.** The report must end with the proposed commit message(s) and the staging list, for human approval.

**Proof:** `git -C /home/mrc/opentrader status --short | wc -l` and the full short-status list before/after your run (to prove you added no dirt).

**DoD:** proposed staging list + commit message(s); tree untouched by you; push decision left to human.

---

## Definition of done for the whole run

- One section per ticket as described, with verbatim proof output pasted.
- Sandbox used for all edits; live tree `git status` identical before vs after (except nothing added).
- No service was stopped/started/restarted; state ledger untouched (report explicitly: "ledger untouched" or the diff).
- Final line per ticket: DONE or BLOCKED + reason.
