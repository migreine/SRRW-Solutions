"""eval/run_eval.py on fixture data only (modes none / fixture / stub; no API, no flights.csv)."""

import csv
import json
from datetime import datetime, timedelta

from eval.run_eval import (
    MODELLED_NOTE,
    PER_SCENARIO_COLUMNS,
    SUMMARY_COLUMNS,
    guard_check,
    main,
    parse_deadline,
    read_sample_file,
)
from src.log.consensus_log import SGT
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

    m = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
    assert m == json.loads(json.dumps(meta))  # returned meta is what was written
    assert m["guard_stopped"] is False and m["n_completed"] == 3 and m["status"] == "done"
    assert m["n_completed_by_mode"] == {"none": 3, "fixture": 3}
    assert m["force_deadlock"] is False and m["tamper_rules"] is False
    assert "| fixture | consensus_rate | 1 |" in (out_dir / "summary.md").read_text(encoding="utf-8")

    # per-mode run folders: same scenario id under both modes does not collide
    for mode in ("none", "fixture"):
        assert len(list((out_dir / "runs" / mode).glob("*.json"))) == 3


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


def test_parse_deadline():
    now = datetime(2026, 10, 31, 9, 30, tzinfo=SGT)
    d = parse_deadline("15:05", now)
    assert (d.hour, d.minute, d.utcoffset()) == (15, 5, timedelta(hours=8))
    assert parse_deadline("none") is None
