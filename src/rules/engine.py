"""Deterministic rules engine. No LLM. Owner: Waseem (T1).

check_all returns exactly one RuleResult per (candidate, rule) pair, candidate-major in menu order,
rules in RULE_IDS order. A rule that does not apply still returns passed=True with observed
"n/a: ..." and a citation saying why. source = weakest input tag (data < estimated < assumed <
synthetic). docs/regulatory_sources.md is not written yet, so regulation values are cited with
"(verify)" and every other constant is labelled "assumed".

- R-WAKE-01  FAA JO 7110.65 5-5-4. Per runway, not airport-wide: the arrival flow per runway in the
  candidate's arrival hour must leave at least the wake spacing behind an assumed leader.
    demand      = BASE_LOAD * nominal_aar + delayed arrivals in that hour (data) + 1 (this flight)
    available_s = 3600 * runways / demand            (runways: ARRIVAL_RUNWAYS_ASSUMED = 3)
    required_s  = WAKE_SEP_NM[LEADER_CATEGORY][wake] nm / 140 kt * 3600
                  (Large leader assumed: H 3, L 3, S 4 nm)
  Leader, separation, approach speed and runway count are the same assumed inputs as the
  reviewer's WAKE re-derivation (docs/calibration.md); the demand formulas still differ.
  Divert: evaluated at the alternate (default AAR, same assumed runway count).
- R-FUEL-01  14 CFR 121.639. airborne extra from src.options.menu.airborne_extra_min.
    non-divert: fuel_reserve_min - extra >= planned_alternate_min + 45 (alternate still reachable)
    divert:     fuel_reserve_min - extra >= 45 on arrival at the alternate
  Stricter than the reviewer (which only keeps the 45 min) for non-diverts.
- R-DUTY-01  14 CFR 117. crew_duty_remaining_min (at scheduled arrival) - incurred ARRIVAL_DELAY
  - added delay (divert = full disruption) >= -DUTY_EXTENSION_MIN. DUTY_EXTENSION_MIN = 0 by
  default (no extension assumed: a 14 CFR 117.19 extension of up to 2 h needs PIC concurrence, a
  human decision). Before the 2026-10-31 calibration, setting it to 120 roughly halved the
  all-candidates-fail rows on the eval sample (74 -> 35 of 200); after it, 27 of 200 rows have no
  passing candidate with the default 0 (docs/calibration.md).
- R-GATE-01  synthetic gate model. The assigned (or swapped) gate must be free over
  [new arrival, new arrival + min turnaround]. ARRIVAL_TIME is gate-in, so TAXI_IN is already in
  the arrival time; a swap's extra_taxi_min is in the new arrival. n/a for diverts.
- R-TURN-01  assumed. The next known leg out of the destination leaves no earlier than arrival +
  min turnaround, so its knock-on is max(0, arrival + turn - sched_dep). The check is on the
  knock-on the candidate ADDS over the unmitigated projection (actual_arr_abs), because delay
  already incurred cannot be undone by any option: added <= TURN_ADDED_MAX_MIN (30, assumed).
  n/a if there is no downstream leg or the next known leg starts elsewhere (chain partial).
- R-AAR-01   assumed nominal rate. Same demand proxy as WAKE vs a cap reduced by weather:
    cap = nominal_aar * (1 - WX_CAP_REDUCTION * weather share of delayed arrivals in that hour),
    WX_CAP_REDUCTION = 0.25 (assumed).
  Limits: flights.csv holds delayed flights only, so demand is a proxy and BASE_LOAD is assumed.
"""

from src.options.menu import (
    added_delay_min,
    airborne_extra_min,
    arrival_point,
    busy_overlap_min,
    new_arrival_abs,
)
from src.scenario.builder import (
    DEFAULT_AAR,
    FINAL_RESERVE_MIN,
    NOMINAL_AAR,
    arrival_hour_stats,
    planned_alternate_min,
)
from src.schemas import Candidate, RuleResult, Scenario

RULE_IDS = ["R-WAKE-01", "R-FUEL-01", "R-DUTY-01", "R-GATE-01", "R-TURN-01", "R-AAR-01"]
_STRENGTH = {"data": 0, "estimated": 1, "assumed": 2, "synthetic": 3}

