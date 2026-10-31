"""Turn a flights.csv row into a Scenario. Owner: Waseem (T1).

Time convention: every *_abs value is minutes since local midnight of the flight's departure date
(YEAR/MONTH/DAY). Arrival times are in destination local time, so an overnight arrival is > 1440.
hhmm 2400 is read as 0 (midnight).

Dict shapes (the contract other modules read; add keys freely, never rename):
- flight: raw row (hhmm columns converted to minutes of day) plus date, sched_dep_abs,
  sched_arr_abs, actual_dep_abs, actual_arr_abs.
- downstream_legs: [{row_index, airline, flight_number, origin, destination, sched_dep_abs,
  sched_arr_abs, departure_delay, arrival_delay, gap_after_actual_arrival_min}], same tail and date,
  scheduled after this flight. Partial: only delayed legs are in the data.
- alternates: [{iata, name, distance_nm, lat, lon}], the 3 nearest to the destination that are at
  least MIN_ALTERNATE_NM (30 nm) away. Closer airports (e.g. DAL at 9.8 nm from DFW) share the
  destination's terminal area and weather, so they are not credible weather alternates. Empty when
  the destination has no coordinates (ECP, PBG, UST).
- gates: {airport, assigned_gate, min_turnaround_min, turnaround_source, occupancy, source}.
  occupancy maps gate id -> [[start_abs, end_abs], ...], the busy intervals of OTHER aircraft.
  The plan is built around the projected gate-in actual_arr_abs (re-flowed to the latest ETA).
- connections: [{row_index, flight_number, destination, sched_dep_abs, minutes_after_arrival,
  est_pax, source}], same-airline departures 45-180 min after actual arrival.

Field semantics (binding for the rules engine and the reviewer, plan-rohan section 0 item 2):
- fuel_reserve_min.value: minutes of flying time available beyond the planned arrival at the
  destination, INCLUDING the final reserve. Built from the organiser workbook (docs/constraints.md):
  30 min final reserve + planned_alternate_min (most distant listed alternate,
  distance_nm / 7 nm per min, 420 kt assumed; 30 min assumed if there are no alternates)
  + 45 min spare fuel on arrival (includes the 5% contingency). Tagged "estimated".
  Engine and reviewer both pass FUEL iff value - airborne_extra >= alternate + 30 (divert: >= 30).
- crew_duty_remaining_min.value: FDP minutes remaining at the SCHEDULED arrival (gate-in). A
  legally scheduled crew has a non-negative remainder there, so the remainder is seeded in
  DUTY_REMAINING_RANGE [60, 420] (capped so the report time is at least 45 min before scheduled
  departure; docs/calibration.md). Max duty 13 h from report time for every flight (organiser
  workbook). The incurred ARRIVAL_DELAY is NOT subtracted here; the rules engine subtracts it.
  Tagged "synthetic".
- nominal_aar: workbook max_runway_ops_per_hour x 0.5 arrival share (assumed). gates
  min_turnaround_min: workbook per destination airport.
- Times: ARRIVAL_TIME / actual_arr_abs are gate-in times (they already include TAXI_IN).

Helpers for other modules (Scenario is frozen, so import these instead of adding fields):
- planned_alternate_min(alternates) -> minutes to the most distant listed alternate.
- delayed_arrivals_in_hour(dest, date_iso, abs_minute) -> delayed arrivals (data) at dest in the
  clock hour containing abs_minute on the flight's date axis (abs_minute may be > 1440 or < 0).
- arrival_hour_stats(dest, date_iso, abs_minute) -> {"delayed", "weather_delayed", "day", "hour"}.
"""

