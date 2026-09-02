#!/usr/bin/env python3
"""Generate synthetic trading scenarios and augment training dataset."""
import json
import sys
from training.programmatic_teacher import ProgrammaticTeacher

def generate_synthetic_dataset(count: int = 2000, output: str = "data/training/synthetic_scenarios.jsonl"):
    teacher = ProgrammaticTeacher(seed=42)
    weights = ["breakout", "false_breakout", "trend_following",
               "mean_reversion", "flash_crash", "range_accumulation"]
    scenarios = teacher.generate_batch(count, weights=weights)

    counts = {}
    buy = sell = hold = 0
    for s in scenarios:
        counts[s.scenario_type] = counts.get(s.scenario_type, 0) + 1
        gt = s.ground_truth
        if "BUY" in gt: buy += 1
        elif "SELL" in gt: sell += 1
        else: hold += 1

    print(f"Generated {len(scenarios)} scenarios:")
    for t, c in sorted(counts.items()):
        print(f"  {t}: {c}")
    print(f"  BUY:{buy} SELL:{sell} HOLD:{hold}")

    with open(output, "w") as f:
        for s in scenarios:
            bar_lines = []
            for b in s.bars[:20]:
                bar_lines.append(f"{b['open']},{b['high']},{b['low']},{b['close']},{b['volume']}")

            context = f"Market data ({s.scenario_type}):\n"
            context += "\n".join(bar_lines)
            context += f"\nPattern: {s.description}"

            # Parse ground truth action
            gt = s.ground_truth
            action = gt.split(" with ")[0] if " with " in gt else gt
            if action not in ("BUY", "SELL", "HOLD"):
                if "buy" in action.lower(): action = "BUY"
                elif "sell" in action.lower(): action = "SELL"
                else: action = "HOLD"

            entry = {
                "messages": [
                    {"role": "system", "content": "You are a crypto trading agent. Analyze the market data and output a trading signal."},
                    {"role": "user", "content": context},
                    {"role": "assistant", "content": json.dumps({
                        "action": action,
                        "confidence": s.confidence,
                        "reasoning": s.explanation[:200],
                        "scenario": s.scenario_type,
                    })},
                ]
            }
            f.write(json.dumps(entry) + "\n")

    print(f"Saved {output} ({len(scenarios)} entries)")
    return len(scenarios)


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
    generate_synthetic_dataset(n)
