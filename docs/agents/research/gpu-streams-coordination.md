# GPU Streams Coordination — live LLM + Ptolemy training + GPU0 role

**Ticket:** #49 "Coordinate two GPU streams: live LLM + training + GPU0 role" (map: Both GPUs productive simultaneously)
**Status:** RESEARCH — no service changes. Verified against code + live systemd/journal/nvidia-smi state (2026-08-10).
**Headline verdict:** Coexistence is *intended* in the code but **not safe as built**. The 10s-quiet gate's signal source is dead (masked unit → always "quiet"), the Ptolemy retrain still kills the live GPU1 server and orphans it on port 5813, and the scheduler feeds one card at a time.

---

## 1. GPU1 (RX 7900 GRE, 16GB) — harness LLM calls vs Ptolemy retrain

### Where the harness's LLM calls run

All calls go through the `gpu_sync` proxy (`config/harness_config.json`: `llama_host = http://127.0.0.1:5801`, `gpu0_host` same proxy). `gpu_sync.py` routes **by model name** (`gpu_sync.py:152-181`): backend pool is fixed at startup to `5802,5803`; `--alias` on each llama-server maps model → physical GPU.

| Call | Cadence | Target |
|---|---|---|
| ADIR bull | every cycle, per active symbol (rule-primary: none) | `qwythos-9b-mtp` → 5802 (GPU1) |
| ADIR bear/risk | every cycle, concurrent with bull | `qwen2.5-7b-instruct` → 5803 (GPU0) |
| Scout (`_llm_json_array`, harness.py:2336) | every 3 cycles, 512 tok | GPU1 |
| Coach review (harness.py:4100-4124) | every 100 cycles | GPU1 |
| arXiv extraction (harness.py:3759) | every 50 cycles | GPU1 |

Dual-host routing: `AdirDebateEngine(bull_host=llama_host, bear_host=gpu0_host, risk_host=gpu0_host)` (harness.py:545-553; mot/agents/adir_debate.py:352-380). Under `--rule-primary` the debate pool is skipped entirely (harness.py:2941-2943) → GPU0 idle.

### The Ptolemy retrain path (found)

```
setup_search/gpu_scheduler.py (manifest, one task/pass)
  └─ auto_tasks.json "ptolemy-retrain"  {gpu:"gpu1", timeout:14400, note:"idle-gated coexistence"}
      └─ task_ptolemy_train.py  →  python -m training.train_scheduler --force
          └─ execute_training() (training/train_scheduler.py:193-264)
              touch data/training.lock → sleep 30 → pkill qwythos llama-server
              → run_finetune() (Unsloth 4-bit QLoRA Qwen2.5-7B, full GPU1)
              → restart llama-server on :5813 → remove lock
```

### The "10s-quiet gating" mechanism (found)

`setup_search/gpu_scheduler.py`:
- `gpu1_quiet(seconds=10)` — `launches_in(GPU1_SERVICE, 10s) == 0`, counting `"slot launch"` events in `journalctl --user -u opentrader-llama-gpu1.service` (lines 42-60).
- Start condition: task may begin only inside a 10s-quiet gap (line 81).
- During the run: if a launch appears within 10s → `SIGSTOP` the training proc; resume after 30s quiet → `SIGCONT` (lines 106-114).
- Rationale in code: GPU1 is ~100% duty-cycled by the harness, so no long quiet window exists; progress is made across the harness's 20-57s inter-call gaps.

### Port fix 5813 — does it hold?

`5813` appears **exactly once** in the entire repo: `training/train_scheduler.py:245` (llama-server restart, `--alias qwen2.5-7b-instruct --port 5813`). No other code references it — gpu_sync's backend pool is fixed at 5802/5803, the harness points at 5801, `adir_debate.py` default is 5801.

