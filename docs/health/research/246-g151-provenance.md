# g151 promotion provenance — how `gate_g151.json` became PASS and `loop_state.json["best"]` became g151 (wayfinder #246)

Read-only investigation. No training, no loop run, no gate re-run, no service touched. Every claim
below is labelled **VERIFIED** (I read the file/line, commit, mtime or append-only log row myself),
**READ-FROM-DOCS** (a repo document states it; I did not re-derive it) or **CLAIMED** (asserted by an
agent/human record, not independently reproducible from artifacts). Nothing here is recomputed — in
particular I did **not** re-run `fxexpert.gate.evaluate`, because that call rewrites `gate_g*.json`.

All times are shown in UTC; the CDT equivalent (UTC−5) is given where the ticket used it.
`2026-09-07T02:12:47Z` = `2026-09-06 21:12:47 CDT`.

## Scope

Provenance chain for the only fxexpert gate PASS (g151): who wrote `data/fx_expert/gate_g151.json`
as `"verdict":"PASS"`, who set `data/fx_expert/loop_state.json["best"] = {tag:"151", ...}`, and why
neither appears in `data/fx_expert/history.jsonl`. Adjudicates the three tickets hypotheses:

- **(a)** scripted — some script/module wrote the gate file and/or `loop_state.json["best"]` directly;
- **(b)** hand-edited — a human manually edited the JSON;
- **(c)** a loop run whose history append was lost (process died between `_save_state` and the history write).

Artifacts examined (all read-only): `fxexpert/{gate,loop,serve,train}.py`, `data/fx_expert/`
(`history.jsonl`, `loop_state.json`, `gate_g{137,138,151}.json`, `train_g*`, `preds_g*.npz` mtimes),
`data/epoch_registry.json` + `data/epoch_registry_log.jsonl`, `data/fx_expert/claims*.json`,
`scripts/bug-bounty/sandbox/`, crontab, `data/logs/`, git history, and — decisively — the agent-CLI
telemetry log `/home/mrc/.zcode/cli/log/zcode-2026-09-06.jsonl`, which retains tool-call names and
timestamps for the session that did the work.

## Verified findings

### F1 — The only writers, from the code (no ad-hoc script exists on disk)

- `gate_g{tag}.json` has exactly **one** writer in the whole tree: `gate.py:267`
  (`(out_dir / f"gate_g{tag}.json").write_text(json.dumps(res, indent=1))`). Repo-wide grep for
  `gate_g` finds no other producer. **VERIFIED**
- `fxexpert/gate.py:279-281` makes that callable as a one-liner CLI: `python3 -m fxexpert.gate <tag>`. **VERIFIED**
- The only in-tree caller of `fxgate.evaluate` is `loop.py:157`, and the loop always trains a **new**
  generation first (`loop.py:155` → `train.run_generation`, then `157` → `evaluate(tag)`) where
  `tag = f"{state['generation']:02d}"` (`loop.py:130-131`). **VERIFIED**
- `loop_state.json` writers: `loop.py:73-76 _save_state` (atomic `tmp` + `Path.replace`, `indent=1`)
  is the only writer of that path in the tree; `serve.py:27-30` only reads it. `loop.py:177`
  is the only assignment to `state["best"]`. **VERIFIED**
- Crontab contains **no** fxexpert-loop entry (only the three `strategies.fx_expert_lane` lanes,
  `fx_runner`/`fx_shadow`/`fx_challenger`/`fx_watchdog`/etc.). Crontab comment:
  `# fxexpert rank-book lanes (3 experts, demo tournament per human directive 2026-09-06; amended gate)`.
  So no scheduled job could have produced these writes. **VERIFIED**

### F2 — The anomaly, restated with exact times

