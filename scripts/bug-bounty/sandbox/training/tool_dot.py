#!/usr/bin/env python3
"""DOT Vision — tool-call timing encoder.

Encodes agent tool interactions as pixel DOT values in a PNG strip.
Each row = one tool invocation. Color channels encode tool_id, duration,
and outcome improvement. Enables 10x denser instrumentation than text logs.

A 512px wide strip holds 512 tool calls. The leftmost column is the call
index marker. Subsequent columns encode the call data.

Usage:
    from training.tool_dot import ToolDotRecorder
    recorder = ToolDotRecorder("data")
    recorder.record("file_read", duration_ms=2340, outcome_delta=+0.15)
    recorder.record("llm_call", duration_ms=890, outcome_delta=-0.05)
"""
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


TOOL_IDS = {
    "llm_call":     0,
    "file_read":    1,
    "file_write":   2,
    "bash_cmd":     3,
    "web_fetch":    4,
    "mcp_tool":     5,
    "delegation":   6,
    "compress":     7,
    "edit":         2,   # alias for file_write
    "read":         1,   # alias for file_read
    "grep":         1,
    "glob":         1,
    "write":        2,
    "task":         6,
}


@dataclass
class DotCall:
    tool_name: str
    duration_ms: float
    outcome_delta: float   # -1.0 to +1.0
    cycle: int = 0
    timestamp: float = field(default_factory=time.time)


class ToolDotRecorder:
    def __init__(self, state_dir: str = "data", width: int = 256):
        self.state_dir = Path(state_dir)
        self.width = width
        self._calls: List[DotCall] = []
        self._png_path = self.state_dir / "dot_timing.png"
        self._json_path = self.state_dir / "dot_timing.json"

    def record(self, tool_name: str, duration_ms: float = 0,
               outcome_delta: float = 0.0, cycle: int = 0):
        self._calls.append(DotCall(
            tool_name=tool_name,
            duration_ms=duration_ms,
            outcome_delta=max(-1.0, min(1.0, outcome_delta)),
            cycle=cycle,
        ))

    def save(self):
        """Save DOT strip as PNG + JSON backup."""
        if not HAS_PIL:
            self._save_json()
            return

        h = max(1, len(self._calls))
        img = Image.new("RGB", (self.width, h), (0, 0, 0))
        pixels = img.load()

        for row, call in enumerate(self._calls):
            tool_id = TOOL_IDS.get(call.tool_name, 0)
            r = min(255, tool_id * 36 + 20)

            duration_clamped = min(2550, call.duration_ms)
            g = int(duration_clamped / 10)

            outcome_clamped = max(-1.0, min(1.0, call.outcome_delta))
            b = int(128 + outcome_clamped * 127)

            for col in range(self.width):
                pixels[col, row] = (r, g, b)

            call_r = min(255, 40 + row * 2)
            call_g = min(255, 200 if row % 10 == 0 else 40 + (row % 10) * 10)
            call_b = min(255, 100 + abs(int(call.outcome_delta * 100)))
            pixels[0, row] = (call_r, call_g, call_b)

        img.save(self._png_path)
        self._save_json()

    def _save_json(self):
        self._json_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._json_path, "w") as f:
            json.dump([{
                "tool": c.tool_name,
                "duration_ms": c.duration_ms,
                "outcome_delta": c.outcome_delta,
                "cycle": c.cycle,
            } for c in self._calls], f, indent=2)

    def summary(self) -> dict:
        """Return text summary of DOT data for agent consumption."""
        if not self._calls:
            return {"calls": 0, "summary": "No tool calls recorded"}

        tool_counts = {}
        for c in self._calls:
            tool_counts[c.tool_name] = tool_counts.get(c.tool_name, 0) + 1

        avg_outcome = sum(c.outcome_delta for c in self._calls) / len(self._calls)
        total_duration = sum(c.duration_ms for c in self._calls)

        return {
            "calls": len(self._calls),
            "tools_used": tool_counts,
            "avg_outcome_delta": round(avg_outcome, 3),
            "total_duration_ms": round(total_duration, 0),
            "most_used": max(tool_counts, key=tool_counts.get) if tool_counts else None,
            "improved_calls": sum(1 for c in self._calls if c.outcome_delta > 0),
            "worsened_calls": sum(1 for c in self._calls if c.outcome_delta < 0),
        }

    @classmethod
    def load(cls, state_dir: str = "data") -> "ToolDotRecorder":
        recorder = cls(state_dir)
        json_path = recorder._json_path
        if json_path.exists():
            with open(json_path) as f:
                data = json.load(f)
            for d in data:
                recorder._calls.append(DotCall(
                    tool_name=d["tool"],
                    duration_ms=d.get("duration_ms", 0),
                    outcome_delta=d.get("outcome_delta", 0),
                    cycle=d.get("cycle", 0),
                ))
        return recorder


def dot_summary_for_agent(state_dir: str = "data") -> str:
    """Generate a text summary of DOT data for LLM context."""
    rec = ToolDotRecorder.load(state_dir)
    s = rec.summary()
    if s["calls"] == 0:
        return "No tool calls recorded yet."

    lines = [
        f"Tool Analytics: {s['calls']} calls across {len(s['tools_used'])} tools",
        f"  Most used: {s['most_used']} ({s['tools_used'].get(s['most_used'], 0)} calls)",
        f"  Improved: {s['improved_calls']} | Worsened: {s['worsened_calls']}",
        f"  Avg outcome delta: {s['avg_outcome_delta']}",
        f"  Total time: {s['total_duration_ms']:.0f}ms",
        "Usage:",
    ]
    for tool, count in sorted(s["tools_used"].items(), key=lambda x: -x[1]):
        lines.append(f"  {tool}: {count}")

    return "\n".join(lines)


if __name__ == "__main__":
    r = ToolDotRecorder()
    r.record("llm_call", 1200, 0.15)
    r.record("file_read", 340, 0.05)
    r.record("bash_cmd", 2500, -0.10)
    r.record("file_write", 890, 0.30)
    r.record("llm_call", 1400, 0.22)
    r.save()
    print("DOT strip saved")
    print(r.summary())
