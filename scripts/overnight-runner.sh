#!/usr/bin/env bash
# Overnight self-improvement runner — chapter/index model.
# Each stage is a fresh opencode run (a "chapter"). The runner extracts each
# chapter's FINAL answer text and appends it as a distilled entry to INDEX.md,
# capped to the last 5 entries. Chapters never read the raw growing history.
set -u

OPC=/home/mrc/.opencode/bin/opencode
DIR=/home/mrc/opentrader
DATA=/home/mrc/opentrader/data
STAGES="$DATA/overnight_stages"
CHAPTERS="$DATA/chapters"
ARCHIVE="$CHAPTERS/archive"
INDEX="$DATA/INDEX.md"
LOG="$DATA/overnight_run.log"
CFG="$DATA/overnight-config.jsonc"

export OPENCODE_CONFIG="$CFG"
export OPENCODE_DISABLE_AUTOCOMPACT=1

mkdir -p "$CHAPTERS" "$ARCHIVE"
[ -f "$INDEX" ] || { printf '# Overnight Run Index\n\n' > "$INDEX"; }
: > "$LOG"

ts() { date '+%Y-%m-%d %H:%M:%S'; }
log() { echo "$(ts) $*" >> "$LOG"; }

# Extract the final assistant message's text from a --format json event stream.
extract_final() {
  python3 - "$1" <<'PY'
import sys, json
texts, order = {}, []
for line in open(sys.argv[1]):
    line = line.strip()
    if not line:
        continue
    try:
        e = json.loads(line)
    except Exception:
        continue
    if e.get("type") == "text":
        mid = e["part"].get("messageID")
        texts.setdefault(mid, []).append(e["part"]["text"])
        if mid not in order:
            order.append(mid)
CONTINUE_STR = "Continue if you have next steps, or stop and ask for clarification if you are unsure how to proceed."
for mid in order:
    joined = "".join(texts[mid]).strip()
    if joined and joined != CONTINUE_STR:
        print(joined)
        break
PY
}

# Cap INDEX.md to the last 5 chapters; archive anything older.
cap_index() {
  python3 - "$INDEX" "$ARCHIVE" <<'PY'
import sys, os, re, time
index_path, archive_dir = sys.argv[1], sys.argv[2]
text = open(index_path).read()
parts = re.split(r'(?m)(?=^## Chapter \d+)', text)
header, chapters = parts[0], parts[1:]
if len(chapters) > 5:
    os.makedirs(archive_dir, exist_ok=True)
    out = os.path.join(archive_dir, "index_archived_%d.md" % int(time.time()))
    with open(out, "w") as f:
        f.write("".join(chapters[:-5]))
    with open(index_path, "w") as f:
        f.write(header + "".join(chapters[-5:]))
PY
}

run_chapter() {
  local n="$1" f="$2"
  local tag; tag=$(printf 'ch%02d' "$n")
  local raw="$CHAPTERS/$tag.json.log"

  log "STAGE $n START"
  "$OPC" run --dir "$DIR" --agent ops --auto --format json \
      --title "overnight-stage-$n" "$(cat "$f")" > "$raw" 2>"$CHAPTERS/$tag.err.log"
  local rc=$?
  if [ "$rc" -eq 0 ]; then log "STAGE $n OK"; else log "STAGE $n FAILED rc=$rc"; fi

  local answer
  answer=$(extract_final "$raw")
  {
    printf '## Chapter %d — %s\n' "$n" "$(ts)"
    if [ -n "$answer" ]; then
      printf '%s\n' "$answer" | head -c 1200
      echo
    fi
    echo
  } >> "$INDEX"
  cap_index
}

run_chapter 1 "$STAGES/stage1.md"
run_chapter 2 "$STAGES/stage2.md"
run_chapter 3 "$STAGES/stage3.md"
run_chapter 4 "$STAGES/stage4.md"
run_chapter 5 "$STAGES/stage5.md"

log "RUNNER DONE"
