"""Deterministic fallback, no AI. Owner: Rohan (L).

Weighted minimum over candidates that pass every rule. Returns None if none pass.
Fires on no consensus by round 2, an invalid message or a deadlock; the log records why.
"""

from src.schemas import Candidate, RuleResult

DEFAULT_WEIGHTS = {"delay": 1.0, "knock_on": 1.0}


def fallback_pick(
    candidates: list[Candidate],
    rule_results: list[RuleResult],
    weights: dict[str, float] = DEFAULT_WEIGHTS,
) -> Candidate | None:
    raise NotImplementedError
