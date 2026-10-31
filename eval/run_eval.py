"""Evaluation harness. Owner: Rohan (L).

    python -m eval.run_eval --n 10 --seed 42 --agents haiku --out eval/results/   # cost test first
    python -m eval.run_eval --n 200 --seed 42 --agents haiku --out eval/results/

Compares, per sampled row: what actually happened, solver-only (--agents none), agents + solver.
Writes eval/results/summary.csv and per_scenario.csv. Hard budget cap of $15.
Metrics: consensus rate within the cap, mean rounds, fallback rate, agent top picks failing a rule,
reviewer rejects, cited-value mismatches, schema-invalid rate, estimated delay vs ARRIVAL_DELAY,
latency, cost.
"""

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the evaluation over a seeded sample.")
    parser.add_argument("--n", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--agents", choices=["stub", "haiku", "sonnet", "none"], default="haiku")
    parser.add_argument("--out", default="eval/results/")
    parser.add_argument("--budget-usd", type=float, default=15.0)
    parser.parse_args()
    raise NotImplementedError


if __name__ == "__main__":
    main()
