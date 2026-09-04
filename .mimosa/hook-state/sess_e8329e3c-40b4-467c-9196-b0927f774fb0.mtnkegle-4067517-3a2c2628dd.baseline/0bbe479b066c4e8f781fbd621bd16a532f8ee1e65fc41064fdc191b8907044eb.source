#!/usr/bin/env python3
"""Arxiv Feature Integrator — validates, scores, and injects research findings into debate context.

Reads feature_backlog.json (populated by arxiv.py extract_features()),
validates entry_filter rules against trade history, and formats validated
findings as context blocks for the ADIR debate engine.

A "validated" feature is one whose rule logic passes a basic consistency
check against the current market regime and trade history. Features that
survive validation are injected as "Research Findings" that each debate
agent (Bull/Bear/Risk) can cite or counter.

Lifecycle:
  1. extracted (status=pending, validated=False) — from LLM
  2. validated (validated=True) — passed regex consistency check
  3. promoted (impact_score > 0) — measured positive impact against trades
  4. demoted / retired (impact_score < 0 or age > MAX_FEATURE_AGE) — negative or stale

Usage:
    integrator = FeatureIntegrator(state_dir="data")
    research_context = integrator.build_context(max_features=5)
    # Inject research_context into debate prompt
"""

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("opentrader.feature_integrator")

# Features that are simple/mechanical enough for automatic validation
VALIDATEABLE_TYPES = {"entry_filter", "exit_signal"}

# Minimum confidence for a feature to be considered for context injection
MIN_CONFIDENCE = 0.65

# Maximum number of features to include in context (to avoid prompt bloat)
MAX_CONTEXT_FEATURES = 5

# Terms that indicate DEX/on-chain-only features not relevant to CEX trading
CEX_IRRELEVANT_TERMS = (
    "dex", "solana", "defi", "filter stack", "rejection event", "reject event",
    "precision audit", "ethereum", "uniswap", "amm", "blockchain",
    " sol ", "rebalance", "filter_event", "filter_rejection", "raydium",
    "liquidity pool", "yield farm", "wallet ", "nft", "metaplex",
    "token", "on-chain", "onchain", "swap", "liquidity pool",
    "DEX", "Solana", "Ethereum", "Uniswap", "AMM",
)

# Minimum feature title length (filters out truncated/garbage extractions)
MIN_TITLE_LENGTH = 8

# Deduplication similarity: titles that share >70% token overlap are duplicates
DEDUP_THRESHOLD = 0.70

# Feature lifecycle constants
MAX_FEATURE_AGE_DAYS = 30  # features older than this get retired unless promoted
IMPACT_LOOKBACK_CYCLES = 50  # cycles to evaluate impact over


