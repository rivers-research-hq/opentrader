"""Arena: RL candidate-battle + portfolio-war referee for the Momentum agent.

Package layout:
  candidates.py  — labeled candidate rows (state, features, forward return)
  opponents.py   — in-process opponent bots (home-grown + persona playbooks)
  battle.py      — the candidate-battle ring (RL training loop surface)
  war.py         — the portfolio-war referee (CPU-fast, engine.run_backtest based)
  agent.py       — the value head (fit + vote + gate)
  train.py       — one arena iteration: battle -> fit -> war -> relabel -> gate
  view.py        — JSON snapshots for the live viewer
  arena_view.html — live animation of both fields
"""
