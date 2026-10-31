"""Tests for src/agents (Reine, T2). No API calls unless LIVE_AGENT_TEST=1.

    pytest tests/test_agents.py -q                       # offline, uses a FakeClient
    LIVE_AGENT_TEST=1 pytest tests/test_agents.py -k live -s   # one real Haiku call per role
"""

from __future__ import annotations

import copy
import json
import os
import re
from types import SimpleNamespace

import pytest

from src.agents import views
from src.agents.base import (
    MODEL_IDS,
    PRICES,
    TOOL_NAME,
    Agent,
    ClaudeAgent,
    InvalidMessage,
    StubAgent,
    _Reply,
    load_prompt,
)
from src.schemas import AgentMessage, Candidate, Scenario, Tagged

ROLES = ("ATC", "PILOT", "GROUND")


# ---------------------------------------------------------------------------------------------
# Mini scenario (own fixture, independent of other modules)
# ---------------------------------------------------------------------------------------------


def make_scenario() -> Scenario:
    return Scenario(
        scenario_id="2015-04-24_AA334_N469AA",
        row_index=123,
        flight={
            "YEAR": 2015, "MONTH": 4, "DAY": 24, "AIRLINE": "AA", "FLIGHT_NUMBER": 334,
            "TAIL_NUMBER": "N469AA", "ORIGIN_AIRPORT": "MFE", "DESTINATION_AIRPORT": "DFW",
            "SCHEDULED_DEPARTURE": 676, "SCHEDULED_ARRIVAL": 775, "DEPARTURE_DELAY": 114.0,
            "TAXI_OUT": 14.0, "DISTANCE": 468, "SCHEDULED_TIME": 99.0,
            "WEATHER_DELAY": 58.0, "LATE_AIRCRAFT_DELAY": 43.0,
            # outcome fields: must never reach an agent
            "ARRIVAL_DELAY": 101.0, "ARRIVAL_TIME": 876, "WHEELS_ON": 866, "TAXI_IN": 10.0,
        },
        dest_disruption=Tagged(value=14, source="data"),
        taxi_congestion=Tagged(value=1.4, source="data"),
        downstream_legs=[
            {"AIRLINE": "AA", "FLIGHT_NUMBER": 1389, "ORIGIN_AIRPORT": "DFW",
             "DESTINATION_AIRPORT": "MEM", "SCHEDULED_DEPARTURE": 828,
             "SCHEDULED_ARRIVAL": 922, "ARRIVAL_DELAY": 102.0, "DEPARTURE_DELAY": 111.0},
            {"AIRLINE": "AA", "FLIGHT_NUMBER": 1274, "ORIGIN_AIRPORT": "DFW",
             "DESTINATION_AIRPORT": "BWI", "SCHEDULED_DEPARTURE": 1115,
             "SCHEDULED_ARRIVAL": 1365, "ARRIVAL_DELAY": 256.0, "DEPARTURE_DELAY": 288.0},
        ],
        alternates=[{"iata": "AUS", "distance_nm": 190}, {"iata": "IAH", "distance_nm": 196}],
        wake_category=Tagged(value="L", source="assumed"),
        fuel_reserve_min=Tagged(value=78, source="estimated"),
        crew_duty_remaining_min=Tagged(value=150, source="synthetic"),
        gates={"assigned": "B12", "free": ["B14", "C3"]},
        connections=[
            {"flight": "AA2211", "dest": "ORD", "pax": 14, "minutes_after_arrival": 70},
            {"flight": "AA1630", "dest": "LGA", "pax": 9, "minutes_after_arrival": 95},
            {"flight": "AA455", "dest": "MIA", "pax": 6, "minutes_after_arrival": 150},
        ],
        nominal_aar=Tagged(value=90, source="assumed"),
    )


def make_candidates() -> list[Candidate]:
    def c(cid, kind, params, d, k):
        return Candidate(candidate_id=cid, kind=kind, params=params, est_delay_min=d,
                         est_knock_on_min=k)

    return [
        c("SLOT+15", "slot_shift", {"shift_min": 15}, 15, 10),
        c("SLOT+30", "slot_shift", {"shift_min": 30}, 30, 25),
        c("HOLD20", "hold", {"minutes": 20}, 20, 15),
        c("HOLD40", "hold", {"minutes": 40}, 40, 35),
        c("DIVERT_AUS", "divert", {"iata": "AUS"}, 150, 95),
        c("GATE_B14", "gate_swap", {"gate": "B14", "extra_taxi_min": 4}, 4, 0),
    ]


