# Factor-Sign Regime Persistence: What the Literature Says

**Research note — read-only, no code changes.**
**Context:** exogenous regime-conditioned trading signals for a large equity dataset, 1996–2026, in three eras (~1996–2005, 2005–2015, 2015–2026). Tested gates: term spread (T10Y2Y), credit spread (BAA-AAA), dollar (DTWEXBGS), fed funds, commodities, VIX. Findings to explain: (a) VIX is stable-direction across eras (high-vol days → better score-tail returns in all eras); (b) term spread and credit spread are significant under date-clustered bootstrap but **flip sign between eras**; (c) a composite with rolling sign-estimation is significant only in the most recent era.

**Method:** every claim below was checked against its primary source (journal page, NBER working-paper page, publisher abstract, or the author-hosted full text). Claims marked [abstract] are verified against the paper's own abstract; [text] against the full text (downloaded and grepped); [survey] against the quoted survey's text. Full citations with DOIs in the References section.

---

## 1. What the literature says about the persistence of factor-sign regimes

### 1.1 The classical baseline: stable positive signs (1941–1987)

- **Fama & French (1989), "Business Conditions and Expected Returns on Stocks and Bonds," JFE 25, 23–49** [abstract]: expected returns on stocks and long-term bonds carry a term/maturity premium with a clear business-cycle pattern — "low near peaks, high near troughs" — plus a risk premium tied to longer-term business conditions, "stronger for low-grade bonds than for high-grade bonds and stronger for stocks than for bonds." In that 1941–87 sample, high term spreads and high default spreads forecast *higher* subsequent equity and bond returns (countercyclical risk premia). This is the canonical "inverted curve / wide spreads ⇒ cheap equities, high forward returns" result — i.e., the classic *risk-on* sign for spreads.

- **Cochrane (2011), "Presidential Address: Discount Rates," JF 66(4), 1047–1108** [abstract]: all price-dividend variation is discount-rate variation; expected returns vary strongly over time. But the predictability is concentrated at **longer horizons** (multi-year), which matters when we ask whether the same relations exist at daily-to-monthly frequencies.

### 1.2 The instability evidence: signs and strengths are not stable (1990s onward)

- **Welch & Goyal (2008), "A Comprehensive Look at the Empirical Performance of Equity Premium Prediction," RFS 21(4), 1455–1508** [abstract, NBER WP 10483]: of the full suite of textbook predictors (including interest rates "in various guises" and valuation ratios), **not one would have helped an investor outpredict the historical equity-premium mean out of sample; most would have outright hurt.** "For all practical purposes, the equity premium has not been predictable." This is the strongest single statement that in-sample macro→equity relations (which often show stable in-sample signs) do not survive out of sample.

- **Ang & Timmermann (2012), "Regime Changes and Financial Markets," Annual Review of Financial Economics 4, 313–337** [survey text, NBER WP 17182]: "The strength of this predictability… has varied considerably over time. **The predictable power of many instruments used in the literature to predict excess aggregate equity returns, like dividend yields, term spreads, and default spreads, declined or even disappeared over the 1990s** as documented by Welch and Goyal (2008) and Ang and Bekaert (2007), among others, and formally tested by Pesaran and Timmermann (2002)." This is a direct, authoritative statement that **term spread and default spread predictive content for equity returns is regime-dependent — strong in some eras, gone in others.** Your sign flip is exactly this phenomenon, not an anomaly.

