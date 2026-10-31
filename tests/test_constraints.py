"""Organiser workbook loader (src/constraints.py)."""

import pytest

from src import constraints


def test_workbook_is_read_once_and_has_every_sheet():
    assert constraints.WORKBOOK.exists()
    wb = constraints.load()
    assert constraints.load() is wb  # cached
    assert len(wb["airports"]) == 322
    assert "Use the limits in this workbook" in wb["rules_of_play"]["Constraints"]


@pytest.mark.parametrize("iata,runways,ops,turn,spare,gates", [
    ("ATL", 4, 90, 45, 3, 150), ("DFW", 4, 90, 45, 3, 150), ("SFO", 3, 60, 35, 3, 70), ("ITH", 1, 20, 35, 2, 8),
])
def test_airport_rows(iata, runways, ops, turn, spare, gates):
    a = constraints.airport(iata)
    assert (a.active_runways, a.max_runway_ops_per_hour, a.min_turnaround_min, a.spare_gates, a.gates) == (
        runways, ops, turn, spare, gates)
    assert a.listed and a.arrival_capacity_per_hour == ops * constraints.ARRIVAL_SHARE == ops / 2
    t = a.tagged("active_runways")
    assert t.source == "assumed" and "organiser workbook (synthetic planning limit)" in t.note


def test_unlisted_airport_gets_default_row():
    a = constraints.airport("ZZZ")
    assert not a.listed and a.size_class == "Non-hub"
    assert (a.active_runways, a.max_runway_ops_per_hour, a.min_turnaround_min, a.spare_gates) == (1, 20, 35, 2)
    assert "not listed" in a.tagged("gates").note


@pytest.mark.parametrize("leader,follower,nm", [
    ("J", "H", 6), ("Super", "Large", 7), ("J", "S", 8), ("H", "H", 4), ("H", "L", 5), ("H", "S", 6),
    ("L", "S", 4), ("L", "L", 3), ("L", "H", 3), ("S", "S", 3),
])
def test_wake_table(leader, follower, nm):
    assert constraints.wake_sep_nm(leader, follower) == nm


def test_fuel_and_crew_values():
    fc = constraints.load()["fuel_crew"]
    assert fc["final_reserve_min"] == 30
    assert fc["contingency_fraction"] == pytest.approx(0.05)
    assert fc["spare_fuel_on_arrival_min"] == 45
    assert fc["crew_max_duty_min"] == 13 * 60
    assert fc["ground_shift_min"] == 8 * 60 and fc["ground_overtime_multiplier"] == 1.5
    assert fc["gate_change_notice_min"] == 20
    assert fc["holding_burn_narrowbody_kg_h"] == 2400 and fc["holding_burn_widebody_kg_h"] == 6500
