"""src/cli.py: run_one end to end on the fixture path (no flights.csv, no API)."""

import json

import pytest

from src.cli import main, run_one
from src.log.consensus_log import ConsensusLog
from src.schemas import Candidate, Recommendation, RuleResult, Scenario, Turn
from tests.fixtures.paths import out_dir  # noqa: F401  (pytest fixture)

TOP_KEYS = {"meta", "scenario", "candidates", "rule_results", "turns", "recommendation",
            "fallback", "reviewer"}
META_KEYS = {"scenario_id", "row_index", "agents", "model", "seed", "flags", "started_at",
             "latency_s", "cost_usd", "tokens_in", "tokens_out", "git_sha"}


def _files(out_dir, result):
    sid = result["meta"]["scenario_id"]
    return out_dir / f"{sid}.json", out_dir / f"{sid}.jsonl"


def test_fixture_mode_end_to_end(out_dir):
    result = run_one(0, "fixture", out_dir=out_dir, fixture=True)
    json_path, log_path = _files(out_dir, result)
    assert json_path.exists() and log_path.exists()

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert set(data) == TOP_KEYS and META_KEYS <= set(data["meta"])
    assert data["meta"]["flags"] == {"force_deadlock": False, "tamper_rules": False}
    s = Scenario.model_validate(data["scenario"])
    assert s.scenario_id.startswith("fixture_r0_") and s.row_index == 0
    [Candidate.model_validate(c) for c in data["candidates"]]
    assert len([RuleResult.model_validate(r) for r in data["rule_results"]]) == 48
    turns = [Turn.model_validate(t) for t in data["turns"]]
    rec = Recommendation.model_validate(data["recommendation"])
    assert rec.decided_by == "consensus" and rec.chosen.candidate_id == "SLOT+30"
    assert rec.rounds_used == 2 and len(turns) == 2
    assert rec.log_path == str(log_path) and rec.human_decision == "pending"
    assert data["fallback"]["fired"] is False
    assert data["reviewer"]["notes"] == ["reviewer not implemented"]

    names = [e["event"] for e in ConsensusLog(log_path).read_all()]
    assert names[0] == "run_start" and names[-1] == "run_end"
    for name in ("scenario_built", "candidates_generated", "round_start", "agent_message",
                 "intersection", "consensus", "reviewer_verdict", "recommendation"):
        assert name in names
    assert names.count("rule_check") == 48 and names.count("agent_message") == 6
    built = next(e for e in ConsensusLog(log_path).read_all() if e["event"] == "scenario_built")
    assert built["source_tag_counts"] == {"data": 2, "estimated": 1, "assumed": 2, "synthetic": 1}


def test_none_mode_is_solver_only(out_dir):
    result = run_one(0, "none", out_dir=out_dir, fixture=True)
    rec = Recommendation.model_validate(result["recommendation"])
    assert rec.rounds_used == 0 and rec.decided_by == "fallback" and result["turns"] == []
    assert result["fallback"]["reason"] == "solver_only" and result["fallback"]["fired"]
    assert rec.chosen.candidate_id == "SLOT-15" and result["meta"]["model"] is None
    log = ConsensusLog(_files(out_dir, result)[1]).read_all()
    assert not [e for e in log if e["event"] == "agent_message"]
    (fb,) = [e for e in log if e["event"] == "fallback_fired"]
    assert fb["reason"] == "solver_only" and fb["n_eligible"] == 6


def test_force_deadlock(out_dir):
    result = run_one(0, "fixture", out_dir=out_dir, force_deadlock=True)
    assert result["fallback"]["reason"] == "forced_deadlock"
    assert result["recommendation"]["decided_by"] == "fallback"
    assert result["meta"]["flags"]["force_deadlock"] is True


def test_rerun_overwrites_json_and_appends_jsonl(out_dir):
    first = run_one(0, "fixture", out_dir=out_dir)
    n1 = len(ConsensusLog(_files(out_dir, first)[1]).read_all())
    second = run_one(0, "none", out_dir=out_dir, fixture=True)
    json_path, log_path = _files(out_dir, second)
    assert len(ConsensusLog(log_path).read_all()) > n1
    assert json.loads(json_path.read_text(encoding="utf-8"))["meta"]["agents"] == "none"


def test_live_mode_without_key_fails_fast(out_dir, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        run_one(0, "haiku", out_dir=out_dir)
    assert list(out_dir.iterdir()) == []


def test_unknown_mode_rejected(out_dir):
    with pytest.raises(ValueError):
        run_one(0, "gpt", out_dir=out_dir)


def test_main_pretty_prints_table(out_dir, capsys):
    main(["--row-id", "0", "--agents", "fixture", "--pretty", "--out", str(out_dir)])
    text = capsys.readouterr().out
    for token in ("SLOT+30", "R-FUEL-01", "FAIL", "Decided by : consensus", "Reviewer",
                  "ATC", "PILOT", "GROUND"):
        assert token in text
    text.encode("ascii")  # the table must print on any Windows console


def test_main_missing_module_exits_cleanly(out_dir, capsys, monkeypatch):
    import src.scenario.builder as builder

    def not_ready(row_index, seed=42):
        raise NotImplementedError

    monkeypatch.setattr(builder, "build_scenario", not_ready)  # independent of merge state
    with pytest.raises(SystemExit) as exc:
        main(["--row-id", "0", "--agents", "none", "--out", str(out_dir)])
    assert exc.value.code == 2
    assert "not implemented" in capsys.readouterr().err
