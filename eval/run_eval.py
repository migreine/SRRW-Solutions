"""Evaluation harness. Owner: Rohan (L).

    python -m eval.run_eval --n 10 --seed 42 --agents haiku --out eval/results/   # cost test first
    python -m eval.run_eval --n 200 --seed 42 --agents haiku --out eval/results/

Compares, per sampled row: what actually happened, solver-only (--agents none), agents + solver.
Writes eval/results/summary.csv and per_scenario.csv. Hard budget cap of $15.
Metrics: consensus rate within the cap, mean rounds, fallback rate, agent top picks failing a rule,
reviewer rejects, cited-value mismatches, schema-invalid rate, estimated delay vs ARRIVAL_DELAY,
latency, cost.

Built on src.cli.run_one (one pipeline for CLI, UI and eval). Flow (docs/plan-rohan.md 3.6):
1. Sample ids from --sample-ids (Waseem's eval/sample_ids.csv). If missing: with --fixture use
   range(n); otherwise build inline with the same recipe (150 WEATHER_DELAY>15 into ORD/ATL/DFW/DEN
   + 50 LATE_AIRCRAFT_DELAY>20, seed 42, shuffled so truncation keeps the mix) and warn.
2. Mode "none" (solver-only baseline) for every row first, sequential, no API.
3. Each agent mode with a ThreadPoolExecutor(--workers). Each run writes its own files under
   <out>/runs/<mode>/, so there is no contention and every row is reproducible with the CLI.
4. One row per (scenario, mode) appended to <out>/per_scenario.csv under a lock, immediately, so a
   crash or guard stop loses nothing; --resume skips (row_index, mode) pairs already done.
5. Cost/time guard on agent modes: stop if cumulative cost > budget (always), or after >= 10 runs
   if projected cost > 1.1 * budget or projected finish > --deadline (today, +08:00).
6. Write summary.csv (long: metric,value,unit,n,definition,note,mode), summary.md and meta.json.
Never runs with force_deadlock or tamper_rules; a run carrying either flag is not counted.

per_scenario.csv columns: row_index, scenario_id, mode, chosen_id, kind, decided_by, rounds_used,
fallback_reason, verdict, n_cited_mismatch, n_invalid, top_pick_fail_ATC, top_pick_fail_PILOT,
top_pick_fail_GROUND, est_delay, est_knock_on, actual_delay, actual_chain, latency_s, cost_usd,
(actual_chain = sum of the downstream legs' arrival delay, key "arrival_delay" from the builder or
"ARRIVAL_DELAY"; read from data/flights.csv by tail and date if the Scenario omits it),
then (additive, needed by the summary) n_agent_calls, n_valid_ATC, n_valid_PILOT, n_valid_GROUND,
consensus_excluded_by_rules, n_engine_disagreements, n_candidates_reviewed,
n_citations_with_value, n_cited_value_mismatch, reviewer_rejected_id, tokens_in, tokens_out,
human_decision, error.

Reviewer columns come from the run JSON's "reviewer" section (src/reviewer/safety.review_detail,
final review after any reviewer_reject fallback): n_engine_disagreements = distinct candidates in
engine_disagreements; n_candidates_reviewed = candidates both re-derived by the reviewer and checked
by the engine on an R-FUEL/R-DUTY/R-WAKE rule; n_citations_with_value = reviewer's
citations_with_value; n_cited_value_mismatch = cited_mismatches that carry a value.

| metric | definition |
|---|---|
| n_rows, n_completed, n_guard_stopped | sample size, finished, stopped by cost/time guard |
| consensus_rate | decided_by=="consensus" / n_completed |
| consensus_round1_rate, consensus_round2_rate | split by rounds_used |
| mean_rounds | mean rounds_used over agent runs |
| fallback_rate_<reason> | fallback count by reason / n_completed |
| agent_top_pick_rule_fail_rate (overall, per role) | valid messages whose ranking[0] fails >= 1 engine rule / valid messages |
| consensus_excluded_by_rules_rate | runs where intersection(acceptable) != {} but intersection(acceptable) & rules_pass == {} |
| reviewer_<verdict>_rate | verdict counts / n_completed |
| reviewer_engine_disagreement_rate | candidates with engine != reviewer pass / candidates checked (all modes) |
| cited_value_mismatch_rate | mismatched citations with a value / citations with a value |
| schema_invalid_rate | invalid messages / total agent calls |
| modelled_delay_agents_mean/median, modelled_delay_solver_mean/median, actual_delay_mean/median, actual_chain_mean | modelled vs data |
| modelled_saving_vs_actual_mean | actual - modelled (agents); an estimate |
| agents_vs_solver_same_pick_rate | chosen ids equal |
| latency_s_mean/p95, cost_usd_mean, cost_usd_total, tokens_total | from run meta |
| human_decision | always pending in eval: the tool never acts |
"""

