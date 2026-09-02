"""
pm_shadow_maker: Shadow maker simulator for the Kalshi favorite-edge maker lane.
Targets V08 (adverse selection) and V09 (realized fill rate); answers Q01.
Reads pm_kalshi_1min_flat.pkl. No API calls. No capital.
"""
import pickle, json, time
import numpy as np
import pandas as pd
from security.guards import guarded_urlopen, guarded_open, sec_pickle_load  # noqa: E402  (hardening layer)

OUT = "/home/mrc/opentrader/data/shadow_scaled"
SRC = f"{OUT}/pm_kalshi_1min_flat.pkl"
SRC_META = f"{OUT}/pm_kalshi_live3_real.pkl"
TICK = 0.01
NBOOT = 4000
SEED = 42
MIN_CANDLES = 10
BINS = [(0.90, 0.95), (0.95, 0.99), (0.99, 1.00)]
BIN_LABELS = ["0.90-0.95", "0.95-0.99", "0.99-1.00"]


def load_and_filter():
    rows = sec_pickle_load(open(SRC, "rb"))
    df = pd.DataFrame(rows)
    # merge result from source pkl (flat pkl has no result column)
    src = pd.read_pickle(SRC_META)
    result_map = dict(zip(src["ticker"], src["result"]))
    df["result"] = df["ticker"].map(result_map)
    n_total = df["ticker"].nunique()
    cc = df.groupby("ticker").size()
    keep_candles = cc[cc >= MIN_CANDLES].index
    df = df[df["ticker"].isin(keep_candles)]
    n_after_candles = df["ticker"].nunique()
    vol_by_mkt = df.groupby("ticker")["volume"].max()
    keep_vol = vol_by_mkt[vol_by_mkt > 0].index
    df = df[df["ticker"].isin(keep_vol)]
    n_after_vol = df["ticker"].nunique()
    df = df.sort_values(["ticker", "ts"]).reset_index(drop=True)
    finfo = {
        "n_markets_total": n_total,
        "n_markets_after_candle_filter": n_after_candles,
        "n_markets_after_vol_filter": n_after_vol,
        "min_candles": MIN_CANDLES,
        "n_candles_total": len(df),
    }
    return df, finfo


def simulate(df):
    records = []
    for tkr in df["ticker"].unique():
        mkt = df[df["ticker"] == tkr].reset_index(drop=True)
        if len(mkt) < 2:
            continue
        fav_side = mkt["fav_side"].iloc[0]
        fav_price = mkt["fav_price"].iloc[0]
        price_bin = mkt["price_bin"].iloc[0]
        cluster = mkt["event_cluster_id"].iloc[0]
        result = int(mkt["result"].iloc[0])
        # settle = 1 if favorite wins, 0 if loses
        settle = float(result) if fav_side == "yes" else float(1 - result)
        # start quoting from first-real candle (spread <= 0.10) to match V03 baseline
        real = mkt[mkt["spread"] <= 0.10]
        start_i = real.index[0] if len(real) else 0
        for i in range(start_i, len(mkt)):
            row = mkt.iloc[i]
            ask_c = row["ask_close"]
            ask_l = row["ask_low"]
            mid_t = row["mid"]
            if i + 1 < len(mkt):
                mid_next = mkt["mid"].iloc[i + 1]
                d_mid = (mid_next - mid_t) if (mid_next is not None and mid_t is not None) else None
            else:
                d_mid = None
            quote = None
            filled = False
            fill_px = None
            pnl = None
            if ask_c is not None and 0 < ask_c < 1:
                q = ask_c - TICK
                if 0 < q < 1:
                    quote = q
                    if ask_l is not None and ask_c is not None:
                        if ask_l <= quote and ask_c >= quote:
                            filled = True
                            fill_px = quote
                            pnl = settle - quote
            records.append({
                "ts": row["ts"], "ticker": tkr, "series": row["series"],
                "fav_side": fav_side, "fav_price": fav_price,
                "price_bin": price_bin, "event_cluster_id": cluster,
                "mid": mid_t, "ask_close": ask_c, "ask_low": ask_l,
                "quote": quote, "filled": filled, "fill_px": fill_px,
                "settle": settle, "pnl": pnl, "d_mid": d_mid,
                "volume": row["volume"],
            })
    return pd.DataFrame(records)


def cluster_bootstrap(pnl_by_cluster, nboot=NBOOT, seed=SEED):
    clusters = list(pnl_by_cluster.keys())
    all_pnl = np.concatenate([pnl_by_cluster[c] for c in clusters])
    n = len(all_pnl)
    if n == 0:
        return 0.0, 0.0, 0.0
    mean = all_pnl.mean()
    rng = np.random.default_rng(seed)
    boots = np.empty(nboot)
    for b in range(nboot):
        chosen = rng.choice(clusters, size=len(clusters), replace=True)
        sample = np.concatenate([pnl_by_cluster[c] for c in chosen])
        boots[b] = sample.mean()
    lo = np.percentile(boots, 2.5)
    hi = np.percentile(boots, 97.5)
    return mean, lo, hi


