"""Seeded evaluation sample. Owner: Waseem (T1).

200 rows: 150 with WEATHER_DELAY > 15 across ORD, ATL, DFW and DEN, plus 50 with
LATE_AIRCRAFT_DELAY > 20. Seed 42. Writes eval/sample_ids.csv (row indices), which is committed.
"""


def make_sample(n: int = 200, seed: int = 42) -> list[int]:
    raise NotImplementedError
