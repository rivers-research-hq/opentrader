"""MarketScenarioGenerator — the multiverse engine.

Two layers, per the architecture decision:
  1. ``ParametricGenerator`` (scenarios.parametric) — the immediate, CPU-fast,
     deterministic everyday multiverse + the distributional baseline.
  2. ``NeuralMarketGenerator`` — a conditional DoppelGANger-style GAN (GRU
     generator with batch generation, per-series normalization, auxiliary
     Wasserstein discriminator) trained on the 5y OHLCV archive. This is the
     learned core the user chose; it upgrades the everyday multiverse once a
     checkpoint exists (see scenarios/train_generator.py, GPU1 idle windows).

The facade ``MarketScenarioGenerator.generate`` prefers the neural generator when
a trained checkpoint is present, else parametric — so the arena always runs. The
tail library (scenarios.tail_library) injects grounded crises on top of either,
because GANs under-sample tails by construction.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from scenarios.parametric import generate as _param_generate
from scenarios.parametric import generate_with_event as _param_generate_event
from scenarios.spec import ScenarioSpec, World
from scenarios.tail_library import EVENTS, TailEvent

DEFAULT_CHECKPOINT = Path(__file__).resolve().parent.parent / "data" / "scenarios" / "neural_gen.pt"


class MarketScenarioGenerator:
    def __init__(self, checkpoint: Optional[Path] = None, device: str = "auto"):
        self.checkpoint = Path(checkpoint) if checkpoint else DEFAULT_CHECKPOINT
        self._neural = None
        self.device = device
        if self.checkpoint.exists():
            self._load_neural()

    # -- neural handling ------------------------------------------------------
    def _load_neural(self):
        try:
            from scenarios.neural import NeuralMarketGenerator
            self._neural = NeuralMarketGenerator(device=self.device)
            self._neural.load(self.checkpoint)
        except Exception as e:  # never let a generator failure break the arena
            print(f"[scenarios] neural generator load failed ({e}); using parametric")
            self._neural = None

    def neural_ready(self) -> bool:
        return self._neural is not None

    # -- public API -----------------------------------------------------------
    def generate(
        self,
        n_worlds: int = 8,
        base_spec: Optional[ScenarioSpec] = None,
        events: Optional[List[str]] = None,
        seeds: Optional[List[int]] = None,
        with_resources: bool = False,
    ) -> List[World]:
        """Generate ``n_worlds`` market realities.

        - Without ``events``: everyday multiverse (neural if trained, else parametric).
        - With ``events``: base worlds with the named crises injected on top.
        - With ``with_resources``: merge scarce/renewable resource assets
          (scenarios.resources) into every world — tradable symbols whose
          dynamics the 17-symbol equity universe cannot express.
        """
        base_spec = base_spec or ScenarioSpec()
        seeds = seeds or [None] * n_worlds
        worlds: List[World] = []
        for i in range(n_worlds):
            spec = ScenarioSpec(**{**base_spec.__dict__, "seed": seeds[i]})
            if self._neural is not None and not spec.event and not with_resources:
                try:
                    data = self._neural.generate_world(spec)
                    worlds.append(World(spec=spec, data=data, generated_by="neural"))
                    continue
                except Exception:
                    pass
            data = _param_generate(spec)
            if with_resources:
                data = _add_resources(data, spec)
            worlds.append(World(spec=spec, data=data,
                                generated_by="neural" if self._neural is not None else "parametric"))

        for eid in (events or []):
            ev = EVENTS.get(eid)
            if ev is None:
                continue
            for w in worlds:
                spec = ScenarioSpec(**{**w.spec.__dict__, "event": eid})
                data = _param_generate_event(spec, ev) if not w.spec.event else _inject(w.data, ev, w.spec.seed)
                if with_resources and not w.spec.event:
                    data = _add_resources(data, spec)
                w.data = data
                w.spec.event = eid
        return worlds

    def tail_events(self) -> List[TailEvent]:
        return list(EVENTS.values())


def _inject(data, event: TailEvent, seed: Optional[int]) -> Dict:
    from scenarios.parametric import inject_event
    return inject_event(data, event, seed=seed)


def _add_resources(data: Dict, spec) -> Dict:
    """Merge scarce/renewable resource assets into a generated world."""
    from scenarios.resources import generate_resource_assets
    import pandas as pd
    resources = generate_resource_assets(spec, index=next(iter(data.values())).index)
    merged = dict(data)
    for sym, df in resources.items():
        if sym not in merged:
            merged[sym] = df
    return merged


def resource_universe() -> list:
    """The resource asset symbols (for spec construction)."""
    from scenarios.resources import RESOURCE_KEYS
    return list(RESOURCE_KEYS)


# Convenience: one crisis-heavy world set covering the user's named tails.
TAIL_EVENT_IDS = [
    "us_debt_ceiling", "covid_crash", "bear_grind_2022",
    "yen_unwind", "flash_crash", "liquidity_gap",
    "currency_crisis", "fed_hike_surprise",
]


def crisis_worlds(n_per_event: int = 2, base_spec: Optional[ScenarioSpec] = None) -> List[World]:
    gen = MarketScenarioGenerator()
    out: List[World] = []
    for eid in TAIL_EVENT_IDS:
        out.extend(gen.generate(n_per_event, base_spec=base_spec, events=[eid]))
    return out
