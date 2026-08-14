"""The expert roster — the "many MB models" vision, realized as specializations.

Each specialization describes one value-head expert: which candidate universe,
which feature extractor, which data source, which checkpoint. The RegimeRouter
routes among *validated* experts; the rule floor holds until an expert earns
per-regime weight. This is the registry Phase 4 of the roadmap: generalize the
arena loop so a new expert is a config entry, not a fork of the code.

Status semantics:
  - ready    -> data + feature pipeline exist; train_expert() can run today
  - prototype-> feature pipeline exists (e.g. value_head_1m macro path); needs
               the per-expert candidate collector wired into the arena
  - planned  -> data source not yet in-process (crypto archive missing,
               sentiment null-result per five-data-sources evaluation)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from mot.experts import ValueHeadExpert

PROJECT = Path(__file__).resolve().parent.parent
ARENA_OUT = PROJECT / "data" / "arena"


@dataclass
class ExpertSpec:
    id: str
    name: str
    description: str
    status: str                 # ready / prototype / planned
    checkpoint: Optional[Path] = None
    universe: str = "US 17-sym (SPY + 16 tradeables)"
    feature_plan: str = ""
    data_plan: str = ""


SPECIALIZATIONS: dict = {
    "momentum": ExpertSpec(
        id="momentum",
        name="Momentum value head",
        description="US cross-sectional momentum: V(state)->E[10-bar fwd], the arena's incumbent.",
        status="ready",
        checkpoint=ARENA_OUT / "arena_value_head.pt",
        feature_plan="9 engineered OHLCV features + composite score + SPY ratio "
                     "(arena/candidates.py FEAT_COLS)",
        data_plan="5y daily archive, 17-symbol US universe (data/setup_search/ohlcv_5y.pkl)",
    ),
    "macro": ExpertSpec(
        id="macro",
        name="Macro / rate-sensitivity value head",
        description="FRED + VIX + breadth features (the value_head_1m reuse path).",
        status="ready",
        checkpoint=ARENA_OUT / "arena_macro_value_head.pt",
        feature_plan="value_head_1m features: cross-sectional ranks + DFF/DGS10/CPIAUCSL + VIX + breadth",
        data_plan="data/setup_search/macro_series.pkl cache (FRED API + yahoo ^VIX), arena/candidates_macro.py",
    ),
    "ftmo": ExpertSpec(
        id="ftmo",
        name="FTMO-US value head",
        description="FX/metals/indices momentum over the FTMO US challenge universe (DXY regime anchor).",
        status="ready",
        checkpoint=ARENA_OUT / "arena_ftmo_value_head.pt",
        feature_plan="same 11-dim arena features over 14 OANDA instruments "
                     "(EUR_USD..NZD_USD, XAU_USD, XAG_USD, US30, SPX500, NAS100, GER30; DXY=regime)",
        data_plan="yfinance 5y daily cached to data/setup_search/ftmo_ohlcv_5y.pkl; "
                  "setup_search/ftmo_universe.py",
    ),
    "sentiment": ExpertSpec(
        id="sentiment",
        name="Sentiment value head",
        description="News/social sentiment (FinBERT on tweets evaluated null; reddit/news not yet integrated).",
        status="planned",
        feature_plan="news/social sentiment scores from data/news_cache.json, social_cache.json",
        data_plan="caches exist; the five-data-sources evaluation found no added value yet",
    ),
    "crypto": ExpertSpec(
        id="crypto",
        name="Crypto value head",
        description="BTC/ETH/SOL leg (kraken).",
        status="planned",
        feature_plan="crypto OHLCV + regime leader (setup_search/crypto_leg.py)",
        data_plan="crypto_ohlcv.pkl archive NOT present (war-referee note) — needs kraken fetch",
    ),
    "international": ExpertSpec(
        id="international",
        name="International value head",
        description="International indices/FX/commodities (the user's 'brewing problems abroad' surface).",
        status="ready",
        checkpoint=ARENA_OUT / "arena_international_value_head.pt",
        feature_plan="same 11-dim arena features over the 12-ticker international universe "
                     "(^N225 ^FTSE ^GDAXI ^HSI ^VIX EEM EFA EURUSD=X USDJPY=X GC=F CL=F, ^GSPC=regime)",
        data_plan="yfinance 5y daily cached to data/setup_search/international_ohlcv_5y.pkl "
                  "(24h TTL); arena/candidates_international.py",
    ),
    "momtrend": ExpertSpec(
        id="momtrend",
        name="Momentum + market-breadth gate (Tournament survivor)",
        description="Deterministic rule allocator: long top-5 by 60d momentum, entries "
                    "gated by market breadth (>60% of universe above 100d MA), no forced "
                    "exits. Transferred OOS: Calmar 0.94 / maxDD -13% on intl 2021-26.",
        status="prototype",
        checkpoint=None,
        universe="US registry (300 names) or intl tradables (10) — daily bars",
        feature_plan="strategies/momtrend.run() — momentum + breadth regime gate",
        data_plan="strategies/verify.py reproduces R1 (23.2%, Calmar 0.469) and OOS "
                  "(Calmar 0.938). NOT wired to live harness yet (different universe).",
    ),
    "multiasset": ExpertSpec(
        id="multiasset",
        name="Momentum-filtered vol-scaled multi-asset (Tournament survivor)",
        description="Deterministic multi-asset allocator: top-10 of 13 by 180d momentum, "
                    "60% inverse-vol + 40% equal-weight, rebal 63 bars. Transferred OOS: "
                    "Calmar 1.29 / maxDD -9% on intl 2021-26 — the drawdown-control tool.",
        status="prototype",
        checkpoint=None,
        universe="13-asset basket (equities/bonds/gold/commodities/FX) — daily bars",
        feature_plan="strategies/multiasset.backtest() — momentum + inverse-vol sizing",
        data_plan="strategies/verify.py reproduces R1 (7.2%, Calmar 0.39, 4/4 folds) and "
                  "OOS (Calmar 1.289, maxDD -9%). NOT wired to live harness yet.",
    ),
    "spectral": ExpertSpec(
        id="spectral",
        name="Spectral (FFT) regime gate + momentum (R1c winner)",
        description="Momentum-top gated by FFT low-frequency-share ANDed with market "
                    "breadth. Best verified Calmar so far: 1.071 (ann 34%, maxDD -31.7%).",
        status="prototype",
        checkpoint=None,
        universe="US registry (300 names) — daily bars",
        feature_plan="swarm agents/r1c_spectral.py — causal rolling FFT, low-freq share gate",
        data_plan="swarm_data.pkl; verified re-run. NOT wired to live harness.",
    ),
    "copula": ExpertSpec(
        id="copula",
        name="Copula tail-dependence sleeve + momentum (R1c)",
        description="Momentum book with lower-tail-dependence sleeve: rotate to lowest-"
                    "lambda basket assets when SPY<200MA. Calmar 0.904, maxDD -32%.",
        status="prototype",
        checkpoint=None,
        universe="US registry + 13-asset basket — daily bars",
        feature_plan="swarm agents/r1c_copula.py — empirical lower-tail dependence λ",
        data_plan="swarm_data.pkl; verified re-run. NOT wired to live harness.",
    ),
    "hurst": ExpertSpec(
        id="hurst",
        name="Hurst persistence gate + momentum (R1c)",
        description="Momentum-top gated by market breadth AND Hurst>0.54 (persistence). "
                    "Calmar 0.884, maxDD -36.9%.",
        status="prototype",
        checkpoint=None,
        universe="US registry (300 names) — daily bars",
        feature_plan="swarm agents/r1c_hurst.py — R/S Hurst (self-implemented, causal)",
        data_plan="swarm_data.pkl; verified re-run. NOT wired to live harness.",
    ),
    "entropy": ExpertSpec(
        id="entropy",
        name="Entropy regime gate + momentum (R1c)",
        description="Momentum-top gated by breadth AND HIGH market entropy (active regime). "
                    "Calmar 0.832, maxDD -35.7%. Hypothesis reversed: high entropy, not low.",
        status="prototype",
        checkpoint=None,
        universe="US registry (300 names) — daily bars",
        feature_plan="swarm agents/r1c_entropy.py — Shannon entropy of market returns",
        data_plan="swarm_data.pkl; verified. NOT wired to live harness.",
    ),
}


def list_roster() -> list:
    return [
        {"id": s.id, "name": s.name, "status": s.status}
        for s in SPECIALIZATIONS.values()
    ]


def build_expert(expert_id: str) -> Optional[ValueHeadExpert]:
    """Return a ValueHeadExpert wrapping the specialization's trained checkpoint,
    or None if not ready / no checkpoint yet."""
    spec = SPECIALIZATIONS.get(expert_id)
    if spec is None or spec.checkpoint is None:
        return None
    exp = ValueHeadExpert.from_checkpoint(spec.checkpoint, name=expert_id)
    return exp if exp.art is not None else None


def train_expert(expert_id: str, **kw) -> dict:
    """Train/iterate one specialization through the arena loop.

    Currently only 'momentum' has a full data+feature pipeline wired into the
    arena. Other specializations raise a clear NotBuildableError until their
    candidate collector exists — the roster mechanism, not the data, is the
    deliverable here.
    """
    spec = SPECIALIZATIONS.get(expert_id)
    if spec is None:
        raise KeyError(f"unknown expert '{expert_id}'")
    if spec.status != "ready":
        raise NotBuildableError(
            f"expert '{expert_id}' status={spec.status}: needs its candidate "
            f"collector wired into the arena (see ExpertSpec.data_plan)"
        )
    from arena.train import run_iteration
    rep = run_iteration(**kw)
    exp = build_expert(expert_id)
    return {"report": rep, "expert": exp}


class NotBuildableError(Exception):
    pass
