"""Tests for src/reviewer/safety.py. Owner: Rohan (L).

Hand-built scenario, independent of tests/fixtures and src/rules. All expected numbers worked by hand:

  fuel_reserve_min 78 (estimated), crew_duty_remaining_min 150 (synthetic), wake L (assumed),
  nominal_aar 90 (assumed), dest_disruption 14 (data), alternate AUS 190 NM.

  FUEL  SLOT+15: 78 - 15 = 63 >= 45 pass | HOLD40: 78 - 40 = 38 < 45 FAIL
        DIVERT_AUS: 190 / 7 = 27.14 min airborne, 78 - 27.14 = 50.86 >= 45 pass
  DUTY  SLOT+15: 150 - 15 = 135 | HOLD40: 150 - 40 = 110 | DIVERT_AUS: 150 - (27.14 + 60) = 62.86
  WAKE  any follower behind an assumed Large leader = 3 NM; required = 3 / (140 / 3600) = 77.14 s
        available per runway = 3600 * 2 runways / (90 - 14) = 94.74 s -> pass (every candidate)
        WAKE_FAIL variant (nominal_aar 120): 3600 * 2 / (120 - 14) = 67.92 s < 77.14 s -> FAIL
        boundary: aar - disruption = 93/h -> 77.42 s pass, 94/h -> 76.60 s FAIL
"""

import pytest

from src.reviewer.safety import (
    ASSUMED_ARRIVAL_RUNWAYS,
    ASSUMED_LEADER_CATEGORY,
    CIT_WAKE,
    CIT_WAKE_LEADER,
    CIT_WAKE_RUNWAYS,
    WAKE_SEP_NM_BEHIND_LARGE,
    review,
    review_detail,
)
from src.schemas import AgentMessage, Candidate, Recommendation, RuleResult, Scenario, Tagged, Turn

REQUIRED_S = 3 / (140 / 3600)  # 77.142857...
AVAIL = 3600 * 2 / 76  # 94.736...
AVAIL_FAIL = 3600 * 2 / 106  # 67.924...
DIVERT_AIR = 190 / 7  # 27.142857...
DIVERT_DELAY = DIVERT_AIR + 60  # 87.142857...


def make_scenario(**over) -> Scenario:
    base = dict(
        scenario_id="2015-01-01_AA334_N3DAAA",
        row_index=0,
        flight={"AIRLINE": "AA", "FLIGHT_NUMBER": 334, "ARRIVAL_DELAY": 101, "DESTINATION_AIRPORT": "DFW"},
        dest_disruption=Tagged(value=14, source="data"),
        taxi_congestion=Tagged(value=1.3, source="data"),
        downstream_legs=[],
        alternates=[{"iata": "AUS", "distance_nm": 190}],
        wake_category=Tagged(value="L", source="assumed"),
        fuel_reserve_min=Tagged(value=78, source="estimated"),
        crew_duty_remaining_min=Tagged(value=150, source="synthetic"),
        gates={"B12": {"free": True}},
        connections=[],
        nominal_aar=Tagged(value=90, source="assumed"),
    )
    base.update(over)
    return Scenario(**base)


def wake_fail_scenario(**over) -> Scenario:
    """Busy destination: 120/h nominal, only 14 disrupted -> 106/h, too tight for 3 NM."""
    return make_scenario(nominal_aar=Tagged(value=120, source="assumed"), **over)


SLOT15 = Candidate(candidate_id="SLOT+15", kind="slot_shift", params={"shift_min": 15}, est_delay_min=15, est_knock_on_min=0)
HOLD40 = Candidate(candidate_id="HOLD40", kind="hold", params={"minutes": 40}, est_delay_min=40, est_knock_on_min=0)
DIVERT = Candidate(candidate_id="DIVERT_AUS", kind="divert", params={"iata": "AUS"}, est_delay_min=87, est_knock_on_min=0)
MENU = [SLOT15, HOLD40, DIVERT]


def rec(chosen, rule_results=(), decided_by="consensus") -> Recommendation:
    return Recommendation(
        scenario_id="2015-01-01_AA334_N3DAAA",
        chosen=chosen,
        decided_by=decided_by,
        rounds_used=1,
        rule_results=list(rule_results),
        reviewer_verdict="APPROVE",
        reviewer_notes=[],
        log_path="runs/test.jsonl",
    )


def rr(rule_id, cid, passed) -> RuleResult:
    return RuleResult(
        rule_id=rule_id, candidate_id=cid, passed=passed, observed=0, threshold=0, source="assumed", citation="engine"
    )


