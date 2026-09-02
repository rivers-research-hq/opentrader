"""The candidate-battle ring — the RL training loop's surface.

Rounds: batches of candidates. Each bot in the field votes TAKE/SKIP per
candidate; the agent votes with its value head. Reward = field-relative
z-scored forward return (cross-sectionally standardized against the round's
candidate field, per research ticket 'Arena reward + war-relabeling
protocol'). Emits standings (true sums — take_mean/arena_score are derived
as sums/takes, never averaged), head-to-head wins, and per-candidate arena
targets (z, field mean) the war-relabeling consumes.
"""

import statistics


def _round_field_z(fwds):
    m = statistics.mean(fwds)
    s = statistics.pstdev(fwds)
    if s < 1e-9:
        return [0.0] * len(fwds), m
    return [(f - m) / s for f in fwds], m


def _mean(values):
    return statistics.mean(values) if values else 0.0


def run_battle(rows, field, agent_fn, round_size=25, agent_evals=None):
    """agent_fn(state) -> (vote: 0/1, value: float).
    Pass agent_evals = {(bar, sym): (vote, value)} to precompute the agent's
    votes in one batched pass instead of calling agent_fn per candidate."""
    field = list(field)
    standings = {
        b.name: {"n": 0, "takes": 0, "take_fwd_sum": 0.0, "take_z_sum": 0.0}
        for b in field
    }
    standings["agent"] = {"n": 0, "takes": 0, "take_fwd_sum": 0.0, "take_z_sum": 0.0}
    h2h = {b.name: {"wins": 0, "losses": 0} for b in field}
    rounds_log = []
    arena_targets = {}

    if not rows:
        return {"standings": standings, "h2h": h2h, "rounds": rounds_log,
                "arena_targets": arena_targets}

    n_rounds = max(1, (len(rows) + round_size - 1) // round_size)
    for ri in range(n_rounds):
        batch = rows[ri * round_size : (ri + 1) * round_size]
        zs, r_field = _round_field_z([r["fwd"] for r in batch])
        bot_takes = {b.name: [] for b in field}
        bot_scores = {b.name: [] for b in field}
        agent_takes, agent_scores = [], []
        keyed = {}
        for row, z in zip(batch, zs):
            if agent_evals is not None:
                v, val = agent_evals[(row["bar"], row["sym"])]
            else:
                v, val = agent_fn(row)
            key = (row["bar"], row["sym"])
            arena_targets[key] = {
                "z": z,
                "r_field": r_field,
                "value": val,
                "agent_vote": v,
            }
            keyed[key] = {"z": z, "agent": v, "bots": {}}
            for b in field:
                bv = b.vote(row)
                keyed[key]["bots"][b.name] = bv
                if bv:
                    bot_takes[b.name].append(row["fwd"])
                    bot_scores[b.name].append(z)
            if v:
                agent_takes.append(row["fwd"])
                agent_scores.append(z)
        for b in field:
            s = standings[b.name]
            s["n"] += len(batch)
            s["takes"] += len(bot_takes[b.name])
            s["take_fwd_sum"] += sum(bot_takes[b.name])
            s["take_z_sum"] += sum(bot_scores[b.name])
            for k, v in keyed.items():
                if not (v["agent"] and v["bots"][b.name]):
                    continue
                if v["z"] > 0:
                    h2h[b.name]["wins"] += 1
                else:
                    h2h[b.name]["losses"] += 1
        sa = standings["agent"]
        sa["n"] += len(batch)
        sa["takes"] += len(agent_takes)
        sa["take_fwd_sum"] += sum(agent_takes)
        sa["take_z_sum"] += sum(agent_scores)
        rounds_log.append(
            {
                "round": ri,
                "bar": batch[0]["bar"],
                "n": len(batch),
                "agent": {"takes": len(agent_takes), "score": _mean(agent_scores)},
                "field": {
                    b.name: {
                        "takes": len(bot_takes[b.name]),
                        "score": _mean(bot_scores[b.name]),
                    }
                    for b in field
                },
            }
        )

    return {
        "standings": standings,
        "h2h": h2h,
        "rounds": rounds_log,
        "arena_targets": arena_targets,
    }
