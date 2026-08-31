NAME = "ma_pullback"
def entry(ctx):
    out = {}
    for sym in ctx.symbols:
        ma10 = ctx.ma(sym, 10)
        ma50 = ctx.ma(sym, 50)
        c = ctx.close(sym)
        if ma10 and ma50 and c and ma10 > ma50 and c > ma10:
            out[sym] = 1.0
    return out
