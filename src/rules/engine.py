"""Deterministic rules engine. No LLM. Owner: Waseem (T1).

check_all returns exactly one RuleResult per (candidate, rule) pair, candidate-major in menu order,
rules in RULE_IDS order. A rule that does not apply still returns passed=True with observed
"n/a: ..." and a citation saying why. source = weakest input tag (data < estimated < assumed <
synthetic). docs/regulatory_sources.md is not written yet, so regulation values are cited with
"(verify)" and every other constant is labelled "assumed".

- R-WAKE-01  FAA JO 7110.65 5-5-4. Per runway, not airport-wide: the arrival flow per runway in the
  candidate's arrival hour must leave at least the wake spacing behind an assumed leader.
    demand      = BASE_LOAD * nominal_aar + delayed arrivals in that hour (data) + 1 (this flight)
    available_s = 3600 * runways / demand   (runways: workbook active_runways at that airport)
    required_s  = constraints.wake_sep_nm(LEADER_CATEGORY, wake) nm / 140 kt * 3600
                  (Large leader assumed; workbook: L->S 4 nm, any other pair 3 nm)
  Leader, separation table, approach speed and runway count are the same inputs the reviewer's
  WAKE re-derivation reads from src/constraints.py (docs/constraints.md); demand formulas differ.
  Divert: evaluated at the alternate (its workbook capacity and runways).
- R-FUEL-01  organiser workbook final reserve 30 min (+ 14 CFR 121.639 alternate leg, kept).
    non-divert: fuel_reserve_min - extra >= planned_alternate_min + 30 (alternate still reachable)
    divert:     fuel_reserve_min - extra >= 30 on arrival at the alternate
- R-GATE-02  organiser workbook: a gate change must be notified >= 20 min before arrival. The
  swap is decided GATE_DECISION_LEAD_MIN (30, assumed) before the projected gate-in, so
  notice = new gate-in - decision time. n/a (pass) for every non-gate-swap candidate.
- R-DUTY-01  organiser workbook 13 h max duty from report (simplified 14 CFR 117). crew_duty_remaining_min (at scheduled arrival) - incurred ARRIVAL_DELAY
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
- R-AAR-01   workbook max_runway_ops_per_hour x 0.5 arrival share (assumed). Same demand proxy as WAKE vs a cap reduced by weather:
    cap = nominal_aar * (1 - WX_CAP_REDUCTION * weather share of delayed arrivals in that hour),
    WX_CAP_REDUCTION = 0.25 (assumed).
  Limits: flights.csv holds delayed flights only, so demand is a proxy and BASE_LOAD is assumed.
"""

from src import constraints
from src.options.menu import (
    added_delay_min,
    airborne_extra_min,
    arrival_point,
    busy_overlap_min,
    new_arrival_abs,
)
from src.scenario.builder import (
    FINAL_RESERVE_MIN,
    FDP_LIMIT_MIN,
    arrival_hour_stats,
    nominal_aar,
    planned_alternate_min,
)
from src.schemas import Candidate, RuleResult, Scenario

RULE_IDS = ["R-WAKE-01", "R-FUEL-01", "R-DUTY-01", "R-GATE-01", "R-GATE-02", "R-TURN-01", "R-AAR-01"]
_STRENGTH = {"data": 0, "estimated": 1, "assumed": 2, "synthetic": 3}

# WAKE: separation distances and per-airport active runways come from the organiser workbook
# through src/constraints.py, the same loader the reviewer reads (docs/constraints.md).
APPROACH_KT = 140  # assumed final approach speed (same as reviewer); not in the workbook
# Assumed leader category: the workbook has no data on the leader. The typical leader at the hubs
# is a Large narrowbody (docs/calibration.md). Distance: constraints.wake_sep_nm(leader, follower).
LEADER_CATEGORY = "L"
# Assumed: the gate-swap decision is taken this many minutes before the projected gate-in
# (actual_arr_abs), i.e. when the negotiation runs, around top of descent. R-GATE-02 checks the
# workbook's gate-change notice (>= 20 min before arrival) against it.
GATE_DECISION_LEAD_MIN = 30
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
    aar = nominal_aar(airport)
    return BASE_LOAD * aar + stats["delayed"] + 1, stats, aar


