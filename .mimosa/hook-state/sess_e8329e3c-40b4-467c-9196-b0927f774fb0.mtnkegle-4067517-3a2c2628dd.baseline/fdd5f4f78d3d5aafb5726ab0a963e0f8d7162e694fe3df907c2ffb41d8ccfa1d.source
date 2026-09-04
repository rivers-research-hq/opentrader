#!/usr/bin/env python3
"""Research Runner — autonomous research sweep without requiring an LLM.

Sweeps:
  1. arXiv API (q-fin.TR, q-fin.CP, q-fin.RM, cs.LG, cs.AI) for recent papers
  2. HuggingFace Hub API for trending models/datasets matching trading keywords

For each finding, uses keyword-based heuristic scoring (no LLM needed) to assign:
  - capability category (regime_detection, risk_management, trade_signal, etc.)
  - relevance score (0-1 based on keyword match density)
  - actionable flag (True if relevance > 0.4)

Writes capability manifest to data/research/capability_manifest_{ts}.json
Then calls capability_distiller.distill_all() to process it.

Intended to be called from the harness cycle when idle (training not needed).
"""
import json
import logging
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from xml.etree import ElementTree

logger = logging.getLogger("opentrader.research_runner")

STATE_DIR = Path(__file__).resolve().parent.parent / "data"
RESEARCH_DIR = STATE_DIR / "research"

ARXIV_CATEGORIES = ["q-fin.TR", "q-fin.CP", "q-fin.RM", "q-fin.GN", "q-fin.MF", "q-fin.PR", "q-fin.ST"]
ARXIV_MAX_RESULTS = 50
ARXIV_EXTRA_QUERY = " OR (cat:cs.LG AND (abs:trading OR abs:portfolio OR abs:market OR abs:crypto OR abs:bitcoin OR abs:financial))"
ARXIV_BASE = "http://export.arxiv.org/api/query"

HF_BASE = "https://huggingface.co/api"
HF_SEARCH_TERMS = ["trading", "financial", "market", "quantitative", "portfolio"]
HF_MAX_PER_TERM = 10

CAPABILITY_KEYWORDS = {
    "regime_detection": [
        "regime", "market regime", "volatility regime", "trend detection",
        "structural break", "market state", "hmm", "hidden markov",
    ],
    "risk_management": [
        "risk management", "position sizing", "stop loss", "drawdown",
        "var", "value at risk", "portfolio risk", "exposure", "hedging",
        "risk parity", "volatility targeting",
    ],
    "trade_signal": [
        "trading signal", "buy sell", "entry signal", "technical indicator",
        "momentum", "mean reversion", "breakout", "signal generation",
        "alpha", "factor model",
    ],
    "multi_step_reasoning": [
        "multi-step", "chain of thought", "reasoning", "planning",
        "sequential decision", "lookahead", "strategic reasoning",
    ],
    "sentiment_analysis": [
        "sentiment", "news sentiment", "social media", "twitter",
        "market sentiment", "nlp sentiment", "opinion mining",
    ],
    "data_augmentation": [
        "data augmentation", "synthetic data", "gan", "vae",
        "market simulation", "price generation",
    ],
    "eval_methodology": [
        "backtest", "walk forward", "out of sample", "benchmark",
        "evaluation", "performance metric", "sharpe", "sortino",
    ],
    "training_technique": [
        "fine-tuning", "lora", "qlora", "dpo", "rlhf", "reinforcement learning",
        "grpo", "ppo", "preference learning", "reward model",
    ],
    "inference_efficiency": [
        "quantization", "distillation", "pruning", "inference",
        "fast", "efficient", "onnx", "gguf",
    ],
}

HIGH_VALUE_TERMS = {
    "crypto", "bitcoin", "ethereum", "altcoin", "defi",
    "order flow", "liquidity", "order book", "microstructure",
    "alpha", "sharpe", "drawdown", "position sizing",
}