def compute_metrics(recs):
    results = {"overall": {}, "by_bin": {}}
    quoted = recs[recs["quote"].notna()]
    fills = quoted[quoted["filled"]]
    no_fills = quoted[~quoted["filled"]]
    n_quotes = len(quoted)
    n_fills = len(fills)
    fill_rate = n_fills / n_quotes if n_quotes > 0 else 0.0
    fill_edge = (fills["pnl"].values * 100).mean() if n_fills > 0 else 0.0
    d_mid_fill = fills["d_mid"].dropna()
    d_mid_nofill = no_fills["d_mid"].dropna()
    e_dmid_fill = d_mid_fill.mean() * 100 if len(d_mid_fill) > 0 else None
    e_dmid_nofill = d_mid_nofill.mean() * 100 if len(d_mid_nofill) > 0 else None
    as_ratio = (e_dmid_fill / e_dmid_nofill) if (e_dmid_nofill is not None and e_dmid_nofill != 0) else None
    pnl_by_cluster = {}
    for _, r in fills.iterrows():
        pnl_by_cluster.setdefault(r["event_cluster_id"], []).append(r["pnl"])
    pnl_by_cluster = {k: np.array(v) for k, v in pnl_by_cluster.items()}
    bm, blo, bhi = cluster_bootstrap(pnl_by_cluster)
    results["overall"] = {
        "n_quotes": n_quotes, "n_fills": n_fills, "fill_rate": fill_rate,
        "fill_edge_c": fill_edge, "boot_mean_c": bm * 100,
        "boot_lo_c": blo * 100, "boot_hi_c": bhi * 100,
        "e_dmid_fill_c": e_dmid_fill, "e_dmid_nofill_c": e_dmid_nofill,
        "as_ratio": as_ratio,
    }
    for label in BIN_LABELS:
        b = recs[recs["price_bin"] == label]
        bq = b[b["quote"].notna()]
        bf = bq[bq["filled"]]
        bnf = bq[~bq["filled"]]
        nq, nf = len(bq), len(bf)
        fr = nf / nq if nq > 0 else 0.0
        fe = (bf["pnl"].values * 100).mean() if nf > 0 else 0.0
        dm_f = bf["d_mid"].dropna()
        dm_nf = bnf["d_mid"].dropna()
        edf = dm_f.mean() * 100 if len(dm_f) > 0 else None
        ednf = dm_nf.mean() * 100 if len(dm_nf) > 0 else None
        ar = (edf / ednf) if (ednf is not None and ednf != 0) else None
        pbc = {}
        for _, r in bf.iterrows():
            pbc.setdefault(r["event_cluster_id"], []).append(r["pnl"])
        pbc = {k: np.array(v) for k, v in pbc.items()}
        bm2, blo2, bhi2 = cluster_bootstrap(pbc) if pbc else (0, 0, 0)
        results["by_bin"][label] = {
            "n_quotes": nq, "n_fills": nf, "fill_rate": fr,
            "fill_edge_c": fe, "boot_mean_c": bm2 * 100,
            "boot_lo_c": blo2 * 100, "boot_hi_c": bhi2 * 100,
            "e_dmid_fill_c": edf, "e_dmid_nofill_c": ednf, "as_ratio": ar,
        }
    return results


def apply_gate(metrics):
    o = metrics["overall"]
    bins = metrics["by_bin"]
    reasons = []
    go = True
    kill = False
    if o["boot_lo_c"] <= 0 <= o["boot_hi_c"]:
        go = False
        reasons.append(f"overall CI [{o['boot_lo_c']:.2f},{o['boot_hi_c']:.2f}] includes 0")
    elif o["boot_mean_c"] <= 0:
        go = False
        kill = True
        reasons.append(f"overall edge {o['boot_mean_c']:.2f}c <= 0")
    as_ok = sum(1 for l in BIN_LABELS if bins[l]["as_ratio"] is not None and bins[l]["as_ratio"] < 1)
    if as_ok < 2:
        go = False
        reasons.append(f"AS ratio <1 in only {as_ok}/3 bins (need >=2)")
    if o["fill_rate"] < 0.10:
        if o["fill_rate"] < 0.05:
            kill = True
            reasons.append(f"fill rate {o['fill_rate']*100:.1f}% < 5% (KILL)")
        else:
            go = False
            reasons.append(f"fill rate {o['fill_rate']*100:.1f}% < 10% (CONDITIONAL)")
    worst_bin = min(BIN_LABELS, key=lambda l: bins[l]["fill_edge_c"])
    if bins[worst_bin]["fill_edge_c"] <= 0:
        go = False
        reasons.append(f"worst bin {worst_bin} edge {bins[worst_bin]['fill_edge_c']:.2f}c <= 0")
    neg_bins = sum(1 for l in BIN_LABELS if bins[l]["fill_edge_c"] < 0)
    if neg_bins >= 2:
        kill = True
        reasons.append(f"{neg_bins}/3 bins have negative edge")
    if kill:
        verdict = "KILL"
    elif go:
        verdict = "GO"
    else:
        verdict = "CONDITIONAL"
    return verdict, reasons