def msg(agent, acceptable, cited, cid="SLOT+15", round_=1, vetoes=()) -> AgentMessage:
    return AgentMessage(
        agent=agent,
        round=round_,
        acceptable=list(acceptable),
        ranking=[{"candidate_id": cid, "score": 0.9, "rationale": "x", "cited_fields": list(cited)}],
        vetoes=list(vetoes),
    )


def turn(*messages, round_=1) -> Turn:
    return Turn(round=round_, messages=list(messages), invalid_messages=[], intersection=[])


def entry(detail, check, cid):
    return next(e for e in detail["re_derived"] if e["check"] == check and e["candidate_id"] == cid)


GOOD_CITES = [
    "fuel_reserve_min=78",
    "crew_duty_remaining_min=150",
    "alternates[0].distance_nm=190",
    "flight.ARRIVAL_DELAY=101",
    "wake_category=l",  # strings are case-insensitive
    "dest_disruption",  # no "=": existence only
]


def consensus_turns(extra_cite=None):
    cites = GOOD_CITES + ([extra_cite] if extra_cite else [])
    return [
        turn(
            msg("ATC", ["SLOT+15"], GOOD_CITES),
            msg("PILOT", ["SLOT+15", "DIVERT_AUS"], cites),
            msg(
                "GROUND",
                ["SLOT+15"],
                ["gates.B12.free=True"],
                vetoes=[{"candidate_id": "HOLD40", "reason": "fuel", "cited_field": "fuel_reserve_min=78"}],
            ),
        )
    ]


# ---- WAKE ----------------------------------------------------------------------------------------
def test_wake_assumptions_are_named_and_cited_as_assumed():
    assert ASSUMED_LEADER_CATEGORY == "L" and WAKE_SEP_NM_BEHIND_LARGE == 3.0
    assert ASSUMED_ARRIVAL_RUNWAYS == 2
    assert "assumed" in CIT_WAKE_LEADER and "assumed" in CIT_WAKE_RUNWAYS
    assert "7110.65" in CIT_WAKE and CIT_WAKE_LEADER in CIT_WAKE and CIT_WAKE_RUNWAYS in CIT_WAKE


def test_wake_passes_at_fixture_numbers():
    d = review_detail(make_scenario(), rec(SLOT15), [], candidates=MENU)
    for cid in ("SLOT+15", "HOLD40", "DIVERT_AUS"):
        w = entry(d, "WAKE", cid)
        assert w["threshold"] == pytest.approx(REQUIRED_S)
        assert w["derived"] == pytest.approx(AVAIL)
        assert w["passed"] is True
    assert w["inputs"]["effective_aar"] == 76 and w["inputs"]["arrival_runways"] == 2
    assert d["verdict"] == "APPROVE"
    assert any(
        n.startswith("WAKE re-derived: SLOT+15") and "77.1 s" in n and "94.7 s per runway" in n and "PASS" in n
        for n in d["notes"]
    )


def test_wake_fails_at_busy_destination_and_engine_pass_is_disagreement():
    rules = [rr("R-WAKE-01", "SLOT+15", True)]
    d = review_detail(wake_fail_scenario(), rec(SLOT15, rules), consensus_turns(), candidates=MENU)
    w = entry(d, "WAKE", "SLOT+15")
    assert w["derived"] == pytest.approx(AVAIL_FAIL) and w["passed"] is False
    assert all(not entry(d, "WAKE", c.candidate_id)["passed"] for c in MENU)  # airport-level
    assert entry(d, "FUEL", "SLOT+15")["passed"] and entry(d, "DUTY", "SLOT+15")["passed"]
    assert d["verdict"] == "REJECT"
    assert any(n.startswith("WAKE re-derived: SLOT+15") and "67.9 s" in n and "FAIL" in n for n in d["notes"])
    assert d["engine_disagreements"] == [
        {"rule_id": "R-WAKE-01", "candidate_id": "SLOT+15", "engine_passed": True, "reviewer_passed": False}
    ]
    assert any("required 77.1 s, available 67.9 s" in n for n in d["notes"])


@pytest.mark.parametrize("aar,passed", [(107, True), (108, False)])
def test_wake_boundary(aar, passed):
    # 107 - 14 = 93/h -> 77.42 s >= 77.14 s; 108 - 14 = 94/h -> 76.60 s < 77.14 s
    d = review_detail(make_scenario(nominal_aar=Tagged(value=aar, source="assumed")), rec(SLOT15), [])
    assert entry(d, "WAKE", "SLOT+15")["passed"] is passed


