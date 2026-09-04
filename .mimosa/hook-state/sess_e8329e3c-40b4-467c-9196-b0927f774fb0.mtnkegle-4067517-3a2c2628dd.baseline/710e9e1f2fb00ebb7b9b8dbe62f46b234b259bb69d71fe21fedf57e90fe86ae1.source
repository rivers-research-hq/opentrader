NAME = "regime_mom_k10"
def entry(ctx):
    out = {}
    for sym in ctx.symbols:
        m = ctx.mom(sym, 10)
        ma50_now = ctx.ma(sym, 50)
        c = ctx.close(sym)
        if m is not None and m > 0 and ma50_now and c and c > ma50_now:
            out[sym] = 1.0
    return out
