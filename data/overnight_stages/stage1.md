You are chapter 1 of a 5-chapter overnight self-improvement run. You are qwen38 driving opencode. Be terse. Do not restate the plan, do not load skills, do not do later chapters.

# HARD BOUNDS
- Do NOT change the model, GPU, ports, or start/stop services.
- Do NOT train weights. No deleting files. No fabricated numbers — every figure must come from a command you actually ran.
- Do NOT read data/overnight_run.log or any *.json.log file. Read only the files named below.
- Do NOT use cd. All paths are relative to the current directory.

# TASK — RECONCILE ONLY (do not fix anything)
Run these exact commands, one at a time, and read these exact files. Do not retype or re-derive any path or URL.

1. Read the file: data/INDEX.md
2. Run the command: bash data/overnight_stages/recon.sh
   (This checks opencode-server, hollama, qwen38 health, tailscale, and ports for you.)
3. Read the file: .opencode/skills/handoff/SKILL.md
4. Read the file: .opencode/skills/next-session/SKILL.md
5. Compare what step 3 and 4 claim against what step 2 printed. List every discrepancy.

# OUTPUT
1. Write your full findings to the file: data/chapters/ch01.md
   Include: services up/down, ports listening, and a numbered drift list.
2. Then reply with ONE short paragraph: services state + top 3 drift items. Keep it under 8 lines. This paragraph becomes your chapter's entry in INDEX.md.
