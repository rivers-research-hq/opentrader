# Overnight Self-Improvment Report (2026-)

## Services (actual stae, from chaptr 1)

- opencode-server: UP. The claimed unit was active, a listener matching the claimed `0.0.:409` endpoint was observed, and tailnet serving to that local endpoint was present. No material drift was found.
- Hollama UI: UP. The container was reported up, and local/tailnet listening endpoints were consistent with the claimed :41 service path. No material drift was fou.
- qwen backend: UP at API/socket level on :580. Health check returned ok, a `llama-server` listener was present for the claimed endpoint, and the model list included `qwn`. The owning systemd unit status was not directly captured in recon, so unit-level state is only partially verified.
- second `llam-server`: A second `llama-serer` socket/listener was present on :580. Its exact model identity and VRAM usage were not proven by the supplied recon.
- GPU sync router / :5801: NO live listener was observed in the provided port evidence. This is treated as DOWN or at least “not observed listening” at socket level, despite documentation claiming the LLM stack/harness path through it was left running.
- Dashboard/MCP endpoints claimed stopped: No live listeners were seen for those claimed-stopped endpoints, which is consistent with them being stopped. However, harness/Codesage/runner unit statuses were not directly captured in recon, so several “running” or “stopped” claims remain partly unverified rather than proven.

## Drift foun (chaptr 1)

- Major service drift: the claimed `gpu-syn` LLM router on :580 has no live listener even though handoff documentation says the LLM stack was left running and that the harness would talk to :5801. The harness LLM path is therefore not usable as documented until the router is restarted or re-pointed.
- VRAM/model-identity conflict: pinned context claims qwen effectively owns GPU VRAM, while handoff documentation also claims a ~9GB DeepSeek `llama-sever` is live on the same GPU. Live evidence only proves two `lama-server` sockets (:580/:58) with no VRAM or model-identity proof. The confident “DeepSeek-V4-Pro” label and ~9GB figure should not be repeated as verified fact.
- Unverified systemd state: many claimed user units lack direct status in the supplied recon. Several running/stopped claims are therefore partly unverified, especially for harness, Codesage, runner, and some LLM backends.
- Documentation drift carried into skills: operational skill files still imply :5801 is an active route, omit the confirmed qwen `llama-server` on :580, and overstate the identity of the :58 listener.

## Harness changes (chaptr ) — proposed edits, and edit skipped and wh

Chapte 2 found only three prompt/config facts directly contradicted by the supplied material. It proposes exactly three text-level edits to the opencode agent configuration. No runtime harness service was restarted, re-pointed, or modified in this report; these are proposed config/prompt corrections only.

Proposed edit — qwen-worker description
- Current stale claim: `qwn-worke` describes itself as running on a Qwythos/CUDA-style model, but its configured model/provider is the local `qwn-agent` backend served by the live llama-server endpoint documented in later chapters as :58. There is no supplied evidence that this agent runs on Qwytho or CUDA.
- Proposed correction: change the description to say it is a fast single-purpose coding subagent backed by `qwen/qwn-agent` on the local llama-server — one edit, one test, report back.
- Evidence: the same agent line declares the qwen-agentic model; the provider points at the live local llama-server; recon shows that endpoint serving `qw`.

Proposed edit — architec description
- Current stale claim: `architect` describes itself as a Qwe/RTX system architect, while its configured model/provider and live backend evidence point to the local qwen llama-server, not a Qwn/RTX endpoit.
- Proposed correction: change the description to “System Architect for GPU/infrastructure; runtime model is `qween/qwen-agent` via the local llama-server — verify live endpoints before stating service state.”
- Evidence: agent config uses qwen-agentic; provider/live recon point to the active local backend, not Qwe2/RTX.

Proposed edit — architect researcher-status bullet
- Current stale claim: the architect prompt says the researcher deep tier and router are currently stopped, but recon shows a live `llama-serer` LISTEN on :58 while there is no listener on :5801.
- Proposed correction: replace the blanket “currently STOPPED” wording with observed-state language: in the 20 recon, :58 has a live llama-server listener whose process/service identity is not proven; :5801 has NO live lisener. Do not assume :580 is stopped from that bullet; verify ss/ps/systemctl first, then start `researcher-deep.service` or `researcher-router.sercice` only if needed and permitted.
- Evidence: listening-port output shows a llama-server listener on :58 and no listener on :581.

