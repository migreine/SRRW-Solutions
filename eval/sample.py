"""Seeded evaluation sample. Owner: Waseem (T1).

    python -m eval.sample            # writes eval/sample_ids.csv (committed)

n=200: 150 rows with WEATHER_DELAY > 15 and DESTINATION_AIRPORT in ATL/DEN/DFW/ORD, stratified
equally (38, 38, 37, 37 in that order), plus 50 rows with LATE_AIRCRAFT_DELAY > 20 from the rest
of the file (excluding rows already picked). np.random.default_rng(seed), seed 42. Each pool is
shuffled once and walked in order, keeping only rows whose Scenario builds.
CSV columns: row_index (0-based flights.csv position, plan-rohan section 0 item 1), stratum
("weather_<IATA>" or "late_aircraft").
"""

from pathlib import Path

import numpy as np
import pandas as pd

from src.scenario.builder import build_scenario, load_flights

HUBS = ("ATL", "DEN", "DFW", "ORD")
OUT = Path(__file__).resolve().parent / "sample_ids.csv"


def _take(pool: np.ndarray, k: int, rng: np.random.Generator, taken: set[int]) -> list[int]:
    out = []
    for i in rng.permutation(pool):
        if len(out) == k:
            break
        i = int(i)
        if i in taken:
            continue
        try:
            build_scenario(i)
        except Exception:
            continue
        out.append(i)
        taken.add(i)
    return out


def make_sample_frame(n: int = 200, seed: int = 42) -> pd.DataFrame:
    f = load_flights()
    rng = np.random.default_rng(seed)
    n_weather = round(n * 0.75)
    per_hub = [n_weather // len(HUBS) + (j < n_weather % len(HUBS)) for j in range(len(HUBS))]
    taken: set[int] = set()
    rows = []
    for hub, k in zip(HUBS, per_hub):
        pool = f.index[(f.WEATHER_DELAY > 15) & (f.DESTINATION_AIRPORT == hub)].to_numpy()
        rows += [(i, f"weather_{hub}") for i in _take(pool, k, rng, taken)]
    pool = f.index[f.LATE_AIRCRAFT_DELAY > 20].to_numpy()
    rows += [(i, "late_aircraft") for i in _take(pool, n - n_weather, rng, taken)]
    return pd.DataFrame(rows, columns=["row_index", "stratum"])


def make_sample(n: int = 200, seed: int = 42) -> list[int]:
    return make_sample_frame(n, seed).row_index.tolist()


def main() -> None:
    df = make_sample_frame()
    df.to_csv(OUT, index=False)
    print(f"wrote {len(df)} rows to {OUT}")
    print(df.stratum.value_counts().to_string())


if __name__ == "__main__":
    main()
