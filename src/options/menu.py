"""Fixed menu of candidate resolutions. Owner: Waseem (T1).

Task card (docs/timeline.md, build block 1):
- Slot shift ±15 / ±30 min, hold 20 / 40 min, divert to 2 alternates, 2 gate swaps,
  ground hold at origin (tail_swap optional, first to be cut).
- est_delay_min and est_knock_on_min are deterministic estimates.
- Return between 5 and 12 candidates.
"""

from src.schemas import Candidate, Scenario


def generate_candidates(s: Scenario) -> list[Candidate]:
    raise NotImplementedError
