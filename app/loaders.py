"""File IO and pure helpers for the Streamlit UI. Owner: Reine (T2).

No streamlit import here, so everything is unit-testable (tests/test_app_loaders.py).

Contracts respected:
- runs/<scenario_id>.json is READ-ONLY (layout: docs/plan-rohan.md section 3.4).
- runs/<scenario_id>.jsonl is append-only; the only thing the UI writes is a `human_decision`
  event (docs/plan-rohan.md section 3.1), via src.log.consensus_log.ConsensusLog when available.
- Every field may be missing: use safe_get(); never assume a key exists.
"""

from __future__ import annotations

import csv
import json
import math
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUN_DIRS = ("runs", "runs/live")
SAMPLE_DIR = ROOT / "tests" / "fixtures" / "sample_run"
DEFAULT_EVAL_DIR = ROOT / "eval" / "results"
SGT = timezone(timedelta(hours=8))

CLI_HINT = "python -m src.cli --row-id 0 --agents stub --out runs/"
EVAL_HINT = "python -m eval.run_eval --n 200 --seed 42 --agents haiku --out eval/results/"

SOURCE_COLOURS = {
    "data": "#2e7d32",  # green
    "estimated": "#1565c0",  # blue
    "assumed": "#ef6c00",  # amber
    "synthetic": "#6a1b9a",  # purple
}
UNKNOWN_COLOUR = "#616161"  # grey
SOURCE_TAGS = tuple(SOURCE_COLOURS)

# Scenario fields that are plain dicts/lists, with their source by convention
# (docs/briefing.md section 5). Shown in the UI so untagged synthetic data is still labelled.
UNTAGGED_SOURCES = {
    "gates": ("synthetic", "synthetic gate model, seeded"),
    "connections": ("estimated", "same-airline departures after arrival (partial)"),
    "downstream_legs": ("data", "same tail later that day (partial: delayed legs only)"),
    "alternates": ("data", "airports.csv geometry"),
}
ROLES = ("ATC", "PILOT", "GROUND")
VERDICT_COLOURS = {"APPROVE": "green", "MODIFY": "orange", "REJECT": "red"}


# ---------------------------------------------------------------------------------------------
# Generic access
# ---------------------------------------------------------------------------------------------

_PATH_RE = re.compile(r"\[(-?\d+)\]|([^.\[\]]+)")


def safe_get(d: Any, path: str, default: Any = None) -> Any:
    """Read "a.b[0].c" from nested dicts/lists/objects. Missing or None -> default."""
    cur = d
    for idx, key in _PATH_RE.findall(path or ""):
        if cur is None:
            return default
        try:
            if idx:
                cur = cur[int(idx)]
            elif isinstance(cur, dict):
                cur = cur.get(key)
            else:
                cur = getattr(cur, key, None)
        except (IndexError, KeyError, TypeError, ValueError):
            return default
    return default if cur is None else cur


def source_colour(tag: Any) -> str:
    return SOURCE_COLOURS.get(str(tag).lower() if tag is not None else "", UNKNOWN_COLOUR)


def fmt_minutes(v: Any) -> str:
    """Minutes since midnight -> HH:MM (schema convention). Non-numeric -> as-is."""
    try:
        m = int(float(v))
    except (TypeError, ValueError):
        return "—" if v is None else str(v)
    return f"{(m // 60) % 24:02d}:{m % 60:02d}"


def fmt_value(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        if math.isnan(v):
            return "null"
        return f"{v:g}"
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False, default=str)
    return str(v)


# ---------------------------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------------------------


def _abs(p: str | Path) -> Path:
    p = Path(p)
    return p if p.is_absolute() else ROOT / p


def list_runs(dirs=RUN_DIRS) -> list[tuple[str, Path]]:
    """[(label, path)] of run JSON files in dirs, newest first (by mtime)."""
    found: list[tuple[float, str, Path]] = []
    for d in dirs:
        base = _abs(d)
        if not base.is_dir():
            continue
        for p in base.glob("*.json"):
            if p.name in ("meta.json",):
                continue
            try:
                mtime = p.stat().st_mtime
            except OSError:
                continue
            try:
                label = str(p.relative_to(ROOT)).replace("\\", "/")
            except ValueError:
                label = str(p)
            found.append((mtime, label, p))
    found.sort(key=lambda t: (-t[0], t[1]))
    return [(label, p) for _, label, p in found]


def is_sample(path: str | Path | None) -> bool:
    if path is None:
        return False
    try:
        return Path(path).resolve().is_relative_to(SAMPLE_DIR.resolve())
    except (OSError, ValueError):
        return False


