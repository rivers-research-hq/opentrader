#!/usr/bin/env python3
"""TRADER.md Manager — self-documenting trading knowledge base.

The model writes, reads, and evolves its own trading playbook over time.
Coach reviews and ATDL lifecycle events distill patterns into persistent
lessons that get injected into every debate context.

File format:
  data/TRADER.md — markdown with sections, each entry timestamped.

Entry types:
  - PATTERN: Reproducible market behavior discovered
  - RULE: Hard-won risk management rule
  - EDGE: Statistical edge quantified from trade history
  - LESSON: Mistake learned and correction applied
  - REGIME: Market regime observation and adaptation
  - SKILL: Capability the model has developed at a specific cycle

The Coach appends entries during periodic reviews. ATDL adds during
MONITOR→PLAN transitions. The debate engine prepends the doc to context.
Over time conflicting entries are pruned and consolidated.
"""
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("opentrader.trader_md")

SECTION_HEADERS = {
    "PATTERN": "## Patterns — reproducible market behaviors",
    "RULE": "## Rules — hard-won risk management principles",
    "EDGE": "## Edges — quantified statistical advantages",
    "LESSON": "## Lessons — mistakes learned and corrections",
    "REGIME": "## Regime — market state observations",
    "SKILL": "## Skills — capabilities developed",
}

ENTRY_PRIORITY = {
    "PATTERN": 5,
    "RULE": 6,
    "EDGE": 4,
    "LESSON": 3,
    "REGIME": 2,
    "SKILL": 1,
}

MAX_ENTRIES_PER_SECTION = 15
MAX_TOTAL_ENTRIES = 60
MAX_TRADER_MD_CHARS = 8000  # keep context injection lean


@dataclass
class TraderEntry:
    etype: str
    cycle: int
    timestamp: str
    content: str
    confidence: float = 0.5
    source: str = "auto"

    def to_markdown(self) -> str:
        ts = self.timestamp[:19] if self.timestamp else ""
        return (
            f"- **[{self.etype}]** (c{self.cycle}, conf={self.confidence:.0%}): "
            f"{self.content}  _{ts}_\n"
        )


