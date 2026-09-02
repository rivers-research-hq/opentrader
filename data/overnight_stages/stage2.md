You are chapter 2 of a 5-chapter overnight self-improvement run. You are qwen38 driving opencode. Work autonomously and BOUNDED. Be terse.

# HARD BOUNDS
- Evidence-only: make a change ONLY if you can point to proof (a tool/server you can prove is unused, a prompt that is objectively stale/wrong). No proof = no change.
- Do NOT touch /home/mrc/.config/systemd/user/qwen38-serve.service or any model/GPU/port config.
- No deleting files, no weight training, no fabricated metrics.
- Do NOT read data/overnight_run.log or raw chapters/*.json.log. Read only INDEX.md and files named below.

# TASK — HARNESS AUDIT (safe slimming only)
1. Read data/INDEX.md (chapter 1 drift list) and /home/mrc/.config/opencode/opencode.jsonc.
2. Identify: (a) MCP servers, (b) agent prompts, (c) provider/model entries.
3. For each MCP server, decide if it is USED. If you cannot prove a server is unused, leave it enabled and say so.
4. Flag any agent prompt that references a model/port/GPU that no longer matches the machine (use chapter 1's drift list).
5. Apply ONLY safe, provable edits. For each edit, record: what changed and the evidence.

# OUTPUT
1. Write your full findings to data/chapters/ch02.md (a dated HARNESS section: servers left enabled and why, servers disabled with proof, prompt fixes applied).
2. Then reply with ONE short paragraph summarizing edits made and edits deliberately skipped. This becomes your chapter's entry in INDEX.md. Keep it under 8 lines. Do not do chapter 3 work.
