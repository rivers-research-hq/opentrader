#!/usr/bin/env python3
"""arXiv research paper feed — surfaces latest quant-finance papers as trading context.

Categories queried (11 in total):
  q-fin:  TR (Trading/Market Microstructure), CP (Computational Finance),
          PM (Portfolio Management), ST (Statistical Finance),
          RM (Risk Management), MF (Mathematical Finance)
  cs:     LG (Machine Learning), CE (Computational Engineering/Finance)
  stat:   ML (Machine Learning), AP (Applications), TH (Statistics Theory)

API: Free, no API key. Rate limit: 1 request/3s (respectful usage).
Cache TTL: 24 hours (papers published daily). Fetch 15 candidates, keyword-filter to top 8.

Also provides extract_features() — periodically asks the LLM to extract
actionable trading rules from unextracted cached papers, producing a feature backlog.
"""
import json
import logging
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError

logger = logging.getLogger("opentrader.arxiv")

ARXIV_API = "https://export.arxiv.org/api/query"
CACHE_DIR = Path(__file__).resolve().parent.parent / "data"
CACHE_FILE = CACHE_DIR / "arxiv_cache.json"
# Persistent discovery library: every fetch MERGES new papers in (dedup by
# arXiv id), so the corpus grows without bound. CACHE_FILE is just the daily
# top-k feed the debate context reads.
LIBRARY_FILE = CACHE_DIR / "arxiv_library.json"
CROSS_CACHE_FILE = CACHE_DIR / "arxiv_cross_cache.json"
FEATURE_BACKLOG = CACHE_DIR / "feature_backlog.json"
CACHE_TTL = 86400  # 24 hours — arXiv updates once daily
EXTRACT_INTERVAL = 50  # cycles between feature extractions
MAX_RESULTS = 100  # fetch more, keyword-filter down
MAX_CACHED = 8  # keep top 8 most relevant after filtering
REQUEST_TIMEOUT = 15  # seconds
SUMMARY_MAX_CHARS = 800  # keep enough methodology for LLM extraction

# arXiv API namespace
ATOM_NS = "http://www.w3.org/2005/Atom"

# Quant finance + ML/stat categories relevant to crypto/algorithmic trading
CATEGORIES = (
    "cat:q-fin.TR"   # Trading and Market Microstructure
    "+OR+cat:q-fin.CP"  # Computational Finance
    "+OR+cat:q-fin.PM"  # Portfolio Management
    "+OR+cat:q-fin.ST"  # Statistical Finance
    "+OR+cat:q-fin.RM"  # Risk Management
    "+OR+cat:q-fin.MF"  # Mathematical Finance
    # Broad ML/stat categories were dropping in physics/biology/3D-ML papers
    # (Seiberg dualities etc.); finance-only feed keeps the researcher on-topic.
)

# Cross-domain discovery stream (Feed B): psychology, neuroscience, complex
# systems, and physical sciences mined for emerging-market trading rules.
# Kept SEPARATE from the core q-fin feed; papers here only reach the model
# after their extracted rules pass the evidence gate.
CROSS_CATEGORIES = (
    "cat:econ.GN"         # General Economics (behavioral econ)
    "+OR+cat:q-fin.EC"    # Economics
    "+OR+cat:physics.soc-ph"  # Physics & Society (opinion/market dynamics)
    "+OR+cat:q-bio.NC"    # Neuroscience (decision-making)
    "+OR+cat:cs.CY"       # Computers & Society (behavior)
    "+OR+cat:cond-mat.mtrl-sci"  # Materials (supply chains)
    "+OR+cat:physics.geo-ph"     # Climate/Earth (energy, commodities)
    "+OR+cat:q-bio.PE"    # Ecology (population/cyclical analogs)
    "+OR+cat:stat.AP"     # Statistics Applications
)

# Trading bridge for cross-domain papers — a paper passes if it hits >= 2 of
# these OR co-tags a q-fin category. This is what keeps the physics noise out.
BRIDGE_KEYWORDS = (
    "risk aversion", "loss aversion", "prospect theory", "decision under uncertainty",
    "overconfidence", "ambiguity", "probability weighting", "discounting",
    "market", "trading", "investor", "portfolio", "asset pricing", "liquidity",
    "volatility", "momentum", "bubble", "crash", "cascade", "herding",
    "sentiment", "belief", "expectation", "coordination", "contagion",
    "systemic risk", "supply", "demand", "price", "futures", "commodity",
    "energy market", "opinion dynamics", "collective behavior", "agent-based",
    "network", "risk", "return", "stock", "bank",
)