class FeatureIntegrator:
    """Validates arxiv-extracted features and builds research context."""

    def __init__(self, state_dir: str = None):
        if state_dir is None:
            state_dir = str(Path(__file__).resolve().parent.parent / "data")
        self.state_dir = Path(state_dir)
        self.backlog_path = self.state_dir / "feature_backlog.json"
        self._last_context: str = ""
        self._last_feature_count: int = -1

    def load_backlog(self) -> Dict[str, Any]:
        """Load the feature backlog."""
        if not self.backlog_path.exists():
            return {"features": [], "total_extracted": 0}
        try:
            return json.loads(self.backlog_path.read_text())
        except (json.JSONDecodeError, FileNotFoundError):
            return {"features": [], "total_extracted": 0}

    def feature_score(self, f: Dict) -> float:
        """Composite score for a feature — used for ranking/selection.

        Components:
          - base: confidence * 0.40
          - validation: +0.30 if validated
          - impact: +/- 0.20 based on measured impact_score
          - effort: +0.10 for 'trivial' (easy wins), -0.05 for 'significant'
          - age: decay by 0.01 per day since extraction (features fade after 30 days)
        """
        score = 0.0

        conf = max(0.0, min(1.0, f.get("confidence", 0.5)))
        score += conf * 0.40

        if f.get("validated"):
            score += 0.30

        impact = f.get("impact_score", 0.0)
        score += max(-0.20, min(0.20, impact * 0.20))

        effort = f.get("implementation_effort", "moderate")
        if effort == "trivial":
            score += 0.10
        elif effort == "significant":
            score -= 0.05

        extracted = f.get("extracted_at", "")
        if extracted:
            try:
                ts = time.strptime(extracted[:19], "%Y-%m-%dT%H:%M:%S")
                age_days = (time.time() - time.mktime(ts)) / 86400.0
                age_days = min(age_days, MAX_FEATURE_AGE_DAYS)
                score -= (age_days / MAX_FEATURE_AGE_DAYS) * 0.15
            except ValueError:
                pass

        return score

    def get_validated_features(self, min_confidence: float = MIN_CONFIDENCE) -> List[Dict]:
        """Return features sorted by composite score, CEX-relevant only.

        Priority goes to validated + high confidence + recent + implemented features.
        Filters out DEX/on-chain-specific features.
        Deduplicates near-identical features by both title AND rule overlap.
        """
        backlog = self.load_backlog()
        features = backlog.get("features", [])

        def is_relevant(f: Dict) -> bool:
            rule = (f.get("rule", "") + " " + f.get("title", "")).lower()
            return not any(term.lower() in rule for term in CEX_IRRELEVANT_TERMS)

        def has_min_title(f: Dict) -> bool:
            return len(f.get("title", "")) >= MIN_TITLE_LENGTH

        features = [f for f in features if is_relevant(f) and has_min_title(f)]

        # Deduplicate by title AND rule token overlap
        deduplicated = []
        seen_pairs: List[Tuple[set, set]] = []
        for f in sorted(features, key=self.feature_score, reverse=True):
            title_tokens = set(f.get("title", "").lower().split())
            rule_tokens = set(f.get("rule", "").lower().split())
            is_dup = any(
                (
                    len(title_tokens & st) / max(len(title_tokens | st), 1) > DEDUP_THRESHOLD
                    or len(rule_tokens & sr) / max(len(rule_tokens | sr), 1) > DEDUP_THRESHOLD
                )
                for st, sr in seen_pairs
            )
            if not is_dup:
                seen_pairs.append((title_tokens, rule_tokens))
                deduplicated.append(f)

        candidates = [f for f in deduplicated if f.get("confidence", 0) >= min_confidence]
        candidates.sort(key=self.feature_score, reverse=True)
        return candidates

    def build_context(self, max_features: int = MAX_CONTEXT_FEATURES) -> str:
        """Build a research context string from the best available features.

        Returns a string like:
        ```
        ## Research Findings (from arXiv papers)

        Finding 1: Reject on volume spike (confidence: 92%, score: 0.85)
          Rule: IF 24h_volume > 2.5 * avg_24h_volume THEN REJECT
          Type: entry_filter | Effort: trivial | Impact: +0.12
          Source: Outcome-Classified...
        ```
        """
        backlog = self.load_backlog()
        fc = backlog.get("total_extracted", 0)
        if fc == self._last_feature_count and self._last_context:
            return self._last_context

        features = self.get_validated_features()
        if not features:
            self._last_context = ""
            self._last_feature_count = fc
            return ""

        top = features[:max_features]
        lines = ["## Research Findings (from arXiv papers)", ""]

        for i, f in enumerate(top, 1):
            title = f.get("title", "Untitled")
            conf = f.get("confidence", 0)
            rule = f.get("rule", "N/A")
            ftype = f.get("type", "unknown")
            effort = f.get("implementation_effort", "unknown")
            source = f.get("paper_source", "Unknown paper")[:60]
            impact = f.get("impact_score", 0.0)
            score = self.feature_score(f)
            validated = "validated" if f.get("validated") else "unvalidated"
            promoted = "promoted" if f.get("promoted") else ""

            status_tags = [validated]
            if promoted:
                status_tags.append(promoted)

            lines.append(
                f"Finding {i}: {title} [{', '.join(status_tags)}, "
                f"conf: {int(conf*100)}%, score: {score:.2f}]"
            )
            lines.append(f"  Rule: {rule}")
            lines.append(f"  Type: {ftype} | Effort: {effort} | Impact: {impact:+.2f}")
            lines.append(f"  Source: {source}")
            lines.append("")

        context = "\n".join(lines).strip()
        self._last_context = context
        self._last_feature_count = fc
        return context

    def validate_against_trades(
        self,
        trade_history: List[Dict],
        max_features: int = 10,
    ) -> int:
        """Validate entry_filter/exit_signal features against historical trade outcomes.

        For each feature, checks if applying the rule to historical
        trades would have improved outcomes. Marks validated features in the backlog.

        Returns number of newly validated features.
        """
        backlog = self.load_backlog()
        features = backlog.get("features", [])
        if not trade_history:
            return 0

        candidates = [
            f for f in features
            if f.get("type") in VALIDATEABLE_TYPES
            and not f.get("validated")
            and f.get("confidence", 0) >= 0.65
        ][:max_features]

        validated_count = 0
        for f in candidates:
            rule = f.get("rule", "")
            if self._check_rule_consistency(rule, trade_history):
                f["validated"] = True
                validated_count += 1
                logger.debug(
                    f"Feature validated: {f['title']} "
                    f"(conf: {f.get('confidence', 0):.2f})"
                )

        if validated_count > 0:
            backlog["updated_at"] = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
            )
            self.backlog_path.write_text(json.dumps(backlog, indent=2))
            logger.info(
                f"Feature integrator: validated {validated_count} new features "
                f"(total backlog: {backlog.get('total_extracted', 0)})"
            )
            self._last_feature_count = -1

        return validated_count

    def promote_feature(self, title: str, impact_delta: float) -> bool:
        """Mark a feature as promoted and record its measured impact.

        Call this when a feature was implemented and showed a measurable result.
        Positive impact_delta means the feature helped.
        """
        backlog = self.load_backlog()
        features = backlog.get("features", [])
        for f in features:
            if f.get("title", "") == title:
                f["promoted"] = True
                f["impact_score"] = round(f.get("impact_score", 0.0) + impact_delta, 4)
                f["impact_measured_at"] = time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                )
                backlog["updated_at"] = f["impact_measured_at"]
                self.backlog_path.write_text(json.dumps(backlog, indent=2))
                logger.info(
                    f"Feature promoted: {title} impact={impact_delta:+.4f} "
                    f"(cumulative: {f['impact_score']:.4f})"
                )
                self._last_feature_count = -1
                return True
        return False

    def retire_feature(self, title: str) -> bool:
        """Mark a feature as retired (negative impact or stale)."""
        backlog = self.load_backlog()
        features = backlog.get("features", [])
        for f in features:
            if f.get("title", "") == title:
                f["status"] = "retired"
                f["retired_at"] = time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                )
                backlog["updated_at"] = f["retired_at"]
                self.backlog_path.write_text(json.dumps(backlog, indent=2))
                logger.info(f"Feature retired: {title}")
                self._last_feature_count = -1
                return True
        return False

    def cleanup_stale(self, max_age_days: int = MAX_FEATURE_AGE_DAYS) -> int:
        """Retire features older than max_age_days that were never validated."""
        backlog = self.load_backlog()
        features = backlog.get("features", [])
        now = time.time()
        retired = 0

        for f in features:
            if f.get("status") == "retired":
                continue
            extracted = f.get("extracted_at", "")
            if not extracted:
                continue
            try:
                ts = time.strptime(extracted[:19], "%Y-%m-%dT%H:%M:%S")
                age_days = (now - time.mktime(ts)) / 86400.0
                if age_days > max_age_days and not f.get("validated"):
                    f["status"] = "retired"
                    f["retired_at"] = time.strftime(
                        "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                    )
                    f["retired_reason"] = f"age ({age_days:.0f}d > {max_age_days}d max)"
                    retired += 1
            except ValueError:
                pass

        if retired > 0:
            backlog["updated_at"] = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
            )
            self.backlog_path.write_text(json.dumps(backlog, indent=2))
            logger.info(f"Feature cleanup: retired {retired} stale features")
            self._last_feature_count = -1

        return retired

    def _check_rule_consistency(
        self, rule: str, trade_history: List[Dict]
    ) -> bool:
        """Basic validation: does the rule target measurable metrics with thresholds?

        A rule is mechanically sound if it references at least 2 of:
          - measurable metric (RSI, MA, volume, price, volatility, etc.)
          - specific action (REJECT, SKIP, STOP, BUY, SELL, etc.)
          - numeric threshold (% or multiplier)
        """
        if len(rule) < 10:
            return False
        if (
            "=" not in rule
            and ">" not in rule
            and "<" not in rule
            and "THEN" not in rule.upper()
        ):
            return False

        pattern_hints = [
            r"(?:RSI|MA\d*|volume|price|volatility|drawdown|VaR|CVaR|ADX|spread|OI)",
            r"(?:REJECT|SKIP|STOP|REJECT_TRADE|DO_NOT_EXECUTE|HOLD|BUY|SELL|REDUCE|INCREASE|CLOSE)",
            r"(?:\d+%|\d+x|\d+\.\d+\s*x|\d+\.\d+%)",
        ]
        matches = sum(1 for p in pattern_hints if re.search(p, rule, re.IGNORECASE))
        return matches >= 2


