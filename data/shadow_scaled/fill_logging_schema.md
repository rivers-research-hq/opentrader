# Fill-Logging Schema — 0.95-0.99 Maker Lane

**Date:** 2026-08-27
**Status:** Spec only. No live order flow. Shadow/sim only (RESUME.md binding rule).

## Premise

The sim CSVs (`shadow_maker_results.csv`, `shadow_maker_single_results.csv`) already
capture 16 of 18 needed columns at fill time. The only genuinely missing fields are:

| Field | Source | Derivation |
|---|---|---|
| `lead_h` | `pm_kalshi_live3_real.pkl` | `(close_ts - fill_ts) / 3600` |
| `spread_at_fill` | `pm_kalshi_1min_flat.pkl` | `spread` column of the fill candle |

No new opentrader integration is needed. The schema is "formalize the sim CSV +
settlement join + 2 derived columns."

## Canonical fill record (19 columns)

| # | Column | Type | Source | Notes |
|---|---|---|---|---|
| 1 | `ts` | int64 (unix s) | sim CSV | Fill candle timestamp |
| 2 | `ticker` | str | sim CSV | Market ticker |
| 3 | `series` | str | sim CSV | Event series (e.g. KXGOLDH) |
| 4 | `fav_side` | str | sim CSV | "yes" or "no" — **constant per market** (from p_first_real) |
| 5 | `fav_price` | float | sim CSV | Favorite price at first-real candle — **constant per market** |
| 6 | `price_bin` | str | sim CSV | "0.90-0.95" / "0.95-0.99" / "0.99-1.00" / "other" — **constant per market** |
| 7 | `event_cluster_id` | str | sim CSV | Series-level cluster proxy |
| 8 | `mid` | float | sim CSV | Mid at fill candle (varies per candle) |
| 9 | `ask_close` | float | sim CSV | Ask close at fill candle |
| 10 | `ask_low` | float | sim CSV | Ask low at fill candle |
| 11 | `quote` | float | sim CSV | Posted bid = ask_close - 1 tick |
| 12 | `filled` | bool | sim CSV | Whether the touch-and-hold rule triggered |
| 13 | `fill_px` | float | sim CSV | Fill price (= quote when filled) |
| 14 | `settle` | float | sim CSV | 1.0 if fav wins, 0.0 if loses |
| 15 | `pnl` | float | sim CSV | settle - quote (per contract) |
| 16 | `d_mid` | float | sim CSV | mid[i+1] - mid[i] (adverse selection proxy) |
| 17 | `volume` | float | sim CSV | Candle volume |
| 18 | `lead_h` | float | **NEW** | Hours from fill to settlement: `(close_ts - ts) / 3600` |
| 19 | `spread_at_fill` | float | **NEW** | `spread` column of the fill candle from flat pkl |

**19 columns total** (17 from sim CSV + 2 derived).

**Key convention:** `fav_side`, `fav_price`, and `price_bin` are **constant per market**
(derived from `p_first_real` at the first-real candle), not per-candle. This matches
the primary flat pkl (`pm_kalshi_1min_flat.pkl`). The per-candle `mid` varies, but the
market's bin assignment does not change over its lifetime.

## Settlement join

The sim CSVs already have `settle` and `pnl` computed. For the extended schema,
`lead_h` requires the market's `close_ts`, which lives in the source metadata pkl
(`pm_kalshi_live3_real.pkl` for the primary sample, or the equivalent for extended
samples). The join key is `ticker`.

```
lead_h = (close_ts - fill_ts) / 3600.0
```

Where:
- `close_ts` = market settlement timestamp (from metadata pkl)
- `fill_ts` = `ts` column of the fill row (the candle at which the fill occurred)

## spread_at_fill

The flat pkl (`pm_kalshi_1min_flat.pkl`) has a `spread` column per candle.
For a fill at row index `i` in the per-market candle sequence, `spread_at_fill`
is simply `spread[i]` from the flat pkl. No additional API call needed.

## What this enables

1. **Within-bin risk modeling**: With `lead_h` and `spread_at_fill`, the next model
   iteration can test whether fills late in the market's life (low `lead_h`) or in
   wide-spread conditions carry different risk profiles.

2. **Backward sim extension**: The same schema applies to extended samples
   (e.g. Aug 17-24). If the true in-bin win rate is 97.5% rather than 100%,
   losses will appear in the 0.95-0.99 bin with enough fills, giving the model
   within-bin signal.

3. **Live trading readiness**: If/when the RESUME.md binding rule is overruled
   and live trading begins, the opentrader fill logger should emit records in
   this exact schema. The 2 derived columns (`lead_h`, `spread_at_fill`) are
   computable at fill time from data already available to the trading engine.

## What this does NOT enable

- **Queue dynamics (V10)**: The 1-min candle proxy cannot capture queue position,
  partial fills, or order book depth. Only live book capture can answer V10.
- **Month-scale persistence (V11)**: Requires holdout samples weeks out, not
  schema changes.
- **Intra-bar path**: The touch-and-hold rule is a conservative proxy. The schema
  captures the candle-level state, not the intra-bar price path.

## File layout (additive, no overwrites)

```
opentrader/data/shadow_scaled/
  fill_logging_schema.md          # this file
  pm_pull_extended.py             # backward extension pull script
  pm_kalshi_extended_real.pkl     # extended market metadata (NEW)
  pm_kalshi_extended_1min.pkl     # extended 1-min candles (NEW)
  pm_kalshi_extended_1min.manifest.json
  shadow_maker_extended_results.csv  # sim output, 19-col schema
  shadow_maker_extended_summary.csv
  shadow_maker_extended_gate.txt
  shadow_maker_extended_diag.json
```

All new files. Never overwrites the primary sample pkls or CSVs.

## Audit gate compliance

- **Writers**: Only `pm_pull_extended.py` writes the extended pkls.
  Only `pm_shadow_maker.py` (parameterized) writes the extended CSVs.
  No other process touches these files.
- **Atomicity**: Pickle writes are single-process, single-thread.
  CSV writes are single `to_csv()` call.
- **Source of truth**: The extended pkls are the source of truth for the extended
  sample. The primary pkls remain the source of truth for the primary sample.
  No cross-contamination.

## Related files

- `risk_scorer_baseline.md` — risk scoring baseline (this directory)
- `RESUME.md` — binding rules (in `toc-tasks/kalshi-favoredge/`)