def _stream_of(cats) -> str:
    """Classify a paper by full category membership: qfin / cross / bridge."""
    has_qfin = any(c.startswith("q-fin") for c in cats)
    cross_set = {"econ.gn", "q-fin.ec", "physics.soc-ph", "q-bio.nc", "cs.cy",
                 "cond-mat.mtrl-sci", "physics.geo-ph", "q-bio.pe", "stat.ap"}
    has_cross = any(c.lower() in cross_set for c in cats)
    if has_qfin and has_cross:
        return "bridge"
    if has_qfin:
        return "qfin"
    if has_cross:
        return "cross"
    return "other"

# Terms for relevance scoring — papers matching more terms score higher
# Also used as a binary filter: papers with zero hits are discarded
KEYWORD_HITS = (
    # Core trading / crypto
    "trading", "algorithmic", "market making", "order book", "order flow",
    "crypto", "defi", "blockchain", "bitcoin", "ethereum", "solana",
    "liquidity", "execution", "bid-ask", "slippage", "market impact",
    # Portfolio / risk
    "portfolio", "risk management", "volatility", "drawdown", "tail risk",
    "sharpe", "alpha", "factor", "hedging", "asset allocation",
    "VaR", "CVaR", "expected shortfall", "stress testing",
    # ML / signal generation
    "reinforcement learning", "deep learning", "neural network",
    "gradient boosting", "random forest", "transformer", "attention",
    "time series", "forecast", "prediction", "regime", "regime switch",
    "anomaly detection", "change point", "conformal prediction",
    "bootstrap", "stochastic", "point process", "optimal stopping",
    # Market structure
    "market microstructure", "high frequency", "limit order",
    "price discovery", "information", "adverse selection",
    "auction", "fragmentation", "dark pool", "OTC",
    # Economic / sentiment
    "sentiment", "news", "macroeconomic", "monetary policy",
    "federal reserve", "inflation", "GDP", "yield curve",
    "credit risk", "default", "contagion", "systemic risk",
)

# DEX/chain-only terms — papers matching these AND nothing from KEYWORD_HITS
# are penalized (but not discarded if they also score keyword hits)
DEX_PENALTY_TERMS = (
    "dex", "solana", "defi", "uniswap", "amm", "automated market maker",
    "token", "nft", "metaplex", "raydium", "yield farm", "liquidity pool",
    "on-chain", "onchain", "wallet", "smart contract", "metamask",
    "sniper", "rug pull", "mempool",
)


def _paper_relevance(title: str, summary: str) -> tuple:
    """Score a paper for trading relevance and detect DEX/chain specificity.

    Returns (hit_count, is_dex_specific) — score 0 means discard.
    """
    text = (title + " " + summary).lower()
    hits = sum(1 for kw in KEYWORD_HITS if kw.lower() in text)
    dex_hits = sum(1 for t in DEX_PENALTY_TERMS if t.lower() in text)
    is_dex_specific = dex_hits >= 2 and hits < 2
    return hits, is_dex_specific


def _load_cache() -> Optional[List[Dict]]:
    """Load cached papers if fresh enough."""
    if not CACHE_FILE.exists():
        return None
    try:
        cache = json.loads(CACHE_FILE.read_text())
        age = time.time() - cache.get("fetched_at", 0)
        if age < CACHE_TTL:
            return cache.get("papers", [])
    except Exception:
        pass
    return None


def _save_cache(papers: List[Dict]) -> None:
    """Save papers to disk cache."""
    CACHE_FILE.write_text(json.dumps({
        "papers": papers,
        "fetched_at": time.time(),
        "count": len(papers),
    }, indent=2))


def _load_library() -> List[Dict]:
    """Load the persistent paper library (grows across fetches)."""
    if not LIBRARY_FILE.exists():
        return []
    try:
        data = json.loads(LIBRARY_FILE.read_text())
        return data.get("papers", []) if isinstance(data, dict) else data
    except Exception:
        return []


