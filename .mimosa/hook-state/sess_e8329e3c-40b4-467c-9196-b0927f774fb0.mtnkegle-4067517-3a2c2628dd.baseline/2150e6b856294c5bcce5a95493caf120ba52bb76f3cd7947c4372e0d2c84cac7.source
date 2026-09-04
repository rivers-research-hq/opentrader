"""scenarios — the multiverse generator for OpenTrader.

Layers:
  - spec: ScenarioSpec / World containers, default universe.
  - tail_library: curated crisis events (US debt ceiling, COVID, yen unwind, ...).
  - parametric: CPU-fast regime-switching jump-diffusion sampler (baseline +
    immediate everyday multiverse).
  - neural: conditional DoppelGANger-style GAN (the learned core; GPU1 idle train).
  - generator: MarketScenarioGenerator facade — neural when trained, else parametric.
  - evaluate: distributional QC + TimeGAN-style gate.
  - train_generator: CLI entry to train the neural core.
"""
from scenarios.generator import MarketScenarioGenerator, crisis_worlds
from scenarios.spec import DEFAULT_UNIVERSE, REGIMES, ScenarioSpec, World

__all__ = ["MarketScenarioGenerator", "crisis_worlds", "ScenarioSpec", "World",
           "DEFAULT_UNIVERSE", "REGIMES"]