def load_run(path: str | Path) -> dict:
    """Parse a run JSON. Never raises: returns {"_load_error": ...} on failure."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        return {"_load_error": f"{type(e).__name__}: {e}"}
    if not isinstance(data, dict):
        return {"_load_error": "run file is not a JSON object"}
    return data


def showcase_preset(runs: list[tuple[str, Path]]) -> Path | None:
    hits = [p for _, p in runs if "aa334" in p.name.lower()]
    clean = [p for p in hits if "deadlock" not in p.name.lower()]
    return (clean or hits or [None])[0]


def failure_preset(runs: list[tuple[str, Path]]) -> Path | None:
    """failure_showcase.json, else aa334_forced_deadlock.json, else first run whose fallback
    fired, else None."""
    by_name = {p.name.lower(): p for _, p in runs}
    for name in ("failure_showcase.json", "aa334_forced_deadlock.json"):
        if name in by_name:
            return by_name[name]
    for _, p in runs:
        if fallback_info(load_run(p))["fired"]:
            return p
    return None


# ---------------------------------------------------------------------------------------------
# Scenario provenance
# ---------------------------------------------------------------------------------------------


def _is_tagged(v: Any) -> bool:
    return isinstance(v, dict) and "value" in v and "source" in v


def tagged_rows(scenario: dict | None) -> list[tuple[str, Any, str, str]]:
    """(field, value, source, note) for every Tagged-shaped dict in the scenario, any depth."""
    rows: list[tuple[str, Any, str, str]] = []

    def walk(obj: Any, prefix: str) -> None:
        if _is_tagged(obj):
            rows.append((prefix, obj.get("value"), str(obj.get("source")), obj.get("note") or ""))
        elif isinstance(obj, dict):
            for k, v in obj.items():
                walk(v, f"{prefix}.{k}" if prefix else str(k))
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                walk(v, f"{prefix}[{i}]")

    if isinstance(scenario, dict):
        walk(scenario, "")
    return rows


def untagged_rows(scenario: dict | None) -> list[tuple[str, Any, str, str]]:
    """Rows for untagged dict/list fields whose source is fixed by convention."""
    rows = []
    for field, (source, note) in UNTAGGED_SOURCES.items():
        v = safe_get(scenario, field)
        if v is None:
            continue
        if isinstance(v, list):
            value = f"{len(v)} item(s)"
        elif isinstance(v, dict):
            value = ", ".join(f"{k}={fmt_value(x)}" for k, x in list(v.items())[:4])
        else:
            value = v
        rows.append((field, value, source, f"{note} (untagged; source by convention)"))
    return rows


def source_counts(scenario: dict | None, include_untagged: bool = True) -> dict[str, int]:
    counts = {t: 0 for t in SOURCE_TAGS}
    rows = tagged_rows(scenario) + (untagged_rows(scenario) if include_untagged else [])
    for _, _, src, _ in rows:
        counts[src] = counts.get(src, 0) + 1
    return counts


def rests_on_line(counts: dict[str, int]) -> str:
    return (f"Rests on {counts.get('synthetic', 0)} synthetic, {counts.get('assumed', 0)} "
            f"assumed and {counts.get('estimated', 0)} estimated values "
            f"({counts.get('data', 0)} from data).")


# ---------------------------------------------------------------------------------------------
# Run interpretation (display only; no decisions are made here)
# ---------------------------------------------------------------------------------------------


def fallback_info(run: dict) -> dict:
    """Merge run["fallback"] and recommendation.fallback. Missing -> not fired."""
    fb = dict(safe_get(run, "recommendation.fallback", {}) or {})
    top = safe_get(run, "fallback", {})
    if isinstance(top, dict):
        fb.update({k: v for k, v in top.items() if v is not None})
    fired = bool(fb.get("fired"))
    if not fired and fb.get("reason"):
        fired = True
    fb["fired"] = fired
    return fb


def reviewer_info(run: dict) -> dict:
    """Reviewer block, or {"verdict": None} when the reviewer did not run.

    recommendation.reviewer_verdict alone is NOT trusted: the mediator writes a placeholder
    APPROVE there before the reviewer runs.
    """
    rev = safe_get(run, "reviewer") or safe_get(run, "recommendation.reviewer_detail")
    if not isinstance(rev, dict) or not rev.get("verdict"):
        return {"verdict": None, "notes": []}
    notes = rev.get("notes") or []
    if any("not implemented" in str(n).lower() for n in notes):
        return {**rev, "verdict": None, "placeholder": True}
    return rev


def verdict_colour(verdict: str | None) -> str:
    return VERDICT_COLOURS.get(str(verdict).upper(), "gray") if verdict else "gray"


def rules_pass_ids(rule_results: list | None) -> set[str]:
    """Candidates with no failing RuleResult (as reported by the rules engine)."""
    ids, failed = set(), set()
    for r in rule_results or []:
        cid = safe_get(r, "candidate_id")
        if cid is None:
            continue
        ids.add(cid)
        if safe_get(r, "passed") is False:
            failed.add(cid)
    return ids - failed


def rule_matrix(rule_results: list | None):
    """pandas DataFrame: rows candidate_id, columns rule_id, cells PASS / FAIL ("" if absent)."""
    import pandas as pd

    cands: list[str] = []
    rules: list[str] = []
    cells: dict[tuple[str, str], str] = {}
    for r in rule_results or []:
        cid, rid = safe_get(r, "candidate_id"), safe_get(r, "rule_id")
        if cid is None or rid is None:
            continue
        if cid not in cands:
            cands.append(cid)
        if rid not in rules:
            rules.append(rid)
        passed = safe_get(r, "passed")
        prev = cells.get((cid, rid))
        cells[(cid, rid)] = "FAIL" if (passed is False or prev == "FAIL") else "PASS"
    return pd.DataFrame([[cells.get((c, r), "") for r in rules] for c in cands],
                        index=pd.Index(cands, name="candidate_id"), columns=rules)


def rule_detail(rule_results: list | None, candidate_id: str) -> list[dict]:
    keys = ("rule_id", "passed", "observed", "threshold", "source", "citation")
    return [{k: safe_get(r, k) for k in keys} for r in rule_results or []
            if safe_get(r, "candidate_id") == candidate_id]


def round_explanation(run: dict) -> str | None:
    """Why fewer than 2 negotiation rounds are shown, or None if both ran."""
    turns = safe_get(run, "turns", []) or []
    agents = safe_get(run, "meta.agents")
    fb = fallback_info(run)
    if not turns:
        if agents == "none" or fb.get("reason") == "solver_only":
            return "Solver-only baseline: no negotiation."
        return "No negotiation rounds recorded in this run."
    if len(turns) >= 2:
        return None
    n = safe_get(turns[-1], "round", len(turns))
    if fb["fired"]:
        reason = fb.get("reason") or "unknown reason"
        return f"Round 2 not run: the fallback fired after round {n} ({reason})."
    if safe_get(run, "recommendation.decided_by") == "consensus":
        return f"Round 2 not needed: consensus in round {n}."
    return f"Only round {n} recorded."


def how_user_knows(run: dict) -> str:
    rev = reviewer_info(run)
    fb = fallback_info(run)
    parts = []
    for h in rev.get("history") or []:
        parts.append(f"reviewer {safe_get(h, 'verdict', '?')} on {safe_get(h, 'candidate_id', '?')}")
    if not parts:
        parts.append(f"reviewer {rev.get('verdict') or 'not run'}")
    if fb["fired"]:
        parts.append(f"fallback fired because {fb.get('reason') or 'unknown'}")
    else:
        parts.append("fallback did not fire")
    parts.append(f"decided by {safe_get(run, 'recommendation.decided_by', 'unknown')}")
    n_inv = sum(len(safe_get(t, "invalid_messages", []) or []) for t in safe_get(run, "turns", []) or [])
    if n_inv:
        parts.append(f"{n_inv} invalid agent message(s) logged with raw text")
    return "How the user knows: " + "; ".join(parts) + "."


def ranking_for(msg: dict) -> list[dict]:
    """Agent ranking sorted by score (desc); malformed entries skipped."""
    items = [r for r in safe_get(msg, "ranking", []) or [] if isinstance(r, dict)]

    def score(r):
        try:
            return float(r.get("score", 0))
        except (TypeError, ValueError):
            return 0.0

    return sorted(items, key=score, reverse=True)


# ---------------------------------------------------------------------------------------------
# Consensus log
# ---------------------------------------------------------------------------------------------


def resolve_log_path(run: dict, run_path: str | Path | None) -> Path | None:
    """recommendation.log_path if it exists, else <run file stem>.jsonl next to the run,
    else the recorded log_path (where a new decision would be written)."""
    recorded = safe_get(run, "recommendation.log_path")
    recorded_p = _abs(recorded) if recorded else None
    if recorded_p is not None and recorded_p.exists():
        return recorded_p
    if run_path is not None:
        sibling = Path(run_path).with_suffix(".jsonl")
        if sibling.exists():
            return sibling
    return recorded_p


def read_log(path: str | Path | None) -> tuple[list[dict], str | None]:
    """(events, error). Malformed lines are skipped and counted in the error string."""
    if path is None:
        return [], "no log path recorded"
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
    except FileNotFoundError:
        return [], None
    except OSError as e:
        return [], f"{type(e).__name__}: {e}"
    events, bad = [], 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            bad += 1
            continue
        if isinstance(ev, dict):
            events.append(ev)
        else:
            bad += 1
    return events, (f"{bad} malformed line(s) skipped" if bad else None)


def human_state(log_path: str | Path | None) -> dict | None:
    """Last human_decision event, None if there is none, {"decision": "unknown"} if the log
    cannot be read."""
    if log_path is None:
        return None
    try:
        with open(log_path, encoding="utf-8") as fh:
            lines = fh.readlines()
    except FileNotFoundError:
        return None
    except OSError as e:
        return {"decision": "unknown", "error": f"{type(e).__name__}: {e}"}
    last = None
    for line in lines:
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(ev, dict) and ev.get("event") == "human_decision":
            last = ev
    return last


def _append_jsonl(path: Path, event: dict) -> None:
    """Same line format as ConsensusLog (ts with +08:00, ensure_ascii=False)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")