from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from src import constraints
from src.schemas import Scenario, Tagged

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
HHMM_COLUMNS = [
    "SCHEDULED_DEPARTURE",
    "DEPARTURE_TIME",
    "WHEELS_OFF",
    "WHEELS_ON",
    "SCHEDULED_ARRIVAL",
    "ARRIVAL_TIME",
]
EXCLUDED_ALTERNATES = {"ECP", "PBG", "UST"}  # no coordinates in airports.csv
MIN_ALTERNATE_NM = 30.0  # assumed: closer airports share the destination's terminal area/weather
CRUISE_NM_PER_MIN = 7.0  # 420 kt, assumed (same constant as the reviewer)
# Organiser workbook fuel_and_crew (src/constraints.py, docs/constraints.md). Minutes of holding;
# we treat a minute of holding fuel as a minute of airborne extra (assumed).
FINAL_RESERVE_MIN = constraints.fuel_crew("final_reserve_min")  # 30 min holding (was 45, 121.639)
CONTINGENCY_FRACTION = constraints.fuel_crew("contingency_fraction")  # 5% of trip (AIR_TIME)
# Spare fuel on arrival above final reserve + alternate (was seeded U[15, 40] + 5% contingency).
# The 5% contingency is assumed to be part of this spare, not added on top.
SPARE_FUEL_ON_ARRIVAL_MIN = constraints.fuel_crew("spare_fuel_on_arrival_min")  # 45 min holding
DEFAULT_ALTERNATE_MIN = 30.0  # assumed alternate time when no alternate can be ranked
EARTH_RADIUS_NM = 3440.065
EPOCH = pd.Timestamp("2015-01-01")


def nominal_aar(iata: str) -> float:
    """Arrival capacity/h: workbook max_runway_ops_per_hour x ARRIVAL_SHARE (0.5, assumed)."""
    return constraints.airport(iata).arrival_capacity_per_hour


HEAVY_DISTANCE_MI = 2500  # longer routes assumed flown by widebodies
# Organiser workbook: flight crew max duty 13 h from report time, every flight (was 13 h Table B,
# 17 h augmented when block > 9 h; the augmented case is dropped to follow the workbook).
FDP_LIMIT_MIN = int(constraints.fuel_crew("crew_max_duty_min"))
REPORT_BEFORE_DEP_MIN = 45  # assumed minimum report-to-departure time
# Seeded FDP remainder at scheduled arrival, synthetic. Calibrated 2026-10-31 (was (30, 300)):
# the leg can sit anywhere in the duty day. Lower end ~1 h = the delay buffer schedulers keep on the
# last leg of a long day (a 117.19 extension needs PIC concurrence, so pairings are not built to the
# limit); upper end ~7 h = first leg of a typical 8-10 h, 3-4 leg duty day. Assumed, not measured.
DUTY_REMAINING_RANGE = (60, 420)
# Min turnaround now per destination airport from the organiser workbook (was assumed per class,
# H 90 / L 45 / S 30): constraints.airport(dest).min_turnaround_min.
GATE_IDS = [f"{c}{n}" for c in "ABCD" for n in (2, 6, 12)]
# Synthetic gate model, seeded. The assigned gate is planned around the PROJECTED gate-in
# (actual_arr_abs): airline gate plans are re-flowed to the latest ETA once a delay is known.
# Calibrated 2026-10-31 (was: planned around the SCHEDULED arrival with 10-29 / 5-25 min gaps).
# Idle gap before our gate-in (previous occupant gone) and after our planned turn (next occupant
# due), minutes, [lo, hi). Assumed: hub gate plans keep a >= 10-15 min buffer between occupants
# and idle gaps of up to ~1 h between arrival banks.
ASSIGNED_GATE_PREV_GAP = (10, 41)
ASSIGNED_GATE_NEXT_GAP = (15, 61)
OTHER_GATE_BUSY = (40, 91)  # assumed occupancy per other aircraft (unchanged)
OTHER_GATE_IDLE = (20, 150)  # assumed idle gap between other aircraft, ~43% utilisation (unchanged)


