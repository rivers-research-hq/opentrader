#!/usr/bin/env python3
"""Read-only OANDA v20 depth probe — evidence for the W4b ladder (#389) human lock.

Answers three questions the canned tests cannot:
  1. Is the practice orderBook/positionBook populated? (the ladder needs real buckets)
  2. What is the wire shape? (v20 quotes numbers as strings — see ot-venues book.rs)
  3. How fast does the book move at a given bucket width? (polling cadence)

No orders. GET only. Creds come from config/oanda_keys.json and are never printed.

Usage: python3 v2/tools/venue_book_probe.py [EUR_USD ...] [--polls N] [--interval S] [--bucket 1M]
Exit: 0 all probes answered; 1 a venue error; 2 creds/config missing.
"""
import argparse, json, os, statistics, sys, time, urllib.error, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_creds():
    cfg_path = os.path.join(ROOT, "config", "oanda_keys.json")
    if not os.path.exists(cfg_path):
        print(f"missing {cfg_path}", file=sys.stderr)
        return None
    cfg = json.load(open(cfg_path))
    host = str(cfg.get("host") or "practice")
    base = "https://api-fxpractice.oanda.com" if "practice" in host else "https://api-fxtrade.oanda.com"
    tok = cfg.get("api_key") or cfg.get("token") or cfg.get("access_token") or ""
    acct = cfg.get("account_id") or cfg.get("account") or ""
    if not tok or not acct:
        print("creds incomplete (token/account missing)", file=sys.stderr)
        return None
    return base, tok, acct


def get(base, tok, path):
    req = urllib.request.Request(base + path, headers={"Authorization": f"Bearer {tok}",
                                                      "Accept-Datetime-Format": "UNIX"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read()), time.time() - t0
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:200].decode("utf8", "replace"), time.time() - t0
    except Exception as e:  # transport failure is Err, never an empty book
        return 0, f"transport: {e}", time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instruments", nargs="*", default=["EUR_USD", "USD_JPY"])
    ap.add_argument("--polls", type=int, default=4)
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--bucket", default="1M")
    a = ap.parse_args()
    creds = load_creds()
    if not creds:
        return 2
    base, tok, acct = creds
    print(f"base={base} account=set token=set bucket={a.bucket}")
    rc = 0
    for inst in a.instruments:
        st, body, dt = get(base, tok, f"/v3/instruments/{inst}/orderBook?bucket={a.bucket}")
        if st != 200:
            print(f"{inst} orderBook HTTP {st}: {str(body)[:120]}")
            rc = 1
            continue
        buckets = (body.get("orderBook") or {}).get("buckets", [])
        # wire shape: one row per PRICE BUCKET, percentages as strings
        shapes = {(k, type(v).__name__) for b in buckets[:50] for k, v in b.items()}
        print(f"{inst} orderBook  HTTP 200  {dt*1000:.0f}ms  buckets={len(buckets)}  "
              f"keys={sorted({k for k, _ in shapes})} types={sorted({t for _, t in shapes})}")
        st2, b2, dt2 = get(base, tok, f"/v3/instruments/{inst}/positionBook?bucket={a.bucket}")
        nb = len((b2.get("positionBook") or {}).get("buckets", [])) if st2 == 200 else -1
        print(f"{inst} positionBook HTTP {st2} {dt2*1000:.0f}ms buckets={nb}")
        if st2 != 200:
            rc = 1

    # cadence: how often does the book actually change between polls?
    inst = a.instruments[0]
    snaps = []
    for i in range(a.polls):
        if i:
            time.sleep(a.interval)
        st, b, _ = get(base, tok, f"/v3/instruments/{inst}/orderBook?bucket={a.bucket}")
        if st != 200:
            print(f"cadence poll {i} HTTP {st}")
            return 1
        snaps.append(json.dumps((b.get("orderBook") or {}).get("buckets", []), sort_keys=True))
    changed = sum(1 for i in range(1, len(snaps)) if snaps[i] != snaps[i - 1])
    print(f"cadence: {changed}/{len(snaps)-1} polls at {a.interval}s showed a changed book "
          f"({inst}/{a.bucket})")

    # the streaming branch of the #389 lock: v20 has no order-book stream
    st, _, _ = get(base, tok, f"/v3/instruments/{inst}/orderBook/stream")
    print(f"orderBook/stream -> HTTP {st} (404 = no streaming depth; polling is the only mechanism)")
    return rc


if __name__ == "__main__":
    sys.exit(main())
