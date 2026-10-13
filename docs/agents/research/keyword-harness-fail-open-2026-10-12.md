# Adoption memo — "Keyword Harnesses Fail Open" (arXiv:2610.02142)

**Ticket:** #320 · **Date:** 2026-10-12 · **Status:** adopted as a *verification-methodology* change; no trading claim.

**Provenance.** Draft emitted by the local worker (`qwen36-35b-agentic`) via
`~/ai/smart-router/dispatch-artifacts/memo-320-v1.json` (1310 completion tokens,
finish=stop). Every claim about *our* system below was then re-checked against the
source by a subscription agent; one draft claim was **wrong** and is corrected in §3.
Claim-level provenance is marked `[draft]` (worker, unverified) vs `[verified]`
(read from source this session).

---

## 1. The failure mode, in our terms `[verified]`

A checker that inspects **text** — commit subjects, artifact keywords, "tests passed"
strings — credits work that never executed. This is not hypothetical here; it is our
2026-10-12 incident. The ticket-loop verifier credited a commit for *completing* a
ticket because the commit message contained the ticket number, and reported
human-gated tickets (`#291/#294/#301/#302/#304`) as auto-closeable. It validated the
*claim* of completion, not the *fact*.

Our lane stays keyword-shaped wherever a decision rests on string matching against
prose: commit messages, artifact presence, "finish=stop", "tests passed" lines. The
memo you are reading is itself such an artifact, and §4 shows it failing open.

## 2. The diagnostic ladder (cheapest first) `[draft, structurally sound]`

| Rung | Check | Catches | Misses | Cost |
|---|---|---|---|---|
| 1 | Textual mention | missing reference | mention without work | ~0 |
| 2 | Declared completion marker | mention without marker | marker without work | low |
| 3 | Cited artifact exists & parses | absent/malformed artifact | valid-but-irrelevant artifact | medium |
| 4 | Artifact passes scope/behaviour check | artifact whose *content* violates the contract | stale artifact; **text that is wrong about the world** | medium |
| 5 | Claimed behaviour **executed** & output recorded | all of the above for executable claims | claims that are not executable (prose) | high |

The draft called rung 4 "content validation". Rung 4's blind spot is the important
one: a scope check validates *conformance*, not *truth*. A document can respect every
formatting and dependency rule and still assert false things about the world — or
about our own code.

## 3. Where our lane actually sits `[verified — draft was wrong]`

- `[draft]` claimed `v2/tools/dispatch/check-artifact.py` sits at **rung 3** and that
  rung 4 is missing.
- `[verified]` **This is false.** `check-artifact.py` already extracts artifact content
  (`extract_content`, L16–38), scans `use`/`::` paths against allowed deps (L64–86),
  enforces the output contract (blocks vs whole-file, L103–107), checks required
  symbols are present (L118), and enforces file-path scope (L121–128). That is rung 4
  for *code* artifacts.
- The genuine gap is **rung 5 for code** and **any rung above 1 for prose**:
  1. Nothing compiles or runs the worker's emitted code before it is treated as
     reviewed — conformance is checked, behaviour is not. The cheapest rung-5 for
     code is the existing `cargo test -p <crate>` run, recorded as the artifact
     (`19 test binaries ok` was exactly that, but it was run *after* review, not as
     the gate).
  2. For prose artifacts there is no rung above 1. "Artifact is well-formed and
     on-topic" is the whole check. Nothing compares a prose claim to a primary source.

## 4. The ladder failing open, demonstrated the same night `[verified]`

The worker's watch-list memo
(`~/ai/smart-router/dispatch-artifacts/memo-watch-list-review-v1.json`, 1041 tok)
passed every text check we have — well-formed, on-topic, contract-respecting,
plausible — and was **factually wrong about all four papers it reviewed**, including
two "Drop" verdicts built on misread methods and one "Adopt" verdict built on a
detection rule the paper does not contain. Details and corrections:
`watch-list-review-2026-10-12.md`. Nothing in rungs 1–4 could have caught it; only
rung 5 (compare the claim against the primary source) did.

## 5. Recommendation (under a day) `[verified feasibility]`

Two changes, in this order:

1. **Prose rung: cite-or-escalate.** Any artifact that makes a claim about an external
   source (paper, API, venue, another file) must either cite a verifiable identifier
   the reviewer can fetch, or be marked `UNVERIFIED — escalate`. Implement as a
   checklist item in the card contract
   (`v2/tools/dispatch/card-template.md`) and enforce in `check-artifact.py` as a
   *warning* first — a hard fail on prose would false-positive immediately.
2. **Code rung 5 as the gate.** For cards whose artifact is code, make the recorded
   `cargo test -p <crate>` output the merge precondition, not a post-review step.
   The command already exists; only its position in the pipeline changes.

Do **not** build a confidence-score heuristic. The draft's rung analysis was sound but
its "cheapest missing rung" was misidentified, which is itself a rung-1 failure.

## 6. Limits `[draft, agreed]`

- The ladder establishes nothing about environments or inputs other than the one
  recorded.
- A small model's **self-report** of its own execution is never evidence. Neither is a
  subscription agent's summary of it.
- Non-deterministic behaviour not captured in the artifact cannot be verified this way.
- Cite-or-escalate catches *unverifiable* claims only if the reviewer actually fetches
  the source. A reviewer who skips that step recreates rung 1 with extra steps.