def _save_library(papers: List[Dict]) -> None:
    LIBRARY_FILE.write_text(json.dumps({
        "papers": papers,
        "count": len(papers),
    }, indent=2))


def _top_feed(library: List[Dict], n: int = MAX_CACHED) -> List[Dict]:
    """Best-n papers from the library for the debate feed: relevance, then recency.

    Only qfin/bridge papers qualify — cross-only papers stay out of the model's
    daily context until their extracted rules pass the evidence gate.
    """
    qual = [p for p in library if p.get("stream") in ("qfin", "bridge")]

    def key(p):
        return (p.get("score", 0), p.get("published", ""))
    feed = sorted(qual, key=key, reverse=True)[:n]
    out = []
    for p in feed:
        q = dict(p)
        q.pop("_extracted", None)
        q.pop("score", None)
        out.append(q)
    return out


def fetch_arxiv(max_results: int = MAX_RESULTS) -> List[Dict[str, str]]:
    """Fetch recent quant-finance papers, merge into the persistent library.

    Every call ADDS newly-published papers to data/arxiv_library.json (dedup by
    arXiv id) so the corpus grows without bound. Returns the top-k feed for the
    debate context (relevance, then recency). Cache TTL 24h gate the refetch.
    """
    cached = _load_cache()
    if cached is not None:
        return cached

    query = f"search_query={CATEGORIES}&max_results={max_results}&sortBy=submittedDate&sortOrder=descending"
    url = f"{ARXIV_API}?{query}"

    try:
        req = Request(url, method="GET")
        req.add_header("User-Agent", "OpenTrader/1.0 (research bot; one query per day)")
        with urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8")
    except URLError as e:
        logger.warning(f"arXiv API unreachable: {e}")
        return _top_feed(_load_library())
    except Exception as e:
        logger.warning(f"arXiv fetch failed: {e}")
        return _top_feed(_load_library())

    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        logger.warning(f"arXiv XML parse error: {e}")
        return _top_feed(_load_library())

    ns = {"a": ATOM_NS}
    candidates = []
    for entry in root.findall("a:entry", ns):
        title_el = entry.find("a:title", ns)
        summary_el = entry.find("a:summary", ns)
        published_el = entry.find("a:published", ns)
        arxiv_id = entry.findtext("a:id", "").rsplit("/", 1)[-1]

        title = title_el.text.strip().replace("\n", " ") if title_el is not None else ""
        summary = summary_el.text.strip().replace("\n", " ") if summary_el is not None else ""
        published = published_el.text[:10] if published_el is not None else ""
        cats = [c.get("term", "") for c in entry.findall("a:category", ns)]

        pdf_url = ""
        for link in entry.findall("a:link", ns):
            if link.get("title") == "pdf":
                pdf_url = link.get("href", "")
                break

        full_summary = summary
        summary = summary[:SUMMARY_MAX_CHARS] + "..." if len(summary) > SUMMARY_MAX_CHARS else summary

        # Finance-first relevance gate: require a q-fin category, or a strong
        # multi-keyword hit. Single generic-ML hits no longer pass — that let
        # physics/ML noise (Seiberg dualities, 3D structure) into the feed.
        is_qfin = any(c.startswith("q-fin") for c in cats)
        score, is_dex = _paper_relevance(title, full_summary)
        if (not is_qfin and score < 2) or score == 0:
            logger.debug(f"arXiv skip (not finance-relevant): {title[:60]}")
            continue

        candidates.append({
            "id": arxiv_id or pdf_url,
            "title": title,
            "summary": summary,
            "published": published,
            "pdf_url": pdf_url,
            "categories": cats,
            "stream": _stream_of(cats),
            "score": score,
            "dex_specific": is_dex,
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })

    # Merge ALL filtered candidates into the persistent library (dedup by id)
    library = _load_library()
    existing_ids = {p.get("id") for p in library}
    new_count = 0
    for c in candidates:
        if c["id"] and c["id"] not in existing_ids:
            library.append(c)
            existing_ids.add(c["id"])
            new_count += 1
    _save_library(library)

    # Feed = top-k from the library; keep CACHE_FILE as the feed snapshot
    feed = _top_feed(library, MAX_CACHED)
    _save_cache(feed)
    logger.info(
        f"arXiv: +{new_count} new papers (library={len(library)}), "
        f"feed={len(feed)}"
    )
    return feed


