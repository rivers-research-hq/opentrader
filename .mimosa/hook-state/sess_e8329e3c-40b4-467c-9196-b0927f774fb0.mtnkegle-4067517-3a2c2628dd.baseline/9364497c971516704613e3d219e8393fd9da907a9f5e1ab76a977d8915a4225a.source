NAME = "breakout_20"
def entry(ctx):
    out = {}
    for sym in ctx.symbols:
        c = ctx.close(sym)
        highs = []
        for j in range(1, 21):
            px = ctx.series.get(sym, {}).get(ctx.dates[ctx.i - j]) if ctx.i - j >= 0 else None
            if px:
                highs.append(px[1])
        if c and highs and c > max(highs):
            out[sym] = 1.0
    return out