def _score_finding(text: str, title: str = "") -> tuple:
    """Score a finding's relevance and determine capability.

    Returns (capability, relevance, actionable).
    """
    combined = f"{title} {text}".lower()
    best_cap = "trade_signal"
    best_score = 0.0

    for cap, keywords in CAPABILITY_KEYWORDS.items():
        matches = sum(1 for kw in keywords if kw in combined)
        if matches == 0:
            continue
        # Score = match density * normalization
        density = matches / max(len(keywords), 1)
        bonus = 0.1 * matches  # raw match bonus
        score = min(density + bonus, 1.0)
        if score > best_score:
            best_score = score
            best_cap = cap

    # Boost for high-value trading terms
    hv_matches = sum(1 for term in HIGH_VALUE_TERMS if term in combined)
    best_score = min(best_score + 0.05 * hv_matches, 1.0)

    actionable = best_score >= 0.4
    return best_cap, round(best_score, 3), actionable


def search_arxiv(max_results: int = ARXIV_MAX_RESULTS) -> List[dict]:
    """Search arXiv for recent papers in relevant categories."""
    cat_query = " OR ".join(f"cat:{cat}" for cat in ARXIV_CATEGORIES)
    cat_query += ARXIV_EXTRA_QUERY
    params = urllib.parse.urlencode({
        "search_query": cat_query,
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    })
    url = f"{ARXIV_BASE}?{params}"

    findings = []
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "OpenTrader-Research/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            xml_data = resp.read()

        ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
        root = ElementTree.fromstring(xml_data)

        for entry in root.findall("atom:entry", ns):
            title = entry.findtext("atom:title", "", ns).strip().replace("\n", " ")
            summary = entry.findtext("atom:summary", "", ns).strip().replace("\n", " ")
            id_url = entry.findtext("atom:id", "", ns).strip()
            published = entry.findtext("atom:published", "", ns).strip()

            # Filter by relevance to trading
            cap, relevance, actionable = _score_finding(summary, title)
            if relevance < 0.15:
                continue

            findings.append({
                "source": "arxiv",
                "title": title[:200],
                "url": id_url,
                "summary": summary[:500],
                "capability": cap,
                "relevance": relevance,
                "actionable": actionable,
                "published": published,
            })

        logger.info("arXiv sweep: %d relevant papers found", len(findings))
    except Exception as e:
        logger.warning("arXiv search failed: %s", e)

    return findings


