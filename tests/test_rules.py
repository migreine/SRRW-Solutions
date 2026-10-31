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
    assert len(rr) == 6 * len(cands)
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


def test_aa334_has_failures_and_a_safe_option(aa334):
    _, cands, rr = aa334
    assert len(cands) >= 8
    assert any(not r.passed for r in rr)
    failing = {r.candidate_id for r in rr if not r.passed}
    assert set(c.candidate_id for c in cands) - failing  # at least one candidate passes everything


def test_hold40_fails_fuel_hold_shorter_needs_less(aa334):
    s, _, rr = aa334
    by = _by(rr)
    hold40 = by[("HOLD40", "R-FUEL-01")]
    assert not hold40.passed
    assert hold40.observed == pytest.approx(s.fuel_reserve_min.value - 40, abs=0.1)
    assert by[("HOLD20", "R-FUEL-01")].observed > hold40.observed
    assert by[("GATE_C6", "R-FUEL-01")].passed and by[("GROUND_HOLD_MFE", "R-FUEL-01")].passed
    # diverts only need the 45 min final reserve on arrival at the alternate
    assert by[("DIVERT_ACT", "R-FUEL-01")].threshold == 45


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
    assert len(check_all(s, [odd])) == 6
