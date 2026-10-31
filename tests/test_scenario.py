import pytest

from src.scenario.builder import (
    ASSIGNED_GATE_NEXT_GAP,
    ASSIGNED_GATE_PREV_GAP,
    DUTY_REMAINING_RANGE,
    EXCLUDED_ALTERNATES,
    _alternates,
    arrival_hour_stats,
    delayed_arrivals_in_hour,
    planned_alternate_min,
    build_scenario,
    hhmm_to_min,
    load_flights,
)

AA334_ROW = 123017  # AA334 MFE->DFW, N469AA, 24 Apr 2015 (docs/briefing.md section 4.5)


def test_hhmm_to_min():
    assert hhmm_to_min(1305) == 785
    assert hhmm_to_min(5) == 5
    assert hhmm_to_min(2400) == 0
    assert hhmm_to_min(float("nan")) is None


def test_aa334_showcase():
    s = build_scenario(AA334_ROW)
    assert s.scenario_id == "2015-04-24_AA334_N469AA"
    assert s.flight["ARRIVAL_DELAY"] == 101
    assert s.flight["sched_arr_abs"] == 12 * 60 + 55
    assert s.flight["actual_arr_abs"] == 12 * 60 + 55 + 101
    legs = [(leg["flight_number"], leg["origin"], leg["destination"]) for leg in s.downstream_legs]
    assert legs == [(1389, "DFW", "MEM"), (1389, "MEM", "DFW"), (1274, "DFW", "BWI")]
    # The aircraft landed after its next leg was due out: the cascade the Ground agent sees.
    assert s.downstream_legs[0]["gap_after_actual_arrival_min"] < 0
    assert s.dest_disruption.source == "data" and s.dest_disruption.value > 0
    # DAL (9.8 nm) is skipped: inside MIN_ALTERNATE_NM, same terminal area and weather.
    assert [a["iata"] for a in s.alternates] == ["ACT", "TYR", "SPS"]
    assert all(a["distance_nm"] >= 30 for a in s.alternates)


def test_row_0_builds():
    s = build_scenario(0)
    assert s.row_index == 0
    assert s.flight["DESTINATION_AIRPORT"] == "HNL"
    assert s.wake_category.value == "H"  # DFW-HNL 3784 mi


def test_source_tags():
    s = build_scenario(AA334_ROW)
    assert s.wake_category.source == "assumed"
    assert s.fuel_reserve_min.source == "estimated"
    assert s.crew_duty_remaining_min.source == "synthetic"
    assert s.nominal_aar.source == "assumed"
    assert s.gates["source"] == "synthetic"
    assert all(c["source"] == "estimated" for c in s.connections)


def test_seeded_and_locked():
    a, b = build_scenario(AA334_ROW), build_scenario(AA334_ROW)
    assert a == b
    assert build_scenario(AA334_ROW, seed=7).gates != a.gates


def test_assigned_gate_free_for_planned_turn():
    # The gate plan is re-flowed to the projected gate-in (actual_arr_abs), docs/calibration.md.
    s = build_scenario(AA334_ROW)
    g = s.gates
    start = s.flight["actual_arr_abs"]
    end = start + g["min_turnaround_min"]
    for busy_start, busy_end in g["occupancy"][g["assigned_gate"]]:
        assert busy_end <= start or busy_start >= end
    # ...with the assumed buffers either side of the planned turn
    (_, prev_end), (next_start, _) = g["occupancy"][g["assigned_gate"]]
    assert ASSIGNED_GATE_PREV_GAP[0] <= start - prev_end < ASSIGNED_GATE_PREV_GAP[1]
    assert ASSIGNED_GATE_NEXT_GAP[0] <= next_start - end < ASSIGNED_GATE_NEXT_GAP[1]


def test_overnight_arrival_wraps():
    f = load_flights()
    row = int(f[(f.SCHEDULED_ARRIVAL < f.SCHEDULED_DEPARTURE) & (f.SCHEDULED_TIME < 300)].index[0])
    s = build_scenario(row)
    assert s.flight["sched_arr_abs"] >= 1440
    assert s.flight["sched_arr_abs"] > s.flight["sched_dep_abs"]


