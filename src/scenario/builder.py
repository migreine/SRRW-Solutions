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
- alternates: [{iata, name, distance_nm, lat, lon}], 3 nearest to the destination.
- gates: {airport, assigned_gate, min_turnaround_min, turnaround_source, occupancy, source}.
  occupancy maps gate id -> [[start_abs, end_abs], ...], the busy intervals of OTHER aircraft.
- connections: [{row_index, flight_number, destination, sched_dep_abs, minutes_after_arrival,
  est_pax, source}], same-airline departures 45-180 min after actual arrival.

fuel_reserve_min is discretionary endurance: minutes of extra airborne time available before the
aircraft would land below the 14 CFR 121.639 requirement (destination + alternate + 45 min).
crew_duty_remaining_min is measured at the actual (unmitigated) arrival time.
"""

from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

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
EARTH_RADIUS_NM = 3440.065
EPOCH = pd.Timestamp("2015-01-01")

# Approximate good-weather arrival acceptance rates (arrivals per hour). Not verified against
# FAA ASPM; always tagged "assumed".
NOMINAL_AAR = {
    "ATL": 126, "ORD": 112, "DFW": 118, "DEN": 112, "LAX": 84, "SFO": 54, "LAS": 60, "IAH": 80,
    "PHX": 76, "CLT": 80, "MSP": 80, "DTW": 80, "SEA": 60, "EWR": 40, "LGA": 40, "JFK": 44,
    "BOS": 60, "MCO": 70, "MIA": 68, "DCA": 36,
}
DEFAULT_AAR = 40
HEAVY_DISTANCE_MI = 2500  # longer routes assumed flown by widebodies
FDP_LIMIT_MIN = 13 * 60  # 14 CFR 117 Table B mid-range, assumed (9-14 h by report time/segments)
TURNAROUND_MIN = {"H": 90, "L": 45, "S": 30}  # assumed per aircraft class
GATE_IDS = [f"{c}{n}" for c in "ABCD" for n in (2, 6, 12)]


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
    return {
        "hour_counts": f.groupby(["arr_day_idx", "DESTINATION_AIRPORT", "arr_hour"]).size(),
        "taxi_in_median": f.groupby("DESTINATION_AIRPORT").TAXI_IN.median(),
        "tail_day": f.groupby(["TAIL_NUMBER", "day_idx"]).indices,
        "airline_origin_day": f.groupby(["AIRLINE", "ORIGIN_AIRPORT", "day_idx"]).indices,
    }


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
    """Synthetic gate model, seeded per row so assignments are locked per scenario."""
    sched_arr = int(row.sched_arr_abs)
    assigned = GATE_IDS[int(rng.integers(len(GATE_IDS)))]
    occupancy = {}
    for gate in GATE_IDS:
        if gate == assigned:
            # Free for the planned turn, then the next aircraft is due a short gap later.
            prev_end = sched_arr - int(rng.integers(10, 30))
            next_start = sched_arr + turnaround + int(rng.integers(5, 26))
            occupancy[gate] = [[prev_end - 60, prev_end], [next_start, next_start + 60]]
            continue
        intervals, t = [], sched_arr - 180 + int(rng.integers(0, 60))
        while t < sched_arr + 420:
            length = int(rng.integers(40, 91))
            intervals.append([t, t + length])
            t += length + int(rng.integers(20, 150))
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

    contingency = 0.05 * float(row.AIR_TIME)
    extra = int(rng.integers(10, 31))
    fuel_reserve_min = Tagged(
        value=round(contingency + extra, 1),
        source="estimated",
        note=f"5% contingency of AIR_TIME ({contingency:.1f} min) + {extra} min discretionary (seeded); "
        "above the 121.639 destination+alternate+45 min requirement",
    )

    report = int(row.sched_dep_abs) - 60 - int(rng.integers(0, 361))
    remaining = FDP_LIMIT_MIN - (int(row.actual_arr_abs) - report)
    crew_duty_remaining_min = Tagged(
        value=remaining,
        source="synthetic",
        note=f"report at {report} min (seeded), FDP limit {FDP_LIMIT_MIN} min assumed, at actual arrival",
    )

    aar = NOMINAL_AAR.get(dest, DEFAULT_AAR)
    nominal_aar = Tagged(
        value=aar,
        source="assumed",
        note="approximate FAA rate, unverified" if dest in NOMINAL_AAR else "default for unlisted airport",
    )

    return Scenario(
        scenario_id=f"{flight['date']}_{row.AIRLINE}{int(row.FLIGHT_NUMBER)}_{row.TAIL_NUMBER}",
        row_index=row_index,
        flight=flight,
        dest_disruption=dest_disruption,
        taxi_congestion=taxi_congestion,
        downstream_legs=_downstream_legs(row),
        alternates=_alternates(dest),
        wake_category=wake_category,
        fuel_reserve_min=fuel_reserve_min,
        crew_duty_remaining_min=crew_duty_remaining_min,
        gates=_gates(row, TURNAROUND_MIN[wake], rng),
        connections=_connections(row, rng),
        nominal_aar=nominal_aar,
    )
