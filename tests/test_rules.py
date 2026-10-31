import pytest

from src.options.menu import generate_candidates
from src.rules.engine import RULE_IDS, check_all
from src.scenario.builder import build_scenario
from src.schemas import Candidate

AA334_ROW = 123017


@pytest.fixture(scope="module")
def aa334():
    s = build_scenario(AA334_ROW)
    c = generate_candidates(s)
    return s, c, check_all(s, c)


@pytest.fixture(scope="module")
def row0():
    s = build_scenario(0)
    c = generate_candidates(s)
    return s, c, check_all(s, c)


def _by(results):
    return {(r.candidate_id, r.rule_id): r for r in results}


def test_one_result_per_pair_in_stable_order(aa334):
    s, cands, rr = aa334
    assert len(RULE_IDS) == 7 and len(rr) == len(RULE_IDS) * len(cands)
    assert [(r.candidate_id, r.rule_id) for r in rr] == [
        (c.candidate_id, rid) for c in cands for rid in RULE_IDS
    ]


def test_every_result_cites_a_source(aa334, row0):
    for _, _, rr in (aa334, row0):
        for r in rr:
            assert r.citation and r.source in {"data", "estimated", "assumed", "synthetic"}
    by = _by(aa334[2])
    assert by[("SLOT+15", "R-DUTY-01")].source == "synthetic"
    assert by[("SLOT+15", "R-GATE-01")].source == "synthetic"
    assert by[("HOLD40", "R-FUEL-01")].source == "estimated"


def test_aa334_escalates_under_workbook_capacity(aa334):
    # Organiser workbook: DFW 90 runway ops/h -> 45 arrivals/h (0.5 share, assumed). With 26 delayed
    # arrivals in the 14:00 weather hour, demand 0.6 x 45 + 26 + 1 = 54 > weather-cut cap 38.1, so
    # every non-divert option fails R-AAR-01 and both diverts fail R-TURN-01: no legal option, the
    # case escalates to a human (docs/constraints.md). Before the workbook (AAR 118) it had options.
    _, cands, rr = aa334
    assert len(cands) >= 8
    failing = {r.candidate_id for r in rr if not r.passed}
    assert failing == {c.candidate_id for c in cands}
    aar = [r for r in rr if r.rule_id == "R-AAR-01" and not r.passed]
    assert {r.candidate_id for r in aar} == {c.candidate_id for c in cands if c.kind != "divert"}
    assert _by(rr)[("SLOT+15", "R-AAR-01")].observed == pytest.approx(54)


def test_fuel_spare_covers_45_min_hold_not_more(aa334):
    # Workbook: 45 min spare fuel on arrival above alternate + 30 min final reserve.
    s, cands, rr = aa334
    by = _by(rr)
    hold40 = by[("HOLD40", "R-FUEL-01")]
    assert hold40.passed
    assert hold40.observed == pytest.approx(s.fuel_reserve_min.value - 40, abs=0.1)
    assert hold40.observed - hold40.threshold == pytest.approx(5, abs=0.1)
    assert by[("HOLD20", "R-FUEL-01")].observed > hold40.observed
    hold50 = Candidate(candidate_id="HOLD50", kind="hold", params={"minutes": 50}, est_delay_min=50, est_knock_on_min=0)
    fuel50 = next(r for r in check_all(s, [hold50]) if r.rule_id == "R-FUEL-01")
    assert not fuel50.passed
    gate_swap = next(c.candidate_id for c in cands if c.kind == "gate_swap")
    assert by[(gate_swap, "R-FUEL-01")].passed and by[("GROUND_HOLD_MFE", "R-FUEL-01")].passed
    # diverts only need the 30 min final reserve on arrival at the alternate
    assert by[("DIVERT_ACT", "R-FUEL-01")].threshold == 30
    assert "organiser workbook" in hold40.citation


def test_divert_gate_not_applicable(aa334):
    r = _by(aa334[2])[("DIVERT_ACT", "R-GATE-01")]
    assert r.passed and str(r.observed).startswith("n/a")


def test_row0_duty_fails_on_incurred_delay(row0):
    s, cands, rr = row0
    assert s.flight["ARRIVAL_DELAY"] == 300
    duty = [r for r in rr if r.rule_id == "R-DUTY-01"]
    assert len(duty) == len(cands) and not any(r.passed for r in duty)
    assert all(r.source == "synthetic" for r in duty)


