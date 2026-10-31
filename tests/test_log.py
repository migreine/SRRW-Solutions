"""src/log/consensus_log.py: append-only JSONL, timestamps, NaN handling, no truncation."""

import json
from datetime import datetime

import pytest

from src.log.consensus_log import EVENTS, ConsensusLog
from src.schemas import Tagged
from tests.fixtures.paths import out_dir  # noqa: F401  (pytest fixture)


def test_two_appends_parse_in_order_with_tz(out_dir):
    path = out_dir / "nested" / "s1.jsonl"  # parent created on first append
    log = ConsensusLog(path)
    log.append({"event": "run_start", "scenario_id": "s1", "row_index": 0})
    log.append({"event": "run_end", "scenario_id": "s1", "latency_s": 1.5})

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    events = [json.loads(line) for line in lines]
    assert [e["event"] for e in events] == ["run_start", "run_end"]
    stamps = [datetime.fromisoformat(e["ts"]) for e in events]
    assert all(t.utcoffset() is not None and t.utcoffset().total_seconds() == 8 * 3600
               for t in stamps)
    assert events[0]["ts"].endswith("+08:00")
    assert stamps[0] <= stamps[1]
    assert log.read_all() == events


def test_tagged_and_nan_round_trip_as_null(out_dir):
    log = ConsensusLog(out_dir / "s2.jsonl")
    tag = Tagged(value=78, source="estimated", note="burn model")
    log.append({"event": "scenario_built", "scenario_id": "s2", "fuel": tag,
                "nested": {"x": float("nan"), "y": [float("inf"), 1.0]}, "ids": {"B", "A"}})
    raw = (out_dir / "s2.jsonl").read_text(encoding="utf-8")
    assert "NaN" not in raw and "Infinity" not in raw
    (event,) = ConsensusLog(out_dir / "s2.jsonl").read_all()
    assert event["fuel"] == {"value": 78, "source": "estimated", "note": "burn model"}
    assert event["nested"] == {"x": None, "y": [None, 1.0]}
    assert event["ids"] == ["A", "B"]


def test_append_after_reinstantiation_does_not_truncate(out_dir):
    path = out_dir / "s3.jsonl"
    ConsensusLog(path).append({"event": "run_start", "scenario_id": "s3"})
    ConsensusLog(path).append({"event": "run_start", "scenario_id": "s3"})  # "restart"
    assert len(ConsensusLog(path).read_all()) == 2


def test_missing_required_keys_raise(out_dir):
    log = ConsensusLog(out_dir / "s4.jsonl")
    with pytest.raises(ValueError):
        log.append({"event": "run_start"})
    with pytest.raises(ValueError):
        log.append({"scenario_id": "s4"})
    assert not (out_dir / "s4.jsonl").exists()


def test_unknown_event_warns_but_writes(out_dir):
    log = ConsensusLog(out_dir / "s5.jsonl")
    with pytest.warns(UserWarning):
        log.append({"event": "not_an_event", "scenario_id": "s5"})
    assert len(log.read_all()) == 1
    assert "fallback_fired" in EVENTS and "human_decision" in EVENTS


def test_unicode_kept_and_ts_preserved(out_dir):
    log = ConsensusLog(out_dir / "s6.jsonl")
    log.append({"event": "human_decision", "scenario_id": "s6", "ts": "2026-10-31T14:00:00+08:00",
                "note": "approved → OCC"})
    assert "→" in (out_dir / "s6.jsonl").read_text(encoding="utf-8")
    assert log.read_all()[0]["ts"] == "2026-10-31T14:00:00+08:00"
