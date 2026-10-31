"""Monotonic concession protocol, at most 2 rounds. Owner: Rohan (L).

- Round 2's `acceptable` must contain round 1's; a message that shrinks it is invalid and logged.
- Consensus = the intersection of all agents' acceptable sets that also passes every rule;
  pick the candidate with the highest summed score.
- No consensus after round 2 -> deterministic fallback (src/fallback/solver.py).
- Agents never see rule results.
"""

from src.agents.base import Agent
from src.schemas import Candidate, Recommendation, RuleResult, Scenario, Turn


def negotiate(
    s: Scenario,
    candidates: list[Candidate],
    agents: list[Agent],
    rules: list[RuleResult],
    max_rounds: int = 2,
) -> tuple[Recommendation, list[Turn]]:
    raise NotImplementedError