def main():
    t0 = time.time()
    print("Loading and filtering...")
    df, finfo = load_and_filter()
    print(f"  {finfo['n_markets_total']} -> {finfo['n_markets_after_candle_filter']} (candles>={MIN_CANDLES}) -> {finfo['n_markets_after_vol_filter']} (vol>0) markets")
    print(f"  {finfo['n_candles_total']} candles in sim universe")
    print("Running shadow maker sim...")
    recs = simulate(df)
    n_quotes = int(recs["quote"].notna().sum())
    n_fills = int(recs["filled"].sum())
    print(f"  {n_quotes} quotes, {n_fills} fills")
    print("Computing metrics...")
    metrics = compute_metrics(recs)
    print("Applying GO/KILL gate...")
    verdict, reasons = apply_gate(metrics)
    # Output: per-candle CSV
    csv_path = f"{OUT}/shadow_maker_results.csv"
    recs.to_csv(csv_path, index=False)
    # Output: summary CSV
    sum_rows = []
    for label in ["overall"] + BIN_LABELS:
        m = metrics["overall"] if label == "overall" else metrics["by_bin"][label]
        sum_rows.append({
            "scope": label, "n_quotes": m["n_quotes"], "n_fills": m["n_fills"],
            "fill_rate": round(m["fill_rate"], 4),
            "fill_edge_c": round(m["fill_edge_c"], 3),
            "boot_lo_c": round(m["boot_lo_c"], 3),
            "boot_hi_c": round(m["boot_hi_c"], 3),
            "e_dmid_fill_c": round(m["e_dmid_fill_c"], 3) if m["e_dmid_fill_c"] is not None else None,
            "e_dmid_nofill_c": round(m["e_dmid_nofill_c"], 3) if m["e_dmid_nofill_c"] is not None else None,
            "as_ratio": round(m["as_ratio"], 3) if m["as_ratio"] is not None else None,
        })
    pd.DataFrame(sum_rows).to_csv(f"{OUT}/shadow_maker_summary.csv", index=False)
    # Output: gate text
    with open(f"{OUT}/shadow_maker_gate.txt", "w") as f:
        f.write(f"VERDICT: {verdict}\n\nReasons:\n")
        for r in reasons:
            f.write(f"  - {r}\n")
        f.write(f"\nOverall: fill_rate={metrics['overall']['fill_rate']*100:.1f}%  edge={metrics['overall']['fill_edge_c']:.2f}c  CI[{metrics['overall']['boot_lo_c']:.2f},{metrics['overall']['boot_hi_c']:.2f}]\n")
        for label in BIN_LABELS:
            m = metrics["by_bin"][label]
            f.write(f"  {label}: n={m['n_quotes']} fills={m['n_fills']} rate={m['fill_rate']*100:.1f}% edge={m['fill_edge_c']:.2f}c CI[{m['boot_lo_c']:.2f},{m['boot_hi_c']:.2f}] AS={m['as_ratio']}\n")
    # Output: diag JSON
    diag = {
        "filter": finfo, "verdict": verdict, "reasons": reasons,
        "tick": TICK, "nboot": NBOOT, "seed": SEED,
        "min_candles": MIN_CANDLES,
        "assumptions": [
            "tick size $0.01 (unverified, V12 explore)",
            "zero maker fee (V04 backtest assumption; verify Q02)",
            "1-min resolution, no intra-candle queue position (V10 unknowable)",
            "touch-and-hold is conservative proxy, not true queue sim",
        ],
        "ts": int(time.time()),
        "elapsed_s": round(time.time() - t0, 1),
    }
    with open(f"{OUT}/shadow_maker_diag.json", "w") as f:
        json.dump(diag, f, indent=2)
    # Print summary
    print(f"\n{'='*60}")
    print(f"VERDICT: {verdict}")
    for r in reasons:
        print(f"  - {r}")
    o = metrics["overall"]
    print(f"\nOverall: fill_rate={o['fill_rate']*100:.1f}%  edge={o['fill_edge_c']:.2f}c  CI[{o['boot_lo_c']:.2f},{o['boot_hi_c']:.2f}]")
    for label in BIN_LABELS:
        m = metrics["by_bin"][label]
        print(f"  {label}: n={m['n_quotes']} fills={m['n_fills']} rate={m['fill_rate']*100:.1f}% edge={m['fill_edge_c']:.2f}c CI[{m['boot_lo_c']:.2f},{m['boot_hi_c']:.2f}] AS={m['as_ratio']}")
    print(f"\nOutputs: shadow_maker_results.csv, shadow_maker_summary.csv, shadow_maker_gate.txt, shadow_maker_diag.json")
    print(f"Elapsed: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
