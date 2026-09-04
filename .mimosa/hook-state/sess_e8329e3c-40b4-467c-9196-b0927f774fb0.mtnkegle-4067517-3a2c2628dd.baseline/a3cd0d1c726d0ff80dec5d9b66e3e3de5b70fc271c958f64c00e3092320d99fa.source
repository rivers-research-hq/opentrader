"""Real GRPO for the arena value-head policy (DeepSeekMath / DeepSeek-R1).

Implements the GRPO objective from DeepSeekMath (arXiv 2402.03300), Eq. 3:
  J = (1/G) Sum_i (1/|o_i|) Sum_t { min[ratio_t * A_hat, clip(ratio_t,1-e,1+e)*A_hat]
                                    - beta * D_KL(pi_theta || pi_ref) }
with the group-relative advantage (Sec 4.1.2) and the KL added to the LOSS
(not the reward), plus the single-update (mu=1) gradient form of Appendix
A.1.6 Eq. 21. Design notes from docs/research/chinese-lab-rl-foundations.md:

  - No critic network: the advantage is the z-score of the outcome within the
    group (the arena's "field"). V(s) is kept as a DETACHED learned baseline
    (the doc's optional-critic note), so the value head still regresses E[fwd].
  - The policy is the value-head MLP: P(TAKE|s) = sigmoid((V(s) - theta)/tau).
  - Hyperparameters: beta=0.04 (DeepSeekMath Sec 4.1.4), clip_eps=0.2
    (inherited PPO/GRPO practice; the papers never publish epsilon).

The arena wire-up (arena/train.py) builds decisions from the war relabels:
reward = realized pnl_pct, action = TAKE, group = regime field (bull/bear), and
this module refines the value head weights toward higher-advantage states.
"""
from __future__ import annotations

from typing import List

import numpy as np
import torch
import torch.nn as nn

BETA = 0.04        # KL coefficient (DeepSeekMath Sec 4.1.4)
CLIP_EPS = 0.2     # ratio clip (inherited PPO/GRPO practice)
TAU = 1.0          # policy temperature: P(TAKE) = sigmoid((V(s)-theta)/tau)


def grpo_update(
    model: nn.Module,
    theta: float,
    mean: np.ndarray,
    std: np.ndarray,
    decisions: List[dict],
    beta: float = BETA,
    lr: float = 1e-3,
    clip_eps: float = CLIP_EPS,
    tau: float = TAU,
    group_key: str = "group",
    device: str = "auto",
):
    """One GRPO update over a list of decisions.

    decisions: [{x: np.ndarray, action: 0/1, reward: float, group: str}]
    Groups default to a single 'all' group; pass regime labels to get the
    field-relative normalization the arena protocol intends. Returns
    (loss, mean_abs_advantage).
    """
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    model = model.to(device)
    model.train()

    # Non-finite rewards must not poison the policy update (NaN/inf gradients
    # silently destroy the weights). Filter them out; nothing to learn from.
    decisions = [d for d in decisions if np.isfinite(d.get("reward", 0.0))]
    if not decisions:
        return 0.0, 0.0

    X = np.stack([np.asarray(d["x"], dtype=np.float32) for d in decisions])
    # Enforce float32 regardless of input dtypes (a float64 mean/std would
    # otherwise crash mat1/mat2 dtype checks).
    Xz = torch.tensor(((X - mean) / (std + 1e-8)).astype(np.float32), device=device)
    acts = torch.tensor([d["action"] for d in decisions], dtype=torch.float32, device=device)
    rewards = np.array([d["reward"] for d in decisions], dtype=np.float64)
    groups = [d.get(group_key, "all") for d in decisions]

    # Reference logits + detached value baseline (mu=1: ref = policy at start).
    with torch.no_grad():
        v = model(Xz)
        ref_logits = (v - theta) / tau
        base = v.detach()

    # Group-relative advantage: z-score of (reward - V(s)) within the group.
    adv = np.zeros(len(decisions), dtype=np.float64)
    for g in set(groups):
        idx = [i for i, gg in enumerate(groups) if gg == g]
        raw = rewards[idx] - base[idx].cpu().numpy()
        if not np.all(np.isfinite(raw)):
            raw = np.nan_to_num(raw, nan=0.0, posinf=0.0, neginf=0.0)
        sd = raw.std()
        if sd < 1e-8:
            sd = 1.0
        adv[idx] = (raw - raw.mean()) / sd
    A = torch.tensor(adv, dtype=torch.float32, device=device)

    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    opt.zero_grad()
    logits = (model(Xz) - theta) / tau
    p = torch.sigmoid(logits)
    p_ref = torch.sigmoid(ref_logits)
    pi = torch.where(acts > 0.5, p, 1 - p)
    pi_ref = torch.where(acts > 0.5, p_ref, 1 - p_ref)

    ratio = pi / (pi_ref + 1e-8)
    clipped = torch.clamp(ratio, 1 - clip_eps, 1 + clip_eps)
    loss_pg = -torch.min(ratio * A, clipped * A).mean()
    # Unbiased KL (DeepSeekMath Eq. 4), added to the loss, not the reward.
    kl = (pi_ref / (pi + 1e-8)) - torch.log((pi_ref + 1e-8) / (pi + 1e-8)) - 1.0
    loss = loss_pg + beta * kl.mean()
    loss.backward()
    opt.step()
    model.eval()
    return float(loss.item()), float(A.abs().mean().item())


def fit_grpo(art: dict, decisions: List[dict], steps: int = 2, beta: float = BETA,
             lr: float = 1e-3) -> dict:
    """Refine an arena value head with GRPO. Mutates art['model'] in place."""
    for _ in range(steps):
        loss, adv = grpo_update(
            art["model"], art["theta"], art["mean"], art["std"],
            decisions, beta=beta, lr=lr,
        )
    art["report"]["grpo"] = {"steps": steps, "loss": loss, "mean_abs_advantage": adv}
    return art
