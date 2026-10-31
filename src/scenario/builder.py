"""Turn a flights.csv row into a Scenario. Owner: Waseem (T1).

Task card (docs/timeline.md, build block 1):
- Load data/flights.csv and data/airports.csv.
- Normalise hhmm times to minutes since midnight, including 2400 and midnight wrap-around.
- dest_disruption: delayed arrivals at the destination in the arrival hour, tagged "data".
- taxi_congestion: TAXI_IN vs that airport's median, tagged "data".
- downstream_legs: the same TAIL_NUMBER's later legs that day.
- alternates: 3 nearest airports by great-circle distance; skip ECP, PBG, UST (no coordinates).
- Seeded synthetic gates, crew duty and fuel, each a Tagged value with its source.
Done when the AA334 / N469AA row (24 Apr 2015) builds and tests/test_scenario.py passes.
"""

from src.schemas import Scenario


def build_scenario(row_index: int, seed: int = 42) -> Scenario:
    raise NotImplementedError