def fetch_cross_domain(max_results: int = 200) -> List[Dict]:
    """Feed B: cross-domain (psych/neuro/complex-systems/physical-science)
    papers mined for emerging-market trading rules.

    Relevance gate: a paper passes if it co-tags a q-fin category (bridge) OR
    hits >= 2 trading-bridge keywords. Merged into the SAME library, classified
    by full category membership (qfin/cross/bridge). Returns the newly added
    papers. Cross-only papers feed extraction but not the model's daily context.
    """
    query = (f"search_query={CROSS_CATEGORIES}&max_results={max_results}"
             f"&sortBy=submittedDate&sortOrder=descending")
    # 24h cooldown — the harness calls this once per cycle, but arXiv is
    # rate-limited; Feed B refreshes daily like Feed A.
    try:
        if CROSS_CACHE_FILE.exists():
            age = time.time() - float(CROSS_CACHE_FILE.read_text().strip())
            if age < CACHE_TTL:
                return []
    except Exception:
        pass
    url = f"{ARXIV_API}?{query}"
    try:
        req = Request(url, method="GET")
        req.add_header("User-Agent", "OpenTrader/1.0 (research bot; one query per day)")
        with urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
    except Exception as e:
        logger.warning(f"arXiv cross-domain fetch failed: {e}")
        return []

    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        logger.warning(f"arXiv cross-domain XML parse error: {e}")
        return []

    ns = {"a": ATOM_NS}
    candidates = []
    for entry in root.findall("a:entry", ns):
        title_el = entry.find("a:title", ns)
        summary_el = entry.find("a:summary", ns)
        published_el = entry.find("a:published", ns)
        arxiv_id = entry.findtext("a:id", "").rsplit("/", 1)[-1]

        title = title_el.text.strip().replace("\n", " ") if title_el is not None else ""
        summary = summary_el.text.strip().replace("\n", " ") if summary_el is not None else ""
        published = published_el.text[:10] if published_el is not None else ""
        cats = [c.get("term", "") for c in entry.findall("a:category", ns)]

        pdf_url = ""
        for link in entry.findall("a:link", ns):
            if link.get("title") == "pdf":
                pdf_url = link.get("href", "")
                break

        stream = _stream_of(cats)
        if stream == "other":
            continue
        text = (title + " " + summary).lower()
        bridge_hits = sum(1 for k in BRIDGE_KEYWORDS if k in text)
        if stream == "cross" and bridge_hits < 2:
            continue

        candidates.append({
            "id": arxiv_id or pdf_url,
            "title": title,
            "summary": summary[:SUMMARY_MAX_CHARS] + "..." if len(summary) > SUMMARY_MAX_CHARS else summary,
            "published": published,
            "pdf_url": pdf_url,
            "categories": cats,
            "stream": stream,
            "bridge": stream == "bridge",
            "bridge_hits": bridge_hits,
            "score": bridge_hits,
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })

    library = _load_library()
    existing_ids = {p.get("id") for p in library}
    added = []
    for c in candidates:
        if c["id"] and c["id"] not in existing_ids:
            library.append(c)
            existing_ids.add(c["id"])
            added.append(c)
    _save_library(library)
    CROSS_CACHE_FILE.write_text(str(time.time()))
    bridges = sum(1 for a in added if a.get("bridge"))
    logger.info(f"cross-domain: +{len(added)} papers ({bridges} bridge), library={len(library)}")
    return added


def format_arxiv_context(papers: List[Dict]) -> str:
    """Format papers into a compact context block for the debate engine."""
    if not papers:
        return ""

    lines = ["\nRECENT QUANT FINANCE RESEARCH (arXiv):"]
    for i, p in enumerate(papers[:5], 1):
        cats = ", ".join(p.get("categories", [])[:2])
        lines.append(
            f"  {i}. [{p.get('published', '?')}] {p['title'][:120]}\n"
            f"     {p['summary'][:200]}... [{cats}]"
        )

    return "\n".join(lines) + "\n"


