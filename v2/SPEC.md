# Opentrader V2 — Locked Spec

**Status:** draft for human signoff (map [#326](https://github.com/rivers-research-hq/opentrader/issues/326), ticket "Assemble and lock the V2 spec" [#340](https://github.com/rivers-research-hq/opentrader/issues/340))
**Date:** 2026-10-07 · **Every decision below is human-locked in its ticket; this document assembles them and resolves seams.**
**Research provenance:** `docs/agents/research/v2-*.md` (8 dossiers, source-cited) · decisions: the map's Decisions-so-far index.

---

## 1. Product definition

**Opentrader V2** is a thinkorswim-class, multi-venue trading platform in Rust — a desktop
terminal (charts, scripting, trade ladder, scanner, paper trading) sold as freemium software,
plus a hosted, metered **MCP server** that AI agents anywhere use to trade the operator's own
capital (access-rental, never profit-share). FX-first (OANDA), expanding across the top-10
retail brokerage APIs wave-by-wave. V1's research corpus and FX lanes are inputs and running
systems, not implementation base: **V2 is a clean-room rebuild, all-Rust.**

## 2. Posture & legal lanes (binding invariants)

| Invariant | Decision |
|---|---|
| Launch posture | **Hybrid**: BYO-keys desktop binary + hosted MCP API on operator capital |
| Account model | Humans bring their own broker keys; venues see each user's own account |
| Hosted side | Customers' agents trade **operator's** books via purchased access |
| Profit structure | **Access-rental, never profit-share** (profit-share ⇒ CTA/pool counsel gate) |
| Third-party funds | Agents trading for third parties = **not a launch lane** (counsel first) |
| Data pricing | All costs assume **individual non-pro status** — explicit invariant; external-money management flips feeds to professional/enterprise pricing |
| thinkorswim RE | Clean-room study only (Sega/Accolade posture; DMCA §1201(f)); no decompiled code, assets, or marks. `ThinkScript`/`think*`/`swim` families prohibited in naming/marketing |
| Open legal items | Actual Schwab EULA sits behind authenticated web login (not in the download) — capture at next legitimate opportunity; partner-program venues (OANDA for-others, Schwab, IBKR) counsel-gated before live multi-user routing |

Provenance: [#343](https://github.com/rivers-research-hq/opentrader/issues/343), [#332](https://github.com/rivers-research-hq/opentrader/issues/332) (`v2-legal-licensing.md`).

## 3. Architecture (all-Rust)

```
v2/                      ← Cargo workspace (this repo, top-level)
├── core/                ← deterministic event-driven engine (engine truth)
├── venues/              ← venue-abstraction trait + adapters (oanda, ibkr, alpaca, …)
├── script/              ← series-native DSL: parser, AST interpreter (Cranelift JIT phased)
├── chart/               ← egui + egui_plot + custom wgpu surfaces
├── terminal/            ← the desktop app (egui)
├── mcp-server/          ← hosted A2A surface (tool-calls, metered)
└── updater/             ← staged in-app updater
```

- **One internal venue-abstraction trait** (account, quotes, orders, positions, history)
  feeding BOTH the egui client and the MCP server. Every added broker = one adapter crate.
- **Event-driven core**: barter/Nautilus patterns adopted as *design* (deterministic replay,
  backtest/live parity), not as dependencies (LGPL / educational disclaimers exclude embedding
  in a closed-source product — `v2-v1-salvage.md` §5).
- **Backtest/live parity is a spec invariant**: backtest = replay of historical events through
  the same handlers live trading uses.

Provenance: [#335](https://github.com/rivers-research-hq/opentrader/issues/335), [#336](https://github.com/rivers-research-hq/opentrader/issues/336), [#345](https://github.com/rivers-research-hq/opentrader/issues/345).

## 4. Engine contract (verbatim from V1, on the event-driven core)

Decisions from the **previous** bar's close (`t-1`); fills at the **current** bar's close;
warm-up one bar late; same-bar high/low exit evaluation (TP/SL vs same-bar H/L, trailing peak
from highs, max-hold/signal/RSI exits); per-bar-dropna cross-sectional rank + date-guard
(symbol uncovered at the signal bar is unscored, never silently dropped); delist force-exit at
last close. **The contract lands as a `proptest` suite from day one** (the pre-1718f33
same-bar bug inflated metrics ~4–5pp — property tests are the defense). This engine is the
single truth for the platform, the scanner, script backtests, and the **FX cutover parity
test** (below).

Provenance: [#345](https://github.com/rivers-research-hq/opentrader/issues/345), `v2-v1-salvage.md` §2.1.

## 5. Venues & data

| Layer | Decision |
|---|---|
| Launch venues | **OANDA v20** (V1 semantics carried + streaming) · **IBKR paper via `ibapi`** (TWS socket, full parity) · **Alpaca paper** (optional, zero-cost) |
| Launch cost | ≈ $0/mo fixed (IBKR subs optional +$1.50–$10 until commission waivers) |
| Top-10 rollout | Trait-first, adapters **wave-by-wave** behind the venue trait (Schwab, E\*TRADE/MS, Tradier, Tastytrade, TradeStation, Webull, crypto anchors); BYO-keys throughout; partner venues counsel-gated |
| Backtest corpus | Dukascopy free FX ticks + OANDA candles + Databento $125 free credits |
| Phase-2 data | No pre-committed spend; $99/$199 tiers unlock on concrete trigger (databento/Alpaca-table in `v2-venues-feeds.md`) |
| Deferred (not excluded) | cTrader, MT5, LMAX, dxFeed — trigger-gated; IEX Cloud retired; OANDA Rust crates rejected (hand-roll the port) |

Provenance: [#336](https://github.com/rivers-research-hq/opentrader/issues/336), `v2-venues-feeds.md`.

## 6. Scripting language

- **ThinkScript-inspired, series-native DSL** — implicit per-bar evaluation, plot model, study
  composition; ThinkScript's documented warts dropped (`v2-thinkscript-study.md`).
- **Binding design constraints** (from the usergui dissection): scanner filter/sort = the same
  language; strategy subsystem = **order-aware** (scripts place/track virtual orders — script
  backtests run on the §4 engine); MCP surface can evaluate scripts.
- **Execution**: AST interpreter now (hot-reload, sandboxed); **Cranelift JIT = phased
  scanner-backend wave** (language unchanged). Pine-compatible import = later optional wave.
  Rhai embedding: dropped.
- Language definition spec: [#346](https://github.com/rivers-research-hq/opentrader/issues/346) → `v2-scripting-spec.md`.

Provenance: [#337](https://github.com/rivers-research-hq/opentrader/issues/337), [#328](https://github.com/rivers-research-hq/opentrader/issues/328), [#344](https://github.com/rivers-research-hq/opentrader/issues/344).

## 7. GUI (egui)

- **egui** locked: `egui_plot` for plots; custom painter/`Shape::Callback` or raw wgpu surface
  for dense ladders/depth; `egui_extras::TableBuilder` for watchlists/orders. Streaming-native
  immediate mode; production-grade table widget; MIT/Apache-2.0; single self-contained binary.
- **Runner-up iced** (Kraken Desktop precedent) stays documented as the fallback if egui fails
  the chart/ladder spike — the spike gate remains open as a measured fallback path.
- **Launch bar = Tier 3 (full thinkorswim parity)**: charts, scripting, ladder/DOM, scanner,
  paper trading, Analyze-tab risk modeler, active-trader views. Tiers 1–2 are internal
  milestone waves in that order, not launch tiers.

Provenance: [#335](https://github.com/rivers-research-hq/opentrader/issues/335), [#334](https://github.com/rivers-research-hq/opentrader/issues/334), `v2-rust-gui.md`, `v2-tos-dissection.md`, `v2-usergui-dissection.md`.

## 8. A2A surface (MCP)

- V2 ships an **MCP server**; agents (Claude, pi, any MCP client) onboard as customers with
  operator-issued keys, metered per tool-call.
- **Two-meter pricing (binding)**: reads approach infra cost (~$10⁻⁶/call); actions carry
  $0.01–$1 each. Structure: free/rate-capped capacity tiers (reads) + per-order metered fees
  (actions) + MCP/x402 per-tool-call settlement. **Metering both at one price = spec violation.**
- Dollar price points: deliberately **not locked** — launch-operational decisions after live
  market checks.
- Hosted-side risk bounds: operator risk systems bound what any agent can do on the operator's
  books (guards semantics port, §10).

Provenance: [#334](https://github.com/rivers-research-hq/opentrader/issues/334), [#338](https://github.com/rivers-research-hq/opentrader/issues/338), `v2-commercial.md`.

## 9. Packaging & updates

- **Launch = Linux only** (build/dogfood platform; hosted MCP carries the product); Windows/macOS
  binaries = first post-launch wave.
- **GitHub Releases, signed artifacts**; in-app staged updater: versioned manifests, overwrite-if-newer,
  atomic swap, rollback on failed boot, stable/beta/nightly channels. install4j's JVM machinery is
  deliberately not replicated (static binary needs none of it).

Provenance: [#342](https://github.com/rivers-research-hq/opentrader/issues/342).

## 10. V1 salvage & FX continuity

- **Semantic ports (faithful, defect-knowledge-bearing)**: `exchange/oanda.py` (venue-truth
  `place_order` — no `orderFillTransaction` ⇒ REJECTED; fresh-price rule — no write-once
  never-expiring caches; `clientExtensions` owner tagging), `security/guards.py`,
  `strategies/lane_attribution.py` (resolver chain clientExtensions → orderID →
  tradesClosed/tradeReduced/tradeOpened; loud `unattributed` bucket, never silent credit).
- **Research input, not code**: MoT/arena layer + honest-negative record (the corpus of
  falsifications is product-defining: V2 sells tooling, not a claimed edge).
- **FX continuity**: V1's five OANDA lanes keep running untouched per `docs/agents/fx-ops.md`
  while V2 builds. **Cutover test**: V2 must replay V1's lane ledger through the §4 engine
  (venue parity) before any live migration.
- **Workspace**: `v2/` top-level in this repo; issues/map/dossiers stay here.

Provenance: [#339](https://github.com/rivers-research-hq/opentrader/issues/339), `v2-v1-salvage.md`.

## 11. Wave roadmap (sequencing only — each wave still gates on its own work)

1. **W0 — engine truth**: event-driven core + §4 contract + proptest suite + venue trait skeleton.
2. **W1 — FX on V2**: OANDA adapter (semantic port) + streaming; ledger replay parity test; egui charts WIP.
3. **W2 — terminal alpha**: charts/watchlists/paper trading; scripting DSL interpreter; IBKR+Alpaca adapters.
4. **W3 — A2A**: MCP server + two-meter metering + hosted-capital risk bounds.
5. **W4 — Tier-3 parity**: ladder/DOM, scanner (same language), Analyze-tab risk modeler; Cranelift scanner backend; Linux release + staged updater.
6. **W5+ — expansion**: top-10 venue waves; Windows/macOS binaries; Pine-import wave; packaging formats; price-point launch ops.

## 12. Open items (tracked, not blockers to this spec)

- Schwab EULA capture (behind web login) — legal dossier open item.
- Counsel gates: partner-program venues; any move toward external-money management.
- #346 scripting-language spec (AFK, in flight) — feeds W2.
- egui chart/ladder spike (measured fallback gate) — before W2 chart lock-in.
- thinkorswim naming: V2 product naming must clear the `think*`/`swim` trademark family.
