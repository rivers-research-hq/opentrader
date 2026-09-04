"""Shared bug-detection logic for the bug-bounty benchmark.

Single source of truth for "did the agent find a seeded bug". Used by both
run_matrix.py (for early-exit while the agent runs) and score.py (for the
final comparison table).

Primary measure: DEMONSTRATED EVIDENCE. An agent has found a bug when it cites
its file, its function, or the keywords that identify it (e.g. dropna(axis=1),
the missing cutoff filter). The hunt prompt contains none of these strings
(verified), so any citation in a transcript comes from the agent actually
reading the code — that is the honest "did it find it" signal.

Secondary measure (informational): REPORT LINES. Whether the agent emitted the
requested FOUNDBUG <id>: <file>:<function> format. This is a discipline/format
check, not a finding check — a run that never reports properly but demonstrates
the bug in its reasoning still found it.
"""
import json
import re


def load_ground(manifest_path):
    """Return {bug_id: {"file", "function", "keywords": [...]}} from manifest."""
    bugs = json.loads(open(manifest_path).read())["bugs"]
    ground = {}
    for b in bugs:
        ground[b["id"]] = {
            "file": b.get("file", ""),
            "function": b.get("function", ""),
            "keywords": [k.lower() for k in b.get("keywords", [])],
        }
    return ground


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _has_any(text_lower: str, needles) -> bool:
    return any(n in text_lower for n in needles)


# A real report line looks like:
#   FOUNDBUG rank-dead: setup_search/engine.py:_cross_sectional_rank - root cause
# It names a bug id AND a file:function. Planning text like "emit the final
# FOUNDBUG rank-dead line" names only the id and must NOT count as a report.
REPORT_LINE = re.compile(
    r"FOUNDBUG\s+([A-Za-z0-9_-]+)\s*:\s*[^\s:]+\.[A-Za-z0-9_]+"
    r":[A-Za-z0-9_\.]+",
    re.IGNORECASE,
)


def _evidence_hits(low: str, info: dict) -> int:
    """Count how many distinct identifiers the agent cited for a bug.

    Function name = 2 (strongest), file basename = 1, each keyword = 1.
    """
    hits = 0
    nfile, nfunc = _norm(info["file"]), _norm(info["function"])
    if nfunc and nfunc in low:
        hits += 2
    if nfile and (nfile in low or nfile.split("/")[-1] in low):
        hits += 1
    for kw in info["keywords"]:
        if kw in low:
            hits += 1
    return hits


def scan_transcript(text: str, ground: dict) -> dict:
    """Return {bug_id: confidence} for each bug found in a transcript.

    confidence in {"evidence", "report"}:
      evidence = agent cited the bug's file/function/keywords (found it).
      report   = agent also emitted a properly-formatted FOUNDBUG line.
    report implies evidence.
    """
    found = {}
    low = text.lower()
    report_claims = {_norm(m.group(1)) for m in REPORT_LINE.finditer(text)}

    for bug_id, info in ground.items():
        hits = _evidence_hits(low, info)
        if hits < 3:
            continue
        n_id = _norm(bug_id)
        reported = any(_norm(h) == n_id or n_id in _norm(h) or _norm(h) in n_id
                       for h in report_claims)
        found[bug_id] = "report" if reported else "evidence"
    return found


def all_found(found: dict, ground: dict) -> bool:
    """True when every ground-truth bug has been demonstrated (evidence or
    better). Evidence is the completion criterion for the runner."""
    return all(bid in found for bid in ground)


def report_lines(text: str) -> int:
    """How many properly-formatted FOUNDBUG report lines the agent emitted."""
    return len(REPORT_LINE.findall(text))


def false_positives(text: str, ground: dict) -> int:
    """Number of report-line claims that match no ground-truth bug id."""
    valid = {_norm(v) for v in ground.keys()}
    claims = {_norm(m.group(1)) for m in REPORT_LINE.finditer(text)}
    fp = 0
    for c in claims:
        if not any(c == v or c in v or v in c for v in valid):
            fp += 1
    return fp
