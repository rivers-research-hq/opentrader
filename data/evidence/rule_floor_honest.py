"""Rule-floor honest re-run (RECONSTRUCTED 2026-08-22; original /tmp script lost to tmp cleanup).

Faithful to AGENTS.md: the repo's own run_backtest, 5y archive, all configs side by side.
No fabricated numbers — every metric below is computed live from ohlcv_5y.pkl.
"""
import json
from setup_search.data import load_ohlcv, align, UNIVERSE, OUT_DIR
from setup_search.engine import run_backtest
from setup_search.core import DEFAULT_CONFIG


def fmt(m):
    return (f"net={m['net_return']*100:+.2f}%  trades={m['n_trades']}  "
            f"sharpe={m['ann_sharpe']:.3f}  maxdd={m['max_drawdown']*100:.2f}%  "
            f"pf={m['profit_factor']:.2f}  win={m['win_rate']*100:.0f}%  fees=${m['total_fees']:.2f}")


def main():
    data = load_ohlcv(period="5y", allow_synthetic=False)
    al = align(data, UNIVERSE)
    closes = al[0]
    master = next(iter(closes.values())).index
    print(f"data: ohlcv_5y.pkl syms={len(closes)} span={master[0].date()}..{master[-1].date()} bars={len(master)}")

    best = json.loads((OUT_DIR / "best.json").read_text())
    m_best = run_backtest(al, best["config"])
    m_def = run_backtest(al, dict(DEFAULT_CONFIG))

    print("best.json (rule floor contract):", fmt(m_best))
    print("DEFAULT_CONFIG (08-12 baseline):", fmt(m_def))
    print("best.json STORED metrics:", {k: best['metrics'][k] for k in ('net_return', 'ann_sharpe', 'max_drawdown', 'n_trades', 'profit_factor')})
    print("best.json summary:", best.get("summary", ""))
    print("Documented: CONTEXT/AGENTS +23.1%/53tr/Sharpe1.12/DD3.5%  |  best.json stored +22.03%/28tr/2.363/2.18%")


if __name__ == "__main__":
    main()