def wake(s: Scenario, c: Candidate) -> RuleResult:
    airport, minute = arrival_point(s, c)
    demand, stats, aar = _demand(s, airport, minute)
    runways = constraints.airport(airport).active_runways
    cat = str(s.wake_category.value).strip().upper()
    if cat in ("H", "L", "S", "J"):
        sep_nm = constraints.wake_sep_nm(LEADER_CATEGORY, cat)
    else:  # unknown follower: most conservative behind the assumed leader
        sep_nm = max(constraints.wake_sep_nm(LEADER_CATEGORY, f) for f in ("H", "L", "S"))
    required_s = sep_nm / APPROACH_KT * 3600
    available_s = 3600 * runways / demand
    leader = {"H": "Heavy", "L": "Large"}.get(LEADER_CATEGORY, LEADER_CATEGORY)
    return _r(
        "R-WAKE-01", c, available_s >= required_s, available_s, required_s,
        _weakest(s.wake_category.source, "assumed", "data"),
        f"organiser workbook wake_separation (from FAA JO 7110.65): {sep_nm:g} nm {cat} behind assumed "
        f"{leader} at {APPROACH_KT} kt (assumed); {airport} {stats['hour']:02d}:00 demand {demand:.1f}/h = "
        f"{BASE_LOAD} x AAR {aar:g} (workbook ops/h x {constraints.ARRIVAL_SHARE}) + {stats['delayed']} "
        f"delayed (data) + 1, over {runways} active runway(s) ({constraints.NOTE})",
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
        f"organiser workbook final reserve {FINAL_RESERVE_MIN:g} min holding (alternate leg kept per "
        f"14 CFR 121.639, verify): fuel_reserve_min {s.fuel_reserve_min.value} (estimated) - "
        f"{extra:.1f} airborne extra = {remaining:.1f} vs {what} {FINAL_RESERVE_MIN:g}; 420 kt assumed",
    )


def duty(s: Scenario, c: Candidate) -> RuleResult:
    incurred = float(s.flight["ARRIVAL_DELAY"])
    added = added_delay_min(s, c)
    left = float(s.crew_duty_remaining_min.value) - incurred - added
    return _r(
        "R-DUTY-01", c, left >= -DUTY_EXTENSION_MIN, left, 0.0 - DUTY_EXTENSION_MIN,
        _weakest(s.crew_duty_remaining_min.source, "data"),
        f"organiser workbook crew max duty {FDP_LIMIT_MIN / 60:g} h from report (simplified 14 CFR 117): "
        f"{s.crew_duty_remaining_min.value} min left at scheduled arrival (synthetic) - {incurred:g} "
        f"incurred ARRIVAL_DELAY (data) - {added:.1f} added",
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
        f"(gate-in + {g['min_turnaround_min']} min min turnaround, {constraints.NOTE})",
    )


def gate_notice(s: Scenario, c: Candidate) -> RuleResult:
    need = constraints.fuel_crew("gate_change_notice_min")
    if c.kind != "gate_swap":
        return _r("R-GATE-02", c, True, "n/a: no gate change", need, "assumed",
                  "organiser workbook gate change notice: not applicable, the assigned gate is kept")
    decided = float(s.flight["actual_arr_abs"]) - GATE_DECISION_LEAD_MIN
    notice = new_arrival_abs(s, c) - decided
    return _r(
        "R-GATE-02", c, notice >= need, notice, need, "assumed",
        f"organiser workbook: gate change notice at least {need:g} min before arrival; swap to "
        f"{c.params.get('gate')} decided at {decided:.0f} (projected gate-in - {GATE_DECISION_LEAD_MIN} "
        f"min, assumed), gate-in {new_arrival_abs(s, c):.0f}",
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
        f"organiser workbook: AAR {rate:g}/h = max_runway_ops_per_hour x {constraints.ARRIVAL_SHARE} "
        f"arrival share (assumed), cut {WX_CAP_REDUCTION:.0%} x weather share "
        f"{share:.2f} at {airport} {stats['hour']:02d}:00; demand proxy {BASE_LOAD} x AAR + "
        f"{stats['delayed']} delayed + 1 (flights.csv has delayed flights only)",
    )


RULES = {"R-WAKE-01": wake, "R-FUEL-01": fuel, "R-DUTY-01": duty, "R-GATE-01": gate,
         "R-GATE-02": gate_notice, "R-TURN-01": turnaround, "R-AAR-01": aar}


def check_all(s: Scenario, candidates: list[Candidate]) -> list[RuleResult]:
    return [RULES[rule_id](s, c) for c in candidates for rule_id in RULE_IDS]
