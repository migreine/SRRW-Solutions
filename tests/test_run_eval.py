"""eval/run_eval.py on fixture data only (modes none / fixture / stub; no API, no flights.csv)."""

import csv
import json
from datetime import datetime, timedelta

import pytest

import src.cli as cli
from eval.run_eval import (
    FLIGHTS_PATH,
    MODELLED_NOTE,
    PER_SCENARIO_COLUMNS,
    SUMMARY_COLUMNS,
    actual_chain,
    chain_from_flights,
    guard_check,
    main,
    parse_deadline,
    read_sample_file,
)
from src.log.consensus_log import SGT
from src.schemas import Tagged
from tests.fixtures.paths import out_dir  # noqa: F401  (pytest fixture)


def _csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _metric(summary, name, mode):
    (row,) = [r for r in summary if r["metric"] == name and r["mode"] == mode]
    return row


def _args(out_dir, *extra):
    return ["--n", "3", "--out", str(out_dir), "--sample-ids", str(out_dir / "absent.csv"),
            "--deadline", "none", "--workers", "2", *extra]


def test_none_and_fixture_modes_write_all_outputs(out_dir):
    meta = main(_args(out_dir, "--modes", "none,fixture"))
    for name in ("per_scenario.csv", "summary.csv", "summary.md", "meta.json"):
        assert (out_dir / name).exists(), name

    rows = _csv(out_dir / "per_scenario.csv")
    assert list(rows[0]) == PER_SCENARIO_COLUMNS
    assert len(rows) == 6 and sorted({r["mode"] for r in rows}) == ["fixture", "none"]
    assert all(r["error"] == "" for r in rows)
    none_rows = [r for r in rows if r["mode"] == "none"]
    fx_rows = [r for r in rows if r["mode"] == "fixture"]
    assert {r["chosen_id"] for r in none_rows} == {"SLOT-15"}
    assert {r["fallback_reason"] for r in none_rows} == {"solver_only"}
    assert {r["chosen_id"] for r in fx_rows} == {"SLOT+30"} and {r["rounds_used"] for r in fx_rows} == {"2"}
    assert {r["actual_delay"] for r in rows} == {"101.0"} and {r["actual_chain"] for r in rows} == {"622.0"}
    assert {r["n_agent_calls"] for r in fx_rows} == {"6"}

    summary = _csv(out_dir / "summary.csv")
    assert list(summary[0]) == SUMMARY_COLUMNS
    assert float(_metric(summary, "consensus_rate", "fixture")["value"]) == 1.0
    assert float(_metric(summary, "consensus_round2_rate", "fixture")["value"]) == 1.0
    assert float(_metric(summary, "agents_vs_solver_same_pick_rate", "fixture")["value"]) == 0.0
    assert float(_metric(summary, "schema_invalid_rate", "fixture")["value"]) == 0.0
    assert float(_metric(summary, "agent_top_pick_rule_fail_rate", "fixture")["value"]) == 0.0
    assert float(_metric(summary, "fallback_rate_solver_only", "none")["value"]) == 1.0
    assert _metric(summary, "modelled_delay_agents_mean", "fixture")["note"] == MODELLED_NOTE
    assert _metric(summary, "modelled_delay_solver_mean", "none")["note"] == MODELLED_NOTE
    assert float(_metric(summary, "modelled_saving_vs_actual_mean", "fixture")["value"]) == 71.0
    assert _metric(summary, "human_decision", "fixture")["value"] == "pending"
    assert all(r["definition"] for r in summary)

    # Reviewer metrics come from the real reviewer: every run is APPROVE. Engine and reviewer
    # agree on all 8 candidates (both fail HOLD40 on fuel and DIVERT_AUS on duty, the reviewer now
    # subtracting the 101 min incurred delay); the fixture agents cite 34 path=value fields per
    # run, all matching the scenario.
    assert {r["verdict"] for r in rows} == {"APPROVE"}
    assert {r["n_candidates_reviewed"] for r in rows} == {"8"}
    assert {r["n_engine_disagreements"] for r in rows} == {"0"}
    assert {r["n_citations_with_value"] for r in fx_rows} == {"34"}
    assert {r["n_cited_value_mismatch"] for r in fx_rows} == {"0"}
    assert {r["reviewer_rejected_id"] for r in rows} == {""}
    for mode in ("none", "fixture"):
        assert float(_metric(summary, "reviewer_MODIFY_rate", mode)["value"]) == 0.0
        assert float(_metric(summary, "reviewer_APPROVE_rate", mode)["value"]) == 1.0
        assert float(_metric(summary, "reviewer_REJECT_rate", mode)["value"]) == 0.0
        dis = _metric(summary, "reviewer_engine_disagreement_rate", mode)
        assert float(dis["value"]) == 0.0 and dis["n"] == "24"
        assert "placeholder" not in dis["note"]
    cited = _metric(summary, "cited_value_mismatch_rate", "fixture")
    assert float(cited["value"]) == 0.0 and cited["n"] == "102"
    assert float(_metric(summary, "fallback_rate_reviewer_reject", "fixture")["value"]) == 0.0
    assert float(_metric(summary, "fallback_rate_reviewer_reject", "none")["value"]) == 0.0

    m = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
    assert m == json.loads(json.dumps(meta))  # returned meta is what was written
    assert m["guard_stopped"] is False and m["n_completed"] == 3 and m["status"] == "done"
    assert m["n_completed_by_mode"] == {"none": 3, "fixture": 3}
    assert m["force_deadlock"] is False and m["tamper_rules"] is False
    assert "| fixture | consensus_rate | 1 |" in (out_dir / "summary.md").read_text(encoding="utf-8")

    # per-mode run folders: same scenario id under both modes does not collide
    for mode in ("none", "fixture"):
        assert len(list((out_dir / "runs" / mode).glob("*.json"))) == 3


