NAME = "mr_fade_carry"
# Hypothesis (gym decides): the c04 fade works better with POSITIVE carry —
# longs you are PAID to hold (base policy rate above quote) decay less and
# have trend-crowd support; skip fades where carry < 0. Coverage is honest:
# carry is only computable where both policy-rate legs exist (US/EUR/GBP/CA
# rate series, ToC BM3); uncovered pairs and uncovered dates are skipped,
# not traded unfiltered.

def entry(ctx):
    out = {}
    for sym in ctx.symbols:
        m = ctx.ma(sym, 20)
        c = ctx.close(sym)
        if not (m and c and (c - m) / m < -0.015):
            continue
        car = ctx.exog("CARRY:" + sym)
        if car is None:
            continue
        if car < 0:
            continue
        out[sym] = 1.0
    return out
