# FTMO 2-Step — Phase 0 facts (live re-verified 2026-08-23)

Primary source: `https://ftmo.com/en/trading-objectives/` (fetched live 2026-08-23,
276 KB HTML; text extracted). Reconciled against ADR-0005 and
`docs/research/prop-firm-challenge-research.md` (both 2026-08-05/06).

## Verified from the live page (2026-08-23)

- **Product:** `1-Step` and `2-Step`. The `2-Step Standard` is "2-phase".
- **Profit target (Phase 1):** 10% — "$100,000 account: Profit Target = $10,000,
  Balance required for passing = $110,000". Phase 2 target = 5%.
- **Maximum Daily Loss:** 5% (present; "Maximum Daily Loss rule establishes a
  limit … below which your account equity … cannot drop").
- **Maximum Loss (2-Step):** 10%, **static** — "Maximum Loss … establishes a
  **static limit** … $100,000 account: Maximum Loss Amount = $10,000,
  Limit = $90,000".
- **Maximum Loss (1-Step):** 10%, **end-of-day trailing** — the page also carries a
  "Maximum Loss … establishes an **end-of-day trailing limit**" section (the
  1-Step product). The trailing example: Day 2 balance $101,000 → limit $98,000.
- **Minimum Trading Days:** at least **4 Trading Days** ("(2-Step)"; a Trading Day
  = any day a position is opened).
- **Best Day Rule:** applies to the **1-Step** ("To pass the FTMO Challenge: 1-Step
  … or to be eligible for a Reward on an FTMO Account"), not the 2-Step.
- No time limit; no consistency rule on the 2-Step (consistent with ADR-0005).

**Key map implication:** the 2-Step Maximum Loss is **static 10%**, matching
ADR-0005 — so the map's "~10% max drawdown hard gate" aligns with FTMO's actual
rule. (If the 1-Step were ever chosen instead, its trailing max-loss is stricter.)

## US path

- FTMO US → **OANDA v20 REST** (ADR-0005; OANDA = CFTC-registered FCM / NFA
  0325821). No VPN workaround (payout-forfeiture risk).

## Instrument list — PARTIALLY UNVERIFIED (flag)

- FTMO instruments are **FX / metals / indices / commodities / crypto CFDs**
  (per `prop-firm-challenge-research.md`, primary-source-fetched 2026-08-05).
- **Whether US single-stock CFDs are offered is still UNVERIFIED** — the FTMO
  symbols page is JS-rendered and could not be extracted this session. The prop
  research (2026-08-05) flagged the same gap. **This is the single most
  eligibility-critical open fact** for the map: it decides whether any
  US-equity-derived expert can enter FTMO at all (current assumption: no).

## Tiers + fees — FLAG

- Sizes $10K–$200K; challenge fee ~$100–500 (prop research, 2026-08-05).
  Exact current fee table not captured this session — fetch before setting the
  Phase 0 dollar target.

## Operational rules (from prop research, primary-source-fetched 2026-08-05)

- **News/gap entry ban:** no entries within ±5 min of high-impact news, or within
  2 hours of a ≥2-hour market close. Must be encoded in the rule engine before
  the prop leg.
- **Automation:** allowed; < 2,000 server requests/day (hyperactivity cap).

## Open questions the map still needs

1. Confirm the full FTMO US/OANDA instrument list (esp. US single-stock CFDs: yes/no).
2. Exact current challenge fee per tier → sets the Phase 0 capital target.
3. Whether crypto CFDs (BTC/ETH/SOL) and index/commodity CFDs (SPY/QQQ/GLD/SLV)
   are on the US path — this is the bridge between the harness's live universe
   and FTMO.
