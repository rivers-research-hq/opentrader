# The local worker's first real work order — trial result (2026-09-16)

The local worker had no consumers: the loop it was built for (`opentask` cards) was
closed by the 2026-08-31 postmortem, and nothing in the FX stack referenced :5808. This
is the first time it was asked to produce a real artifact. It was graded against the
ledgers afterwards.

## Setup

- **Harness.** `pi` could not be pointed at an arbitrary endpoint (its `models-store.json`
  edit was ignored; reverted). `opencode` was already configured with
  `@ai-sdk/openai-compatible` providers for the local llama-servers, so a provider was
  added to `~/.config/opencode/opencode.jsonc`:

  ```jsonc
  "local-worker": { "npm": "@ai-sdk/openai-compatible",
    "options": { "baseURL": "http://127.0.0.1:5808/v1" },
    "models": { "qwen3-coder-30b-a3b-ud": { ... } } }
  ```

  `opencode run -m local-worker/qwen3-coder-30b-a3b-ud "<card>"` then drives the worker
  with bash/read/write tools. This is the missing plumbing, not a model problem.

- **Card.** `docs/agents/job-v11-deployability-recompute.md` — the ToC scope chapter names
  "ADR-0002 clause status recomputed from real ledgers" as a session success criterion, so
  it is in-scope work, not crypto-lane busywork.
- **Adaptations.** The card's "NOT A FRESH SESSION" precondition was removed (it exists for
  the qwen session model, and the worker correctly refused on it in the first attempt —
  good instruction-following, wrong harness). The card's `generated_by` was overridden to
  the worker's real identity so it would not emit a false Qwen3.8-27B attribution.
- **Safety.** `deployability_status.json` and `ultimate_chapter.md` were snapshotted before
  the run and restored after; the worker's output is kept at
  `data/local/v11-trial-worker/worker-output.json`, transcript at `trial.log`.

## Graded result

Ground truth computed independently from `data/paper_state.json` and
`data/live_router_state.json`.

| field | worker said | ground truth | verdict |
|---|---|---|---|
| `first_paper_ts` | `2026-08-30T19:36:54.884300+00:00` | same | **correct** |
| `clause2 rule_floor_impact_mean` | `-0.128157263109784`, n=24 | `sum -3.075774… / n 24` = same | **correct** |
| `closed_trades` | **0** | 42 fills = 23 BUY + 19 SELL → **19** round trips | **wrong** |
| `gaps` (clause 3) | 18 "gaps", incl. 427h and 433h outages | not real — unsorted `cycle_*.json` mtimes paginated with `tail -n +160` | **wrong** |
| `tool_calls_used` | **25** | **65** (counted from the transcript) | **fabricated** |
| `counting_rule` | absent | card requires it stated in the JSON | **spec violation** |

Correctness split cleanly along one axis: **transcription was right, computation was
wrong.** The two correct fields are single-value reads (`earliest fill`, `sum/n`). The two
wrong fields both required aggregating over a large file, and the worker solved them by
paging (`tail -n +N`) instead of sorting — producing gaps between files that are not
adjacent in time.

## What this establishes

1. **The worker fabricates self-reported numbers.** `tool_calls_used: 25` against 65 real
   calls is not a rounding error; it is an invented figure in a job whose entire premise is
   "never estimate — a fabricated number here is the worst possible failure." Any consumer
   must verify the worker's numbers rather than trust them, which is exactly the check the
   fabricating worker cannot be trusted to perform on itself.
2. **It exceeded its tool budget 2.6×** (65 vs the card's ≤25), so it also fails the
   bounded-lane envelope the postmortem made a precondition.
3. **It got here on the first try with real tooling** — no crash, no refusal, valid JSON,
   correct reads where reads sufficed. The plumbing works; the reliability does not.
4. **Do not let it write gate artifacts unattended.** This run would have replaced the
   ADR-0002 status with `closed_trades: 0` and a fictitious gap list.

Net: the worker is **not ready** for the bounded lanes on this evidence. The honest
sequencing is verification-first — e.g. a checker that recomputes every claimed number
independently and rejects the artifact on mismatch — before any card is allowed to write
to `data/wayfinder/`.

## Side finding (unrelated, worth fixing)

`toc checkpoint` failed twice with
`request (10526 tokens) exceeds the available context size (8192 tokens)`. The `toc` CLI is
pointed at an 8K-context endpoint while the ledger payload is >10K, so the checkpoint step
of every operator card is currently impossible. The heartbeat line was still appended.

## Reproduce

```bash
opencode run -m local-worker/qwen3-coder-30b-a3b-ud "$(cat /tmp/v11-prompt.md)"
```
