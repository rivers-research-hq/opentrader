"""fxexpert — recursive FX expert training loop (ADR-0009 seam).

Generations: build panel -> train (warm-started from best) -> OOS gate ->
promote only if the gate passes -> repeat as the accrual store grows.
State lives in data/fx_expert/. Shadow-only; live order flow needs human
signoff per ADR-0009 §4.
"""
