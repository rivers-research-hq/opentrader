#!/usr/bin/env python3
"""fxexpert.train — purged expanding-window walkforward training.

Protocol (pre-registered, matches the walkforward_ml XGBoost reference spans):
unique panel dates split into 4 equal quarters; test folds are quarters 2-4
(the first quarter has no train data — the reference SKIPs it too). Train =
all rows before the fold minus a 6-day purge (5d label horizon + buffer);
validation = last 10% of the train rows by date (early stopping only, no
gradient). Standardization uses train-fold stats only.

One generation = one full walkforward. Warm start: weights from the previous
promoted generation when the architecture matches, else fresh init.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn.functional as Fn

from .model import FXExpert, param_count

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "fx_expert"
T_WINDOW = 20
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


def load_panel(out_dir=OUT_DIR):
    z = np.load(out_dir / "panel.npz", allow_pickle=False)
    return {k: z[k] for k in z.files}


def _spearman(a, b):
    df = pd.DataFrame({"a": a, "b": b}).dropna()
    if len(df) < 100:
        return None
    return float(np.corrcoef(df["a"].rank(), df["b"].rank())[0, 1])


def _windows(pair_idx, n_rows, T=None):
    """Rows with a full T-observation same-pair history, and their (T,) windows
    of subset-local indices. Returns (row_indices, win_matrix)."""
    T = T or T_WINDOW
    order = {}
    for i in range(n_rows):
        order.setdefault(pair_idx[i], []).append(i)
    idxs, wins = [], []
    for pi, rows in order.items():  # rows already in date order per pair
        for j in range(T - 1, len(rows)):
            idxs.append(rows[j])
            wins.append(rows[j - T + 1: j + 1])
    return np.array(idxs, dtype=np.int64), np.stack(wins)


def _predict(model, X, bs=8192):
    model.eval()
    out = np.empty(len(X), dtype=np.float32)
    with torch.no_grad():
        for s in range(0, len(X), bs):
            out[s: s + bs] = model(X[s: s + bs].to(DEVICE)).cpu().numpy()
    return out


def _fit(X_tr, y_tr, X_val, y_val, hp, warm_state, seed, T=T_WINDOW):
    torch.manual_seed(seed)
    model = FXExpert(X_tr.shape[2], hp["d_model"], hp["n_layers"],
                     hp["n_heads"], hp["dropout"], T).to(DEVICE)
    if warm_state is not None:
        try:
            model.load_state_dict(warm_state)
        except RuntimeError:
            pass  # arch changed this generation — fresh head/stack
    opt = torch.optim.AdamW(model.parameters(), lr=hp["lr"], weight_decay=1e-4)
    score_l2 = float(hp.get("score_l2", 0.0))  # magnitude penalty → sparser
    n = len(X_tr)                              # positions under thresholding
    best_val, best_state, patience = float("inf"), None, 0
    for ep in range(hp["epochs"]):
        model.train()
        perm = torch.randperm(n)
        for s in range(0, n, hp["batch"]):
            idx = perm[s: s + hp["batch"]]
            pred = model(X_tr[idx].to(DEVICE))
            loss = Fn.huber_loss(pred, y_tr[idx].to(DEVICE), delta=1.0)
            if score_l2:
                loss = loss + score_l2 * pred.pow(2).mean()
            opt.zero_grad()
            loss.backward()
            opt.step()
        model.eval()
        with torch.no_grad():
            vl = float(Fn.huber_loss(model(X_val.to(DEVICE)), y_val, delta=1.0))
        if vl < best_val - 1e-5:
            best_val, patience = vl, 0
            best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
        else:
            patience += 1
            if patience >= 6:
                break
    if best_state is not None:
        model.load_state_dict(best_state)
    return model, best_val


def run_generation(tag, hp, warm_tag=None, out_dir=OUT_DIR, seed=11, panel=None,
                   warm_states=None, leak_standardization=False):
    """One walkforward. Warm start: fold fi inherits ONLY fold fi of the
    warm generation (same train window) — sharing the last fold's weights
    across folds leaked future data into earlier folds (caught 2026-09-06,
    see fx-expert-loop doc §v0.2).

    leak_standardization=True reintroduces the pre-#244 standardization bug
    (mu/sd indexed without the keep-filter map, so out-of-fold rows incl.
    future data enter the stats). DEBUG-ONLY arm of the #249 leak A/B —
    never for search, gate, or promotion runs."""
    panel = panel or load_panel(out_dir)
    T = int(hp.get("T", T_WINDOW))
    X_all = panel["features"]
    pair_idx = panel["pair_idx"]
    day = panel["date"]  # day numbers since epoch (set by fxexpert.data)
    horizon = int(hp.get("horizon", 5))
    fwd1 = panel["fwd1"]
    fwdh = panel.get(f"fwd{horizon}", panel["fwd5"])  # label horizon
    vol20 = panel["vol20"]

    keep = ~(np.isnan(fwdh) | np.isnan(vol20) | (vol20 <= 0))
    y5 = np.clip(fwdh / (vol20 * np.sqrt(float(horizon))), -5, 5).astype(np.float32)

    pos_v, win_all = _windows(pair_idx, len(X_all), T)  # global row indices
    valid = keep[win_all].all(axis=1)  # every window row must carry a valid label
    idx_keep = pos_v[valid]
    win_k = win_all[valid]
    X = X_all  # gather windows from the FULL array via global indices
    y, f1, fh, pi, day_k = y5[idx_keep], fwd1[idx_keep], fwdh[idx_keep], pair_idx[idx_keep], day[idx_keep]

    udays = np.unique(day_k)
    n = len(udays)
    folds = []
    for q in (1, 2, 3):
        lo = udays[int(n * 0.25 * q)]
        hi = udays[int(n * 0.25 * (q + 1)) - 1]
        folds.append((lo, hi))

    ckpt_dir = out_dir / "checkpoints"
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    warm_by_fold = {}
    if warm_tag:
        for fi in range(len(folds)):
            p = ckpt_dir / f"g{warm_tag}_f{fi}.pt"
            if p.exists():
                warm_by_fold[fi] = torch.load(p, map_location=DEVICE,
                                              weights_only=True)["state_dict"]
    if warm_states:  # explicit fold->state_dict, e.g. a checkpoint transferred
        warm_by_fold.update(warm_states)  # across a feature-count change

    g = {"tag": tag, "hp": hp, "device": str(DEVICE), "params": None,
         "horizon": horizon, "folds": [], "warm_from": warm_tag}
    fold_cfg = {"n_feat": None, "d_model": hp["d_model"],
                "n_layers": hp["n_layers"], "n_heads": hp["n_heads"],
                "dropout": hp["dropout"], "T": T,
                "rule": hp.get("rule", "thr"), "q": float(hp.get("q", 0.8)),
                "k": int(hp.get("k", 3))}
    P = {"date": [], "pair_idx": [], "score": [], "fwd1": [], "fwdh": [],
         "cost": [], "fold": [], "q_long": [], "q_short": [], "q_mid": [],
         "rsi_raw": [], "mom20": [], "vol20": [], "atr_pct": []}
    for fi, (lo, hi) in enumerate(folds):
        tr_mask = day_k <= lo - (horizon + 1)  # purge = label horizon + 1
        te_mask = (day_k >= lo) & (day_k <= hi)
        n_tr = int(tr_mask.sum())
        if n_tr < 2000 or int(te_mask.sum()) < 500:
            g["folds"].append({"fold": fi, "verdict": "SKIP",
                               "n_train": n_tr, "n_test": int(te_mask.sum())})
            continue
        tr_idx = np.where(tr_mask)[0]
        tr_idx, val_idx = tr_idx[:-max(500, len(tr_idx) // 10)], tr_idx[-max(500, len(tr_idx) // 10):]

        # tr_idx are positions in the keep-FILTERED arrays; map back to global
        # row indices before indexing the FULL panel X, else whole pairs across
        # their entire history (incl. future data) leak into mu/sd.
        # The leaky arm (DEBUG-ONLY, #249 A/B) skips the map: X[tr_idx] grabs
        # full-array rows regardless of the keep filter, so invalid and
        # out-of-fold rows contaminate the stats exactly as pre-#244.
        stats_idx = tr_idx if leak_standardization else idx_keep[tr_idx]
        mu = X[stats_idx].mean(axis=0)
        sd = X[stats_idx].std(axis=0)
        sd[sd < 1e-8] = 1.0
        Xs = np.clip((X - mu) / sd, -8, 8).astype(np.float32)
        Xs = np.nan_to_num(Xs)

        X_tr = torch.from_numpy(Xs[win_k[tr_idx]]).to(DEVICE)
        y_tr = torch.from_numpy(y[tr_idx]).to(DEVICE)
        X_val = torch.from_numpy(Xs[win_k[val_idx]]).to(DEVICE)
        y_val = torch.from_numpy(y[val_idx]).to(DEVICE)
        X_te = torch.from_numpy(Xs[win_k[te_mask]]).to(DEVICE)

        model, val_loss = _fit(X_tr, y_tr, X_val, y_val, hp,
                               warm_by_fold.get(fi), seed + fi, T)
        tr_pred = _predict(model, X_tr)
        te_pred = _predict(model, X_te)

        q = float(hp.get("q", 0.8))  # entry quantile; exit hysteresis at median
        q_long = float(np.quantile(tr_pred, q))
        q_short = float(np.quantile(tr_pred, 1.0 - q))
        q_mid = float(np.quantile(tr_pred, 0.5))
        ic = _spearman(te_pred, fh[te_mask])
        acc = float(np.mean(np.sign(te_pred) == np.sign(fh[te_mask])))
        g["folds"].append({"fold": fi, "horizon": horizon,
                           "span": [str(pd.Timestamp(int(lo), unit="D").date()),
                                                str(pd.Timestamp(int(hi), unit="D").date())],
                           "n_train": len(tr_idx), "n_test": int(te_mask.sum()),
                           "val_loss": round(val_loss, 5), "ic_oos": None if ic is None else round(ic, 5),
                           "acc_oos": round(acc, 4)})
        P["date"].append(day_k[te_mask])
        P["pair_idx"].append(pi[te_mask])
        P["score"].append(te_pred)
        P["fwd1"].append(f1[te_mask])
        P["fwdh"].append(fh[te_mask])
        P["cost"].append(panel["cost"][idx_keep[te_mask]])
        P["fold"].append(np.full(int(te_mask.sum()), fi))
        P["q_long"].append(np.full(int(te_mask.sum()), q_long))
        P["q_short"].append(np.full(int(te_mask.sum()), q_short))
        P["q_mid"].append(np.full(int(te_mask.sum()), q_mid))
        P["rsi_raw"].append(panel["rsi_raw"][idx_keep[te_mask]])
        P["mom20"].append(panel["mom20"][idx_keep[te_mask]])
        P["vol20"].append(vol20[idx_keep[te_mask]])
        P["atr_pct"].append(panel["features"][idx_keep[te_mask]][:,
                             list(panel["feature_names"]).index("atr_pct")].astype(np.float32))

        if g["params"] is None:
            g["params"] = param_count(model)
            fold_cfg["n_feat"] = X.shape[1]
        # per-fold checkpoint: the ONLY thing the next generation may inherit
        torch.save({"state_dict": {k: v.detach().cpu().clone()
                                   for k, v in model.state_dict().items()},
                    "config": fold_cfg},
                   ckpt_dir / f"g{tag}_f{fi}.pt")
        last_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
        last_mu, last_sd = mu, sd

    # save artifacts from the last trained fold (the freshest regime)
    ckpt = {"state_dict": last_state, "config": fold_cfg, "tag": tag,
            "feat_mean": torch.from_numpy(last_mu), "feat_std": torch.from_numpy(last_sd),
            "q_long": q_long, "q_short": q_short, "q_mid": q_mid}
    torch.save(ckpt, ckpt_dir / f"g{tag}.pt")

    P = {k: np.concatenate(v) for k, v in P.items()}
    np.savez_compressed(out_dir / f"preds_g{tag}.npz", **P)
    # OOS score export for backtest variants (trailing/TP A/B)
    np.savez_compressed(out_dir / f"oos_scores_g{tag}.npz",
                        day=P["date"], pair_idx=P["pair_idx"], score=P["score"],
                        fwd1=P["fwd1"], fold=P["fold"], atr_pct=P["atr_pct"],
                        cost=P["cost"], vol20=P["vol20"])


    ics = [f["ic_oos"] for f in g["folds"] if f.get("ic_oos") is not None]
    g["aggregate"] = {"ic_mean": None if not ics else round(float(np.mean(ics)), 5),
                      "folds_positive": sum(1 for i in ics if i > 0), "n_folds": len(ics)}
    (out_dir / f"train_g{tag}.json").write_text(json.dumps(g, indent=1))
    print(f"[train g{tag}] params {g['params']}, folds {len(ics)}, "
          f"OOS IC mean {g['aggregate']['ic_mean']}, "
          f"positive {g['aggregate']['folds_positive']}/{len(ics)}")
    return g


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="00")
    ap.add_argument("--d-model", type=int, default=96)
    ap.add_argument("--layers", type=int, default=3)
    ap.add_argument("--heads", type=int, default=4)
    ap.add_argument("--dropout", type=float, default=0.15)
    ap.add_argument("--lr", type=float, default=7e-4)
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--batch", type=int, default=4096)
    ap.add_argument("--warm", default=None)
    a = ap.parse_args()
    hp = {"d_model": a.d_model, "n_layers": a.layers, "n_heads": a.heads,
          "dropout": a.dropout, "lr": a.lr, "epochs": a.epochs, "batch": a.batch}
    run_generation(a.tag, hp, a.warm)
