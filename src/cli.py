"""Run one scenario end to end. Owner: Rohan (L).

    python -m src.cli --row-id 0 --agents stub
    python -m src.cli --row-id <N> --agents haiku --out runs/
    python -m src.cli --row-id <N> --agents none          # solver-only baseline
    python -m src.cli --row-id <N> --agents stub --force-deadlock

    python -m src.cli --row-id 0 --agents fixture --pretty  # test-only: hand-built AA334 fixture

Pipeline: build_scenario -> generate_candidates -> check_all -> negotiate -> review -> write
runs/<scenario_id>.json (Recommendation + turns) and runs/<scenario_id>.jsonl (consensus log).

`run_one()` is the single pipeline: the CLI, the UI's runs and eval/run_eval.py all go through it.

Agent modes:
- stub            three StubAgent (deterministic, no API)
- haiku / sonnet  three ClaudeAgent(role, MODEL_IDS[mode]); needs ANTHROPIC_API_KEY
- none            solver-only baseline: no negotiation, fallback_pick decides (reason solver_only)
- fixture         TEST-ONLY dev path: tests/fixtures/aa334_fixture.py data and
                  FixtureAgent(mode="converge"), bypassing src/scenario, src/options, src/rules and
                  src/agents. `--fixture` uses the fixture data with any other agents mode.

Output <out>/<scenario_id>.json:
    meta: {scenario_id, row_index, agents, model, seed, flags, started_at, latency_s, cost_usd,
           tokens_in, tokens_out, git_sha, ...}
    scenario, candidates, rule_results, turns, recommendation   (model_dump of each)
    fallback: {fired, reason, objective, n_eligible, excluded, rejected_candidate_id, ...}
    reviewer: {verdict, notes, re_derived, cited_mismatches, engine_disagreements,
               derived_delay_min, citations_checked, citations_with_value, not_rederived,
               candidate_id, escalated, initial_review}
The .json is overwritten on a re-run; <scenario_id>.jsonl is append-only, so history survives.

Reviewer (src/reviewer/safety.py, docs/plan-rohan.md 3.4): reviews the pick against every
candidate. REJECT -> the deterministic fallback re-picks excluding the rejected candidate and every
candidate the reviewer fails (fallback_fired reason "reviewer_reject"), and the new pick is reviewed
once more. If that is REJECT too, or nothing is eligible, chosen=None: escalate to the duty manager.
"""

import argparse
import functools
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from src.fallback.solver import DEFAULT_WEIGHTS, fallback_explain, fallback_pick
from src.log.consensus_log import ConsensusLog, now_iso, to_jsonable
from src.mediator.protocol import ROLES, negotiate
from src.schemas import Recommendation, Scenario, Tagged

AGENT_MODES = ("stub", "haiku", "sonnet", "none", "fixture")
LIVE_MODES = ("haiku", "sonnet")
SOURCE_TAGS = ("data", "estimated", "assumed", "synthetic")
ESCALATE_NOTE = "no candidate passes engine and reviewer; escalate to duty manager"
REVIEWER_SECTION_KEYS = ("verdict", "notes", "re_derived", "cited_mismatches",
                         "engine_disagreements", "derived_delay_min", "citations_checked",
                         "citations_with_value", "not_rederived", "candidate_id", "escalated",
                         "initial_review")
REPO_ROOT = Path(__file__).resolve().parents[1]


@functools.lru_cache(maxsize=1)
def git_sha() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT,
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def require_api_key(agents_mode: str) -> None:
    if agents_mode in LIVE_MODES and not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            f"--agents {agents_mode} needs ANTHROPIC_API_KEY (set it in .env or the environment)"
        )


def model_for(agents_mode: str) -> str | None:
    if agents_mode in LIVE_MODES:
        try:
            from src.agents.base import MODEL_IDS  # type: ignore[attr-defined]

            return MODEL_IDS[agents_mode]
        except (ImportError, KeyError):
            env = os.environ.get(f"{agents_mode.upper()}_MODEL")
            if env:
                return env
            raise RuntimeError(
                f"no model id for {agents_mode}: src.agents.base.MODEL_IDS is missing and "
                f"{agents_mode.upper()}_MODEL is unset"
            )
    return {"stub": "stub", "fixture": "fixture", "none": None}[agents_mode]


