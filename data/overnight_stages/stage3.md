You are chapter 3 of a 5-chapter overnight self-improvement run. You are qwen38 driving opencode. Work autonomously and BOUNDED. Be terse and factual — do not embellish.

# HARD BOUNDS
- Tight, factual edits only. Do NOT rewrite skill files wholesale; correct stale facts.
- Read a file before editing it. No fabricated claims — only write facts you verified this run or read from INDEX.md.
- Do NOT read data/overnight_run.log or raw chapters/*.json.log.

# TASK — UPDATE STALE SKILLS
1. Read data/INDEX.md (chapters 1-2 results, especially the drift list).
2. Read these skill files:
   - .opencode/skills/handoff/SKILL.md
   - .opencode/skills/next-session/SKILL.md
   - .opencode/skills/arch/SKILL.md
3. For each, correct ONLY facts that are now wrong: service names/ports, running/stopped status, model identities, known bugs. Update the verified-date line. Leave everything else untouched.

# OUTPUT
1. Write your full findings to data/chapters/ch03.md (a dated SKILLS section: each file edited and the specific fact corrected).
2. Then reply with ONE short paragraph: files touched and what was corrected. This becomes your chapter's entry in INDEX.md. Keep it under 8 lines. Do not do chapter 4 work.
