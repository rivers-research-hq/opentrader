"""Baseline candidate policies for the paper-only FX shadow arena."""


def momentum(row):
    f = row["features"]
    x = float(f.get("mom_20d", 0.0))
    return {"action": "BUY" if x > 0 else "SELL", "conviction": min(abs(x), 1.0)}


def macro_guarded_momentum(row):
    f = row["features"]
    x = float(f.get("mom_20d", 0.0))
    vix = float(f.get("fred_vix_z", 0.0))
    oil = float(f.get("fred_wti_z", 0.0))
    if vix > 1.5 or oil > 2.0:
        return {"action": "HOLD", "conviction": min(max(vix, oil) / 3.0, 1.0)}
    return {"action": "BUY" if x > 0 else "SELL", "conviction": min(abs(x), 1.0)}


def contrarian(row):
    f = row["features"]
    x = float(f.get("mom_20d", 0.0))
    return {"action": "SELL" if x > 0 else "BUY", "conviction": min(abs(x), 1.0)}
