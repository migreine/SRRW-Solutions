import pandas as pd

from eval.sample import OUT, make_sample, make_sample_frame
from src.scenario.builder import load_flights


def test_counts_strata_and_filters():
    df = make_sample_frame()
    assert len(df) == 200 and df.row_index.is_unique
    counts = df.stratum.value_counts()
    assert counts["late_aircraft"] == 50
    assert sorted(counts[[f"weather_{h}" for h in ("ATL", "DEN", "DFW", "ORD")]]) == [37, 37, 38, 38]
    f = load_flights().loc[df.row_index]
    w = df.stratum.str.startswith("weather").to_numpy()
    assert (f.WEATHER_DELAY[w] > 15).all()
    assert f.DESTINATION_AIRPORT[w].isin(["ATL", "DEN", "DFW", "ORD"]).all()
    assert (f.LATE_AIRCRAFT_DELAY[~w] > 20).all()


def test_deterministic_and_matches_committed_file():
    ids = make_sample()
    assert ids == make_sample(200, 42)
    assert make_sample(200, 7) != ids
    assert pd.read_csv(OUT).row_index.tolist() == ids
