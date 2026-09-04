#!/usr/bin/env python3
"""Opencode episode recorder — captures agent runs to JSONL for RL training.

Runs as a post-session hook or inline wrapper. Parses opencode output for:
  - Agent identity (builder, qwen-worker, manager)
  - Tool calls (read, write, edit, bash, glob, grep)
  - Compile/test results (python3 -m py_compile, pytest)
  - Loop detection (repeated actions from same agent)
  - Task completion (did agent finish within step limit?)

Writes structured episodes to data/opencode_episodes.jsonl which the
CodingRLTrainer consumes as training data.

Usage:
  # As post-session analyzer:
  python3 training/opencode_episode_recorder.py --session-dir ~/.opencode/recent

  # As inline wrapper:
  python3 training/opencode_episode_recorder.py --wrap -- opencode "fix the bug"

  # Or import and use programmatically:
  from training.opencode_episode_recorder import OpencodeEpisodeRecorder
  recorder = OpencodeEpisodeRecorder()
  recorder.start_session()
  # ... opencode runs ...
  episodes = recorder.end_session()
"""

import json
import logging
import os
import re
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("opentrader.episodes")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATE_DIR = PROJECT_ROOT / "data"
EPISODES_FILE = "opencode_episodes.jsonl"


@dataclass
class Episode:
    """One agent run captured as a training episode."""
    agent: str = ""
    task: str = ""
    status: str = "unknown"       # success | error | timeout | loop
    files_touched: list = field(default_factory=list)
    compile_passed: bool = False
    test_passed: bool = False
    errors: list = field(default_factory=list)
    steps_used: int = 0
    steps_limit: int = 0
    actions: list = field(default_factory=list)        # list of action strings
    dominant_action: str = ""
    action_diversity: float = 1.0
    duration_s: float = 0.0
    timestamp: str = ""
    raw_actions: list = field(default_factory=list)    # full tool call records
    reward: float = 0.0


