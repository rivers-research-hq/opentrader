#!/usr/bin/env python3
"""warden_failover — keeps a Warden LLM alive across GPU evictions.

The user games; a game grabbing a GPU's VRAM OOMs the llama-server on it.
Primary Warden LLM = Granite 4.2 on the RX 7900 GRE (:5802). This
supervisor (every 5 min, ~free) enforces the fallback chain:

  primary up            -> ensure the fallback (Qwen on 3070, :5804) is off
  primary down + 3070   -> start the fallback, verify it answers
  primary down + 3070   -> do nothing if the 3070 lacks headroom (the user
  has <4GB free            is gaming; the Warden skips its run gracefully)

Never touches the game: no kills, no restart loops against a busy GPU.
"""

import json
import subprocess
import sys
import time
import urllib.request

PRIMARY = "http://127.0.0.1:5802/v1/models"
FALLBACK = "http://127.0.0.1:5804/v1/models"
FALLBACK_UNIT = "opentrader-warden-qwen.service"
MIN_FREE_MIB = 4000


def _up(url, timeout=6):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read()).get("data") is not None
    except Exception:
        return False


def _nvidia_free_mib():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.free",
                              "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=15).stdout
        return min(int(x) for x in out.split() if x.strip())
    except Exception:
        return 0


def _ctl(*args):
    return subprocess.run(["systemctl", "--user", *args],
                          capture_output=True, text=True, timeout=30)


def main():
    primary = _up(PRIMARY)
    fallback = _up(FALLBACK)
    if primary:
        if fallback:
            _ctl("stop", FALLBACK_UNIT)
            print("[failover] primary restored — fallback stopped")
        else:
            print("[failover] primary healthy — nothing to do")
        return
    if fallback:
        print("[failover] primary down, fallback already serving")
        return
    free = _nvidia_free_mib()
    if free < MIN_FREE_MIB:
        print(f"[failover] primary down but 3070 has only {free} MiB free "
              f"(gaming?) — not starting fallback, warden will skip runs")
        return
    r = _ctl("start", FALLBACK_UNIT)
    if r.returncode != 0:
        print(f"[failover] fallback start FAILED: {r.stderr[:200]}")
        return
    for _ in range(12):  # up to 60s for model load
        time.sleep(5)
        if _up(FALLBACK, timeout=4):
            print("[failover] fallback Qwen serving on :5804")
            return
    print("[failover] fallback started but did not answer in 60s")


if __name__ == "__main__":
    main()
