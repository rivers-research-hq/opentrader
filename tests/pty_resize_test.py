"""Real resize test: spawn the TUI in a pty at 110x30, let it render, then
resize the pty to 76x22 via TIOCSWINSZ (fires SIGWINCH), capture post-resize
frames, and assert the rebuilt frame uses the NEW width (no old-width lines
that would wrap)."""
import os, pty, fcntl, struct, termios, select, time, signal
import re

pid, fd = pty.fork()
if pid == 0:
    os.chdir("/home/mrc/opentrader/tui")
    os.execv("/usr/bin/node", ["node", "index.js", "--forex"])

# set 110x30
fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 110, 0, 0))
time.sleep(3.0)
# drain initial output
try:
    while select.select([fd], [], [], 0.1)[0]:
        os.read(fd, 65536)
except OSError:
    pass

# RESIZE mid-run to 76x22 -> SIGWINCH
fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 22, 76, 0, 0))
time.sleep(2.5)

buf = b""
deadline = time.time() + 2.0
while time.time() < deadline:
    r, _, _ = select.select([fd], [], [], 0.2)
    if r:
        try:
            buf += os.read(fd, 65536)
        except OSError:
            break

out = buf.decode("utf8", "replace")
os.kill(pid, signal.SIGKILL)
os.waitpid(pid, 0)

# analysis: after resize, borders should be ~76 wide, not 110
stripped = lambda s: re.sub(r"\x1b\[[0-9;]*m", "", s)
lines = [stripped(l) for l in out.split("\n") if l.strip()]
borders = [ln for ln in out.split("\n") if "╭" in ln or "╰" in ln]
bwidths = sorted({len(stripped(ln).strip()) for ln in borders})
print("border line widths after resize:", bwidths[-6:] if bwidths else "NONE")
print("over-long (>90 char) lines in post-resize output:",
      sum(1 for ln in out.split("\n") if len(stripped(ln)) > 90))
tail = [stripped(ln).rstrip() for ln in out.split("\n") if stripped(ln).strip()][-4:]
print("--- tail sample ---")
for t in tail:
    print("   ", t[:90])
print("PASS" if bwidths and max(bwidths) <= 80 else "FAIL: frame still built at old width")