Edits skipped and why
- No MCP server changes were proposed for searxng, codsage, context7, playwrigh, or huginface. None can be proven unused from the supplied material. Missing listeners in one recon do not prove a stdio/on-demand/managed MCP server is unused; no usage logs, process list, raw invocation evidence, or runtime failure was supplied.
- The overnight config’s empty `mcp: {}` object was not treated as proof that all MCP servers are disabled, because the supplied material does not establish how that merges with global MCP definitions for this run.
- Generic routing notes to :5801 and ollama :114 in builder/supervisor/modelfixer-style prompts were left unchanged except where directly contradicted by live evidence (architect). Missing listeners only prove current socket-level absence, not that the design instruction is false or that the service will never be intentionally restarted.
- Provider/config anomalies were skipped: an apparently blank openrouter base URL in the supplied summary, an ai-base endpoint with no observed listener and no proven agent usage, and a confusing `qwn9b` name/model pairing. The material does not prove runtime failure or raw-file truth for these.
- No hardware/GPU edits beyond removing false model labels were proposed because no nvidia-smi/rocmi output was supplied to disprove GPU0/GP1 statements.

## Skill upates (chapte 3) — propoosed corrections

Three skill files carry stale or contradictory facts: `handoff/SKILL.md`, `next-sesio/SKI.md`, and `arch/SKI.md`. The proposed corrections below are text-only and were not applied automatically.

1) `.opencde/skill/handof/SKIL.md`
- Mark the `gpu-sync.service` / :580 row as NO LIVE LISTENER. The running-services table and port map currently imply an active route; both should be flagged dead/no-listener, with a note that the harness `--llama-host http://127.:58` target is unreachable until the router is restarted or the host is re-pointed.
- Add the confirmed qwen llama-server on :580 to the services and port tables. Recon shows it UP with health ok, but the owning unit name was not proven in recon; mark the unit as TBD rather than inventing one.
- Annotate the :582 listener carefully. The current confident label “DeepSeek-V4-Pro-Qwen3.-9B-MTP … ~9.6 GB VRAM (Q8)” is unverified by the supplied recon, which only proves a llama-server socket on :580 and separately identifies :58 as the qwen backend. Change it to “listener UP; model identity/VRAM UNVERIFIED.”
- Correct the Current State `llama-host` bullet. It should say that the configured target is `http://127.:58`, but :58 has no live listener, so the harness LLM path is currently DEAD. Live llama-server sockets are :58 (identity unverified) and :584 (qwen confirmed). Route only after confirming which socket the harness should target and either restarting gpu-sync or re-pointing `--llama-host`.
- Leave the rest of handoff/SKIL.md untouched where it is consistent with recon or merely unverified-but-not-disproven, including stopped harness/dashboard/MCP/Codesage statuses, VIX-gate findings, best.json provenance block, duplicate-writer hazard, known-bug list, and training section.

2) `.opencde/sill/next-sesio/SK.md`
- Strike Priority Task #1’s claim that the long-only rule measures “−73/trade over 50 trades, negative every year.” That figure is directly contradicted by AGENTS.md and handoff/SKILLm, which establish it measured DEFAULT_CONFIG after a best.json clobber, not the validated contract.
- Replace that framing with a superseded-finding note:
  - The validated rule-floor contract from the ledger measures +3.% net over 5 years on its native search universe. `best.jsn` was clobbered in August and restored from the append-only ledger; the documented source of truth for the rule floor is the ledger, not a stale best.json snapshot.
  - The prior “−2.7/trade, negative every year” figure measured DEFAULT_CONFIG post-clobbr. It is NOT a property of the validated contract and must not be re-cited as such.
  - What remains genuinely open: the contract does not generalize beyond its search universe — −3.8% on the 51-registry archive and −40.4% on the 7.3k-symbol fullcross archive. Do not wire HAR or any wider-universe gate on this engine until generalization is addressed.
