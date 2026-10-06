# thinkorswim (Schwab desktop) installer & client dissection — V2 packaging reference

**Ticket:** [#327](https://github.com/rivers-research-hq/opentrader/issues/327) (Opentrader V2 spec map #326)
**Date:** 2026-10-06 · **Sample:** `thinkorswim_installer.sh` (30,228,323 bytes, app version **1991.3.0**, client-common build **742.0.2** of 2026-02-17)
**Method:** clean-room study. Payload carved from the installer (offsets re-verified), all 60 suit jars decompiled with Vineflower 1.11.1 (Maven Central) into `/tmp/tos-recon2/src`. This dossier names subsystems and public seams and quotes only small identifying fragments; no decompiled source is reproduced wholesale and none is reused in code.
**Scope note / honest boundary:** the installer ships a **bootstrap, not the trading client**. The heavy UI (charting engine, ThinkScript compiler, trade ladder) is the `usergui` module, downloaded at first run from `thinkorswim-desktop{1,2,3}.schwab.com:443` and *not present in this sample*. Everything below about those subsystems is inferred from the seams the shipped jars expose. No connections to Schwab servers were made.

---

## 1. Installer anatomy (install4j SFX)

The file is a standard **install4j** self-extracting installer, three segments:

| Segment | Bytes | Content |
|---|---|---|
| POSIX shell preamble | 0 – 19,530 | install4j-generated launcher: JVM discovery, SFX extraction, `java install4j.Installer443923295` |
| STORED zip | 19,531 – 27,295,031 | the app payload (84 entries, 27,256,787 uncompressed) — "app.zip" |
| gzip tar | last 2,933,291 bytes | install4j runtime: `i4jparams.conf`, `i4jruntime.jar`, `launcher0.jar`, `launcher2bfa42ba.jar`, `launcher8ee4fbfc.jar`, `user.jar` (install4j wizard scripts), `MessagesDefault`, `libi4jinst.dylib`/`libi4jinst2.dylib`, i18n `i4j_extf_*`, `stats.properties`, `user/` (FlatLaf jar + tosbanner PNGs) |

Re-verified carve: EOCD magic at byte 27,295,010, zero-length zip comment → zip ends at 27,295,032 (−1 = matches the payload zip's declared length); trailing segment is gzip (magic `1f 8b`), untars to the runtime above. The preamble embeds both boundaries: `tail -c 2933291 "$prg_dir/${progname}" > sfx_archive.tar.gz` and `-Dexe4j.totalDataLength=30208815`.

### 1.1 JVM discovery (order matters)

From the preamble (`test_jvm()` / `read_db_entry()` / `create_db_entry()` and the main flow):

1. `INSTALL4J_JAVA_HOME_OVERRIDE` env var (user escape hatch)
2. `$app_home/.install4j/pref_jre.cfg` (recorded preferred JRE — updated later by the `jreupdater` module, see `PrefJreCfgUpdater`)
3. bundled JRE (`$app_home/jre`, macOS `.install4j/jre.bundle`)
4. `java` on PATH, **resolving symlinks** (`while [ -h "$prg_jvm" ]` loop)
5. `$JAVA_HOME`
6. a glob over `common_jvm_locations` (`/usr/lib/jvm/*`, `/usr/java*`, `/opt/java*`, macOS framework paths, …)

Each candidate is probed by running `java -version` (with an install4j **JRE database cache** keyed by `JRE_VERSION`/`JRE_INFO` rows and the java executable's mtime) and by an architecture + headless check that looks for `lib/libsplashscreen.so` under the candidate (`is_headless_only()`). Minimum version is enforced by `test_jvm`. The chosen home is exported as `app_java_home`.

### 1.2 Self-extraction

The preamble requires `gunzip`, makes a temp dir (`${progname}.$$.dir`, or `$INSTALL4J_TEMP/…`, with a `/tmp` fallback), `tail -c`s the trailing bytes into `sfx_archive.tar.gz`, gunzips, `tar xf`s (with `TAR_OPTIONS=--no-same-owner`), then launches:

```
"$app_java_home/bin/java" -Dexe4j.moduleName=… -Dexe4j.totalDataLength=… \
  …vmoptions… -classpath "i4jruntime.jar:launcher0.jar" install4j.Installer443923295 "$@"
```

The installer temp dir is trap-cleaned on HUP/INT/QUIT/TERM; `INSTALL4J_KEEP_TEMP=yes` and the hidden `__i4j_extract_and_exit` argument preserve it (useful for carve-style inspection — that is effectively what our carve reproduces).

### 1.3 What the installer installs (i4jparams.conf)

`i4jparams.conf` is a `java.beans.XMLDecoder`-serialized install4j config (built with Java 17.0.3 toolchain): wizard screens, actions — `RequireInstallerPrivilegesAction`, desktop/start-menu link creation, `RunExecutableAction("thinkorswim")` on the Finish screen, an elevated-launcher replacement script (`I4jScript_Internal_106` "Choose if elevated launcher is needed"), and a full uninstaller application. Notable details:

- The GUI launcher's `.desktop` StartupWMClass is `install4j-com-devexperts-jnlp-Launcher` — i.e. the installed `thinkorswim` script ultimately runs `com.devexperts.jnlp.Launcher`.
- `fileOptions` gives every payload entry `overwrite="4"` (install if newer) and `uninstallMode="0"` — silent-update friendly.
- `uninstallDelete` removes runtime-created `client.out` and `jre/bin/server/classes.jsa`.

### 1.4 The installed tree (payload zip contents)

```
thinkorswim               ← install4j-generated launcher script (14,680 B)
thinkorswim.vmoptions     ← -Xmx1536m -Xms32m -Dawt.useSystemAAFontSettings=false
                             -Djava.util.Arrays.useLegacyMergeSort=true
                             -Dapplication.oauth.enabled=true -Djdk.util.jar.version=10
                             -DTimeDef.timeZone=America/New_York
zacinst.ini               ← application.server_url=thinkorswim-desktop1.schwab.com:443,
                             …desktop2…desktop3…; application.login.suffix=schwab
suit.properties           ← suit.server=thinkorswim-desktop1/2.schwab.com:443
                             module=usergui, whitelabel=tos
suit/index.xml             ← <index default="1991.3.0" download="" keep=""/>
suit/1991.3.0/            ← 60 jars + suit.jnlp + launcher.jar (§2)
jreupdater/index.xml      ← <index default="1991.2.4" download="" keep=""/>
.install4j/               ← icons
uninstall, license_*.html
```

**Key fact:** the only *code* installed is the update/login bootstrap ("suit") plus shared model libraries. `module=usergui` in `suit.properties` names the real client that gets downloaded on first run.

---

## 2. Jar-by-jar inventory (`suit/1991.3.0/`, 60 jars)

Two versioning families coexist: the **suit-side family** `tos-common-* / tos-suit / tos-margining-api / …-1991.3.0` and the **client-common family** `toscommon-*-742.0.2` (`Implementation-Version: Build 742.0.2 (20260217-204527)` in each manifest). The former ships with the suit; the latter is the shared library set the downloaded `usergui` client is compiled against — i.e. the installer pre-seeds the client's non-UI dependencies.

### 2.1 Bootstrap & update chain

| Jar | Size | Role (evidence) |
|---|---|---|
| `launcher.jar` | 24,612 | `Main-Class: com.devexperts.jnlp.Launcher` (`META-INF/MANIFEST.MF`, Implementation-Title `tos-launcher`). 9 classes: `Launcher` (loads suit via `SuitLoader`, reflectively invokes the suit's main class), `SuitLoader` (reads `suit/index.xml` → falls back to `index.xml.bak` → newest version dir via `VersionComparator`; builds a `URLClassLoader` from the jnlp jar list), `Xml`, `InstallerCallback`, error handlers |
| `tos-suit-1991.3.0.jar` | 10,630,237 | The DevExpInc "suit" bootstrap + updater + login UI (§3). Signed `TOSPROD` |
| `tos-updater-base-1991.3.0.jar` | 18,159 | Updater primitives: `UIModule` enum (**modules: `suit`, `usergui`, `admingui`, `installer`, `jreupdater`**), `OldVersionJarFinder`, path-matching rules |
| `toscommon-localization-742.0.2.jar` | 8,294 | `LocalizerHook`, `SingletonLanguageController` |
| `toscommon-security-742.0.2.jar` | 22,980 | deserialization hardening: `ObjectInputFilterWrapper`, `DeserializationSecurityChecker`, `SanitizeUtil` |

### 2.2 DxFeed / DevExpInc market-data stack (all 3.349)

| Jar | Size | Role (evidence) |
|---|---|---|
| `qds-3.349.jar` | 1,663,884 | **QD core** — the QD data distribution framework: `com.devexperts.qd` (DataRecord/DataScheme/DataBuffer/subscription model), `impl/matrix` (symbol×record matrix storage), `kit` (`PentaCodec` symbol codec, standard schemes), `qtp` (**QTP wire protocol**: `BinaryQTPParser/Composer`, `MessageConnector`, socket transports, `auth/` QTP auth), `ng` (next-gen subscription model), `com.devexperts.rmi` (**RMI-over-QTP task/service framework** — this is how trading/order RPC rides the same connection), `connector/proto` |
| `dxfeed-api-3.349.jar` | 398,649 | **dxFeed public API**: `com.dxfeed.api.DXEndpoint` (states, `connect()`, `DXFeed`/`DXPublisher` seams), `com.dxfeed.event.market` (Quote, Trade, Order, TimeAndSale, Profile, MarketMaker, AnalyticOrder, SpreadOrder, TradingStatus…), `event/candle`, `event/option` (Greeks, TheoPrice, Underlying), `schedule` (day sessions), `ipf` (instrument profile files), `model` (MarketMakerModel etc.), `promise` |
| `dxlib-3.349.jar` | 328,039 | DevExpInc core primitives: `com.devexperts.util` (IndexedSet/IndexedMap, DayUtil, LockFreePool…), `io` (ChunkedInput/Output, CompactSerializer, Compression), `logging`, `services` (SPI), `management`, `monitoring` |
| `mars-3.349.jar` | 92,023 | **MARS monitoring**: `com.devexperts.mars` (MARSAgent/MARSEvent/MARSNode monitoring tree), `mars/jvm` (`JVMSelfMonitoring`, `CpuCounter`, `ThreadDumper`), `connector` (socket monitoring feeds). Client telemetry/JVM self-monitoring |

### 2.3 TOS domain model — instrument, margining, trading, scanner

| Jar | Size | Role (evidence) |
|---|---|---|
| `toscommon-instrument-742.0.2.jar` | 81,217 | Symbology/math shared by client+server: `SymbolUtil`, `OptionSymbolUtil`, `FutureSymbolUtil`, `ForexSymbolUtil`, `Currencies`, `TickSizes`, `Futures`, option math (`GreekSet`, `StockParameters`, `PricingParameters`), `FredInstrument` (macro data), `ThinkScriptEnum` (chartdata) |
| `tos-common-instrument-1991.3.0.jar` | 795,098 | **The instrument model**: `com.devexperts.tos.data.Instrument` / `InstrumentInterface` / `OptionInstrument` / `OptionPair` / `OptionSeries`, margin-reference profiles in `data/mrp` (`MarginProfile`, `FuturesMarginProfile`, `REGTSpecialRule`, `TDAPMSpecialRule`), `rbm/` (RBMParameters, `RBMFIXMLParser` — risk-basis-margin parameter sets parsed from FIXML/plain), `symbology/`, fundamentals, borrow, ETF, forex financing, GICS, multicurrency, earnings, `chartdata/` |
| `tos-common-instrument-config-1991.3.0.jar` | 15,645 | instrument-side config transfer objects |
| `tos-common-instrument-to-1991.3.0.jar` | 16,180 | transfer-object wrappers: `InstrumentWithType`, `InstrumentWithPrice`, `NgOmsClosingPriceSnapshot` (next-gen OMS closing price snapshot) |
| `toscommon-instrument-schedule-742.0.2.jar` | 21,569 | `ScheduleProvider` (static + dynamic), `ScheduleResolver` — trading-session schedules |
| `tos-margining-api-1991.3.0.jar` | 51,584 | margining API (20 classes) |
| `toscommon-margining-742.0.2.jar` | 135,153 | margin math: `math/markprice`, `math/optionseries`, `qdext/volatility`, `qdext/symbols`, `snapshot` — mark-price & volatility models over QD extensions |
| `toscommon-trading-feature-742.0.2.jar` | 45,189 | **Order model**: `data/orderfill/OrderFill`, `OrderFillLeg`, `OrderType`, `OffsetMode`, `data/orderreject/OrderReject`, `TradeLimitType`, `qdext/OrderFillLegsField` — fills/rejects arrive as QD records |
| `toscommon-scanner-feature-742.0.2.jar` | 125,219 | **Scanner engine**: `qdext/scanner/formula/` — `FormulaParser`, `Expression`, `ShowStocksProcessor`/`ShowOptionsProcessor`/`Sort`/`Limit`/`Filter`/`Namespace` processors, `WatchList`, `Histogram`; plus `data/fundamental/` (info/history fields) and `thinkscript/FundamentalType`, `FredSubscriptionSymbol` — the scanner's show-as/filter-by query language compiles to processor chains over QD subscriptions |
| `toscommon-etf-feature-742.0.2.jar` | 18,773 | `EtfHolding` model + codec |

### 2.4 Platform services, user, chat, messaging, config

| Jar | Size | Role (evidence) |
|---|---|---|
| `tos-common-platform-1991.3.0.jar` | 19,657 | `ServerInfoService`, `TosInstance`/`TosInstanceMode`, bookmap registration encoder |
| `tos-common-platform-api-1991.3.0.jar` | 13,248 | `Platform`, `OrderManagementSystem`, `InstrumentDataProvider` enums; annotations `UsedByTOSSGW` / `UsedByTOSMGW` (server-gateway vs middle-gateway consumers of the same transfer objects) |
| `tos-common-user-api-1991.3.0.jar` | 35,672 | `IUserRecord`, `IndividualRecord`, `MaskablePhone`/`MaskableEmail` (PII masking), domain segments |
| `tos-common-user-TO / -session-TO-1991.3.0.jar` | 11,008 / 11,462 | user/session transfer objects, `UserKey`, roles |
| `tos-common-chat-api / -TO-1991.3.0.jar` | 52,846 / 15,353 | **Chat subsystem**: `data/chat/ChatChannel`, `ChatUser`, `ChatHistory`, `ChatStatisticsVolumeVelocity`; `chat/SimpleChatService`, `RssNewsfeedFormatter` (news RSS), permissions |
| `tos-common-messaging(-to)-1991.3.0.jar` | 20,039 / 8,183 | **Message bus over QD**: `tos/qd/QDCollectors`, `QDCollectorResolver`, `messages/MessageTopics`, `CacheMessage` listeners |
| `toscommon-rmi-messaging-742.0.2.jar` | 8,578 | `ServiceType`/`RMIServiceType` — registry of trading RMI service names over the QTP connection |
| `tos-common-routing-1991.3.0.jar` | 11,472 | `Routing` enum (smart order routing destinations) |
| `tos-common-config-1991.3.0.jar` | 146,252 | client config model: availability, feature flags, params, `quarantine/`, support-department data |
| `tos-common-time-1991.3.0.jar` | 64,664 | `RecurrenceRule` scheduling, `timepattern/`, `TosTimeUtil` |
| `toscommon-timing-742.0.2.jar` | 14,363 | `TradingTime`, `TimeDef`, `TimeProvider`, `CalendarCST` |
| `tos-common-util-1991.3.0.jar` | 86,104 | misc utils (`ZipUtil`, `Clock`, formatters, `CommonVolatilityFormatters`) |
| `toscommon-misc-util-742.0.2.jar` | 180,698 | larger misc-util family build |
| `toscommon-serialization-util-742.0.2.jar` | 29,650 | `util/codecs/` — parameter serialization codecs (strings ↔ typed configs) |
| `toscommon-collections / -enumerable-742.0.2.jar` | 28,722 / 18,773 | `IntMap`/`IntSet` primitives; `EnumerableSet64` (bit-packed indexed sets used throughout QD subscriptions) |
| `toscommon-client-742.0.2.jar` | 263,497 | **Shared Swing widget toolkit**: `gui/widgets/` — DropDownList, DateSelectorPanel, `updown/` spinner controls, colorpicker, table, `scrollable/floatingheader`, `adaptive` — the component library the downloaded client builds its screens (incl. the ladder) from |
| `tos-seahorselaf-base-1991.3.0.jar` | 455,367 | **LAF**: `com.devexperts.tos.ui.seahorselaf` — the "Seahorse" look-and-feel: Schwab color schemes (dark/bright palettes, `scheme/color/scheme/schwab/`), control sizes, fonts |
| `tos-services-auth-TO / tos-common-shared-TO / tos-transfer-object-architectural-testing-1991.3.0.jar` | 10,088 / 10,731 / 6,808 | auth + shared transfer objects; the last is a test/marker artifact |
| `svg-salamander-1.1.2.2.jar` | 314,326 | SVG rendering (Schwab logos are SVGs in tos-suit `resources/graphics/svg/`) |

### 2.5 Third-party (packaging hygiene reference)

`guava-32.1.3-jre`, `gson-2.13.2`, `httpclient-4.5.14`/`httpcore-4.4.16` (update downloads), `commons-io-2.15.1`, `commons-lang3-3.18.0`, `commons-codec-1.11`, `commons-logging-1.2`, `jna-5.7.0`/`jna-platform-5.7.0` (native platform calls), plus annotation-only jars (`checker-qual`, `error_prone_annotations`, `jsr305`, `jcip-annotations`, `annotations-19.0.0`, `VeracodeAnnotations-1.2.1`), `failureaccess-1.0.1`, `listenablefuture-9999.0-empty-to-avoid-conflict-with-guava`, `concurrentlinkedhashmap-lru-1.4.2`, `jakarta.annotation-api-3.0.0`, `javax.annotation-api-1.3.2`.

---

## 3. `tos-suit` — the bootstrap/update/login subsystem

`tos-suit-1991.3.0.jar` (333 classes + resources) is the heart of the installer payload. Packages:

- **`com.devexperts.jnlp.updater`** — the module manager: `ModuleManager` (orchestrates per-module downloads: fetch `<module>/index.xml` → `<module>/<module>.jnlp?version-id=<v>` → resources, with messages `"Downloading jar diff patch for '%1$s' from version '%2$s' to version '%3$s'"`, `"Downloading bin diff patch…"`, `"Downloading full resource…"`), `JNLPDescriptor` (parses the per-module jnlp, handles gzip, enforces uniform resource versions), `JarDiffPatcher` (JNLP-style jardiffs) + `JarDiffPatcherOld`, **`BinDiffPatcher`** with `bindiff/JBPatch` (binary file patching), `ApplicationVersionManager` (staged `index.xml.ready` + keep-list), `ResourceFileManager`/`TosResourceManager`, `BackupFileProvider`, `HttpRequest`/`HttpResponse`, `LauncherUpdater`/`LauncherReplacer` (self-updates the launch script/jar; resources `startScriptChangeFrom`/`startScriptChangeTo` are literal script patch hunks), `DLLClassLoader`.
- **`com.devexperts.jnlp`** — `UpdateManager` (main class of the suit jnlp: updates SUIT, then chains to the `usergui` module — `if (extModuleName == UIModule.SUIT) extModuleName = UIModule.USERGUI;` — and finally `moduleManager.launchModule(args)`), `LauncherFrame` (splash/progress), `LoggedLauncher`, `JavaVersionCheck`, `CurrentModuleUtils`.
- **`com.devexperts.jnlp.utils`** — `URLManager` (server failover: parses `application.server_url`, shuffles unless `suit.serverShuffleDisabled`, rotates `onError`, records the successful server back into `suit.properties` via `PropertySettingsManager`), `ResponseLogger`, XML/IO utils.
- **`com.devexperts.jnlp.settings`** — `VmOptionsManager` (regex-managed `vmoptions` edits: `-Xmx`, `-Xms`, classpath, `-D` properties, `--add-opens` from a bundled `resources/add_opens.txt`), `PropertySettingsManager`, `InfoPlistManager` (macOS), `SettingsManager`.
- **`com.devexperts.jnlp.platform`** — `Platform` abstraction with per-OS impls (`linux/LinuxPlatform`, `mac/MacPlatform`, `windows/WindowsPlatform` incl. registry + `SHChangeNotifyEvents` shell refresh, `unknown/UnknownPlatform`), hardware probes (`CPUInfo`, `GPUInfo`, `RAMInfo`, `NetworkInfo`), `PrefJreCfgUpdater` (writes `.install4j/pref_jre.cfg`).
- **`com.devexperts.suit`** — `SuitStartupManager` (domain/login-style handling: `DomainType` with Schwab suffix, login banner fetched from `https://toslc.thinkorswim.com/api/loginBanner` via an inner `MagnoliaConnection` record), `SignatureVerifier` (jar signature checks), `TosInstanceAddressManager`, `rollback/InstallationRollback` + `SuitCleanup`, and the Schwab-branded update UI (`ui/schwab/UpdateFrame`, `UpdateProgressPanel`, `ui/controls/SchwabSuitButton` etc., colors from `ui/scheme/SchwabUIScheme`).
- **`com.devexperts.jnlp.activeinstance` / `autologin` / `sharedconfig` / `installer`** — single-instance guard (`ActiveInstance`), auto-login support, and the `InstallerCallbackInSuit` seam the install4j wizard calls (`com.install4j.script.I4jScript_Internal_116` = "Call InstallerCallback.onInstall").
- **Resources** — Schwab/TOS SVG logos and fonts, `resources/add_opens.txt`, Windows browser plugins (`resources/browser/plugins/.../npthinkorswim.dll`, `nptossc.dll`), RTD service DLLs (`resources/rtd32|rtd64/RTDService.dll` — the Excel RTD feed), macOS app icon set, and a `deploy/index.xml` template (`default="@version@"`) used when generating new module pointers.

---

## 4. Launch & auto-update chain (what V2 would replicate)

Full cold-start sequence, with evidence at each hop:

1. **OS launcher.** install4j-generated `thinkorswim` script: JVM discovery (§1.1) → reads `thinkorswim.vmoptions` (`read_vmoptions()`) → runs `launcher.jar`.
2. **Suit load.** `com.devexperts.jnlp.Launcher.main` → `SuitLoader.loadSuit()`: resolve version from `suit/index.xml` → parse `suit/1991.3.0/suit.jnlp` → `URLClassLoader` over its jar list → reflectively invoke its main class.
3. **Update + chain.** `suit.jnlp` `application-desc main-class="com.devexperts.jnlp.UpdateManager"`. `UpdateManager.main()` maps the current module, defaults the extension module to **USERGUI**, ensures the suit itself is current (`LauncherUpdater.update()` can replace the launcher script/jar and restart), then `ModuleManager` downloads/patches the `usergui` module.
4. **Client handoff.** `ModuleManager.launchModule(args)`: reads the module's jnlp for its start class + args, sets `<property>`s from the jnlp onto `System`, sets the context classloader to the module loader, and invokes the client's main class. From here the downloaded platform takes over.

### Update mechanics worth copying

- **Versioned module dirs + index pointers.** `<module>/index.xml` holds one `default` version (+ `keep` list). A new version downloads into `module/<version>/` completely before the pointer flips (staged `index.xml.ready` → rename). Rollback = keep the old version dir (`InstallationRollback`, `SuitCleanup` prune).
- **Content-addressed integrity.** every resource in a module jnlp carries `size` + `sha256` (see `suit/1991.3.0/suit.jnlp`); `JNLPDescriptor` + `ResourceChecksumProvider` verify before anything replaces a live file.
- **Delta updates.** Jar-level diffs (`JarDiffPatcher`) and byte-level diffs (`BinDiffPatcher`/`JBPatch`); full resource download only as last resort.
- **Server failover.** `URLManager` over the three `thinkorswim-desktop*.schwab.com:443` hosts; shuffled, rotated on error, winner persisted to `suit.properties` (`suit.server`) so the next start hits the known-good host first.
- **Three-layer self-update.** (a) launcher script patched in place (`startScriptChangeFrom/To`), (b) suit jars via module diffing, (c) JRE via the separate `jreupdater` module (`jreupdater/index.xml` default `1991.2.4`, `PrefJreCfgUpdater` updates `pref_jre.cfg`).
- **Signature + permission discipline.** suit jars signed `TOSPROD`; `SignatureVerifier`; `SanitizeUtil.ensureSafeFilePath` guards against path traversal in version strings (`ModuleManager.getVersionDir`).

---

## 5. The dxFeed/QDS data-flow model (as far as the shipped jars show)

```
dxfeed-api (DXEndpoint/DXFeed/DXPublisher — event-typed public API)
        │  builds on
qds (QD core: DataScheme/DataRecord, Agent/Distributor subscription model,
     impl/matrix storage, kit codecs incl. PentaCodec)
        │  wire format
qds qtp (BinaryQTPParser/Composer, socket MessageConnectors, qtp/auth)
        │  same connection carries
qds rmi (task/service RPC — trading operations)
        │  feed-side TOS extensions
toscommon-*/tos-common-* "qdext" (custom TOS DataRecords/fields:
     ThinkorswimCodecHolder → PentaCodec, OrderFillLegsField,
     VolatilityObjField, scanner WatchList/Histogram records)
        │  auxiliary transports
mars (MARS monitoring tree over its own connector)
dxlib (IndexedSet/ChunkedIO/logging/service-SPI foundations for all of the above)
```

Observations relevant to V2:

- **One protocol, two planes.** Market data (QD subscription/records) and trading operations (RMI tasks over QTP) share the same `MessageConnector` plumbing (`qds/com/devexperts/qd/qtp` + `com/devexperts/rmi`). The TOS-specific records live in `com.devexperts.tos.qdext` packages across the feature jars — a clean "standard feed + domain extension records" split.
- **Transfer-object discipline.** A dedicated `*-TO` jar family (user-TO, session-TO, chat-TO, instrument-to, messaging-to, shared-TO, services-auth-TO) with a `tos-transfer-object-architectural-testing` jar enforcing it — plus `UsedByTOSSGW`/`UsedByTOSMGW` annotations distinguishing server-gateway vs middle-gateway consumers. Worth imitating for V2's state/DTO layers.
- **Scanner = compiled query language.** `FormulaParser`/`Expression`/processor-chain (`ShowStocksProcessor`, `FilterProcessor`, `SortProcessor`, …) over QD subscriptions — the same design shape as our rule-floor configs, but expressed as a DSL parsed client-side.
- **ThinkScript.** the *compiler* is not in the sample; the visible seams are `chartdata/ThinkScriptEnum(+Helper)` in `toscommon-instrument`, `thinkscript/FundamentalType` in the scanner jar, and `ThinkScriptEnumHelper`-adjacent chart-data plumbing. The ladder likewise: the `updown` spinner widget family and table/floating-header widgets in `toscommon-client` are the primitives, but the ladder screen itself lives in the downloaded `usergui` module.

---

## 6. V2 packaging conclusions

1. **Thin installer, thick runtime-download is the proven pattern here.** The installer's only jobs: JVM discovery + managed-JRE path, a small signed bootstrap, server-list config, and a content-verified module downloader with diff updates and rollback. The trading client is just "module #2".
2. **The seam inventory for a V2 client**: feed API (`DXEndpoint`-style facade), domain record extensions (qdext-style), trading RPC over the same transport (RMI-style), versioned module dirs with sha256 manifests, staged index flips, and a failover server list persisted on success.
3. **Schwab's layering is instructive**: all DevExpInc/DxFeed code is under `com.devexperts.*`; Schwab branding and host names arrive as data (`zacinst.ini` suffix, `whitelabel=tos`, `SchwabUIScheme`, banner API host) — i.e. a white-label boundary implemented via config + a thin UI-scheme module, not code forks.
4. **Risks/notes**: the suit still carries JNLP-era machinery (jnlp descriptors, jardiffs) — a modern V2 would use plain manifests + zstd/ggpt-style chunk deltas, but the *staging, keep-list, rollback, and pointer-file* design is directly reusable. The installer also ships Windows-only browser plugins and RTD DLLs inside a cross-platform jar — a packaging wart to avoid.

---

## 7. Provenance & limitations

- Carve re-verified from the raw installer: zip `[19531, 27295032)`, EOCD at 27295010; trailing gzip tar of exactly 2,933,291 bytes (matches the preamble's own `tail -c` constant). Extracted trees: `/tmp/tos-recon2/app` (payload) and `/tmp/tos-recon2/` (install4j runtime).
- Decompilation: Vineflower 1.11.1 from Maven Central, run on OpenJDK 26.0.2; decompiled sources under `/tmp/tos-recon2/src` (tos-suit 186 files, qds 563, dxfeed-api 137, dxlib 101, mars 31, launcher 9, plus all toscommon-*/tos-common-* jars). Manifests were inspected directly (`unzip -p … META-INF/MANIFEST.MF`) rather than decompiled.
- **Not verifiable from this sample:** the `usergui` client module (chart engine, ThinkScript compiler, ladder UI), since it is not shipped. Where this dossier names those subsystems it explicitly cites only the shipped seams. A follow-up would require a live first-run download (not performed — no Schwab servers were contacted).
- Clean-room: study only; no code reuse. All quotes are one-to-three-line identifying fragments for evidence, not reproduced implementations.
