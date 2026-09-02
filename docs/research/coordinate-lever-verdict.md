# Cross-sectional latent-factor lever ("coordinate system") — research verdict

Ticket: [#89](https://github.com/darylerivers/opentrader/issues/89) · 2026-08-08 · sandbox only (ADR-0003)

## Thesis

A "shifting coordinate system" — the rolling cross-sectional eigenbasis of the universe —
carries edge that the fixed 11-dim feature space misses. In the original proposal's terms: the
ticker's position/deviations in the latent "m-point" manifold (eigenportfolio loadings /
residuals) is a real, non-noisy trading signal.

## Angles and verdicts

### Angle #1 — rotate/augment the features, gate under production hybrid — REFUTED

Transform the 11-dim features by (a) appending top-k eigenportfolio loadings, or (b) rotating
by the trailing eigenbasis; fit + gate exactly as production (hybrid: score screen selects,
trained classifier/head orders the tail). No-peek, train-only fit. Neither transform beats
identity coordinates in any window; neither beats the rule floor.

- `scripts/falsify_coord_lever.py` (noisy ceiling probe): no consistent gain.
- `scripts/rigorous_coord_lever.py` (head-only gate, no peek): identity/augment/rotate all ~0
  to +4%, all below rule floor.
- `scripts/hybrid_gate_lever.py` (production hybrid gate): margins within noise, verdict never
  changes (all FAIL).

The absolute feature coordinates carry no extra edge. The shape must be used as an *ordering*
signal, not a *representation* — which is what the m-points framing actually said.

### Angle #2 — residual-from-manifold ordering ("m-points") — SIGNAL, statistically significant

Order the score-screen tail by the ticker's **residual norm** (distance of x from its
reconstruction by the trailing top-3 eigenbasis) instead of the trained classifier. Bootstrap
vs 2000 random shuffles of the same tail:

| window | residual | random mean±std | pctile |
|---|---|---|---|
| 0 w110 | −0.82% | +1.86±2.77 | 17.3 |
| 0 w511 | +3.53% | +1.01±1.99 | 87.9 |
| **1 w612** | **+9.82%** | +3.94±2.59 | **98.9** |
| 1 w1012 | +4.39% | +1.64±1.74 | 93.0 |
| **2 w1112** | **+4.84%** | +1.46±2.14 | **91.0** |
| 2 w1218 | +3.18% | +1.73±6.94 | 58.8 |

- Significant (≥90th pctile) in 3/6 windows including both strongest epochs.
- De-meaning by per-symbol residual: epoch1 w612 stays +8.86% — the signal is partly
  NVDA/AMD/META idiosyncrasy (the bull winners) but not only that.
- Hyperparameter-stable: sweeping eigenbasis (window 20/30/50, top_k 1/3/5) keeps 5/6 windows
  ≥ +1% in 5 of 6 configs. Not a tuning artifact.
- **Caveat:** the edge is symbol-concentrated (high-idiosyncrasy names). It may be partly a
  vol/beta proxy. Needs the honest-label + deployability treatment before promotion.

### Angle #3 — residual under the honest label — PENDING (blocked)

The residual ordering is label-free (no future peeking) which is a strength; the `score_tail`
vs `top10_fwd` distinction matters for the *classifier* arm, which angle #2 replaces. Mark as
superseded unless we want a learned residual-predictor.

### Angle #4 — score_tail classifier label — SUPERSEDED by angle #2

The original classifier arm was already shown near-redundant with raw score ordering (session
text[113]); angle #2 provides a sharper, label-free orderer.

### Angle #5 — crypto universe / 5-min — DEFERRED (data missing)

The crypto data (`/tmp/opentrader-scan/data/crypto_ohlcv.pkl`) was cleared; no crypto cache in
live or sandbox. Cross-sectional structure is richer across perps than 16 large-cap US names,
so this is the highest-value untested angle. Needs a data fetch first (gather-source).

## Overall verdict

- **The "coordinate system" as a feature representation is dead** (angle #1, both gates).
- **The "m-points" mechanic as a residual-ordering signal is alive** — the first statistically
  significant, hyperparameter-stable out-of-sample edge the coordinate investigation produced.
- The lever's value is **ordering within the score tail**, not a new feature space.

## Recommended next step

Prototype the residual-from-manifold orderer as a real selector option in the sandbox epoch
engine: `_margins(selector='residual')`, replacing the classifier as the within-tail orderer,
then run the full walk-forward (gate + erosion) and the DSR bootstrap on the kept trades. If
the bootstrap holds, wire it as a candidate expert (like `classifier-orderer`) rather than
touching the feature space.

## Artifacts

- Scripts: `scripts/falsify_coord_lever.py`, `scripts/rigorous_coord_lever.py`,
  `scripts/hybrid_gate_lever.py`, `scripts/residual_manifold_lever.py`.
- Logs: `/tmp/opencode/{falsify_coord,rigorous_coord,hybrid_gate,residual_manifold}.log`.
- Report: `~/overnight-reports/opentrader-2026-08-08.md`.