class OpencodeEpisodeRecorder:
    """Captures agent episode data during opencode sessions.

    Parses terminal output for:
      - Agent transitions (builder → qwen-worker → ...)
      - Tool call patterns (read, write, edit, bash, glob, grep, task)
      - Compile results (python3 -m py_compile)
      - Loop indicators (same action repeated >80%)

    Dual mode:
      1. Parse existing session logs from a directory
      2. Run opencode as a subprocess and capture output inline
    """

    ACTION_PATTERNS = {
        "read": re.compile(r"\b(Read|read|reading)\b.*\b(\S+\.py|\S+\.json|\S+\.md)\b", re.I),
        "write": re.compile(r"\b(Write|write|writing|wrote)\b", re.I),
        "edit": re.compile(r"\b(Edit|edit|editing|edited)\b", re.I),
        "bash": re.compile(r"\b(Bash|bash|running|run)\b", re.I),
        "glob": re.compile(r"\b(Glob|glob|globbed)\b", re.I),
        "grep": re.compile(r"\b(Grep|grep|grepped)\b", re.I),
        "task": re.compile(r"\b(task|delegate|delegat|subagent)\b", re.I),
        "compile": re.compile(r"(py_compile|SyntaxError|compil\w+|PASS|FAIL)", re.I),
        "test": re.compile(r"(pytest|unittest|test.*PASS|test.*FAIL|ran \d+ tests)", re.I),
    }

    AGENT_PATTERNS = re.compile(
        r"(builder|qwen-worker|manager|architect|supervisor|modelfixer|technician)",
        re.I,
    )

    def __init__(self, state_dir: str = None, max_episodes_per_file: int = 500):
        self.state_dir = Path(state_dir or DEFAULT_STATE_DIR)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.episodes_path = self.state_dir / EPISODES_FILE
        self.max_episodes = max_episodes_per_file

        self._current_agent: str = ""
        self._current_actions: List[dict] = []
        self._current_files: set = set()
        self._start_time: float = 0.0
        self._session_episodes: List[Episode] = []
        self._compile_passed: Optional[bool] = None
        self._test_passed: Optional[bool] = None
        self._errors: List[str] = []

    # ── Public API ─────────────────────────────────────────────

    def start_session(self) -> None:
        self._start_time = time.time()
        self._session_episodes = []
        logger.info("Episode recorder: session started")

    def end_session(self) -> List[Episode]:
        """Finalize current episode and return all session episodes."""
        if self._current_actions:
            ep = self._finalize_episode()
            if ep:
                self._session_episodes.append(ep)
                self._write_episode(ep)

        duration = time.time() - self._start_time
        logger.info(
            f"Episode recorder: session ended — {len(self._session_episodes)} "
            f"episodes in {duration:.1f}s"
        )
        return self._session_episodes

    def parse_log_file(self, log_path: str) -> List[Episode]:
        """Parse a session log file and extract episodes.

        Handles opencode terminal output saved to a file.
        Returns list of extracted Episode objects.
        """
        episodes = []
        current_agent = ""
        current_actions = []
        current_files = set()
        compile_passed = None
        test_passed = None
        errors = []
        episode_start = time.time()

        try:
            with open(log_path) as f:
                lines = f.readlines()
        except Exception as e:
            logger.warning(f"Could not read log file {log_path}: {e}")
            return []

        for line in lines:
            # Detect agent transitions
            agent_match = self.AGENT_PATTERNS.search(line)
            if agent_match and not line.strip().startswith(("builder", "qwen-worker")):
                new_agent = agent_match.group(1).lower()
                if new_agent != current_agent:
                    if current_actions and current_agent:
                        ep = self._build_episode(
                            agent=current_agent,
                            actions=current_actions,
                            files=current_files,
                            compile_passed=compile_passed,
                            test_passed=test_passed,
                            errors=errors,
                            start_time=episode_start,
                        )
                        if ep:
                            episodes.append(ep)
                            self._write_episode(ep)
                    current_agent = new_agent
                    current_actions = []
                    current_files = set()
                    compile_passed = None
                    test_passed = None
                    errors = []
                    episode_start = time.time()

            # Parse tool calls
            for action_type, pattern in self.ACTION_PATTERNS.items():
                m = pattern.search(line)
                if m:
                    current_actions.append({
                        "type": action_type,
                        "detail": m.group(0),
                        "time": datetime.now(timezone.utc).isoformat(),
                    })
                    # Extract file paths from read/edit/write
                    if action_type in ("read", "write", "edit"):
                        file_match = re.search(r"([\w./-]+\.(?:py|json|md|yaml|yml|toml|cfg|ini))", line)
                        if file_match:
                            current_files.add(file_match.group(1))

            # Detect compile results
            if "py_compile" in line:
                compile_passed = "FAIL" not in line and "error" not in line.lower()
            if re.search(r"Syntax\s*Error", line) or "Traceback" in line:
                errors.append(line.strip()[:200])
                compile_passed = False  # compile failed

            # Detect test results
            if re.search(r"PASS", line) and "test" in line.lower():
                test_passed = True
            elif re.search(r"FAIL", line) and "test" in line.lower():
                test_passed = False

        # Finalize last episode
        if current_actions and current_agent:
            ep = self._build_episode(
                agent=current_agent,
                actions=current_actions,
                files=current_files,
                compile_passed=compile_passed,
                test_passed=test_passed,
                errors=errors,
                start_time=episode_start,
            )
            if ep:
                episodes.append(ep)
                self._write_episode(ep)

        self._session_episodes.extend(episodes)
        return episodes

    def get_recent_episodes(self, n: int = 50) -> List[Episode]:
        """Load the most recent N episodes from the JSONL file."""
        episodes = []
        path = self.episodes_path
        if not path.exists():
            return episodes
        try:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            data = json.loads(line)
                            episodes.append(Episode(**data))
                        except Exception:
                            continue
        except Exception:
            pass
        return episodes[-n:]

    def episode_count(self) -> int:
        """Count episodes in JSONL store."""
        if not self.episodes_path.exists():
            return 0
        try:
            return sum(1 for _ in open(self.episodes_path))
        except Exception:
            return 0

    # ── Internal ───────────────────────────────────────────────

    def _build_episode(self, agent: str, actions: List[dict], files: set,
                       compile_passed: Optional[bool], test_passed: Optional[bool],
                       errors: List[str], start_time: float) -> Optional[Episode]:
        """Construct an Episode from captured data."""
        if not actions:
            return None

        action_types = [a["type"] for a in actions]
        action_counts = Counter(action_types)
        if action_counts:
            dominant_action = action_counts.most_common(1)[0][0]
        else:
            dominant_action = "unknown"

        # Compute action diversity (entropy)
        total = len(action_types)
        entropy = 0.0
        for count in action_counts.values():
            p = count / max(total, 1)
            if p > 0:
                entropy -= p * (__import__("math").log(p))
        max_entropy = __import__("math").log(len(self.ACTION_PATTERNS))
        diversity = min(1.0, entropy / max_entropy) if max_entropy > 0 else 1.0

        # Detect loop: >80% of actions are the same type
        dominant_ratio = action_counts[dominant_action] / max(total, 1)
        is_loop = dominant_ratio >= 0.80 and total >= 10

        # Determine status
        if is_loop:
            status = "loop"
        elif errors and compile_passed is False:
            status = "error"
        elif compile_passed:
            status = "success"
        else:
            status = "unknown"

        duration = time.time() - start_time

        # Compute coding reward for this episode
        reward = self._compute_episode_reward(
            compile_passed=compile_passed,
            test_passed=test_passed,
            is_loop=is_loop,
            diversity=diversity,
            action_count=total,
            status=status,
        )

        episode = Episode(
            agent=agent,
            task="",
            status=status,
            files_touched=list(files)[:10],
            compile_passed=bool(compile_passed),
            test_passed=bool(test_passed),
            errors=errors[:5],
            steps_used=total,
            steps_limit=25,  # typical opencode step limit
            actions=action_types,
            dominant_action=dominant_action,
            action_diversity=round(diversity, 4),
            duration_s=round(duration, 2),
            timestamp=datetime.now(timezone.utc).isoformat(),
            raw_actions=actions[:20],
            reward=round(reward, 4),
        )

        return episode

    def _finalize_episode(self) -> Optional[Episode]:
        """Finalize the current in-progress episode."""
        return self._build_episode(
            agent=self._current_agent or "unknown",
            actions=self._current_actions,
            files=self._current_files,
            compile_passed=self._compile_passed,
            test_passed=self._test_passed,
            errors=self._errors,
            start_time=self._start_time,
        )

    @staticmethod
    def _compute_episode_reward(
        compile_passed: Optional[bool],
        test_passed: Optional[bool],
        is_loop: bool,
        diversity: float,
        action_count: int,
        status: str,
    ) -> float:
        """Compute a composite coding reward for a single episode.

        Uses the same weighted structure as coding_composite_reward
        but operates on per-episode signals.
        """
        reward = 0.0

        # Compile: strong positive signal
        if compile_passed is True:
            reward += 0.40
        elif compile_passed is False:
            reward -= 0.30

        # Tests: additional positive signal
        if test_passed is True:
            reward += 0.20
        elif test_passed is False:
            reward -= 0.15

        # Loop penalty
        if is_loop:
            reward -= 0.25

        # Diversity bonus
        reward += 0.15 * diversity

        # Efficiency: more actions = more context used = less efficient
        if action_count > 20:
            reward -= 0.10
        elif action_count <= 5:
            reward += 0.05

        # Success bonus
        if status == "success":
            reward += 0.05

        return max(-1.0, min(1.0, reward))

    def _write_episode(self, episode: Episode) -> None:
        """Append an episode to the JSONL file. Rotates if too large."""
        try:
            # Check rotation
            if self.episode_count() >= self.max_episodes:
                archive = self.episodes_path.with_suffix(".jsonl.old")
                if archive.exists():
                    archive.unlink()
                if self.episodes_path.exists():
                    self.episodes_path.rename(archive)
                logger.info(f"Episode file rotated: {self.episode_count()} → {archive}")

            data = asdict(episode)
            with open(self.episodes_path, "a") as f:
                f.write(json.dumps(data) + "\n")
        except Exception as e:
            logger.warning(f"Could not write episode: {e}")


