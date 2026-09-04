NAME = "carry_regime_breakout"

def entry(ctx):
    """
    Hypothesis: In a high US rate regime (above its recent 90-day mean), long 
    USD-pair breakouts (close above 20-day high) are more likely to continue 
    when the pair has positive carry for the base currency (i.e., long the 
    base vs USD pays positive carry). High rates = risk-off / dollar strength, 
    but carry compensates for holding the base currency through the breakout.
    
    Different from all prior: combines absolute rate level regime with 
    breakout + carry filter, whereas c05 was pure breakout, p01 was MA-break 
    with carry, and p02 was mom with carry (but not breakout/level regime).
    """
    # Only consider USD-quoted pairs where exog carry is available
    symbols = ctx.symbols
    result = {}
    
    # Get 20-day high for each symbol (using ma as a proxy for recent level)
    for sym in symbols:
        close = ctx.close(sym)
        if close is None:
            continue
            
        # 20-day mean as proxy for recent range center (can't get high directly)
        ma20 = ctx.ma(sym, 20)
        atr14 = ctx.atr(sym, 14)
        if ma20 is None or atr14 is None:
            continue
            
        # Breakout: close > ma20 + 1.5 * atr (simulates 20-day high break)
        if close <= ma20 + 1.5 * atr14:
            continue
            
        # Get carry for this pair (base vs USD)
        carry = ctx.exog(f"CARRY:{sym}")
        if carry is None:
            continue
            
        # US rate level regime: above 3.5% = high-rate regime (USD strength)
        us_rate = ctx.exog("RATE:US")
        if us_rate is None or us_rate < 3.5:
            continue
            
        # Only take if positive carry (long base earns positive carry)
        if carry > 0:
            result[sym] = 1.0
    
    # Top-2 by weight would be selected by engine; we return all candidates
    return result
