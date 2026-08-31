NAME = "mr_fade_ma20"
def entry(ctx):
    out = {}
    for sym in ctx.symbols:
        m = ctx.ma(sym, 20)
        c = ctx.close(sym)
        if m and c and (c - m) / m < -0.015:
            out[sym] = 1.0
    return out
