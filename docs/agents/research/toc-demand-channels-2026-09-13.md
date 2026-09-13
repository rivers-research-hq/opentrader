# Research: demand & channels for local-LLM/agent tooling (toc open-core launch)

- **Ticket**: rivers-research-hq/opentrader#262 (map #260 "toc business: open-core launch to first revenue") — 2026-09-13
- **Question**: where do toc's likely buyers congregate, what evidence exists that they **pay** for tooling (not just star it), and which channels reward an open-source CLI launch?
- **Method**: primary sources only — official rule pages, vendor pricing/terms pages, HN's first-party Algolia API. Live reddit.com and several vendor sites are bot-walled (403/Cloudflare); where noted, Reddit rule text comes from **Wayback Machine captures of the server-rendered `old.reddit` rules pages** (the same rule text Reddit serves), capture dates noted. Items I could not verify are labeled **UNVERIFIED** — nothing below is quoted from memory.

---

## 1. Channels and self-promotion norms

### Hacker News — Show HN (launch-grade)

On-topic for toc: the official Show HN page defines the scope as **"things people can run on their computers or hold in their hands"** — an installable CLI qualifies; landing pages, sign-up pages and newsletters do not ("submit those as a regular story instead").

Official rule text ([news.ycombinator.com/newsguidelines.html](https://news.ycombinator.com/newsguidelines.html), [showhn.html](https://news.ycombinator.com/showhn.html)):

- **"Please don't use HN primarily for promotion."** — but **"It's ok to post your own stuff part of the time."**
- **"Don't solicit upvotes, comments, or submissions."** — Show HN adds: **"Please don't ask friends to upvote or comment."**
- Requirements: non-trivial, personally worked on, **creator present in the thread**, **"Make it easy to try"** (no signups/email walls), no landing pages or fundraisers. Early-stage is fine; "Foo 1.3.1 is out" updates are not.

Verified outcomes (HN Algolia API, first-party):

| Thread | Points | Comments | Date |
|---|--:|--:|---|
| "Show HN: Ollama – Run LLMs on your Mac" | 284 | 94 | 2023-07-20 |
| "Aider: AI pair programming in your terminal" (third-party post) | 432 | 156 | 2024-04-10 |
| "Show HN: LocalScore – Local LLM Benchmark" | 124 | 24 | 2025-04-03 |
| "Show HN: Execute local LLM prompts in remote SSH shell sessions" (median case) | 3 | 2 | 2026-03-13 |

High variance is the real norm: most local-LLM Show HNs land 3–40 points; the hits need a working artifact plus a story HN cares about. Ollama's launch sold "run LLMs locally, dead simple" — toc's comparable story is "make a small model trustworthy enough to offload real work to."

### r/LocalLLaMA (largest buyer concentration)

Rule text via Wayback capture of the server-rendered `old.reddit.com/r/LocalLLaMA/about/rules` (2025 capture; live Reddit is bot-walled):

- **Rule 2 "Off-Topic Posts"**: "Posts must be related to Llama or the topic of LLMs."
- **Rule 3 "Low Effort Posts"**: "Asking questions is allowed, but follow Rule 1. Low effort posts may be removed."
- **Rule 4 "Limit Self-Promotion"**: **"The 1/10th rule is a good guideline: self-promotion should not be more than 10% of your content."**
- Rule 5: follow Reddit's Content Policy.

Flairs observed in the sidebar: Discussion, Tutorial | Guide, New Model, News, Resources, Other. The 2026 sidebar capture shows **no Discord link** — do not assume one exists.

Implication: no cold product posts. Post as a practitioner — e.g. a Tutorial|Guide piece ("how I keep a 27B quant inside its competence envelope with a token budget + epistemic ledger") with toc as the tool that made it work, and stay in the comments. One substantive post per account per several posts of ordinary participation.

### r/LocalLLM (smaller mirror audience)

Rules via Wayback capture (2026-07-27) of `old.reddit.com/r/LocalLLM/about/rules` — structurally identical:

- **Rule 3 "Limit Self-Promotion"**: **"The 1/10th rule is a good guideline: self-promotion should not be more than 10% of your content."** (verbatim same as r/LocalLLaMA)
- Rule 5 anti-spam: "If your post in under review by moderators, do not spam similar posts in an attempt to get around it or you will be banned." (typo "in under review" is in the original)

### X/Twitter

No formal self-promotion rule exists (unlike HN/Reddit) — norms are cultural: reply-first engagement, build-in-public threads, screenshots/demos over links. Treat X as an **amplifier** (thread where the HN/Reddit discussion lands) and a credibility trail, not as a discovery channel. No rule text to quote; no barrier to entry.

### Discord / Matrix communities

All rule text is **gate-kept in-server and not publicly fetchable**; nothing verifiable to quote. The known gathering servers in this space (llama.cpp, Hugging Face, tool-specific servers) — links/rules **UNVERIFIED at research time**. Working assumption from universal Discord norms: showcase channels exist, unsolicited DMs/ads get you banned, lurk first. Use Discord/Matrix as the **support home after launch**, not the launch itself.

### Dev newsletters / curators

- **console.dev** (CLI-tool newsletter): live site returned 403 to our fetcher at research time; the `/submit/` path is gone (404). Its historical model was free editorial submissions. **UNVERIFIED at research time — re-check their current submission route before pitching.**
- **Terminal Trove** (terminal-tools directory/newsletter): live site 403 to bots; its GitHub org has no public submissions repo (only `homebrew-tap`, `lumon`, `moltbook-tui`). Submission route **UNVERIFIED — check the live site**.
- **TLDR AI / similar newsletters**: paid sponsorship with rate cards — that is paid reach, not earned; **not fetched, pricing UNVERIFIED**.

---

## 2. Willingness-to-pay evidence in this audience

Comparable OSS dev tools with **public, verified numbers**:

| Tool | Model | Verified specifics |
|---|---|---|
| **Tabby** (self-hosted AI code assistant, OSS) | open-core | Community: **"Free, Open Source"**, "Up to 5 users", local deployment. Team: **"$19/mo per seat"** (up to 50 users). Enterprise: **"Custom"** — SSO, dedicated Slack, roadmap prioritization. (tabbyml.com/pricing) |
| **Open WebUI** (local-LLM web UI, OSS) | brand-license open-core | **"Open WebUI is free to use as-is for everyone."** Standard = internal use "with original branding exactly intact". Enterprise License (white-labeling/rebranding) = contact sales, **organizations only**, no public price. (docs.openwebui.com/enterprise) |
| **BoltAI** (paid Mac app running local LLMs) | one-time license | **"Pay once. Use forever."** Essential **"$79 for 1 seat"** — marketed "For students and hobbyists"; Pro $99; Pro+ $199; Team "$99 per seat" + optional $79/seat/yr. 50% student discount, 30-day money-back. (boltai.com/pricing) |
| **Charm** (charmbracelet OSS CLI tooling) | OSS + enterprise contact-sales | Tools **"Always open-source"**; business = Enterprise contact CTA ("Charm technology lives in over 25,000 applications…"); no public pricing. (charm.land) |
| **LM Studio** (local-LLM desktop app) | free app + reserved paid features | Terms license the app for **"personal and / or internal business purposes"** (no separate commercial wall), state **"Certain features of the Software may be offered for a fee, including through subscriptions, usage-based charges"**, and prohibit SaaS resale ("as an application service provider, or a software-as-a-service"). (lmstudio.ai/terms) |
| **Ollama** (OSS) | free binary, paid hosted convenience | "Ollama Turbo" (2025-08-05) reached 430 pts / 243 comments on HN — the monetization attempt is hosted compute, not the tool. |

**Negative evidence — donations are not a model**: starship (a very popular OSS CLI) on OpenCollective after 5 years: **"Total raised: $8,573.42 USD"**, balance $8,362.75, 28 contributors; top org tier **"Sponsor $500 USD/month"** unsold ("Be the first one to contribute!"). GitHub Sponsors itself totaled $8,866.59 since Oct 2020. ~$1–2k/year is the donation ceiling for a beloved CLI.

**Synthesis for toc's buyers (r/LocalLLaMA-class users, agent devs, small teams on quantized models):**

1. The **core CLI is expected free** — the default local stack (Ollama, llama.cpp, Open WebUI, LM Studio app, aider) is all free, and LM Studio's terms even fold internal business use into the free license.
2. Where money actually changes hands in this audience:
   - **team/org features**: seats, SSO, support, white-label — Tabby $19/mo/seat, Open WebUI enterprise, Charm enterprise (unpriced);
   - **polished one-time pro licenses**: BoltAI's $79–$199 "students and hobbyists" tier proves local-LLM hobbyists buy licenses;
   - **hosted convenience/compute**: Ollama Turbo.
   - **donations/sponsor tiers: essentially zero** (starship).
3. Open-core fit for toc: **free CLI core** (governance of your own local model), paid tier aimed at **teams/orgs** (shared ledgers/multi-user budgets, SSO/seats, support SLA, licensing for internal-tool builds) and/or a **one-time pro tier** for individuals. A subscription-only, donations-based, or "pay to unlock the CLI" model all contradict the verified evidence.

---

## 3. Ranked launch channels for the toc CLI

1. **Show HN** — the only channel where a single earned post verifiably reaches the whole audience at once (Ollama 284 pts; Aider 432 pts via third party), and a CLI is squarely on-topic ("things people can run on their computers"). Requirements are strict and verifiable: runnable immediately, no signup, creator answering comments, zero vote-solicitation. Plan for median-case flop (3–40 pts) as the expected value; the upside case is the actual goal.
2. **r/LocalLLaMA, then r/LocalLLM** — highest density of the exact buyer (people running quantized models locally) and the 1/10 rule makes the winning format predictable: a Tutorial|Guide-flavored practitioner post with dogfood evidence, not a launch announcement. Rule text quoted above is the launch constraint.
3. **X/Twitter build-in-public** — no formal rules, low friction; use as the persistent evidence trail and the place HN/Reddit traffic can follow. Weak discovery on its own.
4. **Dev curators: console.dev, Terminal Trove** — earned, editor-controlled listings aimed precisely at CLI users; near-zero cost. Submission routes could not be verified at research time (bot-walled) — verify before launch week.
5. **Discord/Matrix (llama.cpp, HF, tool-specific servers)** — in-server rules, no public text; right as a **support home and slow-burn presence** after launch, wrong as a launch vehicle.
6. **Product Hunt / DevHunt** — broad, consumer/PM-flavored noise; poor fit for a governance CLI. Optional echo, do not spend the launch there. (DevHunt's own submit mechanics were not retrievable in text form at research time.)

Sequencing recommendation: X trail (weeks −2..0) → Show HN day 0 → r/LocalLLaMA guide day 2–5 (after HN feedback is folded in, so the Reddit post is the improved story) → curators week 2 → Discord as support home. One account, one story, 1/10 rule respected everywhere.

---

## 4. Source register

| Claim | Source |
|---|---|
| HN guidelines quotes | https://news.ycombinator.com/newsguidelines.html |
| Show HN scope + "don't ask friends to upvote" | https://news.ycombinator.com/showhn.html |
| Ollama/Aider/LocalScore/median-flopper outcomes | https://hn.algolia.com/api/v1/search (queries: `"Show HN: Ollama"`, `aider`, `"Show HN" "local LLM"`, tags=story) |
| r/LocalLLaMA rules (1/10 rule) | Wayback capture: https://web.archive.org/web/2025/https://old.reddit.com/r/LocalLLaMA/about/rules |
| r/LocalLLM rules (1/10 rule) | Wayback capture 2026-07-27: https://web.archive.org/web/2026/https://old.reddit.com/r/LocalLLM/about/rules |
| No-Discord sidebar observation | Wayback capture 2026: https://web.archive.org/web/2026/https://old.reddit.com/r/LocalLLaMA/ |
| Tabby tiers | https://www.tabbyml.com/pricing |
| Open WebUI free/enterprise | https://docs.openwebui.com/enterprise |
| BoltAI prices | https://boltai.com/pricing |
| Charm enterprise-only | https://charm.land/ (redirect of charm.sh) |
| LM Studio terms | https://lmstudio.ai/terms |
| starship donation floor | https://opencollective.com/starship |
| Ollama Turbo thread | HN Algolia: "Ollama Turbo", 430 pts, 2025-08-05 |

**Caveats**: (1) Live Reddit, console.dev, terminaltrove.com, lmstudio.ai homepage, and aider.chat homepage were bot-walled or content-poor during research; Reddit rule text is taken from Wayback captures of Reddit's own server-rendered pages, which is primary text via an archive. (2) Discord/Matrix rule texts are in-server; the channel table marks them unverifiable rather than quoting from memory. (3) HN points decay over time — figures above are current Algolia snapshots (2026-09-13).
