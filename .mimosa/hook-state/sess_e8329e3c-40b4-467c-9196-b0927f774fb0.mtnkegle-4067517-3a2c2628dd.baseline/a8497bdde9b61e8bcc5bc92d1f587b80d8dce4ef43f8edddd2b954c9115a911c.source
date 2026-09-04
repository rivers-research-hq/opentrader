#!/usr/bin/env python3
"""Model evaluation and deployment gating using DeepEval (7-dimension scoring).

Evaluates candidate models against the active model. Promotes if candidate
deep_eval weighted_score >= active deep_eval score + 3.0.

Usage:
    python -m training.eval_deploy evaluate <version>
    python -m training.eval_deploy promote <version>
    python -m training.eval_deploy auto
    python -m training.eval_deploy status
"""
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s [eval_deploy] %(levelname)s %(message)s")
logger = logging.getLogger("eval_deploy")

PROJECT = Path(__file__).resolve().parent.parent
EVAL_DIR = PROJECT / "data" / "eval"
REPORTS_DIR = EVAL_DIR / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def load_registry() -> Dict:
    with open(PROJECT / "data" / "adapter_registry.json") as f:
        return json.load(f)


def save_registry(reg: Dict):
    with open(PROJECT / "data" / "adapter_registry.json", "w") as f:
        json.dump(reg, f, indent=2)


def _resolve_base_gguf(base_model_name: str) -> Path:
    """Resolve base model name to absolute GGUF path."""
    candidates = [
        Path("/home/mrc/models") / base_model_name,
        Path("/home/mrc/models") / base_model_name / base_model_name,
        Path("/home/mrc/models/qwen2.5-7b-instruct") / base_model_name,
    ]
    for c in candidates:
        if c.exists():
            return c
    matches = list(Path("/home/mrc/models").rglob(base_model_name))
    if matches:
        return matches[0]
    raise FileNotFoundError(f"Base model GGUF not found for: {base_model_name}")


def get_latest_deep_report(version: str) -> Optional[dict]:
    """Load the latest deep_eval report for a version."""
    reports = sorted(
        REPORTS_DIR.glob(f"{version}_deep_*.json"),
        key=os.path.getmtime, reverse=True,
    )
    if not reports:
        return None
    with open(reports[0]) as f:
        return json.load(f)


def evaluate_candidate(version: str, port: int = 5805) -> Optional[float]:
    """Run DeepEval 7-dimension evaluation on candidate model.

    Returns weighted_score or None on failure.
    """
    logger.info(f"DeepEval evaluating {version}...")

    reg = load_registry()
    if version not in reg:
        logger.error(f"{version} not in registry")
        return None

    entry = reg[version]
    base_name = entry.get("base_model", "")
    gguf_rel = entry.get("gguf_path", "")

    if not base_name:
        logger.error(f"{version} missing base_model in registry")
        return None

    try:
        base_gguf = _resolve_base_gguf(base_name)
    except FileNotFoundError as e:
        logger.error(f"Base model resolution failed: {e}")
        return None

    lora_gguf = str(PROJECT / gguf_rel) if gguf_rel else None

    from training.deep_eval import DeepEval, save_report
    evaluator = DeepEval(version=version, base_gguf=str(base_gguf),
                          lora_gguf=lora_gguf, port=port, connect_only=True)

    with evaluator:
        report = evaluator.run()

    save_report(report)

    reg[version]["eval_score"] = report.weighted_score
    save_registry(reg)

    logger.info(f"{version}: deep_eval={report.weighted_score}")
    return report.weighted_score


def get_active_deep_score() -> Tuple[str, float]:
    """Get active adapter and its deep_eval weighted_score."""
    reg = load_registry()
    for v, entry in reg.items():
        if entry.get("status") == "active":
            report = get_latest_deep_report(v)
            if report:
                return v, report["weighted_score"]
            return v, entry.get("eval_score", 0.0)
    return "none", 0.0


def should_promote(candidate_version: str, candidate_score: float) -> Tuple[bool, str]:
    """Check if candidate should be promoted. Needs >=3.0 over active's deep_eval."""
    active_version, active_score = get_active_deep_score()
    if active_version == candidate_version:
        return False, f"{candidate_version} is already active"

    if candidate_score <= 0:
        return False, f"Score {candidate_score} is zero or negative"

    required = active_score + 3.0
    if candidate_score >= required:
        return True, (f"{candidate_version} score {candidate_score} >= "
                      f"{active_version} score {active_score} + 3.0")
    else:
        return False, (f"{candidate_version} score {candidate_score} < "
                       f"{active_version} score {active_score} + 3.0 = {required}")


