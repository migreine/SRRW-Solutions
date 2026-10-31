"""Append-only consensus log, one JSON object per line with an ISO timestamp. Owner: Rohan (L).

Records every agent message and validation result, every rule check, every concession and vote,
the reviewer verdict, whether the fallback fired and why, and the human decision.

Every line has `ts` (ISO 8601, +08:00), `event`, `scenario_id`, plus the payload. The file is
opened in append mode and closed on every call, so a killed run still leaves complete lines.

Canonical event vocabulary (the UI and the eval harness read these names):

| event                | payload |
|----------------------|---------|
| run_start            | row_index, agents_mode, model, seed, flags {force_deadlock, tamper_rules}, git_sha |
| scenario_built       | source_tag_counts {data, estimated, assumed, synthetic}, n_downstream_legs, n_alternates |
| candidates_generated | n, candidate_ids |
| rule_check           | one per RuleResult: rule_id, candidate_id, passed, observed, threshold, source, citation |
| round_start          | round |
| agent_message        | round, agent, acceptable, vetoes, top_choice, n_ranked, tokens_in, tokens_out, cost_usd, latency_s |
| message_invalid      | round, agent, reason in {schema, unknown_candidate, veto_acceptable_conflict, monotonic_violation, exception}, raw_text, error |
| intersection         | round, acceptable_intersection, rules_pass_intersection |
| consensus            | round, candidate_id, summed_score, per_agent_scores |
| fallback_fired       | reason in {no_consensus, invalid_message, monotonic_violation, forced_deadlock, solver_only, reviewer_reject}, candidate_id or null, objective, n_eligible, weights, excluded |
| reviewer_verdict     | verdict, notes, re_derived, cited_mismatches, engine_disagreements |
| recommendation       | decided_by, candidate_id, rounds_used, reviewer_verdict |
| human_decision       | decision, by, note (written by the UI) |
| run_end              | latency_s, cost_usd, tokens_in, tokens_out |
| agent_interface      | round, agent, interface="legacy" (agent.propose rejected the `others=` kwarg) |
"""

import json
import math
import threading
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import BaseModel

SGT = timezone(timedelta(hours=8), name="SGT")

EVENTS = frozenset({
    "run_start",
    "scenario_built",
    "candidates_generated",
    "rule_check",
    "round_start",
    "agent_message",
    "message_invalid",
    "intersection",
    "consensus",
    "fallback_fired",
    "reviewer_verdict",
    "recommendation",
    "human_decision",
    "run_end",
    "agent_interface",
})

_WRITE_LOCK = threading.Lock()


def now_iso() -> str:
    """Current time, ISO 8601 with the +08:00 offset."""
    return datetime.now(SGT).isoformat(timespec="microseconds")


def to_jsonable(obj):
    """Recursively convert pydantic models, containers and non-finite floats to plain JSON.

    BaseModel -> model_dump(); NaN / inf -> None; tuples and sets -> lists; numpy scalars -> Python.
    Anything else unknown is left for json.dumps(default=str).
    """
    if isinstance(obj, BaseModel):
        return to_jsonable(obj.model_dump())
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, (set, frozenset)):
        return [to_jsonable(v) for v in sorted(obj, key=str)]
    if isinstance(obj, bool) or obj is None or isinstance(obj, (int, str)):
        return obj
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if type(obj).__module__ == "numpy" and hasattr(obj, "item"):
        return to_jsonable(obj.item())
    return obj


def dumps(obj) -> str:
    """One-line JSON for the log and the run files (no NaN, UTF-8 kept)."""
    return json.dumps(to_jsonable(obj), ensure_ascii=False, default=str, allow_nan=False)


class ConsensusLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def append(self, event: dict) -> None:
        """Append one event as one JSON line. Requires "event" and "scenario_id"."""
        if not isinstance(event, dict):
            raise ValueError("event must be a dict")
        missing = [k for k in ("event", "scenario_id") if k not in event]
        if missing:
            raise ValueError(f"log event missing required keys: {missing}")
        if event["event"] not in EVENTS:
            warnings.warn(f"unknown consensus-log event name: {event['event']!r}", stacklevel=2)
        record = {"ts": event.get("ts") or now_iso(), **event}
        line = dumps(record)
        with _WRITE_LOCK:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8", newline="\n") as f:
                f.write(line + "\n")

    def read_all(self) -> list[dict]:
        """Every event in file order (for tests and the UI). Empty if the file does not exist."""
        if not self.path.exists():
            return []
        with open(self.path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
