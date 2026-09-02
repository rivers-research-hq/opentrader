# JOB 2 — Build the Tool-Rotation Plugin (compaction-proof)

You are Qwen3.8-27B via `qwen38/qwen38-agentic`. This is a SINGLE, BOUNDED task: write
one plugin file, verify it loads, report. Do it in ONE pass. Do NOT re-read your own
work. Do NOT summarize your progress repeatedly.

## CRITICAL EXECUTION RULES (these prevent the hang that killed Job 1)

1. **Write the plugin in ONE write call.** Draft the full file mentally, then `write`
   it. Do not write, then re-read, then rewrite.
2. **Never re-read files you just wrote or read.** If you have the content, use it.
3. **Max 8 tool calls total.** Count them. If you're at 8 and not done, write the file
   anyway with your best effort.
4. **After writing: ONE verification** (`opencode debug config` grep for your tool),
   then STOP and give the final report. Do not loop.
5. Do not fetch large docs. You know the opencode plugin API. If unsure, make a
   reasonable choice and note it. (A `tool.definition` hook + a `tool:` custom tool is
   the documented pattern.)

## THE TASK

Write ONE file: `/home/mrc/.config/opencode/plugin/tool-rotation.ts`

It must:
1. Register a `tool_rotate` tool callable by the model with args:
   `{"tools": ["webfetch", "playwright"], "action": "activate" | "deactivate"}`.
2. Use the `tool.definition` hook to filter tool schemas from the model's context based
   on the active set. Default active set:
   `read, write, edit, bash, glob, grep, task, todowrite, question, webfetch, skill,
   mcp__*` (broad defaults so nothing breaks).
   Heavy tools that start DEACTIVATED (filtered from context until rotated in):
   `playwright_browser_*`, `huggingface_*`, `codesage_*`, `context7_*`, `searxng_web_search`.
3. Persist the active set to `/home/mrc/.opentrader-toolset.json` (simple JSON: a list of
   active tool name prefixes). Load it at startup if present.
4. The `tool_rotate` tool itself MUST always remain available (never filter itself).
5. Keep it ~120 lines or less. Simplicity over cleverness.

## VERIFICATION (once)

Run: `opencode debug config 2>&1 | grep -i tool_rotate`
If it shows `tool_rotate`, you're done. If the grep finds nothing, check that the plugin
dir is auto-discovered (`/home/mrc/.config/opencode/plugin/`), then either fix the file
once or report the blocker.

## DELIVERY

Report: the file path, the default active set, the deactivated-heavy list, the grep
output proving it loaded, and any caveat you hit. Keep the report under 250 tokens.