def test_alternates_skip_missing_coordinates():
    assert _alternates("ECP") == []
    for dest in ("DFW", "ATL", "PNS", "MOB"):  # PNS and MOB are near ECP
        assert not {a["iata"] for a in _alternates(dest)} & EXCLUDED_ALTERNATES


def test_fuel_and_duty_semantics():
    s = build_scenario(AA334_ROW)
    # fuel = workbook 30 min final reserve + alternate time + 45 min spare fuel on arrival
    assert s.fuel_reserve_min.value == pytest.approx(30 + planned_alternate_min(s.alternates) + 45, abs=0.1)
    assert "organiser workbook" in s.fuel_reserve_min.note
    # duty remainder is measured at SCHEDULED arrival, so a legal crew is non-negative there
    lo, hi = DUTY_REMAINING_RANGE
    assert 0 < lo <= s.crew_duty_remaining_min.value <= hi
    assert "max duty 780 min from report" in s.crew_duty_remaining_min.note


def test_workbook_airport_limits_in_scenario():
    s = build_scenario(AA334_ROW)  # DFW: Large hub, 90 ops/h, 45 min turnaround
    assert s.nominal_aar.value == 45 and s.nominal_aar.source == "assumed"
    assert "organiser workbook" in s.nominal_aar.note
    assert s.gates["min_turnaround_min"] == 45


def test_delayed_arrivals_helper_matches_scenario():
    s = build_scenario(AA334_ROW)
    n = delayed_arrivals_in_hour("DFW", s.flight["date"], s.flight["actual_arr_abs"])
    assert n == s.dest_disruption.value
    assert arrival_hour_stats("DFW", s.flight["date"], 1440 + 30)["day"] == arrival_hour_stats(
        "DFW", "2015-04-25", 30
    )["day"]


# ---- edge cases -------------------------------------------------------------------------------
from src.options.menu import generate_candidates  # noqa: E402
from src.rules.engine import RULE_IDS, check_all  # noqa: E402

SCHED_ARR_2400_ROW = 86285  # SCHEDULED_ARRIVAL 2400, departs 21:35
ARR_TIME_2400_ROW = 78  # ARRIVAL_TIME 2400, scheduled 23:35, +25 min
NO_COORDS_DEST_ROW = 2171  # destination ECP has no coordinates in airports.csv
LONE_TAIL_ROW = 231375  # tail 7819A has no other legs that day


def test_scheduled_arrival_2400_is_next_midnight():
    s = build_scenario(SCHED_ARR_2400_ROW)
    assert s.flight["SCHEDULED_ARRIVAL"] == 0
    assert s.flight["sched_arr_abs"] == 1440
    assert s.flight["sched_arr_abs"] - s.flight["sched_dep_abs"] == s.flight["SCHEDULED_TIME"]


def test_actual_arrival_2400_wraps_past_midnight():
    s = build_scenario(ARR_TIME_2400_ROW)
    assert s.flight["ARRIVAL_TIME"] == 0
    assert s.flight["actual_arr_abs"] == 1440
    nxt = arrival_hour_stats(s.flight["DESTINATION_AIRPORT"], s.flight["date"], s.flight["actual_arr_abs"])
    assert nxt["hour"] == 0 and nxt["day"] == load_flights().loc[ARR_TIME_2400_ROW, "day_idx"] + 1


def test_missing_destination_coordinates():
    s = build_scenario(NO_COORDS_DEST_ROW)
    assert s.flight["DESTINATION_AIRPORT"] == "ECP"
    assert s.alternates == []
    assert "no alternate ranked" in s.fuel_reserve_min.note  # 30 min default alternate time
    cands = generate_candidates(s)
    assert len(cands) >= 5 and not any(c.kind == "divert" for c in cands)
    assert len(check_all(s, cands)) == len(RULE_IDS) * len(cands)


def test_no_downstream_legs_and_unmatched_tail():
    s = build_scenario(LONE_TAIL_ROW)
    assert s.downstream_legs == []
    assert s.wake_category.source == "assumed"  # no registry lookup: distance-based default
    cands = generate_candidates(s)
    assert all(c.est_knock_on_min == 0 for c in cands)
    turn = [r for r in check_all(s, cands) if r.rule_id == "R-TURN-01"]
    assert all(r.passed and str(r.observed).startswith("n/a") for r in turn)
