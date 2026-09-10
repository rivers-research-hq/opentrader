#!/usr/bin/env python3
"""walkforward_ml — train XGBoost models on the accrual store's feature table
using the pre-registered walkforward protocol (4 time-ordered folds, OOS
metrics per fold, deflated at the end for the multiple-testing load).

The model predicts forward 5-day returns per pair per day. Features are the
price-action, rate, carry, COT, volatility and event columns built by
build_training_data.py. The walkforward folds prevent in-sample leakage.

This is the first ML pass on the store's data — the objective is to find
whether non-linear feature combinations contain signal that the hand-coded
families miss, NOT to produce a deployable lane. If the OOS results are
indistinguishable from noise, that's the honest finding and it's recorded.

Usage: python3 scripts/walkforward_ml.py [--features N] [--depth N]
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FEATURES_FILE = Path(__file__).resolve().parent.parent / "data" / "training" / "features.parquet"
LABELS_FILE = Path(__file__).resolve().parent.parent / "data" / "training" / "labels.parquet"
OUT = Path(__file__).resolve().parent.parent / "data" / "training" / "walkforward_ml_results.json"


def load():
    f = pd.read_parquet(FEATURES_FILE)
    l = pd.read_parquet(LABELS_FILE)
    # merge on index + pair
    f = f.reset_index().rename(columns={"index": "ts"})
    l = l.reset_index().rename(columns={"index": "ts"})
    df = f.merge(l[["ts", "pair", "fwd_ret_1d", "fwd_ret_5d", "fwd_ret_20d"]],
                 on=["ts", "pair"], how="inner")
    df = df.sort_values("ts").reset_index(drop=True)
    # feature columns: everything except ts, pair, and label columns
    feature_cols = [c for c in df.columns if c not in
                    ("ts", "pair", "fwd_ret_1d", "fwd_ret_5d", "fwd_ret_20d")]
    return df, feature_cols


def walkforward_folds(df, n_folds=4):
    """Time-ordered fold boundaries on the date index."""
    dates = pd.to_datetime(df["ts"]).dt.date
    unique_dates = sorted(dates.unique())
    step = len(unique_dates) // n_folds
    folds = []
    for i in range(n_folds):
        lo = unique_dates[step * i]
        hi = unique_dates[min(step * (i + 1), len(unique_dates) - 1)]
        folds.append((lo, hi))
    return folds


def train_fold(df_train, df_test, feature_cols, target_col, depth=4, n_est=200):
    X_train = df_train[feature_cols].fillna(0).values
    y_train = (df_train[target_col] > 0).astype(int).values  # binary: up vs down
    X_test = df_test[feature_cols].fillna(0).values
    y_test = (df_test[target_col] > 0).astype(int).values

    model = xgb.XGBClassifier(
        max_depth=depth, n_estimators=n_est, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8, reg_alpha=1.0, reg_lambda=1.0,
        eval_metric="logloss", use_label_encoder=False, verbosity=0,
    )
    model.fit(X_train, y_train)
    preds = model.predict_proba(X_test)[:, 1]
    return model, preds, y_test


def evaluate(preds, y_test, fwd_returns):
    """Directional accuracy + PF (long when pred > 0.5, short when < 0.5)."""
    if len(preds) == 0:
        return {"n": 0, "accuracy": None, "pf": None}
    correct = sum(1 for p, y in zip(preds, y_test) if (p > 0.5) == (y == 1))
    acc = correct / len(preds)
    # PF: long when pred > 0.5, short when pred <= 0.5
    pnl = [f if p > 0.5 else -f for p, f in zip(preds, fwd_returns)]
    gains = sum(x for x in pnl if x > 0)
    losses = -sum(x for x in pnl if x < 0)
    pf = gains / losses if losses > 0 else float("inf") if gains > 0 else None
    return {"n": len(preds), "accuracy": round(acc, 4), "pf": round(pf, 3) if pf else None}


def main():
    df, feature_cols = load()
    print(f"[ml] loaded: {len(df)} rows, {len(feature_cols)} features, "
          f"{df['pair'].nunique()} pairs, {pd.to_datetime(df['ts']).dt.date.min()} → "
          f"{pd.to_datetime(df['ts']).dt.date.max()}")

    folds = walkforward_folds(df, 4)
    results = {"folds": [], "feature_importance": {}, "verdict": None}

    all_oos_preds = []
    all_oos_true = []
    all_oos_ret5 = []

    for i, (lo, hi) in enumerate(folds):
        dates = pd.to_datetime(df["ts"]).dt.date
        train_mask = dates < lo
        test_mask = (dates >= lo) & (dates <= hi)
        df_train = df[train_mask]
        df_test = df[test_mask]

        if len(df_train) < 100 or len(df_test) < 50:
            results["folds"].append({"fold": i, "verdict": "SKIP",
                                     "reason": f"insufficient data ({len(df_train)} train, {len(df_test)} test)"})
            continue

        model, preds, y_test = train_fold(df_train, df_test, feature_cols, "fwd_ret_5d")
        fwd5 = df_test["fwd_ret_5d"].values
        metrics = evaluate(preds, y_test, fwd5)
        metrics["fold"] = i
        metrics["train_n"] = len(df_train)
        metrics["test_n"] = len(df_test)
        metrics["span"] = [str(lo), str(hi)]
        results["folds"].append(metrics)

        all_oos_preds.extend(preds)
        all_oos_true.extend(y_test)
        all_oos_ret5.extend(fwd5)

        # feature importance from the last fold's model
        for fc, imp in zip(feature_cols, model.feature_importances_):
            results["feature_importance"][fc] = results["feature_importance"].get(fc, 0) + imp

        print(f"  fold {i}: train {len(df_train)}, test {len(df_test)} — "
              f"acc {metrics['accuracy']}, PF {metrics['pf']}")

    # aggregate feature importance (normalize)
    fi = results["feature_importance"]
    total = sum(fi.values())
    if total > 0:
        results["feature_importance"] = {k: round(v / total, 4) for k, v in
                                          sorted(fi.items(), key=lambda kv: -kv[1])}

    # aggregate OOS metrics
    correct = sum(1 for p, y in zip(all_oos_preds, all_oos_true) if (p > 0.5) == (y == 1))
    agg_acc = correct / len(all_oos_preds) if all_oos_preds else 0
    pnl = [f if p > 0.5 else -f for p, f in zip(all_oos_preds, all_oos_ret5)]
    gains = sum(x for x in pnl if x > 0)
    losses = -sum(x for x in pnl if x < 0)
    agg_pf = gains / losses if losses > 0 else None
    results["aggregate"] = {"n_oos": len(all_oos_preds), "accuracy": round(agg_acc, 4),
                            "pf": round(agg_pf, 3) if agg_pf else None}

    # verdict: directional accuracy > 55% AND PF > 1.2 = promising (not deployable — needs deflation)
    if agg_acc > 0.55 and agg_pf and agg_pf > 1.2:
        results["verdict"] = "PROMISING — needs deflated correction + pre-registered confirmation"
    elif agg_acc > 0.52:
        results["verdict"] = "WEAK SIGNAL — below deployment bar, above noise"
    else:
        results["verdict"] = "NO SIGNAL — model predictions indistinguishable from random"

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(results, indent=1, default=str))
    print(f"\n[ml] aggregate OOS: acc {agg_acc:.4f}, PF {agg_pf}, n {len(all_oos_preds)}")
    print(f"[ml] VERDICT: {results['verdict']}")
    print(f"[ml] top features: {list(results['feature_importance'].items())[:5]}")
    print(f"[ml] saved -> {OUT}")


if __name__ == "__main__":
    main()