def _patch_scenario(monkeypatch, **updates):
    """Fixture inputs with Scenario fields replaced (fixture engine results unchanged)."""
    original = cli.load_inputs

    def patched(row_index, seed, fixture):
        s, candidates, rules = original(row_index, seed, fixture)
        return s.model_copy(update=updates), candidates, rules

    monkeypatch.setattr(cli, "load_inputs", patched)


def test_reviewer_reject_counted_from_real_reviewer(out_dir, monkeypatch):
    # fuel 97.1: the reviewer rejects consensus SLOT+30 (97.1-30=67.1 < 42.1 to the most distant
    # alternate + 45 reserve = 72.1); the fallback re-picks SLOT-15, which is also the solver-only
    # pick (and passes review there).
    _patch_scenario(monkeypatch, fuel_reserve_min=Tagged(value=97.1, source="estimated"))
    main(_args(out_dir, "--modes", "none,fixture"))
    rows = _csv(out_dir / "per_scenario.csv")
    fx_rows = [r for r in rows if r["mode"] == "fixture"]
    none_rows = [r for r in rows if r["mode"] == "none"]
    assert {(r["chosen_id"], r["decided_by"], r["fallback_reason"], r["reviewer_rejected_id"])
            for r in fx_rows} == {("SLOT-15", "fallback", "reviewer_reject", "SLOT+30")}
    assert {r["fallback_reason"] for r in none_rows} == {"solver_only"}
    assert {r["verdict"] for r in rows} == {"MODIFY"}
    # nobody accepts SLOT-15, so no supporting citations remain after the hand-over
    assert {r["n_citations_with_value"] for r in fx_rows} == {"0"}

    summary = _csv(out_dir / "summary.csv")
    assert float(_metric(summary, "fallback_rate_reviewer_reject", "fixture")["value"]) == 1.0
    assert float(_metric(summary, "fallback_rate_reviewer_reject", "none")["value"]) == 0.0
    assert float(_metric(summary, "consensus_rate", "fixture")["value"]) == 0.0
    assert float(_metric(summary, "agents_vs_solver_same_pick_rate", "fixture")["value"]) == 1.0
    # engine (fuel 105.1) vs reviewer (fuel 97.1): only SLOT+30 (fuel) disagrees, out of 8
    assert float(_metric(summary, "reviewer_engine_disagreement_rate", "fixture")["value"]) == 0.125
    assert _metric(summary, "cited_value_mismatch_rate", "fixture")["value"] == ""  # 0 / 0