def resolve(s: Scenario, path: str):
    """Resolve a dotted / [i] path against a Scenario, the way the reviewer does."""
    obj = s
    for part in re.findall(r"\[\d+\]|[^.\[\]]+", path):
        if part.startswith("["):
            obj = obj[int(part[1:-1])]
        elif isinstance(obj, dict):
            obj = obj[part]
        else:
            obj = getattr(obj, part)
    return obj.value if isinstance(obj, Tagged) else obj


def assert_citation_resolves(s: Scenario, cited: str) -> None:
    assert "=" in cited, cited
    path, value = cited.split("=", 1)
    actual = resolve(s, path)
    try:
        assert abs(float(value) - float(actual)) <= max(1.0, 0.02 * abs(float(actual)))
    except ValueError:
        assert str(actual).lower() == value.lower()


def run_round(agents, s, cands, rnd, priors):
    msgs = {}
    for a in agents:
        others = [priors[o.role] for o in agents if o.role != a.role and priors.get(o.role)]
        msgs[a.role] = a.propose(s, cands, rnd, priors.get(a.role), others=others or None)
    return msgs


# ---------------------------------------------------------------------------------------------
# StubAgent
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("role", ROLES)
def test_stub_round1_valid(role):
    s, cands = make_scenario(), make_candidates()
    msg = StubAgent(role).propose(s, cands, 1, None)
    AgentMessage.model_validate(msg.model_dump())
    _Reply.model_validate({"acceptable": msg.acceptable, "ranking": msg.ranking,
                           "vetoes": msg.vetoes})  # stub output also fits the LLM tool schema
    assert msg.agent == role and msg.round == 1
    ids = {c.candidate_id for c in cands}
    assert {r["candidate_id"] for r in msg.ranking} == ids
    assert msg.acceptable and set(msg.acceptable) <= ids
    assert not set(msg.acceptable) & {v["candidate_id"] for v in msg.vetoes}
    scores = [r["score"] for r in msg.ranking]
    assert scores == sorted(scores, reverse=True) and all(0 <= x <= 1 for x in scores)
    for r in msg.ranking:
        for cited in r["cited_fields"]:
            assert_citation_resolves(s, cited)
    for v in msg.vetoes:
        assert_citation_resolves(s, v["cited_field"])


@pytest.mark.parametrize("role", ROLES)
def test_stub_round2_superset_and_concedes(role):
    s, cands = make_scenario(), make_candidates()
    r1 = run_round([StubAgent(r) for r in ROLES], s, cands, 1, {})
    others = [m for r, m in r1.items() if r != role]
    msg = StubAgent(role).propose(s, cands, 2, r1[role], others=others)
    assert set(msg.acceptable) >= set(r1[role].acceptable)
    offered = {cid for m in others for cid in m.acceptable} - set(r1[role].acceptable)
    vetoed = {v["candidate_id"] for v in r1[role].vetoes}
    if offered - vetoed:
        assert set(msg.acceptable) & (offered - vetoed), "round 2 must add an id another accepted"
    # a round-1 accepted id never gains a veto
    assert not set(r1[role].acceptable) & {v["candidate_id"] for v in msg.vetoes}


def test_three_stubs_converge_within_two_rounds():
    s, cands = make_scenario(), make_candidates()
    agents = [StubAgent(r) for r in ROLES]
    r1 = run_round(agents, s, cands, 1, {})
    r2 = run_round(agents, s, cands, 2, r1)
    inter = set.intersection(*(set(m.acceptable) for m in r2.values()))
    assert inter, "stub path must be able to reach consensus"