def test_deterministic(aa334):
    s, cands, rr = aa334
    assert check_all(s, cands) == rr
    s2 = build_scenario(AA334_ROW)
    assert check_all(s2, generate_candidates(s2)) == rr


def test_unknown_param_does_not_crash(aa334):
    s, _, _ = aa334
    odd = Candidate(candidate_id="DIVERT_XXX", kind="divert", params={"iata": "XXX"},
                    est_delay_min=0, est_knock_on_min=0)
    assert len(check_all(s, [odd])) == len(RULE_IDS)


def test_wake_inputs_match_reviewer_and_come_from_workbook(aa334):
    # Engine and reviewer read the same workbook values through src/constraints.py.
    from src import constraints
    from src.reviewer import safety
    from src.reviewer.safety import review_detail
    from src.rules import engine
    from src.schemas import Recommendation

    assert engine.LEADER_CATEGORY == safety.ASSUMED_LEADER_CATEGORY == "L"
    assert engine.APPROACH_KT == safety.APPROACH_KT
    s, cands, rr = aa334
    wake = _by(rr)[("SLOT+15", "R-WAKE-01")]
    nm = constraints.wake_sep_nm("L", s.wake_category.value)
    assert nm == 3.0 and wake.threshold == pytest.approx(nm / safety.APPROACH_KT * 3600, abs=0.1)
    assert "organiser workbook" in wake.citation and "4 active runway" in wake.citation  # DFW
    rec = Recommendation(scenario_id=s.scenario_id, chosen=cands[0], decided_by="fallback", rounds_used=0,
                         rule_results=rr, reviewer_verdict="APPROVE", reviewer_notes=[], log_path="x")
    d = review_detail(s, rec, [], candidates=cands)
    w = next(e for e in d["re_derived"] if e["check"] == "WAKE" and e["candidate_id"] == "SLOT+15")
    assert w["threshold"] == pytest.approx(wake.threshold, abs=0.1)
    assert w["inputs"]["arrival_runways"] == constraints.airport("DFW").active_runways == 4


def test_engine_and_reviewer_share_workbook_fuel_and_duty():
    from src import constraints
    from src.reviewer import safety
    from src.rules import engine

    assert engine.FINAL_RESERVE_MIN == safety.FUEL_FINAL_RESERVE_MIN == constraints.fuel_crew("final_reserve_min") == 30
    assert engine.FDP_LIMIT_MIN == safety.CREW_MAX_DUTY_MIN == constraints.fuel_crew("crew_max_duty_min") == 13 * 60


@pytest.mark.parametrize("row", [AA334_ROW, 0])
def test_engine_and_reviewer_agree_on_fuel_and_wake_real_rows(row):
    # FUEL and WAKE verdicts agree on every candidate (DUTY: tests/test_reviewer.py, diverts differ).
    from src.reviewer.safety import review_detail
    from src.schemas import Recommendation

    s = build_scenario(row)
    cands = generate_candidates(s)
    rr = check_all(s, cands)
    rec = Recommendation(scenario_id=s.scenario_id, chosen=cands[0], decided_by="fallback", rounds_used=0,
                         rule_results=rr, reviewer_verdict="APPROVE", reviewer_notes=[], log_path="x")
    d = review_detail(s, rec, [], candidates=cands)
    assert not [e for e in d["engine_disagreements"] if e["rule_id"] in ("R-FUEL-01", "R-WAKE-01")]


def test_gate_notice_rule(aa334, monkeypatch):
    from src.rules import engine

    s, cands, rr = aa334
    by = _by(rr)
    swap = next(c for c in cands if c.kind == "gate_swap")
    r = by[(swap.candidate_id, "R-GATE-02")]
    assert r.passed and r.threshold == 20 and "organiser workbook" in r.citation
    assert r.observed == pytest.approx(engine.GATE_DECISION_LEAD_MIN + swap.params["extra_taxi_min"])
    assert str(by[("SLOT+15", "R-GATE-02")].observed).startswith("n/a") and by[("SLOT+15", "R-GATE-02")].passed
    # A decision taken only 10 min before gate-in gives < 20 min notice -> fails.
    monkeypatch.setattr(engine, "GATE_DECISION_LEAD_MIN", 10)
    late = next(x for x in check_all(s, [swap]) if x.rule_id == "R-GATE-02")
    assert not late.passed and late.observed < 20