def append_human_decision(log_path: str | Path, scenario_id: str, decision: str, by: str,
                          note: str = "") -> dict:
    """Append one human_decision event. Never touches the run .json."""
    if decision not in ("approved", "rejected"):
        raise ValueError(f"decision must be 'approved' or 'rejected', got {decision!r}")
    if not log_path:
        raise ValueError("no log path to write to")
    event = {"ts": datetime.now(SGT).isoformat(timespec="milliseconds"),
             "event": "human_decision", "scenario_id": scenario_id, "decision": decision,
             "by": (by or "").strip() or "anonymous", "note": (note or "").strip()}
    path = _abs(log_path)
    try:
        from src.log.consensus_log import ConsensusLog

        ConsensusLog(path).append(dict(event))
    except (ImportError, NotImplementedError):
        # Rohan's ConsensusLog not merged yet: write the identical line format directly.
        _append_jsonl(path, event)
    return event


# ---------------------------------------------------------------------------------------------
# Evaluation results (docs/plan-rohan.md section 3.6)
# ---------------------------------------------------------------------------------------------

HEADLINE = (
    ("n_completed", "Scenarios completed"),
    ("consensus_rate", "Consensus rate"),
    ("fallback_rate_total", "Fallback rate (all reasons)"),
    ("agent_top_pick_rule_fail_rate", "Agent top picks failing a rule"),
    ("schema_invalid_rate", "Schema-invalid messages"),
    ("reviewer_REJECT_rate", "Reviewer REJECT rate"),
    ("cited_value_mismatch_rate", "Cited-value mismatches"),
)


