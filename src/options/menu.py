"""Fixed menu of candidate resolutions. Owner: Waseem (T1). Deterministic, no LLM.

Menu (5-12 candidates; tail_swap is cut):
- slot_shift  SLOT+15, SLOT+30, SLOT-15, SLOT-30   params {"shift_min"} (negative = earlier)
- hold        HOLD20, HOLD40                       params {"minutes"}
- divert      DIVERT_<IATA> to the 2 nearest alternates          params {"iata"}
- gate_swap   GATE_<ID> x2, the two non-assigned gates whose free window best covers the
              projected arrival, capped at the destination's workbook spare_gates_at_any_time
              (2-3 everywhere, so the cap does not bind)  params {"gate", "extra_taxi_min"}
Ground-crew shift 8 h with 1.5x overtime (organiser workbook) is documented only
(docs/constraints.md): no ground-crew shift times exist in the data, so it is not a cost here.
- ground_hold GROUND_HOLD_<ORIGIN>                 params {"minutes", "airport"}
A destination with no coordinates has no alternates, so the menu is 9 candidates without diverts.

Shared derivations (pure functions; the rules engine imports them so both agree):
- airborne_extra_min: hold -> minutes; slot_shift -> max(shift, 0); divert -> distance_nm / 7
  (420 kt assumed); gate_swap, ground_hold -> 0. Same mapping as the reviewer (plan-rohan 3.5).
- added_delay_min: arrival delay added at the ORIGINAL destination gate, relative to the current
  projected arrival flight["actual_arr_abs"] (negative = earlier). hold -> minutes; slot_shift ->
  shift; ground_hold -> minutes; gate_swap -> extra_taxi_min; divert -> full disruption =
  distance/7 out + DIVERT_GROUND_MIN (60, assumed) on the ground + distance/7 back.
- new_arrival_abs = actual_arr_abs + added_delay_min (gate-in time at the destination).
- arrival_point: (airport, minute) where the aircraft next lands: the alternate at
  actual_arr_abs + distance/7 for a divert, else the destination at new_arrival_abs.
- propagate_knock_on: walk downstream_legs in schedule order. Each leg can leave at the earliest
  arrival + min_turnaround_min (gates model, assumed per class); its departure delay is
  max(0, ready - sched_dep_abs), i.e. the schedule buffer absorbs delay leg by leg; its arrival is
  sched_arr_abs + departure delay (scheduled block time kept). est_knock_on_min is the sum of the
  propagated departure delays. Partial: only delayed legs exist in flights.csv, so a missing
  intermediate leg is not modelled (underestimate).
Assumptions: same-concourse gate swap adds 2 min taxi, other concourse 5 min (assumed). Ground hold
length = minutes to 5 min past the next clock hour at the destination, rounded up to 5, clipped
to [15, 60] (assumed: moves the arrival out of the congested hour without burning fuel).
"""

import math

from src import constraints
from src.schemas import Candidate, Scenario

CRUISE_NM_PER_MIN = 7.0  # 420 kt, assumed (same as builder and reviewer)
DIVERT_GROUND_MIN = 60.0  # assumed turn time at the alternate before returning
SAME_CONCOURSE_TAXI_MIN = 2  # assumed
OTHER_CONCOURSE_TAXI_MIN = 5  # assumed
SLOT_SHIFTS = (15, 30, -15, -30)
HOLD_MINUTES = (20, 40)
N_DIVERTS = 2
N_GATE_SWAPS = 2


def alternate(s: Scenario, iata: str) -> dict | None:
    return next((a for a in s.alternates if a["iata"] == iata), None)


def divert_out_min(s: Scenario, iata: str) -> float:
    """Flying time from the destination area to the alternate (420 kt assumed)."""
    alt = alternate(s, iata)
    return 0.0 if alt is None else alt["distance_nm"] / CRUISE_NM_PER_MIN


def airborne_extra_min(s: Scenario, c: Candidate) -> float:
    p = c.params
    if c.kind == "hold":
        return float(p.get("minutes", 0))
    if c.kind == "slot_shift":
        return float(max(p.get("shift_min", 0), 0))
    if c.kind == "divert":
        return divert_out_min(s, p.get("iata", ""))
    return 0.0


