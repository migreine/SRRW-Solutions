from src.scenario.builder import (
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
    s = build_scenario(AA334_ROW)
    g = s.gates
    start = s.flight["sched_arr_abs"]
    end = start + g["min_turnaround_min"]
    for busy_start, busy_end in g["occupancy"][g["assigned_gate"]]:
        assert busy_end <= start or busy_start >= end


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
    # fuel includes the 45 min final reserve plus the alternate time (plan-rohan section 0)
    assert s.fuel_reserve_min.value >= 45 + planned_alternate_min(s.alternates)
    # duty remainder is measured at SCHEDULED arrival, so a legal crew is non-negative there
    assert 30 <= s.crew_duty_remaining_min.value <= 300


def test_delayed_arrivals_helper_matches_scenario():
    s = build_scenario(AA334_ROW)
    n = delayed_arrivals_in_hour("DFW", s.flight["date"], s.flight["actual_arr_abs"])
    assert n == s.dest_disruption.value
    assert arrival_hour_stats("DFW", s.flight["date"], 1440 + 30)["day"] == arrival_hour_stats(
        "DFW", "2015-04-25", 30
    )["day"]