| Artifact | Time (UTC) | Time (CDT) | Source |
|---|---|---|---|
| `train_g151.json` mtime | 2026-09-07T01:45:24.34Z | 20:45:24 | `ls --time-style=full-iso` **VERIFIED** |
| `preds_g151.npz` mtime | 2026-09-07T01:45:24.34Z | 20:45:24 | same **VERIFIED** |
| `history.jsonl:152` row for g151 | ts `2026-09-07T01:45:25.545Z` | 20:45:25 | row content **VERIFIED** |
| `gate_g151.json` mtime (rewrite) | 2026-09-07T02:12:49.58Z | 21:12:49 | `ls` **VERIFIED** |
| `gate_g137.json` mtime (rewrite) | 2026-09-07T02:12:47.24Z | 21:12:47 | `ls` **VERIFIED** |
| `gate_g138.json` mtime (rewrite) | 2026-09-07T02:12:48.42Z | 21:12:48 | `ls` **VERIFIED** |
| `gate.py` mtime | 2026-09-07T02:12:23.79Z | 21:12:23 | `ls` **VERIFIED** |
| `serve.py` mtime | 2026-09-07T02:14:17.02Z | 21:14:17 | `ls` **VERIFIED** |
| `epoch_registry_log.jsonl` register `fx-expert-g151` | ts `2026-09-07T02:13:15.733932Z` | 21:13:15 | append-only log row **VERIFIED** |
| `epoch_registry_log.jsonl` register `fx-expert-g137`/`g138` | ts `2026-09-07T02:27:47.093682Z` / `.094842Z` | 21:27:47 | log rows **VERIFIED** |
| `epoch_registry_log.jsonl` annotate notes (all three) | ts `2026-09-07T02:34:00.060-.062Z` | 21:34:00 | log rows **VERIFIED** |
| `history.jsonl` promotion row for g151 | — | — | **does not exist** (163 rows, 163 unique tags, 0 rows with `promoted`+`gate!="PASS"`, only g13/g15 have `registered:true`) **VERIFIED** |
| `loop_state.json["best"]` | `{"tag":"151","pf":1.0846,"ic":0.03086,"params":340513}` | — | file content **VERIFIED**; `experts_registered` = `["fx-expert-g13","fx-expert-g15"]` — **g151 absent** **VERIFIED** |

The 27-minute gap in the ticket is confirmed: `02:12:49Z − 01:45:25Z = 27m24s`. **VERIFIED**

### F3 — Decisive: an agent CLI session performed the writes, via `Edit`/`Bash` tool calls

`/home/mrc/.zcode/cli/log/zcode-2026-09-06.jsonl` is a JSONL telemetry log (one `sessionId` for all
of it: `sess_5b566ad6-48da-4089-9883-b8c3f5be6285`, model `~z-ai/glm-flash-latest`) whose
`tool.call.started`/`tool.call.completed` events carry **tool name + timestamp + duration** (they do
**not** carry arguments — grep for `g151`/`gate_g151` in that log returns 0 hits, consistent with
name-only logging). The events line up with every artifact mtime to within milliseconds:

| Tool-call window (from the log) | Tool | Duration | Artifact written inside that window | Match |
|---|---|---|---|---|
| 02:12:23.731 → 02:12:23.791Z | `Edit` | 59 ms | `gate.py` mtime 02:12:23.786Z | **VERIFIED** (5 ms) |
| 02:12:45.578 → 02:12:49.638Z | `Bash` | 4060 ms | `gate_g137.json` 02:12:47.238Z, `gate_g138.json` 02:12:48.419Z, `gate_g151.json` 02:12:49.583Z — **all three inside one Bash call** | **VERIFIED** |
| 02:13:15.162 → 02:13:16.343Z | `Bash` | 1183 ms | registry `register fx-expert-g151` ts 02:13:15.733932Z | **VERIFIED** |
| 02:14:16.974 → 02:14:17.023Z | `Edit` | 50 ms | `serve.py` mtime 02:14:17.017Z | **VERIFIED** (6 ms) |
| 02:27:46.410 → 02:27:47.145Z | `Bash` | 735 ms | registry `register fx-expert-g137`/`g138` ts 02:27:47.093/.094Z | **VERIFIED** |
| 02:33:59.498 → 02:34:00.114Z | `Bash` | 616 ms | registry `annotate notes` ×3 ts 02:34:00.060-.062Z | **VERIFIED** |

