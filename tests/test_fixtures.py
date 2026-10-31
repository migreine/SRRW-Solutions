"""The hand-built fixtures validate against src/schemas.py and have the designed shape."""

import pytest

from src.agents.base import InvalidMessage
from src.schemas import AgentMessage, Candidate, RuleResult, Scenario, Tagged
from tests.fixtures.aa334_fixture import (
    CANDIDATE_IDS,
    RULE_IDS,
    fixture_candidates,
    fixture_rule_results,
    fixture_scenario,
)
from tests.fixtures.fixture_agents import MODES, FixtureAgent, fixture_agents


def test_scenario_validates_and_is_tagged():
    s = fixture_scenario()
    Scenario.model_validate(s.model_dump())
    assert s.flight["ARRIVAL_DELAY"] == 101 and s.flight["DEPARTURE_DELAY"] == 114
    assert s.fuel_reserve_min == Tagged(value=105.1, source="estimated", note=s.fuel_reserve_min.note)
    assert s.crew_duty_remaining_min.source == "synthetic"
    assert s.wake_category.value == "L" and s.wake_category.source == "assumed"
    assert {"iata": "AUS", "distance_nm": 295} in s.alternates and len(s.alternates) == 3
    assert len(s.downstream_legs) == 3


def test_candidates_and_rules_shape():
    cands = fixture_candidates()
    assert [c.candidate_id for c in cands] == CANDIDATE_IDS
    for c in cands:
        Candidate.model_validate(c.model_dump())
    rules = fixture_rule_results()
    assert len(rules) == len(RULE_IDS) * len(CANDIDATE_IDS) == 48
    for r in rules:
        RuleResult.model_validate(r.model_dump())
        assert r.citation and r.source
    failing = {(r.rule_id, r.candidate_id) for r in rules if not r.passed}
    assert failing == {("R-FUEL-01", "HOLD40"), ("R-DUTY-01", "DIVERT_AUS")}


@pytest.mark.parametrize("mode", [m for m in MODES if m != "invalid"])
def test_fixture_agents_return_agent_messages(mode):
    s, cands = fixture_scenario(), fixture_candidates()
    for agent in fixture_agents(mode):
        msg = agent.propose(s, cands, 1, None, others=[])
        assert isinstance(msg, AgentMessage) and msg.agent == agent.role and msg.round == 1


def test_invalid_mode_raises_for_pilot_only():
    s, cands = fixture_scenario(), fixture_candidates()
    with pytest.raises(InvalidMessage) as exc:
        FixtureAgent("PILOT", mode="invalid").propose(s, cands, 1, None)
    assert exc.value.raw_text
    FixtureAgent("ATC", mode="invalid").propose(s, cands, 1, None)


def test_unknown_mode_rejected():
    with pytest.raises(ValueError):
        FixtureAgent("ATC", mode="nope")
