"""Hand-built AA334 fixture: Scenario, 8 candidates, 48 rule results. Owner: Rohan (L).

Test-only stand-in for src/scenario, src/options and src/rules (docs/plan-rohan.md section 2), so
the mediator, fallback, CLI and eval harness can run before, and independently of, those modules.
The flight row is the real data/flights.csv row 123017 (AA334 MFE->DFW, 24 Apr 2015, N469AA) with
hhmm times converted to minutes since midnight. Everything else is hand-picked and tagged.

Designed outcomes:
- HOLD40 fails R-FUEL-01 (105.1 - 40 = 65.1 min < 42.1 min to the most distant alternate, AUS
  295 NM / 7 NM per min, + 30 min organiser-workbook final reserve = 72.1 min).
- DIVERT_AUS passes R-FUEL-01: after a divert the alternate is the destination, so only the 30 min
  final reserve is kept on arrival (105.1 - 42.1 = 63 min >= 30).
- DIVERT_AUS fails R-DUTY-01 (engine's delay estimate 165 min > 150 min duty remaining).
- Every other (rule, candidate) pair passes.
- Fallback objective (delay + knock_on, default weights): SLOT-15 = 15 is the best passing pick,
  then GATE_B12 = 18, SLOT+15 = 25, HOLD20 = 34, GROUND_HOLD_MFE = 43, SLOT+30 = 54.
"""

from src.schemas import Candidate, RuleResult, Scenario, Tagged

AA334_ROW_INDEX = 123017
AA334_SCENARIO_ID = "2015-04-24_AA334_N469AA"

RULE_IDS = ["R-WAKE-01", "R-FUEL-01", "R-DUTY-01", "R-GATE-01", "R-TURN-01", "R-AAR-01"]

CANDIDATE_IDS = [
    "SLOT+15",
    "SLOT+30",
    "SLOT-15",
    "HOLD20",
    "HOLD40",
    "DIVERT_AUS",
    "GATE_B12",
    "GROUND_HOLD_MFE",
]

# 33 min of usable margin over 42.1 min to the most distant alternate (AUS 295 NM at 7 NM per min)
# + 30 min final reserve. AUS moved from 190 NM when the reserve went 45 -> 30, so every threshold
# (72.1 min) and designed outcome is unchanged (docs/constraints.md).
AUS_NM = 295
ALTERNATE_MIN = round(AUS_NM / 7.0, 1)  # 42.1, as src/scenario/builder.py planned_alternate_min
FUEL_RESERVE_MIN = 105.1
CREW_DUTY_REMAINING_MIN = 150
FUEL_THRESHOLD_MIN = 30  # organiser workbook final reserve (was 45, 14 CFR 121.639)


def _flight_row() -> dict:
    """data/flights.csv row 123017, hhmm -> minutes since midnight."""
    return {
        "YEAR": 2015,
        "MONTH": 4,
        "DAY": 24,
        "DAY_OF_WEEK": 5,
        "AIRLINE": "AA",
        "FLIGHT_NUMBER": 334,
        "TAIL_NUMBER": "N469AA",
        "ORIGIN_AIRPORT": "MFE",
        "DESTINATION_AIRPORT": "DFW",
        "SCHEDULED_DEPARTURE": 676,  # 11:16
        "DEPARTURE_TIME": 790,  # 13:10
        "DEPARTURE_DELAY": 114,
        "TAXI_OUT": 16,
        "WHEELS_OFF": 806,  # 13:26
        "SCHEDULED_TIME": 99,
        "ELAPSED_TIME": 86,
        "AIR_TIME": 64,
        "DISTANCE": 469,
        "WHEELS_ON": 870,  # 14:30
        "TAXI_IN": 6,
        "SCHEDULED_ARRIVAL": 775,  # 12:55
        "ARRIVAL_TIME": 876,  # 14:36
        "ARRIVAL_DELAY": 101,
        "DIVERTED": 0,
        "CANCELLED": 0,
        "CANCELLATION_REASON": None,
        "AIR_SYSTEM_DELAY": 0,
        "SECURITY_DELAY": 0,
        "AIRLINE_DELAY": 0,
        "LATE_AIRCRAFT_DELAY": 43,
        "WEATHER_DELAY": 58,
    }


def _downstream_legs() -> list[dict]:
    """Same tail, later legs on 24 Apr 2015 (real rows 123158, 123157, 123124)."""
    return [
        {
            "row_index": 123158,
            "FLIGHT_NUMBER": 1389,
            "ORIGIN_AIRPORT": "DFW",
            "DESTINATION_AIRPORT": "MEM",
            "SCHEDULED_DEPARTURE": 828,  # 13:48
            "SCHEDULED_ARRIVAL": 922,  # 15:22
            "DEPARTURE_DELAY": 111,
            "ARRIVAL_DELAY": 102,
        },
        {
            "row_index": 123157,
            "FLIGHT_NUMBER": 1389,
            "ORIGIN_AIRPORT": "MEM",
            "DESTINATION_AIRPORT": "DFW",
            "SCHEDULED_DEPARTURE": 962,  # 16:02
            "SCHEDULED_ARRIVAL": 1068,  # 17:48
            "DEPARTURE_DELAY": 249,
            "ARRIVAL_DELAY": 264,
        },
        {
            "row_index": 123124,
            "FLIGHT_NUMBER": 1274,
            "ORIGIN_AIRPORT": "DFW",
            "DESTINATION_AIRPORT": "BWI",
            "SCHEDULED_DEPARTURE": 1115,  # 18:35
            "SCHEDULED_ARRIVAL": 1365,  # 22:45
            "DEPARTURE_DELAY": 288,
            "ARRIVAL_DELAY": 256,
        },
    ]


