NAME = "mom_k10_pos"
def entry(ctx):
    out = {}
    for sym in ctx.symbols:
        m = ctx.mom(sym, 10)
        if m is not None and m > 0:
            out[sym] = 1.0
    return out