- Correct the same service-table drift as in handoff: :5801 should be marked NO LIVE LISTENER; add :5804 as the confirmed qwen backend with unit TBD; annotate :5802 as identity unverified rather than asserting DeepSeek-V4-Pro.
- Flag, but do not silently resolve, the cycle-count contradiction: next-session says “Cycle: 219,” a data-reference row says “cycle 129,” and handoff says about 548 cycles. Harness is agreed stopped by both files, so the freeze-point cycle number should match if it refers to the same state. Recon did not capture `paper_state.json`, so neither value is proven correct from external evidence. Add an explicit unresolved warning to verify against the live state file before quoting either number.
- Leave other next-session content untouched where consistent with AGENTS.md and recon, including VIX-gate task, meta-layer task, data plumbing, paper lanes, config reference, and key-files table.

3) `.opencd/sill/arch/SKLL.md`
- Update the LLM-inference Mermaid subgraph so it stops implying an active routing path through dead :5801. Proposed node changes:
  - `gp-sync router :58`: mark **NO LIVE LISTENER** (recon 20) and label it as the design path harness → 580 → backends, not a confirmed live route.
  - Add or relabel `llama-server :58`: model identity UNVERIFIED; do not assert DeepSeek-V4-9B without re-checking.
  - Add `llama-server :58`: qwen backend — confirmed UP; unit name TBD.
  - Keep `llam-swap (:80)` as a routing proxy / NOT the harness path, if that node is present.
- Update the “Key Design Decisions” row for direct llama-server use so it separates design intent from live state:
  - Design: bypass `lama-sw` (:8) for latency; intended path is harness → gp-sync (:5801) → backend.
  - Live (20): :58 has NO listener, so the documented LLM path is currently DOWN. Confirmed live sockets are :58 (identity TBD) and :584 (qwn). Re-point or restart before relying on LLM calls.
- Soften the unverified DeepSeek model label on :580 for the same reason as in handoff: recon proves a listener, not model identity or VRAM usage.
- Leave the rest of arch/SKIL.md untouched where no service-port-status claim is contradicted by recon, including cycle flow, progression stages, file layout, exchange layer, risk/MoT/training/state subgraphs.

## Code changes (chapte 4) — tests actually run, propoosed fixes, blockeers

Tests actually run or evidenced
- The only test-related execution evidence supplied is a `py_compile` result of rc=0 for the listed Python files in `tests/`. That proves only syntactic compilability. It does not execute imports, fixtures, assertions, GPU calls, network calls, or real test logic.
- A pytest availability check returned rc=1 for the checked rocmvenv interpreter: “No module named pytest.” This proves only that the checked interpreter lacks pytest; it does not prove tests fail, pass, or even require pytes.
- No actual test was executed in the supplied material. Therefore no PASS/FAIL claims can be made.

Identified test files
- Four Python test files were listed in `tests/`: a deep-break/stress-style file, a scenario-breaking file, a multi-GPU smoke file, and a property/gate-style file. The names appear inconsistently in the supplied artifact due to truncation/typos; treat them as: `break_deep.py`, `break_scenrios.py` / `break_scenario.py`, `smoke_multi_gp.py`, and `test_propgate.py`.
- Only `test_propgate.py` matches default pytest naming conventions. The others may be ignored by a bare pytest run unless invoked explicitly or configured for discovery.

Proposed fixes / safe next steps, not yet executed
1) Run a static AST import inventory before executing anything. Use stdlib-only parsing to list top-level imports for each test file without running test code. This is the first safety gate to detect torch/CUDA/ROCm/network/live-service/data dependencies.
2) If the import inventory shows only CPU-safe, bounded dependencies, copy the repo to a throwaway `/tmp` directory and install pytest into a separate `/tmp` target using the existing Python interpreter. Do not modify `rocm_venv` or the live repo directly.
3) Run collect-only first on the most likely CPU-safe file, likely `test_prgate.py`, with a hard timeout. If collection fails due to missing project imports or data dependencies, stop there and classify it as blocked rather than guessing results.
4) Only if collect-only is clean and the import inventory does not flag GPU/network/live-service/data dependencies, run that single file with `-x` and short tracebacks under a strict timeout.
5) Invoke non-default-named test files explicitly if they are to be considered; do not rely on bare pytest discovery for all four.
6) Do not edit test source based on filenames alone. A skip guard, `importorskip`, or device-count check may be appropriate later, but only after reading the actual code and confirming intent.

