"""Unit tests for the leak_standardization debug flag (#249).

#244 fixed the standardization leak: mu/sd must come from the keep-FILTERED
train rows (idx_keep[tr_idx]), not X[tr_idx] — the latter indexes the FULL
panel with filtered positions, so invalid and out-of-fold rows (incl. future
data) contaminate the stats. The #249 leak A/B needs the pre-#244 behavior
back as an explicit DEBUG-ONLY arm; these tests pin that the flag does
exactly that, on a synthetic panel engineered so the leak is observable:
rows 8500-8990 are invalid (excluded from every train set by the keep filter)
but carry a 1e7 feature value — only the leaky stats path can see them.

CPU-only, synthetic panel, no venue calls. Patches DEVICE so the test never
initializes CUDA (the GPU may be occupied — VRAM-lock rule).
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fxexpert import train as fxtrain  # noqa: E402

N_DAYS = 12000
# Invalid outlier rows sit INSIDE the last fold's leaky grab span: the leaky
# path indexes the full panel with filtered positions, so it reads full rows
# [0, ~n_train) regardless of the keep filter — the fixed path excludes these
# rows entirely (keep-filter), the leaky path ingests their 1e7 feature value.
BAD_LO, BAD_HI = 4000, 4101  # [BAD_LO, BAD_HI): invalid outlier rows

HP = {"d_model": 8, "n_layers": 1, "n_heads": 2, "dropout": 0.0, "lr": 1e-3,
      "epochs": 1, "batch": 512, "T": 2, "q": 0.8, "rule": "thr",
      "score_l2": 0.0, "horizon": 1}


def _synthetic_panel():
    rng = np.random.default_rng(7)
    feat0 = np.full(N_DAYS, 5.0)
    feat0[BAD_LO:BAD_HI] = 1e7                      # only the leak can see these
    features = np.stack([
        feat0,
        rng.normal(0, 1, N_DAYS),
        rng.normal(0, 1, N_DAYS),
    ], axis=1).astype(np.float32)
    vol20 = np.ones(N_DAYS, dtype=np.float32)
    vol20[BAD_LO:BAD_HI] = np.nan                   # keep-filter excludes them
    return {
        "features": features,
        "pair_idx": np.zeros(N_DAYS, dtype=np.int64),
        "date": np.arange(N_DAYS, dtype=np.int64),
        "fwd1": rng.normal(0, 0.001, N_DAYS).astype(np.float32),
        "fwd5": rng.normal(0, 0.002, N_DAYS).astype(np.float32),
        "vol20": vol20,
        "cost": np.full(N_DAYS, 1e-4, dtype=np.float32),
        "rsi_raw": np.full(N_DAYS, 50.0, dtype=np.float32),
        "mom20": np.zeros(N_DAYS, dtype=np.float32),
        "feature_names": np.array(["f0", "f1", "atr_pct"]),
    }


class TestLeakStandardizationFlag(unittest.TestCase):
    def _run(self, tag, leak):
        panel = _synthetic_panel()
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(fxtrain, "DEVICE", torch.device("cpu")):
            g = fxtrain.run_generation(tag, HP, out_dir=Path(td), seed=11,
                                       panel=panel,
                                       leak_standardization=leak)
            ck = torch.load(Path(td) / "checkpoints" / f"g{tag}.pt",
                            map_location="cpu", weights_only=True)
        return g, ck["feat_mean"].numpy(), ck["feat_std"].numpy()

    def test_fixed_arm_stats_come_from_train_rows_only(self):
        g, mu, sd = self._run("abfix", leak=False)
        self.assertEqual(g["aggregate"]["n_folds"], 3)
        # feature 0 is constant 5.0 on every valid train row of the last fold
        self.assertAlmostEqual(float(mu[0]), 5.0, places=4)
        self.assertEqual(float(sd[0]), 1.0)          # zero sd floored to 1.0

    def test_leaky_arm_stats_contaminate_from_invalid_rows(self):
        g, mu, sd = self._run("ableak", leak=True)
        self.assertEqual(g["aggregate"]["n_folds"], 3)
        # X[tr_idx] grabs full-array rows [0, n_train) for the last fold's
        # train stats — the invalid 1e7 rows inside that span blow up mu/sd
        self.assertGreater(float(mu[0]), 100.0)
        self.assertGreater(float(sd[0]), 1000.0)

    def test_default_is_leak_free(self):
        """Every existing caller (no kwarg) must get the fixed path."""
        panel = _synthetic_panel()
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(fxtrain, "DEVICE", torch.device("cpu")):
            fxtrain.run_generation("abdef", HP, out_dir=Path(td), seed=11,
                                   panel=panel)
            ck = torch.load(Path(td) / "checkpoints" / "gabdef.pt",
                            map_location="cpu", weights_only=True)
        self.assertAlmostEqual(float(ck["feat_mean"].numpy()[0]), 5.0, places=4)


if __name__ == "__main__":
    unittest.main()
