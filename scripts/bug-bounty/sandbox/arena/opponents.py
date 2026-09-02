"""In-process opponent bots for the arena.

Two classes per the map: home-grown (rule config, jitter variants, baselines,
momentum snapshots) and hedge-fund personas (Citadel, Citron, AHL playbooks
from research ticket 'Hedge-fund persona playbooks for the arena'). All are
pure rules over the candidate feature row — no LLM in the loop.

vote(state) -> 0 (SKIP) or 1 (TAKE). state carries feats, score, regime_up,
bar, sym, close.
"""

import random

import numpy as np


class Opponent:
    name = "opponent"

    def vote(self, state) -> int:
        return 0


class AlwaysTake(Opponent):
    name = "always-take"

    def vote(self, state):
        return 1


class AlwaysSkip(Opponent):
    name = "always-skip"

    def vote(self, state):
        return 0


class RandomBot(Opponent):
    name = "random"

    def __init__(self, p=0.5, seed=None):
        self.p = p
        self.rng = random.Random(seed)

    def vote(self, state):
        return 1 if self.rng.random() < self.p else 0


class RuleBot(Opponent):
    name = "rule-config"

    def __init__(self, cfg, require_regime=True):
        self.cfg = cfg
        self.require_regime = require_regime

    def vote(self, state):
        if self.require_regime and not state["regime_up"]:
            return 0
        return 1 if state["score"] >= self.cfg["buy_thresh"] else 0


class JitterBot(RuleBot):
    def __init__(self, cfg, seed=None, jitter=0.25):
        rng = random.Random(seed)
        jc = dict(cfg)
        for k in (
            "w_mom",
            "w_rev",
            "w_rsi",
            "w_brk",
            "w_z",
            "buy_thresh",
            "sell_thresh",
        ):
            jc[k] = cfg[k] * (1.0 + rng.uniform(-jitter, jitter))
        super().__init__(jc)


class CitadelBot(Opponent):
    name = "citadel"

    def __init__(self, z_max=1.0, vol_shrink=2.0):
        self.z_max = z_max
        self.vol_shrink = vol_shrink

    def vote(self, state):
        f = state["feats"]
        if f["mom"] <= 0:
            return 0
        if f["z"] >= self.z_max:
            return 0
        if f["rev"] <= 0:
            return 0
        if f["vol_spike"] and f["vol_spike"] > self.vol_shrink:
            return 0
        return 1


class CitronBot(Opponent):
    name = "citron"

    def __init__(self, z_hi=1.5, d_hi=0.06, rsi_hi=0.5, vs_hi=1.5, brk_hi=-0.02):
        self.z_hi = z_hi
        self.d_hi = d_hi
        self.rsi_hi = rsi_hi
        self.vs_hi = vs_hi
        self.brk_hi = brk_hi

    def vote(self, state):
        f = state["feats"]
        if f["mom"] <= 0:
            return 0
        extended = (
            f["z"] > self.z_hi or f["ma_dist"] > self.d_hi or f["rsi"] > self.rsi_hi
        )
        if not extended:
            return 0
        if f["vol_spike"] and f["vol_spike"] < self.vs_hi:
            return 0
        if f["brk"] > self.brk_hi:
            return 0
        return 1


class AHLBot(Opponent):
    name = "ahl"

    def __init__(self, mom_long_mult=3, ma_long=200):
        self.mom_long_mult = mom_long_mult
        self.ma_long = ma_long

    def vote(self, state):
        c = state["close_series"]
        t = state["bar"]
        if t - self.ma_long < 0:
            return 0
        if c.iloc[t] <= c.iloc[t - self.ma_long]:
            return 0
        if c.iloc[t] <= c.iloc[t - self.ma_long // 2 : t].mean():
            return 0
        if not state["regime_up"]:
            return 0
        return 1


def home_grown(cfg, seed=7, n_jitter=3):
    bots = [
        RuleBot(cfg),
        AlwaysTake(),
        AlwaysSkip(),
        RandomBot(0.5, seed),
        RandomBot(0.75, seed + 1),
    ]
    for i in range(n_jitter):
        bots.append(JitterBot(cfg, seed=seed + 10 + i))
    return bots


def personas():
    return [CitadelBot(), CitronBot(), AHLBot()]


def default_field(cfg, seed=7):
    bots = home_grown(cfg, seed)
    bots += personas()
    names = set()
    ordered = []
    for b in bots:
        if b.name not in names:
            names.add(b.name)
            ordered.append(b)
    return ordered