# ═══════════════════════════════════════════════════════════════
# Feature Extraction — LLM reads papers → actionable backlog
# ═══════════════════════════════════════════════════════════════

FEATURE_EXTRACT_PROMPT = """You analyze quantitative finance and ML research papers for a crypto trading bot (CEX — Kraken spot/futures).

From the following paper summaries, extract 1-3 actionable trading rules that could be
IMPLEMENTED AS CODE in a trading system. Focus on concrete, mechanical rules — not vague advice.

This bot trades centralized exchanges (NOT DEX/smart-contract platforms). Skip rules that
require on-chain data, mempool access, DEX infrastructure, or smart-contract events.
Focus on rules using: OHLCV, volume, order book depth, volatility, correlation, regime
detection, risk metrics, sentiment signals, technical indicators.

For each rule, output a JSON object with these fields:
  - "title": short descriptive name (max 8 words, unique)
  - "rule": concrete condition → action (e.g., "IF RSI < 30 AND volume > 2x avg THEN BUY")
  - "type": one of ["entry_filter", "exit_signal", "position_sizing", "risk_management", "regime_detection", "market_microstructure"]
  - "expected_impact": estimate of win-rate or profit-factor improvement (e.g., "+2% win rate")
  - "confidence": 0.0-1.0 (how well-supported by the paper's empirical results)
  - "implementation_effort": one of ["trivial", "moderate", "significant"]
  - "paper_source": which paper this came from (first 50 chars of title)

Output ONLY a JSON array of objects (no markdown, no explanation).
Only include rules that are SPECIFIC and IMPLEMENTABLE.
If a paper contains no actionable rules, skip it entirely.
Do not include generic advice like "use better risk management."

IMPORTANT: The following rules already exist in the backlog. Do NOT suggest these again or
any close variant of them. Propose only genuinely new, distinct rules:
{existing_features}"""


