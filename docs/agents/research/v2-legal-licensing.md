# V2 legal & licensing boundaries (wayfinder ticket #332)

- **Ticket:** [#332](https://github.com/rivers-research-hq/opentrader/issues/332) (Opentrader V2 spec map [#326](https://github.com/rivers-research-hq/opentrader/issues/326))
- **Date:** 2026-10-06
- **Scope:** What is safely reusable in the V2 clean-room rebuild and what is not — (1) the thinkorswim client (Schwab proprietary), (2) Devexperts dxlib/QDS/dxFeed, (3) data-vendor resale/redistribution terms (Polygon/Massive, Databento, IEX, OANDA), (4) the regulated-activity boundary as the product is sold.
- **Status:** Research recommendation + posture map. **Not legal advice.** This is information-gathering by a non-lawyer agent for spec purposes; every "counsel gate" below is exactly where licensed counsel must be engaged before the decision, not after.
- **Method:** Primary sources fetched today (GitHub LICENSE/pom files, live ToS pages, archived ToS, US statutes via Cornell LII, the thinkorswim installer's own embedded `license_en.html`), quoted verbatim in short excerpts. Secondary sources (Justia's USPTO aggregation, Wikipedia) are labeled. Statutory and case citations are quoted/characterized from the cited texts; case law is cited by citation with standard characterizations, not fresh legal analysis. US-law-centric.

---

## Part 0 — Bottom line (posture at a glance)

| Item | Posture | One-line reason |
|---|---|---|
| thinkorswim decompiled **code, assets, config verbatim** | **Prohibited** | Copyright § 106; decompiler output is a derivative work of Schwab software |
| thinkorswim **architecture/design knowledge** (module map, feed model, updater mechanics, ThinkScript semantics) | **Safe (with hygiene)** | Ideas/procedures/methods of operation are not copyrightable (17 U.S.C. § 102(b)); case law supports intermediate-copying study (Sega/Accolade, Connectix) |
| Decompiling more jars for study | **Conditional** | DMCA § 1201(f) interop exception + fair use support private study; contract (EULA) terms may still bind — capture and review the EULA first (open item 1) |
| Using Schwab marks (`thinkorswim`, `paperMoney`, `TOS`, `ThinkScript`, `think*`/`swim` family) in V2 **naming/marketing** | **Prohibited** | Registered-marks family, Lanham Act § 32/43(a) confusion & dilution exposure |
| Factual references to thinkorswim in V2 docs ("not affiliated…") | **Safe (narrowly)** | Nominative fair use (*New Kids on the Block* test), with disclaimers |
| Devexperts **QD/dxlib** source (GitHub `devexperts/QD`, **MPL-2.0**) | **Safe with obligations** | Genuinely open source (verified); file-level copyleft + patent grant; Rust *reimplementation* from study = clean |
| dxFeed **data / cloud services** | **Commercial license required** | dxFeed is a paid data vendor; internal-use-only default; redistribution needs dxFeed + exchange written approval |
| Polygon.io (now **Massive**) data in a sold V2 | **Prohibited on individual terms** | Individual/Market-Data ToS: personal, non-commercial only; "you may not use the Market Data to build an application intended for use by end users other than you" |
| Databento data inside V2 | **Conditional** | Internal business use OK on Standard; external distribution = Plus tier ($1,750/mo, annual) + per-exchange agreements + attribution |
| IEX Cloud | **Moot** | Service retired (~Aug 2024); site unreachable (verified today); archived ToS recorded for the pattern only |
| OANDA v20 practice (V1's lane) | **Safe today** | Personal token on own practice account; V2 built as a customer-side tool |
| OANDA for **other users' accounts** via V2 | **Partner lane** | OANDA's own wizard routes "will others trade and access their accounts with your application" to a Partner Form |
| Selling V2 while it stays: paper/practice-first, BYO accounts/keys, no advice, no custody, no order routing for others | **Low-risk lane** | No broker/adviser/CTA definition triggered |
| Real-money order routing for customers, sold advice/signals, agents trading others' assets | **Counsel gate — hard stop first** | BD (15 U.S.C. § 78c(a)(1)), RIA (§ 80b-2(a)(11)), CTA (CEA § 1a(12)) definitions come into play |

---

## Part 1 — thinkorswim (Schwab proprietary software): the clean-room posture

### 1.1 What the primary artifacts say

The installer sample (`thinkorswim_installer.sh`, app 1991.3.0 — see the dissection dossier [#327](v2-tos-dissection.md)) ships its EULA as a pointer, not the full text. Extracted verbatim from the payload's `license_en.html` (532 bytes, carved at zip offset 19,531 — read-only, in-memory):

> "The terms of an End User License Agreement ("License") govern your use of the **thinkorswim® software and trading platform**, as well as the **paperMoney® application** for thinkorswim (collectively, thinkorswim and paperMoney are called the "Software"). You will be required to review, acknowledge and accept the License terms in order to use the Software. If you do not agree to the License terms, you will not be able to use the Software, but you will be able to uninstall it."

Facts that follow from this and the carve itself:

1. **Schwab asserts exclusive rights and a click-through EULA** over thinkorswim and paperMoney; both names carry the ® symbol. "Free to download" is not "free to reuse" — § 106 exclusive rights (reproduction, derivative works, distribution) apply regardless of price.
2. **The full EULA text is NOT in the installer** — it is presented at install/first run. Its reverse-engineering and use clauses have therefore **not yet been reviewed** (open item 1). The recon so far has been static and offline ("No connections to Schwab servers were made" — dissection dossier), and the payload is a plain STORED zip with no access-control circumvention — no descrambling, no decryption, no § 1201(a) "circumvention" as defined in § 1201(a)(3)(A).
3. The heavy UI (charting, ThinkScript compiler, trade ladder) is the `usergui` module downloaded at first run — decompiling it would touch a different risk surface than the shipped jars.

### 1.2 Copyright boundary: study vs. copy

The governing principle is the idea/expression dichotomy, 17 U.S.C. [§ 102(b)](https://www.law.cornell.edu/uscode/text/17/102):

> "In no case does copyright protection for an original work of authorship extend to any idea, procedure, process, system, method of operation, concept, principle, or discovery, regardless of the form in which it is described, explained, illustrated, or embodied in such work."

What this means for V2, concretely:

- **Safely reusable (study/derive design):** the module decomposition (ticker-plant/feed model, install4j updater mechanics, script-language semantics, order-type taxonomy, layout concepts). These are systems, procedures, and methods of operation. Writing our own Rust implementation from a *specification* derived from study is the classic lawful path.
- **Never reusable:** decompiled source (even "cleaned up"), copied resources/images/strings, config tables lifted verbatim, ThinkScript grammar text copied wholesale, any jar or class carried into V2. Decompiler output is a translation of the copyrighted program — a derivative work. Publishing wholesale decompilations of the jars is also a distribution of derivative works.
- **Case law that frames this** (cited by citation; characterizations standard): *Sega Enters. v. Accolade*, 977 F.2d 1510 (9th Cir. 1992) (disassembly to reach unprotectable functional ideas can be fair use where it is the only means of access); *Sony v. Connectix*, 203 F.3d 596 (9th Cir. 2000) (intermediate copying of object code for functional study is fair use; the shipping product contained none of it); *Atari v. Nintendo*, 975 F.2d 832 (Fed. Cir. 1992) (the goal was lawful; the means — unauthorized copying — was not; hygiene is decisive); *Google LLC v. Oracle Am.*, 593 U.S. 1 (2021) (reimplementing ~11,500 lines of declaring code held fair use — but after a decade of litigation; it is a defense, not a license, and it covered a tiny fraction of the code at issue).

### 1.3 DMCA § 1201: decompilation for interop vs. for redistribution

17 U.S.C. [§ 1201(f)](https://www.law.cornell.edu/uscode/text/17/1201) ("Reverse Engineering") exempts, verbatim:

> "(1) Notwithstanding the provisions of subsection (a)(1)(A), a person who has **lawfully obtained the right to use** a copy of a computer program may circumvent a technological measure that effectively controls access to a particular portion of that program **for the sole purpose of identifying and analyzing those elements of the program that are necessary to achieve interoperability** of an independently created computer program with other programs, and that have not previously been readily available to the person engaging in the circumvention, to the extent any such acts of identification and analysis do not constitute infringement under this title."

and § 1201(f)(3) permits sharing information derived this way "solely for the purpose of permitting interoperability of an independently created computer program with other programs," § 1201(f)(4) defines interoperability as programs' "ability… to exchange information, and… mutually to use the information which has been exchanged." § 1201(c)(1) preserves fair-use defenses.

Honest reading for V2:

- **The interop exception is narrow.** It is aimed at making programs talk to each other, not at studying a competitor's architecture to build a competing product. If a future V2 phase needed to decrypt jars or protocol streams, § 1201(f) would not clearly cover "competitor design study" as the *sole purpose*. Where possible, keep the study strictly on the interoperability seam (what a compatible script/paper-trading session needs to exchange).
- **Likely moot today:** nothing in the current recon circumvented an access control — the installer is a plain zip; the dissection carved bytes, no descrambling (§ 1201(a)(3)(A) defines circumvention as descrambling/decrypting/avoiding/bypassing a technological measure). § 1201 should not be assumed to protect a future phase that does break any encryption; that would need its own analysis.
- **Decompilation for redistribution is never covered** by § 1201(f): the exception requires that acts "do not constitute infringement under this title." It protects analysis, not copying.

### 1.4 Contract/EULA exposure — the real constraint

Independent of copyright and the DMCA, a EULA clause prohibiting reverse engineering can be enforceable as a contract: *Bowers v. Baystate Technologies*, 320 F.3d 1317 (Fed. Cir. 2003) (click-through restriction on reverse engineering enforceable under state law; no federal preemption). And contract terms can shape the "authority" analysis under § 1201: *MDY Industries v. Blizzard*, 629 F.3d 373 (9th Cir. 2010).

What this means practically:

- The full thinkorswim EULA must be captured and reviewed before any further client-side recon (open item 1).
- Track whether/who accepted it: if the human ran the installer to obtain a working install, the EULA may bind *that machine's* use. Static study of a downloaded installer file by an agent that never ran it (current state) is a different posture. Document the provenance chain explicitly — this is exactly the kind of record that decides contract claims.
- The clean-room two-role procedure (below) exists to keep any EULA dispute about *study* from bleeding into *implementation*.

### 1.5 Trademark exposure — naming and marketing similarity

The trademark facts (secondary aggregation of USPTO data via [Justia Trademarks search "thinkorswim"](https://trademarks.justia.com/search?q=thinkorswim), cross-checked with Schwab's own ® usage on [schwab.com](https://www.schwab.com/trading/thinkorswim) and the client's `license_en.html`):

| Mark | Serial | Filed | Goods/services (abbrev.) | Owner of record |
|---|---|---|---|---|
| THINKORSWIM | 75819263 | 1999-10-12 | securities brokerage | Charles Schwab & Co., Inc. |
| THINKORSWIM | 77171002 | 2007-05-02 | securities brokerage | Charles Schwab & Co., Inc. |
| THINKORSWIM | 86116292 | 2013-11-12 | electronic trading software, portfolio management software | Charles Schwab & Co., Inc. |
| PAPERMONEY | 77409002 | 2008-02-28 | "software application that permits users to use virtual money to trade securities and futures" | Charles Schwab & Co., Inc. |
| THINKMONEY | 77233469 / 77319462 | 2007 | publications | Charles Schwab & Co., Inc. |
| THINKPIPES | 78926499 | 2006 | securities execution software | Charles Schwab & Co., Inc. |
| THINKANYWHERE | 76174990 | 2000 | brokerage-access software | Charles Schwab & Co., Inc. |
| THINKMICRO | 77233485 | 2007 | brokerage-access software | TD Ameritrade IP Company |
| SWIM FX | 77136877 | 2007 | FX brokerage | thinkorswim Holdings |
| TOS LIQUID / TOSLIQUID | 76550686 / 76561375 | 2003 | trading platform software | thinkorswim Group |

Schwab owns a dense **"think\*" and "TOS" mark family** spanning brokerage and trading software — i.e., V2's exact classes. (Live/registered status per application not verified individually — open item 4 for ThinkScript specifically; the ® symbols Schwab itself uses establish registered status for at least the core marks.)

Rules this implies for V2:

1. **Lanham Act exposure** runs through 15 U.S.C. § 1114 (registered-mark infringement) and § 1125(a) (unregistered/likelihood of confusion) — the test is likelihood of consumer confusion as to source, sponsorship, or affiliation.
2. **Product naming:** avoid any name containing "TOS", "think", "swim", or phonetic near-misses; avoid a logo/look deliberately evoking thinkorswim's. "thinkorswim-informed" is fine in internal engineering docs but must never be marketing copy.
3. **UI/trade dress:** functionality and layout concepts are free (§ 102(b)); pixel-level cloning of the thinkorswim look-and-feel invites trade-dress confusion claims. Reimplement concepts, not the skin.
4. **Nominative fair use** permits factual reference (*New Kids on the Block v. News America Publishing*, 971 F.2d 302 (9th Cir. 1992)): use the mark only when the product is not reasonably identifiable otherwise, use only as much of the mark as needed, and do nothing suggesting sponsorship — plus an explicit "not affiliated with, endorsed by, or connected to Charles Schwab & Co." disclaimer in any doc that names thinkorswim.
5. **ThinkScript**: same treatment as the platform marks — the *language semantics* are functional and free; the *name* is not ours to brand. Call V2's language by its own name; describe compatibility factually if we ever claim it.

### 1.6 The clean-room procedure to lock into the spec

- **Two-role rule:** agents who read decompiled material produce *specifications* (the `docs/agents/research/v2-*.md` dossiers — subsystem names, public seams, behavior contracts). V2 implementers work from those dossiers only, never from `/tmp/tos-recon*` sources or the jars. The dossiers already self-limit to "small identifying fragments" — keep that rule.
- **No flow-through:** no decompiled code, config verbatim, images, or string tables from Schwab material into the repo or the V2 codebase, ever — including "translations" or reformattings.
- **No server contact:** recon stays static; we do not probe Schwab endpoints beyond what an ordinary client would do when the human uses the software.
- **Recordkeeping:** each dossier names its input artifact (installer path, offsets), decompiler and version (Vineflower 1.11.1), date — the chain of custody that proves the wall.

---

## Part 2 — Devexperts dxlib / QDS / dxFeed: what's actually open

### 2.1 Verified facts (the ticket's premise, corrected and confirmed)

The open-source repository is **[`devexperts/QD`](https://github.com/devexperts/QD)** (not "qds" — the repo name is `QD`, description "Quote Distribution Subsystem"; Maven artifact `com.devexperts.qd:QD`, version 3.355). Verified today via the GitHub API and raw files:

- **License: Mozilla Public License 2.0.** The repo's [`LICENSE.txt`](https://github.com/devexperts/QD/blob/master/LICENSE.txt) is the full MPL-2.0 text ("Mozilla Public License Version 2.0"), and the root `pom.xml` header states verbatim: *"QDS - Quick Data Signalling Library … Copyright (C) 2002 - 2026 Devexperts LLC … This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0. If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/."* The GitHub API reports `license: MPL-2.0`.
- **Active and genuine:** created 2016-12-23, last push 2026-09-08, 65 stars / 20 forks, not archived. Current `ReleaseNotes.txt`: "QDS 3.355 … New distribution repo at repo.devexperts.com" (`https://repo.devexperts.com/repository/qd-maven`).
- **Both asked-for components live inside it**: the module list includes **`dxlib`** (+ `dxlib-qd-sandbox`, `dxlib-jcstress`), **`qds`**, `qds-file`, `qds-tools`, `qds-monitoring`, `qd-core`, `qd-nio`, `qd-rmi`, and also `dxfeed-api`, `dxfeed-impl`, `dxfeed-ondemand`, `dxlink-websocket`, `proto`, `mars`. Third-party dependencies and their dual-licenses are documented in the repo's `licenses/` directory (Jetty, Servlet API, JAXB, JNA, etc.).
- **So: yes — dxlib/QDS are genuinely open source under MPL-2.0.** This is the *library/ticker-plant core* of the Devexperts stack, not a stub repo.

### 2.2 What MPL-2.0 permits, and the obligations it carries

(MPL-2.0 text as shipped in the repo's LICENSE.txt; characterization standard.)

- **Permitted:** commercial use, modification, distribution, running internally without publishing anything, studying the design. A **Rust reimplementation written from studying QD** is unencumbered — methods and architecture are not copyrightable (§ 102(b)), and MPL imposes no terms on independent reimplementations.
- **Obligations if we distribute QD-derived code** (linking, embedding, vendoring, or *translating* MPL files): MPL-2.0 is **file-level copyleft** — modified MPL-covered files must be distributed with their source under MPL (LICENSE § 3); a "Larger Work" may combine MPL files with proprietary files, but the MPL files' source obligations remain (§ 3.3); attribution/notices must be preserved (§ 3.1, 3.4–3.6); there is an **express patent grant** from contributors (§ 5) and termination conditions (§ 5.2). Practically: if V2 ever ships a port of QD/dxlib code, those ported files become open-file obligations — segment them deliberately or don't port, reimplement.

### 2.3 dxFeed (the commercial side) — separate and strictly licensed

dxFeed the *service/vendor* is **dxFeed Solutions IE Limited** (Dublin, reg. 720582), a commercial market-data company — and its terms are far narrower than QD's license. From the primary pages fetched today:

- **[Site Terms of Use](https://dxfeed.com/terms-of-use/):** content is Devexperts' IP; no scraping/data-mining/re-utilization of substantial parts; no commercial use of site content without a license; **"'Devexperts' and 'dxFeed' are trademarks of Devexperts LLC"** (footer of dxfeed.com: "Devexperts TM and dxFeed TM belong to dxFeed Solutions IE Limited or its affiliates").
- **[dxFeed Services Terms of Use](https://dxfeed.com/general-terms-and-conditions-for-services/) (effective April 2025)** — the commercial data contract:
  - **§ 4.2:** "Except as provided in the Order(s), the Services shall be used solely for **Customer's internal usage** and not for third party (including its affiliates, consultants) access or use."
  - **§ 4.4:** any retransmission, redistribution, reproduction, or derivative works beyond the Agreement require "**prior written approval by dxFeed and Data Originators**."
  - **§ 4.7:** Customer shall not sell/lease/sublicense the Services or their output, **nor "reverse engineer or otherwise use the Services in any way to develop, test, enhance, or calibrate … any models, system, or services that are similar to any component(s) of the Services."** — i.e., the *commercial service* carries a no-clone clause. (Studying the open-source QD repo is unaffected; studying dxFeed's live service output to build a rival service is contractually barred.)
  - **§ 8.4:** dxFeed and Data Originators claim "exclusive and valuable property rights" in Market Data, with injunctive relief for disclosure.
  - **§ 7.10:** audit rights over usage; **§ 7.2:** dxFeed can terminate immediately at a Data Originator's request on misuse.
- **[3rd Party Terms](https://dxfeed.com/3pty/):** redistribution "requires all required approvals for control and redistribution" from third-party licensors — with the per-exchange agreement stack (OPRA Vendor Agreement, UTP/CTA Vendor Agreements, Nasdaq Global Data Agreement, CME ILA, ICE, NYSE, Euronext, Deutsche Börse, OTC Markets…). This is the standard exchange-gate every equities/options data product has to clear.
- dxFeed's own positioning: "dxFeed Solutions IE Limited is a software company that provides software products and services. dxFeed Solutions IE Limited does not provide any investment or brokerage services." (site footer)

### 2.4 Integration boundary for V2

| Want | Legitimate path |
|---|---|
| Study QD's ticker-plant/scheme/protocol design, implement in Rust | Free — read the MPL repo, write our own; keep the two-role rule anyway for simplicity |
| Run/fork QD or embed dxFeed Java API in a Java component | MPL-2.0 obligations (file-level source sharing for distributed modified files) |
| Get real market data via dxFeed cloud/APIs | Commercial contract — internal-use default; **budget for "external distribution" only with written dxFeed + exchange approval** |
| Redistribute dxFeed-sourced data in V2 to V2 customers | Not without the § 4.4 written approvals — treat as out-of-scope for V1.0 of V2 |
| Use "dxFeed"/"Devexperts" names/marks in V2 marketing | No — trademark notice is explicit; nominative references in docs only |

---

## Part 3 — Data-vendor terms constraining resale/redistribution

The universal pattern (verified on every primary source below): **personal/internal use by default; redistribution — including display to third parties and derived-data products — is a separately purchased entitlement**, and exchange (SRO) agreements ride on top. A sold V2 is always a "redistribution/external distribution" case.

### 3.1 Polygon.io → Massive (massive.com, Inc., Atlanta GA; rebranded)

Polygon.io now serves its terms from **massive.com** ([/terms](https://massive.com/legal/individuals-terms-of-service) redirects there). Primary pages fetched today:

- **[Massive for Individuals Terms of Service](https://massive.com/legal/individuals-terms-of-service)** (last updated 2025-07-18): grants "solely for your own personal, non-commercial, and non-business purposes" (§ 2); prohibits selling or transferring access or materials (§ 6.1(h)); prohibits using the Services "to carry out any financial activities subject to registration or licensing" (§ 6.1(m)); prohibits reverse engineering "except to the extent that the activity is expressly permitted by applicable law" (§ 6.1(f)(iii)).
- **[Market Data Terms of Service](https://massive.com/legal/market-data-terms-of-service)** (last updated 2025-08-28), incorporated into every subscription:
  - **§ 1:** the Market-Data license is "nonexclusive, nontransferable, non-sublicensable, revocable, limited … exclusively for your personal, non-business, and non-commercial purposes. For the avoidance of doubt, you may not use the Market Data for any business or commercial purpose, and **you may not use the Market Data to build an application intended for use by end users other than you.**"
  - **§ 2:** absent a further agreement, "any and all Market Data is strictly for **display use only**."
  - **§ 5(c):** no "redistribute, display, disseminate, duplicate, license, sublicense, publish, broadcast, transmit, distribute, … sell, resell, rebrand, or otherwise transfer" — including **"Derived Works"** (data, charts, analytics, research "based on, referring to, or derived from the Market Data").
  - **§ 5(d):** no non-display use or creation of derivative financial products (indices, NAVs, investment products) without a license.
  - **§ 3:** subscriber-status warranty — Non-Professional only (personal, non-business; not a registered/qualified person with SEC/CFTC/exchange; not "engaged as an investment advisor" under § 202(a)(11)); Massive bills the **retroactive difference** to professional rates if it later determines you qualify. Embedded schedules make the OPRA/Nasdaq/UTP/NYSE/CME subscriber agreements binding, with SRO third-party-beneficiary enforcement (e.g., NYSE Schedule 2 § 3: SROs may enforce; subscriber pays their attorneys' fees).
  - **§ 8:** on termination, cease use and **delete all Market Data**.
- **Business use** is governed by separate [Massive for Businesses Terms](https://massive.com/legal/businesses-terms-of-service) **[not fetched — open item 2]**; note the plan needed is a "Business Use"-labeled product, per the /terms routing.

**Implication for V2:** Polygon/Massive data **cannot** power a sold product on individual-tier credentials — not even via a BYO-key design, because the individual terms themselves ban business use and end-user applications. Any commercial embedding requires the business terms plus, for equity/options real-time, the exchange subscriber/vendor stack.

### 3.2 Databento

- **[Databento User Agreement](https://databento.com/legal/databento-user-agreement/platform-access)** (effective 2024-01-31):
  - **§ 1.1:** license to access the Platform and Third-Party Data "solely for its **internal business purposes**."
  - **§ 1.4(b)/(c)/(d):** no transferring, distributing, sublicensing, or service-bureau use; no disassembly/decompilation/reverse engineering of the Platform; no using the Platform "in order to build a **similar or competitive application or service**."
  - **§ 1.5(e):** defines **"Redistribution"** ("the publication or distribution of covered data, the use of such data to create financial products, and all other means of furnishing such data or other information derived from the same to entities other than Customer") — prohibited except where it complies with the relevant Third-Party Provider Agreements **and** Databento's prior written approval.
  - **§ 1.6:** any permitted Redistribution must attribute "Data Provided by Databento" (or an enterprise contract without attribution); **§ 1.7:** screenshots allowed with attribution, unmodified.
  - Third-Party Providers are third-party beneficiaries with direct enforcement rights (§ 1.5(c), (f)); termination obliges ceasing use.
- **[Pricing](https://databento.com/pricing):** Usage-based (pay-as-you-go history); **Standard $199/mo** ("No license fees", up to 2 devices, internal); **Plus $1,750/mo** (annual contract, "**External distribution**"); **Unlimited $4,500/mo**. Live data requires activating per-exchange licenses — "We pass through these license fees with no upcharge," self-service agreements in the portal. Login page: "Databento is a licensed distributor of market data from over 70 trading venues."
- Code is free where it matters: the DBN format/client libs are Apache-2.0 (e.g., [github.com/databento/dbn](https://github.com/databento/dbn)) — same split as Devexperts: **open client, licensed data**.

**Implication for V2:** Databento is the clearest paid path for embedding data in a sold product: internal build/test on Standard; customer-facing display/derivative features need the **Plus tier (external distribution)** plus per-exchange agreements and attribution — or an enterprise contract.

### 3.3 IEX Cloud (retired — recorded for the pattern)

- iexcloud.io is **unreachable today** (connection failure, verified from this machine) and the service **ceased operating around August 2024** ([Wikipedia — secondary](https://en.wikipedia.org/wiki/IEX)). The final ToS survive via the Internet Archive: **[Terms of Service (Wayback, 2024-09-10)](https://web.archive.org/web/2024/https://iexcloud.io/terms/)**:
  - **§ 1.1:** license to use the Services "solely for use by Customer and Customer End Users in Customer's Application(s)" — notably *more permissive of end-user apps* than Polygon's.
  - **§ 1.2(b):** no reverse engineering "except to the extent expressly permitted by applicable law."
  - **§ 1.3:** third-party end users may access "IEX Cloud Core Data" for **display purposes only**, with attribution and pass-through protective terms.
- Lessons: (a) vendor ToS differ sharply on end-user display — read each one, never generalize; (b) **vendor mortality** is real; design V2's data layer against a swappable interface so a feed vendor dying is a commercial event, not an architectural one.

### 3.4 OANDA (V1's lane — practice, and the multi-user boundary)

- **[OANDA legal resources page](https://www1.oanda.com/resources/legal/)** (fetched today): "OANDA Corporation is a registered **Futures Commission Merchant and Retail Foreign Exchange Dealer** with the Commodity Futures Trading Commission and is a member of the **National Futures Association. No: 0325821**"; "'OANDA', 'fxTrade' and OANDA's 'fx' family of trademarks are owned by OANDA Corporation"; and "OANDA Corporation does not act in the capacity of your financial advisor or fiduciary and **simply executes customer instructions**."
- **[Developer portal](https://developer.oanda.com/):** the API-usage wizard asks "**Will others trade and access their accounts with your application?**" — and routes every yes to the **Partner Form** (institutional/partner lane), away from the self-serve personal-token lane V1 uses. The v20 personal access token is account-scoped (see the [v20 introduction](https://developer.oanda.com/rest-live-v20/introduction/): you must have a v20 trading account).
- **[Not found today — open item 3]:** a standalone current "OANDA API Terms of Use" document (old `oanda.com/legal/api-terms-of-use` and site terms-of-use URLs 404; the oanda.com restructure is JS-heavy). The API surface facts (practice host, free practice accounts) are carried in the sibling venue survey [#329](v2-venues-feeds.md) from primary developer docs.

**Implications for V2:**
1. **Single-user tool on the customer's own account (BYO token)** — V1's shape — is the lane OANDA's self-serve API is designed for. Keep V2's FX execution there for launch.
2. **A hosted/multi-user V2 that logs into customers' OANDA accounts** crosses into OANDA's Partner lane — a commercial/API-terms gate before that feature, not just a code feature.
3. OANDA is the RFED/FCM (the counterparty); V2-as-customer-tool is not and must not become the counterparty (see Part 4).
4. Same trademark rule as Schwab: "OANDA"/"fxTrade" marks are theirs — nominative references only, disclaimers attached.

### 3.5 Cross-cutting decision for the spec: BYO-key vs bundled data

- **BYO-key architecture** (each customer supplies their own vendor credentials) shifts the *data* contract to the customer — but does **not** immunize V2: Massive's individual terms ban business use by the key-holder too; Databento's User Agreement binds each customer to internal use unless they hold redistribution entitlements. V2 marketing copy must not instruct customers into breach.
- **Bundled data** (V2 redistributes) requires the vendor's external-distribution tier (Databento Plus/enterprise; dxFeed written approval + exchange vendor agreements; Massive business terms) — a recurring per-exchange cost line item in the spec's commercial model, not a footnote.
- **Paper/simulated data** (V2's own synthetic feed, or delayed/free sources each user pulls themselves) is the launch-safe default while the commercial model is locked.

---

## Part 4 — Regulated-activity boundary: V1 today vs the sold product

### 4.1 Where V1 stands (and why)

V1 is practice/paper-based: OANDA v20 **practice**, the human's own funds at risk only, no compensation from third parties for trading or advice. It triggers none of the definitions below — not because "paper trading" is specially exempt, but because the statutory elements (transactions in *others'* accounts; compensation for *advice*; a *business* of effecting or advising) are absent. Selling V2 the same way — a **tool**: customer's own accounts, customer's own credentials, no advice, no custody, no routing-for-others — keeps that posture. Each feature that changes one of those elements changes the regulatory analysis.

### 4.2 Securities (SEC/Finra) — what changes as V2 is sold

- **Broker-dealer:** 15 U.S.C. [§ 78c(a)(1)](https://www.law.cornell.edu/uscode/text/15/78c): the term "broker" "means any person engaged in the business of **effecting transactions in securities for the account of others**." Registration: [§ 78o(a)](https://www.law.cornell.edu/uscode/text/15/78o) ("It shall be unlawful for any broker or dealer … to make use of the mails or any means or instrumentality of interstate commerce … unless registered"). **Triggers to watch:** V2 (or V2-hosted agents) routing/executing securities orders for customers; handling order flow as part of a hosted service; transaction-based compensation for securities-related facilitation. A self-directed tool where the *customer* presses the button on their *own* brokerage account is the classic non-BD shape — but hosted multi-user execution pushes toward "effecting."
- **Investment adviser:** 15 U.S.C. [§ 80b-2(a)(11)](https://www.law.cornell.edu/uscode/text/15/80b-2), verbatim: "any person who, **for compensation, engages in the business of advising others, either directly or through publications or writings, as to the value of securities or as to the advisability of investing in, purchasing, or selling securities**, or who … issues or promulgates analyses or reports concerning securities." **Triggers:** selling V2 "strategy packs," signals, or AI-agent recommendations on securities for compensation; performance-fee pricing; even written "what to trade" content if it's the product. Software with no advice (user defines own strategies) is the low-risk shape; marketing that highlights our strategies' returns can convert the product into advice.
- **Reg BI** (17 C.F.R. § 240.15l-1) applies only once a BD makes recommendations to retail customers — a gate behind the BD gate, noted for completeness.
- **Anti-fraud applies to everyone:** § 10(b)/Rule 10b-5-style liability and state analogues apply to unregistered sellers too — performance claims in V2 marketing must be evidence-backed (this also matches the repo's claims-governance rules).

### 4.3 FX (CFTC/NFA) — V1's asset class

- **OANDA is the RFED/FCM counterparty** (NFA 0325821, above) — V1/V2 as the customer's tool is outside dealer registration by construction. V2 must never take the other side of, or custody, customer FX trades.
- **Commodity trading advisor:** 7 U.S.C. [§ 1a(12)](https://www.law.cornell.edu/uscode/text/7/1a), verbatim: "any person who — **for compensation or profit, engages in the business of advising others, either directly or through publications, writings, or electronic media, as to the value of or the advisability of trading in** — (I) any contract of sale of a commodity for future delivery, … [or] (II) any agreement, contract, or transaction described in section 2(c)(2)(C)(i) … **" — § 2(c)(2) covers retail FX (leverage) transactions. **Trigger:** selling FX trading advice/analyses/reports for compensation — including "AI agent" outputs that advise on FX trades. Exemptions exist (e.g., advice solely incidental to another business, or to fewer than 15 persons), but that analysis is counsel's, not ours.
- **Introducing-broker:** soliciting FX customers for OANDA for compensation implicates the IB definition (CEA § 1a(29) family) — relevant the moment V2 runs a "sign up with our partner broker" funnel for a fee.
- **A2A asset trading** (map #326's surface): if V2 "agents" trade *other people's* funds or accounts, that is CTA (advice/authority) and potentially portfolio-manager/fiduciary territory regardless of asset class — counsel gate. If each customer's agents trade only that customer's own account on that customer's standing instructions, the tool framing holds — but the marketing must describe it that way, and disclosed performance rules still bite.

### 4.4 Multi-user / hosted-service risks (map #326's open shape)

1. **Custody:** never hold, transmit, or "float" customer funds (money-transmission and FCM analyses attach to custody + trading). Subscription billing for software is fine; billing for trades is not.
2. **Execution-as-a-service:** hosted order handling for many users' accounts is the BD-shaped feature; keep execution client-side (user's machine/keys) at launch.
3. **Advice creep:** dashboards, rankings, and "top strategies" features read as advice when sold; label, disclaim, and route through counsel before shipping anything that recommends.
4. **Data resale:** Part 3 — every customer-facing data display is "redistribution/external distribution."
5. **Trademark/disclaimers:** "not affiliated with" blocks for every named third party (Schwab, OANDA, Databento, etc.); risk-disclosure and performance-claim standards for anything published.

### 4.5 Counsel-gate list (the human's checklist before these ship)

1. Any real-money order routing/execution for securities customers (BD analysis).
2. Selling advice, signals, strategies, or agent recommendations for compensation — securities or FX (RIA/CTA analysis; exemptions).
3. A2A agents trading anyone's assets other than the subscriber's own (CTA/PMM/fiduciary).
4. Hosted multi-user trading service (order handling, custody, data redistribution, terms drafting).
5. V2 marketing/naming review against the trademark families above.
6. Entity formation, customer ToS/EULA drafting, and export-control/sanctions screening for a commercial SaaS/product.

---

## Part 5 — Open items (for the spec's TODO list)

1. **Capture the full thinkorswim EULA** (presented at install/first-run, absent from the bootstrap) and review its reverse-engineering/use clauses; record who has ever accepted it and on what machine. Blocks further client-side recon beyond static study.
2. **Fetch the Massive for Businesses terms** when a business data plan is actually contemplated (individual + market-data terms already captured).
3. **Locate OANDA's current API/developer legal terms** (site restructure made old URLs 404; partner-form boundary already documented from the portal wizard).
4. **Verify "ThinkScript" trademark status** specifically (not in the top-20 family search results; likely registered or claimed — treat as Schwab's mark until proven otherwise).
5. **OPRA/UTP/CTA vendor agreements** if equities/options real-time resale ever lands (current links on dxFeed's [3rd Party Terms page](https://dxfeed.com/3pty/)).

## Limitations

- **This is not legal advice.** It is a research dossier compiled by an autonomous non-lawyer agent for spec planning; every conclusion marked "counsel gate" is unverified until a licensed attorney signs it. US-centric; other jurisdictions (V2 customers abroad) not analyzed.
- **Snapshot dates:** all fetched sources were live on 2026-10-06 unless noted (IEX ToS via Wayback 2024-09-10; dxFeed Services Terms "effective April 2025"; Massive terms 2025-07-18 / 2025-08-28; Databento User Agreement 2024-01-31; QD repo last push 2026-09-08). Terms change; re-verify at contract time.
- **Secondary sources used and labeled:** Justia (USPTO aggregation) for trademark filings/owners; Wikipedia for the IEX Cloud retirement date. The Justia listings do not show live/registered status per application — ® usage by Schwab on its site and in the client EULA is the primary evidence of registration for the core marks.
- **Case-law citations** (Sega, Connectix, Atari, Google v. Oracle, Bowers, MDY, New Kids) are quoted by citation with standard characterizations, not re-read in full for this doc; treat them as pointers for counsel, not as analysis.
- **Web-tool note:** OANDA's and Schwab's main sites are JS-rendered; some legal URLs 404 through restructure. Where a page could not be verified from a primary source today, it is marked as an open item rather than assumed.