def test_stub_edge_cases():
    s, cands = make_scenario(), make_candidates()
    with pytest.raises(ValueError):
        StubAgent("ATC").propose(s, [], 1, None)
    one = StubAgent("PILOT").propose(s, cands[:1], 1, None)
    assert one.acceptable == ["SLOT+15"] and one.vetoes == []
    # all delays equal -> no divide-by-zero
    flat = [c.model_copy(update={"est_delay_min": 10.0, "est_knock_on_min": 0.0}) for c in cands]
    assert StubAgent("GROUND").propose(s, flat, 1, None).ranking
    # round 2 without others, and without prior
    r1 = StubAgent("ATC").propose(s, cands, 1, None)
    r2 = StubAgent("ATC").propose(s, cands, 2, r1, others=None)
    assert set(r2.acceptable) >= set(r1.acceptable)
    r2b = StubAgent("ATC").propose(s, cands, 2, None)
    assert r2b.round == 2 and set(r2b.acceptable) == set(r1.acceptable)
    with pytest.raises(ValueError):
        StubAgent("TOWER")


def test_stub_deterministic():
    s, cands = make_scenario(), make_candidates()
    a = [StubAgent(r).propose(s, cands, 1, None).model_dump() for r in ROLES]
    b = [StubAgent(r).propose(s, cands, 1, None).model_dump() for r in ROLES]
    assert a == b
    assert views.domain_view(s, cands, "PILOT", 1) == views.domain_view(s, cands, "PILOT", 1)


def test_propose_signature_accepts_others_kwarg():
    import inspect

    for cls in (Agent, StubAgent, ClaudeAgent):
        params = inspect.signature(cls.propose).parameters
        assert list(params)[:6] == ["self", "s", "candidates", "round", "prior", "others"]
        assert params["others"].default is None


# ---------------------------------------------------------------------------------------------
# domain_view
# ---------------------------------------------------------------------------------------------

FORBIDDEN = {
    "ATC": ["fuel_reserve_min", "crew_duty", "gates", "connections", "alternates"],
    "PILOT": ["gates", "nominal_aar", "dest_disruption", "taxi_congestion", "downstream_legs"],
    "GROUND": ["fuel_reserve_min", "crew_duty", "alternates", "nominal_aar"],
}


@pytest.mark.parametrize("role", ROLES)
def test_view_domain_separation(role):
    view = views.domain_view(make_scenario(), make_candidates(), role, 1)
    for token in FORBIDDEN[role]:
        assert token not in view, f"{role} view leaks {token}"
    for outcome in ("ARRIVAL_DELAY", "ARRIVAL_TIME", "WHEELS_ON", "TAXI_IN"):
        assert outcome not in view
    assert "rule" not in view.lower()  # rule results never reach an agent
    assert view.rstrip().endswith("Reply by calling submit_message exactly once.")
    if role == "ATC":
        assert '"est_knock_on_min"' not in view
    else:
        assert '"est_knock_on_min"' in view


def test_view_contents_and_sources():
    s, cands = make_scenario(), make_candidates()
    atc = views.domain_view(s, cands, "ATC", 1)
    pilot = views.domain_view(s, cands, "PILOT", 1)
    ground = views.domain_view(s, cands, "GROUND", 1)
    assert "dest_disruption=14 (data)" in atc and "wake_category=L (assumed)" in atc
    assert "fuel_reserve_min=78 (estimated)" in pilot
    assert "crew_duty_remaining_min=150 (synthetic)" in pilot
    assert "alternates[0].distance_nm=190 (data)" in pilot
    assert "gates.assigned=B12 (synthetic)" in ground and "gates.free[1]=C3 (synthetic)" in ground
    assert "downstream_legs[0].SCHEDULED_DEPARTURE=828 (data)" in ground
    assert "connections.count=3 (estimated)" in ground
    assert "taxi_congestion=1.4 (data)" in ground
    for c in cands:
        assert f'"candidate_id": "{c.candidate_id}"' in atc


@pytest.mark.parametrize("role", ROLES)
def test_view_paths_resolve(role):
    s = make_scenario()
    for line in views.data_lines(s, role):
        if "...(" in line or line.startswith("connections.count="):
            continue
        m = re.match(r"^(\S+?)=(.*) \((\w+)\)$", line)
        assert m, line
        assert_citation_resolves(s, f"{m.group(1)}={m.group(2)}")


