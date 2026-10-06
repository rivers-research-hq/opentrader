# V2 GUI stack evaluation — egui vs iced vs Slint vs Tauri (+ charting options) (ticket 330)

**Purpose:** pick the Rust GUI stack for a thinkorswim-class desktop terminal (V2, part of the
spec map #326): streaming real-time charts, price ladders / order books, watchlists, heavy
tables, high tick rates, eventually packaged as a sellable binary.
**Method:** literature evaluation against primary sources only — official READMEs/CHANGELOGs/
release feeds via GitHub API, Kraken's engineering blog, TradingView/Tauri docs, crates.io
download stats (all retrieved 2026-10-06). No hands-on benchmark was run; a cheap spike gate is
proposed at the end. Recommendation framed for the human to lock.

## TL;DR recommendation (for the human to lock)

- **Primary: egui** (+ `egui_plot` for standard plots, custom painter/`Shape::Callback` or a raw
  wgpu surface for dense ladders/depth, `egui_table` or `egui_extras::TableBuilder` for
  watchlists/orders). Fastest upstream velocity in the field, the natural fit for streaming
  state (immediate mode renders the latest data each frame — no view/state sync bugs), the only
  stack with a production-grade millions-of-rows table widget, clean MIT/Apache-2.0 licensing,
  and a single self-contained binary with no system-webview dependency.
- **Runner-up: iced** — the *only* stack with a shipped thinkorswim-class precedent:
  **Kraken Desktop** (charts, order books, depth charts, ladders, multi-window, 48 modules per
  board) is built from scratch in iced per Kraken's own announcement. Choose iced over egui if
  you value that production precedent and its retained/Elm architecture more than upstream
  velocity and the table ecosystem; its risks are slow release cadence (one minor release in 15
  months), self-described "experimental" status, and open table/scrollable performance issues.
- **Tauri** = the fallback if we ever want web-ecosystem chart polish (TradingView
  `lightweight-charts` works day one) and accept a JSON-IPC tax on every tick plus a system
  webview. **Slint** is rejected for this use case (no charts, embedded-first, DSL friction)
  despite being the most license-clean, stable-API option.

## Requirement frame (what "thinkorswim-class" demands)

Heuristic envelope (engineering estimate, not measured; used only to grade the stacks):

- **Charts:** 10²–10⁵ bars per series, latest bar mutating at tick rate (10–100+ Hz for
  futures/FX), pan/zoom/crosshair over history, multiple synced charts.
- **Ladder / order book:** 50–200 price levels per side, full redraw at 10–50 Hz.
- **Watchlist / positions tables:** 10²–10³ rows × ~10–20 columns, cell updates at 5–10 Hz.
- **Global:** dozens of panels visible at once, ≤ 16 ms frame budget, continuous repaint while
  markets are open, low idle CPU when nothing changed, sells as a single installer/binary.

## Evaluation matrix

| Criterion | egui | iced | Slint | Tauri (webview) |
|---|---|---|---|---|
| Chart suitability | ◐ plot lib built for it (`egui_plot`), candles DIY (open FR #84); custom-painter escape hatch is first-class | ◐ no chart widgets; `Canvas` widget + cache is the escape hatch Kraken used | ○ no charts at all; custom `Path`/canvas drawing only | ● best: any web chart lib; TradingView `lightweight-charts` is purpose-built financial charting |
| Streaming / tick-rate performance | ● immediate mode renders latest state each frame; FAQ cites ~1–2 ms/frame typical; repaint-on-demand or continuous 60 fps; wasm+native | ◐ Elm messages — every tick must become messages and re-run `view()`; workable (Kraken proves it) but you must batch; regressed scrollables reported open | ◐ compiled property bindings, model/view ListView — good by design, but no trading-scale precedent | ○ every tick crosses JSON IPC; official docs steer "ordered, high-throughput" away from events to Channels; webview = 3 different JS engines |
| Heavy tables | ● `egui_table` (Rerun): "support for millions of rows", sticky header/columns; `egui_extras::TableBuilder` built in | ○ no official table widget; community `iced_table`; open freeze #1720 (large tables), scrollable perf regression #2603 | ◐ `StandardTableView` since 1.7 with ListView optimizations — real widget, untested at trading scale | ● the web is the best table ecosystem there is (virtualized grids), gated by IPC for updates |
| Maturity / upstream velocity | ● 0.36.2 (2026-09), ~9 releases in 15 months, 30.9k★, ~5.9M recent downloads; Rerun (11.5k★) in production on it; but breaking changes every release | ◐ 0.14.0 (2025-12) after 0.13 (2024-09); 31.7k★, ~0.6M downloads; README self-describes "experimental software"; Kraken Desktop + System76 COSMIC (libcosmic) are huge production wins | ● 1.18.1 (2026-09), stable 1.x API promise, 24.1k★, vendor-backed (SixtyFPS GmbH), embedded pedigree | ● Tauri v2 stable + v3 alpha (2026-10) adding a CEF runtime option; 111.6k★, ~13.5M downloads |
| Sellable single binary | ● MIT/Apache-2.0; eframe app = one static binary (~5–15 MB), no system webview | ● MIT/Apache-2.0; same one-binary story | ◐ tri-license: royalty-free for proprietary desktop OK, GPLv3, commercial for embedded — extra license surface to audit | ◐ MIT/Apache; tiny binary BUT depends on the OS webview (WebView2/WKWebView/WebKitGTK) — "single binary" is really "binary + system component"; `lightweight-charts` adds an Apache-2.0 attribution obligation |
| Dev velocity (solo Rust dev) | ● pure Rust, no DSL, no callbacks, no JS; hot docs/demo; 3rd-party crate wiki | ◐ pure Rust + Elm architecture (state/messages/update/view) — clean but more boilerplate for streaming data | ◐ `.slint` DSL + Rust business logic; live-preview LSP tooling is excellent but the DSL is an extra language in the repo | ● best widget velocity via the web ecosystem, but two stacks (TS + Rust) to maintain and bridge |
| Trading-domain precedent | ◐ hobbyist (netstrat, 67★); Rerun proves heavy-data viz at scale, not trading | ● Kraken Desktop — production thinkorswim-class crypto terminal (see evidence) | ○ none found | ○ many crypto dashboards, none of thinkorswim class found; Kraken explicitly contrasts "web-based architecture" as the thing they avoided |

(● strong ◐ workable ○ weak. ●/◐/○ grades are judgment calls over cited facts.)

## Evidence, per stack

### egui — immediate mode, MIT/Apache-2.0

- Repo/README: <https://github.com/emilk/egui> — goals include "Responsive: target 60 Hz in
  debug build"; FAQ: "For most cases you can expect egui to take up 1–2 ms per frame… egui only
  repaints when there is interaction… so if your app is idle, no CPU is wasted" (a live
  terminal drives continuous repaints — that's the documented cost model). README also names
  the flagship production app: Rerun Viewer; Rerun sponsors egui development.
- Scale of adoption: 30,898★ (2026-10-06), crates.io ~5,925,319 recent downloads; releases
  0.36.2 (2026-09-08), 0.35 (2026-06), 0.34 (2026-05) — <https://github.com/emilk/egui/releases>.
- Perf is an active workstream, not a frozen one — CHANGELOG
  (<https://github.com/emilk/egui/blob/main/CHANGELOG.md>): 0.31 added the `Scene` container
  (pannable, zoomable canvas — chart-like surface) and a tessellator rework ("fewer vertices…
  less overdraw"); parallel tessellation behind an opt-in `rayon` feature; recurring
  "Performance" sections (text-layout caching, `WidgetText` shrink, etc.).
- Tables: `egui_table` (Rerun's own crate) — "Auto-sized, resizable columns… Sticky columns and
  header… **Support for millions of rows**… Heterogenous row heights", actively maintained
  (pushed 2026-09-25) — <https://github.com/rerun-io/egui_table>. `egui_extras::TableBuilder`
  is the built-in lighter option. Rerun itself (11,549★, robot data streaming) is the
  production proof that egui holds up under heavy live data.
- Charts: `egui_plot` (official, extracted from egui 2024-07; ~1.14M recent downloads) —
  <https://github.com/emilk/egui_plot>. Known open gaps directly relevant to us: #18 "Optimize
  Plot", #22 (Ramer–Douglas–Peucker line simplification proposal — the classic tick-chart
  trick), #134 (f32 memory footprint), and #84 "Can a real-time display module for financial
  market K-lines be added to it?" — i.e. candlesticks are a custom `PlotItem`, not a built-in.
  The escape hatch is egui's 2D painting API (`epaint` painter, `Shape::Callback` for
  wgpu-native rendering) — README documents custom painting/3D callbacks as a core use.
- Trading-domain first-hand: `blitzarx1/netstrat` — "trading strategy construction,
  visualization and backtesting tool" built in egui (67★, dormant 2023), posted in egui's
  showcase thread (#996). Hobby scale — the honest read is "no egui trading terminal at Kraken
  scale found," balanced by Rerun's heavy-data production proof.
- Costs: non-native look (irrelevant for a custom-styled terminal — thinkorswim-class apps are
  skinned anyway); breaking changes every release (pin versions, read changelogs); very long
  scrollbacks are slow by design (README: lay out only what's in view).

### iced — Elm architecture, MIT/Apache-2.0

- **The decisive precedent:** Kraken's announcement "Meet Kraken Desktop: The powerful,
  customizable, lightweight trading app" (Oct 2024):
  <https://blog.kraken.com/product/kraken-desktop> — "While other desktop applications rely on
  web-based architecture, we developed this app from scratch using **Iced** — a low-latency,
  low-memory GUI library built on Rust." Feature list is exactly our target class: 800+
  markets, advanced order types, TA/drawing library, "up to 48 modules per board, including
  price charts, order books, depth charts, market summaries", multi-window support, ladder
  trading, Win/Mac/Linux. It is the evolution of Cryptowatch Desktop (iced's original sponsor;
  Cryptowatch was sunset into Kraken Pro/Desktop — <https://blog.kraken.com/product/cryptowatch-to-sunset-kraken-pro-to-integrate-cryptowatch-features>),
  and iced's own showcase lists Kraken Desktop: <https://iced.rs/>.
- Also production: System76's COSMIC desktop environment runs on an iced-derived toolkit
  (`pop-os/libcosmic`, 956★, pushed 2026-10-06) — plus Halloy, Sniffnet, etc. on the showcase.
- Maturity caveats, from iced's own artifacts: README says "**Iced is currently experimental
  software**" (<https://github.com/iced-rs/iced>); release cadence: 0.13.1 (2024-09-19) →
  0.14.0 (2025-12-07), one minor in ~15 months. Issue #7 "Perform benchmarks" open since 2019.
- Heavy-table / streaming pain, in the tracker: **#1720 "Freezes when trying to make a table
  with a large number of rows"** (open; workaround = draw only viewport rows yourself),
  #160 `InfiniteList` widget request, #2603 "Noticeable performance degradation for
  scrollables in 0.13" (open), #3173 "Canvas cache performance regression with large images in
  0.14" (open), #897 "for large texts, scrolling can be slow and may seg fault" (open),
  #34 "Advanced layout strategies" (open, since 2019). There is no official table widget
  (community `iced_table`/`iced_aw` grid — the #1720 thread itself is the iced_aw grid case).
- Scale of adoption: 31,682★; crates.io ~628,675 recent downloads (egui is ~9×).
- Architecture: Elm (state/messages/update/view) — clean and type-safe; for a tick firehose
  you aggregate ticks off-thread and deliver batched messages, then `view()` re-runs per
  update. Kraken's use shows this is viable at terminal scale; it is more boilerplate than
  egui's "render whatever the channel currently holds."

### Slint — declarative DSL, tri-licensed

- Repo/README: <https://github.com/slint-ui/slint> — declarative `.slint` markup compiled to
  native code; renderers femtovg (GL), Skia, or software; positioning is
  **embedded-first** ("for embedded systems, desktops, and mobile"), backed by SixtyFPS GmbH.
- API stability is its superpower: "Stable APIs: Slint follows a stable 1.x API. We evolve
  carefully without breaking your code" (README) — 1.18.1 released 2026-09-21; 24,088★.
- Licensing (sellable-binary criterion): choose royalty-free (proprietary desktop/mobile/web
  free), GPLv3, or commercial (embedded royalties $1/device) — README + FAQ
  (<https://slint.dev/pricing>). Desktop proprietary is fine; the tri-license is still more
  surface to audit than MIT/Apache.
- Tables: `StandardTableView` shipped in 1.7 (2024-07) and later gained ListView optimizations
  (`slint` CHANGELOG: "Improved StandardTableView to use ListView optimization for all
  styles", plus `row-pointer-event`, `current-row` APIs). Model/view + delegate is the right
  shape for live tables — but no trading-scale evidence exists.
- Charts: none. No charting story at all — everything would be custom `Path`/canvas drawing.
- Verdict for this project: wrong pedigree (embedded HMIs), an extra DSL in the repo, zero
  charting, zero trading precedent. Its genuine strengths (tiny footprint, stable API,
  designer tooling) don't buy us anything a trading terminal needs that egui/iced lack.

### Tauri — Rust backend + system webview (MIT/Apache-2.0)

- Repo: <https://github.com/tauri-apps/tauri> — renders via WRY over the **system webview**
  (WebView2 on Windows, WKWebView on macOS, WebKitGTK on Linux); 111,619★, ~13.5M recent
  downloads; v2 stable, v3.0.0-alpha.4 (2026-10-01) which notably adds a `tauri-runtime-cef`
  (Chromium Embedded Framework) option — upstream's own answer to system-webview
  inconsistency/perf (alpha-stage).
- Packaging is excellent: built-in bundlers for `.app/.dmg/.deb/.rpm/AppImage/.exe(NSIS)/.msi`,
  self-updater, tray, notifications (README) — the best "sellable installer" story of the four,
  with the caveat that the binary depends on the platform webview being present/healthy.
- The high-frequency cost is architectural, per Tauri's own docs
  (<https://v2.tauri.app/develop/calling-rust/>): commands serialize through JSON ("This can
  slow down your application if you try to return large data", hence raw `ipc::Response`
  buffers); the event system "is not type safe… only supports JSON payloads", and "For ordered,
  high-throughput data delivery, consider using Channels instead of the event system." A
  terminal pushing every tick through Rust→JSON→webview JS→DOM/canvas is exactly the
  anti-pattern Kraken called out ("other desktop applications rely on web-based architecture").
  Channels/raw buffers mitigate but the boundary remains.
- Webview fragmentation: three different engines render your app (plus CEF as a fourth option
  in v3); WebKitGTK is the historically weakest for heavy canvas work on Linux. Not quantified
  here — flagged as a structural risk, not a measured one.
- Charts inside the webview are the strongest option of any stack:
  **TradingView Lightweight Charts** (<https://github.com/tradingview/lightweight-charts>) —
  "one of the smallest and fastest financial HTML5 charts", canvas-based, v5 with a plugin
  system, Apache-2.0 **with an attribution obligation** (must credit TradingView in the
  product — see its NOTICE/LICENSE terms). Candlesticks, time/price scales, crosshair,
  primitives for custom panes: real thinkorswim-grade charting on day one.
- Verdict: fastest route to a *polished* UI and the best installer story, at the price of a
  two-language codebase, a per-tick serialization boundary, and engine fragmentation. For a
  sellable high-frequency terminal where the data engine is already Rust, that's the wrong
  default — but it's the right fallback if web-UI velocity ever dominates.

### Charting options, ranked

| Option | Fit | Evidence / citation |
|---|---|---|
| `egui_plot` + custom candle `PlotItem` | Good for standard plots; candles/indicators are ours to build; open perf FRs (#22/#18/#84/#134) show the seams | <https://github.com/emilk/egui_plot> |
| egui painter / `Shape::Callback` / raw wgpu surface | Best for ladders/depth/dense tick charts — draw 10³–10⁵ primitives per frame in one call; this is Rerun's pattern for heavy scenes | egui README ("custom painting", "Rendering 3D stuff"), Rerun production use |
| iced `Canvas` widget | Equivalent escape hatch; Kraken Desktop's charts live behind it | iced docs/showcase, Kraken blog |
| TradingView `lightweight-charts` in Tauri | Purpose-built financial charts, instant; but webview+IPC+attribution | <https://github.com/tradingview/lightweight-charts> |
| `plotters` crate | **Rejected for interactive use**: a drawing framework for static/bitmap/SVG/canvas figures (candlestick *elements* exist), rasterizes a full image per frame — no interaction, wrong tool for 60 fps streaming. 54M downloads = the chart *export/report* tool, not the terminal renderer | <https://github.com/plotters-rs/plotters> |

## Reasoning

1. **The app class decides the model.** A terminal is "big shared state, mutated by a firehose,
   rendered continuously." egui's immediate mode is the shortest path between that state and
   pixels: each frame reads the latest arena/ledger state — the same mental model as our
   append-only `fx_ledger.jsonl`/venue caches — with zero sync layer. iced's Elm model is
   workable (Kraken proves it at terminal scale) but every tick stream becomes a message
   protocol plus `view()` re-runs. Tauri adds a serialization boundary per tick by design;
   Slint adds a DSL for no compensating chart/trading benefit.
2. **Heavy tables are a solved, production-tested problem only on the egui side.** `egui_table`
   ("support for millions of rows", sticky header/columns, maintained by Rerun for exactly
   this) plus `egui_extras::TableBuilder`. iced's own tracker shows the gap: #1720 (large
   table freezes, open), #160 (`InfiniteList` request, open), #2603 (scrollable regression,
   open), and no official table widget. Watchlists/positions/order history is a core surface —
   this criterion weighs heavily.
3. **Upstream velocity compounds for a small team.** egui shipped ~9 releases in the 15 months
   in which iced shipped one minor; egui's changelog shows continuous performance and layout
   work (`Scene`, tessellator rework, rayon tessellation). Betting a sellable product's UI on
   iced means accepting "experimental software" (their words) at 2024–25 velocity, offset by
   the fact that its flagship user is a trading company that needed exactly our app class.
4. **Charts are the build-vs-buy axis.** Nothing in Rust-native land gives thinkorswim-grade
   candlestick/TA tooling out of the box (egui_plot #84 still open). Tauri+
   lightweight-charts is the only "buy the chart" option, and it's a good one — the trade is
   the IPC boundary and engine fragmentation. Kraken's blog is a direct, citable statement
   that a trading company chose *against* web-based architecture for exactly this product.
5. **Packaging/selling:** egui, iced, Slint all produce one static binary; egui/iced are
   plain MIT/Apache (zero license friction, no attribution), Slint adds a tri-license audit,
   Tauri is smallest-on-disk but webview-dependent. eframe binaries land around 5–15 MB —
   irrelevant size either way; what matters is *no runtime dependency roulette* for customers.

### Named runner-up: iced

Pick iced **if**: the Kraken Desktop precedent (production thinkorswim-class in exactly this
stack) outweighs egui's ecosystem/velocity edge, and/or you want a retained Elm architecture
for complex multi-window composition. Its specific risks to accept in writing: slow release
cadence, "experimental" self-description, open heavy-table/scrollable regressions (#1720,
#2603, #3173), community-only table widgets.

## Proposed lock + spike gate (cheap, before committing the codebase)

Recommendation for the human to lock: **egui primary, iced runner-up, Tauri fallback,
Slint out.** Before wiring V2 to it, a 1–2 day throwaway spike (sandbox-style, prototype skill)
should prove the two risky cells of the matrix, and only those:

1. **Tick-chart cell:** one candlestick chart fed 10⁴ bars + 100 mutations/sec via a channel,
   custom painter path (not `egui_plot`), target 60 fps on the 3070 and CPU-only — measure
   frame time, not vibes.
2. **Heavy-table cell:** `egui_table` with 10⁴ rows × 15 cols updating 100 cells at 10 Hz,
   scroll while updating.

If both pass → lock egui and record the ADR. If the tick-chart cell fails ugly, re-run it as
the same spike in iced `Canvas` (runner-up gets its day) before deciding anything. Numbers from
that spike, not this doc, become the quotable performance claims.

## Sources

Retrieved 2026-10-06. Download/star counts are point-in-time.

- egui README/releases/CHANGELOG: https://github.com/emilk/egui , /releases ,
  /blob/main/CHANGELOG.md
- egui_plot + issues #18/#22/#84/#134: https://github.com/emilk/egui_plot
- egui_table: https://github.com/rerun-io/egui_table · Rerun: https://github.com/rerun-io/rerun
- egui showcase thread (netstrat): https://github.com/emilk/egui/issues/996
- iced README/showcase/releases + issues #7/#34/#160/#897/#1720/#2603/#3173:
  https://github.com/iced-rs/iced , https://iced.rs/
- Kraken Desktop announcement: https://blog.kraken.com/product/kraken-desktop · Cryptowatch
  sunset: https://blog.kraken.com/product/cryptowatch-to-sunset-kraken-pro-to-integrate-cryptowatch-features
- libcosmic (COSMIC): https://github.com/pop-os/libcosmic
- Slint README/CHANGELOG/releases/pricing: https://github.com/slint-ui/slint ,
  https://slint.dev/pricing
- Tauri README/v3 alpha releases/IPC docs: https://github.com/tauri-apps/tauri ,
  https://v2.tauri.app/develop/calling-rust/
- TradingView Lightweight Charts: https://github.com/tradingview/lightweight-charts
- plotters: https://github.com/plotters-rs/plotters
- crates.io API (recent downloads): egui 5.93M · egui_plot 1.14M · iced 0.63M · slint 0.56M ·
  tauri 13.5M · plotters 54.1M

— ticket #330 · wayfinder:research · 2026-10-06
