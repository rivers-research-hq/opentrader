# Incident 2026-10-12: tmux view hijack + second instance on a live session

**What happened:** an agent testing the /res overlay created a tmux window in a
session the human was attached to (`tmux new-window` switches the attached
client's active window — view hijack), then launched bare `pi` in it, which
RESUMED the human's live session file as a second concurrent writer. The human
experienced their session as "gone" and their keystrokes landed in the agent's
test instance.

**Damage:** none to data — session file verified intact (789 entries, parseable);
the human's real pi instance never stopped. View + trust damage only.

**Binding rules for all future sessions:**
1. NEVER create tmux windows/panes in a session the human is attached to, and
   never send keys into a pane without explicit human go-ahead for exactly that
   action. Interactive testing of pi features happens ONLY in a detached,
   agent-created tmux SERVER (separate socket: `tmux -L agent-test`), never in
   the human's session.
2. NEVER launch a bare `pi` — it resumes the most recent session file, which may
   be the human's live session. Always `pi --no-session` or an explicit fresh
   session for any agent-side interactive test.
3. Two pi processes on one session file = corruption risk. If it ever happens:
   kill the agent-side instance FIRST, verify the file parses, tell the human
   immediately (audit rule 5).
