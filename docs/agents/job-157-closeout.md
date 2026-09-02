# TASK — #157 closeout (mechanical, ≤8 tool calls, fresh session)

The shadow driver revision is ALREADY COMPLETE in
`/home/mrc/opentrader-sandbox/strategies/shadow_driver.py` (verified: delegates
to `RegimeRouter.step()`, `_apply_floor` multi-expert guard, `shadow_last_asof`
double-accrual guard, parses clean). A prior session looped on cosmetic
docstring edits and was halted. **Do NOT edit `shadow_driver.py` — the file on
disk is correct and your context's copy of it is stale. Your only job is the
three closeout steps below.**

If any prior conversation exists above this message, STOP and reply exactly:
"NOT A FRESH SESSION — open a new one and paste only this file."

## Steps

1. Regenerate the patch:
   `git -C /home/mrc/opentrader-sandbox diff > /home/mrc/opentrader/data/wayfinder/patches/157.patch 2>/dev/null || diff -u /home/mrc/opentrader/strategies/shadow_driver.py /home/mrc/opentrader-sandbox/strategies/shadow_driver.py > /home/mrc/opentrader/data/wayfinder/patches/157.patch`
   (sandbox has no git; the diff fallback is expected to produce a new-file diff)
2. Re-run the proof, paste output verbatim:
   `cd /home/mrc/opentrader-sandbox && PYTHONPATH=/home/mrc/opentrader-sandbox /home/mrc/rocm_venv/bin/python3 -m strategies.shadow_driver --dry`
3. Append to `data/wayfinder/ultimate_chapter.md`:
   `157 closeout heartbeat: patch regenerated, dry-run verified, ready for HITL review`

## Rules

- ≤ 8 tool calls. If a command returns the same output twice, STOP and ship
  what you have — do not retry.
- Do not modify any file under `strategies/` in either tree.
- Final reply: the dry-run output verbatim + the patch's file count. Nothing else.