**The fix holds only in the narrow sense:** training's private server no longer collides on a live port. It does NOT restore the live server — `pkill -TERM -f llama-server.*qwythos` kills the 5802 server, training uses GPU1, then a new server comes up on **5813 which gpu_sync never routes to**. The live GPU1 backend stays dead → harness bull fails over to GPU0 or 503. Evidence: `data/gpu_scheduler/ptolemy-retrain.out` — after an `ft_error`, `llama-server` came up on `http://127.0.0.1:5813` ("llama-server restarted") and nothing ever re-bound 5802.

### Safety verdict (GPU1): intended, not safe

1. **The gate is vacuous.** `opentrader-llama-gpu1.service` is **masked** (verified: `systemctl status` → inactive/dead, masked). `journalctl --user -u` on it returns "No entries" → `launches_in()` always 0 → `gpu1_quiet()` always True → training never pauses for the harness, even mid-call.
2. **SIGSTOP only stops the training process**, not llama-server — no GPU-side preemption. With the researcher's 27B resident at ~66% VRAM (~10.5GB of 16GB used now), a 4-bit QLoRA 7B (~5-6GB) on top is an OOM risk in the un-gated window.
3. **The "graceful pause" is a one-way signal with no consumer.** `TRAINING_LOCK.touch()` claims to put the harness in HOLD (train_scheduler.py:210-213), but **harness.py never reads `training.lock`** (grep: zero references). Only training-side components (is_idle, idle_trainer, research_runner, harness_scheduler) respect it. The pkill is the only thing that actually stops harness LLM calls — by breaking them mid-flight (sleep(30) after lock is not an ack wait; harness cycles are ≥60s).
4. **No VRAM precondition** in `finetune_cycle.py` before loading the 7B base model.
5. Currently the running researcher servers are safe from pkill (pattern is `qwythos`; the researcher's cmdline is `Qwen3.6-27B…`/`Hermes-3…`), but the 5813 orphan + journal-based gate failure applies to any retrain.

---

## 2. GPU0 (RTX 3070, 8GB) — duty cycle + concurrent fine-tune

No `docs/agents/research/gpu0-capacity.md` exists (sibling ticket #48 still open), so measured live:

- **Measured (2026-08-10, 2 min sample @3s):** 0% util, flat; VRAM 6174MiB/8192MiB used — researcher Hermes-3-8B (5936MiB) + Steam (~93MiB). Free ≈ **2.0GiB**.
- With qwen resident as per #48 (4.9GB): ≈ 3.3GiB free, minus Steam → ≈ **3.2GiB** usable.

### Duty cycle with the gated debate (bear/risk on qwen)

Bear+risk = 2 concurrent qwen calls per symbol-debate (2000 tok each, `DEBATE_TIMEOUT`-bound, thread pool; `_API_SEMAPHORE` caps 4). `mot/agents/debate.py:1022` puts a 3-call debate at ~10-24s. Harness cycle is forced ≥60s (harness.py:4404); all active symbols debate per cycle, up to 4 workers (bull on GPU1 runs concurrently).

- **Estimate: ~15-40% average duty** (10-24s busy per ≥60s cycle wave), with bursts as debates overlap; not 100%, and never co-resident with training by design — bear/risk calls land in the same quiet gaps the GPU1 training targets.
- Under rule-primary today: **0%** — the debate pool is skipped (harness.py:2941), qwen/Hermes sits resident doing nothing. That is the problem the map ticket exists to fix.

### Can a small fine-tune fit in the headroom CONCURRENTLY?

- **VRAM: yes for ≤1.5B-class QLoRA** (~1.8-2.2GB in 3.2GiB headroom with qwen resident; borderline ~2.1GB in the current 2.0GiB with Hermes resident). FinBERT-scale batch inference (420MB) fits trivially. A 7B QLoRA (~5-6GB) does **not** fit in either scenario.
- **But the existing task does the opposite:** `setup_search/task_gpu0_finetune.py:37` runs `systemctl stop opentrader-llama-gpu0.service` to free the card — the exact regression #47 flags ("no stopping services from a research task"). Its last run crashed on a missing `sentencepiece` dep *after* stopping the service (data/gpu_scheduler/gpu0-qwen-finetune.out) — service left stopped. It is also **not in the current manifest**.
- **Verdict: a concurrent fine-tune fits only as a rewrite** that (a) trains a ≤1.5B QLoRA inside the residual headroom, (b) never touches systemd, (c) honors the debate's request activity (pause on launch). The gated-debate role and a 1.5B fine-tune can share GPU0's 3.2GiB **if** the fine-tune is throttled to the quiet gaps — the same journal gate, fixed.

---

## 3. The scheduler — lock/conflict handling and residual windows

Components: `setup_search/gpu_scheduler.py` (manifest, request-activity gating), `training/train_scheduler.py` (decision + execution), `training/harness_scheduler.py` (cron milestones), `training/idle_trainer.py` (idle-watch daemon, :5802).

Shared primitive: `data/training.lock` — respected by all training-side components; **not by the harness**.

Residual conflict windows:

1. **Vacuous gate (critical):** journal gating reads a masked unit → no events → gate never fires. Any Ptolemy retrain today runs un-gated against the harness/researcher load.
2. **Pkill mid-call:** no graceful drain; sleep(30) is not an ack (harness never acknowledges the lock). In-flight LLM requests die when the qwythos server is killed.
3. **5813 orphan:** post-train server is unreachable by gpu_sync (fixed backend pool) → live GPU1 backend dead until manual restart; harness fails over to GPU0 or 503.
4. **SIGSTOP granularity:** 15s poll + 10s journal window → up to ~25s of un-gated GPU1 overlap per launch; resume needs 30s quiet → up to 45s of lost training progress per interruption.
5. **One-card serial feeding:** gpu_scheduler runs **one task per pass** (line 179 `break`). While ptolemy-retrain runs (up to 4h), GPU0 manifest tasks starve → GPU0 stays idle → the two-stream goal is structurally unreachable with the current scheduler.
6. **No VRAM preflight** before QLoRA on a card with a resident model (both GPU1 researcher 27B and GPU0 qwen/Hermes scenarios).
7. **No cross-scheduler mutual exclusion:** `harness_scheduler` milestones and `gpu_scheduler` tasks both launch training; only the (harness-unread) `training.lock` stands between them, and gpu_scheduler doesn't enforce cooldown vs `harness_scheduler` state.

---

## 4. No-regression invariants (for the downstream design ticket #50)

1. qwen/qwythos llama-servers stay up — no task may stop/restart a service or kill a server process (task_gpu0_finetune and train_scheduler's pkill both violate this today).
2. The validated rule config remains the decider (rule-primary / `RegimeRouter(rule_floor="rule")` — mot/mixture.py) — the debate may only propose.
3. MoT intact — gpu_sync model routing (5801 → 5802/5803) must not be bypassed by orphaned servers on new ports.
4. Training may only run inside verified quiet windows — the journal gate must be fixed (active unit logging `slot launch`, or a live-request probe like `idle_trainer.check_llama_idle` on the actual serving port).
5. Both cards fed independently — the scheduler must evaluate GPU0-gate and GPU1-gate as separate streams (issue #49 task 3 gap).
6. No VRAM oversubscription — preflight free-VRAM check before any training load.

---

*Sources: harness.py (scout/coach/ATDL/debate wiring, rule-primary skip), mot/agents/adir_debate.py (dual-host routing), mot/mixture.py (rule floor), gpu_sync.py (model routing), setup_search/gpu_scheduler.py + auto_tasks.json (10s/60s gating, serial feeding), training/train_scheduler.py (lock, pkill, 5813), training/harness_scheduler.py + idle_trainer.py (lock checks), setup_search/task_ptolemy_train.py / task_gpu0_finetune.py (manifest tasks), data/gpu_scheduler/*.out + scheduler.log (retrain/orphan + finetune failure evidence), live systemctl/journalctl/nvidia-smi/rocm-smi state 2026-08-10.*
