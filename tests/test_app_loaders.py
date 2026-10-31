"""Tests for app/loaders.py (Reine, T2). No streamlit import, no network."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import loaders as L
from src.schemas import AgentMessage, Candidate, Recommendation, RuleResult, Scenario, Turn

SAMPLE = Path(__file__).parent / "fixtures" / "sample_run"
SHOWCASE = SAMPLE / "2015-04-24_AA334_N469AA.json"
FAILURE = SAMPLE / "failure_showcase.json"
INVALID = SAMPLE / "2015-04-24_AA1389_N469AA.json"
EVENTS = {"run_start", "scenario_built", "candidates_generated", "rule_check", "round_start",
          "agent_message", "message_invalid", "intersection", "consensus", "fallback_fired",
          "reviewer_verdict", "recommendation", "human_decision", "run_end"}


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


# --- sample fixtures follow the documented layout and the shared schemas ----------------------


@pytest.mark.parametrize("path", [SHOWCASE, FAILURE, INVALID])
def test_sample_runs_follow_layout_and_schemas(path):
    run = load(path)
    assert list(run) == ["meta", "scenario", "candidates", "rule_results", "turns",
                         "recommendation", "fallback", "reviewer"]
    for k in ("scenario_id", "row_index", "agents", "model", "seed", "flags", "started_at",
              "latency_s", "cost_usd", "tokens_in", "tokens_out", "git_sha"):
        assert k in run["meta"], k
    s = Scenario.model_validate(run["scenario"])
    cands = [Candidate.model_validate(c) for c in run["candidates"]]
    rules = [RuleResult.model_validate(r) for r in run["rule_results"]]
    turns = [Turn.model_validate(t) for t in run["turns"]]
    Recommendation.model_validate(run["recommendation"])
    assert len(rules) == len(cands) * len({r.rule_id for r in rules})  # every (rule, candidate)
    ids = {c.candidate_id for c in cands}
    for t in turns:
        for m in t.messages:
            assert set(m.acceptable) <= ids
            assert not set(m.acceptable) & {v["candidate_id"] for v in m.vetoes}
            for r in m.ranking:
                assert "=" in "".join(r["cited_fields"]) or not r["cited_fields"]
    for k in ("fired", "reason", "objective", "n_eligible", "excluded"):
        assert k in run["fallback"]
    for k in ("verdict", "notes", "re_derived", "cited_mismatches", "engine_disagreements"):
        assert k in run["reviewer"]
    assert run["recommendation"]["log_path"] == f"runs/{s.scenario_id}.jsonl"
    # sibling log uses only the canonical event names and the right scenario id
    events, err = L.read_log(path.with_suffix(".jsonl"))
    assert err is None and events
    assert {e["event"] for e in events} <= EVENTS
    assert all(e["scenario_id"] == s.scenario_id and "+08:00" in e["ts"] for e in events)
    assert not any(e["event"] == "human_decision" for e in events)


def test_sample_round2_is_monotonic():
    run = load(SHOWCASE)
    r1, r2 = run["turns"]
    for a, b in zip(r1["messages"], r2["messages"]):
        assert a["agent"] == b["agent"] and set(b["acceptable"]) >= set(a["acceptable"])


# --- generic helpers -------------------------------------------------------------------------


def test_safe_get():
    d = {"a": {"b": [{"c": 1}, {"c": None}]}, "x": 0}
    assert L.safe_get(d, "a.b[0].c") == 1
    assert L.safe_get(d, "a.b[1].c", "dflt") == "dflt"  # None -> default
    assert L.safe_get(d, "a.b[5].c", "dflt") == "dflt"
    assert L.safe_get(d, "a.zz.c") is None
    assert L.safe_get(d, "x", 9) == 0  # falsy but present
    assert L.safe_get(None, "a", 3) == 3
    assert L.safe_get(SimpleNamespace(k={"v": 2}), "k.v") == 2
    assert L.safe_get(d, "a.b.c", "d") == "d"  # key lookup on a list


def test_source_colours():
    assert L.source_colour("synthetic") == "#6a1b9a"
    assert L.source_colour("DATA") == "#2e7d32"
    assert L.source_colour("made-up") == L.UNKNOWN_COLOUR == "#616161"
    assert L.source_colour(None) == L.UNKNOWN_COLOUR


def test_fmt_helpers():
    assert L.fmt_minutes(775) == "12:55" and L.fmt_minutes(None) == "—"
    assert L.fmt_minutes("n/a") == "n/a"
    assert L.fmt_value(None) == "—" and L.fmt_value(float("nan")) == "null"
    assert L.fmt_value(78.0) == "78"


# --- runs ------------------------------------------------------------------------------------


def test_list_runs_newest_first(tmp_path):
    (tmp_path / "live").mkdir()
    a, b, c = tmp_path / "a.json", tmp_path / "live" / "b.json", tmp_path / "c.json"
    for i, p in enumerate((a, b, c)):
        p.write_text("{}", encoding="utf-8")
        os.utime(p, (1_000_000 + i * 10, 1_000_000 + i * 10))
    (tmp_path / "meta.json").write_text("{}", encoding="utf-8")
    (tmp_path / "x.jsonl").write_text("", encoding="utf-8")
    runs = L.list_runs((str(tmp_path), str(tmp_path / "live"), str(tmp_path / "missing")))
    assert [p for _, p in runs] == [c, b, a]


def test_load_run_never_raises(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert "_load_error" in L.load_run(bad)
    assert "_load_error" in L.load_run(tmp_path / "missing.json")
    (tmp_path / "list.json").write_text("[1]", encoding="utf-8")
    assert "_load_error" in L.load_run(tmp_path / "list.json")
    assert L.load_run(SHOWCASE)["meta"]["scenario_id"] == "2015-04-24_AA334_N469AA"


def test_presets(tmp_path):
    runs = L.list_runs((str(SAMPLE),))
    assert L.failure_preset(runs).name == "failure_showcase.json"
    assert L.showcase_preset(runs).name == "2015-04-24_AA334_N469AA.json"
    # without failure_showcase.json: forced-deadlock file, then the first run with a fallback
    no_fs = [(lab, p) for lab, p in runs if p.name != "failure_showcase.json"]
    assert L.failure_preset(no_fs).name == "2015-04-24_AA1389_N469AA.json"
    dl = tmp_path / "aa334_forced_deadlock.json"
    dl.write_text("{}", encoding="utf-8")
    assert L.failure_preset(no_fs + [("dl", dl)]) == dl
    assert L.showcase_preset([("dl", dl)]) == dl  # deadlock only used if nothing cleaner
    assert L.failure_preset([("s", SHOWCASE)]) is None
    assert L.showcase_preset([]) is None


# --- provenance ------------------------------------------------------------------------------


def test_tagged_rows_and_counts():
    sc = load(SHOWCASE)["scenario"]
    rows = {r[0]: r for r in L.tagged_rows(sc)}
    assert rows["fuel_reserve_min"][1:3] == (78, "estimated")
    assert rows["crew_duty_remaining_min"][2] == "synthetic"
    assert rows["wake_category"][1] == "L" and "registry" in rows["wake_category"][3]
    assert L.source_counts(sc, include_untagged=False) == {
        "data": 2, "estimated": 1, "assumed": 2, "synthetic": 1}
    full = L.source_counts(sc)
    assert full["synthetic"] == 2 and full["estimated"] == 2  # + gates, connections
    assert "2 synthetic, 2 assumed and 2 estimated" in L.rests_on_line(full)
    assert L.tagged_rows(None) == [] and L.source_counts({})["data"] == 0
    nested = {"x": {"y": [{"value": 1, "source": "weird"}]}}
    assert L.tagged_rows(nested) == [("x.y[0]", 1, "weird", "")]


# --- run interpretation ----------------------------------------------------------------------


def test_fallback_and_reviewer_info():
    assert L.fallback_info({})["fired"] is False
    assert L.fallback_info({"fallback": None})["fired"] is False
    f = L.fallback_info(load(FAILURE))
    assert f["fired"] and f["reason"] == "reviewer_reject" and f["n_eligible"] == 2
    assert L.fallback_info({"recommendation": {"fallback": {"reason": "no_consensus"}}})["fired"]
    assert L.reviewer_info({})["verdict"] is None
    # mediator placeholder APPROVE without a reviewer block is not trusted
    assert L.reviewer_info({"recommendation": {"reviewer_verdict": "APPROVE"}})["verdict"] is None
    ph = L.reviewer_info({"reviewer": {"verdict": "APPROVE", "notes": ["reviewer not implemented"]}})
    assert ph["verdict"] is None and ph["placeholder"]
    assert L.reviewer_info(load(SHOWCASE))["verdict"] == "MODIFY"
    assert L.verdict_colour("REJECT") == "red" and L.verdict_colour(None) == "gray"


def test_round_explanation():
    assert L.round_explanation(load(SHOWCASE)) is None
    assert "after round 1 (reviewer_reject)" in L.round_explanation(load(FAILURE))
    assert "invalid_message" in L.round_explanation(load(INVALID))
    assert L.round_explanation({"turns": [], "meta": {"agents": "none"}}).startswith("Solver-only")
    assert L.round_explanation({"turns": [], "fallback": {"fired": True, "reason": "solver_only"}}
                               ).startswith("Solver-only")
    r1 = {"turns": [{"round": 1}], "recommendation": {"decided_by": "consensus"}}
    assert L.round_explanation(r1) == "Round 2 not needed: consensus in round 1."
    assert L.round_explanation({}) == "No negotiation rounds recorded in this run."


def test_how_user_knows():
    text = L.how_user_knows(load(FAILURE))
    assert "reviewer REJECT on HOLD20" in text and "fallback fired because reviewer_reject" in text
    assert "decided by fallback" in text
    assert "1 invalid agent message" in L.how_user_knows(load(INVALID))
    assert "reviewer not run" in L.how_user_knows({})


def test_rule_matrix_and_detail():
    run = load(SHOWCASE)
    mat = L.rule_matrix(run["rule_results"])
    assert mat.shape == (10, 6)
    assert mat.loc["HOLD40", "R-FUEL-01"] == "FAIL" and mat.loc["SLOT+15", "R-FUEL-01"] == "PASS"
    assert L.rule_matrix([]).empty
    passing = L.rules_pass_ids(run["rule_results"])
    assert "SLOT+15" in passing and "HOLD40" not in passing and "GATE_C30" not in passing
    det = L.rule_detail(run["rule_results"], "HOLD40")
    assert len(det) == 6 and {"citation", "source", "observed", "threshold"} <= set(det[0])
    assert L.rule_matrix([{"rule_id": "R1"}, {"candidate_id": "A", "rule_id": "R1",
                                               "passed": False}]).loc["A", "R1"] == "FAIL"


def test_ranking_for_sorted_and_tolerant():
    msg = {"ranking": [{"candidate_id": "A", "score": 0.2}, "junk",
                       {"candidate_id": "B", "score": "x"}, {"candidate_id": "C", "score": 0.9}]}
    assert [r["candidate_id"] for r in L.ranking_for(msg)] == ["C", "A", "B"]
    assert L.ranking_for({}) == []


# --- consensus log ---------------------------------------------------------------------------


def test_resolve_log_path(tmp_path):
    run = load(SHOWCASE)
    # recorded runs/<id>.jsonl does not exist in the repo -> sibling of the run file
    assert L.resolve_log_path(run, SHOWCASE) == SHOWCASE.with_suffix(".jsonl")
    recorded = tmp_path / "r.jsonl"
    recorded.write_text("", encoding="utf-8")
    assert L.resolve_log_path({"recommendation": {"log_path": str(recorded)}}, SHOWCASE) == recorded
    target = L.resolve_log_path({"recommendation": {"log_path": str(tmp_path / "new.jsonl")}},
                                tmp_path / "x.json")
    assert target == tmp_path / "new.jsonl"
    assert L.resolve_log_path({}, None) is None


def test_human_state(tmp_path):
    log = tmp_path / "s.jsonl"
    assert L.human_state(log) is None and L.human_state(None) is None
    lines = [{"event": "run_start", "scenario_id": "s"},
             {"event": "human_decision", "scenario_id": "s", "decision": "rejected", "by": "a"},
             "not json",
             {"event": "human_decision", "scenario_id": "s", "decision": "approved", "by": "b"},
             {"event": "run_end", "scenario_id": "s"}]
    log.write_text("\n".join(x if isinstance(x, str) else json.dumps(x) for x in lines) + "\n",
                   encoding="utf-8")
    st = L.human_state(log)
    assert st["decision"] == "approved" and st["by"] == "b"
    assert L.human_state(tmp_path)["decision"] == "unknown"  # a directory: unreadable
    events, err = L.read_log(log)
    assert len(events) == 4 and "1 malformed" in err


def test_append_human_decision(tmp_path):
    run_dir = tmp_path / "runs"
    shutil.copy(SHOWCASE, run_dir.mkdir() or run_dir / SHOWCASE.name)
    shutil.copy(SHOWCASE.with_suffix(".jsonl"), run_dir / SHOWCASE.with_suffix(".jsonl").name)
    run_file = run_dir / SHOWCASE.name
    before_json = run_file.read_bytes()
    log = run_dir / SHOWCASE.with_suffix(".jsonl").name
    n_before = len(log.read_text(encoding="utf-8").splitlines())

    ev = L.append_human_decision(log, "2015-04-24_AA334_N469AA", "approved", " Duty Mgr ", "ok")
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == n_before + 1
    last = json.loads(lines[-1])
    assert last["event"] == "human_decision" and last["decision"] == "approved"
    assert last["by"] == "Duty Mgr" and last["note"] == "ok"
    assert last["scenario_id"] == "2015-04-24_AA334_N469AA" and "+08:00" in last["ts"]
    assert {"ts", "event", "scenario_id", "decision", "by", "note"} <= set(last)
    assert ev["decision"] == "approved"
    assert run_file.read_bytes() == before_json  # run JSON never modified
    assert L.human_state(log)["decision"] == "approved"

    new = tmp_path / "deep" / "dir" / "new.jsonl"  # parent dirs created
    L.append_human_decision(new, "x", "rejected", "", "")
    assert json.loads(new.read_text(encoding="utf-8"))["by"] == "anonymous"
    with pytest.raises(ValueError):
        L.append_human_decision(new, "x", "maybe", "a", "")
    with pytest.raises(ValueError):
        L.append_human_decision("", "x", "approved", "a", "")


# --- evaluation ------------------------------------------------------------------------------


def test_load_summary_hand_made(tmp_path):
    p = tmp_path / "summary.csv"
    p.write_text(
        "metric,value,unit,n,definition,note\n"
        "n_completed,40,rows,200,finished,\n"
        "consensus_rate,0.55,fraction,40,consensus / n,\n"
        "fallback_rate_no_consensus,0.3,fraction,40,fb,\n"
        "fallback_rate_invalid_message,0.1,fraction,40,fb,\n"
        "modelled_delay_agents_mean,17.5,min,,est,\"model estimate; not comparable like-for-like "
        "with actual\"\n"
        "human_decision,pending,,40,never acts,\n", encoding="utf-8")
    s = L.load_summary(p)
    assert len(s) == 6
    assert s["n_completed"]["value"] == 40 and s["consensus_rate"]["value"] == 0.55
    assert s["modelled_delay_agents_mean"]["n"] is None  # blank n omitted
    assert s["modelled_delay_agents_mean"]["note"].startswith("model estimate;")
    assert s["human_decision"]["value"] == "pending"  # non-numeric kept as text
    assert L.metric_value(s, "fallback_rate_total") == pytest.approx(0.4)
    cards = dict((m, v) for m, _, v in L.headline_metrics(s))
    assert cards["consensus_rate"] == 0.55 and cards["schema_invalid_rate"] is None
    assert [m for m, _ in L.modelled_vs_actual(s)] == ["modelled_delay_agents_mean"]
    assert L.load_summary(tmp_path / "missing.csv") is None


def test_eval_fixture_and_meta(tmp_path, monkeypatch):
    s = L.load_summary(SAMPLE / "eval" / "summary.csv")
    assert s and all("SAMPLE" in r["note"] or r["note"].startswith(("model estimate", "data"))
                     for r in s.values())
    assert L.load_meta(SAMPLE / "eval" / "meta.json")["n_completed"] == 40
    assert L.load_meta(tmp_path / "nope.json") == {}
    monkeypatch.setenv("EVAL_RESULTS_DIR", str(tmp_path))
    assert L.eval_dir() == tmp_path
    monkeypatch.delenv("EVAL_RESULTS_DIR")
    assert L.eval_dir() == L.DEFAULT_EVAL_DIR


def test_fmt_metric():
    assert L.fmt_metric(None) == "—"
    assert L.fmt_metric(0.55, "fraction") == "55.0%"
    assert L.fmt_metric(40, "rows") == "40"
    assert L.fmt_metric(17.5, "min") == "17.5 min"
    assert L.fmt_metric(0.0031, "USD") == "$0.0031"
    assert L.fmt_metric("pending") == "pending"
