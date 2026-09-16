#!/usr/bin/env python3
"""Causal baseline for trader-agent voting.

This does not call an LLM. It validates the feature window and scorer against
historical bars first; the LLM runner is a separate paper-vote path.
"""
import argparse, json, pathlib, sys
import duckdb
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from strategies.trader_agent.scorer import score_vote, summarize
STORE = "/home/mrc/opentrader-data/store.duckdb"

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--symbol',default='EUR_USD'); ap.add_argument('--limit',type=int,default=200); a=ap.parse_args()
    con=duckdb.connect(STORE,read_only=True)
    rows=con.execute("""SELECT ts, close FROM bars WHERE symbol=? AND timeframe='1d' ORDER BY ts LIMIT ?""",(a.symbol,a.limit+1)).fetchall(); con.close()
    scored=[]
    # causal momentum baseline: vote in direction of prior daily return
    for i in range(1,len(rows)-1):
        prev, cur, nxt=rows[i-1][1], rows[i][1], rows[i+1][1]
        if not prev or not cur or not nxt: continue
        vote={'symbol':a.symbol,'action':'BUY' if cur>prev else 'SELL','conviction':0.5,'thesis':'one-day momentum baseline'}
        scored.append(score_vote(vote,(nxt/cur-1)*100))
    print(json.dumps({'symbol':a.symbol,'bars':len(rows),'baseline':summarize(scored)},indent=1))
if __name__=='__main__': main()
