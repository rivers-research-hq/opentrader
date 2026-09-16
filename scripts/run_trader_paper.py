#!/usr/bin/env python3
"""Run today's agentic paper votes. No orders, no exchange writes."""
import argparse, json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from strategies.trader_agent.features import all_symbols, daily_context
from strategies.trader_agent.agent import decide

OUT = pathlib.Path(__file__).resolve().parents[1] / "data" / "trader_agent"

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--symbols", nargs="*")
    ap.add_argument("--limit", type=int, default=6)
    a = ap.parse_args(); OUT.mkdir(parents=True, exist_ok=True)
    symbols = a.symbols or all_symbols()[:a.limit]
    votes=[]
    for sym in symbols:
        print(f"voting {sym}...", flush=True)
        votes.append(decide(sym, daily_context(sym)))
    payload={"generated": __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),
             "paper_only": True, "model_url": __import__('strategies.trader_agent.agent',fromlist=['URL']).URL,
             "votes": votes}
    (OUT/"votes.json").write_text(json.dumps(payload,indent=2)+"\n")
    print(json.dumps({"n":len(votes),"actions":{x:sum(v['action']==x for v in votes) for x in ['BUY','SELL','HOLD']},"path":str(OUT/"votes.json")}))
if __name__ == "__main__": main()
