# Research: ThinkScript language design (grammar, built-ins, plot model)

**Ticket:** [#328 — Study ThinkScript language design (grammar, built-ins, plot model)](https://github.com/rivers-research-hq/opentrader/issues/328)
**Parent map:** [#326 — Opentrader V2 locked spec](https://github.com/rivers-research-hq/opentrader/issues/326)
**Date:** 2026-10-07
**Method:** Schwab's official thinkorswim Learning Center (thinkScript reference:
tutorials, reserved words, declarations, functions, constants, operators, data types),
cross-checked against the useThinkScript community FAQ for practitioner-observed
behavior. **Clean-room:** semantics only, nothing transplanted. The ticket suggested
cross-checks against the decompiled `tos-suit` jar; no such jar exists on this machine
(searched `$HOME`, the sandbox, and the repo — nothing matches `*tos*suit*`), so the
grammar description below is derived from the official reference and the language's
documented behavior, and the jar cross-check is recorded as **not performed**.

---

## 1. The core model

### 1.1 Series-by-default: every binding is a time series

The defining idea of thinkScript is that **every variable is a per-bar time series**.
A script is not a program that runs once; it is an expression tree that the engine
evaluates bar-by-bar over the chart's loaded history. `def price = close;` does not
capture one close — it binds a series whose value at each bar is that bar's close;
`def condition = close > 700;` yields a series of 0/1 values, and Booleans are
explicitly numeric (they can be summed and averaged). Source:
[Chapter 1 — Defining Variables](https://toslc.thinkorswim.com/center/reference/thinkScript/tutorials/Basic/Chapter-1---Defining-Variables).

Consequences:

- **No loops over bars are needed for most indicators** — the engine does the
  iteration; scalar-looking code is implicitly a map over bars.
- **Indexing, not iteration, is the history-access operator:** `close[5]` is the
  close 5 bars ago; positive index = past, **negative index = future**
  (`close[-1]` is the next bar's close — the language explicitly permits
  look-ahead). Source:
  [Chapter 10 — Referencing Historical Data](https://toslc.thinkorswim.com/center/reference/thinkScript/tutorials/Advanced/Chapter-10---Referencing-Historical-Data).
- **Recursion is a first-class declaration form**, not an error: `def vol = vol[1] + volume;`
  compiles and computes cumulative volume. The initial value of a recursive
  variable is implicitly 0 at the first bar; explicit initialization is done with
  `CompoundValue(length, visibleData, historicalData)`, which selects the
  historical-data argument for bars before `length`. Sources:
  [Chapter 1](https://toslc.thinkorswim.com/center/reference/thinkScript/tutorials/Basic/Chapter-1---Defining-Variables),
  [Chapter 10](https://toslc.thinkorswim.com/center/reference/thinkScript/tutorials/Advanced/Chapter-10---Referencing-Historical-Data).
  The older `rec` keyword ("recursion") is the same thing and is officially
  obsolete, replaceable by `def`: [reserved word `rec`](https://toslc.thinkorswim.com/center/reference/thinkScript/Reserved-Words/rec).

### 1.2 Past offset, prefetch, future offset — the execution contract

The engine computes a per-study **past offset** = the maximum lookback any
expression needs (e.g. `Average(close, 11)` ⇒ offset 10). Two documented rules
with real design bite:

- **The highest past offset in a study overrides all expressions in that study** —
  a recursive counter `def x = x[1] + 1;` sharing a study with an 11-bar average
  starts its first bar at 11, not 2, because both get the study-global offset.
  `CompoundValue` is the escape hatch to give an expression an independent
  initialization point. Source:
  [Chapter 12 — Past/Future Offset and Prefetch](https://toslc.thinkorswim.com/center/reference/thinkScript/tutorials/Advanced/Chapter-12---Past-Offset-and-Prefetch).
- **Prefetch** (ExpAverage, EMA2, WildersAverage only): the engine reaches back
  before the visible window (4×length bars for ExpAverage, 7×length for Wilders)
  so EMA values are **range-independent** — the same value regardless of how much
  history the chart loaded. Same source.

**Future offset**: any negative index makes the study depend on quotes that
haven't arrived yet; the recommended idiom for "last bar on chart" is exactly
this: `!IsNaN(close) && IsNaN(close[-1])`. The docs explicitly warn that the
popular alternative (`HighestAll(...)` over all bars) makes the study depend on
the entire chart, causing "productivity problems" and forcing once-per-bar
recalculation. Source:
[Chapter 12](https://toslc.thinkorswim.com/center/reference/thinkScript/tutorials/Advanced/Chapter-12---Past-Offset-and-Prefetch).

Recalculation mode is a study property: by default the last bar recalculates
**on every tick**; `declare once_per_bar;` forces recalculation only at bar close
(used to cut CPU). Source:
[declaration `once_per_bar`](https://toslc.thinkorswim.com/center/reference/thinkScript/Declarations/once-per-bar).

### 1.3 Bar model and aggregation/period handling

Charts aggregate quotes three ways (time, tick, range: Range Bars / Momentum Bars /
Renko), but thinkScript's period parameter only speaks **time aggregation**.
Source: [Chapter 11 — Referencing Secondary Aggregation](https://toslc.thinkorswim.com/center/reference/thinkScript/tutorials/Advanced/Chapter-11---Referencing-Secondary-Aggregation).

- Every data function takes `period` and `symbol` parameters; the chart's own
  setting is the **primary** period; any other period is **secondary**:
  `plot dailyOpen = open(period = AggregationPeriod.DAY);`.
- Constraints, both documented in Chapter 11:
  - a secondary period must be **≥ the primary** period (a daily reference won't
    work on a weekly chart);
  - **two different secondary periods cannot be mixed in one expression** — you
    must split into separate `def`s first.
- Period is an **enum constant** (`AggregationPeriod.MIN … YEAR, OPT_EXP`,
  see [AggregationPeriod constants](https://toslc.thinkorswim.com/center/reference/thinkScript/Constants/AggregationPeriod))
  or one of a fixed set of strings (`"1 min"`, `"Day"`, `"Month"`, `<current period>`, …).
- **Context demotion is implicit:** an expression mixing a secondary-period
  variable with any primary-period data (e.g. a Fundamental or Date&Time
  function, or a primary-period variable) silently evaluates the *whole*
  expression in the primary context; the Chapter 11 worked example shows
  `Average(priContext, 12)` becoming a *primary*-period average. This is one of
  the language's sharpest edges — aggregation context is tracked, but invisibly.
- Cross-symbol data is a plain parameter too: `close("IBM", period = AggregationPeriod.WEEK)`
  plots on any chart's symbol; `priceType` (LAST/ASK/BID/MARK) is likewise a
  parameter on every fundamental function. Source:
  [Chapter 13 — Referencing Other Data](https://toslc.thinkorswim.com/center/reference/thinkScript/tutorials/Advanced/Chapter-13---Referencing-Other-Data).

### 1.4 Plot model

`plot X = expr;` is the output surface: it declares a named **visible series**
assigned to a subgraph. `declare lower/upper/on_volume;` selects the pane; other
declarations change placement/behavior (`hide_on_daily`, `hide_on_intraday`,
`real_size`, `zerobase`, `weak_volume_dependency` — see
[Declarations](https://toslc.thinkorswim.com/center/reference/thinkScript/Declarations)).
Plots can be **declared first and assigned later** (`plot Second; … Second = Average(close, 10);`),
enabling forward references between plots. Source:
[reserved word `plot`](https://toslc.thinkorswim.com/center/reference/thinkScript/Reserved-Words/plot).

Besides plot series, a study emits through **side-effect functions** — labels,
bubbles, clouds, vertical lines, price/bar coloring, alerts:
`AddChartBubble, AddCloud, AddLabel, AddVerticalLine, AssignBackgroundColor,
AssignNormGradientColor, AssignPriceColor, AssignValueColor, DefineColor,
SetDefaultColor, SetHiding, SetLineWeight, SetPaintingStrategy, SetStyle, …`
(full list: [Look and Feel functions](https://toslc.thinkorswim.com/center/reference/thinkScript/Functions/Look---Feel)).
Plot appearance is driven by `PaintingStrategy` constants (lines, points, arrows,
boolean wedges…), and **NaN is the "don't paint here" sentinel** — the
appendix-documented idiom for gaps and last-bar detection. Sources:
[Constants index](https://toslc.thinkorswim.com/center/reference/thinkScript/Constants),
[Appendix D — NaN and Infinity](https://toslc.thinkorswim.com/center/reference/thinkScript/tutorials/Appendices/Appendix-D---Using-NaN-and-Infinity-Constants).

**Strategies** are studies plus `AddOrder(OrderType.BUY_AUTO, condition, …)`:
signals fire the next bar (default fill at `open[-1]` — deliberately
look-ahead-free), arrows appear on chart, a per-strategy P/L report is available,
and the docs are explicit that **signals are hypothetical — strategies cannot
send real orders**. Source:
[Chapter 7 — Creating Strategies](https://toslc.thinkorswim.com/center/reference/thinkScript/tutorials/Basic/Chapter-7---Creating-Strategies).

### 1.5 Study composition

- **`reference <BuiltInStudy>;`** pulls any of ~200–300 built-in studies' plots
  into your script; a built-in study is also callable **as an ordinary function**
  with all its parameters: `SimpleMovingAvg(volume, 20)`. Documented restriction:
  **only built-in studies can be referenced — users cannot reference their other
  custom studies.** Source:
  [Chapter 13](https://toslc.thinkorswim.com/center/reference/thinkScript/tutorials/Advanced/Chapter-13---Referencing-Other-Data).
- **`script` blocks** are the user's only subroutine mechanism: a named inline
  study with `input`s and `plot`s, invoked like a function; multiple plots are
  selected with dot notation (`avg(20).EMA`), with the first plot as the default
  return. Same source.
- **`fold`** is the only iteration construct: `fold i = 0 to n with p = init while cond do expr`
  — a per-bar fold whose `while` clause can break early; combined with
  `GetValue(data, dynamicOffset, maxOffset)` it implements loops over history.
  Source: [reserved word `fold`](https://toslc.thinkorswim.com/center/reference/thinkScript/Reserved-Words/fold).

### 1.6 Grammar surface (doc-derived)

The statement grammar is small and declarative — every top-level statement is one
of: `declare X;` (study metadata), `input name = default;` (GUI-exposed typed
parameter), `def name = expr;` (series binding), `plot name = expr;` (visible
output), `script name { … }` (subroutine), `AddOrder/Alert/Label…` calls
(side effects), or `if`/`switch` statements assigning to pre-declared plots.
Reserved words (the full 40-word list is at
[Reserved-Words](https://toslc.thinkorswim.com/center/reference/thinkScript/Reserved-Words))
include both programming keywords (`def, input, plot, if, then, else, switch, case,
and, or, not, fold, while, do, to, with`) and a **human-readable operator
sub-syntax**: `close from 2 bars ago`, `price crosses above avg`,
`between`, `is greater than`, `equals`, `within` — these desugar to indexing and
comparison. Data types are inferred on assignment; the type set is tiny —
`boolean, double, int, String, CustomColor, Symbol, Any/IDataHolder`
([Data Types](https://toslc.thinkorswim.com/center/reference/thinkScript/Data-Types)).
Function arguments are **named and order-independent**
(`average(length = 50, data = close)` — [Functions](https://toslc.thinkorswim.com/center/reference/thinkScript/Functions)).
Inputs are GUI-typed: boolean, integer, float, price, string, constant, and enum
(`input smoothingType = {Default SMA, EMA};` with `switch` dispatch —
[reserved word `input`](https://toslc.thinkorswim.com/center/reference/thinkScript/Reserved-Words/input),
Chapter 11 example).

Three conditional forms exist and they differ semantically:
- **if-expression** (`if c then a else b`): **always evaluates both branches**
  (documented explicitly);
- **if-statement** (`plot X; if c { X = … } else { X = … }`): evaluates only the
  taken branch;
- **`If(c, a, b)` function**: numeric operands only.
Source: [reserved word `if`](https://toslc.thinkorswim.com/center/reference/thinkScript/Reserved-Words/if),
[Chapter 5](https://toslc.thinkorswim.com/center/reference/thinkScript/tutorials/Basic/Chapter-5---Conditional-Expressions).

## 2. Built-in function families

The reference splits functions into eleven sections
([Functions index](https://toslc.thinkorswim.com/center/reference/thinkScript/Functions)):

| Family | Contents (representative) | Source |
|---|---|---|
| **Fundamentals** | `open, high, low, close, hl2, hlc3, ohlc4, vwap, volume, ask, bid, imp_volatility, open_interest, tick_count` — each parameterized by `symbol`, `period`, `priceType` | [Fundamentals](https://toslc.thinkorswim.com/center/reference/thinkScript/Functions/Fundamentals) |
| **Technical Analysis** | `Average, ExpAverage, EMA2, WildersAverage, WMA, MovingAverage(avgType), Highest/Lowest (+All, +Weighted), TrueRange, MoneyFlow, AccumDist, BodyHeight, MidBodyVal, candlestick predicates (IsDoji, IsLongBlack…)` | [Tech-Analysis](https://toslc.thinkorswim.com/center/reference/thinkScript/Functions/Tech-Analysis) |
| **Statistical** | `Correlation, Covariance, StDev(+All), StErr(+All), LinDev, Inertia(+All)` (formulas published in the docs) | [Statistical](https://toslc.thinkorswim.com/center/reference/thinkScript/Functions/Statistical) |
| **Mathematical & Trigonometric** | general math/trig built-ins | [Math---Trig](https://toslc.thinkorswim.com/center/reference/thinkScript/Functions/Math---Trig) |
| **Look and Feel** | chart-painting side effects (see §1.4) | [Look---Feel](https://toslc.thinkorswim.com/center/reference/thinkScript/Functions/Look---Feel) |
| **Option Related** | option pricing/greeks functions (unique to a brokerage-embedded language) | [Option-Related](https://toslc.thinkorswim.com/center/reference/thinkScript/Functions/Option-Related) |
| **Date and Time** | bar/session clock functions | [Date---Time](https://toslc.thinkorswim.com/center/reference/thinkScript/Functions/Date---Time) |
| **Corporate Actions** | e.g. `GetEventOffset` — scheduled-future-event functions (which *raise* the future offset) | [Corporate-Actions](https://toslc.thinkorswim.com/center/reference/thinkScript/Functions/Corporate-Actions) |
| **Portfolio** | account/position-aware values | [Portfolio](https://toslc.thinkorswim.com/center/reference/thinkScript/Functions/Portfolio) |
| **Stock Fundamentals** | fiscal/fundamental data | [Stock-Fundamentals](https://toslc.thinkorswim.com/center/reference/thinkScript/Functions/Stock-Fundamentals) |
| **Others** | `AddOrder, Alert, BarNumber, Between, CompoundValue, Concat, EntryPrice, FPL, Fundamental, GetValue, If, TickSize, TickValue, GetSymbol…` | [Others](https://toslc.thinkorswim.com/center/reference/thinkScript/Functions/Others) |

Plus a **constant taxonomy** used as enum-like first-class values
([Constants](https://toslc.thinkorswim.com/center/reference/thinkScript/Constants)):
`AggregationPeriod, Alert, AverageType, ChartType, Color, CrossingDirection, Curve,
Double (NaN/Infinity), EarningTime, Events, FiscalPeriod, FontSize, FundamentalType,
Location, NumberFormat, OptionClass, OrderType, PaintingStrategy, PricePerRow,
PriceType, ProfitLossMode, Sound`.

## 3. Strengths

1. **The series-by-default model is the killer feature.** Indicators read like
   math, not loops; recursion (EMA, cumulative, state machines) needs no
   scaffolding. This is the core to keep. (Ch 1, Ch 10, above.)
2. **Typed, GUI-serializable inputs with enum dropdowns** defined *in the code*
   (`input smoothingType = {Default SMA, EMA}`) — the study's parameter panel is
   generated from the script. (Ch 11; reserved word `input`.)
3. **Named, order-independent function arguments** make call sites self-documenting
   and refactor-safe. ([Functions index](https://toslc.thinkorswim.com/center/reference/thinkScript/Functions/Functions).)
4. **Orthogonal parameters on data access**: `symbol`, `period`, `priceType` on
   every fundamental makes cross-symbol and multi-timeframe formulas one-liners.
   (Ch 11, Ch 13.)
5. **A huge curated built-in library** — 300+ studies referenceable as functions,
   plus greeks, fundamentals, corporate actions — is what makes the small language
   productive. (Ch 13; overview page.)
6. **Honest execution details where it counts**: prefetch making EMAs
   range-independent; default strategy fills at next-bar open (`open[-1]`);
   the documented "IsNaN + future offset" last-bar idiom with warnings about
   `HighestAll`. (Ch 12, Ch 7.)
7. **Human-readable operator syntax** (`crosses above`, `from 2 bars ago`)
   demonstrably lowered the entry barrier for non-programmers. (Ch 10, Ch 6,
   reserved-words list.)
8. **NaN as a first-class "no value here" sentinel** integrated with painting
   strategies — gaps and conditional painting fall out naturally. (Appendix D;
   Constants.)

## 4. Warts

1. **If-expression has no short-circuit** — both branches always evaluate
   (officially documented). With recursion and NaN this silently changes results;
   users must know to reach for the if-*statement* for laziness.
   ([`if`](https://toslc.thinkorswim.com/center/reference/thinkScript/Reserved-Words/if).)
2. **The past offset is study-global, not per-expression**: the max lookback in
   any expression overrides the initialization point of every other expression,
   so a trivial counter starts at 11 because a sibling expression averages 11
   bars. Only `CompoundValue` carves out an independent init.
   ([Ch 12](https://toslc.thinkorswim.com/center/reference/thinkScript/tutorials/Advanced/Chapter-12---Past-Offset-and-Prefetch).)
3. **Aggregation context is tracked invisibly.** Mixing a secondary-period series
   with any primary-period datum silently demotes the whole expression to primary
   context; mixing two secondary periods in one expression is an outright error;
   some functions implicitly use fundamentals and drag context back. (Ch 11.)
4. **Silent zero-initialization of recursion.** `def x = x[1] + volume` "just works"
   because unobserved init rules inject 0 — convenient, but a correctness trap
   the user must actively fight with `CompoundValue`. (Ch 1, Ch 10.)
5. **Future data is one character away.** `[−1]` indexing and event functions make
   look-ahead trivially expressible, and the language leaves repaint detection to
   the user. The community's most-viewed FAQ topic is repainting: pivots/zigzags
   and fold+`Highest`/`Lowest` scripts rewrite history; the standing advice is to
   signal on the previous bar / next-bar open. Schwab documents the mechanics
   (Ch 12); the community documents the damage:
   [useThinkScript — Answers to Commonly Asked Questions](https://usethinkscript.com/threads/answers-to-commonly-asked-questions.6006/).
6. **`HighestAll`-style whole-history dependence** is legal but changes the
   recalculation mode and performance profile of the entire study — a global
   side effect from a scalar-looking call. (Ch 12 warning.)
7. **No arrays, no user functions, no libraries.** `fold` is the only loop;
   `script` blocks are the only subroutine; user studies **cannot reference other
   user studies** (official restriction), so the ecosystem copy-pastes code.
   (Ch 13; `fold` page.)
8. **Weak string/formatting model**: `Concat` and `AsText`-family formatting are
   about it; no string operations beyond that. (Others section.)
9. **Booleans are numerics** — flexible (sums of conditions) but error-prone
   (no type errors for truthiness mistakes). (Ch 1.)
10. **Strategies are hypothetical only** — `AddOrder` draws arrows and a P/L
    report but cannot reach the order pipe. Good for safety, but it means the
    language's strategy surface and its trading surface are different worlds.
    (Ch 7.)
11. **Recalculation semantics are implicit and performance-coupled**: default is
    per-tick; `once_per_bar` and whole-history references change it, and the
    docs concede output can change "in an unwanted way". (Ch 12;
    `once_per_bar` declaration.)

## 5. Implications for a V2 language

For the #326 "V2 scripting language semantics" decision (ThinkScript-inspired DSL
vs Pine vs embedded interpreter), this study argues:

### What to copy

- **Series-by-default execution model** with `[n]` history indexing and first-class
  recursion — proven, concise, and the reason thinkScript feels native to traders.
  V2 should make it explicit in the type system: values carry a *bar context*
  (frame/period), and history access is an operator on that context.
- **Typed inputs with in-code GUI metadata** (enum dropdowns with defaults) —
  the script is its own config schema. This maps cleanly onto a Rust-typed
  parameter struct.
- **Named, order-independent arguments** for all built-ins.
- **The eleven-family built-in taxonomy** as the organizing scheme for V2's
  function library, and "study-as-function" referencing so the built-in library
  is user-extensible *by composition*, not copy-paste.
- **Orthogonal `symbol`/`period` parameters on data access** — but made explicit
  (see below).
- **NaN-as-sentinel painting semantics**, prefetch-style deterministic
  warm-up conventions, and the next-bar-open fill default for strategy semantics
  (aligns with V1's no-lookahead rule: prior-bar decisions, current-bar fills).

### What to drop or fix

- **Both-branch if-expressions**: V2 should evaluate lazily, or expose laziness
  explicitly (e.g. separate `select` vs `if`). This is thinkScript's most
  documented semantic trap.
- **Global past offset**: make lookback a *per-expression* property (a window
  type, or inferred per-binding with per-binding initialization), so expressions
  don't steal each other's initialization points.
- **Implicit context demotion**: aggregation mixing should be an explicit
  `resample()`/`align()` step, or a compile error — never a silent primary-context
  fallback.
- **Magic-zero recursion init**: require an initializer (e.g. `series x = 0 then
  x[1] + volume`), keeping `CompoundValue` semantics as the general form.
- **Negative-index future access by default**: make look-ahead an explicit,
  loudly-marked construct (a `future` window) so repaint hazards are auditable —
  the single biggest community footgun.
- **Numerics-as-booleans**: keep numeric compatibility if desired, but give
  conditions a distinct type in the checker.

### Open design questions for the scripting-language lock ticket

1. **Execution target**: interpreted AST vs compiled (to Rust/wasm) — thinkScript
   gives no signal here (closed client), but its per-tick vs once-per-bar split
   says V2 needs an explicit, user-visible recalculation contract from day one.
2. **How far does the language go toward order flow?** thinkScript deliberately
   stops at hypothetical signals; V2 is a live trading platform, so the DSL needs
   a boundary: signal emission vs. order placement (probably a separate, typed
   surface rather than `AddOrder`-style side effects).
3. **Multi-timeframe data model**: eagerly materialized resampled frames vs lazy
   aligned reads — decides whether context tracking can be static (types) or
   must stay dynamic (thinkScript's runtime context demotion).
4. **Study state across sessions**: recursion state (EMA, position-of-mind state)
   must be addressable/checkpointable for live-restart parity — thinkScript has
   no answer because studies are throwaway per-chart.
5. **Module/library story**: user studies referencing user studies (the thing
   thinkScript bans) — what's the namespacing and versioning model?
6. **Backtest/live parity**: same engine for both, so the next-bar-open fill and
   once-per-bar/tick semantics are properties of the *data model*, not of the
   chart widget (thinkScript's is coupled to the chart).
7. **Determinism & warm-up**: adopt prefetch-style "range-independent" warm-up
   conventions as a norm (declare required warm-up length per indicator) so
   values don't depend on how much history the caller loaded.

---

*Provenance note: all Schwab Learning Center pages fetched 2026-10-07 from
`toslc.thinkorswim.com`. No decompiled-jar cross-check was performed (no `tos-suit`
jar found on this machine); the grammar section is therefore documentation-derived
and any V2 grammar decision should re-verify against the dissection tickets'
payload findings when those land. No numeric claims about V1 or thinkScript
performance were made.*
