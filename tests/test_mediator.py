"""src/mediator/protocol.py: monotonic concession, 2-round cap, invalid -> fallback, log events."""

from collections import Counter

import pytest

from src.agents.base import Agent
from src.log.consensus_log import ConsensusLog
from src.mediator.protocol import negotiate
from src.schemas import AgentMessage, Recommendation, Turn
from tests.fixtures.aa334_fixture import (
    fixture_candidates,
    fixture_rule_results,
    fixture_scenario,
)
from tests.fixtures.fixture_agents import INVALID_RAW_TEXT, FixtureAgent, fixture_agents
from tests.fixtures.paths import out_dir  # noqa: F401  (pytest fixture)


def run(mode, out_dir, **kw):
    agents = fixture_agents(mode)
    log = ConsensusLog(out_dir / "m.jsonl")
    rec, turns = negotiate(fixture_scenario(), fixture_candidates(), agents,
                           fixture_rule_results(), log=log, **kw)
    Recommendation.model_validate(rec.model_dump())
    for t in turns:
        Turn.model_validate(t.model_dump())
    return rec, turns, log.read_all(), agents


def events(log, name):
    return [e for e in log if e["event"] == name]


def per_round_message_counts(log):
    c = Counter()
    for e in log:
        if e["event"] in ("agent_message", "message_invalid"):
            c[e["round"]] += 1
    return c


def test_converge_reaches_consensus_in_round_2(out_dir):
    rec, turns, log, agents = run("converge", out_dir)
    assert rec.decided_by == "consensus" and rec.rounds_used == 2
    assert rec.chosen.candidate_id == "SLOT+30" and rec.fallback is None
    assert [t.intersection for t in turns] == [[], ["SLOT+30"]]
    assert len(events(log, "agent_message")) == 6
    assert per_round_message_counts(log) == {1: 3, 2: 3}
    assert [e["round"] for e in events(log, "intersection")] == [1, 2]
    (cons,) = events(log, "consensus")
    assert cons["candidate_id"] == "SLOT+30" and set(cons["per_agent_scores"]) == {"ATC", "PILOT", "GROUND"}
    assert not events(log, "fallback_fired")
    # round 2: prior is the agent's own round-1 message, others are the other two roles
    for a in agents:
        r2 = a.received[1]
        assert r2["prior"].agent == a.role and r2["prior"].round == 1
        assert sorted(m.agent for m in r2["others"]) == sorted({"ATC", "PILOT", "GROUND"} - {a.role})
        assert a.received[0]["others"] == []


def test_converge_r1_stops_after_round_1(out_dir):
    rec, turns, log, agents = run("converge_r1", out_dir)
    assert rec.decided_by == "consensus" and rec.rounds_used == 1
    assert rec.chosen.candidate_id == "SLOT+15"
    assert len(turns) == 1 and len(turns[0].messages) == 3
    assert all([c["round"] for c in a.calls] == [1] for a in agents)  # round 2 never called
    assert per_round_message_counts(log) == {1: 3}
    assert len(events(log, "intersection")) == 1


def test_unsafe_consensus_goes_to_fallback(out_dir):
    rec, turns, log, _ = run("unsafe_consensus", out_dir)
    assert turns[0].intersection == ["HOLD40"] and turns[1].intersection == ["HOLD40"]
    assert all(e["rules_pass_intersection"] == [] for e in events(log, "intersection"))
    assert rec.decided_by == "fallback" and rec.rounds_used == 2
    assert rec.chosen is not None and rec.chosen.candidate_id != "HOLD40"
    assert rec.fallback["reason"] == "no_consensus"
    (fb,) = events(log, "fallback_fired")
    assert fb["reason"] == "no_consensus" and fb["candidate_id"] == rec.chosen.candidate_id
    assert fb["weights"] == {"delay": 1.0, "knock_on": 1.0} and fb["n_eligible"] == 6


def test_deadlock_falls_back_after_two_rounds(out_dir):
    rec, turns, log, _ = run("deadlock", out_dir)
    assert rec.decided_by == "fallback" and rec.rounds_used == 2 and len(turns) == 2
    assert rec.fallback["reason"] == "no_consensus" and rec.chosen.candidate_id == "SLOT-15"
    assert per_round_message_counts(log) == {1: 3, 2: 3}


def test_shrink_is_monotonic_violation(out_dir):
    rec, turns, log, _ = run("shrink", out_dir)
    assert rec.decided_by == "fallback" and rec.fallback["reason"] == "monotonic_violation"
    assert rec.rounds_used == 2
    (bad,) = turns[1].invalid_messages
    assert bad["agent"] == "PILOT" and bad["reason"] == "monotonic_violation" and "HOLD20" in bad["error"]
    assert bad["raw_text"]  # the offending message, verbatim
    (inv,) = events(log, "message_invalid")
    assert inv["reason"] == "monotonic_violation" and inv["round"] == 2
    assert events(log, "fallback_fired")[0]["reason"] == "monotonic_violation"
    assert per_round_message_counts(log) == {1: 3, 2: 3}  # other agents still called and logged