def test_view_caps_and_nulls():
    s = make_scenario().model_copy(update={
        "alternates": [{"iata": f"A{i}", "distance_nm": i} for i in range(7)],
        "gates": {f"g{i}": i for i in range(20)},
        "flight": {**make_scenario().flight, "WEATHER_DELAY": float("nan"), "TAXI_OUT": None},
    })
    pilot = views.domain_view(s, make_candidates(), "PILOT", 1)
    assert "alternates...(3 more)" in pilot and "alternates[4]" not in pilot
    assert "flight.WEATHER_DELAY=null (data)" in pilot
    ground = views.domain_view(s, make_candidates(), "GROUND", 1)
    assert "gates...(5 more)" in ground
    assert "flight.TAXI_OUT=null" in views.domain_view(s, make_candidates(), "ATC", 1)


def test_round2_view_hides_other_domain_values():
    s, cands = make_scenario(), make_candidates()
    pilot_r1 = AgentMessage(
        agent="PILOT", round=1, acceptable=["SLOT+15", "GATE_B14"],
        ranking=[{"candidate_id": "SLOT+15", "score": 0.9, "rationale": "x",
                  "cited_fields": ["fuel_reserve_min=78"]}],
        vetoes=[{"candidate_id": "HOLD40",
                 "reason": "fuel_reserve_min=78 is an estimate and a long hold draws on it",
                 "cited_field": "fuel_reserve_min=78"}],
    )
    ground_r1 = StubAgent("GROUND").propose(s, cands, 1, None)
    atc_r1 = StubAgent("ATC").propose(s, cands, 1, None)
    view = views.domain_view(s, cands, "ATC", 2, atc_r1, [pilot_r1, ground_r1])
    assert "fuel_reserve_min=" not in view and "fuel_reserve_min" not in view
    # GROUND's cited field (taxi_congestion=...) is stripped; the only occurrence is ATC's own
    # DATA line, since taxi congestion is in ATC's domain too.
    assert view.count("taxi_congestion=") == 1
    assert "PILOT veto HOLD40:" in view and "is an estimate" in view
    assert 'PILOT: acceptable ["SLOT+15", "GATE_B14"]' in view
    assert "YOUR ROUND-1 MESSAGE" in view and "OTHER AGENTS' ROUND-1 POSITIONS" in view
    assert "dest_disruption=14 (data)" in view  # its own domain is still there


# ---------------------------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("role", ROLES)
def test_prompt_files(role):
    text = load_prompt(role)
    assert f"{role} AGENT" in text
    assert TOOL_NAME in text
    # Rohan's merge gate: prompts must not contain these tokens.
    assert not re.search(r"legal|safe to|compute|calculate|minus|subtract", text, re.I)


# ---------------------------------------------------------------------------------------------
# ClaudeAgent with a scripted fake client (no network)
# ---------------------------------------------------------------------------------------------


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests: list[dict] = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.requests.append(copy.deepcopy(kwargs))
        return self.responses.pop(0)


def usage(t_in=1000, t_out=200, c_read=0, c_write=0):
    return SimpleNamespace(input_tokens=t_in, output_tokens=t_out,
                           cache_read_input_tokens=c_read, cache_creation_input_tokens=c_write)


def tool_resp(payload, u=None, stop="tool_use"):
    block = SimpleNamespace(type="tool_use", id="toolu_01", name=TOOL_NAME, input=payload)
    return SimpleNamespace(content=[block], usage=u or usage(), stop_reason=stop)


def prose_resp(text="I think SLOT+15 is best."):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], usage=usage(),
                           stop_reason="end_turn")


def good_payload():
    return {
        "acceptable": ["SLOT+15", "GATE_B14"],
        "ranking": [
            {"candidate_id": "SLOT+15", "score": 0.9, "rationale": "Small shift.",
             "cited_fields": ["fuel_reserve_min=78"]},
            {"candidate_id": "HOLD40", "score": 0.1, "rationale": "Long hold.",
             "cited_fields": []},
        ],
        "vetoes": [{"candidate_id": "HOLD40", "reason": "Draws on an estimated reserve.",
                    "cited_field": "fuel_reserve_min=78"}],
    }


def bad_payload():
    p = good_payload()
    p["ranking"][0]["score"] = 1.7  # out of range
    return p


def agent_with(responses, role="PILOT"):
    client = FakeClient(responses)
    return ClaudeAgent(role, MODEL_IDS["haiku"], client=client), client