def fixture_scenario() -> Scenario:
    """AA334-shaped Scenario; every non-raw number is Tagged."""
    return Scenario(
        scenario_id=AA334_SCENARIO_ID,
        row_index=AA334_ROW_INDEX,
        flight=_flight_row(),
        dest_disruption=Tagged(
            value=14, source="data", note="delayed arrivals at DFW in the 12:00 hour (proxy)"
        ),
        taxi_congestion=Tagged(value=0.67, source="data", note="TAXI_IN 6 vs DFW median 9"),
        downstream_legs=_downstream_legs(),
        alternates=[
            {"iata": "DAL", "distance_nm": 12},
            {"iata": "ACT", "distance_nm": 78},
            {"iata": "AUS", "distance_nm": AUS_NM},
        ],
        wake_category=Tagged(value="L", source="assumed", note="A321 fleet default, no registry"),
        fuel_reserve_min=Tagged(
            value=FUEL_RESERVE_MIN, source="estimated", note="distance x typical burn"
        ),
        crew_duty_remaining_min=Tagged(
            value=CREW_DUTY_REMAINING_MIN, source="synthetic", note="seeded duty model, seed 42"
        ),
        gates={
            "airport": "DFW",
            "assigned": "C20",
            "available": ["B12", "B14"],
            "source": "synthetic",
            "seed": 42,
        },
        connections=[
            {"flight": "AA1389", "dest": "MEM", "sched_dep_min": 828, "pax_est": 34,
             "source": "estimated"},
            {"flight": "AA2210", "dest": "ORD", "sched_dep_min": 870, "pax_est": 12,
             "source": "estimated"},
        ],
        nominal_aar=Tagged(value=90, source="assumed", note="published DFW arrival rate"),
    )


def fixture_candidates() -> list[Candidate]:
    """8 candidates with plausible deterministic estimates (minutes)."""
    return [
        Candidate(candidate_id="SLOT+15", kind="slot_shift", params={"shift_min": 15},
                  est_delay_min=15, est_knock_on_min=10),
        Candidate(candidate_id="SLOT+30", kind="slot_shift", params={"shift_min": 30},
                  est_delay_min=30, est_knock_on_min=24),
        Candidate(candidate_id="SLOT-15", kind="slot_shift", params={"shift_min": -15},
                  est_delay_min=-15, est_knock_on_min=30),
        Candidate(candidate_id="HOLD20", kind="hold", params={"minutes": 20},
                  est_delay_min=20, est_knock_on_min=14),
        Candidate(candidate_id="HOLD40", kind="hold", params={"minutes": 40},
                  est_delay_min=40, est_knock_on_min=30),
        Candidate(candidate_id="DIVERT_AUS", kind="divert", params={"iata": "AUS"},
                  est_delay_min=165, est_knock_on_min=140),
        Candidate(candidate_id="GATE_B12", kind="gate_swap",
                  params={"gate": "B12", "extra_taxi_min": 4},
                  est_delay_min=6, est_knock_on_min=12),
        Candidate(candidate_id="GROUND_HOLD_MFE", kind="ground_hold", params={"minutes": 20},
                  est_delay_min=25, est_knock_on_min=18),
    ]


def _airborne_extra_min(c: Candidate) -> float:
    if c.kind == "hold":
        return float(c.params["minutes"])
    if c.kind == "slot_shift":
        return float(max(c.params["shift_min"], 0))
    if c.kind == "divert":
        return round(AUS_NM / 7.0, 1)
    return 0.0


def fixture_rule_results() -> list[RuleResult]:
    """6 rules x 8 candidates = 48 RuleResults; HOLD40 fails fuel, DIVERT_AUS fails duty."""
    results: list[RuleResult] = []
    for c in fixture_candidates():
        cid = c.candidate_id
        fuel_left = round(FUEL_RESERVE_MIN - _airborne_extra_min(c), 1)
        # 14 CFR 121.639: keep the most distant alternate leg unless the candidate diverts there.
        fuel_need = FUEL_THRESHOLD_MIN + (0.0 if c.kind == "divert" else ALTERNATE_MIN)
        duty_left = CREW_DUTY_REMAINING_MIN - max(c.est_delay_min, 0)
        results += [
            RuleResult(rule_id="R-WAKE-01", candidate_id=cid, passed=True, observed=150.0,
                       threshold=129.0, source="assumed",
                       citation="FAA JO 7110.65 5-5-4 (approach speed 140 kt assumed)"),
            RuleResult(rule_id="R-FUEL-01", candidate_id=cid,
                       passed=fuel_left >= fuel_need, observed=fuel_left,
                       threshold=round(fuel_need, 1), source="estimated",
                       citation="14 CFR 121.639"),
            RuleResult(rule_id="R-DUTY-01", candidate_id=cid, passed=duty_left >= 0,
                       observed=duty_left, threshold=0.0, source="synthetic",
                       citation="14 CFR Part 117"),
            RuleResult(rule_id="R-GATE-01", candidate_id=cid, passed=True, observed=0.0,
                       threshold=0.0, source="synthetic",
                       citation="synthetic gate model (seed 42)"),
            RuleResult(rule_id="R-TURN-01", candidate_id=cid, passed=True, observed=55.0,
                       threshold=40.0, source="assumed",
                       citation="assumed: airline turnaround, narrowbody 40 min"),
            RuleResult(rule_id="R-AAR-01", candidate_id=cid, passed=True, observed=60.0,
                       threshold=76.0, source="assumed",
                       citation="assumed: DFW nominal 90 arrivals/h minus 14 disrupted = 76 cap"),
        ]
    return results


def rules_passing_ids() -> set[str]:
    """Candidate ids whose every fixture RuleResult passed."""
    failed = {r.candidate_id for r in fixture_rule_results() if not r.passed}
    return set(CANDIDATE_IDS) - failed