def make_agents(agents_mode: str, model: str | None) -> list:
    if agents_mode == "fixture":
        from tests.fixtures.fixture_agents import FixtureAgent

        return [FixtureAgent(role, mode="converge") for role in ROLES]
    if agents_mode == "stub":
        from src.agents.base import StubAgent

        return [StubAgent(role) for role in ROLES]
    from src.agents.base import ClaudeAgent

    return [ClaudeAgent(role, model) for role in ROLES]


def load_inputs(row_index: int, seed: int, fixture: bool):
    """(scenario, candidates, rule_results) from the real modules or the test fixture."""
    if fixture:
        from tests.fixtures.aa334_fixture import (
            fixture_candidates,
            fixture_rule_results,
            fixture_scenario,
        )

        s = fixture_scenario()
        # Prefix the id so fixture runs never overwrite or masquerade as real runs.
        s = s.model_copy(update={"row_index": row_index,
                                 "scenario_id": f"fixture_r{row_index}_{s.scenario_id}"})
        return s, fixture_candidates(), fixture_rule_results()

    from src.options.menu import generate_candidates
    from src.rules.engine import check_all
    from src.scenario.builder import build_scenario

    try:
        s = build_scenario(row_index, seed=seed)
    except IndexError as e:
        raise ValueError(f"row_index {row_index} is out of range for data/flights.csv") from e
    candidates = generate_candidates(s)
    return s, candidates, check_all(s, candidates)


def source_tag_counts(s: Scenario) -> dict[str, int]:
    counts = dict.fromkeys(SOURCE_TAGS, 0)
    for name in type(s).model_fields:
        value = getattr(s, name)
        if isinstance(value, Tagged):
            counts[value.source] = counts.get(value.source, 0) + 1
    return counts


def sum_usage(agents: list) -> dict:
    usage = {"cost_usd": 0.0, "tokens_in": 0, "tokens_out": 0, "cache_read_tokens": 0,
             "n_agent_calls": 0}
    for agent in agents:
        for call in getattr(agent, "calls", None) or []:
            if not isinstance(call, dict):
                continue
            usage["n_agent_calls"] += 1
            for key in ("cost_usd", "tokens_in", "tokens_out", "cache_read_tokens"):
                usage[key] += call.get(key) or 0
    usage["cost_usd"] = round(usage["cost_usd"], 6)
    return usage


def _reviewer_failed_ids(detail: dict) -> set[str]:
    """Candidates for which the reviewer's own FUEL/DUTY/WAKE re-derivation fails."""
    return {e["candidate_id"] for e in detail.get("re_derived", []) if not e.get("passed")}


def _reject_reasons(detail: dict) -> list[str]:
    """The notes that made a review REJECT (a failed check on the pick, or an explicit REJECT)."""
    return [n for n in detail.get("notes", []) if "-> FAIL" in n or "-> REJECT" in n]


