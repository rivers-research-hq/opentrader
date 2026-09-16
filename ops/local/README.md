# Local worker stack (retooled 2026-09-15)

## What was rotten

| finding | evidence |
|---|---|
| `llama-server`, `llama-server-perf`, `llama-server-light` all point at `qwen3.6-35b-a3b/…UD-IQ4_XS.gguf`, which **no longer exists** | journal: `gguf_init_from_file: failed to open GGUF file` |
| the on-disk 27B `UD-Q3_K_XL` **cannot load** in the installed llama.cpp (v8908) | `missing tensor 'blk.64.ssm_conv1d.weight'`, arch `qwen35` — a GGUF/build vintage mismatch, not a bad download (13.44GB local vs 13.15GB on HF) |
| the eval harness scored `tool-call 0/10` on every historical run | `eval.py` never imported `re`; the category was structurally un-passable (fixed 2026-08-29) |
| three units "looked live" but produced nothing | the postmortem rule: every job must name a recent artifact it produced or be removed |

Per AGENTS.md: the GRE **is** a compute target; it only has to be free while the
human games. `scripts/gpu_pick.py` is the gate.

## The rule this stack enforces

**A local model is not "up" until it has a validation artifact.** Load + eval +
needle at two contexts + one real queued work order, recorded under
`data/local/<model>/`. Benchmarks are not acceptance.

## Shape chosen for this hardware

GRE = 16GB VRAM, 3070 = 8GB (always-on, shared with the warden), 31GB RAM, 16 cores.

| shape | example | fits | trade |
|---|---|---|---|
| dense 9–10B @ **Q8_0** (~9.8GB) | `Ornith-1.5-9B-Q8_0` | fully in VRAM + large KV | max precision per weight; less model |
| MoE 30B/**A3B** @ Q5_K_M (~21GB) | `Qwen3-Coder-30B-A3B-Instruct-Q5_K_M` | 16GB VRAM + experts on CPU | 5-bit, but ~3B active = fast and more capable |

Both are non-Google and ≥4-bit. `--n-cpu-moe N` keeps only attention/dense on the
GPU for the MoE; a dense model needs no expert offload.

## Files

- `worker.env` — single source of truth (model path, port, ctx, offload).
- `local-worker.service` — normal profile; refuses to start while gaming
  (`ExecCondition` on `gpu_pick.py`).
- `local-worker-gaming.service` — LIGHT profile: fewer GPU layers, smaller ctx,
  safe to run alongside a game.
- `scripts/local_validate.sh` — the acceptance gate.

Install: `cp ops/local/local-worker*.service ~/.config/systemd/user/` then
`systemctl --user daemon-reload`. Validate before trusting it with queue work.

## Using it as a coding agent

This server is wired to `opencode` as the `local-coder` agent — the repo's local
coding workhorse. Invoke it with `scripts/local_coder.sh "<task>"` (fresh session
per call; project venv on PATH). Full guide, measured reliability and known
failure modes: `docs/agents/local-coder.md`.