def promote_candidate(version: str) -> bool:
    """Promote a version to active (only if deep_eval passed)."""
    report = get_latest_deep_report(version)
    if not report:
        logger.error(f"No deep_eval report for {version}")
        return False

    score = report["weighted_score"]
    should, reason = should_promote(version, score)
    if not should:
        logger.warning(f"Promotion blocked: {reason}")
        return False

    reg = load_registry()
    for v, entry in reg.items():
        if entry.get("status") == "active":
            entry["status"] = "replaced"
    if version in reg:
        reg[version]["status"] = "active"
        reg[version]["eval_score"] = score
    else:
        logger.error(f"{version} not in registry")
        return False
    save_registry(reg)

    _update_llama_dynamic_script(version)

    logger.info(f"Promoted {version}: deep_eval={score}, {reason}")
    return True


def _update_llama_dynamic_script(version: str):
    """Point llama-dynamic-ptolemy at the promoted model's GGUF files."""
    reg = load_registry()
    entry = reg.get(version)
    if not entry:
        logger.warning(f"Cannot update script: {version} not in registry")
        return

    base_name = entry.get("base_model", "")
    gguf_rel = entry.get("gguf_path", "")

    script = Path("/home/mrc/.local/bin/llama-dynamic-ptolemy")
    if not script.exists():
        logger.warning(f"llama-dynamic-ptolemy not found")
        return

    content = script.read_text()

    try:
        base_gguf = _resolve_base_gguf(base_name)
        content = re.sub(r'^MODEL=".*"', f'MODEL="{base_gguf}"', content, flags=re.MULTILINE)
    except FileNotFoundError:
        logger.warning(f"Cannot resolve base GGUF: {base_name}")

    if gguf_rel:
        lora_path = PROJECT / gguf_rel
        content = re.sub(r'^LORA=".*"', f'LORA="{lora_path}"', content, flags=re.MULTILINE)

    content = re.sub(r'--alias\s+\S+', f'--alias {version}', content)

    script.write_text(content)
    logger.info(f"Updated llama-dynamic-ptolemy for {version}")

    _reload_llama_swap()


def _reload_llama_swap():
    """Send SIGHUP to llama-swap process to reload."""
    import subprocess
    try:
        result = subprocess.run(
            ["pgrep", "-f", "llama-swap"],
            capture_output=True, text=True, timeout=5,
        )
        pids = result.stdout.strip().split()
        for pid in pids:
            if pid:
                subprocess.run(["kill", "-SIGHUP", pid], capture_output=True, timeout=5)
                logger.info(f"llama-swap reloaded (PID {pid})")
    except Exception as e:
        logger.warning(f"llama-swap reload failed: {e}")


def evaluate_all_candidates() -> Optional[str]:
    """DeepEval all non-active candidates. Returns best version or None."""
    reg = load_registry()
    candidates = [v for v, e in reg.items() if e.get("status") != "active"]

    if not candidates:
        logger.info("No candidates to evaluate")
        return None

    best_version = None
    best_score = -1.0

    for version in candidates:
        report = get_latest_deep_report(version)
        if report and report.get("timestamp", "").startswith(
                datetime.now(timezone.utc).strftime("%Y%m%d")):
            score = report["weighted_score"]
            logger.info(f"{version}: using existing deep_eval score={score}")
        else:
            score = evaluate_candidate(version)
            if score is None:
                continue

        if score > best_score:
            best_score = score
            best_version = version

    if best_version:
        active_v, active_s = get_active_deep_score()
        if best_score >= active_s + 3.0:
            logger.info(f"Best: {best_version} ({best_score}) beats {active_v} ({active_s}) by >=3.0")
            return best_version

    return None


def auto():
    """Full auto cycle: DeepEval candidates, promote best if it beats active by >=3.0."""
    best = evaluate_all_candidates()
    if best:
        promote_candidate(best)
    else:
        logger.info("No candidate beats active by >=3.0 -- keeping current")


def cli():
    import argparse
    parser = argparse.ArgumentParser(description="DeepEval model evaluation and deployment gating")
    parser.add_argument("action", nargs="?", default="status",
                        choices=["evaluate", "promote", "auto", "status"])
    parser.add_argument("version", nargs="?", help="Model version to evaluate/promote")
    parser.add_argument("--port", type=int, default=5805, help="llama-server port")
    args = parser.parse_args()

    if args.action == "status":
        active_v, active_s = get_active_deep_score()
        print(f"Active: {active_v} (deep_eval={active_s})")
        reg = load_registry()
        for v, e in reg.items():
            report = get_latest_deep_report(v)
            ds = report["weighted_score"] if report else e.get("eval_score", "N/A")
            print(f"  {v}: {e['status']} deep_eval={ds}")
        return

    if args.action == "evaluate":
        if not args.version:
            print("Usage: eval_deploy evaluate <version>")
            sys.exit(1)
        score = evaluate_candidate(args.version, port=args.port)
        if score is not None:
            print(f"DeepEval {args.version}: weighted_score={score}")
        else:
            sys.exit(1)
        return

    if args.action == "promote":
        if not args.version:
            print("Usage: eval_deploy promote <version>")
            sys.exit(1)
        ok = promote_candidate(args.version)
        print("OK" if ok else "BLOCKED")
        return

    if args.action == "auto":
        auto()


if __name__ == "__main__":
    cli()