def review_and_resolve(s: Scenario, rec: Recommendation, turns: list, candidates: list,
                       rules: list, weights: dict, emit) -> tuple[Recommendation, dict]:
    """Independent review of the pick; on REJECT the deterministic fallback takes over once.

    docs/plan-rohan.md 3.4 "Reviewer wiring":
    - review with candidates= so engine disagreements are computed on every candidate.
    - APPROVE / MODIFY: the recommendation stands with the reviewer's notes.
    - REJECT: fallback_pick excluding the rejected pick and every candidate the reviewer fails,
      decided_by="fallback", fallback_fired reason "reviewer_reject", then review the new pick once.
      Still REJECT, or nothing eligible: chosen=None, verdict REJECT, escalate to duty manager.
    Returns (final Recommendation, the JSON "reviewer" section). Logs every reviewer_verdict.
    """
    from src.reviewer.safety import review_detail

    def log_review(detail: dict, stage: str, final: bool, candidate_id: str | None) -> None:
        emit("reviewer_verdict", stage=stage, final=final, candidate_id=candidate_id,
             verdict=detail["verdict"], notes=detail["notes"], re_derived=detail["re_derived"],
             cited_mismatches=detail["cited_mismatches"],
             engine_disagreements=detail["engine_disagreements"])

    def cid(r: Recommendation) -> str | None:
        return r.chosen.candidate_id if r.chosen else None

    first = review_detail(s, rec, turns, candidates=candidates)
    initial = None
    if first["verdict"] != "REJECT":
        log_review(first, "review", True, cid(rec))
        final, escalated = first, False
    else:
        log_review(first, "review", False, cid(rec))
        rejected = cid(rec)
        exclude = _reviewer_failed_ids(first) | ({rejected} if rejected else set())
        pick = fallback_pick(candidates, rules, weights, exclude=exclude)
        info = fallback_explain(candidates, rules, weights, exclude=exclude)
        prev_by = rec.decided_by
        prev_reason = (rec.fallback or {}).get("reason") if prev_by == "fallback" else None
        emit("fallback_fired", reason="reviewer_reject", candidate_id=info["chosen"],
             objective=info["objective"], n_eligible=info["n_eligible"], weights=weights,
             excluded=info["excluded"], eligible_ids=info["eligible_ids"],
             unchecked=info["unchecked"], rounds_used=rec.rounds_used,
             rejected_candidate_id=rejected, previous_decided_by=prev_by,
             previous_fallback_reason=prev_reason)
        rec = rec.model_copy(update={
            "chosen": pick,
            "decided_by": "fallback",
            "fallback": {"fired": True, "reason": "reviewer_reject", **info,
                         "weights": dict(weights), "rejected_candidate_id": rejected,
                         "previous_decided_by": prev_by,
                         "previous_fallback_reason": prev_reason},
        })
        handover = (
            f"REVIEWER: REJECT of {rejected or 'no pick'} (decided by {prev_by}"
            f"{', ' + prev_reason if prev_reason else ''}); deterministic fallback re-ran excluding "
            f"{info['excluded']} -> {pick.candidate_id if pick else 'nothing eligible'} "
            f"[docs/plan-rohan.md 3.4: reviewer_reject]."
        )
        initial = first
        notes = [handover] + _reject_reasons(first)
        if pick is not None:
            second = review_detail(s, rec, turns, candidates=candidates)
            notes += second["notes"]
            escalated = second["verdict"] == "REJECT"
            log_review(second, "re_review", not escalated, pick.candidate_id)
            final = second
        else:
            final, escalated = first, True
        if escalated:
            rec = rec.model_copy(update={"chosen": None})
            notes.append(ESCALATE_NOTE)
            final = {**final, "verdict": "REJECT", "notes": notes}
            log_review(final, "escalation", True, None)
        else:
            final = {**final, "notes": notes}

    detail = {**final, "initial_review": initial, "escalated": escalated,
              "candidate_id": cid(rec)}
    rec = Recommendation.model_validate({
        **rec.model_dump(),
        "reviewer_verdict": detail["verdict"],
        "reviewer_notes": detail["notes"],
        "reviewer_detail": detail,
    })
    section = {k: detail.get(k) for k in REVIEWER_SECTION_KEYS}
    return rec, section


def _write_json(path: Path, payload: dict) -> None:
    text = json.dumps(to_jsonable(payload), ensure_ascii=False, indent=2, allow_nan=False,
                      default=str)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text + "\n", encoding="utf-8")
    os.replace(tmp, path)


