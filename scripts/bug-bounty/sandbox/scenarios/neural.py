"""NeuralMarketGenerator — conditional DoppelGANger-style GAN over market returns.

Follows the architecture notes in docs/research/chinese-lab-rl-foundations.md
(DoppelGANger 1909.13403) and the failure-mode research in
docs/research/market-generator-failure-modes.md:
  - GRU generator with BATCH generation (S records per hidden step) to preserve
    long-range autocorrelation;
  - per-series auto-normalization, with the per-series scale emitted as metadata
    the generator must also produce;
  - a spectral-normalized temporal-conv Wasserstein critic (fix #3: WGAN-GP
    through an RNN requires non-CuDNN double backwards, and SN is the
    recommended stability fix for finite critic updates) plus the auxiliary
    metadata critic; combined loss L_seq + alpha * L_meta;
  - per-window standardization (zero mean / unit std) removes drift/scale games.

Input space: per-bar log-returns of the 17-symbol universe (SPY + 16
tradeables), normalized to unit variance per column. The generator is
CONDITIONAL on a regime + event one-hot.

torch is imported lazily so the rest of the scenarios package works without it.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import torch
import torch.nn as nn

from scenarios.spec import DEFAULT_UNIVERSE, ScenarioSpec, World

D = len(DEFAULT_UNIVERSE)          # 17 (SPY + 16 tradeables)
N_REGIME = 4
N_EVENT = 8
COND_DIM = N_REGIME + N_EVENT

_BASE_LEN = 256
_BATCH_S = 1


def _norm_cdf(z):
    """Standard normal CDF via math.erf."""
    z = np.asarray(z, dtype=np.float64)
    return 0.5 * (1.0 + np.vectorize(lambda x: math.erf(x / math.sqrt(2.0)))(z))


def _norm_ppf(p):
    """Inverse standard normal CDF via Newton's method on the erf-based CDF.
    Seed: 4.9*(p^0.14 - (1-p)^0.14); 4 iterations -> ~1e-10. No scipy needed
    and every step is verifiable (a memory-transcribed coefficient table is
    exactly the kind of thing that silently breaks)."""
    p = np.asarray(p, dtype=np.float64)
    p = np.clip(p, 1e-12, 1 - 1e-12)
    z = 4.9 * (np.power(p, 0.14) - np.power(1.0 - p, 0.14))
    for _ in range(4):
        phi = np.exp(-0.5 * z * z) / np.sqrt(2.0 * np.pi)
        cdf = 0.5 * (1.0 + np.vectorize(lambda x: math.erf(x / math.sqrt(2.0)))(z))
        z = z - (cdf - p) / phi
    return z


def _condition_vector(regime: str, event: str = "") -> np.ndarray:
    c = np.zeros(COND_DIM, dtype=np.float32)
    reg_idx = {"bull": 0, "bear": 1, "range": 2, "crisis": 3}.get(regime, 2)
    c[reg_idx] = 1.0
    if event:
        ev_idx = {"us_debt_ceiling": 0, "covid_crash": 1, "bear_grind_2022": 2,
                  "yen_unwind": 3, "flash_crash": 4, "liquidity_gap": 5,
                  "currency_crisis": 6, "fed_hike_surprise": 7}.get(event)
        if ev_idx is not None:
            c[N_REGIME + ev_idx] = 1.0
    return c


class _Generator(nn.Module):
    def __init__(self, latent=32, hidden=64, out=D):
        super().__init__()
        self.latent = latent
        self.mlp_meta = nn.Sequential(nn.Linear(latent + COND_DIM, hidden), nn.ReLU(),
                                      nn.Linear(hidden, hidden), nn.ReLU(),
                                      nn.Linear(hidden, D))
        self.gru = nn.GRU(latent + COND_DIM, hidden, batch_first=True)
        self.head = nn.Sequential(nn.Linear(hidden, hidden), nn.ReLU(), nn.Linear(hidden, out))

    def forward(self, z, c, steps, batch_s=_BATCH_S):
        """Return (records (steps*batch_s, D), fake_meta (D,)).

        PER-STEP NOISE INPUT: a fresh latent z_t is fed to the GRU every step.
        With a constant input the hidden state converges to a fixed point and
        the whole sequence freezes (measured acf(lag1)~0.98 on the real-data
        run); per-step noise keeps the dynamics moving so autocorrelation
        emerges from the learned recurrence instead of vanishing.
        """
        zc = torch.cat([z, c], dim=-1)
        meta = self.mlp_meta(zc)
        hh = None
        out_rows = []
        for _ in range(steps):
            z_t = torch.randn(1, self.latent, device=z.device)
            x_in = torch.cat([z_t, c], dim=-1).unsqueeze(1)  # (1,1,latent+cond)
            _, hh = self.gru(x_in, hh)                       # hh: (1,1,H)
            h = hh[0, 0]                                     # (H,)
            if batch_s == 1:
                out_rows.append(self.head(h))
            else:
                h_exp = h.unsqueeze(0).repeat(batch_s, 1)
                noise = torch.randn(batch_s, h_exp.size(-1), device=h.device) * 0.5
                out_rows.append(self.head(h_exp + noise))
        rows = torch.stack(out_rows, dim=0).reshape(-1, D)
        return rows, meta


class _SeqCritic(nn.Module):
    """Temporal-conv Wasserstein critic with spectral normalization.

    Replaces the GRU critic: WGAN-GP through an RNN requires non-CuDNN double
    backwards (order-of-magnitude slower), and the literature (see
    docs/research/market-generator-failure-modes.md, fix #3) recommends SN over
    GP with finite critic updates. CNN over the (B,T,D) sequence, mean-pooled
    score."""
    def __init__(self, hidden=64):
        super().__init__()
        self.conv = nn.Sequential(
            nn.utils.spectral_norm(nn.Conv1d(D, hidden, 5, padding=2)),
            nn.LeakyReLU(0.2),
            nn.utils.spectral_norm(nn.Conv1d(hidden, hidden, 5, padding=2)),
            nn.LeakyReLU(0.2),
            nn.utils.spectral_norm(nn.Conv1d(hidden, hidden, 5, padding=2)),
            nn.LeakyReLU(0.2),
            nn.Conv1d(hidden, 1, 1),
        )

    def forward(self, x):
        if x.dim() == 2:
            x = x.unsqueeze(0)
        out = self.conv(x.transpose(1, 2))   # (B,1,T)
        return out.mean(dim=2).squeeze(-1)   # (B,)


class _MetaCritic(nn.Module):
    def __init__(self, hidden=32):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(D, hidden), nn.ReLU(), nn.Linear(hidden, 1))

    def forward(self, m):
        return self.net(m).squeeze(-1)


class NeuralMarketGenerator:
    """Conditional WGAN over market log-returns with emitted metadata.

    Tails: Gaussian-driven generators have finite moments and CANNOT produce
    heavy tails (research fix #5). We use rank-based Gaussianization (empirical
    copula) instead of Lambert-W: each column's training returns are mapped to
    exact standard normals via the empirical CDF; the generator learns the
    Gaussian joint; generation inverts per column through the empirical quantile
    function, restoring the EXACT observed marginal (including tails) and the
    rank copula (cross-symbol dependence). Crisis extrapolation beyond observed
    extremes is the tail library's job, not the everyday generator's.
    """

    def __init__(self, latent=32, hidden=64, device: str = "auto"):
        self.device = _pick_device(device)
        self.gen = _Generator(latent, hidden, D).to(self.device)
        self.seq_c = _SeqCritic(hidden).to(self.device)
        self.meta_c = _MetaCritic().to(self.device)
        self.alpha = 0.5
        self.norm_std = np.ones(D, dtype=np.float32)
        self.gauss_basis = None   # (N,D) z-values of the rank transform
        self.raw_basis = None     # (N,D) sorted raw returns (inverse map)
        self._trained = False

    # -- Gaussianization helpers ----------------------------------------------
    def _gaussianize(self, logret: np.ndarray) -> np.ndarray:
        """Raw (T,D) log-returns -> (T,D) exact-standard-normal z, storing the
        per-column empirical quantile map for inversion."""
        N = logret.shape[0]
        raw_sorted = np.sort(logret, axis=0)                 # (N,D)
        ranks = np.argsort(np.argsort(logret, axis=0), axis=0)  # 0..N-1
        p = (ranks + 0.5) / N
        z = _norm_ppf(np.clip(p, 1e-6, 1 - 1e-6))
        self.raw_basis = raw_sorted.astype(np.float32)
        self.gauss_basis = _norm_ppf((np.arange(N) + 0.5) / N).astype(np.float32)[:, None]
        self.norm_std = np.ones(D, dtype=np.float32)
        return z.astype(np.float32)

    def _invert(self, z: np.ndarray) -> np.ndarray:
        """(T,D) z-samples -> (T,D) raw log-returns via the empirical quantile
        function (linear interpolation on the stored basis)."""
        p = _norm_cdf(z)
        T = z.shape[0]
        out = np.empty_like(z)
        basis = self.gauss_basis[:, 0]  # (N,) increasing z grid
        for j in range(z.shape[1]):
            out[:, j] = np.interp(p[:, j], basis, self.raw_basis[:, j])
        return out

    # -- training -------------------------------------------------------------
    def train(self, logret: np.ndarray, regimes: np.ndarray, epochs=50,
              lr=1e-3, grad_penalty=None, window=_BASE_LEN, seed=0, stride=None,
              critic_per_gen=1, gaussianize=False):
        """logret: (T, D) normalized-log-return matrix; regimes: (T,) label str
        per bar. With gaussianize=True (default) the returns are rank-
        Gaussianized first (tails restored exactly at generation); windows are
        then zero-mean/unit-std so the generator learns the Gaussian joint.
        Runs the WGAN-SN update (spectral-normalized temporal-conv critic; no
        gradient penalty — see _SeqCritic docstring)."""
        if gaussianize:
            x = self._gaussianize(logret)
        else:
            self.norm_std = (np.std(logret, axis=0) + 1e-8).astype(np.float32)
            x = (logret / self.norm_std).astype(np.float32)
        conds = np.stack([_condition_vector(r) for r in regimes])
        windows = _make_windows(x, window, stride or 16)
        cond_w = _make_windows(conds, window, stride or 16)
        for i in range(len(windows)):  # per-window standardization
            w = windows[i]
            windows[i] = (w - w.mean(0)) / (w.std(0) + 1e-8)
        lr_g, lr_d = lr, lr * 2.0  # TTUR: higher critic LR
        opt_g = torch.optim.Adam(self.gen.parameters(), lr=lr_g, betas=(0.5, 0.999))
        opt_d = torch.optim.Adam(list(self.seq_c.parameters()) + list(self.meta_c.parameters()),
                                 lr=lr_d, betas=(0.5, 0.999))
        steps = (window + _BATCH_S - 1) // _BATCH_S
        rng = np.random.RandomState(seed)
        meta_target = torch.ones(D, device=self.device).unsqueeze(0)
        for ep in range(epochs):
            g_loss_t, d_loss_t = 0.0, 0.0
            idx = rng.permutation(len(windows))
            for i in idx:
                xw = torch.tensor(windows[i].astype(np.float32),
                                  device=self.device).unsqueeze(0)  # (1,T,D)
                cw = torch.tensor(cond_w[i][0], device=self.device)             # (Dc,)
                for _ in range(critic_per_gen):
                    z = torch.randn(1, 32, device=self.device)
                    fake, fake_meta = self.gen(z, cw.unsqueeze(0), steps)
                    fake = fake[:xw.size(1)]
                    fake_seq = fake.unsqueeze(0)
                    d_real = self.seq_c(xw)
                    d_fake = self.seq_c(fake_seq.detach())
                    m_real = self.meta_c(meta_target)
                    m_fake = self.meta_c(fake_meta.detach())
                    d_loss = (d_fake.mean() - d_real.mean()
                              + self.alpha * (m_fake.mean() - m_real.mean()))
                    opt_d.zero_grad()
                    d_loss.backward()
                    opt_d.step()
                z = torch.randn(1, 32, device=self.device)
                fake, fake_meta = self.gen(z, cw.unsqueeze(0), steps)
                g_loss = (-self.seq_c(fake).mean() - self.alpha * self.meta_c(fake_meta).mean())
                opt_g.zero_grad()
                g_loss.backward()
                opt_g.step()
                g_loss_t += g_loss.item()
                d_loss_t += d_loss.item()
            print(f"[neural] epoch {ep}: g={g_loss_t / len(windows):.3f} d={d_loss_t / len(windows):.3f}", flush=True)
        self._trained = True
        return self

    # -- generation -----------------------------------------------------------
    def generate_world(self, spec: ScenarioSpec, n_bars=None, seed=None) -> dict:
        if not self._trained:
            raise RuntimeError("NeuralMarketGenerator not trained/loaded")
        if seed is not None:
            torch.manual_seed(seed)
            np.random.seed(seed)
        n = n_bars or spec.n_bars
        steps = (n + _BATCH_S - 1) // _BATCH_S
        self.gen.eval()
        with torch.no_grad():
            z = torch.randn(1, 32, device=self.device)
            c = torch.tensor(_condition_vector(spec.regime, spec.event or ""),
                             device=self.device).unsqueeze(0)
            rows, _ = self.gen(z, c, steps)
            ret = rows.cpu().numpy().astype(np.float64)
        if self.gauss_basis is not None:
            ret = self._invert(ret[:n])
        else:
            ret = ret[:n] * self.norm_std
        close = 100.0 * np.exp(np.cumsum(ret, axis=0))
        index = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
        data = {}
        for j, s in enumerate(DEFAULT_UNIVERSE):
            df = pd.DataFrame(
                {"open": close[:, j], "high": close[:, j] * 1.005,
                 "low": close[:, j] * 0.995, "close": close[:, j],
                 "volume": np.full(n, 1e6)},
                index=index,
            )
            data[s] = df
        return data

    def save(self, path):
        torch.save({"gen": self.gen.state_dict(), "norm_std": self.norm_std,
                    "gauss_basis": self.gauss_basis, "raw_basis": self.raw_basis}, path)

    def load(self, path) -> bool:
        """Load a checkpoint; returns True on success, False (without raising)
        on corrupt/missing-key checkpoints so callers degrade gracefully."""
        try:
            ck = torch.load(path, map_location=self.device, weights_only=False)
            if "gen" not in ck or "norm_std" not in ck:
                print(f"[neural] checkpoint {path} missing keys; ignoring")
                return False
            self.gen.load_state_dict(ck["gen"])
            self.norm_std = np.asarray(ck["norm_std"], dtype=np.float32)
            self.gauss_basis = ck.get("gauss_basis")
            self.raw_basis = ck.get("raw_basis")
            self._trained = True
            return True
        except Exception as e:
            print(f"[neural] checkpoint {path} unreadable ({e}); ignoring")
            return False


def _pick_device(device: str):
    if device != "auto":
        return device
    return "cuda" if torch.cuda.is_available() else "cpu"


def _make_windows(x: np.ndarray, window: int, stride=None) -> np.ndarray:
    stride = stride or window // 2
    n = len(x)
    return np.stack([x[i:i + window] for i in range(0, max(1, n - window + 1), stride)])