Interval containment is **VERIFIED**; that the command text inside each `Bash` call was
`python3 -m fxexpert.gate <tag>` / a promotion snippet is **INFERRED** (the log retains no arguments).
The agent's `Edit` calls are verified as such, which rules out a human JSON hand-edit for those two
files.

The **same session drove the loop run**: turn 15 of `sess_5b566ad6` ran 2026-09-07T00:35:24Z →
01:55:41Z with 36 tool calls including `Bash` calls of 595 030 ms each covering the history rows
`01:07:09Z` (g137) → `01:54:08Z` (g156). **VERIFIED**. That is why no loop log for 2026-09-06 exists
on disk: `data/logs/` contains only `fxexpert_loop_3gen_20260910.log` (mtime 2026-09-09 23:41:22
CDT) — the 09-06 loop's stdout went to the agent, not to a file. **VERIFIED**

### F4 — The rewritten gate files are a genuine re-evaluation under edited code, not a flipped verdict

- Only `gate_g137.json`, `gate_g138.json`, `gate_g151.json` contain the `gate_amendment` key
  (checked `gate_g136`, `g150`, `g152`: absent). All three are in the F2 burst. **VERIFIED**
- `gate.py:37-45` carries the documented bar amendment: `AMENDED 2026-09-06 (human decision): the
  buy-and-hold criterion applies only to DIRECTIONAL books… Amendment made post hoc with results in
  view`, plus `GATE["net_exposure_max"] = 0.2`; `gate.py:239-253` implements it (measures
  `net_exposure_ratio`, and pops `buy_hold` from the gating set for dollar-neutral books);
  `gate.py:210` NaN-guards the position vector. **VERIFIED** (read at those lines)
- Each rewritten file's `n_pairdays` is **exactly 6050 lower** than the loop's own history row for
  the same tag — 213269→207219 (g137), 213267→207217 (g138), 213265→207215 (g151) — while `pf`,
  `sharpe`, `maxdd` are identical to history. A hand-edited verdict would not move a derived count
  uniformly by 6050 across three files. **VERIFIED** (values read from both sources)
- The gate flip is fully explained by the exemption, not by new numbers: g151 `model.pf 1.0846`
  vs `buy_hold.pf 1.1427` → pre-amendment reason `does not beat baselines: {'buy_hold': 1.1427}`
  (`history.jsonl:152`) → post-amendment `base_pfs` no longer contains `buy_hold`, so
  `reasons == []` → PASS. `gate_g151.json:50-53` records `gate_amendment: {beat_buy_hold:false,
  net_exposure_max:0.2}` and `model.dollar_neutral: true` (`net_exposure_ratio 0.0356`). **VERIFIED**
- No retraining occurred: `train_g151.json` and `preds_g151.npz` still carry the 20:45:24 CDT
  mtimes, and `history.jsonl` has exactly one row per tag (163 rows / 163 unique tags / 163 =
  `loop_state.json["generation"]`). So the PASS is a re-score of the *same* OOS predictions. **VERIFIED**
- The committed `gate.py` content **is** the amended version: `fxexpert/` is clean in `git status`,
  and `git log -1 -- fxexpert/gate.py` = `ffe3978` ("New Dashboard and Warden Implementation",
  2026-09-10 08:18:01 −0500), which added `fxexpert/gate.py` as a **new file** (`new file mode
  100644`) and whose diff contains the amendment lines. **VERIFIED**
- `git log -1 -- data/fx_expert/loop_state.json` = `ffe3978`, `1 file changed, 134 insertions(+)` —
  a pure addition, i.e. **no pre-2026-09-10 git history exists for `loop_state.json`** (or for any
  `data/fx_expert/*` artifact). **VERIFIED** (this confirms the ticket's premise; it also means the
  2026-09-06 21:12 content of `loop_state.json` is unrecoverable from git).

### F5 — The out-of-band path is visible in the registry strings

