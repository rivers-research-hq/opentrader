# Risk Scorer Baseline — 0.95-0.99 Maker Lane

**Date:** 2026-08-27
**Data:** `shadow_maker_results.csv` (717 fills) + `shadow_maker_single_results.csv` (23 fills) = 740 total
**Label:** pnl > 0 (win) vs pnl < 0 (loss)
**Class balance:** 710 wins / 30 losses

## Headline

The model achieves **AUC 1.0000** (5-fold CV) on the full dataset. But this is **trivially separable** — the single most important feature is `fav_price` (GB importance = 1.0), and the separation is essentially "is fav_price > 0.90?"

## What the model actually learned

| Feature | GB Importance | LR Coefficient |
|---|---|---|
| **fav_price** | **1.0000** | +2.43 |
| fav_side_enc | 0.0000 | +4.05 |
| price_bin_enc | 0.0000 | -2.28 |
| series_enc | 0.0000 | +1.02 |
| ask_low | 0.0000 | +0.66 |
| ask_close | 0.0000 | +0.65 |
| quote | 0.0000 | +0.66 |
| mid | 0.0000 | +0.41 |
| volume | 0.0000 | +0.08 |
| d_mid | 0.0000 | -0.04 |

The model is a **bin-boundary detector**, not a risk scorer. It separates "other" bin (fav_price < 0.90) from the high bins (fav_price ≥ 0.90).

## Within the 0.95-0.99 bin: NO signal

- **456 fills, 456 wins, 0 losses**
- Model predictions: all exactly 1.0000 (no variance)
- The model cannot distinguish "safe" 0.95-0.99 fills from "risky" ones because **there are no losses in this bin to learn from**

## Within the "other" bin: fav_price is the separator

- 165 fills: 135W / 30L
- **All 30 losses have fav_price = 0.505** (the coin-flip KXGOLDH markets)
- Wins have fav_price mean = 0.793 (std 0.074)
- Losses have fav_price mean = 0.505 (std 0.000)
- A simple threshold `fav_price > 0.60` separates all 30 losses from all 135 wins

## Threshold analysis (full dataset, GB)

| Threshold | Fills passing | W/L | Win rate |
|---|---|---|---|
| p ≥ 0.500 | 710/740 | 710W/0L | 100% |
| p ≥ 0.900 | 710/740 | 710W/0L | 100% |
| p ≥ 0.975 | 710/740 | 710W/0L | 100% |
| p ≥ 0.990 | 710/740 | 710W/0L | 100% |

The model is so confident in the bin separation that even at p ≥ 0.99, all 710 wins pass and all 30 losses are rejected.

## What this means for the 0.95-0.99 strategy

1. **The model confirms the bin filter works.** All 30 losses are in the "other" bin (fav_price < 0.90). The 0.95-0.99 bin has zero losses in the sim.

2. **The model cannot help within the 0.95-0.99 bin.** There's no loss data in this bin to learn from. The 97.5% breakeven question remains unanswered by the model.

3. **The real risk is not captured by the current features.** The 30 losses are all coin-flip markets (fav_price = 0.505) that happened to be in the "other" bin. The 0.95-0.99 bin's risk profile is fundamentally different — these are deep favorites, not coin flips.

4. **The model's value is as a guardrail, not a filter.** It can reject fills that look like the "other" bin profile (low fav_price), but it cannot rank fills within the 0.95-0.99 bin by risk.

## What would make the model useful

To get within-bin signal, we need:
- **Losses in the 0.95-0.99 bin** (from live trading or longer sim history)
- **Richer features**: time-to-settlement (`lead_h`), market age (`n_candles`), volume trends, spread dynamics, series-specific risk profiles
- **More data**: 740 fills is small; the 30 losses are all one profile (coin-flip KXGOLDH)

## Recommendation

The ML approach is **not the bottleneck** for the 0.95-0.99 lane. The bin filter already eliminates the loss profile. The real questions are:

1. **V10 (queue dynamics)**: Does the 70.1% fill rate hold in production?
2. **V11 (month-scale persistence)**: Does the 0.95-0.99 edge persist over months?
3. **True win rate in 0.95-0.99**: Is it 100% (as observed) or 97.5% (breakeven)? The model can't answer this without losses in the bin.

The $100 deployment (if the RESUME.md binding rule is overruled) would be the data-collection phase for answering #3. Until then, the model's contribution is: **confirm the bin filter is sufficient, and flag any fill that looks like the "other" bin profile.**