def run_one(
    row_index: int,
    agents_mode: str,
    out_dir: str | Path = "runs/",
    seed: int = 42,
    force_deadlock: bool = False,
    tamper_rules: bool = False,
    max_rounds: int = 2,
    weights: dict[str, float] | None = None,
    fixture: bool = False,
) -> dict:
    """Run one scenario end to end; write <out_dir>/<scenario_id>.json and append .jsonl.

    Returns the JSON payload that was written (plain dicts). `tamper_rules` is recorded in the
    flags only: the fault injection itself is not built (docs/plan-rohan.md cut #1).
    """
    if agents_mode not in AGENT_MODES:
        raise ValueError(f"unknown agents mode {agents_mode!r}; expected one of {AGENT_MODES}")
    fixture = fixture or agents_mode == "fixture"
    weights = dict(weights or DEFAULT_WEIGHTS)
    started_at, t0 = now_iso(), time.perf_counter()

    require_api_key(agents_mode)  # fail fast, before any data is loaded
    model = model_for(agents_mode)
    s, candidates, rules = load_inputs(row_index, seed, fixture)

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / f"{s.scenario_id}.json"
    log_path = out / f"{s.scenario_id}.jsonl"
    log = ConsensusLog(log_path)
    flags = {"force_deadlock": force_deadlock, "tamper_rules": tamper_rules}

    def emit(event: str, **payload) -> None:
        log.append({"event": event, "scenario_id": s.scenario_id, **payload})

    emit("run_start", row_index=row_index, agents_mode=agents_mode, model=model, seed=seed,
         flags=flags, git_sha=git_sha(), fixture=fixture, max_rounds=max_rounds, weights=weights)
    agents: list = []
    try:
        emit("scenario_built", source_tag_counts=source_tag_counts(s),
             n_downstream_legs=len(s.downstream_legs), n_alternates=len(s.alternates))
        emit("candidates_generated", n=len(candidates),
             candidate_ids=[c.candidate_id for c in candidates])
        for r in rules:
            emit("rule_check", **r.model_dump())

        if agents_mode == "none":
            chosen = fallback_pick(candidates, rules, weights)
            info = fallback_explain(candidates, rules, weights)
            emit("fallback_fired", reason="solver_only", candidate_id=info["chosen"],
                 objective=info["objective"], n_eligible=info["n_eligible"], weights=weights,
                 excluded=info["excluded"], eligible_ids=info["eligible_ids"],
                 unchecked=info["unchecked"], rounds_used=0)
            rec = Recommendation(
                scenario_id=s.scenario_id, chosen=chosen, decided_by="fallback", rounds_used=0,
                rule_results=rules, reviewer_verdict="APPROVE", reviewer_notes=[], log_path="",
                fallback={"fired": True, "reason": "solver_only", **info, "weights": weights},
            )
            turns = []
        else:
            agents = make_agents(agents_mode, model)
            rec, turns = negotiate(s, candidates, agents, rules, max_rounds, log=log,
                                   force_deadlock=force_deadlock, weights=weights)

        rec, reviewer = review_and_resolve(s, rec, turns, candidates, rules, weights, emit)
        rec = rec.model_copy(update={"log_path": str(log_path)})
        emit("recommendation", decided_by=rec.decided_by,
             candidate_id=rec.chosen.candidate_id if rec.chosen else None,
             rounds_used=rec.rounds_used, reviewer_verdict=rec.reviewer_verdict)
        usage = sum_usage(agents)
        latency = round(time.perf_counter() - t0, 4)
        emit("run_end", latency_s=latency, cost_usd=usage["cost_usd"],
             tokens_in=usage["tokens_in"], tokens_out=usage["tokens_out"])
    except BaseException as e:  # incl. KeyboardInterrupt: the log still gets a closing line
        usage = sum_usage(agents)
        emit("run_end", latency_s=round(time.perf_counter() - t0, 4), cost_usd=usage["cost_usd"],
             tokens_in=usage["tokens_in"], tokens_out=usage["tokens_out"], aborted=True,
             error=f"{type(e).__name__}: {e}")
        raise

    fb = rec.fallback or {}
    payload = {
        "meta": {
            "scenario_id": s.scenario_id,
            "row_index": row_index,
            "agents": agents_mode,
            "model": model,
            "seed": seed,
            "flags": flags,
            "started_at": started_at,
            "latency_s": latency,
            "cost_usd": usage["cost_usd"],
            "tokens_in": usage["tokens_in"],
            "tokens_out": usage["tokens_out"],
            "cache_read_tokens": usage["cache_read_tokens"],
            "n_agent_calls": usage["n_agent_calls"],
            "git_sha": git_sha(),
            "fixture": fixture,
            "max_rounds": max_rounds,
            "weights": weights,
            "json_path": str(json_path),
            "log_path": str(log_path),
        },
        "scenario": s.model_dump(),
        "candidates": [c.model_dump() for c in candidates],
        "rule_results": [r.model_dump() for r in rules],
        "turns": [t.model_dump() for t in turns],
        "recommendation": rec.model_dump(),
        "fallback": {
            "fired": bool(fb.get("fired")),
            "reason": fb.get("reason"),
            "objective": fb.get("objective"),
            "n_eligible": fb.get("n_eligible"),
            "excluded": fb.get("excluded", []),
            "chosen": fb.get("chosen"),
            "eligible_ids": fb.get("eligible_ids", []),
            "unchecked": fb.get("unchecked", []),
            "weights": fb.get("weights"),
            "rejected_candidate_id": fb.get("rejected_candidate_id"),
            "previous_decided_by": fb.get("previous_decided_by"),
            "previous_fallback_reason": fb.get("previous_fallback_reason"),
        },
        "reviewer": reviewer,
    }
    payload = to_jsonable(payload)
    _write_json(json_path, payload)
    return payload