- **Ang & Bekaert (2007), "Stock Return Predictability: Is it There?," RFS 20(3), 651–707** [text, final version]: in US and international data, the short rate is the only *robust* short-horizon predictor; dividend-yield predictability is fragile, does not survive finite-sample corrections, and long-horizon predictability largely disappears. (Note: the widely-cited "predictability concentrated in a high-volatility regime" finding is actually **Henkel, Martin & Nardari (2011)** — see §1.5; the published Ang-Bekaert paper's own abstract does not claim it.)

- **Paye & Timmermann (2006), "Instability of Return Prediction Models," J. Empirical Finance 13(2), 125–149**: predictive regression coefficients for aggregate stock returns are unstable over time, with estimated break dates clustering around identifiable macro episodes. (Cited for instability in Ang-Timmermann 2012 [survey text]; title/venue/date verified.)

- **Rapach & Wohar (2006), "Structural Breaks and Predictive Regression Models of Aggregate U.S. Stock Returns," J. Financial Econometrics 4(2), 112–138** [abstract]: of eight bivariate predictive regressions (S&P 500, quarterly 1946–2004), **five display strong evidence of structural breaks**; and "when we estimate the predictive regression models over the different regimes defined by structural breaks, **we find that the predictive ability of financial variables can vary markedly over time.**" Direct support for era-dependent sign/strength.

- **Pesaran & Timmermann (2002), "Market Timing and Return Prediction Under Model Instability," J. Empirical Finance 9(1), 65–91** [text]: formalizes the problem — "the literature on predictability of stock returns almost uniformly assumes a time-invariant relationship between state variables and returns," which is rejected by data. They estimate **three major breaks** in a US stock-return forecasting model (1954–1998) and show a constant-parameter model would have "predicted **negative excess returns during the second half of the nineties** (a period with unusually high mean returns)" — a concrete, documented sign-flip of a predictor relative to realized returns. This is the closest published analogue to your term/credit sign flips.

### 1.3 Term structure: the *macro* content is robust, the *equity-sign* content is not

- **Estrella & Mishkin (1998), "Predicting U.S. Recessions: Financial Variables as Leading Indicators," REStat 80(1), 45–61** [abstract]: in out-of-sample tests one to eight quarters ahead, "**the slope of the yield curve emerges as the clear individual choice**" for predicting recessions. Note what is robust: the *negative-slope ⇒ recession* relation for the real economy. The equity-return *sign* of that same variable is a different, weaker object (see §1.2).

- **Ang, Piazzesi & Wei (2006), "What Does the Yield Curve Tell Us About GDP Growth?," J. Econometrics 131(1–2), 359–403**: the term structure (short rate + slope) contains significant predictive content for GDP growth. (Title/venue verified; cited for the broad robustness of term-structure → growth, not → equity returns.)

- **Estrella, Rodrigues & Schich (2003), "How Stable Is the Predictive Power of the Yield Curve?," REStat 85(3), 654–664** [abstract]: even the yield-curve→growth relation "may not be stable over time"; formal break tests find instability. So even the *most robust* macro use of the term spread is era-dependent; the equity-sign version (yours) sits well downstream of this.

**Implication for Q1:** the literature does **not** treat term-spread and credit-spread → equity-return relations as sign-stable. The stable-sign results (Fama-French 1989) are from a 1941–87 sample; from the 1990s on, predictability "declined or even disappeared" (Ang-Timmermann 2012), OOS performance is at or below the historical mean (Welch-Goyal 2008), and formal break tests find instability in a majority of predictive models (Rapach-Wohar 2006; Pesaran-Timmermann 2002; Paye-Timmermann 2006). **Your result — significant within eras, flipping sign between eras — is the literature's expected outcome, not an anomaly.**

### 1.4 Credit spreads: robust content for *activity*, unstable sign for *equity returns*

- **Gilchrist & Zakrajšek (2012), "Credit Spreads and Business Cycle Fluctuations," AER 102(4), 1692–1720** [abstract]: their micro-data credit-spread index "has considerable predictive power for **future economic activity**," and shocks to the **excess bond premium** (the part of the spread not explained by expected defaults) "lead to declines in… economic activity." Robust direction: wider spreads ⇒ worse activity. The paper does **not** claim a stable sign for equity *returns*; the spread's activity content and its equity-sign content are different channels, and only the former is robust.

- **Philippon (2009), "The Bond Market's q," QJE 124(3), 1011–1056** [abstract]: credit spreads contain information about future *asset values/investment* (bond-market q "fits the investment equation six times better" than equity q). Again: real-side predictability, not a stable equity-return sign.

- **Martin (2017), "What Is the Expected Return on the Market?," QJE 132(1), 367–402** [text]: documents that conventional predictor variables "forecast returns with the **wrong sign**" relative to expectations, and reports **negative out-of-sample R²** for valuation-ratio predictors of −2.06%, −1.93%, −1.78%, −1.72% (full sample) and **−15.14% to −29.31% in the 1976–2005 subsample**. High spreads (a classic "cheap equity" signal) coincided with flat-to-negative subsequent equity returns in several post-2000 episodes; the sign of spread→return relations is empirically unstable.

**Implication:** credit spreads are a *robust* leading indicator of the real economy (GZ 2012; Philippon 2009) but the literature contains no stable sign result mapping spreads to near-horizon equity returns; the strongest evidence (Welch-Goyal 2008; Martin 2017; Rapach-Wohar 2006) says the equity-side relation is weak and time-varying. Your BAA-AAA flip between eras is consistent with this.

### 1.5 Regime-switching models: predictability is real but regime-concentrated

- **Hamilton (1989), "A New Approach to the Economic Analysis of Nonstationary Time Series and the Business Cycle," Econometrica 57(2), 357–384** [abstract]: occasional discrete shifts between a positive-growth and a negative-growth state are a "recurrent feature of the U.S. business cycle"; regimes are persistent states with a 3% permanent drop in GNP per recession. This is the canonical framework for regime-conditioned estimation.

- **Ang & Bekaert (2002), "International Asset Allocation with Regime Shifts," RFS 15(4), 1137–1167** [abstract]: return correlations and volatilities increase in bad (bear) regimes; the "bad regime is persistent" [survey text, Ang-Timmermann 2012: "this bad regime is persistent so a draw from this regime makes a draw next period from the same regime more likely"]; costs of ignoring regimes are small for all-equity portfolios but grow when a conditionally risk-free asset is held.

- **Henkel, Martin & Nardari (2011), "Time-Varying Short-Horizon Predictability," JFE 99(3), 560–580** [finding as described in Ang-Timmermann 2012 survey text; title/venue verified]: in a regime-switching VAR, **"predictability is very weak during business cycle expansions but is very strong during recessions… the regime switching model captures this counter-cyclical predictability by exhibiting significant predictability only in the contraction regime."** This is the single most relevant published analogue to your VIX result: the conditioning variable that matters is the *risk/volatility state*, and the effect is stable in direction across eras.

- **Bollerslev, Tauchen & Zhou (2009), "Expected Stock Returns and Variance Risk Premia," RFS 22(11), 4463–4492** [abstract]: the variance risk premium predicts aggregate returns at short horizons — "high (low) premia predicting high (low) future returns" — i.e., high-implied-vol/risk-off states are followed by higher returns. Same direction as your VIX finding.

- **Martin (2017)** [text]: option-implied vol (SVIX) implies an equity premium that "rose above 20% at the height of the crisis in 2008"; "high equity premia available at times of stress largely reflect high expected returns **over the very short run**." Direct support for a *vol-gate* conditioning variable with stable sign.

- **Tu (2010), "Is Regime Switching in Stock Returns Important in Portfolio Decisions?," Management Science 56(11), 2033–2052** [abstract]: ignoring regimes costs "certainty-equivalent losses… generally above 2% per year and… as high as 10%" — but the gains come mainly through better covariance/volatility structure, a nuance consistent with regime models mattering most in the vol dimension.

### 1.6 Factor-timing literature: the honest position from practitioners and academics

- **Asness (2016), "The Siren Song of Factor Timing," JPM 42(3)** [text, AQR's own page]: "I think that siren song should be resisted… At least when using the simple 'value' of the factors themselves, I find such timing strategies to be **very weak historically**, and some tests of their long-term power to be exaggerated and/or inapplicable." The canonical practitioner statement: factor timing mostly fails.

- **Haddad, Kozak & Santosh (2020), "Factor Timing," RFS 33(5), 1980–2018** [abstract, NBER WP 26708]: "**Market-neutral equity factors are strongly and robustly predictable**. Exploiting this predictability leads to substantial improvement in portfolio performance relative to static factor investing." The important nuance: their predictability comes from imposing SDF restrictions on the *dynamics of expected returns* — effectively slow-moving, price-based signals — **not** from macro variables. Macro-variable timing of factors is exactly what the literature finds weak.

- **McLean & Pontiff (2016), "Does Academic Research Destroy Stock Return Predictability?," JF 71(1), 5–32** [journal page]: across 97 published cross-sectional predictors, portfolio returns are **26% lower out-of-sample** and **58% lower after publication**. Predictability decays as soon as it is measured in fresh data — a general prior against any in-sample-discovered regime signal.

**Q1 answer, in one paragraph:** The literature says term- and credit-spread predictive relations with *equity returns* are regime-dependent in strength and sign, with stability documented only in early samples (Fama-French 1989) and instability, decline, or disappearance documented thereafter (Welch-Goyal 2008; Ang-Timmermann 2012; Rapach-Wohar 2006; Pesaran-Timmermann 2002; Paye-Timmermann 2006). Sign-flipping across multi-year eras is the documented norm, not an anomaly. What *is* stable in sign across eras is the **volatility/risk-state channel** (Henkel-Martin-Nardari 2011; Bollerslev-Tauchen-Zhou 2009; Martin 2017) — matching your VIX result, and contradicting nothing.

---

## 2. How persistent are regimes at 1–3 month horizons?

**What is persistent: the volatility/risk state.**
- Regime-switching estimates find a highly persistent "bad" state: volatility and correlation regimes persist for many periods, with persistence governed by transition probabilities p₀₀, p₁₁ — "the new behavior of financial variables often persists for several periods after such a change" and regimes "often correspond to different periods in regulation, policy, and other secular changes" (Ang-Timmermann 2012 [survey text]). Hamilton's (1989) two-state model of the business cycle [abstract] has the same structure, with regimes lasting many months.
- The **great moderation** literature quantifies era-length persistence at the macro level: a structural break toward lower volatility at 1984:1 (Kim & Nelson 1999 [abstract]); GDP growth volatility fell from 2.7% (1960–83) to 1.6% (1984–2001), with no further breaks detected in that window (Stock & Watson 2002 [abstract]). So "eras" of a decade or more are real, statistically detectable objects in macro-financial dynamics.

**What is less persistent: the sign of macro→equity relations.**
- The sign instability evidence (§1.2) implies sign regimes that last *years* (the "declined or even disappeared over the 1990s" pattern; Pesaran-Timmermann 2002's three breaks in ~45 years). That means a causal learner would have ~2–3 sign observations per 30 years — the effective sample for learning a *sign regime* is tiny even though the regime itself is long.
- The one rigorous published test that break-aware, real-time sign estimation can *work* at monthly horizons: **Pesaran-Timmermann (2002)** [text]. Their two-stage procedure detects the most recent break in real time (reversed ordered Cusum) and re-estimates on post-break data; "we find evidence that the proportion of **correctly predicted signs** of US stock returns can be improved over unconditional methods that do not account for breaks such as expanding or rolling windows," and the method beats Bai-Perron's ex-post multi-break method in their OOS experiment. This is the strongest affirmative evidence that era-length persistence is long enough to be learned causally and traded — and note their procedure is exactly your "rolling sign estimation" done properly (one-sided, break-tested, window chosen by data rather than arbitrary era cuts).

**Q2 answer:** Yes — regime persistence at 1–3 month horizons is real and well-documented for the *volatility/risk* state (persistent, months-to-years, one-sided learnable: filtered regime probabilities are causal). The *sign* of term/credit relations is era-length but with very few observed switches, so it is learnable only with break-aware, real-time methods (PT 2002's ROC), not with arbitrary era labels; and the sign component is the weak link — the literature's predictive failures concentrate exactly there (Welch-Goyal 2008).

---

## 3. The honest out-of-sample bar

What the literature actually uses, and what it takes to "prove" an era classifier before trading:

1. **Direction-of-change tests.** Pesaran & Timmermann (1992), "A Simple Nonparametric Test of Predictive Performance," JBES 10(4), 461–473 [abstract]: distribution-free test for whether a forecast gets the *sign* of the change right more often than chance (with the extension for multi-category forecasts: Pesaran & Timmermann (2009), JASA 104(485), 78–90). This is the correct null for a gate that flips risk-on/risk-off.
2. **Equal-predictive-accuracy tests.** Diebold & Mariano (1995), JBES 13(3), 253–263, and West (1996), Econometrica 64(5), 1067–1084 (DM statistic with parameter-estimation correction); **Clark & West (2007)**, "Approximately Normal Tests for Equal Predictive Accuracy in Nested Models," J. Econometrics 138(1), 291–311 [abstract metadata]: the correct test when the benchmark is nested (your historical-mean/always-on benchmark), because standard DM under-rejects in nested comparisons.
3. **Out-of-sample R² against the historical mean.** The Welch-Goyal (2008) [abstract] OOS R² framework; Campbell & Thompson (2008), RFS 21(4), 1509–1531 [abstract]: predictors *can* beat the historical mean once theory-consistent sign restrictions are imposed, but "the out-of-sample explanatory power is small"; at monthly frequency the economically meaningful hurdle is small (order 0.5–1% monthly R²; best-in-class machine learning gets 0.16–1.8% monthly — Gu-Kelly-Xiu 2020, §4). Any claim of regime-gate value should be stated as monthly OOS R² or DM/PT p-values against the *always-trade* benchmark, not as in-era tail statistics.
4. **No-lookahead walk-forward.** Estimation must be one-sided (only data available at t): filtered regime probabilities, expanding/rolling windows that exclude future data, and *in-sample* break dates never used in trading decisions. The template is Pesaran-Timmermann (2002) [text] (real-time ROC break detection); the violation pattern is "in-sample era boundaries defined after seeing the data."
5. **Multiple-hypothesis and selection-bias corrections.** With 6 factors × 3 eras × multiple horizons × a handful of composite designs, you are data-snooping by construction:
   - Harvey, Liu & Zhu (2016), "…and the Cross-Section of Expected Returns," RFS 29(1), 5–68 [abstract]: "a new factor needs to clear a much higher hurdle, with a t-statistic greater than 3.0."
   - White (2000), "A Reality Check for Data Snooping," Econometrica 68(5), 1097–1126; Sullivan, Timmermann & White (1999), "Data-Snooping, Technical Trading Rule Performance, and the Bootstrap," JF 54(5), 1647–1691 [abstract]: after correcting for the full universe of tested rules (≈7,800 rules, 100 years of daily DJIA data), the best technical trading rules' apparent edge is no longer significant. Your date-clustered bootstrap is the right family of method (block/stationary bootstrap preserving dependence — the STW 1999 toolbox); the missing piece is that the *universe of tested designs* must enter the correction, not just one design.
   - Hansen (2005), "A Test for Superior Predictive Ability," JBES 23(4), 365–380 [abstract]: SPA test, more powerful than the Reality Check; and Bailey & López de Prado (2014), "The Deflated Sharpe Ratio," JPM 40(5), 94–107 [abstract]; Bailey, Borwein, López de Prado & Zhu (2014), "Pseudo-Mathematics and Financial Charlatanism," Notices of the AMS 61(5) [metadata]: backtest-overfitting corrections for strategy-selection bias.
6. **The era-classifier-specific power problem.** An "era" classifier has effectively **n ≈ 3 independent era observations** in your sample. No era-level statistic can be significant at n = 3. Tests must be run at the observation level (daily/monthly) with dependence-robust inference (date-clustered or block bootstrap — which you already do), and the era classifier's *sign estimates* must be validated only through the walk-forward path where each era's sign was estimated from data available before that era began. Also relevant: Pesaran & Timmermann (1992) note that chi-square-type independence tests are conservative in this setting; use the PT test directly.
7. **Publication-decay sanity check.** McLean & Pontiff (2016) [journal page]: expect ~26% OOS decay of any in-sample edge even before it is published; budget for it.

**Minimum battery that would convince the literature:** (i) one-sided walk-forward with real-time break/regime estimation (PT 2002 style); (ii) PT (1992/2009) sign tests and Clark-West (2007) tests against the always-trade benchmark; (iii) monthly OOS R² reported in Welch-Goyal/Campbell-Thompson form; (iv) multiple-testing correction across the full design universe (HLZ 2016 threshold, SPA/DSR); (v) bootstrap inference that respects time dependence (stationary/date-clustered bootstrap).

---

## 4. Honest prior on an era classifier for term/credit factors, daily-to-monthly

Anchors from the verified literature:

- **Best-in-class monthly equity-premium OOS R² is ~0.2–2%.** Gu, Kelly & Xiu (2020) [text]: linear benchmark 0.16%/month; elastic net 0.11%; PCR 0.26%; best trees/neural nets 0.33–0.40% at stock level and 1.08–1.80% for bottom-up S&P 500 forecasts. These are *huge* models with 900+ predictors; the signal-to-noise at monthly horizons is tiny.
- **Unconditional macro timing usually loses to the historical mean** (Welch-Goyal 2008 [abstract]); gains appear only with theory-imposed signs and are "small but economically meaningful" (Campbell-Thompson 2008 [abstract]).
- **Sign instability is the rule for term/credit** (§1.2): 5 of 8 predictive models have breaks (Rapach-Wohar 2006); term/default spread predictive power "declined or even disappeared" (Ang-Timmermann 2012); the most sophisticated OOS evaluations of conventional predictors are negative (Martin 2017: −1.7% to −29% OOS R² in 1976–2005).
- **But: break-aware sign estimation has one rigorous affirmative result** (Pesaran-Timmermann 2002 [text]: improved sign prediction OOS), and **regime-concentrated predictability in the risk/vol state is well established** (Henkel-Martin-Nardari 2011 via AT 2012; Bollerslev-Tauchen-Zhou 2009; Martin 2017).
- **Published predictability decays** (McLean-Pontiff 2016: 26% OOS, 58% post-publication); **factor timing with macro/fundamental signals is the weak variant** (Asness 2016 [text]; Haddad-Kozak-Santosh 2020 [abstract] — their robust timing is price/SDF-based, not macro-based).

**Prior:** low-to-moderate, and strongly asymmetric across the two components.
- **VIX/vol-state gate:** literature-supported direction and sign stability (risk-state channel), consistent across your three eras. Prior: moderate — worth prototyping, but note that "high vol ⇒ better forward returns" is a risk-premium bet, not free alpha; its value shows up in the tail/score distribution, exactly as you found.
- **Term/credit sign learning:** the literature's expectation is instability; the only affirmative evidence is PT 2002's real-time break method, and its gains were on 1954–1998 monthly data with three breaks. Prior for a *fixed-sign* era classifier: low. Prior for a *walk-forward, break-tested rolling-sign* classifier: low-to-moderate. Your composite's "significant only in the most recent era" is precisely the pattern OOS instability predicts for a signal whose last regime happens to be favorable — it is weak evidence, not confirmation.
- **Statistical prior from the design:** ~6 factors × 3 eras × several horizons ⇒ the multiple-testing hurdle (HLZ 2016: t>3; SPA/DSR) means most of your "95–100th percentile bootstrap" findings, even if real in-sample, should be expected to evaporate under correction — unless the VIX result survives, which the literature structure says is the one most likely to.

---

## 5. Verdict

**"Era classifier is worth prototyping" — but only in the narrow form the literature supports:**

1. **Vol-regime gate first (VIX / risk-state):** this is the component with stable-direction literature support (Henkel-Martin-Nardari 2011; Bollerslev-Tauchen-Zhou 2009; Martin 2017), matches your stable VIX finding, and is the documented place where predictability concentrates. A regime-switching overlay on the vol state (Hamilton-style filtered probabilities, one-sided) is the literature-standard implementation.
2. **Term/credit signs via real-time break detection, not era labels:** implement PT 2002's two-stage logic (detect the most recent break causally; estimate sign on post-break data; compare against expanding/rolling windows in walk-forward). This is the only published method with a positive OOS result for sign prediction under instability. Arbitrary era cuts estimated on full-sample data are the version the literature says fails.
3. **Evaluate against the honest bar (§3):** PT (1992) sign tests, Clark-West (2007), monthly OOS R² vs. always-trade, multiple-testing correction across the design universe, date-clustered bootstrap. Do not call an era classifier "working" on within-era significance; era-level n≈3 can never be significant.
4. **Calibrate expectations:** best-case monthly OOS R² from the literature is ~0.2–2% (Gu-Kelly-Xiu 2020); anything above that, found on this data, is suspicious rather than impressive.

**Why not "dead end":** the literature contains (a) one rigorous affirmative result for break-aware sign estimation (PT 2002), (b) strong, replicated evidence that predictability concentrates in persistent high-vol states (HMN 2011; BTZ 2009; Martin 2017) — which is exactly your stable VIX finding — and (c) no result saying regime conditioning *cannot* work at monthly horizons, only that naive fixed-sign macro timing fails OOS (WG 2008) and that sign instability is the norm (AT 2012; RW 2006).

**Why the prior is low, honestly:** the same literature says unconditional macro-based timing mostly loses to the historical mean; published edges decay by ~26–58%; factor timing that works (HKS 2020) is price-based, not macro-based; and your composite's significance appearing only in the most recent era is the signature of an unstable relation, not of a discovered one. The term/credit sign component is the least likely to survive; the vol-gate component is the most likely to survive but is a risk-premium tilt, not an edge.

Prototype: **vol-regime overlay (stable-direction, literature-backed) + PT-2002-style break-aware sign estimation for term/credit (the only affirmative-method variant) + the §3 test battery.** If the vol-gate survives the battery but the sign component does not, that outcome would itself be the literature-consistent result.

---

## References

All verified against primary sources on 2026-08-09 (NBER page/PDF, publisher abstract page, OpenAlex/Crossref record, or author-hosted full text).

1. Ang, A., & Bekaert, G. (2007). Stock Return Predictability: Is it There? *Review of Financial Studies*, 20(3), 651–707. doi:10.1093/rfs/hhl021
2. Ang, A., & Bekaert, G. (2002). International Asset Allocation with Regime Shifts. *Review of Financial Studies*, 15(4), 1137–1167. doi:10.1093/rfs/15.4.1137
3. Ang, A., Piazzesi, M., & Wei, M. (2006). What Does the Yield Curve Tell Us About GDP Growth? *Journal of Econometrics*, 131(1–2), 359–403. doi:10.1016/j.jeconom.2005.01.032
4. Ang, A., & Timmermann, A. (2012). Regime Changes and Financial Markets. *Annual Review of Financial Economics*, 4, 313–337. (NBER WP 17182). doi:10.3386/w17182
5. Asness, C. S. (2016). The Siren Song of Factor Timing. *Journal of Portfolio Management*, 42(3). doi:10.2139/ssrn.2763956 (text from AQR's site)
6. Bailey, D. H., & López de Prado, M. (2014). The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting, and Non-Normality. *Journal of Portfolio Management*, 40(5), 94–107. doi:10.3905/jpm.2014.40.5.094
7. Bailey, D. H., Borwein, J. M., López de Prado, M., & Zhu, Q. J. (2014). Pseudo-Mathematics and Financial Charlatanism: The Effects of Backtest Overfitting on Out-of-Sample Performance. *Notices of the AMS*, 61(5), 458–471. doi:10.1090/noti1105
8. Bollerslev, T., Tauchen, G., & Zhou, H. (2009). Expected Stock Returns and Variance Risk Premia. *Review of Financial Studies*, 22(11), 4463–4492. doi:10.1093/rfs/hhp008
9. Campbell, J. Y., & Thompson, S. B. (2008). Predicting Excess Stock Returns Out of Sample: Can Anything Beat the Historical Average? *Review of Financial Studies*, 21(4), 1509–1531. doi:10.1093/rfs/hhm055
10. Clark, T. E., & West, K. D. (2007). Approximately Normal Tests for Equal Predictive Accuracy in Nested Models. *Journal of Econometrics*, 138(1), 291–311. doi:10.1016/j.jeconom.2006.05.023
11. Cochrane, J. H. (2011). Presidential Address: Discount Rates. *Journal of Finance*, 66(4), 1047–1108. doi:10.1111/j.1540-6261.2011.01671.x
12. Diebold, F. X., & Mariano, R. S. (1995). Comparing Predictive Accuracy. *Journal of Business & Economic Statistics*, 13(3), 253–263. doi:10.1080/07350015.1995.10524599
13. Duarte, F., & Rosa, C. (2015). The Equity Risk Premium: A Review of Models. *FRB NY Staff Report 714*. doi:10.2139/ssrn.2646037
14. Estrella, A., & Mishkin, F. S. (1998). Predicting U.S. Recessions: Financial Variables as Leading Indicators. *Review of Economics and Statistics*, 80(1), 45–61. doi:10.1162/003465398557320
15. Estrella, A., Rodrigues, A. P., & Schich, S. (2003). How Stable Is the Predictive Power of the Yield Curve? Evidence from Germany and the United States. *Review of Economics and Statistics*, 85(3), 654–664. doi:10.1162/003465303322369777
16. Fama, E. F., & French, K. R. (1989). Business Conditions and Expected Returns on Stocks and Bonds. *Journal of Financial Economics*, 25(1), 23–49. doi:10.1016/0304-405X(89)90095-0
17. Gilchrist, S., & Zakrajšek, E. (2012). Credit Spreads and Business Cycle Fluctuations. *American Economic Review*, 102(4), 1692–1720. doi:10.1257/aer.102.4.1692
18. Gu, S., Kelly, B., & Xiu, D. (2020). Empirical Asset Pricing via Machine Learning. *Review of Financial Studies*, 33(5), 2223–2273. doi:10.1093/rfs/hhaa009
19. Haddad, V., Kozak, S., & Santosh, S. (2020). Factor Timing. *Review of Financial Studies*, 33(5), 1980–2018. (NBER WP 26708). doi:10.1093/rfs/hhaa017
20. Hamilton, J. D. (1989). A New Approach to the Economic Analysis of Nonstationary Time Series and the Business Cycle. *Econometrica*, 57(2), 357–384. doi:10.2307/1912559
21. Hansen, P. R. (2005). A Test for Superior Predictive Ability. *Journal of Business & Economic Statistics*, 23(4), 365–380. doi:10.1198/073500105000000063
22. Harvey, C. R. (2017). Presidential Address: The Scientific Outlook in Financial Economics. *Journal of Finance*, 72(4), 1399–1443. doi:10.1111/jofi.12530
23. Harvey, C. R., Liu, Y., & Zhu, C. (2016). …and the Cross-Section of Expected Returns. *Review of Financial Studies*, 29(1), 5–68. doi:10.1093/rfs/hhv059
24. Henkel, S. J., Martin, J. S., & Nardari, F. (2011). Time-Varying Short-Horizon Predictability. *Journal of Financial Economics*, 99(3), 560–580. doi:10.1016/j.jfineco.2010.09.008
25. Kim, C.-J., & Nelson, C. R. (1999). Has the U.S. Economy Become More Stable? A Bayesian Approach Based on a Markov-Switching Model of the Business Cycle. *Review of Economics and Statistics*, 81(4), 603–609. doi:10.1162/003465399558472
26. Martin, I. (2017). What Is the Expected Return on the Market? *Quarterly Journal of Economics*, 132(1), 367–402. doi:10.1093/qje/qjw034
27. McLean, R. D., & Pontiff, J. (2016). Does Academic Research Destroy Stock Return Predictability? *Journal of Finance*, 71(1), 5–32. doi:10.1111/jofi.12365
28. Paye, B. S., & Timmermann, A. (2006). Instability of Return Prediction Models. *Journal of Empirical Finance*, 13(2), 125–149. doi:10.1016/j.jempfin.2005.11.001
29. Pesaran, M. H., & Timmermann, A. (1992). A Simple Nonparametric Test of Predictive Performance. *Journal of Business & Economic Statistics*, 10(4), 461–473. doi:10.1080/07350015.1992.10509922
30. Pesaran, M. H., & Timmermann, A. (2002). Market Timing and Return Prediction Under Model Instability. *Journal of Empirical Finance*, 9(1), 65–91. doi:10.1016/S0927-5398(02)00007-5 (text from author copy, econ.ucsd.edu/~atimmerm)
31. Pesaran, M. H., & Timmermann, A. (2009). Testing Dependence Among Serially Correlated Multicategory Variables. *Journal of the American Statistical Association*, 104(485), 78–90. doi:10.1198/jasa.2009.0113
32. Philippon, T. (2009). The Bond Market's q. *Quarterly Journal of Economics*, 124(3), 1011–1056. doi:10.1162/qjec.2009.124.3.1011
33. Rapach, D. E., & Wohar, M. E. (2006). Structural Breaks and Predictive Regression Models of Aggregate U.S. Stock Returns. *Journal of Financial Econometrics*, 4(2), 238–274. doi:10.1093/jjfinec/nbj008
34. Stock, J. H., & Watson, M. W. (2002). Has the Business Cycle Changed and Why? *NBER Working Paper 9127*. doi:10.3386/w9127
35. Sullivan, R., Timmermann, A., & White, H. (1999). Data-Snooping, Technical Trading Rule Performance, and the Bootstrap. *Journal of Finance*, 54(5), 1647–1691. doi:10.1111/0022-1082.00163
36. Tu, J. (2010). Is Regime Switching in Stock Returns Important in Portfolio Decisions? *Management Science*, 56(11), 2033–2052. doi:10.1287/mnsc.1100.1181
37. Welch, I., & Goyal, A. (2008). A Comprehensive Look at the Empirical Performance of Equity Premium Prediction. *Review of Financial Studies*, 21(4), 1455–1508. (NBER WP 10483). doi:10.1093/rfs/hhm014
38. West, K. D. (1996). Asymptotic Inference About Predictive Ability. *Econometrica*, 64(5), 1067–1084. doi:10.2307/2171956
39. White, H. (2000). A Reality Check for Data Snooping. *Econometrica*, 68(5), 1097–1126. doi:10.1111/1468-0262.00152