def test_claude_valid_first_try_and_cost():
    agent, client = agent_with([tool_resp(good_payload())])
    msg = agent.propose(make_scenario(), make_candidates(), 1, None)
    assert isinstance(msg, AgentMessage) and msg.agent == "PILOT" and msg.round == 1
    assert msg.acceptable == ["SLOT+15", "GATE_B14"]
    assert len(agent.calls) == 1
    call = agent.calls[0]
    assert call["valid"] is True and call["attempt"] == 1 and call["round"] == 1
    assert call["cost_usd"] == pytest.approx((1000 * 0.10 + 200 * 0.50) / 1e6)
    assert call["cache_read_tokens"] == 0 and call["latency_s"] >= 0
    for key in ("round", "tokens_in", "tokens_out", "cache_read_tokens", "cost_usd",
                "latency_s", "valid"):
        assert key in call  # plan-rohan section 0 note 5
    assert len(client.requests) == 1


def test_claude_cache_tokens_costed():
    u = usage(t_in=100, t_out=50, c_read=700, c_write=300)
    agent, _ = agent_with([tool_resp(good_payload(), u=u)])
    agent.propose(make_scenario(), make_candidates(), 1, None)
    p = PRICES["haiku"]
    expected = (100 * p["in"] + 300 * 1.25 * p["in"] + 700 * 0.10 * p["in"] + 50 * p["out"]) / 1e6
    assert agent.calls[0]["cost_usd"] == pytest.approx(expected)
    assert agent.calls[0]["cache_read_tokens"] == 700
    assert agent.calls[0]["cache_write_tokens"] == 300


def test_claude_missing_usage_fields_default_zero():
    resp = tool_resp(good_payload(), u=SimpleNamespace(input_tokens=10, output_tokens=5))
    agent, _ = agent_with([resp])
    agent.propose(make_scenario(), make_candidates(), 1, None)
    assert agent.calls[0]["cache_read_tokens"] == 0 and agent.calls[0]["cache_write_tokens"] == 0


def test_claude_invalid_then_valid():
    agent, client = agent_with([tool_resp(bad_payload()), tool_resp(good_payload())])
    msg = agent.propose(make_scenario(), make_candidates(), 2, None)
    assert msg.round == 2
    assert [c["valid"] for c in agent.calls] == [False, True]
    assert [c["attempt"] for c in agent.calls] == [1, 2]
    second = client.requests[1]["messages"]
    assert second[-2]["role"] == "assistant"
    last_user = json.dumps(second[-1])
    assert second[-1]["role"] == "user"
    assert "failed validation" in last_user and "less than or equal to 1" in last_user
    # every tool_use in the echoed assistant turn is answered by a tool_result
    assert second[-1]["content"][0]["type"] == "tool_result"
    assert second[-1]["content"][0]["tool_use_id"] == "toolu_01"


def test_claude_invalid_twice_raises():
    extra = good_payload() | {"agent": "PILOT"}  # extra keys are forbidden
    agent, _ = agent_with([tool_resp(bad_payload()), tool_resp(extra)])
    with pytest.raises(InvalidMessage) as ei:
        agent.propose(make_scenario(), make_candidates(), 1, None)
    err = ei.value
    assert err.role == "PILOT" and err.raw_text and "agent" in err.raw_text
    assert "attempt 1:" in err.error and "attempt 2:" in err.error
    assert len(err.attempts) == 2
    assert [c["valid"] for c in agent.calls] == [False, False]


def test_claude_prose_reply_is_invalid_attempt():
    agent, client = agent_with([prose_resp(), tool_resp(good_payload())])
    agent.propose(make_scenario(), make_candidates(), 1, None)
    assert [c["valid"] for c in agent.calls] == [False, True]
    assert "prose" in agent.calls[0]["error"]
    # prose-only: assistant text is echoed and the error follows as a user turn
    second = client.requests[1]["messages"]
    assert second[-2]["role"] == "assistant" and second[-1]["role"] == "user"


def test_claude_prose_twice_raw_text_is_prose():
    agent, _ = agent_with([prose_resp("first"), prose_resp("second answer")])
    with pytest.raises(InvalidMessage) as ei:
        agent.propose(make_scenario(), make_candidates(), 1, None)
    assert ei.value.raw_text == "second answer"


