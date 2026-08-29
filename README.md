# OpenTrader

A self-improving algorithmic trading system. Most trading systems are a single model with a backtest — OpenTrader treats edge as something that must be *earned and re-proven*. Nothing deploys on vibes; everything earns its place against the incumbent on data it has never seen.

> 🎬 Prefer the full walkthrough? Open [`showcase/opentrader.html`](showcase/opentrader.html) in a browser for the complete animated tour with controls.

---

## 1. The Rule Floor

The system starts with a walk-forward-validated long-only daily momentum strategy. This is the **incumbent** — it holds all trading weight until an expert proves it can beat it. The rule fires when price is above its 96-day regime average (SPY as the equities market clock), with a 12.28% stop, 17.81% target, and 14-day max hold.

![The Rule Floor](showcase/rule_floor.gif)

Validated with walk-forward analysis on real data — no in-sample leakage, no parameter mining. ~68% win rate across held-out regime windows.

## 2. The Arena

Candidate experts don't get deployed by default. They enter the **arena** — an adversarial training loop where they train against the incumbent rule floor through five stages: `battle → fit → war → relabel → gate`.

![The Arena](showcase/arena.gif)

A candidate only ships if it clears a **+1% edge on both regime windows** against held-out data. Most candidates fail the gate and are rejected. The few that pass are promoted to deployable experts.

## 3. Mixture-of-Traders Router

Deployed experts don't trade blindly. The **MoT router** checks the current market regime (SPY above or below its 96-day average) and selects the best expert for that regime.

![Mixture-of-Traders](showcase/mot_router.gif)

The rule floor holds all weight by default. An expert only takes the trade when its recorded per-trade impact in that regime beats the floor's. Weaker experts are demoted automatically as evidence accrues.

## 4. Multiverse Stress Test

Before any edge deploys, it survives the **multiverse** — a battery of generated market worlds (neural + parametric samplers) plus a curated crisis tail-library (COVID crash, 2022 bear, yen unwind).

![Multiverse](showcase/multiverse.gif)

A world is **ruined** if the strategy falls below −25% net or −30% drawdown. GANs under-sample tails; the crisis library is the countermeasure. Synthetic rows never enter the gate, the war, or the evidence — they exist only to break things.

## 5. Live Harness

The **live harness** streams real prices (equities + crypto), applies regime-gated risk rules, settles paper trades, and feeds every result back into the arena.

![Live Harness](showcase/live_harness.gif)

Every paper trade is evidence. The system doesn't just trade — it learns from each trade and refines its experts continuously.

---

## Repository layout

| Path | Purpose |
|---|---|
| `arena/` | Adversarial training loop (battle / fit / war / relabel / gate) |
| `mot/` | Mixture-of-Traders router + expert definitions |
| `setup_search/` | Value-head training, walk-forward validation, FTMO universe |
| `training/` | RL / distillation refinement (GRPO) |
| `exchange/` | Data sources, live / paper execution, multi-router |
| `risk/` | Regime-gated risk rules |
| `harness.py` | Live paper-trading harness |
| `docs/` | Architecture, ADRs, research decisions |

## Getting started

```
pip install -r requirements.txt
python harness.py --help
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full design, ports, and integration seams, and [`docs/CONTEXT.md`](docs/CONTEXT.md) for the project's shared vocabulary.
