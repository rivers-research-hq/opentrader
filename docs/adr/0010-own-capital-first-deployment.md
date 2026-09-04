# ADR-0010: Own-capital-first deployment path; the prop fee is gated on a demonstrated edge

- **Status:** accepted (human decision, 2026-09-03)
- **Date:** 2026-09-03
- **Context:** ADR-0005/0007 pinned FTMO as the revenue vehicle. Two developments
  changed the economics. First, the prop-firm survey (#183) and the FTMO US
  agreement review (`FTMO/document.pdf`): challenge accounts are simulated; the
  US product exits into OANDA Prop US Corp's Signal Provider Program — a
  *recommendation* to earn rewards for generated data, not guaranteed funded
  capital; fees are non-refundable under any circumstances; enforcement of
  trading-practice rules is sole-discretion, updatable, without pre-notice
  (clause 7). Second, the FX lanes' early accrual (2026-09-03: h1-mom +7.74,
  mom-k5 −0.68, crash −22.10 retired, three challengers at zero) does not yet
  demonstrate an edge whose capital leverage would justify fee-per-attempt
  economics. At current scale the binding constraint is the edge, not capital:
  OANDA practice already provides real-plumbing operation at zero cost, retail
  leverage caps are far above our usage ($228 margin on a $100k book), and a
  small own-capital stake provides real-money stakes at minimal tuition with
  full control and 100% of profits.

- **Decision:**

  1. **Deployment path: practice → own OANDA real account funded $300–500
     within 4 weeks (by 2026-10-04) → prop-fee decision, gated on a
     demonstrated edge.** The fee is paid only if the edge carries itself —
     sustained realized profitability on the real stake with drawdown well
     inside prop limits — otherwise the fee is detrimental to the end goal and
     the survey matrix (#183) stays shelved.
  2. **FTMO is demoted from the default revenue vehicle to a conditional
     scaling instrument.** The #183 decision matrix is the standing record for
     the prop leg; ADR-0005's capital ceiling and the Runway ladder are
     unchanged. No challenge fee is paid before the real-stake evidence exists.
  3. **Real-money pre-flight (before the first live order):** separate
     live-environment credentials (api-fxtrade.oanda.com — the practice host is
     hardcoded in the current keys file), a per-lane sizing decision for the
     funded amount, a hard daily-loss cap and cross-lane correlation/exposure
     caps, and news-ban encoding. The best-accruing lane goes first; the
     challenger bench stays on practice.

- **Consequences:** the FTMO application is deferred with no set date; the
  accumulation window (09-07→09-14), promotion gates, and weekly reviews proceed
  unchanged. The prop decision becomes data-driven in October: if sustained
  realized profit on the real stake shows that more capital is the binding
  constraint, the #183 matrix is revisited; if not, the fee is detrimental and
  own capital carries. The real stake is tuition with capped downside — sized so
  its total loss is an acceptable cost of the answer.