def extract_features(llama_host: str = "http://127.0.0.1:5802",
                     model: str = "qwythos-9b-mtp") -> List[Dict]:
    """Ask the LLM to extract implementable trading rules from cached arxiv papers.

    Returns list of new feature dicts, saves to feature_backlog.json.
    Skips papers already extracted (tracked via cache's per-paper `_extracted` flag).
    Deduplicates against existing backlog by title similarity AND rule overlap.
    Filters out DEX/on-chain-specific features.
    """
    # Read from the persistent LIBRARY (all discovered papers), not just the
    # daily 8-paper feed — so features accumulate as the corpus grows.
    library = _load_library()
    unextracted = [p for p in library if not p.get("_extracted", False)]
    if not unextracted:
        logger.debug("arXiv features: all papers already extracted")
        return []

    # Load existing backlog
    try:
        backlog = json.loads(FEATURE_BACKLOG.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        backlog = {"features": [], "updated_at": "", "total_extracted": 0}

    existing_titles = set()
    existing_rules = []
    rule_to_feat = {}
    for item in backlog.get("features", []):
        t = item.get("title", "").lower()
        if t:
            existing_titles.add(t)
        r = item.get("rule", "").lower()
        if r:
            existing_rules.append(r)
            rule_to_feat.setdefault(r, item)

    # Show existing feature titles to avoid duplicates
    existing_list = "\n".join(f"  - {t}" for t in sorted(existing_titles))
    base_prompt = FEATURE_EXTRACT_PROMPT.format(existing_features=existing_list or "  (none yet)")

    features = []
    new_count = 0
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    # Process unextracted papers in batches of 5 per LLM call, bounded per run
    # so extraction never starves the live debate on the shared GPU.
    processed = []
    n_batches = min((len(unextracted) + 4) // 5, 3)
    for i in range(n_batches):
        batch = unextracted[i * 5 : i * 5 + 5]
        processed.extend(batch)
        batch_fields = sorted({p.get("stream", "?") for p in batch})
        paper_text = "\n\n---\n\n".join(
            f"PAPER {j+1} ({p.get('published', '?')}): {p['title']}\n{p['summary']}"
            for j, p in enumerate(batch)
        )
        prompt = f"{base_prompt}\n\n{paper_text}"

        payload = json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": "You are a quantitative trading researcher for a centralized exchange (Kraken) trading bot. Output only valid JSON arrays. Never output DEX/on-chain specific rules."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "max_tokens": 1200,
        }).encode()

        url = f"{llama_host}/v1/chat/completions"
        req = Request(url, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")

        try:
            with urlopen(req, timeout=60) as resp:
                raw = resp.read().decode()
                data = json.loads(raw)
                text = data["choices"][0]["message"].get("content", "")
        except Exception as e:
            logger.warning(f"Feature extraction LLM call failed: {e}")
            break

        # Parse JSON from response
        batch_features = []
        try:
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            batch_features = json.loads(text)
            if isinstance(batch_features, dict):
                batch_features = [batch_features]
        except json.JSONDecodeError:
            logger.warning(f"Feature extraction: couldn't parse JSON from: {text[:150]}...")
            continue

        # Filter, deduplicate, and merge
        for f in batch_features:
            title = f.get("title", "").strip()
            rule = f.get("rule", "").strip()
            ftype = f.get("type", "").strip()

            if not title or not rule or not ftype:
                continue

            title_lower = title.lower()
            rule_lower = rule.lower()

            # Reject obvious duplicates by title
            if title_lower in existing_titles:
                continue

            # Reject near-duplicate rules (70%+ token overlap with any existing rule)
            rule_tokens = set(rule_lower.split())
            is_dup = False
            for er in existing_rules:
                er_tokens = set(er.split())
                if rule_tokens and er_tokens:
                    overlap = len(rule_tokens & er_tokens) / max(len(rule_tokens | er_tokens), 1)
                    if overlap > 0.70:
                        is_dup = True
                        break
            if is_dup:
                # Cross-field triangulation: the same rule emerging from a
                # DIFFERENT stream (finance vs psychology/neuro/physics) is
                # independent corroboration — promote the existing feature.
                ex_feat = rule_to_feat.get(er)
                if ex_feat is not None:
                    ex_fields = set(ex_feat.get("fields", []))
                    if set(batch_fields) - ex_fields:
                        merged = sorted(ex_fields | set(batch_fields))
                        ex_feat["fields"] = merged
                        ex_feat["multi_source"] = len(merged) > 1
                        logger.info(f"arXiv: rule '{title}' triangulated across {merged}")
                continue

            # Reject DEX/on-chain specific features
            if ftype in ("entry_filter", "exit_signal"):
                combined = (title_lower + " " + rule_lower)
                dex_hits = sum(1 for t in DEX_PENALTY_TERMS if t.lower() in combined)
                trading_hits = sum(1 for kw in KEYWORD_HITS[:12] if kw.lower() in combined)
                if dex_hits >= 2 and trading_hits == 0:
                    logger.debug(f"arXiv feature skip (DEX-specific): {title}")
                    continue

            f["source"] = "arxiv_llm_extraction"
            f["extracted_at"] = now
            f["status"] = "pending"
            f["validated"] = False
            f["fields"] = batch_fields
            f["multi_source"] = len(batch_fields) > 1
            f["confidence"] = max(0.0, min(1.0, f.get("confidence", 0.5)))
            backlog["features"].append(f)
            existing_titles.add(title_lower)
            existing_rules.append(rule_lower)
            rule_to_feat[rule_lower] = f
            new_count += 1
            features.append(f)

    # Mark only the PROCESSED papers as extracted in the LIBRARY — the rest
    # stay unextracted and get picked up on later runs.
    for p in processed:
        p["_extracted"] = True
    _save_library(library)

    if new_count > 0:
        backlog["updated_at"] = now
        backlog["total_extracted"] += new_count
        FEATURE_BACKLOG.write_text(json.dumps(backlog, indent=2))
        logger.info(
            f"arXiv features: extracted {new_count} new rules "
            f"(from {len(processed)}/{len(unextracted)} unextracted papers)"
        )

    return features


# ── Test ──
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    papers = fetch_arxiv(5)
    print(f"Found {len(papers)} papers:")
    for p in papers:
        print(f"  [{p['published']}] {p['title'][:80]}")
    print()
    print(format_arxiv_context(papers))