def added_delay_min(s: Scenario, c: Candidate) -> float:
    p = c.params
    if c.kind in ("hold", "ground_hold"):
        return float(p.get("minutes", 0))
    if c.kind == "slot_shift":
        return float(p.get("shift_min", 0))
    if c.kind == "gate_swap":
        return float(p.get("extra_taxi_min", 0))
    if c.kind == "divert":
        return 2 * divert_out_min(s, p.get("iata", "")) + DIVERT_GROUND_MIN
    return 0.0


def new_arrival_abs(s: Scenario, c: Candidate) -> float:
    return float(s.flight["actual_arr_abs"]) + added_delay_min(s, c)


def arrival_point(s: Scenario, c: Candidate) -> tuple[str, float]:
    if c.kind == "divert":
        iata = c.params.get("iata", "")
        return iata, float(s.flight["actual_arr_abs"]) + divert_out_min(s, iata)
    return s.flight["DESTINATION_AIRPORT"], new_arrival_abs(s, c)


def propagate_knock_on(s: Scenario, arrival_abs: float) -> list[dict]:
    """Per downstream leg: {row_index, ready_abs, departure_delay}. Pure."""
    turn = s.gates["min_turnaround_min"]
    ready = arrival_abs + turn
    out = []
    for leg in sorted(s.downstream_legs, key=lambda leg: leg["sched_dep_abs"]):
        delay = max(0.0, ready - leg["sched_dep_abs"])
        out.append({"row_index": leg["row_index"], "ready_abs": ready, "departure_delay": delay})
        ready = leg["sched_arr_abs"] + delay + turn
    return out


def knock_on_min(s: Scenario, arrival_abs: float) -> float:
    return round(sum(leg["departure_delay"] for leg in propagate_knock_on(s, arrival_abs)), 1)


def busy_overlap_min(intervals: list, start: float, end: float) -> float:
    """Minutes of [start, end] covered by the busy intervals."""
    return float(sum(max(0.0, min(end, b) - max(start, a)) for a, b in intervals))


def _slack_min(intervals: list, start: float, end: float) -> float:
    gaps = [start - b for a, b in intervals if b <= start] + [a - end for a, b in intervals if a >= end]
    return min(gaps) if gaps else math.inf


def _gate_choices(s: Scenario) -> list[tuple[str, int]]:
    g = s.gates
    assigned = g["assigned_gate"]
    ranked = []
    for gate, intervals in g["occupancy"].items():
        if gate == assigned:
            continue
        extra = SAME_CONCOURSE_TAXI_MIN if gate[0] == assigned[0] else OTHER_CONCOURSE_TAXI_MIN
        start = s.flight["actual_arr_abs"] + extra
        end = start + g["min_turnaround_min"]
        ranked.append((busy_overlap_min(intervals, start, end), -_slack_min(intervals, start, end), gate, extra))
    ranked.sort()
    # Never offer more swaps than the destination has spare gates (organiser workbook).
    n = min(N_GATE_SWAPS, constraints.airport(s.flight["DESTINATION_AIRPORT"]).spare_gates)
    return [(gate, extra) for _, _, gate, extra in ranked[:n]]


def _ground_hold_minutes(s: Scenario) -> int:
    arr = s.flight["actual_arr_abs"]
    to_next_hour = 60 - arr % 60 + 5
    return int(min(60, max(15, 5 * math.ceil(to_next_hour / 5))))


def _make(s: Scenario, cid: str, kind: str, params: dict) -> Candidate:
    c = Candidate(candidate_id=cid, kind=kind, params=params, est_delay_min=0.0, est_knock_on_min=0.0)
    c.est_delay_min = round(added_delay_min(s, c), 1)
    c.est_knock_on_min = knock_on_min(s, new_arrival_abs(s, c))
    return c


def generate_candidates(s: Scenario) -> list[Candidate]:
    out = [_make(s, f"SLOT{m:+d}", "slot_shift", {"shift_min": m}) for m in SLOT_SHIFTS]
    out += [_make(s, f"HOLD{m}", "hold", {"minutes": m}) for m in HOLD_MINUTES]
    out += [_make(s, f"DIVERT_{a['iata']}", "divert", {"iata": a["iata"]}) for a in s.alternates[:N_DIVERTS]]
    out += [
        _make(s, f"GATE_{gate}", "gate_swap", {"gate": gate, "extra_taxi_min": extra})
        for gate, extra in _gate_choices(s)
    ]
    origin = s.flight["ORIGIN_AIRPORT"]
    out.append(
        _make(s, f"GROUND_HOLD_{origin}", "ground_hold", {"minutes": _ground_hold_minutes(s), "airport": origin})
    )
    return out
