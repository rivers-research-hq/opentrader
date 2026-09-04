NAME = "carry_break_ma20"

def entry(ctx):
    # Hypothesis: When a pair has positive carry, a break below the 20-bar MA
    # is a continuation signal (long), not a fade — trend follows liquidity flow.
    # This differs from c09 (fade with positive carry) by taking the BREAKOUT direction
    # instead of fading back to the mean.
    
    weights = {}
    
    for sym in ctx.symbols:
        close = ctx.close(sym)
        ma20 = ctx.ma(sym, 20)
        carry = ctx.exog(f"CARRY:{sym}")
        
        if close is None or ma20 is None or carry is None:
            continue
        
        # Long only when price closes below MA20 and carry is positive
        if close < ma20 and carry > 0:
            weights[sym] = 1.0
    
    return weights