def hhmm_to_min(v) -> int | None:
    """hhmm integer -> minutes since midnight. 2400 -> 0. NaN -> None."""
    if v is None or pd.isna(v):
        return None
    v = int(v)
    if v == 2400:
        return 0
    return (v // 100) * 60 + v % 100


def _hhmm_series(s: pd.Series) -> pd.Series:
    s = s.where(s != 2400, 0)
    return (s // 100) * 60 + s % 100


def _haversine_nm(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_NM * np.arcsin(np.sqrt(a))


@lru_cache(maxsize=1)
def load_flights() -> pd.DataFrame:
    """flights.csv plus derived absolute-time columns. Index = row_index."""
    f = pd.read_csv(DATA_DIR / "flights.csv")
    day = pd.to_datetime(dict(year=f.YEAR, month=f.MONTH, day=f.DAY))
    f["day_idx"] = (day - EPOCH).dt.days
    f["sched_dep_abs"] = _hhmm_series(f.SCHEDULED_DEPARTURE)
    # Arrival is local to the destination: pick the day offset that best matches the block time.
    arr = _hhmm_series(f.SCHEDULED_ARRIVAL)
    expected = f.sched_dep_abs + f.SCHEDULED_TIME
    f["sched_arr_abs"] = np.where((arr + 1440 - expected).abs() < (arr - expected).abs(), arr + 1440, arr)
    f["actual_dep_abs"] = f.sched_dep_abs + f.DEPARTURE_DELAY
    f["actual_arr_abs"] = f.sched_arr_abs + f.ARRIVAL_DELAY
    f["arr_day_idx"] = f.day_idx + f.actual_arr_abs // 1440
    f["arr_hour"] = (f.actual_arr_abs % 1440) // 60
    return f


@lru_cache(maxsize=1)
def load_airports() -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / "airports.csv").set_index("IATA_CODE")


@lru_cache(maxsize=1)
def _indexes():
    f = load_flights()
    keys = ["arr_day_idx", "DESTINATION_AIRPORT", "arr_hour"]
    return {
        "hour_counts": f.groupby(keys).size(),
        "hour_weather_counts": f[f.WEATHER_DELAY > 0].groupby(keys).size(),
        "taxi_in_median": f.groupby("DESTINATION_AIRPORT").TAXI_IN.median(),
        "tail_day": f.groupby(["TAIL_NUMBER", "day_idx"]).indices,
        "airline_origin_day": f.groupby(["AIRLINE", "ORIGIN_AIRPORT", "day_idx"]).indices,
    }


def _day_idx(date_iso: str) -> int:
    return (pd.Timestamp(date_iso) - EPOCH).days


def arrival_hour_stats(dest: str, date_iso: str, abs_minute: float) -> dict:
    """Delayed and weather-delayed arrivals (data, proxy) at dest in the clock hour of abs_minute.

    abs_minute is on the flight's date axis (minutes since local midnight of date_iso), so values
    >= 1440 fall on the next day and negative values on the previous day.
    """
    m = int(np.floor(abs_minute))
    day = _day_idx(date_iso) + m // 1440
    hour = (m % 1440) // 60
    idx = _indexes()
    key = (day, dest, hour)
    return {
        "delayed": int(idx["hour_counts"].get(key, 0)),
        "weather_delayed": int(idx["hour_weather_counts"].get(key, 0)),
        "day": int(day),
        "hour": int(hour),
    }


def delayed_arrivals_in_hour(dest: str, date_iso: str, abs_minute: float) -> int:
    """Delayed arrivals (data, proxy: delayed flights only) at dest in the hour of abs_minute."""
    return arrival_hour_stats(dest, date_iso, abs_minute)["delayed"]


def planned_alternate_min(alternates: list[dict]) -> float:
    """Minutes to the most distant listed alternate at 420 kt (assumed); default if none."""
    if not alternates:
        return DEFAULT_ALTERNATE_MIN
    return round(max(a["distance_nm"] for a in alternates) / CRUISE_NM_PER_MIN, 1)


def _clean(v):
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        return None if np.isnan(v) else float(v)
    return v


def _flight_dict(row: pd.Series) -> dict:
    d = {k: _clean(v) for k, v in row.items() if k not in ("day_idx", "arr_day_idx", "arr_hour")}
    for col in HHMM_COLUMNS:
        d[col] = hhmm_to_min(row[col])
    d["date"] = (EPOCH + timedelta(days=int(row.day_idx))).date().isoformat()
    return d


def _downstream_legs(row: pd.Series) -> list[dict]:
    f = load_flights()
    positions = _indexes()["tail_day"].get((row.TAIL_NUMBER, row.day_idx), [])
    legs = f.iloc[positions]
    legs = legs[(legs.index != row.name) & (legs.sched_dep_abs > row.sched_dep_abs)]
    return [
        {
            "row_index": int(i),
            "airline": leg.AIRLINE,
            "flight_number": int(leg.FLIGHT_NUMBER),
            "origin": leg.ORIGIN_AIRPORT,
            "destination": leg.DESTINATION_AIRPORT,
            "sched_dep_abs": int(leg.sched_dep_abs),
            "sched_arr_abs": int(leg.sched_arr_abs),
            "departure_delay": int(leg.DEPARTURE_DELAY),
            "arrival_delay": int(leg.ARRIVAL_DELAY),
            "gap_after_actual_arrival_min": int(leg.sched_dep_abs - row.actual_arr_abs),
        }
        for i, leg in legs.sort_values("sched_dep_abs").iterrows()
    ]


def _alternates(dest: str, n: int = 3) -> list[dict]:
    airports = load_airports()
    if dest not in airports.index or pd.isna(airports.loc[dest, "LATITUDE"]):
        return []  # no coordinates for the destination: no alternates can be ranked
    cand = airports.drop(index=[dest, *EXCLUDED_ALTERNATES], errors="ignore").dropna(
        subset=["LATITUDE", "LONGITUDE"]
    )
    dist = _haversine_nm(
        airports.loc[dest, "LATITUDE"], airports.loc[dest, "LONGITUDE"], cand.LATITUDE, cand.LONGITUDE
    )
    dist = dist[dist >= MIN_ALTERNATE_NM]  # same terminal area and weather: not an alternate
    return [
        {
            "iata": iata,
            "name": cand.loc[iata, "AIRPORT"],
            "distance_nm": round(float(dist[iata]), 1),
            "lat": float(cand.loc[iata, "LATITUDE"]),
            "lon": float(cand.loc[iata, "LONGITUDE"]),
        }
        for iata in dist.nsmallest(n).index
    ]


def _connections(row: pd.Series, rng: np.random.Generator, limit: int = 6) -> list[dict]:
    f = load_flights()
    arr_day = int(row.arr_day_idx)
    positions = _indexes()["airline_origin_day"].get((row.AIRLINE, row.DESTINATION_AIRPORT, arr_day), [])
    deps = f.iloc[positions]
    offset = (arr_day - row.day_idx) * 1440  # express on this flight's date axis
    deps = deps.assign(after=deps.sched_dep_abs + offset - row.actual_arr_abs)
    deps = deps[(deps.after >= 45) & (deps.after <= 180)].sort_values("after").head(limit)
    return [
        {
            "row_index": int(i),
            "flight_number": int(d.FLIGHT_NUMBER),
            "destination": d.DESTINATION_AIRPORT,
            "sched_dep_abs": int(d.sched_dep_abs + offset),
            "minutes_after_arrival": int(d.after),
            "est_pax": int(rng.integers(5, 41)),
            "source": "estimated",
        }
        for i, d in deps.iterrows()
    ]


def _gates(row: pd.Series, turnaround: int, rng: np.random.Generator) -> dict:
    """Synthetic gate model, seeded per row so assignments are locked per scenario.

    Planned around the projected gate-in (actual_arr_abs), see ASSIGNED_GATE_* above.
    """
    planned_arr = int(row.actual_arr_abs)
    assigned = GATE_IDS[int(rng.integers(len(GATE_IDS)))]
    occupancy = {}
    for gate in GATE_IDS:
        if gate == assigned:
            # Free for the planned turn, then the next aircraft is due a gap later.
            prev_end = planned_arr - int(rng.integers(*ASSIGNED_GATE_PREV_GAP))
            next_start = planned_arr + turnaround + int(rng.integers(*ASSIGNED_GATE_NEXT_GAP))
            occupancy[gate] = [[prev_end - 60, prev_end], [next_start, next_start + 60]]
            continue
        intervals, t = [], planned_arr - 180 + int(rng.integers(0, 60))
        while t < planned_arr + 420:
            length = int(rng.integers(*OTHER_GATE_BUSY))
            intervals.append([t, t + length])
            t += length + int(rng.integers(*OTHER_GATE_IDLE))
        occupancy[gate] = intervals
    return {
        "airport": row.DESTINATION_AIRPORT,
        "assigned_gate": assigned,
        "min_turnaround_min": turnaround,
        "turnaround_source": "assumed",
        "occupancy": occupancy,
        "source": "synthetic",
    }


def build_scenario(row_index: int, seed: int = 42) -> Scenario:
    f = load_flights()
    row = f.loc[row_index]
    idx = _indexes()
    rng = np.random.default_rng([seed, row_index])  # same row + seed -> same synthetic state
    dest = row.DESTINATION_AIRPORT
    flight = _flight_dict(row)

    count = int(idx["hour_counts"].get((row.arr_day_idx, dest, row.arr_hour), 0))
    dest_disruption = Tagged(
        value=count,
        source="data",
        note=f"delayed arrivals at {dest} in hour {int(row.arr_hour):02d}:00 (proxy, delayed flights only)",
    )

    median = float(idx["taxi_in_median"].get(dest, np.nan))
    taxi_congestion = Tagged(
        value=round(float(row.TAXI_IN) / median, 2) if median else 1.0,
        source="data",
        note=f"TAXI_IN {int(row.TAXI_IN)} min vs {dest} median {median:g} min",
    )

    heavy = row.DISTANCE > HEAVY_DISTANCE_MI
    wake = "H" if heavy else "L"
    wake_category = Tagged(
        value=wake,
        source="assumed",
        note=f"no registry lookup; DISTANCE {int(row.DISTANCE)} mi {'>' if heavy else '<='} {HEAVY_DISTANCE_MI} -> {wake}",
    )

    alternates = _alternates(dest)
    alt_min = planned_alternate_min(alternates)
    contingency = round(CONTINGENCY_FRACTION * float(row.AIR_TIME), 1)
    spare = SPARE_FUEL_ON_ARRIVAL_MIN
    alt_label = f"most distant alternate {max(alternates, key=lambda a: a['distance_nm'])['iata']}" if alternates else "no alternate ranked, assumed"
    fuel_reserve_min = Tagged(
        value=round(FINAL_RESERVE_MIN + alt_min + spare, 1),
        source="estimated",
        note=f"minutes beyond planned arrival incl. final reserve: {FINAL_RESERVE_MIN:g} final reserve "
        f"+ {alt_min:g} to {alt_label} (420 kt assumed) + {spare:g} spare fuel on arrival, which "
        f"includes {contingency:g} unburnt contingency (5% of AIR_TIME {int(row.AIR_TIME)}); "
        f"{constraints.NOTE}",
    )

    block = int(row.SCHEDULED_TIME)
    fdp_limit = FDP_LIMIT_MIN
    lo, hi = DUTY_REMAINING_RANGE
    hi = max(lo, min(hi, fdp_limit - block - REPORT_BEFORE_DEP_MIN))
    remaining = int(rng.integers(lo, hi + 1))
    report = int(row.sched_arr_abs) - (fdp_limit - remaining)
    crew_duty_remaining_min = Tagged(
        value=remaining,
        source="synthetic",
        note=f"FDP remaining at SCHEDULED arrival (incurred delay not subtracted); report at {report} "
        f"min (seeded), max duty {fdp_limit} min from report ({constraints.NOTE})",
    )

    lim = constraints.airport(dest)
    nominal_aar_t = Tagged(
        value=lim.arrival_capacity_per_hour,
        source=constraints.SOURCE,
        note=f"{constraints.NOTE}: {lim.max_runway_ops_per_hour} runway ops/h x {constraints.ARRIVAL_SHARE} "
        f"arrival share (assumed)" + ("" if lim.listed else f"; {dest} not listed, default row"),
    )

    return Scenario(
        scenario_id=f"{flight['date']}_{row.AIRLINE}{int(row.FLIGHT_NUMBER)}_{row.TAIL_NUMBER}",
        row_index=row_index,
        flight=flight,
        dest_disruption=dest_disruption,
        taxi_congestion=taxi_congestion,
        downstream_legs=_downstream_legs(row),
        alternates=alternates,
        wake_category=wake_category,
        fuel_reserve_min=fuel_reserve_min,
        crew_duty_remaining_min=crew_duty_remaining_min,
        gates=_gates(row, lim.min_turnaround_min, rng),
        connections=_connections(row, rng),
        nominal_aar=nominal_aar_t,
    )
