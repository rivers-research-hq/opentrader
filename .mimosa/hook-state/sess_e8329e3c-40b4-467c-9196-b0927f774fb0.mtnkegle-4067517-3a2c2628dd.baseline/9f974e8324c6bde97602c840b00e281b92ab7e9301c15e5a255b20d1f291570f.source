NAME = "carry_mom_filter"

def entry(ctx):
    # Hypothesis: Positive carry pairs with positive momentum have higher probability of continuation
    # than momentum alone. When carry is positive AND short-term momentum is positive, the pair is
    # attractive. When carry is negative, momentum signals are unreliable due to carry drag.
    # This differs from p01 (carry_break_ma20) which uses carry with MA breakout, and from c01-c03
    # pure momentum without carry conditioning.
    
    candidates = {}
    
    for sym in ctx.symbols:
        # Get momentum (5-day) as a fast signal
        mom5 = ctx.mom(sym, 5)
        if mom5 is None:
            continue
        
        # Get carry for this pair
        carry = ctx.exog(f"CARRY:{sym}")
        if carry is None:
            continue
        
        # Only consider pairs with positive carry (long side earns interest)
        if carry <= 0:
            continue
        
        # Only consider pairs with positive short-term momentum
        if mom5 <= 0:
            continue
        
        # Additional filter: today's close should be above 20-day MA for trend confirmation
        ma20 = ctx.ma(sym, 20)
        close = ctx.close(sym)
        if ma20 is None or close is None:
            continue
        
        if close <= ma20:
            continue
        
        # Weight by strength of carry * momentum combo
        weight = min(1.0, abs(mom5) * 0.5 + carry * 0.1)
        candidates[sym] = weight
    
    # Return top 2 by weight (engine picks top-2)
    if len(candidates) <= 2:
        return candidates
    
    # Sort by weight descending, take top 2
    sorted_pairs = sorted(candidates.items(), key=lambda x: x[1], reverse=True)[:2]
    return dict(sorted_pairs)