class TraderMD:
    """Manage the self-evolving TRADER.md trading knowledge base."""

    def __init__(self, state_dir: str = None):
        if state_dir is None:
            state_dir = str(Path(__file__).resolve().parent.parent / "data")
        self.path = Path(state_dir) / "TRADER.md"
        self.index_path = Path(state_dir) / "trader_index.json"
        self._entries: Dict[str, List[TraderEntry]] = {}
        self._load_or_init()

    def _load_or_init(self) -> None:
        if self.path.exists():
            self._parse_existing()
        else:
            self._init_fresh()

    def _init_fresh(self) -> None:
        self._entries = {k: [] for k in SECTION_HEADERS}
        self._save()

    def _parse_existing(self) -> None:
        self._entries = {k: [] for k in SECTION_HEADERS}
        content = self.path.read_text(encoding="utf-8", errors="replace")
        current_section = None

        for line in content.split("\n"):
            line = line.strip()

            for stype, header in SECTION_HEADERS.items():
                if line == header:
                    current_section = stype
                    break

            if current_section and line.startswith("- **"):
                match = re.match(
                    r"- \*\*\[(\w+)\]\*\* \(c(\d+), conf=(\d+)%\): (.*?)\s+_([^_]+)_\s*$",
                    line,
                )
                if match:
                    entry = TraderEntry(
                        etype=match.group(1),
                        cycle=int(match.group(2)),
                        timestamp=match.group(5).strip(),
                        content=match.group(4).strip(),
                        confidence=float(match.group(3)) / 100.0,
                    )
                    if current_section and current_section in self._entries:
                        self._entries[current_section].append(entry)

    def _save(self) -> None:
        parts = [
            "# TRADER.md — Autonomous Trading Knowledge Base",
            "",
            "> This document is written by the model itself. Coach reviews distill patterns;",
            "> ATDL lifecycle events capture lessons. It is injected into every debate cycle",
            "> as institutional memory. Pruned and consolidated automatically.",
            "",
            f"Last updated: {datetime.now(timezone.utc).isoformat()[:19]}Z",
            f"Total entries: {sum(len(v) for v in self._entries.values())}",
            "",
        ]
        for stype in ["PATTERN", "RULE", "EDGE", "LESSON", "REGIME", "SKILL"]:
            parts.append(SECTION_HEADERS[stype])
            if self._entries[stype]:
                for entry in sorted(self._entries[stype], key=lambda e: -e.confidence):
                    parts.append(entry.to_markdown())
            else:
                parts.append("*No entries yet — model will write lessons as it learns.*")
            parts.append("")

        self.path.write_text("\n".join(parts), encoding="utf-8")

        index = {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "total_entries": sum(len(v) for v in self._entries.values()),
            "breakdown": {k: len(v) for k, v in self._entries.items()},
        }
        self.index_path.write_text(json.dumps(index, indent=2))

    def add_entry(
        self,
        etype: str,
        cycle: int,
        content: str,
        confidence: float = 0.5,
        source: str = "coach",
    ) -> Optional[TraderEntry]:
        if etype not in SECTION_HEADERS:
            return None

        # Dedup: don't add if nearly identical content exists
        content_lower = content.lower()[:80]
        for existing in self._entries.get(etype, []):
            if content_lower in existing.content.lower()[:80]:
                if confidence > existing.confidence:
                    existing.confidence = confidence
                    existing.cycle = cycle
                    existing.timestamp = datetime.now(timezone.utc).isoformat()
                return existing

        entry = TraderEntry(
            etype=etype,
            cycle=cycle,
            timestamp=datetime.now(timezone.utc).isoformat(),
            content=content,
            confidence=confidence,
            source=source,
        )
        self._entries.setdefault(etype, []).append(entry)

        # Prune if over limit
        self._prune()
        self._save()
        logger.info(f"TRADER.md: added [{etype}] c{cycle} '{content[:60]}...'")
        return entry

    def _prune(self) -> None:
        for section in self._entries:
            if len(self._entries[section]) > MAX_ENTRIES_PER_SECTION:
                self._entries[section].sort(key=lambda e: -e.confidence)
                self._entries[section] = self._entries[section][:MAX_ENTRIES_PER_SECTION]

        total = sum(len(v) for v in self._entries.values())
        if total > MAX_TOTAL_ENTRIES:
            all_entries = []
            for section, entries in self._entries.items():
                for e in entries:
                    all_entries.append((section, e))
            all_entries.sort(key=lambda x: -x[1].confidence * ENTRY_PRIORITY.get(x[0], 1))
            keep = all_entries[:MAX_TOTAL_ENTRIES]
            new_entries: Dict[str, List[TraderEntry]] = {k: [] for k in SECTION_HEADERS}
            for section, entry in keep:
                new_entries[section].append(entry)
            self._entries = new_entries

    def to_context(self, max_chars: int = None) -> str:
        max_chars = max_chars or MAX_TRADER_MD_CHARS
        if not sum(len(v) for v in self._entries.values()):
            return ""

        lines = ["[MEMORY] Institutional trading knowledge (TRADER.md):\n"]
        remaining = max_chars - len(lines[0])

        for stype, header in SECTION_HEADERS.items():
            entries = self._entries.get(stype, [])
            if not entries:
                continue
            sorted_entries = sorted(entries, key=lambda e: -e.confidence)[:5]
            section_text = f"  {stype}S:\n"
            for e in sorted_entries:
                line = f"    - {e.content}\n"
                if len(line) > remaining:
                    break
                section_text += line
                remaining -= len(line)
            if len(section_text) > len(f"  {stype}S:\n"):
                lines.append(section_text)

        return "".join(lines)

    def get_stats(self) -> dict:
        return {
            "total_entries": sum(len(v) for v in self._entries.values()),
            "breakdown": {k: len(v) for k, v in self._entries.items()},
            "last_updated": self.index_path.exists() and json.loads(self.index_path.read_text()).get("last_updated", ""),
            "sections": {
                k: {
                    "count": len(v),
                    "avg_confidence": sum(e.confidence for e in v) / max(len(v), 1),
                    "latest_cycle": max((e.cycle for e in v), default=0),
                }
                for k, v in self._entries.items()
                if v
            },
        }


