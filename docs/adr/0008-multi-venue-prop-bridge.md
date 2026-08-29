# ADR-0008: Multi-venue prop bridge — FTMO and TradeLocker firms both supported

- **Status:** accepted (amends ADR-0005)
- **Date:** 2026-08-29
- **Context:** ADR-0005 selected FTMO 2-Step as the sole prop revenue vehicle,
  chiefly because only FTMO lacked an inactivity clock (The5ers 30d,
  FundedNext 60d, Apex 30d vs the system's historical 102-day no-trade gap)
  and because it simmed PASS in `prop_challenge_sim.py`. The 2026-08-28
  small-capital research (`docs/research/small-capital-profitability-plan.md`,
  primary-source-backed, spot-checked 2026-08-29) surfaced a class of
  TradeLocker-platform firms — FTUK (no time limit, 8% **relative** max DD),
  FunderPro (static DD, 8-hr payouts, open trust questions), E8 Markets
  (EOD dynamic DD, ~$110 Futures / ~$138 CFD at $25K) — that also satisfy the
  no-inactivity-clock constraint. Human decision (2026-08-29): the harness is
  meant for this asset class generally and should have access to **both**
  venues rather than committing to one.

- **Decision:**

  1. **ADR-0005 is amended, not repealed:** FTMO 2-Step remains the
     sim-validated primary venue (OANDA universe bridge per
     `universe-bridge-matrix.md`). The TradeLocker firm class is added as a
     candidate venue class alongside it.
  2. **The TradeLocker adapter is the single new bridge work item:** an
     `ExchangeBase` implementation (JWT auth, REST polling vs the 60s cycle,
     the 5 interface methods) against the official
     `TradeLocker/tradelocker-python` SDK. Sequencing: **after** #155–157
     close; built sandbox-first; paper-validated on the TradeLocker demo
     before any challenge purchase. It is exchange infrastructure — like any
     adapter — not a monetization commitment.
  3. **Venue selection for an actual challenge purchase is a per-instance
     human decision**, made with evidence in hand: verified current rules
     (firms change them), the trust record (FunderPro's 2026 payout-denial
     complaints are a standing caution), and a venue-specific sim run.
  4. **Per ADR-0001, "challenge mode" is not a config toggle:** any
     reconfiguration of the validated risk contract (e.g., tightening to a
     4% DD envelope for an E8 Signature 4% EOD dynamic drawdown) requires its
     own ADR with sandbox proof that the challenge envelope and the faithful
     replica do not conflict.
  5. **Economics stay HEURISTIC until simmed:** pass-probability and income
     figures in the research plan are decision inputs only. Extending
     `setup_search/prop_challenge_sim.py` to venue-specific rule sets is the
     sanctioned way to firm them up.

- **Consequences:** `data/wayfinder/toc/` ledger carries the venue facts as
  V16–V19 (spot-checked 2026-08-29, with the E8 CFD/Futures variant conflation
  flagged). Monetization remains gated behind ADR-0002 deployability; the
  adapter work item enters the roadmap behind #157. If a firm's rules change
  (they do — FTUK's newer "Flex" variant already differs), the ledger entry is
  re-verified before any purchase decision quotes it.
