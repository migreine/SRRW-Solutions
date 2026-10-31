"""src/cli.py: run_one end to end on the fixture path (no flights.csv, no API)."""

import json

import pytest

import src.cli as cli
from src.cli import ESCALATE_NOTE, main, run_one
from src.log.consensus_log import ConsensusLog
from src.schemas import Candidate, Recommendation, RuleResult, Scenario, Tagged, Turn
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

    # Real reviewer: SLOT+30 passes FUEL 105.1-30=75.1 >= 27.1 (most distant alternate AUS) + 45 =
    # 72.1, DUTY 150-30=120, WAKE 94.7 s >= 77.1 s; the
    # engine fails DIVERT_AUS on duty (est 165 min) but the reviewer derives 190/7+60 = 87 min.
    rv = data["reviewer"]
    assert rv["verdict"] == "MODIFY" == rec.reviewer_verdict
    assert rv["engine_disagreements"] == [{"rule_id": "R-DUTY-01", "candidate_id": "DIVERT_AUS",
                                           "engine_passed": False, "reviewer_passed": True}]
    assert len(rv["re_derived"]) == 8 * 3  # every candidate, FUEL/DUTY/WAKE
    assert rv["cited_mismatches"] == [] and rv["citations_with_value"] == 34
    assert rv["candidate_id"] == "SLOT+30" and rv["escalated"] is False
    assert rv["initial_review"] is None
    assert rec.reviewer_notes == rv["notes"] and rec.reviewer_detail["verdict"] == "MODIFY"
    assert any(n.startswith("ENGINE: R-DUTY-01 failed DIVERT_AUS") for n in rv["notes"])

    names = [e["event"] for e in ConsensusLog(log_path).read_all()]
    assert names.count("reviewer_verdict") == 1 and names.count("fallback_fired") == 0
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
    assert rec.reviewer_verdict == "MODIFY"  # SLOT-15 passes; DIVERT_AUS engine disagreement
    assert result["reviewer"]["citations_with_value"] == 0  # no agents, no citations
    log = ConsensusLog(_files(out_dir, result)[1]).read_all()
    assert not [e for e in log if e["event"] == "agent_message"]
    (fb,) = [e for e in log if e["event"] == "fallback_fired"]
    assert fb["reason"] == "solver_only" and fb["n_eligible"] == 6


def test_force_deadlock(out_dir):
    result = run_one(0, "fixture", out_dir=out_dir, force_deadlock=True)
    assert result["fallback"]["reason"] == "forced_deadlock"
    assert result["recommendation"]["decided_by"] == "fallback"
    assert result["meta"]["flags"]["force_deadlock"] is True


def _patch_scenario(monkeypatch, **updates):
    """Fixture inputs with Scenario fields replaced; the fixture engine results are unchanged, so
    the engine still passes what the reviewer now fails (an upstream fault the reviewer catches)."""
    original = cli.load_inputs

    def patched(row_index, seed, fixture):
        s, candidates, rules = original(row_index, seed, fixture)
        return s.model_copy(update=updates), candidates, rules

    monkeypatch.setattr(cli, "load_inputs", patched)


def _events(result, out_dir, name):
    return [e for e in ConsensusLog(_files(out_dir, result)[1]).read_all() if e["event"] == name]


