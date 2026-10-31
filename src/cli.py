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
    fallback: {fired, reason, objective, n_eligible, excluded, ...}
    reviewer: {verdict, notes, re_derived, cited_mismatches, engine_disagreements, implemented}
The .json is overwritten on a re-run; <scenario_id>.jsonl is append-only, so history survives.
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
REVIEWER_NOT_IMPLEMENTED = "reviewer not implemented"
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


def run_reviewer(s: Scenario, rec: Recommendation, turns: list) -> dict:
    from src.reviewer.safety import review

    try:
        verdict, notes = review(s, rec, turns)
        implemented = True
    except NotImplementedError:
        verdict, notes, implemented = "APPROVE", [REVIEWER_NOT_IMPLEMENTED], False
    detail = getattr(rec, "reviewer_detail", None) or {}
    return {
        "verdict": verdict,
        "notes": list(notes),
        "re_derived": detail.get("re_derived", []),
        "cited_mismatches": detail.get("cited_mismatches", []),
        "engine_disagreements": detail.get("engine_disagreements", []),
        "implemented": implemented,
    }


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
    flags but is a no-op until the reviewer is wired (docs/plan-rohan.md cut #1).
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

        reviewer = run_reviewer(s, rec, turns)
        rec = Recommendation.model_validate({
            **rec.model_dump(),
            "reviewer_verdict": reviewer["verdict"],
            "reviewer_notes": reviewer["notes"],
            "log_path": str(log_path),
        })
        emit("reviewer_verdict", **reviewer)
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
        + (f" (fallback reason: {fb['reason']})" if fb.get("fired") else ""),
        f"Chosen     : {chosen_id or 'NONE - no candidate passes every rule; escalate to duty manager'}",
        f"Rounds     : {rec['rounds_used']} of max {meta.get('max_rounds')}",
        f"Reviewer   : {rv['verdict']}" + ("" if rv.get("implemented") else " (placeholder)"),
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
                        help="fault injection (recorded only; no-op until the reviewer is wired)")
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