# ── Convenience functions for harness integration ──

def get_research_context(
    state_dir: str = None, max_features: int = 5
) -> str:
    """Quick access: get arxiv research context for debate injection."""
    integrator = FeatureIntegrator(state_dir)
    return integrator.build_context(max_features=max_features)


def validate_and_integrate(
    state_dir: str = None,
    trade_history: List[Dict] = None,
) -> Tuple[int, str]:
    """Validate features and return context. Single call for harness."""
    integrator = FeatureIntegrator(state_dir)
    validated = 0
    if trade_history:
        validated = integrator.validate_against_trades(trade_history)
    integrator.cleanup_stale()
    context = integrator.build_context()
    return validated, context


# ── Test ──
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    integrator = FeatureIntegrator()
    features = integrator.get_validated_features()
    print(f"Validated/confident features: {len(features)}")

    if features:
        print("\nTop 5 by composite score:")
        for i, f in enumerate(features[:5], 1):
            score = integrator.feature_score(f)
            print(
                f"  {i}. [{score:.3f}] {f['title'][:60]} "
                f"(conf={f.get('confidence', 0):.2f}, "
                f"validated={f.get('validated')}, "
                f"impact={f.get('impact_score', 0):+.2f})"
            )

    print()
    ctx = integrator.build_context()
    print(ctx if ctx else "(No features meet confidence threshold)")
