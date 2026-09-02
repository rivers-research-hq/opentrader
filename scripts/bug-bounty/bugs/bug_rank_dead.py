"""Seed bug 1: rank_on silently dead (dropna(axis=1)).

Historical ground truth: commit 9b7301a "engine: fix _cross_sectional_rank
(dropna(axis=1) killed the whole rank signal)". The buggy version drops ANY
column that contains NaN (leading momentum warm-up bars), so the entire rank
signal goes dead whenever one symbol has leading NaN. rank_on configs were
permanently inactive (0 trades).

The seed re-introduces the exact pre-fix body so the harness scores against
real, historically-verified ground truth.
"""

BUG_ID = "rank-dead"
FILE = "setup_search/engine.py"
FUNCTION = "_cross_sectional_rank"
SEVERITY = "high"  # silently disables a whole signal family; no error raised
DETECTABLE_BY = "engine"
KEYWORDS = [
    "_cross_sectional_rank", "dropna(axis=1)", "frame.columns",
    "rank signal", "rank_on", "valid.index", "leading nan",
]

# The pre-fix (buggy) function body. Replaces the entire fixed body.
BUGGY_BODY = '''def _cross_sectional_rank(mom: dict, idx: pd.Index) -> dict:
    rank = {s: np.zeros(len(idx)) for s in mom}
    frame = pd.DataFrame(mom).dropna(axis=1)
    if frame.shape[1] < 2:
        return rank
    for t in range(len(frame)):
        row = frame.iloc[t]
        vals = row.values
        order = vals.argsort().argsort()
        norm = (order / max(len(vals) - 1, 1)) * 2 - 1
        for j, s in enumerate(frame.columns):
            rank[s][t] = norm[j]
    return rank
'''

# The fixed body currently in the repo (used to locate the function start/end).
FIXED_BODY = '''def _cross_sectional_rank(mom: dict, idx: pd.Index) -> dict:
    rank = {s: np.zeros(len(idx)) for s in mom}
    frame = pd.DataFrame(mom)
    if frame.shape[1] < 2:
        return rank
    for t in range(len(frame)):
        # rank only the symbols with a valid value THIS bar; symbols with
        # NaN (e.g. warm-up bars, delisted names) get rank 0 and are not
        # candidates. Column-wise dropna would kill the whole rank signal
        # whenever any symbol has leading NaN.
        valid = frame.iloc[t].dropna()
        if len(valid) < 2:
            continue
        vals = valid.values
        order = vals.argsort().argsort()
        norm = (order / max(len(vals) - 1, 1)) * 2 - 1
        for j, s in enumerate(valid.index):
            rank[s][t] = norm[j]
    return rank
'''

# Deterministic smoke check: with one symbol having leading NaN, the buggy
# version returns all-zero ranks for every symbol (signal dead).
DETECTOR = '''
import numpy as np, pandas as pd
import setup_search.engine as E
mom = {"A": np.array([1.0, 2.0, 3.0]), "B": np.array([np.nan, 1.5, 2.5])}
idx = pd.date_range("2026-01-01", periods=3)
rank = E._cross_sectional_rank(mom, idx)
nonzero = sum(1 for s, v in rank.items() if np.any(v != 0))
print("non_zero_series=%d" % nonzero)
assert nonzero == 0, "expected rank signal dead (bug present)"
'''