- `loop._register_expert` (`loop.py:100-111`) hard-codes `family="fx-transformer"`,
  `universe="16-pair accrual store D1"`, `source=f"fxexpert loop generation {tag} (OOS PF {pf}, IC {ic})"`,
  `notes="fxexpert recursive loop v0.1; numeric branch (…)"`. The loop-registered entries
  `fx-expert-g13` / `fx-expert-g15` match those strings **exactly**. **VERIFIED**
- `fx-expert-g151`'s registry entry instead reads `family:"fx-transformer-rank"`,
  `universe:"58-pair accrual store D1, 10d horizon"`,
  `source:"fxexpert loop g151: OOS PF 1.0846, Sharpe 0.281, IC 0.0309 (3/3 folds), weekly
  rank-rebalanced dollar-neutral book"`, `promotion_bar:"Amended gate 2026-09-06 (human): …"`, and its
  registration-time `notes` (recoverable from the log's `annotate` "from" field) were
  `"Gate amendment made post hoc by the human with results in view (Q10); multiple-testing load
  across 157 generations acknowledged. Shadow-only."` — **different strings from every loop-generated
  entry**. Therefore g151 was **not** registered by `loop._register_expert`. **VERIFIED**
- `registered_by:"agent"` in both eras. **VERIFIED**

### F6 — Nothing else changed in the window

`find` over the repo (excluding `.git`, `.venv`, `checkpoints/`) for files with mtime in
`2026-09-06 21:10–21:20 CDT` returns exactly five paths: `fxexpert/serve.py`, `fxexpert/gate.py`,
`data/fx_expert/gate_g137.json`, `gate_g138.json`, `gate_g151.json`. **VERIFIED**. So no driver script
was left on disk; the driver was an inline `Bash` command (F3), whose text is not retained anywhere I
can read.

### F7 — The loop code path cannot set `best` without a history row

`loop.py:167-201` (current committed version): the history append (`with HISTORY.open("a")`, lines
189-199, carrying `gate`, `gate_reasons`, `promoted`) executes **before** `_save_state(state)`
(line 201); `state["best"]` is only assigned inside `if better:` (line 176-178), where
`better = passed and (state["best"] is None or m["pf"] > state["best"]["pf"])` (line 170) and
`passed = res["gate"]["verdict"] == "PASS"` (line 169). The history append is **not** inside the
`try/except` that guards train/gate (lines 154-165), so a failure there aborts the run before
`_save_state`. The same `if better:` branch calls `_register_expert` and appends
`state["experts_registered"]` (lines 179-182) — which is exactly why g13/g15 are in that list.
**VERIFIED** against the committed source.
*Caveat:* `fxexpert/loop.py` was first committed in `ffe3978` (2026-09-10), so the **2026-09-06 text**
of this ordering is not recoverable; this claim is verified against current `HEAD` only.

### F8 — Corroborating context

- **READ-FROM-DOCS** `docs/agents/research/fx-expert-loop-2026-09-06.md` §"Amendment and first
  registration (2026-09-06, human decision: 'Amend')" (lines 238-259): the human amended the gate;
  under the amended bar "g137/g138/g151 all PASS"; "**fx-expert-g151** … is PROMOTED and registered
  as an accruing challenger"; a NaN-guard was added after NaN outputs poisoned the neutrality
  measure; "fxexpert.serve now emits daily rank-weighted shadow signals" (which is the 02:14:17Z
  `serve.py` Edit).
- **READ-FROM-DOCS** `data/wayfinder/toc/TOC.md:39-40` (Q11/Q12): g151 registered accruing as the
  first gate-PASSing trained FX expert under the amended bar; the three-expert demo tournament was a
  human signoff; `docs/health/research/232-fxexpert-alpha-loop.md` G2 already recorded "out-of-band
  gate re-run 27 min after the loop logged FAIL" with the same mtimes I re-measured.
- **VERIFIED** `data/fx_expert/loop_state.json` (mtime 2026-09-09 23:41:22 CDT) prints `best =
  {tag 151, pf 1.0846, ic 0.03086, params 340513}` and `data/logs/fxexpert_loop_3gen_20260910.log`
  shows generations 160-162 all `warm=151` and the same `best` after the run — i.e. later loop runs
  **loaded and re-preserved** the out-of-band `best`, overwriting any mtime evidence of the original
  write. **VERIFIED**
- **VERIFIED** `data/fx_expert/loop_state.json` values match `history.jsonl:152` exactly
  (pf 1.0846, ic 0.03086, params 340513) and `gate_g151.json:4` (pf 1.0846) — so the promoted record
  was built from the loop's own g151 observation, not from a different generation.

## Provenance conclusion

**(a) — scripted: an agent CLI session performed an out-of-band re-evaluation and promotion.**
Not (b); not (c).

Complete chain, reconstructed from artifact mtimes + the agent-CLI tool-call log (F3):

1. **02:09Z (21:09 CDT)** — turn 16 of agent session `sess_5b566ad6-48da-4089-9883-b8c3f5be6285`
   begins (TodoWrite) after turn 15 ran the g137-g156 loop campaign (00:35-01:55Z). **VERIFIED**
2. **02:12:23.786Z** — that session's `Edit` writes `fxexpert/gate.py`: adds
   `GATE["net_exposure_max"]=0.2`, the `gate_amendment` block, the buy-hold exemption for
   dollar-neutral books, and the NaN guard. **VERIFIED**
3. **02:12:45.578-49.638Z** — a single `Bash` call re-runs the gate for **g137, g138, g151**,
   writing the three gate files 1.19 s apart (only writer: `gate.py:267`). PASS appears for all
   three; `n_pairdays` drops uniformly by 6050 (the NaN guard), `pf` unchanged. **VERIFIED**
   (that a *re-evaluation* happened, not a verdict edit); **INFERRED** (that the command was the
   `gate.py` CLI/driver — no argument log exists).
4. **02:13:15.733Z** — a second `Bash` call registers `fx-expert-g151` accruing in epoch 1, with
   out-of-band strings (`fx-transformer-rank`, "Amended gate 2026-09-06 (human)…",
   "…shadow-only."), `registered_by:"agent"`. Not `loop._register_expert`. **VERIFIED**
5. **Between 02:12:49Z and 02:13:16Z** — `loop_state.json["best"]` is set to the loop-shaped g151
   record `{tag, pf, ic, params}` (values lifted from the loop's own g151 observation);
   `experts_registered` is **not** updated. Both observable `Bash` windows that could contain that
   write are steps 3 and 4. **VERIFIED** (that `best` was set with no history row and no
   `experts_registered` entry); **INFERRED** (which of the two Bash calls wrote it — its mtime is
   destroyed by later loop runs, F8).
6. **02:14:17.017Z** — `Edit` patches `serve.py` (rank-book weight emission, `serve.py:56-69`), then
   02:21-02:32Z long `Bash` calls wire/exercise `strategies.fx_expert_lane.py`. **VERIFIED**
7. **02:27:47Z / 02:34:00Z** — g137/g138 registered and all three notes annotated ("LIVE LANES
   WIRED …"), matching the crontab lanes. **VERIFIED**

Why not the other two hypotheses:

- **(b) hand-edited — rejected.** The gate flips are code-produced: `gate_amendment` key present only
  in these three files, `n_pairdays` shifted by exactly 6050, key order identical to
  `evaluate()`'s construction order, and the same window contains verified `Edit`/`Bash` tool calls
  from an agent session (F3/F4). A human hand-editing JSON would have had to fabricate the amendment
  block and a uniform derived-count shift. For `loop_state.json["best"]`, a manual edit is not
  excluded *absolutely* (its writer is unrecorded), but every surrounding write in the same 4-minute
  window is a verified agent tool call — so a human text-editor step is not the parsimonious reading.
- **(c) loop run with a lost history append — rejected.** (i) In the committed loop the history
  append precedes `_save_state` and lies outside the guarded `try` (`loop.py:154-201`, F7), so a
  saved `best` with no history row is structurally impossible in that code; (ii) under the
  pre-amendment bar the g151 run logged `FAIL` → `passed=False` → `better=False` → `best` untouched
  (`loop.py:169-178`), and the bar was only amended **after** that run (02:12:23Z vs the 01:45:25Z
  row); (iii) no second g151 training exists (`train_g151.json`/`preds_g151.npz` mtimes unchanged,
  163 rows / 163 unique tags, `generation:163`); (iv) the loop's own `if better:` branch would have
  appended `fx-expert-g151` to `experts_registered` (as it did for g13/g15) — it is absent;
  (v) `history.jsonl` is consistent throughout: zero rows with `promoted` but not `PASS`.
  The ordering argument (i) is verified only against current `HEAD` (caveat in F7); (ii)-(v) rest on
  artifacts that cannot be rewritten retroactively and hold independently.

**Net statement:** the gate files were re-scored by `fxexpert.gate.evaluate` under a post-hoc,
human-authorised bar amendment, and the promotion/registration were done by ad-hoc agent `Bash`
commands — a deliberate, documented out-of-band act (the research doc calls it the "Amendment and
first registration", the registry bar string names the human decision). The **documentation is
honest about the amendment**; what is missing is that the **machine records never captured the
promotion**: `history.jsonl` (append-only, the loop's promotion ledger) has no g151 row, and
`loop_state.json` carries no authorship. Any consumer that treats `history.jsonl` as the promotion
record — as `#232` G2 and `docs/health/2026-09-10.md:167` do — will see a promoted expert with no
promotion evidence. That is the real defect: not forgery, but a **provenance gap between the human
decision and the loop's append-only record**, plus a post-hoc bar amendment (the exemption at
`net/gross ≤ 0.2` is ~6× looser than g151's measured 0.0356) whose consequence is un-priced.

## Open questions

1. **Exact `loop_state.json["best"]` write instant and command text** — unrecoverable: `zcode` logs
   tool names/timestamps only (0 hits for `g151`), the two candidate `Bash` windows are 02:12:45-49Z
   and 02:13:15-16Z, and the file's own mtime was overwritten by the loop runs of 2026-09-09
   (23:41:22 CDT). Same for the `Bash` arguments behind the three gate writes — the command was
   almost certainly the `gate.py` CLI (`gate.py:279-281`) or an imported `evaluate()` loop, but that
   is inference, not evidence.
2. **The 2026-09-06 source text of `fxexpert/{gate,loop}.py` is not in git** (first commit `ffe3978`,
   2026-09-10). The "history before state" ordering argument (F7) therefore cannot be checked against
   the code that was actually running at 01:45Z; a copy might still exist in an agent snapshot — I
   found no `2026-09-06` snapshot in `~/.local/share/opencode/snapshot` (only `global` and one
   2026-08-20 dir) and no other `fxexpert/` tree anywhere under `/home/mrc` (searched, bounded).
3. **Where is the human's "Amend" decision recorded verbatim?** The gate comment, the research doc,
   the registry `promotion_bar` and TOC Q10/Q11 all assert it; no chat/issue artifact with the exact
   instruction was found in the repo. The decision is therefore **CLAIMED** by the implementing
   session and **READ-FROM-DOCS** elsewhere, not independently verifiable.
4. **Reproducibility of the three amended PASSes is untested.** Re-running
   `fxexpert.gate.evaluate` would rewrite `gate_g{137,138,151}.json` and is outside this read-only
   ticket. Note `#232` D1 (train-fold leakage into normalization, `train.py:170-171`) applies to all
   163 generations including these three, so a clean re-baseline is a prerequisite for treating any
   PASS as evidence.
5. **Process gap, not just an instance.** Nothing in the tree prevents an out-of-band promotion:
   `history.jsonl` is written only by `loop.main`, and `loop_state.json` accepts any `best` a caller
   sets. Candidate remedies for a follow-up ticket (not implemented here): have the gate record
   `amended_bar` + `evaluated_at` + `driver` inside `gate_g*.json` (it already records
   `gate_amendment` but no timestamp), and require any `best` write to also append a `history.jsonl`
   row with `promoted_by:"out-of-band"`.
