# V2 scripting-language spec — series model, grammar, built-ins, strategy/scanner/MCP surfaces

**Ticket:** [#346 — Write the V2 scripting-language spec](https://github.com/rivers-research-hq/opentrader/issues/346)
**Parent map:** [#326 — Opentrader V2 locked spec](https://github.com/rivers-research-hq/opentrader/issues/326)
**Date:** 2026-10-07
**Status:** DESIGN DOC (no implementation). Sections marked **[LOCKED]** restate
decisions already made by the human (#337, #334, #339, #335); sections marked
**[PROPOSED]** are this ticket's design proposals awaiting implementer/human
confirmation; open questions are collected in §10.

**Inputs (provenance):** the ThinkScript language study
(`v2-thinkscript-study.md`, ticket #328 — official Schwab docs, clean-room), the
usergui compiler dissection (`v2-usergui-dissection.md` §4, ticket #344), the
installer/scanner dissection (`v2-tos-dissection.md`, ticket #327), the V1
salvage audit (`v2-v1-salvage.md` §2.1, ticket #331), and the locked decisions
in #337 (language approach) and #334 (MCP-native A2A surface, Tier-3 launch
bar). Clean-room discipline: nothing here is transplanted from decompiled code;
ThinkScript is cited as *semantics to copy or drop*, per the #328 study.

**Scope of the language.** One language — working name **v2script** — serving
four hosts: chart studies, order-aware strategy backtests, scanner filter/sort,
and the MCP evaluation surface. #337 **[LOCKED]**: ThinkScript-inspired,
series-native DSL; ThinkScript's documented warts dropped; scanner uses the
same language/compiler; the strategy subsystem is order-aware (virtual orders);
the MCP surface can evaluate scripts. Execution target **[LOCKED]**: an
AST interpreter in Rust now (hot-reload, sandbox-safe, no compile step), with
Cranelift-native compilation as a later Tier-3 optimization wave for
scanner-scale sweeps — *the language definition does not change between tiers*.
Pine-compat import and Rhai are **[LOCKED]** out of launch scope.

---

## 1. Core execution model **[PROPOSED — refines LOCKED "series-native"]**

### 1.1 Series-by-default

Every binding is a per-bar time series aligned to an evaluation *frame* (§5).
A script is an expression DAG evaluated bar-by-bar over the frame's loaded
history; scalar-looking code is implicitly a map over bars, so indicators read
like math, not loops. This is the ThinkScript killer feature and the core we
keep (`v2-thinkscript-study.md` §3.1).

- **`def`** — a derived series: `def fast = Average(close, 9);`. Its value at
  bar *t* is the expression evaluated with all history access relative to *t*.
  `def` bindings must be acyclic (self-reference is a compile error — state
  requires `series`, below).
- **`series`** — a stateful binding with an *explicit initializer*:
  `series cum = 0 then cum[1] + volume;`. `x[1]` inside the `then` expression
  refers to the previous bar's value of `x`; the init expression is evaluated
  at the first bar. This fixes ThinkScript's silent zero-init recursion
  (study §4.4) by construction: **there is no implicit initialization**. The
  general ThinkScript `CompoundValue(n, visible, historical)` form remains a
  built-in for "independent init point" cases, implemented over `series`.
- **History indexing**: `expr[n]` with *n ≥ 0* — past only. **Negative
  (future) indexing does not exist in the language** (study §4.5, the single
  biggest community repaint footgun). Look-ahead is not expressible, so it
  cannot be shipped by accident.
- **Recursion horizon is unbounded** (a `series` may read its own past), which
  means a stateful binding's output can depend on how much history was loaded.
  Range-independence conventions handle this (§1.4).

### 1.2 Laziness and conditionals

`if c then a else b` is **lazy**: only the taken branch is evaluated per bar.
ThinkScript's always-both-branches if-expression is the study's most documented
semantic trap (§4.1) and is **[LOCKED]** dropped (#337 warts clause). Both
branches are still type-checked at compile time (same type required). The
statement form is retained for plots:

```
plot sig;
if close > Average(close, 20) {
    sig = 1;
} else {
    sig = Double.NaN;
}
```

with the usual per-branch evaluation, and a compile-time exhaustiveness check
that every declared-then-assigned plot is assigned on every path (or carries a
declared default).

### 1.3 Per-binding warm-up (no global past offset)

ThinkScript's study-global past offset lets one 11-bar average shift a sibling
counter's initialization (study §4.2). v2script computes **warm-up per
binding**: each `def`/`plot` gets its own required lookback = max static
`[n]` in its expression tree plus callees' declared lookbacks; bars before a
binding's warm-up yield `NaN`, never silently-shifted values. A `series`
initializes at the frame's first bar regardless of sibling lookbacks. This
makes warm-up a static, per-column property the host can read (§5.4, §9) and
is **[PROPOSED]** as the fix #337 mandates.

### 1.4 Determinism and warm-up conventions

- Built-ins declare their exact lookback. Averaging families that converge
  asymptotically (EMA/Wilder/RMA) additionally declare a **prefetch
  convention** — the multiple of `length` of prior bars the host must supply
  so the emitted value is independent of loaded-history length within a
  published tolerance (the ThinkScript prefetch idea, made explicit; study
  §1.2). E.g. `EMA(close, 20)` declares lookback 0 but warm-up 4×length.
- A script whose stateful bindings make it history-length-dependent (cumulative
  sums, all-history references — §7.4) is flagged at compile time with
  `warmup: unbounded`, and evaluation results carry a `warmup_complete:
  bool`. Consumers (chart, scanner, MCP) may refuse or annotate. **No numeric
  output is presented as complete without this flag** (audit-gate rule 4
  applied to the language itself).

### 1.5 Recalculation contract — explicit and user-visible

ThinkScript couples recalculation mode to hidden expression properties (study
§4.11). v2script makes it a first-class, declared property:

- **Chart studies**: default `recalc = bar_close;` (evaluate once per closed
  bar). `recalc = tick;` opts a study into per-tick recomputation of the
  forming bar for smoother plots. Plots may repaint *only the forming bar*.
- **Signals and strategies always evaluate on closed bars only** — a signal
  emitted at bar *t* is a function of data through *t*'s close, full stop.
  There is no repaint of emitted signals; this is a structural no-lookahead
  guarantee (§7.2), matching V1's engine-integrity lesson
  (`v2-v1-salvage.md` §2.1) and the #337 wart drops.
- **Scanner**: `recalc = bar_close` only (scan results update on bar closes).

### 1.6 Types

A deliberately tiny, statically-checked set: `bool`, `int`, `float`, `string`,
`color`, `timeframe` (enum), plus user-declared input-enums. Every value in a
script is a per-bar series of one scalar type (`Series[T]`); scalars are the
"constant series". Two hard differences from ThinkScript (both fixes, study
§4.9 and the #337 warts clause):

1. **`bool` is not numeric.** Summing conditions requires an explicit
   `count(cond)` or `if cond then 1 else 0`. Truthiness mistakes become type
   errors at compile time.
2. **NaN is `float`-only.** Booleans, ints, strings have no NaN; a warm-up
   hole in a non-float series is a compile-time preventable only via explicit
   `Option`-free design: int/string/bool bindings must be total (init at
   first bar or literal); the checker enforces it.

Function arguments are **named and order-independent**
(`Average(length = 20, data = close)`), copied verbatim from ThinkScript
(study §3.3) — call sites stay self-documenting and refactor-safe, and the
calling convention serializes cleanly into JSON for the MCP surface (§8).

## 2. Plot model **[PROPOSED — shape copied from ThinkScript, study §1.4]**

`plot Name = expr;` declares a named, visible output series bound to a pane:

- `declare lower;` / `declare upper;` / `declare on_price;` select the pane
  (oscillators below, overlays on price). Minor ThinkScript declarations
  (`zerobase`, `hide_on_daily`, …) arrive as a small declarative family; each
  is data, not behavior — the host renderer consumes them.
- Plots may be **declared first, assigned later** (forward references between
  plots), with the exhaustiveness check of §1.2.
- **NaN means "don't paint here"** — the single sentinel for gaps, conditional
  painting, and warm-up holes. Painting style lives on the plot:
  `Name.set_style(LINE | POINTS | ARROW_UP | BOOLEAN_WEDGE, color, weight)`
  via look-and-feel built-ins (§4.5).
- Side-effect built-ins (labels, bubbles, clouds, vertical lines, price/bar
  coloring, alerts) mirror ThinkScript's Look-and-Feel family as
  *annotations*: they attach presentation metadata to (bar, value) pairs and
  are consumed by the chart host only. In scanner/MCP host modes,
  annotation built-ins are compile-time **no-ops** (allowed, dropped) except
  `alert`, which maps to the host's alert pipeline — one script, portable
  across hosts.

## 3. Grammar sketch **[PROPOSED]**

Statement grammar (EBNF-lite; lexer is conventional — reserved words below —
with the ThinkScript human-readable operator sub-syntax desugared at parse
time: `close from 2 bars ago` → `close[2]`, `a crosses above b` → the
`CrossesAbove(a, b)` built-in):

```
script        := { statement }

statement     := declare_stmt | input_stmt | def_stmt | series_stmt
               | plot_stmt | study_stmt | strategy_stmt | effector_stmt
               | if_assign_stmt

declare_stmt  := "declare" IDENT [ "=" expr ] ";"          // study properties
input_stmt    := "input" IDENT "=" input_default ";"
               | "input" IDENT "=" "{" IDENT { "," IDENT } "}" "default" IDENT ";"
def_stmt      := "def" IDENT "=" expr ";"
series_stmt   := "series" IDENT "=" expr "then" expr ";"   // init expr, step expr
plot_stmt     := "plot" IDENT ( "=" expr ";" | ";" )       // decl-then-assign
study_stmt    := "study" IDENT "{" script "}"              // user subroutine
strategy_stmt := "strategy" IDENT "{" { strategy_item } "}"   // §7
effector_stmt := effector "(" named_args ")" ";"           // label/alert/…
if_assign_stmt:= "if" expr "{" { statement } "}" [ "else" ( if_assign_stmt | "{" { statement } "}" ) ]

expr          := if_expr | or_expr
if_expr       := "if" expr "then" expr "else" expr          // LAZY (§1.2)
or_expr       := and_expr { ("or" | "xor") and_expr }
and_expr      := not_expr { "and" not_expr }
not_expr      := "not" not_expr | comparison
comparison    := range_expr { ("=" | "<" | ">" | "<=" | ">=" | "crosses above"
                              | "crosses below" | "between") range_expr }
range_expr    := additive { "to" additive }                  // for `between`
additive      := multiplicative { ("+" | "-") multiplicative }
multiplicative:= unary { ("*" | "/") unary }
unary         := "-" unary | postfix
postfix      := primary { "[" expr "]" | "." IDENT }
primary      := NUMBER | STRING | constant | IDENT
               | IDENT "(" [ named_args ] ")"               // built-in / study call
               | "(" expr ")"
named_args    := IDENT "=" expr { "," IDENT "=" expr }      // named, order-free
```

Notes on what is deliberately absent:

- **No negative indexing** (§1.1). `[n]` requires a non-negative int expr;
  the checker proves it constant-foldable at compile time (dynamic offsets go
  through `GetValue(data, offset, max_offset)` with a declared cap, as in
  ThinkScript's fold+GetValue idiom).
- **`fold` is the only loop**, per-bar: `fold i = 0 to n with p = init while
  cond do expr` — copied from ThinkScript (study §1.5) with a checked
  iteration budget (§9.2 guardrails). `while` is the early-break.
- **No user functions; `study` blocks are the only subroutine**, invocable
  like a built-in with named args, dot-selected plots
  (`MyAvg(20).smoothed`), first plot as default return — copied from
  ThinkScript. **Unlike ThinkScript, user studies may reference other user
  studies** (TOS bans this and its ecosystem copy-pastes; study §4.7). The
  module/versioning model is open question §10.4.
- Built-in studies callable as ordinary functions
  (`Stochastic(data = close, k = 14)`); `reference <study>;` for wholesale
  import.
- Reserved-word list is small and closed; adding words is a breaking change
  versioned with the language (§10.9 IR versioning).

## 4. Built-in function families **[PROPOSED — taxonomy from study §2]**

Organized by family (the ThinkScript eleven-family taxonomy, adapted to
FX-first V2 — no options/greeks/corporate-actions at launch; those are later
waves gated on venue support):

1. **Fundamentals** — `open, high, low, close, volume, bid, ask, mid,
   spread, hl2, hlc3, ohlc4, vwap, tick_count` — each parameterized by
   `symbol` and `period` (§5); `price_type` (LAST/BID/ASK/MID) replaces
   ThinkScript's LAST/ASK/BID/MARK (no MARK on FX venues at launch). The
   OANDA semantic-port facts apply underneath: prices are fetched live from
   the venue, never from a write-once cache (#339, `v2-usergui` defect
   history in AGENTS.md).
2. **Technical** — `Average, EMA, Wilders, WMA, MovingAverage(avg_type),
   Highest, Lowest, HighestAll*, Sum, TrueRange, ATR, RSI, Stochastic,
   MACD, BodyHeight, IsDoji` and candlestick predicates.
   (`*HighestAll`-family = whole-history: legal but flags the study
   `warmup: unbounded` and changes its recalculation class — ThinkScript's
   documented trap made loud, study §4.6. **Banned in scanner mode.**)
3. **Statistical** — `StDev, Correlation, Covariance, LinDev, Inertia,
   Rank` (cross-sectional, per-bar — V1's per-bar rank semantics, the
   commit 9b7301a fix, carried as a first-class `Rank(data, n)`).
4. **Math & trig** — the ordinary set, plus `Min, Max, Abs, Log, Round`
   and `NaN`/`Infinity` constants.
5. **Look-and-feel / annotations** — §2: labels, bubbles, clouds, vertical
   lines, price/bar coloring; no-ops outside the chart host.
6. **Date & time** — `BarNumber, SecondsTillTime, GetTime, SessionOpen/
   Close, IsMarketOpen` — session-aware for FX (weekend rollover, venue
   schedule via the schedule-provider seam).
7. **Strategy** — order-aware family, §7 (`Entry, Exit, Flatten,
   Position, EntryPrice, OpenPL, TotalPL`, …). Chart-host-only.
8. **State & misc** — `CompoundValue, GetValue, If (deprecated alias for
   the lazy if-expression, kept for compatibility), Between, CrossesAbove/
   Below, Concat, Format` (string formatting stays minimal, ThinkScript-level
   — study §4.8; richer strings are open question §10.7).
9. **Constants/enums** — first-class enum values as in ThinkScript's
  constant taxonomy: `AggregationPeriod, AverageType, CrossingDirection,
  Color, PaintingStrategy, PriceType, OrderType, OrderSide` — the input-enum
  surface below consumes them.

**Inputs are the GUI/config schema.** `input length = 14;`,
`input showSig = true;`, `input color1 = Color.GREEN;`,
`input mode = { SMA, EMA } default SMA;` — typed, defaulted, enum dropdowns
generated from code, copied verbatim from ThinkScript (study §3.2). The
compiler emits a **JSON Schema** for a script's inputs — this is how the
MCP surface (§8) and hosted UI drive evaluation without parsing the script.

## 5. Frames, aggregation, and period handling **[PROPOSED]**

The frame model — v2script's answer to ThinkScript's sharpest edge, implicit
aggregation-context demotion (study §4.3):

- Every expression has a compile-time **frame**: the primary frame (the
  host's chart/scan timeframe) by default, or a secondary frame via data
  params: `close(period = HOUR_1)`, `Average(close("EUR/USD", period =
  DAY), 20)`.
- A secondary frame must be ≥ the primary (a daily series on an hourly
  chart is fine; the reverse is a compile error — same constraint as
  ThinkScript Chapter 11, kept).
- **Mixing frames in one expression is a compile error, always** — no silent
  demotion to primary context exists in the language. Cross-frame use
  requires an explicit alignment built-in:
  - `align_upper(s, method)` — bring a higher-frame series into the current
    frame: `LAST` (forward-fill, the standard "daily value on intraday
    bars"), `CONFIRMED` (NaN until the upper bar has closed — the
    repaint-safe variant, default), `EXACT` (NaN except on boundary bars).
  - `resample_lower(s, how)` — fold a lower-frame series up to a higher
    frame (`open/high/low/close/sum/last` per boundary bar).
- Frame inference is **static** (every binding's frame is known at compile
  time and reported in the compile plan) — the host can pre-subscribe all
  frames a script needs before evaluation starts, exactly the
  dependency-analysis seam the TOS compiler exposes (usergui §4
  `script/Dependency`, `FunctionUsageFinder`).
- Aggregation beyond time (tick/range/renko bars) is a *data-layer* property
  (aggregation-rule objects, usergui §3.1 `chartcommon`) — the language's
  `period` speaks time frames only, as ThinkScript's does (study §1.3).
  Exposing non-time aggregation to scripts is open question §10.8.
- `symbol` is an ordinary data param: cross-symbol formulas are one-liners
  (`Correlation(close, close("GBP/USD"), 20)`). A script's symbol set is
  static (compile-plan-visible) — required for scanner/MCP prefetch and
  metering.

## 6. Host binding model (script-to-chart, scanner, alerts, columns) **[PROPOSED]**

One compiled artifact, several hosts — the TOS design we copy structurally
(usergui §4): ThinkScript's `ThinkScriptRequest` carrier `{symbol,
requestAttributes, escapedFormula}` with mode tags (alert `'A'`, custom
column `'C'`, predefined `'P'`) becomes v2script's **`ScriptRequest`**:

```
ScriptRequest { source, mode: Study | Alert | Column | Scan | McpEval,
                context: { symbol, timeframe, price_type }, inputs: json }
```

- **Compile plan** (the TOS seam inventory, usergui §4, restated for the
  Rust interpreter): text → AST → static analysis (frames, per-binding
  lookback/warm-up, symbol set, input schema, annotation usage, guardrail
  metrics) → *typed evaluation plan*. TOS compiles the plan to JVM bytecode;
  V2's interpreter walks the plan directly, and the same plan is the input
  the later Cranelift tier compiles — the language and plan are tier-stable
  (#337).
- **Binding**: a host instantiates a plan against data sources (frame
  subscriptions for the plan's symbol/frame set) and a calculator that owns
  per-instance state: per-binding columns, `series` state slots (TOS's
  "past-offset state as fields", usergui §4), annotation buffers. Host
  modes consume different output faces: plots+annotations (Study), boolean
  column value (Column/Alert filter), filter+sort pair (Scan), everything
  (McpEval).
- **Hot reload** (#337's reason for the interpreter): an edit recompiles and
  rebinds without a restart; whether `series` state carries over or
  reinitializes is open question §10.6.
- **Versioned fixers**: TOS's `codeport/` fixer passes (usergui §4) map to a
  semantic-versioned AST with idiom-rewrite passes; fixers run at load, are
  recorded in the compile plan, and never silently change semantics across a
  version boundary.

## 7. Order-aware strategy surface **[PROPOSED — order-awareness LOCKED by #337]**

#337 locked that the strategy subsystem is order-aware: scripts place and
track **virtual orders** — script backtests — via the same machinery as
studies (TOS's `strategies/` + `ScriptStrategyApi`, `IEntryOrder`/
`IExitOrder`, `StateRecord`, `StrategyConfiguration`, usergui §4). ThinkScript's
boundary is inverted though: TOS strategies are chart-hypotheticals that
*cannot* reach an order pipe (study §4.10); V2 strategies run on the same
no-lookahead engine the venue lanes use, and their output is *promotion
evidence*, not decoration.

### 7.1 Shape

A strategy is a `strategy` block — a study body plus order statements:

```
strategy BreakoutATR {
    input stopMult = 2.0;
    input riskUnits = 10000;                 // units, FX-first

    series atr = ATR(14) then atr[1];        // warm-up demo; ATR is a built-in anyway
    def upper = Highest(high, 20);
    def goLong = close crosses above upper;

    on goLong -> Entry(side = LONG, size = riskUnits,
                       stop   = close - stopMult * atr,
                       target = close + 2 * stopMult * atr);
    on close < Average(close, 50) -> Exit(side = LONG);
    on MaxHold(20) -> Flatten();
}
```

- `on cond -> Action(...)` fires when the closed-bar boolean series `cond` is
  true at bar *t*; `cond` is a normal series expression (full language
  available).
- Order actions: `Entry` (market, or pending `limit =`/`stop =` prices),
  `Exit` (reduce/close by side or tag), `Flatten`, `Modify` (move stop/
  target — trailing stops are a `Modify` on a `TrailingPeak` series, V1's
  trailing-peak semantics, salvage §2.1). Brackets/OCO are properties of an
  `Entry` (stop+target ride the position as OCO by default).
- Pyramiding is off by default; `declare pyramiding = N;` if wanted.

### 7.2 Fill and no-lookahead semantics (binding invariant)

- **Decisions on closed bar *t*; market fills at bar *t+1* open** — the
  ThinkScript default (study §1.4), and structurally lookahead-free.
- Pending limit/stop orders evaluate against subsequent bars' high/low with
  conservative same-bar rules (bar order: stop before target if both
  touched; V1's same-bar TP/SL discipline, salvage §2.1).
- Exits: TP/SL against the same bar's high/low once in position; trailing
  from highs; max-hold; signal exits. Delisted/closed symbols force-exit at
  last close (V1 semantics).
- Costs: half-spread + commission model from venue config (FX-first: the
  OANDA practice semantics the FX arm already runs — AGENTS.md "Venue is
  authoritative"); fills are **venue-journaled in live mode, modeled in
  backtest mode**.
- Whether V2's *engine-wide* backtest contract should be prior-close-
  decision/current-bar-close (V1 `run_backtest`, salvage §2.1) or
  next-bar-open (this surface) is open question §10.5 — the strategy
  surface here and the standalone backtest-engine ticket (#326 "not yet
  specified" graduate) must agree.

### 7.3 State, checkpointing, live parity

- Strategy runtime state — virtual position, open orders, per-`series` state
  slots, cumulative P/L — is a first-class **`StrategyState`** (TOS's
  `StateRecord` seam) that serializes deterministically. Checkpoint/restart
  must reproduce identical subsequent output given identical subsequent
  bars (live-restart parity — the question the ThinkScript study posed and
  TOS never had to answer, §5.4 there).
- Backtest and live are the same evaluator over the same frame
  subscriptions (TOS's OnDemand/time-machine lesson, usergui §3.2);
  "backtest" is a replay of recorded frames, "live" is streaming frames.
- **Boundary — binding from AGENTS.md/V1 doctrine:** strategy scripts emit
  *virtual* orders only. Routing virtual orders to a real venue is a
  separate, explicitly human-gated promotion (V1's "the human decides and
  gates" rule, AGENTS.md role division #4), passing through the semantic
  ports of `guards.py` (risk gates) and lane attribution (#339). The
  language has no live-order verb. An MCP caller likewise cannot bridge a
  strategy into live routing by construction.

### 7.4 Reporting

Per-strategy trade list (entries/exits with bars and prices), realized/
unrealized P/L net of costs, and the metric set (PF, Calmar, maxDD, trade
count, fee ratio — V1's wide-eval vocabulary). Exposed as the return of
`script.backtest` (§8) and the strategy pane in the chart host.

## 8. Scanner filter surface **[PROPOSED — same-language LOCKED by #337]**

The scanner's filter/sort language **is** v2script (TOS's `TosFormulaParser`,
`ThinkScriptFilterProcessor`, `ThinkScriptSortProcessor` over QD
subscriptions, usergui §4 — the 10× leverage point). A scan is:

```
Scan { script_source, universe, timeframe,
       filter: <a boolean plot or last def>, sort: <a numeric plot, optional>,
       limit: N }
```

- The filter expression must be a `bool` series evaluated at the last closed
  bar per symbol; the sort expression a `float` series; both are ordinary
  language expressions (any built-ins, studies, frames ≥ scan timeframe).
- **Execution**: compile once → per-symbol evaluation plans with their
  data-needs unioned → batch-evaluated over the universe on bar close,
  incrementally (only symbols whose frames changed re-evaluate). The
  compile plan's symbol/frame set drives subscription management (the
  processor-chain design from `v2-tos-dissection.md` §5, scanner section).
- **Scanner-grade guardrails (compile-time refusals)**: no whole-history
  built-ins (`HighestAll`), no unbounded-warmup scripts unless the scan
  explicitly grants history, capped lookback (default e.g. 500 bars), capped
  fold budget, capped statement count (TOS's `ScriptIsTooLongException` /
  `ColumnComplexityCache` discipline, usergui §4 — made static).
- The **Cranelift tier** (#337) targets exactly this surface: 10k symbols ×
  multi-year sweeps are the JIT-pressure point; single-chart studies stay
  interpreted forever. Determinism requirement: tier output must be
  bit-comparable to interpreter output on the same frames (a conformance
  test, not an aspiration).
- Scans are also first-class MCP resources (§9) — an agent can define, run,
  and subscribe to a scan within its metered budget.

## 9. MCP evaluation surface **[PROPOSED — evaluability LOCKED by #334]**

#334 locked that ThinkScript-class scripting is callable from MCP for the
A2A story (agents as hosted-API customers, tool-calls metered two-meter:
data reads wholesale-cheap, actions priced). Tool surface:

| Tool | Purpose | Metering class |
|---|---|---|
| `script.validate` | compile-only: errors, input JSON Schema, frames/symbols needed, lookback, warm-up class, guardrail metrics | free/cheap |
| `script.eval` | run a script over `{symbols, timeframe, range, inputs}` → plots (downsampled arrays), scalars (`last`, user-tagged), annotations | per-call + data reads |
| `script.backtest` | strategy script → §7.4 report | per-run (compute-heavy) |
| `scan.run` | §8 over a universe | per symbols×bars touched |
| `script.store` / `script.list` / `script.get` | versioned script library (store returns `script_id@rev`) | cheap |

Design rules:

- **Capability-sandboxed by construction** (this is why #337 chose an
  interpreter): the language has no I/O, no wall-clock, no randomness, no
  network — a script can only transform data the host feeds it. Every tool
  call is deterministic given `(script_rev, inputs, data snapshot hash)`,
  which is also the cache key.
- Results carry the compile plan's honesty metadata: `warmup_complete`,
  frames used, bar count — so an agent consumer can't misread a truncated
  evaluation (audit-gate rule 4 applied to the API).
- Strategy outputs from MCP are *reports* only — the §7.3 boundary means no
  MCP tool bridges a script backtest into live order flow; the existing
  order-action tools (the priced action tier of #334) remain the only path
  to a venue, gated by the operator's risk bounds.

## 10. Open implementation questions (for the Rust interpreter ticket)

1. **Value representation.** `enum Value { Bool(bool), Int(i64), Float(f64),
   Str(...), ... }` vs NaN-boxed u64; `Series<T>` storage columnar per
   binding (`Vec<f64>` per def, per frame) vs row-wise. NaN-as-sentinel vs
   `Option` boundaries at host edges. F64-only numerics (int promoted at
   compile?) — recommendation: keep int/float distinct in the checker, f64 in
   storage.
2. **Parser tooling.** Hand-rolled lexer/parser (TOS's action-record
   lineage) vs `pest`/`lalrpop`. Needs: precise error spans for the IDE,
   error recovery for hot-reload editing. The named-arg calling convention
   and `crosses above` word-operators favor a hand-rolled or highly
   customized grammar.
3. **Frame materialization.** Eager resampled frames per (symbol, frame)
   cached host-side vs lazy aligned cursors. Eager is simpler and makes the
   compile plan's subscription set exact; lazy wins on scanner-scale memory.
   Likely: eager for chart host, lazy/batched for scan host — but that must
   not leak semantic differences (conformance tests across hosts).
4. **User-study modules.** Namespacing, versioning, and upgrade policy for
   user-studies-referencing-user-studies (the thing TOS bans). Pinned
   versions per referencing script? Global "latest" with recorded rev?
   Breaking-change discipline for built-ins alongside.
5. **Fill-model parity.** Strategy backtests here spec next-bar-open fills;
   V1's `run_backtest` contract is prior-close-decision/current-close-fill
   (salvage §2.1). The standalone backtest-engine ticket must lock one
   engine-wide answer or an explicit dual contract with a stated mapping —
   otherwise V1 evidence numbers and V2 strategy results are silently
   incommensurable (a repeat of the 1718f33 same-bar bug class).
6. **Hot-reload state policy.** On edit: reinit all `series` state, or
   best-effort carry-over by binding name+type? Carry-over risks wrong
   values after semantic edits; reinit loses long warm-ups on charts.
   Proposal: reinit by default, `declare keep_state;` opt-in.
7. **String/format richness.** ThinkScript-level minimal (`Concat`,
   `Format`) at launch, or a small formatting family (number formats,
   date formats) — scanner columns and MCP labels want a bit more than TOS
   shipped.
8. **Non-time aggregation in-language.** Tick/range/renko frames exposed via
   `period`-like params, or kept data-layer-only (chart types) at launch?
9. **AST/plan versioning + fixer pass discipline.** TOS's codeport fixers
   suggest: versioned IR, fixers recorded in the plan, a frozen grammar per
   language version (`v2script 1.x`), and a policy for reserved-word
   additions.
10. **Complexity guardrail metrics.** Which static metrics (statement count,
    fold budget, lookback, frame count, symbol count) gate which hosts, and
    their default caps; how they surface in `script.validate` output and
    metering.
11. **FX specifics in the fundamentals family.** Position sizing in units,
    half-spread cost model, session/rollover semantics in Date&Time
    built-ins, and whether venue-true bid/ask series (not just derived mid)
    are exposed as first-class fundamentals (OANDA semantic-port influence,
    #339).
12. **Determinism across tiers.** The conformance suite that pins
    interpreter output = Cranelift output = backtest-replay output, and the
    property tests for the §7.2 no-lookahead invariants (prior-close
    decision, next-bar fill — proptest-expressible per salvage §2.1).

---

## Provenance & epistemic notes

- ThinkScript semantics are cited from the clean-room study
  (`v2-thinkscript-study.md`, official Schwab docs; decompiled-jar cross-check
  recorded as not performed there). Compiler seams cited from the clean-room
  usergui dissection (§4) and scanner seams from the installer dissection
  (§5). No decompiled code is reproduced or reused.
- **[LOCKED]** items restate human decisions (#337 language approach, #334
  MCP/Tier-3 bar, #339 salvage/FX continuity, #335 all-Rust) and are not
  re-litigated here. **[PROPOSED]** items are this doc's design proposals and
  need confirmation before implementation tickets are cut from them; §10
  questions feed the implementation-planning ticket.
- No numeric claims about V1 or thinkScript are introduced; V1 semantics
  referenced (no-lookahead contract, trailing-peak exits, rank fix) are
  cited to the salvage audit and AGENTS.md, per ToC claims governance.
- Scope guard: this doc defines the *language*, not the host. Chart binding,
  metering implementation, Cranelift tiering, and the backtest-engine
  contract are referenced but belong to their own tickets (#326 graduates).
