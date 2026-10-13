# arXiv probe triage — 2026-10-12

Worker triage of the four open `ready-for-agent` arXiv probe tickets. Verdicts are the
local worker's (`qwen36-35b-agentic`); each is backed by an artifact in
`~/ai/smart-router/dispatch-artifacts/arxiv-<N>-v1.json`.

| Ticket | Paper | Verdict | Disposition |
|---|---|---|---|
| #381 | arXiv:2610.12360 — epistemic humility under knowledge conflict | `skip` | closed — no bearing on FX method, arena training, or the agent-integrity stack |
| #378 | arXiv:2610.12375 — OnTrack trajectory monitoring | `deep` | memo → `ontrack-agent-trajectory-monitoring-2026-10-12.md` |
| #365 | arXiv:2610.12445 — sabotage/deception probes | `deep` | memo → `sabotage-probe-detection-2026-10-12.md` |
| #321 | arXiv:2610.02140 — finetuning with sampling | `deep` | memo → `sft-sampling-agent-training-2026-10-12.md` |

**Process note:** these tickets were auto-filed with `Triage source: heuristic-key-unset` — the
triage heuristic never ran, so every one carried the same templated hypothesis proposing an
FX-dataset backtest of the paper's method. That framing is a category error for LLM-safety
papers and was corrected in the memo cards; the memos target the agent-integrity stack instead.