@pytest.mark.parametrize("cat", ["H", "L", "S", "J"])
def test_wake_separation_same_for_every_follower_behind_large(cat):
    d = review_detail(make_scenario(wake_category=Tagged(value=cat, source="assumed")), rec(SLOT15), [])
    w = entry(d, "WAKE", "SLOT+15")
    assert w["inputs"]["sep_nm"] == 3.0 and w["threshold"] == pytest.approx(REQUIRED_S)
    assert w["passed"] is True and w["inputs"]["leader_category"] == "L"


def test_wake_disruption_floor():
    # nominal 10 - disruption 14 -> effective floor 1/h -> 7200 s available
    d = review_detail(make_scenario(nominal_aar=Tagged(value=10, source="assumed")), rec(SLOT15), [])
    assert entry(d, "WAKE", "SLOT+15")["derived"] == pytest.approx(7200)


# ---- (1) APPROVE ----------------------------------------------------------------------------------
def test_approve_slot15_with_correct_citations():
    s = make_scenario()
    r = rec(SLOT15, [rr("R-FUEL-01", "SLOT+15", True), rr("R-DUTY-01", "SLOT+15", True), rr("R-WAKE-01", "SLOT+15", True)])
    verdict, notes = review(s, r, consensus_turns())
    assert verdict == "APPROVE", notes
    d = r.reviewer_detail
    assert d is not None and d["verdict"] == "APPROVE" and d["notes"] == notes
    assert d["cited_mismatches"] == [] and d["engine_disagreements"] == []
    assert d["citations_checked"] == 6 + 6 + 1 + 1
    assert d["citations_with_value"] == 5 + 5 + 1 + 1  # "dest_disruption" has no "=" (x2)
    assert d["derived_delay_min"] == pytest.approx(15)
    assert entry(d, "FUEL", "SLOT+15")["derived"] == pytest.approx(63)
    assert entry(d, "DUTY", "SLOT+15")["derived"] == pytest.approx(135)
    assert entry(d, "WAKE", "SLOT+15")["derived"] == pytest.approx(AVAIL)
    assert all("[" in n and "]" in n for n in notes)  # every note cites a source
    assert any("assumed" in n for n in notes if n.startswith("FUEL"))


def test_agents_none_no_turns_approves_on_rederivation_alone():
    assert review(make_scenario(), rec(SLOT15, decided_by="fallback"), [])[0] == "APPROVE"
    assert review(make_scenario(), rec(HOLD40, decided_by="fallback"), [])[0] == "REJECT"


# ---- (2) REJECT on HOLD40 fuel --------------------------------------------------------------------
def test_reject_hold40_fuel():
    verdict, notes = review(make_scenario(), rec(HOLD40), [])
    assert verdict == "REJECT"
    fuel_note = next(n for n in notes if n.startswith("FUEL re-derived"))
    assert "needs 40+45=85 min" in fuel_note
    assert "fuel_reserve_min=78 (estimated)" in fuel_note
    assert "leaves 38 min" in fuel_note and "FAIL" in fuel_note and "14 CFR 121.639" in fuel_note
    d = review_detail(make_scenario(), rec(HOLD40), [])
    assert entry(d, "FUEL", "HOLD40")["derived"] == pytest.approx(38)
    assert entry(d, "DUTY", "HOLD40")["passed"] is True  # 150 - 40 = 110


def test_engine_pass_does_not_rescue_reviewer_fail():
    # rule_results never decide: the engine passing HOLD40 on fuel must not change REJECT
    d = review_detail(make_scenario(), rec(HOLD40, [rr("R-FUEL-01", "HOLD40", True)]), [])
    assert d["verdict"] == "REJECT"
    assert d["engine_disagreements"] == [
        {"rule_id": "R-FUEL-01", "candidate_id": "HOLD40", "engine_passed": True, "reviewer_passed": False}
    ]


# ---- (3) DIVERT_AUS and the engine-disagreement path ----------------------------------------------
def test_divert_aus_numbers():
    d = review_detail(make_scenario(), rec(DIVERT), [])
    assert entry(d, "FUEL", "DIVERT_AUS")["derived"] == pytest.approx(78 - DIVERT_AIR)
    assert entry(d, "FUEL", "DIVERT_AUS")["passed"] is True
    assert entry(d, "DUTY", "DIVERT_AUS")["derived"] == pytest.approx(150 - DIVERT_DELAY)
    assert entry(d, "DUTY", "DIVERT_AUS")["passed"] is True
    assert d["derived_delay_min"] == pytest.approx(DIVERT_DELAY)
    assert d["verdict"] == "APPROVE"  # est 87 vs 87.14 agrees