import argparse
import csv
import json
import math
import statistics
import sys
import threading
import time
import warnings
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timedelta
from pathlib import Path

from src.cli import AGENT_MODES, git_sha, model_for, require_api_key, run_one
from src.log.consensus_log import SGT, now_iso, to_jsonable
from src.reviewer.safety import ENGINE_PREFIX

ROLES = ("ATC", "PILOT", "GROUND")
HUBS = ("ORD", "ATL", "DFW", "DEN")
FALLBACK_REASONS = ("no_consensus", "invalid_message", "monotonic_violation", "forced_deadlock",
                    "reviewer_reject")
VERDICTS = ("APPROVE", "REJECT", "MODIFY")
MODELLED_NOTE = "model estimate; not comparable like-for-like with actual"
GUARD_MIN_RUNS = 10

PER_SCENARIO_COLUMNS = [
    "row_index", "scenario_id", "mode", "chosen_id", "kind", "decided_by", "rounds_used",
    "fallback_reason", "verdict", "n_cited_mismatch", "n_invalid", "top_pick_fail_ATC",
    "top_pick_fail_PILOT", "top_pick_fail_GROUND", "est_delay", "est_knock_on", "actual_delay",
    "actual_chain", "latency_s", "cost_usd",
    # additive
    "n_agent_calls", "n_valid_ATC", "n_valid_PILOT", "n_valid_GROUND",
    "consensus_excluded_by_rules", "n_engine_disagreements", "n_candidates_reviewed",
    "n_citations_with_value", "n_cited_value_mismatch", "reviewer_rejected_id", "tokens_in",
    "tokens_out", "human_decision", "error",
]
SUMMARY_COLUMNS = ["metric", "value", "unit", "n", "definition", "note", "mode"]


# ---------------------------------------------------------------------------------------------
# sample


def build_inline_sample(seed: int = 42, n_weather: int = 150, n_late: int = 50,
                        flights_path: str | Path = "data/flights.csv") -> list[int]:
    """Same recipe as eval/sample.py's spec; temporary until eval/sample_ids.csv exists."""
    import numpy as np
    import pandas as pd

    d = pd.read_csv(flights_path, keep_default_na=True,
                    usecols=["DESTINATION_AIRPORT", "WEATHER_DELAY", "LATE_AIRCRAFT_DELAY"])
    rng = np.random.default_rng(seed)
    weather_pool = d.index[(d.WEATHER_DELAY > 15) & d.DESTINATION_AIRPORT.isin(HUBS)].to_numpy()
    weather = rng.choice(weather_pool, size=min(n_weather, len(weather_pool)), replace=False)
    late_pool = d.index[d.LATE_AIRCRAFT_DELAY > 20].difference(weather).to_numpy()
    late = rng.choice(late_pool, size=min(n_late, len(late_pool)), replace=False)
    ids = np.concatenate([weather, late])
    rng.shuffle(ids)
    return [int(i) for i in ids]


def read_sample_file(path: Path) -> list[int]:
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    if not rows:
        return []
    header = [h.strip() for h in rows[0]]
    if "row_index" in header:
        col, body = header.index("row_index"), rows[1:]
    else:
        col = 0
        body = rows[1:] if not header[0].lstrip("-").isdigit() else rows
    return [int(float(r[col])) for r in body if r and r[col].strip()]


def load_sample_ids(path: str | Path, n: int, seed: int, fixture: bool,
                    out: Path) -> tuple[list[int], str]:
    p = Path(path)
    if p.exists():
        return read_sample_file(p)[:n], str(p)
    if fixture:
        return list(range(n)), "fixture: range(n), no sample file"
    warnings.warn(f"{p} not found; building the sample inline (same recipe, seed {seed})",
                  stacklevel=2)
    ids = build_inline_sample(seed)
    inline = out / "sample_ids_inline.csv"
    with open(inline, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["row_index"])
        w.writerows([i] for i in ids)
    return ids[:n], f"inline recipe (written to {inline})"


# ---------------------------------------------------------------------------------------------
# guard


