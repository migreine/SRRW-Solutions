"""src/fallback/solver.py: deterministic weighted argmin over rule-passing candidates."""

import pytest

from src.fallback.solver import DEFAULT_WEIGHTS, fallback_explain, fallback_pick, objective
from src.schemas import Candidate, RuleResult
from tests.fixtures.aa334_fixture import fixture_candidates, fixture_rule_results


def _rr(cid: str, passed: bool = True) -> RuleResult:
    return RuleResult(rule_id="R-FUEL-01", candidate_id=cid, passed=passed, observed=1.0,
                      threshold=0.0, source="estimated", citation="14 CFR 121.639")


def test_picks_lowest_objective_passing_candidate():
    cands, rules = fixture_candidates(), fixture_rule_results()
    pick = fallback_pick(cands, rules)
    assert pick is not None and pick.candidate_id not in {"HOLD40", "DIVERT_AUS"}
    failing = {r.candidate_id for r in rules if not r.passed}
    expected = min((c for c in cands if c.candidate_id not in failing),
                   key=lambda c: (objective(c, DEFAULT_WEIGHTS), c.candidate_id))
    assert pick.candidate_id == expected.candidate_id == "SLOT-15"
    info = fallback_explain(cands, rules, DEFAULT_WEIGHTS)
    assert info["chosen"] == "SLOT-15" and info["objective"] == 15.0
    assert info["n_eligible"] == 6 and "HOLD40" not in info["eligible_ids"]
    assert info["excluded"] == [] and info["unchecked"] == []


def test_failing_candidate_never_picked_even_if_cheapest():
    cands = fixture_candidates()
    rules = [r if r.candidate_id != "SLOT-15" or r.rule_id != "R-WAKE-01"
             else r.model_copy(update={"passed": False}) for r in fixture_rule_results()]
    assert fallback_pick(cands, rules).candidate_id == "GATE_B12"


def test_exclude_winner_gives_next_best():
    cands, rules = fixture_candidates(), fixture_rule_results()
    assert fallback_pick(cands, rules, exclude={"SLOT-15"}).candidate_id == "GATE_B12"
    info = fallback_explain(cands, rules, DEFAULT_WEIGHTS, exclude={"SLOT-15"})
    assert info["excluded"] == ["SLOT-15"] and info["n_eligible"] == 5


def test_none_when_nothing_eligible():
    cands = fixture_candidates()
    all_fail = [r.model_copy(update={"passed": False}) for r in fixture_rule_results()]
    assert fallback_pick(cands, all_fail) is None
    info = fallback_explain(cands, all_fail, DEFAULT_WEIGHTS)
    assert info["chosen"] is None and info["objective"] is None and info["n_eligible"] == 0
    assert fallback_pick([], []) is None


def test_unchecked_candidate_ignored():
    cheap = Candidate(candidate_id="FREE", kind="slot_shift", params={"shift_min": 0},
                      est_delay_min=-100, est_knock_on_min=0)
    cands = fixture_candidates() + [cheap]
    pick = fallback_pick(cands, fixture_rule_results())
    assert pick.candidate_id == "SLOT-15"
    assert fallback_explain(cands, fixture_rule_results(), DEFAULT_WEIGHTS)["unchecked"] == ["FREE"]


def test_tie_break_is_lowest_candidate_id():
    a = Candidate(candidate_id="B_OPT", kind="hold", params={"minutes": 10},
                  est_delay_min=10, est_knock_on_min=5)
    b = a.model_copy(update={"candidate_id": "A_OPT"})
    for order in ([a, b], [b, a]):
        assert fallback_pick(order, [_rr("A_OPT"), _rr("B_OPT")]).candidate_id == "A_OPT"


def test_weights_change_pick():
    cands, rules = fixture_candidates(), fixture_rule_results()
    assert fallback_pick(cands, rules, {"delay": 1.0, "knock_on": 1.0}).candidate_id == "SLOT-15"
    assert fallback_pick(cands, rules, {"delay": 0.0, "knock_on": 1.0}).candidate_id == "SLOT+15"


def test_missing_weight_key_raises():
    with pytest.raises(KeyError):
        fallback_pick(fixture_candidates(), fixture_rule_results(), {"delay": 1.0})