def test_claude_truncated_reply_is_invalid():
    agent, _ = agent_with([tool_resp(good_payload(), stop="max_tokens"),
                           tool_resp(good_payload())])
    agent.propose(make_scenario(), make_candidates(), 1, None)
    assert [c["valid"] for c in agent.calls] == [False, True]
    assert "max_tokens" in agent.calls[0]["error"]


def test_claude_missing_cited_fields_is_invalid():
    p = good_payload()
    del p["ranking"][0]["cited_fields"]
    agent, _ = agent_with([tool_resp(p), tool_resp(p)])
    with pytest.raises(InvalidMessage):
        agent.propose(make_scenario(), make_candidates(), 1, None)


def test_claude_api_error_propagates():
    import anthropic

    class Boom:
        messages = SimpleNamespace(create=lambda **kw: (_ for _ in ()).throw(
            anthropic.APIConnectionError(request=None)))

    agent = ClaudeAgent("ATC", MODEL_IDS["haiku"], client=Boom())
    with pytest.raises(anthropic.APIError):
        agent.propose(make_scenario(), make_candidates(), 1, None)


@pytest.mark.parametrize("role", ROLES)
def test_claude_request_shape(role):
    agent, client = agent_with([tool_resp(good_payload())], role=role)
    agent.propose(make_scenario(), make_candidates(), 1, None)
    req = client.requests[0]
    assert req["model"] == MODEL_IDS["haiku"]
    assert req["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert f"{role} AGENT" in req["system"][0]["text"]
    assert req["tool_choice"] == {"type": "tool", "name": TOOL_NAME}
    assert req["tools"][0]["name"] == TOOL_NAME
    assert req["temperature"] == 0 and req["max_tokens"] == 1200
    user = req["messages"][0]["content"]
    assert user == views.domain_view(make_scenario(), make_candidates(), role, 1)


def test_unknown_model_costs_at_haiku_with_warning():
    agent = ClaudeAgent("ATC", "some-other-model", client=FakeClient([tool_resp(good_payload())]))
    with pytest.warns(UserWarning):
        agent.propose(make_scenario(), make_candidates(), 1, None)
    assert agent.calls[0]["cost_usd"] == pytest.approx((1000 * 0.10 + 200 * 0.50) / 1e6)


def test_model_ids_and_prices():
    assert set(MODEL_IDS) >= {"haiku", "sonnet"} and all(MODEL_IDS.values())
    assert PRICES["haiku"] == {"in": 0.10, "out": 0.50}


# ---------------------------------------------------------------------------------------------
# Live test: off by default. One real call per role, never more (OneShotClient enforces it).
# ---------------------------------------------------------------------------------------------


class OneShotClient:
    """Wraps the real client and allows exactly one messages.create, so a content retry fails
    the test instead of spending a second call."""

    def __init__(self, real):
        self._real, self.n = real, 0
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.n += 1
        if self.n > 1:
            raise RuntimeError("live budget: only one call allowed per role in this test")
        return self._real.messages.create(**kwargs)


@pytest.mark.skipif(not os.getenv("LIVE_AGENT_TEST"), reason="set LIVE_AGENT_TEST=1 to call the API")
@pytest.mark.parametrize("role", ROLES)
def test_live_haiku_one_call(role):
    import anthropic

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    client = OneShotClient(anthropic.Anthropic(max_retries=0, timeout=60))
    agent = ClaudeAgent(role, MODEL_IDS["haiku"], client=client)
    s, cands = make_scenario(), make_candidates()
    msg = agent.propose(s, cands, 1, None)
    AgentMessage.model_validate(msg.model_dump())
    ids = {c.candidate_id for c in cands}
    print(f"\n{role} reply: acceptable={msg.acceptable} "
          f"vetoes={[v['candidate_id'] for v in msg.vetoes]}")
    print(f"{role} first ranking item: {json.dumps(msg.ranking[0])}")
    print(f"{role} calls: {json.dumps(agent.calls)}")
    assert agent.calls[0]["valid"] is True and len(agent.calls) == 1
    unknown = ({r["candidate_id"] for r in msg.ranking} | set(msg.acceptable)) - ids
    print(f"{role} unknown candidate ids: {sorted(unknown)}")