def distill_coach_report(report: dict, cycle: int) -> List[Tuple[str, str, float]]:
    """Extract TRADER.md entries from a Coach review report.

    Returns list of (entry_type, content, confidence) tuples.
    """
    entries = []
    grade = report.get("grade", "F")
    win_rate_pct = report.get("win_rate", 50)
    patterns = report.get("patterns", [])
    mistakes = report.get("mistakes", [])
    recommendations = report.get("recommendations", [])

    if grade in ("A", "B"):
        entries.append((
            "PATTERN",
            f"Portfolio earned grade {grade} with {win_rate_pct:.0f}% win rate at cycle {cycle}. "
            f"Strategy is working — preserve current risk parameters and debate configuration.",
            min(0.9, win_rate_pct / 100 + 0.1),
        ))

    for pattern in patterns[:3]:
        if isinstance(pattern, str) and len(pattern) > 10:
            entries.append(("PATTERN", pattern[:200], 0.6))
        elif isinstance(pattern, dict):
            desc = pattern.get("description", pattern.get("pattern", ""))
            conf = pattern.get("confidence", 0.5)
            if desc:
                entries.append(("PATTERN", str(desc)[:200], float(conf)))

    for mistake in mistakes[:3]:
        if isinstance(mistake, str) and len(mistake) > 5:
            entries.append(("LESSON", f"Mistake identified: {mistake[:200]}. "
                                     f"Coach recommends avoiding this pattern.", 0.7))
        elif isinstance(mistake, dict):
            desc = mistake.get("description", mistake.get("mistake", ""))
            if desc:
                entries.append(("LESSON", str(desc)[:200], 0.7))

    for rec in recommendations[:3]:
        if isinstance(rec, str) and len(rec) > 5:
            entries.append(("RULE", rec[:200], 0.65))
        elif isinstance(rec, dict):
            desc = rec.get("description", rec.get("rule", rec.get("recommendation", "")))
            if desc:
                entries.append(("RULE", str(desc)[:200], 0.65))

    if grade in ("D", "F"):
        entries.append((
            "LESSON",
            f"Portfolio earned failing grade {grade} with {win_rate_pct:.0f}% win rate. "
            f"Current strategy is NOT working — retraining or parameter adjustment needed.",
            0.85,
        ))

    return entries


def distill_atdl_action(action: dict, cycle: int) -> List[Tuple[str, str, float]]:
    """Extract TRADER.md entries from an ATDL lifecycle action."""
    entries = []
    phase = action.get("phase", "")
    focus = action.get("focus", "")

    if phase == "MONITOR" and action.get("triggered"):
        entries.append((
            "REGIME",
            f"ATDL detected performance drift at cycle {cycle}. "
            f"Triggering PLAN phase for strategy review. Focus: {focus[:100] if focus else 'general improvement'}.",
            0.75,
        ))

    if phase == "DEPLOY" and action.get("promoted"):
        entries.append((
            "SKILL",
            f"New model adapter promoted to production at cycle {cycle}. "
            f"{action.get('reason', 'Performance improvement')[:100]}",
            0.8,
        ))

    if phase == "ITERATE":
        learnings = action.get("learnings", "")
        if learnings:
            entries.append((
                "LESSON",
                f"ATDL iteration learning: {str(learnings)[:200]}",
                0.7,
            ))

    return entries