# ---------------------------------------------------------------------------------------------
# --pretty: compact terminal table (ASCII only, so it prints on any Windows console)


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    widths = [max(len(str(x)) for x in col) for col in zip(header, *rows)]
    fmt = lambda r: "  ".join(str(x).ljust(w) for x, w in zip(r, widths)).rstrip()  # noqa: E731
    return [fmt(header), fmt(["-" * w for w in widths])] + [fmt(r) for r in rows]


def render_pretty(result: dict) -> str:
    meta, s, rec = result["meta"], result["scenario"], result["recommendation"]
    f = s.get("flight", {})
    chosen_id = (rec.get("chosen") or {}).get("candidate_id")
    rule_ids = list(dict.fromkeys(r["rule_id"] for r in result["rule_results"]))
    passed = {(r["rule_id"], r["candidate_id"]): r["passed"] for r in result["rule_results"]}
    turns = result["turns"]
    final = {m["agent"]: m for m in turns[-1]["messages"]} if turns else {}

    lines = [
        f"Scenario {meta['scenario_id']}  (row {meta['row_index']}, agents={meta['agents']}, "
        f"model={meta['model']}{', FIXTURE' if meta.get('fixture') else ''})",
        f"Flight   {f.get('AIRLINE', '?')}{f.get('FLIGHT_NUMBER', '?')} "
        f"{f.get('ORIGIN_AIRPORT', '?')}->{f.get('DESTINATION_AIRPORT', '?')}  "
        f"arr delay {f.get('ARRIVAL_DELAY', '?')} min (data)",
        "",
    ]
    header = [" ", "candidate", "kind", "delay", "knock"] + rule_ids + list(ROLES)
    rows = []
    for c in result["candidates"]:
        cid = c["candidate_id"]
        cells = ["*" if cid == chosen_id else " ", cid, c["kind"], f"{c['est_delay_min']:g}",
                 f"{c['est_knock_on_min']:g}"]
        for rid in rule_ids:
            p = passed.get((rid, cid))
            cells.append("-" if p is None else ("ok" if p else "FAIL"))
        for role in ROLES:
            m = final.get(role)
            vetoed = {v.get("candidate_id") for v in m["vetoes"]} if m else set()
            cells.append("-" if m is None else
                         ("Y" if cid in m["acceptable"] else ("veto" if cid in vetoed else ".")))
        rows.append(cells)
    lines += _table(header, rows)
    lines.append("")
    if turns:
        lines.append(f"Agent columns = final round {turns[-1]['round']} acceptable "
                     f"(Y accept, veto, . neither, - no valid message)")
    for t in turns:
        acc = "  ".join(f"{m['agent']}={{{','.join(m['acceptable'])}}}" for m in t["messages"])
        lines.append(f"Round {t['round']}: {acc}  | intersection={t['intersection']}")
        for bad in t["invalid_messages"]:
            lines.append(f"  INVALID {bad.get('agent')} ({bad.get('reason')}): {bad.get('error')}")
    fb, rv = result["fallback"], result["reviewer"]
    lines += [
        "",
        f"Decided by : {rec['decided_by']}"
        + (f" (fallback reason: {fb['reason']})" if fb.get("fired") else "")
        + (f", reviewer rejected {fb['rejected_candidate_id']}"
           if fb.get("reason") == "reviewer_reject" and fb.get("rejected_candidate_id") else ""),
        f"Chosen     : {chosen_id or 'NONE - ' + ESCALATE_NOTE}",
        f"Rounds     : {rec['rounds_used']} of max {meta.get('max_rounds')}",
        f"Reviewer   : {rv['verdict']}",
    ]
    lines += [f"  note: {n}" for n in rv["notes"]]
    lines += [
        f"Human      : {rec['human_decision']}",
        f"Cost/time  : ${meta['cost_usd']:.4f}, {meta['latency_s']:.2f} s, "
        f"{meta['n_agent_calls']} agent calls",
        f"Files      : {meta['json_path']}",
        f"             {meta['log_path']}",
    ]
    return "\n".join(lines)


