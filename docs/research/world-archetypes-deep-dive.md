# World archetypes & resource classes deep-dive — what the generator should model next

**Research for:** OpenTrader multiverse generator (`scenarios/parametric.py`, `scenarios/resources.py`).
**Date:** 2026-08-11. **Status:** research only; no code changed. Builds on the scarce (Hotelling) + renewable (regeneration) classes just landed in `resources.py`, and on the `tail_library.py` event mechanism.

## Verdict

The next highest-value moves are: (1) a **storage/inventory asset class** (natural-gas style) that puts an observable state variable — not just a latent premium — into price dynamics; (2) **regulatory/allowance assets** (emissions, RINs) where price is set by a policy schedule, not by supply/demand curves; (3) **world archetypes as generator parameters** (structural break, liquidity drought, inflation regime, scarcity spiral) rather than more tail events. Cross-asset coupling should be implemented as a **factor matrix + per-symbol betas + event transmission multipliers** — all three are already the framework's shape (`factor_ret` × `_BETAS` in `parametric.py:99-101`, uniform `shock` in `inject_event`), so the builder can extend rather than refactor.

---

## 1. Additional tradable resource-asset classes

### 1.1 Storage commodities — natural gas (new class: "STORED")
**Mechanism:** inventory (working gas in storage) is the state variable; injections in summer, withdrawals in winter; price is set by inventory *relative to its seasonal norm*, not by a depleting stock. Real market: front-month jumps ~60% in a week when withdrawals undershoot expectations, while the 12-month strip barely moves — the EIA weekly storage report (fetched 2026-08-11: 120 Bcf withdrawn vs 191 Bcf 5y avg → Henry Hub spot +60% WoW) is the exact trigger.
**Dynamics:** seasonal mean reversion to a weather-driven norm; gap risk on cold snaps; term-structure (contango/backwardation) carries a tradable storage yield.
**Edge vs equities:** calendar spreads and carry, not direction — a trader wins by anticipating the *inventory* path, a signal equities don't expose.
**Hook:** `resources.py` — new `STORED_ASSETS` registry (`{"NATGAS": {"cap": ..., "season": ..., "withdraw_noise": ...}}`), path function `_stored_path` mirroring `_scarce_path` but with `price = f(stock - seasonal_norm)`; needs a `carry`/term column the OHLCV shape can absorb via a second symbol (e.g., `NATGAS1Y`).
**Sources:** EIA Weekly Natural Gas Storage Report (fetched); NYMEX Henry Hub contract spec; EIA "Energy & Financial Markets" series.

### 1.2 Emissions allowances & compliance credits (new class: "ALLOWANCE")
**Mechanism:** price set by a *policy schedule* — EU ETS cap declines ~2.2%/yr with a Market Stability Reserve absorbing surplus; US RINs are bankable compliance credits under the RFS. Supply is a policy step-function, not a depletion curve.
**Dynamics:** mean reversion to marginal abatement cost between policy dates; discrete step-gaps on cap/rule announcements; year-end compliance-driven vol.
**Edge vs equities:** event-driven policy risk — the trader's edge is holding/retiring credits across a schedule (banking), i.e., storage without physical inventory; equities have no analog for "instrument with a finite, dated redemption."
**Hook:** `resources.py` — `ALLOWANCE_ASSETS` with `{"cap_schedule": [...], "banking": True}`; the schedule maps to the same `stock` slot but *depletes only at compliance dates*; policy shock = `spec`-level step injection (see §2.4).
**Sources:** European Commission EU ETS rules + MSR; ICAP *Emissions Trading Worldwide*; US EPA RFS/RIN program pages.

### 1.3 Uranium — spot vs term, and inelastic demand (extend URAN)
**Mechanism:** demand is inelastic to price and near-predictable (utilities run reactors flat; ~80,000 tU/yr, 3–15-yr term contracts; spot is only ~25% of the market — WNA, fetched 2026-08-11). Current `_scarce_path` gives URAN a Hotelling premium, but the real edge is the **spot/term basis**: spot spikes on supply news while term contracts lag, then utilities buy the dip (floor).
**Dynamics:** long quiet drift + sharp supply-news gaps (mine outage, export ban); strong floor from utility restocking; low realized vol otherwise.
**Edge:** basis/carry and gap-absorption — the inverse of momentum.
**Hook:** `resources.py` — dual series (`URAN` spot + `URANTERM` = spot-smoothed with contract lag), `demand_elasticity ≈ 0` instead of regime-linked `demand`.
**Sources:** World Nuclear Association "Uranium Markets" (fetched); UxC/TradeTech quoted in same.

### 1.4 Soft/perishable commodities — lumpy supply (extend RENEWABLE)
**Mechanism:** perishability caps inventory; supply arrives in lumps (harvest), so price *gaps down* at harvest and reverts up as inventory decays. The current `season` sine is too smooth.
**Hook:** step-function supply events + storage decay in `_renewable_path`. **Sources:** USDA WASDE; CME specs. (Water rights — Nasdaq Veles California Water Index — optional reuse of the scarce path with drought-event injection.)