def test_cited_value_mismatch_rate_from_reviewer(out_dir, monkeypatch):
    # dest_disruption 20 while ATC cites "dest_disruption=14" in each of its 2 + 3 ranking entries:
    # 5 mismatches out of 34 path=value citations per run (WAKE: 7200/70 = 102.9 s, still passes).
    _patch_scenario(monkeypatch, dest_disruption=Tagged(value=20, source="data"))
    main(_args(out_dir, "--modes", "fixture"))
    rows = _csv(out_dir / "per_scenario.csv")
    assert {(r["n_cited_mismatch"], r["n_cited_value_mismatch"], r["n_citations_with_value"])
            for r in rows} == {("5", "5", "34")}
    cited = _metric(_csv(out_dir / "summary.csv"), "cited_value_mismatch_rate", "fixture")
    assert float(cited["value"]) == pytest.approx(15 / 102, rel=1e-5) and cited["n"] == "102"


def test_resume_skips_done_rows(out_dir):
    main(_args(out_dir, "--modes", "none,fixture"))
    meta = main(_args(out_dir, "--modes", "none,fixture", "--resume"))
    assert len(_csv(out_dir / "per_scenario.csv")) == 6
    assert meta["stats_by_mode"]["fixture"]["n_todo"] == 0 and meta["n_completed"] == 3


def test_without_resume_starts_fresh(out_dir):
    main(_args(out_dir, "--modes", "none,fixture"))
    main(_args(out_dir, "--modes", "none", "--fixture"))
    rows = _csv(out_dir / "per_scenario.csv")
    assert {r["mode"] for r in rows} == {"none"} and len(rows) == 3
    assert all(r["error"] == "" for r in rows)


def test_stub_mode_on_fixture_data_completes_sweep(out_dir):
    meta = main(_args(out_dir, "--agents", "stub", "--modes", "none,stub", "--fixture"))
    rows = _csv(out_dir / "per_scenario.csv")
    assert len(rows) == 6 and meta["n_completed_by_mode"]["none"] == 3
    assert (out_dir / "summary.csv").exists() and (out_dir / "meta.json").exists()


def test_sample_file_is_used(out_dir):
    ids = out_dir / "ids.csv"
    ids.write_text("row_index\n7\n3\n9\n11\n", encoding="utf-8")
    assert read_sample_file(ids) == [7, 3, 9, 11]
    main(["--n", "2", "--out", str(out_dir), "--sample-ids", str(ids), "--deadline", "none",
          "--modes", "none", "--fixture"])
    assert [r["row_index"] for r in _csv(out_dir / "per_scenario.csv")] == ["7", "3"]


def test_guard_check():
    now = datetime(2026, 10, 31, 14, 0, tzinfo=SGT)
    late = now + timedelta(hours=1)
    assert guard_check(1, 200, 16.0, 10, 15.0, None, now).startswith("budget")
    assert guard_check(5, 200, 5.0, 10, 15.0, None, now) is None  # < 10 runs: no projection
    assert guard_check(10, 200, 1.0, 10, 15.0, None, now).startswith("projected_cost")  # $20
    assert guard_check(10, 200, 0.5, 10, 15.0, None, now) is None  # $10 projected
    assert guard_check(10, 200, 0.1, 600, 15.0, late, now).startswith("deadline")  # 3.2 h left
    assert guard_check(10, 200, 0.1, 60, 15.0, late, now) is None  # 19 min left


# ---- actual_chain (data, partial) ---------------------------------------------------------------
# Regression: the eval at 1f2c0ca reported actual_chain_mean = 0 on all 200 rows because the
# harness read leg["ARRIVAL_DELAY"] while src/scenario/builder.py names the key "arrival_delay".