def search_hf_hub() -> List[dict]:
    """Search HuggingFace Hub for trading-related models and datasets."""
    findings = []
    for term in HF_SEARCH_TERMS:
        try:
            params = urllib.parse.urlencode({"search": term, "limit": HF_MAX_PER_TERM, "sort": "downloads", "direction": "-1"})
            url = f"{HF_BASE}/models?{params}"
            req = urllib.request.Request(url, headers={"User-Agent": "OpenTrader-Research/1.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                items = json.loads(resp.read())

            for item in items:
                model_id = item.get("modelId", "")
                tags = item.get("tags", [])
                downloads = item.get("downloads", 0)
                desc = " ".join(tags)
                cap, relevance, actionable = _score_finding(desc, model_id)
                if relevance < 0.2:
                    continue
                findings.append({
                    "source": "hf_models",
                    "title": model_id,
                    "url": f"https://huggingface.co/{model_id}",
                    "summary": f"Tags: {', '.join(tags[:10])}. Downloads: {downloads}",
                    "capability": cap,
                    "relevance": relevance,
                    "actionable": actionable,
                    "downloads": downloads,
                })
        except Exception as e:
            logger.debug("HF model search for '%s' failed: %s", term, e)

    # Deduplicate by title
    seen = set()
    unique = []
    for f in findings:
        if f["title"] not in seen:
            seen.add(f["title"])
            unique.append(f)

    logger.info("HF Hub sweep: %d relevant models found", len(unique))
    return unique


def generate_manifest(state_dir: str = "data") -> Optional[Path]:
    """Run a full research sweep and write a capability manifest.

    Returns path to the generated manifest, or None if no findings.
    """
    state_path = Path(state_dir)
    if not state_path.is_absolute():
        state_path = Path(__file__).resolve().parent.parent / state_dir

    research_dir = state_path / "research"
    research_dir.mkdir(parents=True, exist_ok=True)
    (research_dir / "scenarios").mkdir(exist_ok=True)
    (research_dir / "eval_transforms").mkdir(exist_ok=True)
    (research_dir / "augmentations").mkdir(exist_ok=True)
    (research_dir / "archived").mkdir(exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    logger.info("Starting research sweep %s", ts)
    arxiv_findings = search_arxiv()
    hf_findings = search_hf_hub()

    all_findings = arxiv_findings + hf_findings

    # Deduplicate by title
    seen_titles = set()
    deduped = []
    for f in all_findings:
        t = f["title"].lower().strip()
        if t not in seen_titles:
            seen_titles.add(t)
            deduped.append(f)

    if not deduped:
        logger.info("No findings in this sweep — skipping manifest")
        return None

    manifest = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "findings": deduped,
        "surveyed_sources": ["arxiv", "hf_models"],
        "total_findings": len(deduped),
        "actionable_findings": sum(1 for f in deduped if f.get("actionable")),
    }

    manifest_path = research_dir / f"capability_manifest_{ts}.json"
    tmp = manifest_path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    os.replace(str(tmp), str(manifest_path))

    logger.info(
        "Manifest written: %s (%d findings, %d actionable)",
        manifest_path.name,
        len(deduped),
        manifest["actionable_findings"],
    )
    return manifest_path


def run_sweep(state_dir: str = "data", distill: bool = True) -> dict:
    """Run a complete research sweep + distillation cycle.

    Returns summary dict.
    """
    manifest_path = generate_manifest(state_dir)
    if manifest_path is None:
        return {"status": "no_findings", "manifest": None, "distilled": None}

    distilled = None
    if distill:
        try:
            from training.capability_distiller import distill_all
            distilled = distill_all(state_dir)
            logger.info(
                "Distillation complete: %d scenarios, %d transforms, %d augments",
                distilled.get("total_scenarios", 0),
                distilled.get("total_transforms", 0),
                distilled.get("total_augmentations", 0),
            )
        except Exception as e:
            logger.error("Distillation failed: %s", e)
            distilled = {"error": str(e)}

    return {
        "status": "ok",
        "manifest": manifest_path.name,
        "distilled": distilled,
    }


def should_research(state_dir: str = "data") -> bool:
    """Check if research sweep should run now.

    Returns True if:
    - No training lock is held
    - At least RESEARCH_COOLDOWN_CYCLES since last sweep
    - Not too many unprocessed manifests already pending
    """
    state_path = Path(state_dir)
    if not state_path.is_absolute():
        state_path = Path(__file__).resolve().parent.parent / state_dir

    # Check training lock
    lock = state_path / "training.lock"
    if lock.exists():
        return False

    # Check last sweep time
    registry_path = state_path / "research" / "distilled_registry.json"
    if registry_path.exists():
        try:
            with open(registry_path) as f:
                reg = json.load(f)
            distilled = reg.get("distilled_manifests", [])
            if len(distilled) > 0:
                # Cooldown: don't sweep if we processed one in the last hour
                last_manifest = distilled[-1]
                manifest_dir = state_path / "research" / "archived"
                last_file = manifest_dir / last_manifest
                if last_file.exists():
                    age = time.time() - last_file.stat().st_mtime
                    if age < 3600:  # 1 hour cooldown
                        return False
        except Exception:
            pass

    return True


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Autonomous research sweep")
    parser.add_argument("--state-dir", default="data")
    parser.add_argument("--no-distill", action="store_true", help="Generate manifest only, don't distill")
    parser.add_argument("--check", action="store_true", help="Check if research should run")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")

    if args.check:
        print(f"should_research: {should_research(args.state_dir)}")
        return

    result = run_sweep(args.state_dir, distill=not args.no_distill)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()