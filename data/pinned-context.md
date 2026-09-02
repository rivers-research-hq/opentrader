# Pinned Context — OpenTrader / qwen38 ops

This is the operating context for the `ops` agent. Read this before acting. Update it when state changes.

## Hardware
- GPU0 = RTX 3070 (8GB, CUDA). GPU1 = RX 7900 GRE (16GB, ROCm). VRAM is essentially FULL at 15.85/16GB (qwen38 owns GPU1).
- System RAM: 31Gi total, ~19Gi available. `/home` ~28G free, `/` ~36G free.
- 16 CPU cores.

## Services & ports (verify with real commands, do not assume)
- opencode server: `opencode-server.service`, 0.0.0.0:4096.
- Hollama UI: docker `hollama`, 127.0.0.1:4173 (phone chat, browser-direct).
- qwen38 backend: `qwen38-serve.service`, 127.0.0.1:5804, alias `qwen38`, single slot, full offload.
- tailscale serve: 4173, 5804 (tcp), 54006 -> 4096 (legacy web handler). Config lives in tailscaled state (wiped on stray `sudo tailscaled`).
- Overnight runner: `scripts/overnight-runner.py` (launched `systemd-run --user --unit=overnight-runner`). "Runner does all file I/O": it gathers live state + file contents, builds a self-contained prompt, invokes the tool-less `scribe` agent (`~/.config/opencode/agents/scribe.md`, `permission: deny`) to emit a text analysis, then writes `data/chapters/chNN.md` + appends a distilled entry to `data/INDEX.md` (capped to last 5) + writes `data/overnight_run_report.md` (stage 5). Each `chNN.md`/report carries a runner-appended "Machine-verified appendix" (recon.sh + llama-server cmdlines) because qwen38 garbles digits/identifiers in prose. Retries empty responses (up to 3). Run single stages with `--only N` or `--from N`. Never read `data/overnight_run.log` or raw `chapters/*.json.log` in a chapter.

## Model
- `/var/tmp/llama-models/Qwen3.8-27B-UD-Q3_K_XL.gguf` (13.4GB, 27.3B, arch `qwen35` hybrid: full-attn + SSM/Gated-DeltaNet).
- Trained to 256K ctx; SERVED at 128K (memory-bound, not model-bound). KV cache q4_0 in RAM via `--no-kv-offload` (uses the idle RAM, frees VRAM). Generation ~10.4 t/s (~30% slower than GPU-KV@64K's 14.7) but Qwen Code's input budget roughly doubles (~52K), fixing the forced-compaction wall. Preflight counts offloaded KV against RAM.
- Reasoning is ON (`<think>`/`reasoning_content`) — user chose to keep it. Sampling flags (2026-08-20, DRY disabled): `--temp 0.7 --repeat-penalty 1.0 --dry-multiplier 0.0 --dry-base 1.75 --dry-allowed-length 2 --dry-penalty-last-n 4096`. A/B (garble probe, temp 0): DRY-on gave 5/10 exact identifier matches with digits/identifiers elided to `...`; DRY-off + repeat-penalty 1.0 gave 10/10 across 3 runs. DRY (prose anti-repetition) was corrupting code identifiers. Do NOT re-enable DRY/repeat-penalty for Qwen Code.
- No weight training: blocked by disk + VRAM.

## Decisions locked in (do not relitigate)
- qwen38 STAYS. Do not propose model swaps (user rejected Qwen3-Coder).
- Reasoning stays ON.
- No SFT/weight training this cycle.

## Recent changes
- qwen38 sampling: DRY disabled + repeat-penalty 1.0 (A/B: identifier exact-match 5/10 → 10/10; DRY was eliding digits/identifiers to `...`). Service unit is the source of truth.
- qwen38 context: 32K → 64K → 128K; KV q8_0 → q4_0, then moved to RAM (`--no-kv-offload`); batch 512 → 1024. Preflight updated for offloaded KV. Gen 14.7 → 10.4 t/s; Qwen Code budget ~52K.
- qwen38 spec decoding: `--spec-type ngram-simple` (size_n=4, size_m=8). ~1.6× on real code (23.6 vs 14.7 t/s), ~4.7× on repetition tasks. Draft-MODEL approach (Qwen2.5-0.5B) FAILED — target `qwen35` pre-tokenizer ≠ draft `qwen2`, llama.cpp rejects vocab mismatch. Do not re-try model drafts.
- Skills slimmed 85 -> 35 (`odysseus` 50-skill dir removed from `opencode.jsonc` skills.paths).
- Compaction tuned less-aggressive: `tail_turns 10`, `preserve_recent_tokens 8192`.
- `ops` agent created (this context) for lean overnight/self-improvement work.

## Known issues (flag, do not silently "fix")
- `paper_state.json` has MULTIPLE writers and no cross-process lock — never treat as verified truth without reconciliation.
- `opencode-server.service` contains plaintext API keys (DEEPSEEK/OPENROUTER/ZHIPU) — flagged, not remediated.
- `/usr/local/bin/opencode` is a 9-byte "Not Found" stub (needs sudo to remove); real binary at `/home/mrc/.opencode/bin/opencode`.

## Operating rules (from AGENTS.md)
- Audit gate before consuming/building/reporting; no fabricated metrics; surface contradictions first.
- rcheck `check_environment` before heavy steps; `run_sandboxed` for risky commands.
- Evidence-first: make changes only with proof.