def test_actual_chain_reads_the_builder_leg_key():
    builder_shape = {"downstream_legs": [{"row_index": 5, "arrival_delay": 30, "departure_delay": 25},
                                         {"row_index": 6, "arrival_delay": 12, "departure_delay": 0}]}
    assert actual_chain(builder_shape) == 42.0
    fixture_shape = {"downstream_legs": [{"ARRIVAL_DELAY": 102}, {"ARRIVAL_DELAY": 264}]}
    assert actual_chain(fixture_shape) == 366.0
    assert actual_chain({"downstream_legs": []}) == 0.0  # no later leg in the extract


def _flights_csv(path):
    cols = ["YEAR", "MONTH", "DAY", "TAIL_NUMBER", "SCHEDULED_DEPARTURE", "ARRIVAL_DELAY"]
    rows = [
        (2015, 4, 24, "N1", 900, 50),   # 0: earlier leg, same tail and day: excluded
        (2015, 4, 24, "N1", 1116, 101),  # 1: the scenario's own row: excluded
        (2015, 4, 24, "N1", 1348, 102),  # 2: later
        (2015, 4, 24, "N1", 2400, 7),    # 3: hhmm 2400 = 0 min (midnight), not later: excluded
        (2015, 4, 24, "N1", 1835, 256),  # 4: later
        (2015, 4, 24, "N2", 1500, 999),  # 5: other tail
        (2015, 4, 25, "N1", 1500, 999),  # 6: other day
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        w.writerows(rows)
    return path


def test_actual_chain_reads_flights_csv_when_scenario_omits_delays(out_dir):
    path = _flights_csv(out_dir / "flights_mini.csv")
    flight = {"TAIL_NUMBER": "N1", "YEAR": 2015, "MONTH": 4, "DAY": 24,
              "SCHEDULED_DEPARTURE": 11 * 60 + 16}  # Scenario keeps hhmm as minutes of day
    assert chain_from_flights(1, flight, path) == 102 + 256
    # legs without any arrival-delay key (outcomes deliberately omitted) -> flights.csv lookup
    s = {"row_index": 1, "flight": flight,
         "downstream_legs": [{"row_index": 2, "departure_delay": 90}, {"row_index": 4}]}
    assert actual_chain(s, path) == 358.0
    # missing tail/date keys or file -> None, never a silent 0
    assert chain_from_flights(1, {"YEAR": 2015}, path) is None
    assert actual_chain({**s, "flight": {}}, path) is None
    assert chain_from_flights(1, flight, out_dir / "absent.csv") is None


@pytest.mark.skipif(not FLIGHTS_PATH.exists(), reason="data/flights.csv not present")
def test_actual_chain_on_real_builder_scenario_matches_flights_csv():
    from src.agents.views import data_lines
    from src.scenario.builder import build_scenario

    s = build_scenario(123017)  # AA334 MFE->DFW 2015-04-24 N469AA, later legs exist
    d = s.model_dump()
    assert d["downstream_legs"] and all("arrival_delay" in leg for leg in d["downstream_legs"])
    from_scenario = actual_chain(d)
    from_csv = chain_from_flights(s.row_index, d["flight"])
    assert from_scenario > 0 and from_scenario == from_csv
    # the agents still never see an actual arrival delay, at any depth
    for role in ("ATC", "PILOT", "GROUND"):
        assert not [ln for ln in data_lines(s, role) if "arrival_delay" in ln.lower()]
    # later legs have not flown yet: none of their actual-outcome fields reach an agent either
    leg_lines = [ln for ln in data_lines(s, "GROUND") if ln.startswith("downstream_legs")]
    assert leg_lines and not [ln for ln in leg_lines if "departure_delay" in ln.lower()]


def test_parse_deadline():
    now = datetime(2026, 10, 31, 9, 30, tzinfo=SGT)
    d = parse_deadline("15:05", now)
    assert (d.hour, d.minute, d.utcoffset()) == (15, 5, timedelta(hours=8))
    assert parse_deadline("none") is None