def parse_deadline(text: str | None, now: datetime | None = None) -> datetime | None:
    """'HH:MM' today in Singapore time (+08:00); 'none' or empty disables it."""
    if text is None or text.strip().lower() in ("", "none", "off"):
        return None
    hh, mm = (int(x) for x in text.strip().split(":"))
    now = now or datetime.now(SGT)
    return now.replace(hour=hh, minute=mm, second=0, microsecond=0)


def guard_check(i_done: int, n_total: int, cum_cost: float, elapsed_s: float, budget: float,
                deadline: datetime | None, now: datetime) -> str | None:
    """Reason to stop, or None. The hard budget cap applies always; projections after 10 runs."""
    if cum_cost > budget:
        return f"budget: cumulative cost ${cum_cost:.4f} > ${budget:.2f}"
    if i_done < GUARD_MIN_RUNS:
        return None
    projected = cum_cost / i_done * n_total
    if projected > 1.1 * budget:
        return f"projected_cost: ${projected:.4f} > 1.1 x ${budget:.2f}"
    if deadline is not None:
        finish = now + timedelta(seconds=elapsed_s / i_done * (n_total - i_done))
        if finish > deadline:
            return f"deadline: projected finish {finish.isoformat(timespec='seconds')} > {deadline.isoformat(timespec='seconds')}"
    return None


# ---------------------------------------------------------------------------------------------
# one row per run


def _num(x):
    if x is None or x == "":
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


# actual_chain (data, partial). The builder's downstream_legs carry the leg's arrival delay as
# "arrival_delay" (src/scenario/builder.py); the test fixture uses the flights.csv column name
# "ARRIVAL_DELAY". Reading only "ARRIVAL_DELAY" made actual_chain 0 on every real row (eval run
# 1f2c0ca). The agents never see either key: src/agents/views.py drops ARRIVAL_DELAY at any depth.
LEG_ARRIVAL_DELAY_KEYS = ("ARRIVAL_DELAY", "arrival_delay")
FLIGHTS_PATH = Path(__file__).resolve().parents[1] / "data" / "flights.csv"


def _leg_arrival_delay(leg: dict) -> float | None:
    for key in LEG_ARRIVAL_DELAY_KEYS:
        if key in leg:
            return _num(leg[key])
    return None