# WAKE assumed inputs, reconciled 2026-10-31 with the reviewer's constants (src/reviewer/safety.py:
# ASSUMED_LEADER_CATEGORY, WAKE_SEP_NM_BEHIND_LARGE, APPROACH_KT, ASSUMED_ARRIVAL_RUNWAYS) so both
# derive the same required and per-runway spacing. docs/calibration.md.
APPROACH_KT = 140  # assumed final approach speed (same as reviewer)
# Assumed leader category (was "H"): the typical leader at the four hubs is a Large narrowbody;
# Heavies are a small share of hub arrivals. A Heavy-led pair (4-6 nm) is not modelled per hour.
LEADER_CATEGORY = "L"
# FAA JO 7110.65 5-5-4 legacy minima (verify), leader -> follower -> nm. Distances unchanged.
# Behind a Large: 3 nm radar minimum, 4 nm Small behind Large on final.
WAKE_SEP_NM = {"H": {"H": 4, "L": 5, "S": 6}, "L": {"H": 3, "L": 3, "S": 4}}
WAKE_SEP_NM_BEHIND_HEAVY = WAKE_SEP_NM["H"]  # kept for reference/imports
# Arrival runways in simultaneous use, one assumed value for every airport (was a per-airport
# table, ATL/ORD/DEN 3, DFW 4, others 1-2, default 1). The reviewer can only take one number, and
# 3 is the typical hub figure (ATL 26R/27L/28; ORD, DFW, DEN 3-4); it is also the smallest count
# for which the assumed ATL AAR of 126/h fits 3 nm spacing at 140 kt (46.7/h per runway).
ARRIVAL_RUNWAYS_ASSUMED = 3
BASE_LOAD = 0.6  # assumed share of nominal AAR filled by on-time arrivals in any hour
# Assumed (was 0.4): AAR cut when all delayed arrivals in the hour are weather. VMC -> IMC called
# rates at the large hubs drop by roughly 15-30% (FAA airport capacity profiles, not verified).
WX_CAP_REDUCTION = 0.25
DUTY_EXTENSION_MIN = 0  # 14 CFR 117.19 allows up to 120 with PIC concurrence; not assumed
TURN_ADDED_MAX_MIN = 30  # assumed: max extra next-leg delay an option may add


def _weakest(*tags: str) -> str:
    return max(tags, key=_STRENGTH.__getitem__)


def _r(rule_id, c, passed, observed, threshold, source, citation) -> RuleResult:
    if isinstance(observed, float):
        observed = round(observed, 1)
    if isinstance(threshold, float):
        threshold = round(threshold, 1)
    return RuleResult(
        rule_id=rule_id, candidate_id=c.candidate_id, passed=bool(passed),
        observed=observed, threshold=threshold, source=source, citation=citation,
    )


def _demand(s: Scenario, airport: str, minute: float) -> tuple[float, dict, int]:
    stats = arrival_hour_stats(airport, s.flight["date"], minute)
    aar = NOMINAL_AAR.get(airport, DEFAULT_AAR)
    return BASE_LOAD * aar + stats["delayed"] + 1, stats, aar


def wake(s: Scenario, c: Candidate) -> RuleResult:
    airport, minute = arrival_point(s, c)
    demand, stats, aar = _demand(s, airport, minute)
    runways = ARRIVAL_RUNWAYS_ASSUMED
    cat = str(s.wake_category.value)
    seps = WAKE_SEP_NM[LEADER_CATEGORY]
    sep_nm = seps.get(cat, max(seps.values()))  # unknown follower: most conservative
    required_s = sep_nm / APPROACH_KT * 3600
    available_s = 3600 * runways / demand
    leader = {"H": "Heavy", "L": "Large"}.get(LEADER_CATEGORY, LEADER_CATEGORY)
    return _r(
        "R-WAKE-01", c, available_s >= required_s, available_s, required_s,
        _weakest(s.wake_category.source, "assumed", "data"),
        f"FAA JO 7110.65 5-5-4 (verify): {sep_nm} nm {cat} behind assumed {leader} at {APPROACH_KT} kt "
        f"(assumed); {airport} {stats['hour']:02d}:00 demand {demand:.1f}/h = {BASE_LOAD} x AAR {aar} "
        f"(assumed) + {stats['delayed']} delayed (data) + 1, over {runways} runway(s) (assumed)",
    )


def fuel(s: Scenario, c: Candidate) -> RuleResult:
    extra = airborne_extra_min(s, c)
    remaining = float(s.fuel_reserve_min.value) - extra
    if c.kind == "divert":
        need, what = float(FINAL_RESERVE_MIN), f"on arrival at {c.params.get('iata')}"
        src = _weakest(s.fuel_reserve_min.source, "assumed")
    else:
        alt = planned_alternate_min(s.alternates)
        need, what = alt + FINAL_RESERVE_MIN, f"alternate {alt:g} min + final reserve"
        src = s.fuel_reserve_min.source
    return _r(
        "R-FUEL-01", c, remaining >= need, remaining, need, src,
        f"14 CFR 121.639 (verify): fuel_reserve_min {s.fuel_reserve_min.value} (estimated) - "
        f"{extra:.1f} airborne extra = {remaining:.1f} vs {what} {FINAL_RESERVE_MIN}; 420 kt assumed",
    )


