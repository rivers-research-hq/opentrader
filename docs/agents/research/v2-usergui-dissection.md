# thinkorswim `usergui` client dissection — V2 UI design reference

**Ticket:** [#344](https://github.com/rivers-research-hq/opentrader/issues/344) (Opentrader V2 spec map #326; fetch authorized by human decision in #341)
**Date:** 2026-10-06 · **Sample:** `usergui` module version **1993.3.1**, fetched live from `update-thinkorswim-desktop1.schwab.com` (46 jars, ~41 MB of the 241 cross-platform jars; the OS-specific bulk — jxbrowser ~580 MB, VLC ~163 MB — was not fetched)
**Method:** clean-room study. Jars downloaded exactly as the real client downloads them (per the suit's `ModuleManager`/`URLManager` logic, decompiled in [#327](v2-tos-dissection.md)), then decompiled with Vineflower 1.11.1 (Maven Central) on OpenJDK 26.0.2 into `/tmp/tos-usergui/src`. This dossier names subsystems and public seams and quotes only small identifying fragments; no decompiled source is reproduced wholesale and none is reused in code.
**Companion artifact:** [`v2-usergui-eula.txt`](v2-usergui-eula.txt) — the license texts served with the download (open item in [v2-legal-licensing.md](v2-legal-licensing.md) § EULA capture).

---

## 1. Fetch mechanics — how the module actually arrives

The suit's `URLManager` resolves each server from `suit.properties` into **four** candidate base URLs per host, in priority order: `https://update-<host>:443`, `https://update-<host>`, then the plain host variants. The **`update-` prefix is what matters**: `thinkorswim-desktop1.schwab.com:443` itself is the *application/trading backend* and speaks the QTP binary protocol, not HTTP (verified accidentally — see §8). The download server is `update-thinkorswim-desktop{1,2,3}.schwab.com`.

URL grammar (reconstructed from `ModuleManager.getModulePath` / `getResourcePath` / `URLManager.getURL`, all one-line fragments):

```
GET https://update-thinkorswim-desktop1.schwab.com/usergui/index.xml?whitelabel=tos
    → 48 bytes: <index default="1993.3.1" download="" keep=""/>
GET .../usergui/usergui.jnlp?version-id=1993.3.1&whitelabel=tos
    → 47,471-byte JNLP manifest: 255 <jar> entries, each with size + truncated sha256
GET .../usergui/<jar-name>.jar?version-id=1993.3.1&whitelabel=tos
    → the resource (with &current-version-id=<old> appended when patching)
```

The client sends `User-Agent: JNLP/1.5 javaws/1.5.0 (b64) J2SE/1.5.0`, `Cache-Control: no-cache`, `accept-encoding: pack200-gzip,gzip` (from the suit's `HttpRequest`). Hostname verification pins the prod cert to `thinkorswim.schwab.com` / `thinkorswim-desktop1-b.tos-prd.prd.gcp.schwabcloud.com` (in `URLManager`'s `PROD_HOST_NAMES`).

**Module manifest facts (1993.3.1):**

- **255 jars, 877.4 MB total.** 241 cross-platform jars = only **132.1 MB**; the other ~745 MB is OS-specific natives: jxbrowser (5 platforms, ~580 MB — the embedded Chromium for Schwab web content), VLC (~163 MB, media), BookMap natives, mac file chooser.
- JNLP `<application-desc main-class="com.devexperts.tos.ui.user.DesktopStarter"/>` — the module entry point.
- Jars are built by `svc.tosteamcity` (Gradle 8.14.4, entry dates 2026-09-28) and signed **TOSPROD**.
- **Integrity-check anomaly:** every `sha256` attribute in the served JNLP is *truncated* (observed lengths 60–63 hex chars, not 64), and the digests do **not** prefix-match the served bytes even where sizes match exactly. The prior dossier's "content-addressed integrity" claim (from the shipped 1991.3.0 suit.jnlp, whose hashes also truncate) does not hold against live content at this granularity; treat the mechanism as size-verified + signature-verified, with the sha256 manifest at best an internal CI artifact. Worth imitating in V2: *don't* truncate your integrity digests.

**Fetch honesty note:** this study made 48 HTTPS GETs to `update-thinkorswim-desktop1.schwab.com` (index, jnlp, 46 jars — serial, ~1 s apart) plus **one accidental GET to `thinkorswim-desktop1.schwab.com:443`** (the trading backend; it answered with a 714-byte QTP protocol advertisement banner — `DXP3` magic, `qtp`, `rmi`, version `QDS-3.351` — and closed; no authentication was attempted, no further backend contact was made; details in §8). No login, no trading, no scraping loops.

## 2. Module map — versioning families and the UI jar set

Four version families coexist inside one module (from jar names/manifests):

| Family | Version | Meaning |
|---|---|---|
| `tos-common-*`, `tos-suit`, `tos-usergui*`, `tos-frontend-*`, `tos-connectivity`, `tos-endpoint-connector`… | **1993.3.1** | the TOS client/server domain + UI generation (matches the installer's suit family, two releases ahead) |
| `toscommon-*` (client-common) | **753.3.0** | shared client libraries (widgets, messaging records, instrument, margining) — the family the installer pre-seeds at 742.0.2 |
| `chartcommon`, `toschart`, `thinkscript`, `thinkscript-api`, `chartdescriber-*` | **213.2.0** | the chart/script engine family |
| `qds`, `dxfeed-api`, `dxlib`, `mars`, `dxfeed-ondemand` | **3.351** | the dxFeed/QD stack (suit shipped 3.349) |

**The UI jars that matter (all fetched):**

| Jar | Size / classes | Role |
|---|---|---|
| `tos-usergui-1993.3.1.jar` | 358 KB / 46 | **entry point**: `DesktopStarter` → `DesktopMain` → login → desktop; also carries NOTICE.txt/NOTICE2.txt (the only license files in the module) |
| `tos-usergui-base-1993.3.1.jar` | 17.3 MB / 7,556 | **the whole UI**: 3,827 files under `com.devexperts.tos.ui.*` — every screen, gadget, dialog, and the centrals data-agent layer |
| `tos-usergui-realbase-1993.3.1.jar` | 99 KB | base widget/gadget plumbing: `GadgetType`, `AbstractGadget`, detached-frame utils |
| `toschart-213.2.0.jar` | 8.5 MB / 2,558 | **the chart engine** (rendering + logic; see §3) |
| `chartcommon-213.2.0.jar` | 755 KB / 498 | chart **data** layer: aggregation, drawings model, patterns, QD services (§3) |
| `thinkscript-213.2.0.jar` + `-api-` | 1.3 MB / 683 + 311 KB | **the ThinkScript compiler + runtime** (§4) |
| `toscommon-client-753.3.0.jar` | 263 KB | shared Swing widget toolkit + `gui/centrals/LiveList` |
| `tos-frontend-api/impl/threads`, `tos-endpoint-connector`, `tos-connectivity` | 137 KB | connection/context plumbing (§6) |
| `toscommon-messaging-*` (qd-common, market-maker, heatmap, volumeperprice) | ~56 KB | QD extension records incl. the DOM/heatmap data (§5) |
| `ngapi-69.0.1.jar` | 112 KB | "next-gen API" RMI request/response DTOs (alerts, watchlists, corp events) |
| `orcs-api-3.4.9.jar` | 21 KB | **dxFeed ORCS price-level service** client (DOM depth; §5) |
| `loadbalancer-api/client-0.0.8.jar` | 70 KB | `com.tdameritrade.bootstrap.loadbalancer` — HTTP service discovery (§6) |
| `Bookmap-20260616.jar`, `bm-l1api`, `bm-dxfeed`, `BookmapRecorder` | 7.5 MB | embedded **Bookmap** (velox API) order-book heatmap (§5) |

The desktop is a **gadget composition system**. `GadgetType` enumerates the panel vocabulary (clean-room list): `LIVE_NEWS`, `CHART`/`CHART_2`/`CHART_3`, `LEVEL_II`, `DASHBOARD`, `ACTIVETRADER`, `TIME_SALES`, `BIG_BUTTONS`, `WATCHLIST`, `QUICK_QUOTE`, `LIVE_AUDIO`, `LIVE_VIDEO`, `SCRATCH_PAD`, `CALCULATOR`, `MINE_SWEEPER`, `TETRIS`, `LINES`, `MARKET_DEPTH`, `QUICK_CHART`, `CHART_DESCRIBER`, `COMPOSITE`, `ACTIVE_ACCOUNT`, `TRADE`, `MIDNIGHT_TRADER`, `PAIRS_TRADING`, `FX_CURRENCY_MAP`, `COMPANY_PROFILE`, `MESSAGE_CENTER`, `THINKSTUFF`, `PHASE_SCORES`, `OPTION_CHAIN`, `BOOK_MAP`. (Yes — Minesweeper and Tetris ship in the trading client.) `AbstractGadget` is the base: bound to a `ContextDescriptor`, LAFAware, config-layout persistable.

## 3. Charting engine architecture

The chart subsystem is a **three-layer split** — and this layering is the single most valuable design fact in this module:

1. **`chartcommon` — the data layer** (`com.devexperts.toschart.aggregate|common|net|util`, `tos.chartdata`): QD-side aggregation with *pluggable aggregation rules*. `aggregate/rule/` has `TimedAggregateRule`, `TickAggregateRuleWithRollover`, `RangeAggregateRule`, `RenkoAggregateRule`, `PriceAggregateRule` — every chart type's bar construction is a rule object over a record sink. `aggregate/aggregator/` holds `HLOCAggregator`, `HLOCPriceAggregator`, `HLOCRawAggregator`, `HLOCReplaceAggregator`, `CompositeRecordAggregation`; `aggregate/ticker/` builds live tickers (`PriceAggregateLiveTicker`, `TickAggregateLiveTicker`, `TimeAggregateLiveTicker`, `DayDataTicker*` for session-rollover). `chartdata/` defines `ChartAggregationPeriod` (time, tick, range, renko, day/week/month/quarter + `CompositeCandleSymbol` — candle identity is a *symbol*, so QD subscriptions address bars directly), `datetime/aggregate/TimeInterval` hierarchy (Intraday/Daily/Weekly/Monthly/Quarterly/Annual/OptionExpiration with holiday and session alignment). Drawings are a pure **model** here (`drawings/model/` — `TrendlineData`, `FibonacciRetracementsData`, `AndrewsPitchforkData`, `GannFansData`, `RegressionChannelData`… + `builder/` fluent builders + JSON serialization adapters), fully decoupled from rendering. `net/` defines `ChartRequest`/`ChartResponse`/`HistoryDataRequest`/`ProductDepthRequest` — chart-shaped requests over the transport. `generation/` exists for **synthetic data** (PinkNoise generators — the simulated-feed mode) and `likefolio`/`historicalnews`/`stockfundamentals` are additional data providers, all behind the same sinks.

2. **`toschart` — the engine** (`com.devexperts.toschart.*`, 2,558 classes): `core/Chart` + `ChartModel` + `ChartView` with a **mode system** (`ChartMode`, `RegularMode`, `MonkeyBarsMode` (market profile), `MpExpandedChartType`, `SeasonalitySubgraphController`) and chart-type renderers `ChartTypeCANDLE|BAR|LINE|AREA|EQUIVOLUME|HEIKIN_ASHI|CANDLE_TREND`. Axes are first-class models (`YAxisModel(+Impl/Proxy/Wrapper)`, `ManualYAxis`, `PercentYAxisModel`, `LogScaleYAxisSolver`, `LogAxisStepCalculator`, xaxis/yaxis packages). Painting is buffered (`BufferedPaintable`, `BufferTrigger`, `RepaintLayer`, `ChartLayeredPane`) — i.e. feed updates accumulate into a paint buffer that flushes on its own cadence rather than invalidating per tick. Studies are `Indicator`/`IIndicator`/`IPlot`/`Plot` with `SystemIndicator` vs `SymbolIndicator` vs `ThinkscriptBasedIndicator` — builtins and scripts are the *same* abstraction. **Orders/positions on charts** are engine citizens (`OrderLogic`, `OrderGroupLogic`, `OrderStorage`, `orderalerts/`, `positions/`). The hub is `central/QDMarketCentral`: it owns the QD subscription processor (`HistorySubscriptionProcessor`), the market-data processor, a `TimeMachineRepository` (per-symbol replayable time), a playback data source (`QDPlaybackDataSource` — the OnDemand time-travel feature), a client delay timer, and a **hard cap `VISIBLE_BARS_MAX_AMOUNT = 8000`**. Subscriptions flow `QDExternalSubscriber` → `HistorySubscriptionProcessor` → `MarketDataProcessor` → per-chart `SubscribableModel`s. `thinkscript/` (200 classes) is the script *integration* into charts: `ChartThinkScriptCalculator` (implements `ThinkScriptCalculator`), dataprovider/painter/model/runtime glue. Also present: `tvchart` (TradingView-style?), `simplechart`, `databox` (the on-chart data boxes), `zooming`, `control` (174 classes of controller logic), `fred/` (FRED macro overlays), `earnings/`, `corporateactions/` (split/dividend adjustment), `productcurve/` (§5), `monkeybars/`, `patterns/` (155 classes — the thinkorswim pattern-recognition studies: Classic/Fibonacci pattern query models + `PatternScanModel`).

3. **`techchart` (in `tos-usergui-base`) — the gadget glue**: `ChartGadget`, `ChartLayout`, `TosChartingBuilder`/`TosChartMixinsBuilder` (the gadget-side builder assembling engine + mixins: `BubblesMixin`, playback, describer client, color schemes), `TosChartActionItem*` (menu actions: studies/styles/drawings/alerts/orders), LAF color schemes, crosshair sync config (`AtAndChartCrosshairSyncConfig`), `PlaybackDataProviderImpl`, user-position/note services.

**Design takeaways for V2:** (a) candle identity as a symbol (subscription-addressable bars); (b) aggregation as rule objects over a record sink — new chart types are new rules, zero renderer changes; (c) drawings as a serialization-clean model separate from rendering; (d) buffered painting with an explicit flush trigger; (e) a single "indicator" abstraction for builtins and user scripts; (f) a visible-bar cap; (g) per-symbol time machines making backtesting/playback the same code path as live.

## 4. ThinkScript compiler surfaces

The compiler is **fully client-side** and ships in this module (`thinkscript-213.2.0.jar` + `thinkscript-api`):

- **Carrier format:** `ThinkScriptRequest` — an immutable `{symbol, requestAttributes, escapedFormula}` triple, with formula tags `'A'` (alert), `'C'` (custom column), `'P'` (predefined script), `';'` expression separator, and a default DAY aggregation. Scripts ride inside quotes/scanners/alerts/columns as strings.
- **Parse:** a hand-rolled action-record tokenizer/parser — `ExpressionParser` produces `ListActionRecord`s of `Action.BEFORE_FUNCTION_CALL` / `AFTER_FUNCTION_CALL` / `INVALID` etc. from token streams (`script/javacc.Token` — javacc lineage in the class names, though no grammar file ships).
- **Compile:** `script/ASMClassGenerator` + `ASMExpressionGenerator` (+ `asm/` wrapper layer: `ASMInvokeVirtual`, `ASMFieldAssignment`, `ASMCast`, `ASMTypedThis`…) **emit JVM bytecode directly** for the script. Entry: thinkscript-api's `ClassCompiler.generateScriptClass(ScriptDefinition, LanguageStrategy, ScriptCollection) → GenerationResult`. The class is defined through a custom loader (`BasePublicMorozovClassLoader.define(byteCodes, languageStrategy)`) and instantiated by `CompileUtils.newScriptInstance(generated, calculator, gui)` as a `ThinkScriptGeneratedCodeFunctions` — bound at birth to its host chart's `ThinkScriptCalculator` and the GUI hooks. This is why TOS studies run at native Java speed.
- **Runtime:** `ThinkScriptCalculator` (chart-side impl `ChartThinkScriptCalculator`) manages registered studies/strategies: `calculateAll()`, `invalidateAll()`, `reinitAll()`, incremental status; data enters through `thinkscript/data` sources (`FunctionDataSource`, `MIRecordSource` over QD `MIRecord`, `chartdata.MarketData`), the `runtime/` package (`DataRepository`, `TimeMachineUpdateListener`, `TimeZoneProvider`, corp-action adapters), and `TimingCache`. Past-offset references (`IPastOffsetLogic`, `ASMOffsetHelper`, `ASMPastOffsetHelper`) compile `close[1]`-style history access into field state.
- **Function library:** `functions/` (68 files) — `AverageFCFunctionExt`, `AccumDistFunction`, `CorrelationFunction`, `ExtremesFunction`, `FastKCustomFunction`, `DateFunctions`, `CorporateActionFunctions`, `DeclarePropertiesImpl`… plus `constants/` and `buildlimited/` (feature-gated builds).
- **Source-to-source migration:** `codeport/` — `AbstractFunctionFixer`s (`AddChartLabelFixer`, `CrossoverFixer`, `AvgTrueRangeFixer`, `AddCloudFixer`) with a `CodePortCache`/`CodePortConfig` — a compatibility rewriter that upgrades legacy script idioms at load time. (V2 equivalent: a semantic-versioned IR with fixer passes.)
- **Strategies:** a first-class subsystem (`strategies/` + api `ScriptStrategyApi`, `StrategiesCoreDataAccess`, `IEntryOrder`/`IExitOrder`, `StateRecord`, `StrategyConfiguration`) — order-aware backtests compiled and run by the same machinery, with the chart's order storage (§3) as the execution surface.
- **IDE:** `ui/user/thinkscriptide/` (detached tools panel, tabbed UI, welcome pane) + error surfaces (`exceptions/` — 42 files incl. `ScriptIsTooLongException`, `ListScriptingException`); scanner integration reuses the same compiler: `tos-common-watchlist` carries `TosFormulaParser`, `ThinkScriptSortProcessor`, `ThinkScriptFilterProcessor` — **the scanner's filter/sort language IS ThinkScript**, compiled to processor chains over QD subscriptions.

**Seam inventory for V2:** text → AST (action records) → dependency analysis (`script/Dependency`, `ActionRecordReverseGraph`, `FunctionUsageFinder`, `InlineSimplePriceReferencingFinder`) → typed codegen (bytecode here; a Rust/LLVM or interpreter target would substitute) → instance bound to data sources + calculator; past-offset state as fields; complexity guardrails (`ColumnComplexityCache`, `ScriptIsTooLongException`); versioned fixers for legacy syntax.

## 5. Trade ladder / DOM structure

Four distinct depth surfaces, all fed from the same QTP connection:

1. **ActiveTrader ladder** (`ui/user/acttrader/`, 102 files): `ActiveTraderModel` implements `EntityListListener<FullQuoteEntity>` + `FullQuoteListener`; the ladder is a **table of `PriceStat` price rows** plus `ActiveTraderQuotesSubModel` — two `TreeMap`s (`bidPrices` inverted, `askPrices`) bucketing per-price aggregate sizes into **5 gradient levels** (`GRADIENT_COLORS_COUNT = 5`) per side. Orders are placed by *row interaction*: `ActiveTraderDragDropRowListener`/`PriceMouseListener`/`OrderMouseListener` create tagged orders (`OrderTag.AT_LADDER` / `AT_LADDER_AS` when auto-send), `OrderPainter`/`DraggingPainter` draw working orders onto the ladder, `FlattenButton`/`CancelButton`/`BigButtonsGadget` do bulk actions, `NetPosition`/`psummary` (position summary) track the net, `ATBracketTable`/`ActiveTraderOCOStopSetup` handle brackets/OCO. Default instrument set is futures-first (`ActiveTraderMain(cd, acceptorProvider, true, new String[]{"/ES", "/NQ"})` in `Desktop.java`). Mouse-driven row → order mapping is the whole UX contract; nothing here needs a server round-trip to render.
2. **Level II montage** (`ui/user/regsheet/` + gadget `LEVEL_II`): `LevelIIMontageTable/Model/Panel`, `FullBookEntityListsManager`, `centrals/quotes/LevelIIQuoteInfo` (per-exchange bid/ask/size + exchange name + trend coloring — the classic Level II by-exchange stack over QD `Quote`/`MarketMaker` events).
3. **MARKET_DEPTH / product depth / heatmap** (`ui/user/productdepth/`, 59 files + `MARKET_DEPTH` gadget): options/futures **curves** (`OptionsChartLayout`, `FuturesChartLayout`, `ProductCurveSmoothLinePanel`, `productcurve/` in toschart — 39 classes) plus a **price heatmap** whose data arrives as the custom QD record `HeatMap` (TICKER contract, single obj field carrying a serialized `byte[]` blob) and a `VolumePerPrice` record (marshalled "VPP" field) — both defined in `toscommon-messaging-heatmap/-volumeperprice` via `qdext/records/*Factory` + codegen (`HeatMapFieldsGenerator`). DOM depth-as-blob over the record system, not per-level events.
4. **BOOK_MAP** (`ui/user/bookmap/` 65 files + the Bookmap jars): thinkorswim embeds **Bookmap** (Velox/`velox.api.layer0/layer1` — 892 classes in `bm-l1api`) as its order-book heatmap component, with `bm-dxfeed` bridging it to the QD feed (`BookMapPlatform` per-OS). A commercial component wrapped at the platform layer — the one part of the depth story TOS did not build itself.

**Price-level service:** `orcs-api-3.4.9.jar` — dxFeed **ORCS** (`PriceLevelService`, `PriceLevelCandle`/`PriceLevelCandleFactory`, `PriceLevelChecker`, `OrcsSamples`) — aggregated price-level candles as a QD-adjacent service, i.e. the vendor-side answer to depth-as-candles. Note for V2: DevExpInc already productized "depth as time-aggregated price-level candles"; that shape (rather than raw L2 streams) is the composable unit worth copying.

## 6. Feed-binding model — how the UI binds to dxFeed/QDS

**Bootstrap chain:** `DesktopStarter.main` (log4j2 config + `SystemPropertyFix`) → `DesktopMain.main` → `PrepareJXBrowserTask.start()` (embedded browser warm-up) → `login(cfg, startUpFrame)` → a `Connection` object → `DesktopMainInitializer.init(rootCD, cfg, startUpFrame, …)`. The `Connection` carries the root `ContextDescriptor` and the `Invoker` (RMI facade); the whole desktop then composes gadgets on that root context.

**The context system:** `ContextDescriptor extends PropertyContext` — a **hierarchical typed property bus**. Every agent and widget is constructed with a `ContextDescriptor`; properties (`CurrentAccountProperty`, `SymbolProperty`, watchlist keys…) flow down the tree, listeners subscribe per `PropertyKey`. This is the UI's entire dependency-injection + linkage mechanism (link a chart to a watchlist by sharing a child context). V2 equivalent: an entity-component context tree rather than global singletons.

**Data agents ("centrals"):** `ui/user/centrals/*` — per-domain agents (`FullQuoteEntityAgent` — abstract base wiring `FullQuoteAgent` (feed subscription), `BorrowAgent`, `EprAgent`, fundamentals, market-lookback, social-metrics agents; `SingleAccountAgent`/`AccountAgent`; order/position agents; `phasescores`, `chat`, `news` centrals) each translating a QD/RMI domain into **`EntityList`s** for the nodetable widget system (`com.devexperts.nodetable` — `ArrayEntityList`, `EntityColumn`, `FilteredEntityList`, `TosNodeTableModel`), i.e. **feed → agent → entity list → table model** with property-context linkage. (Caveat §8: the concrete `FullQuoteAgent`/`accounts`/`orders` centrals base classes live in one of the ~195 jars not fetched; the pattern is fully visible from the abstract layers, `LiveList`, and the suit.)

**Transport:** `tos-endpoint-connector`'s `QdRmiConnector` family wraps an **`RMIEndpoint`** (qds `rmi`) — `endpoint.connect(address)` opens the single QTP connection carrying both market data and trading RPC; `ConnectionChecker` validates liveness; `RecoveringQdRmiConnector` schedules reconnection. Address resolution comes from `com.tdameritrade.bootstrap.loadbalancer` (`HttpUrlBalancerClient`): the connector *discovers service nodes from an HTTP load balancer* — `AddressRequest.builder().login(…).service(…)` → node list (`"Discovery service '%s' from '%s'"`), with DNS/IP fallback connectors. So: **HTTP discovery → QTP/RMI endpoint → one pipe, two planes** (QD records + RMI tasks), exactly as the suit dissection inferred, now confirmed on the client side.

**Record families:** TOS domain records are QD extensions (`com.devexperts.tos.qdext.*`): `HeatMap`, `VolumePerPrice`, `MarketMakerRecord` (via `toscommon-record-gen`-style factories: `*RecordGenContext`/`*RecordFields`/`*RecordFactory` + per-record **codegen**), `OrderFillLegsField`, volatility objects, scanner WatchList/Histogram, plus the whole `toscommon-messaging-*` family (news, highlow, market, marketlookback, report, environmentstatus, etf, instrument-common, infrastructure-util…). `ngapi` adds versioned RMI request/response DTOs (alerts, watchlists, corp events) and `tos-invoker-api` provides `BeanDescriptorRegistry`-driven RMI service beans (Trading, UserManagement, WatchList, UnderlyingSnapshot descriptors). `tos-frontend-impl` supplies `Request`/`RequestEssence`/`MethodSpec`/`ParameterAppendStrategy` — the RPC marshalling discipline.

**Monitoring:** MARS (mars-3.351) is still wired (as in the suit), and `ui/user/selfmonitoring` + performance monitors (`SimplePerformanceMonitor.start()`, `PerformanceMonitor.startMonitor()` in `DesktopMain`) run in-client.

## 7. Implications for V2's Rust rebuild (design reference, not code)

1. **Same layer boundaries, different tech.** The module's proven seams map cleanly onto a Rust client: `chartcommon`-style data/subscription layer (aggregation rules over a record sink), `toschart`-style engine (buffered paint, mode system, indicator abstraction), `techchart`-style gadget glue, `centrals`-style domain agents → entity lists → widgets, `QdRmiConnector`-style single-transport endpoint with HTTP service discovery.
2. **Candle-as-symbol + rule-object aggregation** is the design worth porting verbatim (conceptually): bars become subscription-addressable, every chart type (incl. Renko/Range/Tick) is a rule, and history/live/playback share one subscription processor.
3. **Scripting: compile, don't interpret** — even a non-JVM V2 should compile studies to native/IR (cranelift, wasm, or a fast interpreter with typed fields), keep the *seams*: request-carrier strings, AST with dependency graph, past-offset state as fields, function library, versioned fixer passes, complexity guardrails. The scanner reusing the same language+compiler is a 10× leverage point TOS got for free.
4. **DOM as aggregated price-level candles** (ORCS shape, heatmap/VPP as compact record payloads) rather than raw L2 event floods — especially for our FX-first focus: the ladder UX (row → tagged order, 5-level size gradient, net-position summary) is independent of the depth transport.
5. **The property-context tree** (ContextDescriptor) is the cheapest high-value mechanism to copy: linkage (symbol/account propagation across gadgets) without a message bus per pair.
6. **Packaging:** module = one jnlp-style manifest with per-resource size+sha (don't truncate digests), staged version dirs, one signed entry jar carrying the license notices. 241 jars for 132 MB of cross-platform code is gradle-module sprawl — V2 should ship fewer, layered artifacts.
7. **What NOT to copy:** JVM bytecode codegen for user scripts (a security liability we don't need — V2's scripts are ours, not user-supplied), embedded Chromium+VLC+games in a trading client (745 MB of OS-specific bulk for features irrelevant to a lean rebuild), and the Bookmap-style third-party depth component (build the heatmap natively).

## 8. Limitations, anomalies, and open questions

- **Accidental backend contact (disclosed):** one GET to `https://thinkorswim-desktop1.schwab.com:443/usergui/index.xml?whitelabel=tos` (before the `update-` host was identified from `URLManager`) reached the **trading backend**, which responded with a 714-byte QTP handshake advertisement (`DXP3` magic, `type: qtp`, `QDS-3.351`, RMI subject/operation descriptors incl. `HISTORY_DATA`, `STREAM_DATA`, `RMI_ADVERTISE_SERVICES`) and closed the connection. No auth attempt, no further backend traffic. This confirms the split: plain host = trading/data plane; `update-` host = download plane.
- **`FullQuoteAgent` & centrals base classes:** not present in any of the 46 fetched jars (the abstract `FullQuoteEntityAgent` references them); they live in one of the ~195 unfetched cross-platform jars. The architecture is fully determined by the fetched layers; the concrete subscription class was not needed for the design questions and was not hunted further (fetch restraint).
- **sha256 truncation/mismatch** (§1) — unresolved; flagged as a defect in their manifest discipline worth noting but not imitating.
- **EULA:** the module download serves only NOTICE.txt/NOTICE2.txt (captured in `v2-usergui-eula.txt`); the actual Schwab EULA acceptance happens behind authenticated web login — still open for the legal dossier.
- **Not fetched (by design):** OS-specific natives (jxbrowser, VLC, BookMap natives, mac bundles), remaining third-party jars, and the 1991-series suit copy inside the module; decompilation covers 46 jars ≈ 18.6k classes (12.5k decompiled source files).
- All findings above are from static decompilation; nothing was executed, no account was used, no trading-backend session was opened.

## 9. Provenance & tooling

- Fetch: 2026-10-06, 49 HTTPS GETs total (48 to `update-thinkorswim-desktop1.schwab.com` — index + jnlp + 46 jars — and 1 accidental to the app backend, disclosed above), serial, ~1 s spacing, client User-Agent, no auth.
- Decompile: Vineflower 1.11.1 (Maven Central) on OpenJDK 26.0.2 → `/tmp/tos-usergui/src` (46 jar trees, ~75 MB of .java).
- Analysis corpus (the 46 fetched jars): `tos-usergui(-base/-chat/-games/-monitor/-realbase)`, `toschart`, `chartcommon`, `chartdescriber-api/-server-api`, `thinkscript(-api)`, `tos-common-chart`, `toscommon-client/-core/-messaging-qd-common/-messaging-heatmap/-messaging-volumeperprice/-messaging-market-maker`, `tos-frontend-api/-impl/-threads`, `tos-endpoint-connector`, `tos-connectivity`, `tos-invoker-api`, `tos-common-base/-desktop/-user/-user-impl/-user-integration/-watchlist/-order/-price/-snapshot/-fundamentals/-public-api-instrument/-describer-server-api`, `tos-userini`, `ngapi`, `orcs-api`, `loadbalancer-api/-client`, `Bookmap`, `bm-l1api`, `bm-dxfeed`, `mac-resources`.
- Clean-room: study only; no code reuse. All quotes are one-to-three-line identifying fragments for evidence, not reproduced implementations.