def _hhmm_to_min(v) -> int | None:
    f = _num(v)
    if f is None:
        return None
    v = int(f)
    return 0 if v == 2400 else (v // 100) * 60 + v % 100


_TAIL_DAY_CACHE: dict[str, dict] = {}
_TAIL_DAY_LOCK = threading.Lock()


def _tail_day_index(path: Path) -> dict:
    """(TAIL_NUMBER, YEAR, MONTH, DAY) -> [(row_index, sched_dep_min, ARRIVAL_DELAY)], read once."""
    key = str(Path(path).resolve())
    with _TAIL_DAY_LOCK:
        if key not in _TAIL_DAY_CACHE:
            import pandas as pd

            cols = ["YEAR", "MONTH", "DAY", "TAIL_NUMBER", "SCHEDULED_DEPARTURE", "ARRIVAL_DELAY"]
            d = pd.read_csv(path, usecols=cols, keep_default_na=True)
            index: dict = {}
            for i, r in zip(d.index, d.itertuples(index=False)):
                index.setdefault((r.TAIL_NUMBER, int(r.YEAR), int(r.MONTH), int(r.DAY)), []).append(
                    (int(i), _hhmm_to_min(r.SCHEDULED_DEPARTURE), _num(r.ARRIVAL_DELAY)))
            _TAIL_DAY_CACHE[key] = index
        return _TAIL_DAY_CACHE[key]


def chain_from_flights(row_index: int, flight: dict, path: str | Path | None = None) -> float | None:
    """sum(ARRIVAL_DELAY) over the same tail's later legs that day, read from data/flights.csv.

    Same selection as the builder's downstream_legs: same TAIL_NUMBER and YEAR/MONTH/DAY, a
    different row, scheduled departure strictly later. None if the file or a key is missing.
    flight["SCHEDULED_DEPARTURE"] is in minutes of day (the Scenario normalises hhmm).
    """
    path = Path(path or FLIGHTS_PATH)
    try:
        key = (flight["TAIL_NUMBER"], int(flight["YEAR"]), int(flight["MONTH"]), int(flight["DAY"]))
        dep = _num(flight["SCHEDULED_DEPARTURE"])
    except (KeyError, TypeError, ValueError):
        return None
    if dep is None or not path.exists():
        return None
    legs = [a for i, d, a in _tail_day_index(path).get(key, [])
            if i != row_index and d is not None and d > dep]
    return float(sum(a for a in legs if a is not None))


def actual_chain(scenario: dict, flights_path: str | Path | None = None) -> float | None:
    """sum(ARRIVAL_DELAY) over Scenario.downstream_legs (data, partial; 0 if there are none).

    If any leg does not carry its arrival delay (a Scenario that deliberately omits outcomes),
    the whole sum is read from data/flights.csv by tail and date instead, so it is never a
    silent partial sum. None if that lookup is impossible.
    """
    legs = [leg for leg in scenario.get("downstream_legs") or [] if isinstance(leg, dict)]
    if not legs:
        return 0.0
    values = [_leg_arrival_delay(leg) for leg in legs]
    if all(v is not None for v in values):
        return float(sum(values))
    return chain_from_flights(scenario.get("row_index"), scenario.get("flight") or {}, flights_path)


def _rules_pass(rule_results: list[dict]) -> set[str]:
    by_id: dict[str, list[bool]] = {}
    for r in rule_results:
        by_id.setdefault(r["candidate_id"], []).append(bool(r["passed"]))
    return {cid for cid, ps in by_id.items() if ps and all(ps)}


def _engine_comparable(rule_id: str) -> bool:
    return any(rule_id.upper().startswith(p) for p in ENGINE_PREFIX)


def _candidates_compared(reviewer: dict, rule_results: list[dict]) -> set[str]:
    """Candidates the reviewer re-derived AND the engine checked on a FUEL/DUTY/WAKE rule: the
    denominator of reviewer_engine_disagreement_rate."""
    rederived = {e["candidate_id"] for e in reviewer.get("re_derived") or []}
    engine = {r["candidate_id"] for r in rule_results if _engine_comparable(r["rule_id"])}
    return rederived & engine


def row_from_result(result: dict, mode: str) -> dict:
    meta, rec, s = result["meta"], result["recommendation"], result["scenario"]
    flags = meta.get("flags") or {}
    if flags.get("force_deadlock") or flags.get("tamper_rules"):
        raise ValueError("refusing to count a run with force_deadlock or tamper_rules")
    chosen = rec.get("chosen") or {}
    turns = result["turns"]
    passing = _rules_pass(result["rule_results"])
    failing = {r["candidate_id"] for r in result["rule_results"] if not r["passed"]}

    top_fail = dict.fromkeys(ROLES, 0)
    n_valid = dict.fromkeys(ROLES, 0)
    n_invalid = n_calls = 0
    excluded_by_rules = 0
    for t in turns:
        n_invalid += len(t["invalid_messages"])
        n_calls += len(t["messages"]) + len(t["invalid_messages"])
        if t["intersection"] and not (set(t["intersection"]) & passing):
            excluded_by_rules = 1
        for m in t["messages"]:
            n_valid[m["agent"]] += 1
            if m["ranking"] and m["ranking"][0].get("candidate_id") in failing:
                top_fail[m["agent"]] += 1

    reviewer = result["reviewer"]
    mismatches = reviewer.get("cited_mismatches") or []
    return {
        "row_index": meta["row_index"],
        "scenario_id": meta["scenario_id"],
        "mode": mode,
        "chosen_id": chosen.get("candidate_id"),
        "kind": chosen.get("kind"),
        "decided_by": rec["decided_by"],
        "rounds_used": rec["rounds_used"],
        "fallback_reason": result["fallback"].get("reason") if result["fallback"].get("fired") else None,
        "verdict": rec["reviewer_verdict"],
        "n_cited_mismatch": len(mismatches),
        "n_invalid": n_invalid,
        **{f"top_pick_fail_{r}": top_fail[r] for r in ROLES},
        "est_delay": chosen.get("est_delay_min"),
        "est_knock_on": chosen.get("est_knock_on_min"),
        "actual_delay": _num(s.get("flight", {}).get("ARRIVAL_DELAY")),
        "actual_chain": actual_chain(s),
        "latency_s": meta.get("latency_s"),
        "cost_usd": meta.get("cost_usd"),
        "n_agent_calls": n_calls,
        **{f"n_valid_{r}": n_valid[r] for r in ROLES},
        "consensus_excluded_by_rules": excluded_by_rules,
        "n_engine_disagreements": len({d.get("candidate_id")
                                       for d in reviewer.get("engine_disagreements") or []}),
        "n_candidates_reviewed": len(_candidates_compared(reviewer, result["rule_results"])),
        "n_citations_with_value": reviewer.get("citations_with_value") or 0,
        "n_cited_value_mismatch": sum(1 for m in mismatches if m.get("cited") is not None),
        "reviewer_rejected_id": result["fallback"].get("rejected_candidate_id"),
        "tokens_in": meta.get("tokens_in"),
        "tokens_out": meta.get("tokens_out"),
        "human_decision": rec.get("human_decision", "pending"),
        "error": "",
    }


class RowWriter:
    """Appends rows to per_scenario.csv under a lock; header written once."""

    def __init__(self, path: Path, resume: bool):
        self.path = path
        self.lock = threading.Lock()
        if not resume and path.exists():
            path.unlink()

    def append(self, row: dict) -> None:
        clean = {k: ("" if row.get(k) is None else row.get(k)) for k in PER_SCENARIO_COLUMNS}
        with self.lock:
            new = not self.path.exists() or self.path.stat().st_size == 0
            with open(self.path, "a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=PER_SCENARIO_COLUMNS, extrasaction="ignore")
                if new:
                    w.writeheader()
                w.writerow(clean)


def read_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------------------------------------
# running


def run_mode(mode: str, ids: list[int], *, runs_dir: Path, writer: RowWriter, seed: int,
             fixture: bool, workers: int, budget: float, deadline: datetime | None,
             done: set[tuple[int, str]], guarded: bool) -> dict:
    todo = [i for i in ids if (i, mode) not in done]
    out_dir = runs_dir / mode
    stats = {"mode": mode, "n_todo": len(todo), "n_completed": 0, "n_errors": 0,
             "n_guard_stopped": 0, "guard_stopped": False, "reason": None, "cost_usd": 0.0}

    def job(row_index: int) -> dict:
        try:
            result = run_one(row_index, mode, out_dir=out_dir, seed=seed, force_deadlock=False,
                             tamper_rules=False, fixture=fixture)
            return row_from_result(result, mode)
        except Exception as e:  # recorded per row; the sweep continues
            return {"row_index": row_index, "mode": mode, "error": f"{type(e).__name__}: {e}"}

    it = iter(todo)
    in_flight: set = set()
    n_done, cum_cost, t0 = 0, 0.0, time.monotonic()
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        def submit_next() -> bool:
            row_index = next(it, None)
            if row_index is None:
                return False
            in_flight.add(ex.submit(job, row_index))
            return True

        while len(in_flight) < max(1, workers) and submit_next():
            pass
        while in_flight:
            finished, _ = wait(in_flight, return_when=FIRST_COMPLETED)
            for fut in finished:
                in_flight.discard(fut)
                row = fut.result()
                writer.append(row)
                n_done += 1
                cum_cost += _num(row.get("cost_usd")) or 0.0
                stats["n_errors" if row.get("error") else "n_completed"] += 1
            if guarded and stats["reason"] is None:
                stats["reason"] = guard_check(n_done, len(todo), cum_cost, time.monotonic() - t0,
                                              budget, deadline, datetime.now(SGT))
            if stats["reason"] is None:
                while len(in_flight) < max(1, workers) and submit_next():
                    pass
    stats["n_guard_stopped"] = len(todo) - n_done
    stats["guard_stopped"] = stats["reason"] is not None
    stats["cost_usd"] = round(cum_cost, 6)
    return stats


# ---------------------------------------------------------------------------------------------
# summary


def _rate(num, den):
    return num / den if den else None


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return statistics.fmean(xs) if xs else None


def _median(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def _p95(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    return xs[min(len(xs) - 1, math.ceil(0.95 * len(xs)) - 1)]


def _latest_ok(rows: list[dict]) -> dict[tuple[int, str], dict]:
    """Last successful row per (row_index, mode), so --resume never double counts."""
    out: dict[tuple[int, str], dict] = {}
    for r in rows:
        if not r.get("error"):
            out[(int(float(r["row_index"])), r["mode"])] = r
    return out


def summarize(rows: list[dict], modes: list[str], n_rows: int, stats: dict[str, dict]) -> list[dict]:
    ok = _latest_ok(rows)
    by_mode = {m: [r for (i, mm), r in sorted(ok.items()) if mm == m] for m in modes}
    out: list[dict] = []

    def add(metric, value, unit, n, definition, note="", mode=""):
        out.append({"metric": metric, "value": value, "unit": unit, "n": n,
                    "definition": definition, "note": note, "mode": mode})

    # data: what actually happened, over every distinct completed row
    actual_rows = {i: r for (i, _), r in ok.items()}
    actual = [_num(r["actual_delay"]) for r in actual_rows.values()]
    chain = [_num(r["actual_chain"]) for r in actual_rows.values()]
    add("actual_delay_mean", _mean(actual), "min", len(actual_rows), "mean ARRIVAL_DELAY of the sampled rows", "data", "data")
    add("actual_delay_median", _median(actual), "min", len(actual_rows), "median ARRIVAL_DELAY of the sampled rows", "data", "data")
    add("actual_chain_mean", _mean(chain), "min", len(actual_rows),
        "mean of sum(ARRIVAL_DELAY) over the tail's later legs that day (0 if none)",
        "data, partial: only delayed downstream legs exist in the extract", "data")

    solver = by_mode.get("none", [])
    for mode in modes:
        rs = by_mode[mode]
        n = len(rs)
        st = stats.get(mode, {})
        add("n_rows", n_rows, "rows", n_rows, "sample size", "", mode)
        add("n_completed", n, "rows", n_rows, "runs finished without error", "", mode)
        add("n_guard_stopped", st.get("n_guard_stopped", 0), "rows", n_rows,
            "rows not run because the cost/time guard stopped the sweep", st.get("reason") or "", mode)
        add("n_errors", sum(1 for r in rows if r["mode"] == mode and r.get("error")), "rows", n_rows,
            "runs that raised (recorded in per_scenario.csv 'error')", "", mode)
        for v in VERDICTS:
            add(f"reviewer_{v}_rate", _rate(sum(r["verdict"] == v for r in rs), n), "ratio", n,
                f"final reviewer verdict == {v} / n_completed", "", mode)
        checked = sum(int(r["n_candidates_reviewed"]) for r in rs)
        add("reviewer_engine_disagreement_rate", _rate(sum(int(r["n_engine_disagreements"]) for r in rs), checked),
            "ratio", checked, "candidates where engine and reviewer pass/fail differ / candidates checked",
            "checked = re-derived by the reviewer and checked by the engine on R-FUEL/R-DUTY/R-WAKE", mode)
        add("latency_s_mean", _mean([_num(r["latency_s"]) for r in rs]), "s", n, "mean run_one wall time", "", mode)
        add("latency_s_p95", _p95([_num(r["latency_s"]) for r in rs]), "s", n, "95th percentile run_one wall time", "", mode)
        costs = [_num(r["cost_usd"]) or 0.0 for r in rs]
        add("cost_usd_mean", _mean(costs), "usd", n, "mean agent API cost per scenario", "", mode)
        add("cost_usd_total", sum(costs), "usd", n, "total agent API cost", "", mode)
        add("tokens_total", sum((_num(r["tokens_in"]) or 0) + (_num(r["tokens_out"]) or 0) for r in rs),
            "tokens", n, "input + output tokens across agent calls", "", mode)
        pending = all(r["human_decision"] == "pending" for r in rs)
        add("human_decision", "pending" if pending else "mixed", "", n,
            "human decision on eval recommendations", "eval never acts; a human approves", mode)

        if mode == "none":
            add("fallback_rate_solver_only", _rate(sum(r["fallback_reason"] == "solver_only" for r in rs), n),
                "ratio", n, "solver-only runs decided by fallback_pick / n_completed", "", mode)
            add("fallback_rate_reviewer_reject", _rate(sum(r["fallback_reason"] == "reviewer_reject" for r in rs), n),
                "ratio", n, "solver-only runs whose pick the reviewer rejected, re-picked by fallback_pick / n_completed",
                "", mode)
            add("modelled_delay_solver_mean", _mean([_num(r["est_delay"]) for r in rs]), "min", n,
                "mean est_delay_min of the solver-only pick", MODELLED_NOTE, mode)
            add("modelled_delay_solver_median", _median([_num(r["est_delay"]) for r in rs]), "min", n,
                "median est_delay_min of the solver-only pick", MODELLED_NOTE, mode)
            continue

        cons = [r for r in rs if r["decided_by"] == "consensus"]
        add("consensus_rate", _rate(len(cons), n), "ratio", n, 'decided_by == "consensus" / n_completed', "", mode)
        for k in (1, 2):
            add(f"consensus_round{k}_rate", _rate(sum(int(r["rounds_used"]) == k for r in cons), n), "ratio", n,
                f"consensus in round {k} / n_completed", "", mode)
        add("mean_rounds", _mean([_num(r["rounds_used"]) for r in rs]), "rounds", n, "mean rounds_used over agent runs", "", mode)
        for reason in FALLBACK_REASONS:
            add(f"fallback_rate_{reason}", _rate(sum(r["fallback_reason"] == reason for r in rs), n), "ratio", n,
                f"fallback with reason {reason} / n_completed",
                "forced runs are never counted" if reason == "forced_deadlock" else "", mode)
        total_valid = sum(int(r[f"n_valid_{role}"]) for r in rs for role in ROLES)
        total_fail = sum(int(r[f"top_pick_fail_{role}"]) for r in rs for role in ROLES)
        add("agent_top_pick_rule_fail_rate", _rate(total_fail, total_valid), "ratio", total_valid,
            "valid messages whose ranking[0] candidate fails >= 1 engine rule / valid messages",
            "violations caught by the rules engine", mode)
        for role in ROLES:
            v = sum(int(r[f"n_valid_{role}"]) for r in rs)
            add(f"agent_top_pick_rule_fail_rate_{role}", _rate(sum(int(r[f"top_pick_fail_{role}"]) for r in rs), v),
                "ratio", v, f"{role} valid messages whose ranking[0] fails >= 1 engine rule / {role} valid messages", "", mode)
        add("consensus_excluded_by_rules_rate", _rate(sum(int(r["consensus_excluded_by_rules"]) for r in rs), n),
            "ratio", n, "runs where the acceptable intersection was non-empty but none of it passed every rule / n_completed",
            "", mode)
        cites = sum(int(r["n_citations_with_value"]) for r in rs)
        add("cited_value_mismatch_rate", _rate(sum(int(r["n_cited_value_mismatch"]) for r in rs), cites), "ratio",
            cites, "mismatched path=value citations / path=value citations checked by the reviewer "
            "(every message of each agent that accepts the final pick)", "", mode)
        calls = sum(int(r["n_agent_calls"]) for r in rs)
        add("schema_invalid_rate", _rate(sum(int(r["n_invalid"]) for r in rs), calls), "ratio", calls,
            "invalid messages (schema, unknown_candidate, conflict, monotonic, exception) / agent calls", "", mode)
        delays = [_num(r["est_delay"]) for r in rs]
        add("modelled_delay_agents_mean", _mean(delays), "min", n, "mean est_delay_min of the agents+solver pick", MODELLED_NOTE, mode)
        add("modelled_delay_agents_median", _median(delays), "min", n, "median est_delay_min of the agents+solver pick", MODELLED_NOTE, mode)
        savings = [(_num(r["actual_delay"]) - _num(r["est_delay"])) for r in rs
                   if _num(r["actual_delay"]) is not None and _num(r["est_delay"]) is not None]
        add("modelled_saving_vs_actual_mean", _mean(savings), "min", len(savings),
            "mean of actual ARRIVAL_DELAY - modelled est_delay_min (agents+solver pick)",
            "estimate: " + MODELLED_NOTE, mode)
        if solver:
            solver_pick = {int(float(r["row_index"])): r["chosen_id"] for r in solver}
            pairs = [(r["chosen_id"], solver_pick[int(float(r["row_index"]))]) for r in rs
                     if int(float(r["row_index"])) in solver_pick]
            add("agents_vs_solver_same_pick_rate", _rate(sum(a == b for a, b in pairs), len(pairs)), "ratio",
                len(pairs), "rows where agents+solver and solver-only chose the same candidate / rows run in both",
                "the like-for-like comparison", mode)
    return out


def _fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.6g}"
    return str(v)


def write_summary(out: Path, summary: list[dict], meta: dict) -> None:
    with open(out / "summary.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=SUMMARY_COLUMNS)
        w.writeheader()
        for row in summary:
            w.writerow({k: _fmt(row[k]) for k in SUMMARY_COLUMNS})
    lines = [
        "# Evaluation summary",
        "",
        f"Generated {meta['ended_at']} | git {meta['git_sha']} | modes {', '.join(meta['modes'])} | "
        f"seed {meta['seed']} | sample n={meta['n_rows']} ({meta['sample_source']})"
        + (" | FIXTURE DATA (test only)" if meta["fixture"] else ""),
        "",
        "Modelled delays are model estimates of the delay the recommendation would induce; actual "
        "delays are what happened (data). They are not the same quantity.",
        "",
    ]
    if meta.get("guard_stopped"):
        lines += [f"**Guard stopped the sweep:** {meta['reason']} (n_completed={meta['n_completed']}).", ""]
    lines += ["| mode | metric | value | unit | n | note |", "|---|---|---|---|---|---|"]
    for row in summary:
        lines.append(f"| {row['mode']} | {row['metric']} | {_fmt(row['value'])} | {row['unit']} | "
                     f"{row['n']} | {row['note']} |")
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_meta(out: Path, meta: dict) -> None:
    (out / "meta.json").write_text(json.dumps(to_jsonable(meta), indent=2, ensure_ascii=False) + "\n",
                                   encoding="utf-8")


# ---------------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser(description="Run the evaluation over a seeded sample.")
    parser.add_argument("--n", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--agents", choices=list(AGENT_MODES), default="haiku")
    parser.add_argument("--modes", default=None,
                        help='comma list, default "none,<agents>"; "none" is the solver-only baseline')
    parser.add_argument("--out", default="eval/results/")
    parser.add_argument("--budget-usd", type=float, default=15.0)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--sample-ids", default="eval/sample_ids.csv")
    parser.add_argument("--deadline", default="15:05", help='HH:MM today (+08:00), or "none"')
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--fixture", action="store_true",
                        help="test-only: hand-built AA334 fixture data for every row")
    args = parser.parse_args(argv)

    modes = [m.strip() for m in (args.modes or f"none,{args.agents}").split(",") if m.strip()]
    modes = list(dict.fromkeys(modes))
    bad = [m for m in modes if m not in AGENT_MODES]
    if bad:
        parser.error(f"unknown modes {bad}; expected {AGENT_MODES}")
    modes = (["none"] if "none" in modes else []) + [m for m in modes if m != "none"]
    fixture = args.fixture or "fixture" in modes

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    try:
        for m in modes:
            require_api_key(m)
        models = {m: model_for(m) for m in modes}
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    runs_dir = out / "runs"
    ids, sample_source = load_sample_ids(args.sample_ids, args.n, args.seed, fixture, out)
    deadline = parse_deadline(args.deadline)
    per_path = out / "per_scenario.csv"
    done = set(_latest_ok(read_rows(per_path))) if args.resume else set()
    writer = RowWriter(per_path, resume=args.resume)

    meta = {
        "status": "running", "started_at": now_iso(), "ended_at": None, "modes": modes,
        "agents": args.agents, "models": models, "seed": args.seed, "n": args.n,
        "n_rows": len(ids), "workers": args.workers, "budget_usd": args.budget_usd,
        "deadline": deadline.isoformat() if deadline else None, "sample_source": sample_source,
        "fixture": fixture, "resume": args.resume, "git_sha": git_sha(),
        "force_deadlock": False, "tamper_rules": False,
    }
    _write_meta(out, meta)

    stats: dict[str, dict] = {}
    for mode in modes:
        is_agent = mode != "none"
        stats[mode] = run_mode(mode, ids, runs_dir=runs_dir, writer=writer, seed=args.seed,
                               fixture=fixture, workers=args.workers if is_agent else 1,
                               budget=args.budget_usd, deadline=deadline, done=done,
                               guarded=is_agent)
        print(f"[{mode}] completed={stats[mode]['n_completed']} errors={stats[mode]['n_errors']} "
              f"guard_stopped={stats[mode]['guard_stopped']} cost=${stats[mode]['cost_usd']:.4f}")
        if stats[mode]["guard_stopped"]:
            print(f"[{mode}] guard: {stats[mode]['reason']}")

    rows = read_rows(per_path)
    summary = summarize(rows, modes, len(ids), stats)
    ok = _latest_ok(rows)
    n_completed_by_mode = {m: sum(1 for (_, mm) in ok if mm == m) for m in modes}
    primary = next((m for m in modes if m != "none"), "none")
    stopped = [s for s in stats.values() if s["guard_stopped"]]
    meta.update({
        "status": "guard_stopped" if stopped else "done",
        "ended_at": now_iso(),
        "guard_stopped": bool(stopped),
        "reason": stopped[0]["reason"] if stopped else None,
        "n_completed": n_completed_by_mode[primary],
        "n_completed_by_mode": n_completed_by_mode,
        "cost_usd_total": round(sum(s["cost_usd"] for s in stats.values()), 6),
        "stats_by_mode": stats,
    })
    _write_meta(out, meta)
    write_summary(out, summary, meta)
    print(f"wrote {per_path}, {out / 'summary.csv'}, {out / 'summary.md'}, {out / 'meta.json'}")
    return meta


if __name__ == "__main__":
    main()