def test_invalid_message_falls_back_with_raw_text(out_dir):
    rec, turns, log, agents = run("invalid", out_dir)
    assert rec.decided_by == "fallback" and rec.fallback["reason"] == "invalid_message"
    assert rec.rounds_used == 1 and len(turns) == 1
    (inv,) = events(log, "message_invalid")
    assert inv["agent"] == "PILOT" and inv["reason"] == "schema" and inv["raw_text"] == INVALID_RAW_TEXT
    assert turns[0].invalid_messages[0]["raw_text"] == INVALID_RAW_TEXT
    assert len(events(log, "agent_message")) == 2  # ATC and GROUND still called
    assert all(len(a.calls) == 1 for a in agents)  # no round 2, no retry by the mediator


def test_unknown_id_is_invalid(out_dir):
    rec, turns, log, _ = run("unknown_id", out_dir)
    assert rec.decided_by == "fallback" and rec.fallback["reason"] == "invalid_message"
    (inv,) = events(log, "message_invalid")
    assert inv["agent"] == "GROUND" and inv["reason"] == "unknown_candidate" and "BOGUS" in inv["error"]


def test_veto_conflict_is_invalid(out_dir):
    rec, _, log, _ = run("veto_conflict", out_dir)
    assert rec.decided_by == "fallback" and rec.fallback["reason"] == "invalid_message"
    (inv,) = events(log, "message_invalid")
    assert inv["agent"] == "PILOT" and inv["reason"] == "veto_acceptable_conflict"


def test_force_deadlock(out_dir):
    rec, turns, log, _ = run("converge", out_dir, force_deadlock=True)
    assert rec.decided_by == "fallback" and rec.fallback["reason"] == "forced_deadlock"
    assert rec.rounds_used == 2 and all(t.intersection == [] for t in turns)
    ids = [c.candidate_id for c in fixture_candidates()]
    r1 = {m.agent: m.acceptable for m in turns[0].messages}
    assert r1 == {"ATC": ids[0::3], "PILOT": ids[1::3], "GROUND": ids[2::3]}
    assert all(e["forced"] for e in events(log, "agent_message"))
    assert events(log, "fallback_fired")[0]["reason"] == "forced_deadlock"


def test_agents_never_receive_rule_results(out_dir):
    _, _, _, agents = run("converge", out_dir)
    for a in agents:
        for call in a.received:
            assert set(call) == {"round", "prior", "others"}


def test_custom_weights_flow_to_fallback(out_dir):
    rec, _, log, _ = run("deadlock", out_dir, weights={"delay": 0.0, "knock_on": 1.0})
    assert rec.chosen.candidate_id == "SLOT+15"
    assert events(log, "fallback_fired")[0]["weights"] == {"delay": 0.0, "knock_on": 1.0}


class LegacyAgent(Agent):
    """Agent with the original 4-argument propose (no `others=`)."""

    def __init__(self, role):
        super().__init__(role)
        self.inner = FixtureAgent(role, mode="converge_r1")

    def propose(self, s, candidates, round, prior):
        return self.inner.propose(s, candidates, round, prior)


def test_legacy_agent_interface_retried_and_logged(out_dir):
    agents = [LegacyAgent(r) for r in ("ATC", "PILOT", "GROUND")]
    log = ConsensusLog(out_dir / "legacy.jsonl")
    rec, _ = negotiate(fixture_scenario(), fixture_candidates(), agents, fixture_rule_results(),
                       log=log)
    assert rec.decided_by == "consensus"
    iface = events(log.read_all(), "agent_interface")
    assert len(iface) == 3 and all(e["interface"] == "legacy" for e in iface)


class BrokenAgent(Agent):
    def propose(self, s, candidates, round, prior, others=None):
        raise RuntimeError("connection reset")


class WrongRoleAgent(Agent):
    def propose(self, s, candidates, round, prior, others=None):
        return AgentMessage(agent="ATC", round=round, acceptable=[], ranking=[], vetoes=[])


def test_exception_and_wrong_role_become_invalid(out_dir):
    s, cands, rules = fixture_scenario(), fixture_candidates(), fixture_rule_results()
    log = ConsensusLog(out_dir / "x.jsonl")
    agents = [FixtureAgent("ATC"), BrokenAgent("PILOT"), WrongRoleAgent("GROUND")]
    rec, turns = negotiate(s, cands, agents, rules, log=log)
    reasons = [m["reason"] for m in turns[0].invalid_messages]
    assert reasons == ["exception", "schema"]
    assert "connection reset" in turns[0].invalid_messages[0]["error"]
    assert rec.decided_by == "fallback" and rec.fallback["reason"] == "invalid_message"


def test_bad_agent_list_rejected():
    s, cands, rules = fixture_scenario(), fixture_candidates(), fixture_rule_results()
    with pytest.raises(ValueError):
        negotiate(s, cands, fixture_agents()[:2], rules)
    with pytest.raises(ValueError):
        negotiate(s, cands, [FixtureAgent("ATC"), FixtureAgent("ATC"), FixtureAgent("PILOT")], rules)


def test_no_log_is_fine():
    rec, turns = negotiate(fixture_scenario(), fixture_candidates(), fixture_agents("converge"),
                           fixture_rule_results())
    assert rec.chosen.candidate_id == "SLOT+30" and len(turns) == 2
