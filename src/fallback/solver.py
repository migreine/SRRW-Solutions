"""Deterministic fallback, no AI. Owner: Rohan (L).

Weighted minimum over candidates that pass every rule. Returns None if none pass.
Fires on no consensus by round 2, an invalid message or a deadlock; the log records why.

- Agents' opinions are never consulted: inputs are the candidate menu and the rule results only.
- Eligible = at least one RuleResult for the candidate, all of them passed, and not excluded.
  A candidate with no RuleResult is "unchecked" and never eligible.
- Objective = weights["delay"] * est_delay_min + weights["knock_on"] * est_knock_on_min.
  A missing weight key raises KeyError on purpose (weights live in one dict and are logged).
- Ties -> lowest candidate_id (string order). No randomness.
- None means "no safe option: escalate to a human" and must stay representable.
"""

from collections import defaultdict

from src.schemas import Candidate, RuleResult

DEFAULT_WEIGHTS = {"delay": 1.0, "knock_on": 1.0}


def objective(c: Candidate, weights: dict[str, float]) -> float:
    return weights["delay"] * c.est_delay_min + weights["knock_on"] * c.est_knock_on_min


def rules_passing_ids(candidates: list[Candidate], rule_results: list[RuleResult]) -> set[str]:
    """Ids of candidates with >= 1 RuleResult, all passed. Shared with the mediator."""
    passed: dict[str, list[bool]] = defaultdict(list)
    for r in rule_results:
        passed[r.candidate_id].append(r.passed)
    return {c.candidate_id for c in candidates if passed.get(c.candidate_id) and all(passed[c.candidate_id])}


def _evaluate(candidates, rule_results, weights, exclude) -> dict:
    exclude = set(exclude)
    checked = {r.candidate_id for r in rule_results}
    passing = rules_passing_ids(candidates, rule_results)
    eligible = [c for c in candidates if c.candidate_id in passing and c.candidate_id not in exclude]
    scored = sorted(((objective(c, weights), c.candidate_id, c) for c in eligible),
                    key=lambda t: (t[0], t[1]))
    best = scored[0] if scored else None
    return {
        "chosen_candidate": best[2] if best else None,
        "chosen": best[1] if best else None,
        "objective": float(best[0]) if best else None,
        "n_eligible": len(eligible),
        "eligible_ids": sorted(c.candidate_id for c in eligible),
        "excluded": sorted(exclude),
        "unchecked": sorted(c.candidate_id for c in candidates if c.candidate_id not in checked),
    }


def fallback_pick(
    candidates: list[Candidate],
    rule_results: list[RuleResult],
    weights: dict[str, float] = DEFAULT_WEIGHTS,
    exclude: set[str] = frozenset(),
) -> Candidate | None:
    """Lowest-objective candidate that passes every rule and is not excluded, else None."""
    return _evaluate(candidates, rule_results, weights, exclude)["chosen_candidate"]


def fallback_explain(
    candidates: list[Candidate],
    rule_results: list[RuleResult],
    weights: dict[str, float] = DEFAULT_WEIGHTS,
    exclude: set[str] = frozenset(),
) -> dict:
    """What fallback_pick decided and why, for the log:
    {"chosen", "objective", "n_eligible", "eligible_ids", "excluded", "unchecked"}."""
    out = _evaluate(candidates, rule_results, weights, exclude)
    out.pop("chosen_candidate")
    return out