def eval_dir() -> Path:
    env = os.getenv("EVAL_RESULTS_DIR")
    return _abs(env) if env else DEFAULT_EVAL_DIR


def _num(v: Any) -> Any:
    if v is None:
        return None
    s = str(v).strip()
    if s == "":
        return None
    try:
        f = float(s)
    except ValueError:
        return s
    return int(f) if f.is_integer() and "." not in s and "e" not in s.lower() else f


def load_summary(path: str | Path) -> dict[str, dict] | None:
    """summary.csv (metric,value,unit,n,definition,note) -> {metric: {...}}; None if missing."""
    try:
        with open(path, encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            out = {}
            for row in reader:
                metric = (row.get("metric") or "").strip()
                if not metric:
                    continue
                out[metric] = {
                    "value": _num(row.get("value")),
                    "unit": (row.get("unit") or "").strip(),
                    "n": _num(row.get("n")),
                    "definition": (row.get("definition") or "").strip(),
                    "note": (row.get("note") or "").strip(),
                }
            return out
    except (OSError, csv.Error, UnicodeDecodeError):
        return None


def load_meta(path: str | Path) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}


def metric_value(summary: dict | None, metric: str) -> Any:
    """Value of one metric; fallback_rate_total = sum of numeric fallback_rate_* metrics."""
    if not summary:
        return None
    if metric == "fallback_rate_total":
        vals = [r["value"] for k, r in summary.items()
                if k.startswith("fallback_rate_") and isinstance(r.get("value"), (int, float))]
        return sum(vals) if vals else None
    return safe_get(summary, f"{metric}.value")


def fmt_metric(value: Any, unit: str = "") -> str:
    if value is None:
        return "—"
    if isinstance(value, (int, float)):
        if unit == "fraction" or (unit == "" and isinstance(value, float) and 0 <= value <= 1):
            return f"{value * 100:.1f}%"
        if unit == "USD":
            return f"${value:.4f}"
        text = f"{value:g}"
        return f"{text} {unit}".strip() if unit and unit not in ("rows",) else text
    return str(value)


def headline_metrics(summary: dict | None) -> list[tuple[str, str, Any]]:
    """[(metric, label, value or None)] for the headline cards."""
    return [(m, label, metric_value(summary, m)) for m, label in HEADLINE]


def modelled_vs_actual(summary: dict | None) -> list[tuple[str, dict]]:
    return [(k, r) for k, r in (summary or {}).items()
            if k.startswith("modelled_") or k.startswith("actual_")]
