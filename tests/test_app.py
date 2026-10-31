"""Headless render tests for app/streamlit_app.py (Reine, T2).

Uses streamlit.testing.v1.AppTest, which runs the script in-process without starting a server.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py")
SAMPLE = Path(__file__).parent / "fixtures" / "sample_run"
TIMEOUT = 60


def copy_runs(dst: Path) -> Path:
    dst.mkdir(parents=True, exist_ok=True)
    for p in SAMPLE.glob("*.json*"):
        shutil.copy(p, dst / p.name)
    return dst


def texts(at) -> str:
    parts = []
    for kind in ("title", "header", "subheader", "markdown", "caption", "error", "warning",
                 "info", "success"):
        parts += [str(e.value) for e in getattr(at, kind)]
    return "\n".join(parts)


def assert_clean(at):
    assert not at.exception, [e.value for e in at.exception]
    bad = [w.value for w in at.warning if "could not render" in str(w.value)]
    assert not bad, bad


def make_app(monkeypatch, runs_dir, eval_dir) -> AppTest:
    monkeypatch.setenv("RUN_DIRS", str(runs_dir))
    monkeypatch.setenv("EVAL_RESULTS_DIR", str(eval_dir))
    return AppTest.from_file(APP, default_timeout=TIMEOUT)


def test_module_imports_without_rendering():
    import app.streamlit_app as ui

    assert callable(ui.main) and callable(ui.panel_evaluation)


def test_renders_every_panel_on_real_layout(tmp_path, monkeypatch):
    runs = copy_runs(tmp_path / "runs")
    at = make_app(monkeypatch, runs, SAMPLE / "eval").run()
    assert_clean(at)
    body = texts(at)
    for h in ("1 · Scenario", "2 · Negotiation", "3 · Checks", "4 · Recommendation",
              "Evaluation", "Consensus log"):
        assert h in body, h
    assert "SAMPLE FIXTURE evaluation" in body


def test_select_each_run_and_presets(tmp_path, monkeypatch):
    runs = copy_runs(tmp_path / "runs")
    at = make_app(monkeypatch, runs, tmp_path / "no_eval").run()
    labels = at.sidebar.selectbox[0].options
    assert len(labels) == 3
    for label in labels:
        at.sidebar.selectbox[0].select(label).run()
        assert_clean(at)

    at.sidebar.button[1].click().run()  # Failure case
    assert_clean(at)
    body = texts(at)
    assert at.sidebar.selectbox[0].value.endswith("failure_showcase.json")
    assert "Deterministic fallback fired: **reviewer_reject**" in body
    assert "How the user knows: reviewer REJECT on HOLD20" in body
    assert "Evaluation not run" in body  # eval dir missing -> info, no crash

    at.sidebar.button[0].click().run()  # Showcase AA334
    assert_clean(at)
    assert at.title[0].value == "2015-04-24_AA334_N469AA"
    assert "Verdict: :orange-badge[MODIFY]" in texts(at)
    assert "Deterministic fallback fired" not in texts(at)


def test_invalid_message_is_shown(tmp_path, monkeypatch):
    runs = copy_runs(tmp_path / "runs")
    at = make_app(monkeypatch, runs, tmp_path).run()
    label = next(o for o in at.sidebar.selectbox[0].options if "AA1389" in o)
    at.sidebar.selectbox[0].select(label).run()
    assert_clean(at)
    body = texts(at)
    assert "1 invalid message(s) in round 1" in body
    assert any("Extra inputs are not permitted" in c.value for c in at.code)
    assert "Round 2 not run: the fallback fired after round 1 (invalid_message)." in body


def test_approve_appends_human_decision(tmp_path, monkeypatch):
    runs = copy_runs(tmp_path / "runs")
    at = make_app(monkeypatch, runs, tmp_path).run()
    at.sidebar.button[0].click().run()  # showcase
    at.text_input[0].input("Duty manager").run()
    at.text_input[1].input("checked fuel note").run()
    approve = next(b for b in at.button if b.label == "Approve")
    assert not approve.disabled
    approve.click().run()
    assert_clean(at)
    log = runs / "2015-04-24_AA334_N469AA.jsonl"
    last = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
    assert last["event"] == "human_decision" and last["decision"] == "approved"
    assert last["by"] == "Duty manager" and last["note"] == "checked fuel note"
    assert "Human decision: **approved** by Duty manager" in texts(at)


def test_sample_fixture_is_read_only_and_shown_when_no_runs(tmp_path, monkeypatch):
    empty = tmp_path / "empty"
    empty.mkdir()
    before = (SAMPLE / "2015-04-24_AA334_N469AA.jsonl").read_bytes()
    at = make_app(monkeypatch, empty, tmp_path).run()
    assert_clean(at)
    body = texts(at)
    assert "No runs in" in body and "python -m src.cli" in body
    assert "SAMPLE FIXTURE: hand-authored example" in body
    assert next(b for b in at.button if b.label == "Approve").disabled
    assert next(b for b in at.button if b.label == "Reject").disabled
    assert (SAMPLE / "2015-04-24_AA334_N469AA.jsonl").read_bytes() == before

    at.sidebar.checkbox[0].uncheck().run()  # no samples, no runs -> empty state, no crash
    assert_clean(at)
    assert "No run selected" in texts(at)


def test_degrades_on_sparse_and_broken_runs(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    runs.mkdir()
    sparse = {"meta": {"scenario_id": "sparse_run", "agents": "none"},
              "scenario": {"flight": {"AIRLINE": "AA"}},
              "turns": [],
              "recommendation": {"chosen": None, "decided_by": "fallback",
                                 "log_path": str(runs / "sparse_run.jsonl")}}
    (runs / "sparse_run.json").write_text(json.dumps(sparse), encoding="utf-8")
    at = make_app(monkeypatch, runs, tmp_path).run()
    assert_clean(at)
    body = texts(at)
    assert "Solver-only baseline: no negotiation." in body
    assert "No option passes engine and reviewer — escalate to duty manager." in body
    assert "No rule results recorded in this run." in body
    assert "Verdict: :gray-badge[reviewer not run]" in body
    assert next(b for b in at.button if b.label == "Approve").disabled

    (runs / "broken.json").write_text("{oops", encoding="utf-8")
    at = make_app(monkeypatch, runs, tmp_path).run()
    at.sidebar.selectbox[0].select(next(o for o in at.sidebar.selectbox[0].options
                                        if "broken" in o)).run()
    assert not at.exception
    assert any("Could not read" in e.value for e in at.error)


def test_reject_verdict_requires_note(tmp_path, monkeypatch):
    runs = copy_runs(tmp_path / "runs")
    run = json.loads((runs / "failure_showcase.json").read_text(encoding="utf-8"))
    run["reviewer"]["verdict"] = "REJECT"
    (runs / "failure_showcase.json").write_text(json.dumps(run), encoding="utf-8")
    at = make_app(monkeypatch, runs, tmp_path).run()
    at.sidebar.button[1].click().run()
    assert_clean(at)
    assert "Approving it requires a written justification" in texts(at)
    assert next(b for b in at.button if b.label == "Approve").disabled
    at.text_input[1].input("override: fuel figure re-checked with dispatch").run()
    assert not next(b for b in at.button if b.label == "Approve").disabled
