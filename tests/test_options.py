import pytest

from src.options.menu import (
    airborne_extra_min,
    generate_candidates,
    knock_on_min,
    new_arrival_abs,
)
from src.scenario.builder import build_scenario

AA334_ROW = 123017


@pytest.fixture(scope="module")
def aa334():
    s = build_scenario(AA334_ROW)
    return s, generate_candidates(s)


def test_aa334_menu(aa334):
    s, cands = aa334
    ids = [c.candidate_id for c in cands]
    assert 8 <= len(cands) <= 12
    assert ids[:6] == ["SLOT+15", "SLOT+30", "SLOT-15", "SLOT-30", "HOLD20", "HOLD40"]
    assert {"DIVERT_ACT", "DIVERT_TYR", "GROUND_HOLD_MFE"} <= set(ids)
    assert sum(c.kind == "gate_swap" for c in cands) == 2
    assert len(set(ids)) == len(ids)


def test_param_conventions(aa334):
    s, cands = aa334
    keys = {"hold": {"minutes"}, "slot_shift": {"shift_min"}, "divert": {"iata"},
            "ground_hold": {"minutes", "airport"}, "gate_swap": {"gate", "extra_taxi_min"}}
    for c in cands:
        assert set(c.params) == keys[c.kind]
    gates = [c for c in cands if c.kind == "gate_swap"]
    assert all(c.params["gate"] != s.gates["assigned_gate"] for c in gates)


def test_delay_estimates(aa334):
    s, cands = aa334
    by = {c.candidate_id: c for c in cands}
    assert by["SLOT-30"].est_delay_min == -30
    assert by["HOLD40"].est_delay_min == 40
    assert airborne_extra_min(s, by["HOLD40"]) == 40
    assert airborne_extra_min(s, by["SLOT-30"]) == 0
    d = s.alternates[0]["distance_nm"]
    assert by["DIVERT_ACT"].est_delay_min == pytest.approx(2 * d / 7 + 60, abs=0.1)
    assert new_arrival_abs(s, by["HOLD20"]) == s.flight["actual_arr_abs"] + 20
    # later arrival never reduces knock-on
    assert by["HOLD40"].est_knock_on_min >= by["HOLD20"].est_knock_on_min >= by["SLOT-30"].est_knock_on_min
    assert by["HOLD20"].est_knock_on_min > 0  # AA334 landed after its next leg was due out


def test_no_downstream_legs_no_knock_on(aa334):
    s, _ = aa334
    bare = s.model_copy(update={"downstream_legs": []})
    assert knock_on_min(bare, s.flight["actual_arr_abs"] + 500) == 0


def test_deterministic():
    s = build_scenario(0)
    assert generate_candidates(s) == generate_candidates(build_scenario(0))
    assert 5 <= len(generate_candidates(s)) <= 12
