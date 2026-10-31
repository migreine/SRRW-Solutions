"""Run one scenario end to end. Owner: Rohan (L).

    python -m src.cli --row-id 0 --agents stub
    python -m src.cli --row-id <N> --agents haiku --out runs/
    python -m src.cli --row-id <N> --agents none          # solver-only baseline
    python -m src.cli --row-id <N> --agents stub --force-deadlock

Pipeline: build_scenario -> generate_candidates -> check_all -> negotiate -> review -> write
runs/<scenario_id>.json (Recommendation + turns) and runs/<scenario_id>.jsonl (consensus log).
"""

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one disruption scenario end to end.")
    parser.add_argument("--row-id", type=int, required=True)
    parser.add_argument("--agents", choices=["stub", "haiku", "sonnet", "none"], default="stub")
    parser.add_argument("--out", default="runs/")
    parser.add_argument("--force-deadlock", action="store_true")
    parser.parse_args()
    raise NotImplementedError


if __name__ == "__main__":
    main()