def test_reviewer_rejects_consensus_pick_and_fallback_takes_over(out_dir, monkeypatch):
    # fuel 97.1 (old 70 + 27.1 alternate time): consensus SLOT+30 leaves 97.1-30=67.1 < 27.1 to the
    # most distant alternate (AUS) + 45 reserve = 72.1 -> REJECT. Reviewer also fails HOLD40
    # (97.1-40=57.1). DIVERT_AUS needs only the 45 min reserve on arrival (97.1-27.1=70 >= 45), so
    # the reviewer passes it, but the engine still fails it on duty. The fallback excludes HOLD40
    # and SLOT+30 and picks SLOT-15 (objective -15+30=15) from
    # SLOT+15/SLOT-15/HOLD20/GATE_B12/GROUND_HOLD_MFE.
    _patch_scenario(monkeypatch, fuel_reserve_min=Tagged(value=97.1, source="estimated"))
    result = run_one(0, "fixture", out_dir=out_dir)
    rec = Recommendation.model_validate(result["recommendation"])

    assert rec.decided_by == "fallback" and rec.chosen.candidate_id == "SLOT-15"
    assert rec.rounds_used == 2
    fb = result["fallback"]
    assert fb["fired"] and fb["reason"] == "reviewer_reject"
    assert fb["rejected_candidate_id"] == "SLOT+30" and fb["previous_decided_by"] == "consensus"
    assert fb["excluded"] == ["HOLD40", "SLOT+30"] and fb["n_eligible"] == 5
    assert fb["objective"] == 15

    # SLOT-15 passes the re-review; MODIFY because the engine (fuel 105.1) and reviewer (fuel 97.1)
    # disagree on SLOT+30 fuel, and on DIVERT_AUS duty as in the base case.
    rv = result["reviewer"]
    assert rv["verdict"] == "MODIFY" == rec.reviewer_verdict and rv["candidate_id"] == "SLOT-15"
    assert rv["escalated"] is False and rv["initial_review"]["verdict"] == "REJECT"
    assert {(d["rule_id"], d["candidate_id"]) for d in rv["engine_disagreements"]} == {
        ("R-FUEL-01", "SLOT+30"), ("R-DUTY-01", "DIVERT_AUS")}
    assert rv["notes"][0].startswith("REVIEWER: REJECT of SLOT+30 (decided by consensus)")
    assert any(n.startswith("FUEL re-derived: SLOT+30") and "FAIL" in n for n in rv["notes"])
    assert any(n.startswith("FUEL re-derived: SLOT-15") and "PASS" in n for n in rv["notes"])
    assert rec.reviewer_detail["initial_review"]["verdict"] == "REJECT"

    log = ConsensusLog(_files(out_dir, result)[1]).read_all()
    names = [e["event"] for e in log]
    i = names.index("consensus")
    assert names[i + 1:i + 5] == ["reviewer_verdict", "fallback_fired", "reviewer_verdict",
                                  "recommendation"]
    first, second = [e for e in log if e["event"] == "reviewer_verdict"]
    assert (first["stage"], first["final"], first["verdict"], first["candidate_id"]) == (
        "review", False, "REJECT", "SLOT+30")
    assert (second["stage"], second["final"], second["verdict"], second["candidate_id"]) == (
        "re_review", True, "MODIFY", "SLOT-15")
    (fired,) = _events(result, out_dir, "fallback_fired")
    assert fired["reason"] == "reviewer_reject" and fired["candidate_id"] == "SLOT-15"
    assert fired["rejected_candidate_id"] == "SLOT+30"
    (final,) = _events(result, out_dir, "recommendation")
    assert final["decided_by"] == "fallback" and final["candidate_id"] == "SLOT-15"
    assert final["reviewer_verdict"] == "MODIFY"

    text = cli.render_pretty(result)
    assert "fallback reason: reviewer_reject" in text and "reviewer rejected SLOT+30" in text


def test_reviewer_wake_fail_everywhere_escalates(out_dir, monkeypatch):
    # nominal_aar 120: 7200 / (120-14) = 67.9 s < 77.1 s, so WAKE fails for every candidate
    # (airport-level); nothing is eligible after exclusion -> chosen=None, escalate.
    _patch_scenario(monkeypatch, nominal_aar=Tagged(value=120, source="assumed"))
    result = run_one(0, "fixture", out_dir=out_dir)
    rec = Recommendation.model_validate(result["recommendation"])
    assert rec.chosen is None and rec.decided_by == "fallback"
    assert rec.reviewer_verdict == "REJECT" and rec.reviewer_notes[-1] == ESCALATE_NOTE
    assert result["fallback"]["reason"] == "reviewer_reject"
    assert result["fallback"]["chosen"] is None and result["fallback"]["n_eligible"] == 0
    rv = result["reviewer"]
    assert rv["escalated"] is True and rv["candidate_id"] is None
    wake = [d for d in rv["engine_disagreements"] if d["rule_id"] == "R-WAKE-01"]
    assert len(wake) == 8 and all(d["engine_passed"] and not d["reviewer_passed"] for d in wake)
    assert len(rv["engine_disagreements"]) == 9  # + R-DUTY-01 DIVERT_AUS, as in the base case
    stages = [(e["stage"], e["final"]) for e in _events(result, out_dir, "reviewer_verdict")]
    assert stages == [("review", False), ("escalation", True)]
    (final,) = _events(result, out_dir, "recommendation")
    assert final["candidate_id"] is None and final["reviewer_verdict"] == "REJECT"
    assert "NONE - " + ESCALATE_NOTE in cli.render_pretty(result)


def test_reviewer_rejects_fallback_pick_too_escalates(out_dir, monkeypatch):
    # Force REJECT on every review: the fallback's pick is reviewed once more, then escalated.
    import src.reviewer.safety as safety

    real = safety.review_detail

    def always_reject(s, rec, turns, *, candidates=None):
        return {**real(s, rec, turns, candidates=candidates), "verdict": "REJECT"}

    monkeypatch.setattr(safety, "review_detail", always_reject)
    result = run_one(0, "fixture", out_dir=out_dir)
    assert result["recommendation"]["chosen"] is None
    assert result["recommendation"]["reviewer_verdict"] == "REJECT"
    # first exclusion: rejected SLOT+30 plus HOLD40 (reviewer fuel fail); fallback picked SLOT-15
    assert result["fallback"]["excluded"] == ["HOLD40", "SLOT+30"]
    assert result["fallback"]["chosen"] == "SLOT-15"
    assert result["reviewer"]["notes"][-1] == ESCALATE_NOTE
    stages = [(e["stage"], e["candidate_id"]) for e in _events(result, out_dir, "reviewer_verdict")]
    assert stages == [("review", "SLOT+30"), ("re_review", "SLOT-15"), ("escalation", None)]


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
    for token in ("SLOT+30", "R-FUEL-01", "FAIL", "Decided by : consensus", "Reviewer   : MODIFY",
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
