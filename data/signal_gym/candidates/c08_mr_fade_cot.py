NAME = "mr_fade_ma20_cot"
# Hypothesis under test (gym decides, not vibes): the c04 mean-reversion fade
# fails when entering would mean JOINING a crowded speculator position. Crowd
# = CFTC leveraged-money net positioning (scripts/fetch_exog.py), z-scored.
# exposure sign: +1 when buying the pair means long the COT currency (EUR_USD
# -> long EUR), -1 when it means short it (USD_JPY -> short JPY). Skip the
# fade when sign * z > CROWD (i.e., we would be buying alongside a crowded
# book). Crosses and pairs without a COT series are honestly skipped, not
# traded unfiltered.

CROWD = 1.5
EXPOSURE = {
    "EUR_USD": ("EUR", +1), "GBP_USD": ("GBP", +1), "AUD_USD": ("AUD", +1),
    "USD_JPY": ("JPY", -1), "USD_CHF": ("CHF", -1), "USD_CAD": ("CAD", -1),
}


def entry(ctx):
    out = {}
    for sym in ctx.symbols:
        if sym not in EXPOSURE:
            continue
        m = ctx.ma(sym, 20)
        c = ctx.close(sym)
        if not (m and c and (c - m) / m < -0.015):
            continue
        cur, sign = EXPOSURE[sym]
        z = ctx.exog("COT:" + cur)
        if z is None:
            continue
        if sign * z > CROWD:
            continue
        out[sym] = 1.0
    return out