def _not_implemented_where(e: BaseException) -> str:
    tb = e.__traceback__
    last = None
    while tb is not None:
        last = tb
        tb = tb.tb_next
    if last is None:
        return "unknown module"
    code = last.tb_frame.f_code
    try:
        where = Path(code.co_filename).resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        where = code.co_filename
    return f"{where} {code.co_name}()"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run one disruption scenario end to end.")
    parser.add_argument("--row-id", type=int, required=True)
    parser.add_argument("--agents", choices=list(AGENT_MODES), default="stub",
                        help="'fixture' is a test-only path on hand-built AA334 data")
    parser.add_argument("--out", default="runs/")
    parser.add_argument("--force-deadlock", action="store_true")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-rounds", type=int, default=2)
    parser.add_argument("--tamper-rules", action="store_true",
                        help="fault injection (recorded only; not built, plan cut #1)")
    parser.add_argument("--fixture", action="store_true",
                        help="test-only: use the hand-built AA334 fixture data with any --agents")
    parser.add_argument("--pretty", action="store_true", help="print a compact summary table")
    args = parser.parse_args(argv)

    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    try:
        result = run_one(args.row_id, args.agents, out_dir=args.out, seed=args.seed,
                         force_deadlock=args.force_deadlock, tamper_rules=args.tamper_rules,
                         max_rounds=args.max_rounds, fixture=args.fixture)
    except NotImplementedError as e:
        print(f"error: not implemented yet: {_not_implemented_where(e)}. "
              f"Use --agents fixture (test path) until that module is merged.", file=sys.stderr)
        sys.exit(2)
    except (ValueError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        print("aborted (run_end logged with aborted=true)", file=sys.stderr)
        sys.exit(130)

    if args.pretty:
        print(render_pretty(result))
    else:
        rec, fb = result["recommendation"], result["fallback"]
        chosen = (rec.get("chosen") or {}).get("candidate_id")
        print(f"{result['meta']['scenario_id']}: {chosen} decided_by={rec['decided_by']}"
              + (f" ({fb['reason']})" if fb["fired"] else "")
              + f" rounds={rec['rounds_used']} reviewer={rec['reviewer_verdict']}")
        print(f"wrote {result['meta']['json_path']} and {result['meta']['log_path']}")


if __name__ == "__main__":
    main()