### 1.5 Uranium — covered in §1.3

---

## 2. World archetypes beyond regime

All are expressible as `ScenarioSpec` fields + small path changes; none needs the neural generator.

### 2.1 Structural break (regime shift mid-world)
**Express as:** `spec.regime_break = (bar_t, to_regime)` — switch `_regime_params` mid-path in `generate()`.
**Exposes:** slow regime detection — the validated rule's SPY-vs-96d gate lags a mid-world flip, so a previously-correct long-only rule whipsaws; overconfident momentum fit to the early window.

### 2.2 Liquidity drought (archetype, not just event)
**Express as:** `spec.liquidity = {"vol_collapse_at": bar, "spread_mult": 4.0, "gap_p": 0.15}` — drives `_ohlcv_from_close`'s hi/lo range and gap behavior, plus volume.
**Exposes:** stop-hunting — stops fill at adverse prices the paper sandbox hides; agents relying on tight fills fail exactly where `flash_crash`/`liquidity_gap` point, but over a whole world.

### 2.3 Inflation regime
**Express as:** second latent factor `infl_t` (AR(1) + surprise shocks); all symbols get `ret = beta_f * factor_ret + beta_i * infl + idio` (extend `parametric.py:99-101` to a beta matrix).
**Exposes:** factor-blind cross-sectional strategies — duration names (NVDA/AMD) decouple from energy (XOM) like 2022; a trader betting only the common factor stops being diversified. **Sources:** Fama & Schwert 1977; IMF GFSR.

### 2.4 Policy shock (discrete step in a factor)
**Express as:** `spec.policy_steps = [(bar, "RARE", -0.5), ...]` — multiplicative step on a symbol's close at a bar boundary (export ban on rare earths; EUA cap cut; generalizes the `crisis_mult` pattern).
**Exposes:** gap/entry discipline — ties to the prop-firm news-gap ban the rule engine must encode (CONTEXT.md); agents without pre-event positioning or post-event rules get gapped.

### 2.5 Scarcity spiral
**Express as:** depletion scales super-linearly with scarcity in `_scarce_path` (`depletion *= 1 + 3*scarcity`); exhaustion-gap probability rising as `frac → floor` (today: flat 5%).
**Exposes:** trend-chasing into a terminal blow-off; shorting a "mean-reverting" asset that isn't; repeated gaps ruin momentum stops — the war's −25% ruin line becomes the correct lesson. **Sources:** Hotelling 1931; IEA *Critical Minerals Outlook*.

*(Seasonality as a full-world archetype: fold into §1.1/1.4 — a world-level `spec.seasonality` amplitude applied to the common factor. Sources: EIA seasonal gas data, USDA WASDE.)*

---

## 3. Cross-asset coupling (keep implementable)

1. **Factor matrix + beta matrix** — replace single `factor_ret` with `[n_bars × k]` factors (market, energy, rate, inflation, scarcity); `_BETAS` becomes `_BETAS[sym, k]`. Energy factor feeds XOM/GOLD/OIL/NATGAS; rate factor feeds NVDA/AMD vs PG/KO. The existing k-ratio correlation logic (`parametric.py:93`) still controls idio.
2. **Event transmission multipliers** — `TailEvent.shock` gains `sym_mult: {"NVDA": 1.5, "XOM": 0.5, "URAN": 2.0}` so `inject_event` (`parametric.py:120-155`) shocks symbols differentially instead of uniformly — today a crisis squeezes GOLD exactly like AAPL, the least realistic part of the system.
3. **Rolling resource-to-equity beta** — `beta[sym, energy] = beta_base + coupling * rolling_ret(OIL)`; resource prices feed equity margins (oil up → XOM up, RARE up → EV names down). A post-pass recompute in `generate()`, no new infrastructure.

**Expected payoff:** worlds that kill the *same* agent behaviors the real archive kills — 2022-style duration/energy decoupling, TTF/NG carry, EUA policy gaps — instead of 60 re-rolls of one equity factor.

## Sources (checked this session)

- EIA, *Weekly Natural Gas Storage Report / Weekly Update* (fetched 2026-08-11)
- World Nuclear Association, *Uranium Markets* (fetched 2026-08-11)
- European Commission, *EU ETS & Market Stability Reserve*; ICAP *Emissions Trading Worldwide*; US EPA *RFS/RINs*
- Hotelling (1931), *The Economics of Exhaustible Resources*, JPE 39(2); IEA *Critical Minerals Outlook*
- Fama & Schwert (1977), *Asset returns and inflation*, JFE 5(2); IMF *GFSR* (inflation)
- Nasdaq *Veles California Water Index* methodology; USDA *WASDE*; CME/NYMEX specs