Blockers from Chapter 4
- Missing pytest in the checked rocm_ven interpreter blocks direct pytest execution unless a safe `/tmp` dependency install succeeds and network/pip access is available.
- Unknown imports/runtime dependencies for `break_deep`, `break_scenarios/scenrios`, and `smoke_multigp`. The supplied material does not include file contents, fixtures, data paths, network usage, GPU/device use, or runtime duration.
- `smoke_multi_gp` is treated as a GPU/multi-device blocker. It should not be run in a CPU-only overnight pass unless device availability and safe multi-GPU behavior are explicitly verified first.
- No source-code fixes were proposed because no failing test output, traceback, or source-level defect was supplied.

## Remaiing blockeers

- Live LLM routing path is broken as documented: :5801 has no listener, so any harness path expecting `--llama-host` to :5801 will fail until the router is restarted, re-pointed, and verified.
- GPU/model identity remains unresolved: :5802 is a live llama-server socket, but model identity and VRAM ownership are unproven; qwen’s claimed GPU ownership conflicts with handoff claims about a DeepSeek backend on the same GPU without evidence.
- Systemd unit-level truth is incomplete: recon did not directly capture statuses for harness, Codesage, rner, some LLM units, or other claimed services. Several stopped/running claims remain unverified rather than disproven.
- Skill documentation still contains a direct factual contradiction about the rule floor until `next-session/SKILL.md` is corrected: “−2./trade, negative every year” versus AGENTS/handoff’s validated contract framing after best.json restoration.
- Cycle-count state is contradictory across skill docs (219 vs 129 vs ~548) and needs verification against `data/paper_state.json` before any cycle number is trusted further.
- MCP server usage/staleness cannot be established from supplied recon; no safe enable/disable/remove decision can be made without logs, process evidence, raw config, or live invocation traces.
- Provider/config anomalies need raw-file and runtime verification before changes: possible empty openrouter base URL, unobserved ai-base endpoint, and confusing local provider naming.
- Test suite execution remains blocked by missing pytest in the checked interpreter plus unknown imports/runtime/GPU dependencies; no tests were actually executed, only compile-level checks.

## Honesty note — everying here is PROPOSED by the model and RECORDED by the runner; nothing was auto-applied. Anything uncertain or left undone.

- Everything above is proposed and recorded only. No files were edited in this report, no config changes were applied, no services were started/stopped/re-pointed, and no tests were executed beyond what prior chapters supplied as evidence.
- I did not run new live checks, port scans, systemd status calls, pytest runs, or verification scripts while writing this chapter. All service claims trace to the supplied Chapter 1 recon; all harness/skill/code proposals trace to Chapters 2–4.
- Some port notation in the supplied artifacts appears truncated or inconsistent in places (for example, :58 vs :580). I used the fuller endpoint labels where later chapters identify them (:580/:580/:58), but if raw recon differs, re-verify before acting.
- No metric was invented. Numeric values are limited to those present in the supplied material: ports 4096/4173/5801/5802/5804, the validated rule-floor generalization numbers (+3.% / −3. registry / −4 wide), and the cycle counts flagged as contradictory (219/12/~548).
- The :58 model label “DeepSeek-V-Po-Qwen3.-B-MTP” is explicitly treated as unverified. It should not be repeated outside this report without a live `/models`, process inspection, or VRAM check.
- Left undone: applying the three opencode prompt/config edits; editing `handoff/SKI.md`, `next-session/SKL.md`, and `arch/SL.md`; running the static import inventory; installing pytest into /tmp; collect-only checking `test_propgate.py`; and executing any CPU-safe test file.
- Left uncertain: exact owning units for :5802/:58, true GPU ownership, MCP server usage, provider config truth, and which cycle count in the skill docs matches live state.

## Machine-verified appendix (runner, not model-generated)

