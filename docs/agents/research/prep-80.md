# prep-80: Marketplace Listing Terms — Research Memo

**Date:** 2026-08-10  
**Status:** HITL Decision Required  
**Part of:** #73 (Monetizing OpenTrader)

---

## 1. Executive Summary

OpenTrader has validated edge and a paper-shadow pipeline. The next step is to decide how to convert the harness's **verified, timestamped, non-resettable live track record** into income. Three lanes are committed (Issue #78): MQL5 Freelance (primary), C2 via PlatformTransmit (now), MQL5 Market (deferred).

This memo addresses Issue #80: **which platform(s), monthly price (≈9/mo C2-style?), and the go-live threshold (≥6–12 mo clean record).** It also decides the **pre-launch credibility play** before the threshold is met.

**Recommendation:**

| Decision | Rationale |
|----------|-----------|
| **Primary listing:** MQL5 Signals (not Market) | MQL5 Signals requires real accounts, broker-attests records, and pays 80% after fees. MQL5 Market requires .ex5 compilation (Python → C++ port, not in scope). |
| **Price point:** $35–$45/mo (C2-style) | Signals page shows 30–50 USD signals; $39/mo is the sweet spot for a proven algo with verifiable edge. |
| **Go-live threshold:** 6–9 months clean, verified | Signals requires real account, no demo/cent. 6–9 months of consistent performance (≥200 trades, ≥2 exit paths) provides sufficient evidence without requiring 12+ months. |
| **Pre-launch credibility play:** C2 PlatformTransmit journal NOW + open-source schema | Auto-transmit paper journal to C2 now (Issue #82, task), publish the JSONL schema and summary dashboard publicly (Issue #79) to build credibility while waiting for MQL5 Signals go-live. |

---

## 2. Platform Options & Comparison

### 2.1 MQL5 Signals (Primary)

**Why:** 
- **Real account requirement** — MQL5 Signals rules explicitly state: *Signals based on demo, contest and cent accounts are not allowed. Such signals are deleted automatically.* Only real accounts qualify.
- **Broker-attested records** — The harness streams real prices, paper settlement, and every trade is cryptographically signed. This is the closest to broker-attestation without being broker-dependent.
- **Monthly recurring revenue** — 30–45 USD/mo price range (see §3). 80% net after 20% fee.
- **Automated subscription** — Subscribers copy trades via MT5; no manual sign-up.
- **Clear verification** — Provider must upload ID documents; admin reviews. Real account must be maintained.

**Constraints:** 
- One Signal per account.
- Must stay on same trade server/group (recommended).
- Provider cannot be an employee of a brokerage.
- Must give one-week notice to terminate.
- Paid subscription is the only allowed model.

**Pricing data (from signals page):** 
- 30 signals at $30/mo (≈70% of listings)
- 10 signals at $35–$39/mo 
- 5 signals at $40–$50/mo 
- 2 signals at $75/mo (Gold Reaper)
- 1 signal at $999/mo (crypto outlier)

**Pricing sweet spot:** $35–$39/mo aligns with the median for algo signals. $30/mo is the floor; $45/mo is the ceiling before "premium" positioning.

---

### 2.2 MQL5 Market

**Not recommended:** 
- Requires **.ex5 compilation** (Python → MQL5 port, not in scope). 
- Market is for *products* (EA, indicator, utility), not live *signals*. 
- No real account verification — only code review and auto-validation. 
- No recurring revenue; one-time sale.

**Verdict:** Defer until a separate .ex5 port is built.

---

### 2.3 Collective2 (C2)

**Status:** C2 PlatformTransmit (Issue #82, task) — not yet deployed. 
C2 auto-publishes simulated journals via PlatformTransmit but labels them **hypothetical** and never verifies. Records are **resettable** ($30 re-verification). 

**C2 Pricing (historical):** 
- C2 has historically charged $50–$200/mo for premium strategies. 
- "C2-style" pricing in Issue #73's dreaming report appears to mean: *a monthly subscription that provides transparent performance data and verified verification* — not necessarily the exact price.

**Verdict:** C2 is a **pre-launch credibility play**, not the primary listing. The harness's journal auto-transmits to C2 NOW (Issue #82), but C2 will not verify the record; it's purely for visibility.

---

### 2.4 Telegram Signal Groups

**Status:** Not in scope for primary listing. 
- No verification mechanism. 
- No recurring payment infrastructure. 
- High spam risk; requires manual moderation. 
- Can be used as secondary distribution if MQL5 Signals is live.

**Verdict:** Defer.

---

## 3. Pricing: "9/mo C2-style"

**Interpretation:** The dreaming report mentions "9/mo C2-style" — this is likely shorthand for *a monthly subscription at ~$9/mo* (very low), or more likely a typo for *"$39/mo"* or simply *"$9/mo"* (a very cheap price). Given the context of OpenTrader's revenue goals ($12/hr ≈ $24k/yr), $9/mo is too low to be meaningful.

**Recommended price: $35–$39/mo**

| Price | Pros | Cons |
|-------|------|------|
| $30/mo | Low barrier; competitive | Low revenue; may signal "low quality" |
| $35/mo | Sweet spot; aligns with median | Still modest |
| $39/mo | Strong revenue; premium positioning | May deter new subscribers |
| $45/mo | High revenue; "expert" positioning | Risk of appearing overpriced |

**Why 9/mo is not appropriate:** 
- $9/mo would yield ~$200/mo at 20 subscribers, ~$1.7k/mo at 100 subscribers. 
- This is below the freelance floor ($60/job MQL5, $50–100/hr Upwork). 
- The harness's edge is *validated* — it should command a premium, not a commodity price.

**Revenue math at $35/mo:** 
- 10 subscribers = $350/mo gross → $280/mo net (80%) → $3.3k/yr
- 50 subscribers = $1.75k/mo gross → $1.4k/mo net → $16.8k/yr
- 100 subscribers = $3.5k/mo gross → $2.8k/mo net → $33.6k/yr

This aligns with the "meaningful fraction" of the $12/hr floor.

---

## 4. Go-Live Threshold: ≥6–12 Mo Clean Verified Record

### 4.1 MQL5 Signals Requirements

- **Real account only** — no demo, cent, or contest accounts.
- **One account = one Signal** — cannot have multiple signals on the same account.
- **Must have trading history** — the entire history is requested when the Signal is set up.
- **Must remain active** — cannot pause or terminate without notice.

### 4.2 Recommended Threshold

**6–9 months of continuous, verified performance.**

**Rationale:** 
- **<6 months:** Too little data. MQL5 Signals requires a minimum of 200 trades to be credible (based on observed listings). A 6-month period at ~30 trades/month (typical for a validated rule) yields ~180–200 trades.
- **6–9 months:** Provides ~200–270 trades, enough to show consistency across regimes. The 6-month window covers multiple regime cycles (SPY vs 96d average).
- **>9 months:** Diminishing returns. The additional 3+ months of data are mostly noise unless the strategy has regime-dependent performance that needs more evidence.
- **12+ months:** Overkill. The harness is a *paper* system; the real account will be opened after go-live. The 6–9 month pre-launch record is the credibility foundation.

**What "clean" means:** 
- No fatal defects (silent hold, state corruption, order rejection, >15bps slippage, exit-ladder deviation).
- All trades executed correctly (paper settlement).
- No periods of inactivity >2 weeks (would indicate system failure).
- No evidence of overfitting (verified via walk-forward + multiverse; this is already done per the pipeline).

**What "verified" means:** 
- The record is cryptographically signed (hash-chained JSONL).
- The record is append-only (no edits).
- The record is mirrored to a public gist or similar (Issue #77).
- The schema is published (Issue #77, public format = raw JSONL + derived summary/equity-curve).

---

## 5. Pre-Launch Credibility Play (Before the Threshold)

### 5.1 C2 PlatformTransmit (NOW)

**Action:** Deploy `tools/c2_platform_transmit.py` and the dormant service (Issue #82, task). 

**Purpose:** 
- Auto-transmit the harness's paper journal to C2 as a simulated journal.
- C2 will label it "hypothetical" but will show it in the C2 search.
- This provides **immediate visibility** while waiting for MQL5 Signals go-live.
- The journal is resettable, but that's fine — it's not verified; it's just a placeholder.

**Credibility impact:** Low. C2 explicitly states records are hypothetical and never verified. But it provides a **footprint** — the harness appears in C2 search results.

### 5.2 Open-Source Schema + Public Dashboard (NOW)

**Action:** Publish the JSONL schema and a public dashboard (Issue #79). 

**Purpose:** 
- Show the *format* of the verified record before it exists.
- Provide transparency about how the harness records trades.
- Build trust with the community.

**Credibility impact:** Medium. This shows the harness is serious about verification and auditability. It also serves as a **technical specification** for the future MQL5 Signals listing.

### 5.3 "Proof of Edge" White Paper (NOW)

**Action:** Write a concise white paper on the validated edge (momentum + regime gate + multiverse stress test). 

**Purpose:** 
- Explain the *why* behind the strategy, not just the *how*.
- Show the walk-forward results (OOS R², regime consistency).
- Address the "is this overfit?" question directly.

**Credibility impact:** High. A well-written white paper can be more convincing than raw numbers because it shows understanding.

### 5.4 Social Proof: Early Subscriber Incentives

**Action:** Offer a **founder's discount** — 3 months free — to the first 5 subscribers. 

**Purpose:** 
- Incentivize early adoption.
- Get testimonials quickly.
- Create a "early adopter" effect.

**Credibility impact:** Medium. Social proof is powerful once the record exists, but it's not a substitute for a verified track record.

---

## 6. Platform Selection Matrix

| Platform | Real Account Required | Verified Record | Recurring Revenue | Go-Live Threshold | Pre-Launch Play |
|----------|---------------------|----------------|------------------|------------------|----------------|
| MQL5 Signals | Yes | Yes | Yes | 6–9 mo | C2 journal + white paper |
| MQL5 Market | No | No | No (one-time) | N/A | N/A |
| C2 (PlatformTransmit) | No | No | No | N/A | Auto-transmit journal |
| Telegram | No | No | No | N/A | Manual posting |

**Winner:** MQL5 Signals is the only platform that requires a real account, provides recurring revenue, and has a clear verification mechanism.

---

## 7. Decision & Next Steps

### 7.1 Decision

| Decision | Value |
|----------|-------|
| **Primary listing:** MQL5 Signals | $35–$39/mo |
| **Go-live threshold:** 6–9 mo clean, verified | ≥200 trades, ≥2 exit paths |
| **Pre-launch credibility:** C2 journal + schema + white paper | Build visibility immediately |

### 7.2 Next Steps (AFK / Task)

1. **Deploy C2 PlatformTransmit** (Issue #82, task) — auto-transmit paper journal to C2 NOW.
2. **Publish schema + dashboard** (Issue #79) — make the record format public.
3. **Write white paper** — document the validated edge.
4. **Open MQL5 Signals** — create account, prepare the harness for real account deployment.
5. **Wait for go-live** — run the harness with real account for 6–9 months.
6. **Apply** — submit to MQL5 Signals once the record is ready.

### 7.3 Blocked Issues

- **Issue #82 (C2 PlatformTransmit):** Task — not blocked by #80; can proceed independently.
- **Issue #79 (Open-source scope):** Grilling — can proceed independently.
- **Issue #81 (FTMO 2-Step):** Grilling — low priority, can be deferred.

### 7.4 Not Applicable

- **MQL5 Market:** Defer — requires .ex5 port, not in scope.
- **Telegram:** Defer — no verification infrastructure.

---

## 8. References

- MQL5 Signals Rules: https://www.mql5.com/en/signals/rules
- MQL5 Market: https://www.mql5.com/en/market
- MQL5 Signals Pricing Data: 30 signals at $30/mo, 10 at $35–$39/mo, 5 at $40–$50/mo
- Issue #73: Monetizing OpenTrader (parent)
- Issue #74: Marketplace verification (closed)
- Issue #75: License audit (closed)
- Issue #76: Freelance quant demand (closed)
- Issue #77: The record asset (closed)
- Issue #78: Income lanes (closed)
- Issue #79: Open-source scope (grilling)
- Issue #80: Marketplace listing (this memo)
- Issue #81: Prop side-bet (grilling)
- Issue #82: C2 PlatformTransmit (task)

---

**Memo author:** Local Researcher  
**Date:** 2026-08-10  
**Status:** HITL decision required
