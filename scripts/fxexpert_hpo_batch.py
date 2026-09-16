#!/usr/bin/env python3
"""Run a bounded causal HPO batch through the existing FXExpert trainer."""
import json, pathlib, sys, time
from fxexpert import train
import numpy as np
PANEL=dict(np.load("data/fx_expert/panel.npz", allow_pickle=False))

OUT=pathlib.Path('data/fx_expert/hpo_batch_20260916'); OUT.mkdir(parents=True,exist_ok=True)
configs={
 'hpo_a':dict(d_model=128,n_layers=4,n_heads=8,dropout=.20,lr=5e-4,epochs=40,batch=1024,T=40,rule='rank',lev=1.0,rebal=5,score_l2=.05,horizon=10,rank_lambda=.05,cost_lambda=.5),
 'hpo_b':dict(d_model=192,n_layers=5,n_heads=8,dropout=.20,lr=4e-4,epochs=40,batch=1024,T=20,rule='rank',lev=1.0,rebal=5,score_l2=.05,horizon=10,rank_lambda=.05,cost_lambda=.5),
 'hpo_c':dict(d_model=96,n_layers=3,n_heads=4,dropout=.10,lr=5e-4,epochs=60,batch=2048,T=20,rule='rank',lev=1.0,rebal=5,score_l2=.02,horizon=20,rank_lambda=.10,cost_lambda=.5),
 'hpo_d':dict(d_model=128,n_layers=4,n_heads=8,dropout=.15,lr=3e-4,epochs=40,batch=1024,T=40,rule='rank',lev=1.0,rebal=5,vol_target=True,score_l2=.05,horizon=20,rank_lambda=.05,cost_lambda=.5),
}
summary=[]
for tag,hp in configs.items():
    print('RUN',tag,flush=True); t=time.time()
    try:
        g=train.run_generation(tag,hp,out_dir=OUT,seed=11,panel=PANEL)
        summary.append({'tag':tag,'seconds':round(time.time()-t,1),'aggregate':g.get('aggregate'),'params':g.get('params'),'hp':hp})
    except Exception as e:
        summary.append({'tag':tag,'error':repr(e),'hp':hp})
(pathlib.Path(OUT)/'summary.json').write_text(json.dumps(summary,indent=2))
print(json.dumps(summary,indent=2))