# ── CLI ────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Record opencode agent episodes for RL training"
    )
    parser.add_argument(
        "--parse-log", type=str, help="Parse an existing session log file"
    )
    parser.add_argument(
        "--state-dir", type=str, default=str(DEFAULT_STATE_DIR),
        help="State directory for episode storage"
    )
    parser.add_argument(
        "--wrap", nargs=argparse.REMAINDER,
        help="Wrap an opencode command: -- -- opencode \"fix the bug\""
    )
    parser.add_argument(
        "--stats", action="store_true",
        help="Show episode statistics"
    )
    parser.add_argument(
        "--export", action="store_true",
        help="Export recent episodes for CodingRLTrainer consumption"
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Verbose logging"
    )
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )

    recorder = OpencodeEpisodeRecorder(state_dir=args.state_dir)

    if args.stats:
        episodes = recorder.get_recent_episodes(50)
        print(f"Total episodes stored: {recorder.episode_count()}")
        print(f"Recent ({len(episodes)}):")
        success = sum(1 for e in episodes if e.status == "success")
        errors = sum(1 for e in episodes if e.status == "error")
        loops = sum(1 for e in episodes if e.status == "loop")
        print(f"  success={success} error={errors} loop={loops}")
        by_agent = Counter(e.agent for e in episodes)
        for agent, count in by_agent.most_common():
            print(f"  {agent}: {count}")
        return

    if args.export:
        episodes = recorder.get_recent_episodes(50)
        # Export as code_diffs format for agent_state.json
        diffs = []
        for ep in episodes:
            diffs.append({
                "file": ep.files_touched[0] if ep.files_touched else "unknown",
                "action": ep.dominant_action.upper(),
                "reason": f"{ep.status} ({ep.compile_passed})",
                "test_pass_rate": 1.0 if ep.compile_passed else 0.0,
                "bugs_introduced": len(ep.errors),
                "review_score": ep.reward * 5.0,  # scale to 0-5
                "agent": ep.agent,
                "status": ep.status,
                "duration_s": ep.duration_s,
            })
        print(json.dumps(diffs, indent=2))
        # Also write to agent_state.json for CodingRLTrainer
        agent_path = Path(args.state_dir) / "agent_state.json"
        existing = {}
        if agent_path.exists():
            try:
                existing = json.loads(agent_path.read_text()) or {}
            except Exception:
                pass
        existing["code_diffs"] = diffs
        existing["_signal_history"] = [
            {"action": ep.dominant_action.upper(), "reason": f"{ep.status}"}
            for ep in episodes
        ]
        agent_path.parent.mkdir(parents=True, exist_ok=True)
        agent_path.write_text(json.dumps(existing, indent=2))
        print(f"Exported {len(diffs)} code_diffs to {agent_path}")
        return

    if args.parse_log:
        episodes = recorder.parse_log_file(args.parse_log)
        print(f"Parsed {len(episodes)} episodes from {args.parse_log}")
        for ep in episodes[-5:]:
            print(f"  {ep.agent}: {ep.status} (compile={ep.compile_passed}) [{len(ep.actions)} actions]")
        return

    if args.wrap:
        # Run opencode as subprocess
        cmd = args.wrap
        if not cmd:
            print("Usage: opencode_episode_recorder.py --wrap -- opencode [args...]")
            sys.exit(1)
        recorder.start_session()
        try:
            proc = subprocess.run(cmd, capture_output=False, cwd=str(PROJECT_ROOT))
            episodes = recorder.end_session()
            print(f"\n[Episode recorder] Captured {len(episodes)} episodes.")
        except KeyboardInterrupt:
            episodes = recorder.end_session()
        return

    parser.print_help()


if __name__ == "__main__":
    main()