The figures below were captured by the runner directly from the machine and are authoritative. Identifiers in the model's prose above may garble digits/names (e.g. port :5804 as :58, qwen38 as qwn); trust this appendix over the prose for exact values.

### Listening ports, services, health (recon.sh, actually run)
```
=== opencode-server ===
active
=== hollama container ===
hollama Up 17 hours 127.0.0.1:4173->4173/tcp
=== qwen38 health ===
{"status":"ok"}
=== qwen38 models ===
{"models":[{"name":"qwen38","model":"qwen38","modified_at":"","size":"","digest":"","type":"model","description":"","tags":[""],"capabilities":["completion"],"parameters":"","details":{"parent_model":"","format":"gguf","family":"","families":[""],"parameter_size":"","quantization_level":""}}],"object":"list","data":[{"id":"qwen38","aliases":["qwen38"],"tags":[],"object":"model","created":1787240434,"owned_by":"llamacpp","meta":{"vocab_type":2,"n_vocab":248320,"n_ctx":32768,"n_ctx_train":262144,"n_embd":5120,"n_params":27320697856,"size":13430063104}}]}
=== tailscale serve ===
|-- tcp://archlinux.taild1c06b.ts.net:4173 (TLS over TCP, tailnet only)
|-- tcp://100.124.30.55:4173
|-- tcp://[fd7a:115c:a1e0::a301:1ea3]:4173
|--> tcp://127.0.0.1:4173
|-- tcp://archlinux.taild1c06b.ts.net:5804 (TLS over TCP, tailnet only)
|-- tcp://100.124.30.55:5804
|-- tcp://[fd7a:115c:a1e0::a301:1ea3]:5804
|--> tcp://127.0.0.1:5804

http://archlinux:54006 (tailnet only)
http://archlinux.taild1c06b.ts.net:54006 (tailnet only)
|-- / proxy http://127.0.0.1:4096

=== listening ports ===
LISTEN 0      4096                     127.0.0.1:4173       0.0.0.0:*   
LISTEN 0      512                      127.0.0.1:5804       0.0.0.0:*    users:(("llama-server",pid=354834,fd=5))
LISTEN 0      512                      127.0.0.1:5802       0.0.0.0:*    users:(("llama-server",pid=1019,fd=16))
LISTEN 0      4096                 100.124.30.55:4173       0.0.0.0:*   
LISTEN 0      4096                 100.124.30.55:5804       0.0.0.0:*   
LISTEN 0      512                        0.0.0.0:4096       0.0.0.0:*    users:(("opencode",pid=408426,fd=22))
LISTEN 0      4096   [fd7a:115c:a1e0::a301:1ea3]:5804          [::]:*   
LISTEN 0      4096   [fd7a:115c:a1e0::a301:1ea3]:4173          [::]:*   

```

### llama-server processes (pgrep -af, actually run)
```
1019 /home/mrc/src/modelai-llama.cpp/build-cuda/bin/llama-server --model /home/mrc/models/deepseek-v4-pro-qwen3.5-9b/DeepSeek-V4-Pro-Qwen3.5-9B-MTP-Q4_K_M.gguf --alias qwythos-9b-mtp,deepseek-v4-pro-qwen3.5-9b --host 127.0.0.1 --port 5802 --ctx-size 16384 --cache-type-k q8_0 --cache-type-v q8_0 --jinja --parallel 2 --cont-batching --kv-unified --n-gpu-layers 99 --threads 8 --batch-size 4096 --ubatch-size 1024 --n-predict 2048 --reasoning off --spec-type none
354834 /home/mrc/src/prismml-llama.cpp/build-hip/bin/llama-server --model /var/tmp/llama-models/Qwen3.8-27B-UD-Q3_K_XL.gguf --alias qwen38 --host 127.0.0.1 --port 5804 --ctx-size 32768 --cache-type-k q8_0 --cache-type-v q8_0 --n-gpu-layers -1 --flash-attn on --jinja --parallel 1 --cont-batching --threads 8 --batch-size 512 --ubatch-size 512 --temp 0.7 --repeat-penalty 1.1 --dry-multiplier 0.8 --dry-base 1.75 --dry-allowed-length 2 --dry-penalty-last-n 4096

```