def test_engine_disagreement_on_non_chosen_is_modify():
    rules = [
        rr("R-DUTY-01", "DIVERT_AUS", False),  # reviewer passes it (62.86 min left) -> disagreement
        rr("R-FUEL-01", "HOLD40", False),  # reviewer agrees (38 < 45)
        rr("R-FUEL-01", "SLOT+15", True),
    ]
    d = review_detail(make_scenario(), rec(SLOT15, rules), consensus_turns(), candidates=MENU)
    assert d["verdict"] == "MODIFY"
    assert d["engine_disagreements"] == [
        {"rule_id": "R-DUTY-01", "candidate_id": "DIVERT_AUS", "engine_passed": False, "reviewer_passed": True}
    ]
    assert any(n.startswith("ENGINE: R-DUTY-01 failed DIVERT_AUS, reviewer passes it") for n in d["notes"])


def test_engine_failing_chosen_is_reject():
    d = review_detail(make_scenario(), rec(DIVERT, [rr("R-DUTY-01", "DIVERT_AUS", False)]), [])
    assert d["verdict"] == "REJECT"
    assert any("ENGINE: R-DUTY-01 failed chosen DIVERT_AUS" in n and "REJECT" in n for n in d["notes"])
    assert len(d["engine_disagreements"]) == 1
    # any engine rule, not only FUEL/DUTY/WAKE
    assert review(make_scenario(), rec(SLOT15, [rr("R-GATE-01", "SLOT+15", False)]), [])[0] == "REJECT"


def test_engine_results_without_params_are_reported_not_decisive():
    d = review_detail(make_scenario(), rec(SLOT15, [rr("R-FUEL-01", "HOLD40", True)]), [])
    assert d["verdict"] == "APPROVE"
    assert d["not_rederived"] == ["HOLD40"]
    assert any("no params were passed for HOLD40" in n for n in d["notes"])


# ---- (4) cited-value mismatch ---------------------------------------------------------------------
def test_cited_fuel_95_is_modify():
    d = review_detail(make_scenario(), rec(SLOT15), consensus_turns(extra_cite="fuel_reserve_min=95"))
    assert d["verdict"] == "MODIFY"
    (m,) = d["cited_mismatches"]
    assert m["agent"] == "PILOT" and m["path"] == "fuel_reserve_min" and m["cited"] == "95"
    assert m["actual"] == 78 and m["tolerance"] == pytest.approx(1.56) and m["candidate_id"] == "SLOT+15"
    assert any(
        n.startswith("CITED: PILOT ranked SLOT+15") and "fuel_reserve_min=95" in n and "scenario has 78 (estimated" in n
        for n in d["notes"]
    )


@pytest.mark.parametrize("value,ok", [("79", True), ("76.5", True), ("80", False), ("78.0", True), ("seventy", False)])
def test_cited_numeric_tolerance(value, ok):
    # tolerance = max(1.0, 2% of 78) = 1.56
    d = review_detail(make_scenario(), rec(SLOT15), consensus_turns(extra_cite=f"fuel_reserve_min={value}"))
    assert (d["cited_mismatches"] == []) is ok


@pytest.mark.parametrize("value,ok", [("78 (estimated)", True), ("78(Estimated)", True), ("95 (estimated)", False)])
def test_cited_source_tag_suffix_is_ignored(value, ok):
    # Agents see "path=value (source)" and copy the tag into their citation.
    d = review_detail(make_scenario(), rec(SLOT15), consensus_turns(extra_cite=f"fuel_reserve_min={value}"))
    assert (d["cited_mismatches"] == []) is ok


@pytest.mark.parametrize("value,ok", [("15.0", True), ("40", False)])
def test_cited_candidate_field_resolves_on_ranked_candidate(value, ok):
    # est_delay_min is a Candidate field, not a Scenario path; SLOT+15's estimate is 15.
    d = review_detail(make_scenario(), rec(SLOT15), consensus_turns(extra_cite=f"est_delay_min={value}"))
    assert (d["cited_mismatches"] == []) is ok


