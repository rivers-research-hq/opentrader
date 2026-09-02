#!/bin/bash
# Accumulator daily refresh — gpu-run delegates to best GPU + rcheck caps
set -euo pipefail
cd /home/mrc/opentrader
DATASETS="fred.VIXCLS fred.BAA fred.AAA etf.SPY etf.IEF etf.LQD etf.HYG etf.GLD etf.DBC etf.VNQ etf.EEM etf.TLT fred.PPIACO fred.DFF fred.T10YIE fred.DTWEXBGS fred.DCOILWTICO sec.form4"

# 1. refresh data lake (network acquires in parallel)
/opt/miniconda3/bin/python3 -u data/refresh.py >> /tmp/opencode/accumulator.log 2>&1

# 2. falsify all datasets on GPU (rebuilt v2 — GPU-resident, ordinal-only)
#    via verify_alert.py so every scheduled run also proves the honesty bar
#    (scale workers -> util/VRAM delta moves on rocm-smi, else ALERT)
/opt/miniconda3/bin/python3 -u /home/mrc/opentrader-sandbox/data/verify_alert.py --workers 2 \
    --falsify /home/mrc/opentrader-sandbox/data/gpu_falsify_v2.py >> /tmp/opencode/accumulator.log 2>&1 \
    || echo "VERIFY-ALERT FAILED: GPU claim contradicted meters" >> /tmp/opencode/accumulator.log

# 3. check for survivors
/opt/miniconda3/bin/python3 -c "
import sqlite3
conn = sqlite3.connect('data/accumulator/catalog.db')
rows = conn.execute('''
    SELECT dataset, direction, GROUP_CONCAT(boot_pctile) as pctiles
    FROM evidence WHERE tested_at > datetime('now','-1 hour')
    GROUP BY dataset, direction
''').fetchall()
print(f'--- {len(rows)} test-results this run ---')
survivors = []
for ds, d, pcts in rows:
    vals = [float(x) for x in pcts.split(',')]
    sig = sum(1 for v in vals if v >= 95)
    if sig >= 2:
        survivors.append(ds)
        print(f'  SURVIVOR: {ds} ({\"+\" if d>0 else \"-\"}) pctiles={pcts}')
print(f'survivors: {survivors or \"none\"}')
" >> /tmp/opencode/accumulator.log 2>&1