def duty(s: Scenario, c: Candidate) -> RuleResult:
    incurred = float(s.flight["ARRIVAL_DELAY"])
    added = added_delay_min(s, c)
    left = float(s.crew_duty_remaining_min.value) - incurred - added
    return _r(
        "R-DUTY-01", c, left >= -DUTY_EXTENSION_MIN, left, 0.0 - DUTY_EXTENSION_MIN,
        _weakest(s.crew_duty_remaining_min.source, "data"),
        f"14 CFR Part 117 FDP (verify): {s.crew_duty_remaining_min.value} min left at scheduled "
        f"arrival (synthetic) - {incurred:g} incurred ARRIVAL_DELAY (data) - {added:.1f} added",
    )


def gate(s: Scenario, c: Candidate) -> RuleResult:
    g = s.gates
    if c.kind == "divert":
        return _r("R-GATE-01", c, True, "n/a: divert", "n/a", g["source"],
                  "synthetic gate model: not applicable, the aircraft does not use its gate on this arrival")
    gate_id = c.params.get("gate", g["assigned_gate"]) if c.kind == "gate_swap" else g["assigned_gate"]
    start = new_arrival_abs(s, c)
    end = start + g["min_turnaround_min"]
    overlap = busy_overlap_min(g["occupancy"].get(gate_id, []), start, end)
    return _r(
        "R-GATE-01", c, overlap == 0, overlap, 0.0, _weakest(g["source"], g["turnaround_source"]),
        f"synthetic gate model (seeded): gate {gate_id} busy minutes in [{start:.0f}, {end:.0f}] "
        f"(gate-in + {g['min_turnaround_min']} min assumed turnaround)",
    )


def turnaround(s: Scenario, c: Candidate) -> RuleResult:
    g = s.gates
    dest = s.flight["DESTINATION_AIRPORT"]
    legs = sorted(s.downstream_legs, key=lambda leg: leg["sched_dep_abs"])
    if not legs:
        return _r("R-TURN-01", c, True, "n/a: no downstream leg", TURN_ADDED_MAX_MIN, "assumed",
                  "assumed: airline turnaround; no later leg of this tail in flights.csv (data partial)")
    nxt = legs[0]
    if nxt["origin"] != dest:
        return _r("R-TURN-01", c, True, f"n/a: next known leg departs {nxt['origin']}",
                  TURN_ADDED_MAX_MIN, "assumed",
                  "assumed: airline turnaround; chain partial (only delayed legs in flights.csv)")
    turn = g["min_turnaround_min"]
    base = max(0.0, s.flight["actual_arr_abs"] + turn - nxt["sched_dep_abs"])
    knock = max(0.0, new_arrival_abs(s, c) + turn - nxt["sched_dep_abs"])
    added = knock - base
    return _r(
        "R-TURN-01", c, added <= TURN_ADDED_MAX_MIN, added, float(TURN_ADDED_MAX_MIN),
        _weakest(g["turnaround_source"], "data"),
        f"assumed: airline turnaround {turn} min per class; next leg {nxt['airline']}"
        f"{nxt['flight_number']} sched dep {nxt['sched_dep_abs']} (data): knock-on {knock:.0f} min vs "
        f"{base:.0f} unmitigated; max {TURN_ADDED_MAX_MIN} min added assumed",
    )


def aar(s: Scenario, c: Candidate) -> RuleResult:
    airport, minute = arrival_point(s, c)
    demand, stats, rate = _demand(s, airport, minute)
    share = stats["weather_delayed"] / stats["delayed"] if stats["delayed"] else 0.0
    cap = rate * (1 - WX_CAP_REDUCTION * share)
    return _r(
        "R-AAR-01", c, demand <= cap, demand, cap, _weakest(s.nominal_aar.source, "data"),
        f"assumed: nominal AAR {rate}/h (unverified) cut {WX_CAP_REDUCTION:.0%} x weather share "
        f"{share:.2f} at {airport} {stats['hour']:02d}:00; demand proxy {BASE_LOAD} x AAR + "
        f"{stats['delayed']} delayed + 1 (flights.csv has delayed flights only)",
    )


RULES = {"R-WAKE-01": wake, "R-FUEL-01": fuel, "R-DUTY-01": duty, "R-GATE-01": gate,
         "R-TURN-01": turnaround, "R-AAR-01": aar}


def check_all(s: Scenario, candidates: list[Candidate]) -> list[RuleResult]:
    return [RULES[rule_id](s, c) for c in candidates for rule_id in RULE_IDS]
