# Overnight Run Index

## Chapter 1
Live state: opencode-server is UP (:4096), Hollama is UP (:4173 local/tailnet), the qwen backend is UP on :5804 (health ok, `llama-server` listening), and a second `llama-server` listener is present on :5802; dashboard/MCP claimed-stopped endpoints show no live listeners, but harness/Codesage/runner unit statuses were not directly captured in recon. Top 3 items: (1) the claimed `gpu-sync` LLM router on :5801 has no live listener even though the handoff says the LLM stack was left running and the harness would talk to :5801; (2) pinned context claims qwen effectively owns GPU1 VRAM while the handoff also claims a ~9.6GB DeepSeek `llama-server` is LIVE on the same GPU, yet live evidence only proves two `llama-server` sockets (:5802/:5804) with no VRAM proof; (3) many claimed systemd user units lack direct status in the provided recon, so several “running” or “stopped” claims are partly unverified.

## Services

| Service | Claimed unit / claim | Claimed port/status | Live evidence from recon | Current state | Drift flag |
|---|---|---|---:|---|---|
| opencode server | `opencode_server` | 0.0.0.0:4096, running | `=== opencode_server === active`; `LISTEN 0 ... 0.0.0:40 users:("opencode

## Chapter 2
Only three prompt facts are directly contradicted by the supplied material; no MCP server can be PROVEN unused from it. The proven contradictions are: qwen-worker describes itself as Qwythos-9/CUDA although its model/provider is qwn-agentic on :580, architect describes itself as Qwen2/RTX while also using qwn-agentic, and architect says researcher deep :580 is STOPPED even though recon shows a live llama-server listener on :580. I propose exactly three edits: fix qwen-worker desc, fix architect desc, replace the architect ":580 stopped" bullet with observed-state wording. I deliberately skip all MCP server changes and most generic :581/:114 routing notes because missing listeners in one recon do not prove those prompts are unused or false as design instructions.

FULL FINDINGS

A. MCP SERVER VERDICTS

1) searxng
- Verdict: unverified / possibly stale backend, but NOT proven unused.
- Evidence: GLOBAL CONFIG lists `MCP searxng: local /home/mrc/rocm_venv/bin/python3 /home/mrc/.opencode/researcher/searxng_mcp.py enabled=True`. The architect prompt says web_search uses local SearXNG :8085, but the supplied listening-ports output has no :8085 listener.
- Why skip edit: a stdio MCP serve

## Chapter 3
**Summary paragraph:**
Three skill files carry stale or contradictory facts: `handoff/SKILL.md`, `next-session/SKILL.md`, and `arch/SKILL.md`. The single most important fix in each is: (1) **handoff** — mark the `gpu-sync` router on :5801 as having NO live listener (recon-proven dead) and add the un-documented qwen `llama-server` on :5804 to the services/port tables; (2) **next-session** — strike Priority Task #1's claim that the rule floor measures "−2.73%/trade, negative every year," which directly contradicts AGENTS.md and handoff/SKILL.md both proving that figure measured DEFAULT_CONFIG after a best.json clobber (resolved 2026-08-13), while also correcting the same :5801/:5804 port drift; (3) **arch** — update the LLM-inference subgraph and "Key Design Decisions" row so they stop implying an active routing path through dead :5801, add :5804, and soften the unverified DeepSeek model label on :5802.

---

## Full Findings by File

### 1. `.opencode/skills/handoff/SKILL.md`

**Stale fact A — `gpu-sync.service` / port 5801 shown as running.**
Recon (Chapter 1, item 1): "the claimed `gpu-sync` LLM router on :5801 has **no live listener**." The handoff lists it in the Running Service

## Chapter 4
Four Python test files exist in tests/: break_deep.py, break_scenrios.py, smoke_multi_gp.py, and test_propgate.py; the supplied py_compile run returned rc=0, so they are syntactically compilable, but no test was actually executed and pytest is missing from the checked rocmvenv interpreter. I recommend a static import inventory first, then a sandboxed collect-only/check of the CPU-safe file (likely test_propate) using a /tmp pytest dependency install, and treat smoke_multi_gp as blocked pending GPU verification.

Evidence actually run versus inferred
- Actually supplied/observed:
  - tests/ listing shows four .py test files plus __pycache__.
  - PY_COMPILE RESULT was rc=0. I interpret this as the listed Python files compiling syntactically, but the exact py_compile invocation is not shown and py_compile does not execute import statements or test logic.
  - PYTEST AVAILABILITY was rc=1: /home/mrc/rcmvn/bin/py reports “No module named pytest.” This proves only that the checked rocm_venv interpreter lacks pytest; it does not prove tests fail, pass, or even require pytest.
- Not verified from the supplied material:
  - File contents, exact test targets, imports, fixtures, data dependenc

## Chapter 5
# Overnight Self-Improvment Report (2026-)

## Services (actual stae, from chaptr 1)

- opencode-server: UP. The claimed unit was active, a listener matching the claimed `0.0.:409` endpoint was observed, and tailnet serving to that local endpoint was present. No material drift was found.
- Hollama UI: UP. The container was reported up, and local/tailnet listening endpoints were consistent with the claimed :41 service path. No material drift was fou.
- qwen backend: UP at API/socket level on :580. Health check returned ok, a `llama-server` listener was present for the claimed endpoint, and the model list included `qwn`. The owning systemd unit status was not directly captured in recon, so unit-level state is only partially verified.
- second `llam-server`: A second `llama-serer` socket/listener was present on :580. Its exact model identity and VRAM usage were not proven by the supplied recon.
- GPU sync router / :5801: NO live listener was observed in the provided port evidence. This is treated as DOWN or at least “not observed listening” at socket level, despite documentation claiming the LLM stack/harness path through it was left running.
- Dashboard/MCP endpoints claimed stopped:

