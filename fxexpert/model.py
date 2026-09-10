"""fxexpert.model — the FX expert network.

A temporal transformer over a T-day window of per-pair features. One scalar
head predicts the vol-standardized 5-day forward return; sign is the
direction, magnitude is the conviction (the gate thresholds on it). Params
scale with d_model/layers — the loop grows them as the accrual store grows
(v0.1 configs are 0.2-1.5M params: honest for ~65k training rows; the 10B
target is data-gated, not code-gated).
"""

import math

import torch
import torch.nn as nn


def sinusoidal(T, d):
    pos = torch.arange(T).unsqueeze(1).float()
    div = torch.exp(torch.arange(0, d, 2).float() * (-math.log(10000.0) / d))
    pe = torch.zeros(T, d)
    pe[:, 0::2] = torch.sin(pos * div)
    pe[:, 1::2] = torch.cos(pos * div[: pe[:, 1::2].shape[1]])
    return pe


class FXExpert(nn.Module):
    def __init__(self, n_feat, d_model=96, n_layers=3, n_heads=4,
                 dropout=0.15, T=20):
        super().__init__()
        self.T = T
        self.inp = nn.Linear(n_feat, d_model)
        self.drop = nn.Dropout(dropout)
        layer = nn.TransformerEncoderLayer(
            d_model, n_heads, dim_feedforward=4 * d_model, dropout=dropout,
            activation="gelu", batch_first=True, norm_first=True)
        self.enc = nn.TransformerEncoder(layer, n_layers,
                                         enable_nested_tensor=False)
        self.norm = nn.LayerNorm(d_model)
        self.head = nn.Linear(d_model, 1)
        self.register_buffer("pe", sinusoidal(T, d_model), persistent=False)

    def forward(self, x):  # x: (B, T, F)
        h = self.drop(self.inp(x) + self.pe.unsqueeze(0))
        h = self.enc(h)
        return self.head(self.norm(h[:, -1])).squeeze(-1)


def param_count(model):
    return sum(p.numel() for p in model.parameters() if p.requires_grad)