def test_cited_string_mismatch_and_veto_field():
    t = [turn(msg("ATC", ["SLOT+15"], [], vetoes=[{"candidate_id": "HOLD40", "reason": "x", "cited_field": "wake_category=H"}]))]
    d = review_detail(make_scenario(), rec(SLOT15), t)
    assert d["verdict"] == "MODIFY"
    assert d["cited_mismatches"][0]["path"] == "wake_category"
    assert any(n.startswith("CITED: ATC vetoed HOLD40") for n in d["notes"])


# ---- (5) unknown path -----------------------------------------------------------------------------
@pytest.mark.parametrize("cite", ["foo.bar=1", "alternates[3].distance_nm=190", "flight.NOPE=1", "foo"])
def test_unknown_field_is_mismatch(cite):
    d = review_detail(make_scenario(), rec(SLOT15), consensus_turns(extra_cite=cite))
    assert d["verdict"] == "MODIFY"
    (m,) = d["cited_mismatches"]
    assert m["reason"] == "unknown_field" and m["actual"] == "unknown_field"
    assert any("mismatch unknown_field" in n for n in d["notes"])


def test_non_supporting_agent_citations_ignored_supporter_all_rounds_checked():
    t = [
        # PILOT does not accept SLOT+15 in round 1 but does in round 2: its round-1 cite is checked.
        turn(msg("PILOT", ["DIVERT_AUS"], ["fuel_reserve_min=95"]), msg("GROUND", ["SLOT+15"], []), round_=1),
        # GROUND drops SLOT+15 in round 2: its bad cite is not a supporting citation.
        turn(
            msg("PILOT", ["SLOT+15"], ["fuel_reserve_min=78"], round_=2),
            msg("GROUND", ["DIVERT_AUS"], ["foo.bar=1"], round_=2),
            round_=2,
        ),
    ]
    d = review_detail(make_scenario(), rec(SLOT15), t)
    assert [(m["agent"], m["round"], m["path"]) for m in d["cited_mismatches"]] == [("PILOT", 1, "fuel_reserve_min")]


# ---- (6) chosen=None ------------------------------------------------------------------------------
def test_chosen_none_is_reject():
    verdict, notes = review(make_scenario(), rec(None, decided_by="fallback"), consensus_turns())
    assert verdict == "REJECT"
    assert any(n.startswith("CHOSEN: no candidate was chosen") for n in notes)


# ---- delay re-derivation and params ---------------------------------------------------------------
def test_delay_disagreement_is_modify_note():
    bad = SLOT15.model_copy(update={"est_delay_min": 40})  # derived 15, off by 25 (> 20%, > 5)
    d = review_detail(make_scenario(), rec(bad), [])
    assert d["verdict"] == "MODIFY"
    assert any(n.startswith("DELAY: SLOT+15 re-derived delay is 15 min but est_delay_min=40") for n in d["notes"])
    close = SLOT15.model_copy(update={"est_delay_min": 19})  # off by 4 (< 5 min)
    assert review(make_scenario(), rec(close), [])[0] == "APPROVE"


def test_missing_param_noted_and_unknown_alternate_fails_closed():
    no_min = Candidate(candidate_id="HOLD?", kind="hold", params={}, est_delay_min=0, est_knock_on_min=0)
    verdict, notes = review(make_scenario(), rec(no_min), [])
    assert verdict == "APPROVE"
    assert any(n.startswith("PARAMS: HOLD? (hold) has no 'minutes' param") for n in notes)

    div_x = Candidate(candidate_id="DIVERT_XXX", kind="divert", params={"iata": "XXX"}, est_delay_min=60, est_knock_on_min=0)
    d = review_detail(make_scenario(), rec(div_x), [])
    assert d["verdict"] == "REJECT"
    assert entry(d, "FUEL", "DIVERT_XXX")["passed"] is False
    assert entry(d, "DUTY", "DIVERT_XXX")["passed"] is False


def test_negative_slot_shift_and_gate_swap():
    early = Candidate(candidate_id="SLOT-10", kind="slot_shift", params={"shift_min": -10}, est_delay_min=-10, est_knock_on_min=0)
    d = review_detail(make_scenario(), rec(early), [])
    assert entry(d, "FUEL", "SLOT-10")["derived"] == pytest.approx(78)  # max(shift, 0) airborne
    assert entry(d, "DUTY", "SLOT-10")["derived"] == pytest.approx(160)
    gate = Candidate(candidate_id="GATE_B12", kind="gate_swap", params={"gate": "B12", "extra_taxi_min": 6}, est_delay_min=6, est_knock_on_min=0)
    d = review_detail(make_scenario(), rec(gate), [])
    assert d["derived_delay_min"] == pytest.approx(6) and d["verdict"] == "APPROVE"
