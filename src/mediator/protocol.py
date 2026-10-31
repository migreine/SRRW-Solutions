"""Monotonic concession protocol, at most 2 rounds. Owner: Rohan (L).

- Round 2's `acceptable` must contain round 1's; a message that shrinks it is invalid and logged.
- Consensus = the intersection of all agents' acceptable sets that also passes every rule;
  pick the candidate with the highest summed score.
- No consensus after round 2 -> deterministic fallback (src/fallback/solver.py).
- Agents never see rule results.

Details (docs/plan-rohan.md section 3.3):
- "Under 3 turns" = max_rounds=2; the fallback is turn 3.
- Every round calls all three agents, in order, with
  propose(s, candidates, round, prior=own previous valid message, others=[the other agents' most
  recent valid messages from earlier rounds]; empty in round 1, so call order never matters). An agent whose propose() does not take `others=` is retried without it
  and an `agent_interface` event is logged.
- A message is invalid if: the agent raised InvalidMessage ("schema"), any other exception
  ("exception"), it is not a well-formed AgentMessage for this role and round ("schema"), it names
  an id that is not on the menu ("unknown_candidate"), an id is both acceptable and vetoed
  ("veto_acceptable_conflict"), or round-2 acceptable is not a superset of the agent's previous
  acceptable ("monotonic_violation"). Invalid messages are logged with raw text and never repaired.
  Any invalid message in a round -> the deterministic fallback decides.
- Consensus tie-break: highest summed clamped score (missing = 0), then lower
  est_delay_min + est_knock_on_min, then candidate_id.
- force_deadlock overwrites each valid message's acceptable set with candidates[i::3] (agent i),
  so the real path runs and the fallback fires with reason "forced_deadlock".
"""

import time
import traceback

from src.agents.base import Agent, InvalidMessage
from src.fallback.solver import DEFAULT_WEIGHTS, fallback_explain, fallback_pick, rules_passing_ids
from src.log.consensus_log import ConsensusLog
from src.schemas import AgentMessage, Candidate, Recommendation, RuleResult, Scenario, Turn

ROLES = ("ATC", "PILOT", "GROUND")
INVALID_REASONS = (
    "schema",
    "unknown_candidate",
    "veto_acceptable_conflict",
    "monotonic_violation",
    "exception",
)


def negotiate(
    s: Scenario,
    candidates: list[Candidate],
    agents: list[Agent],
    rules: list[RuleResult],
    max_rounds: int = 2,
    *,
    log: ConsensusLog | None = None,
    force_deadlock: bool = False,
    weights: dict[str, float] = DEFAULT_WEIGHTS,
) -> tuple[Recommendation, list[Turn]]:
    roles = [getattr(a, "role", None) for a in agents]
    if len(agents) != 3 or sorted(roles) != sorted(ROLES):
        raise ValueError(f"negotiate needs exactly one ATC, PILOT and GROUND agent; got {roles}")
    if max_rounds < 1:
        raise ValueError("max_rounds must be >= 1")

    def emit(event: str, **payload) -> None:
        if log is not None:
            log.append({"event": event, "scenario_id": s.scenario_id, **payload})

    cand_ids = [c.candidate_id for c in candidates]
    by_id = {c.candidate_id: c for c in candidates}
    rules_pass = rules_passing_ids(candidates, rules)
    forced = {a.role: cand_ids[i::3] for i, a in enumerate(agents)}

    own_last: dict[str, AgentMessage] = {}  # each agent's last valid message as it sent it
    seen_last: dict[str, AgentMessage] = {}  # as the mediator used it (after any forced overwrite)
    turns: list[Turn] = []

    for rnd in range(1, max_rounds + 1):
        emit("round_start", round=rnd, max_rounds=max_rounds, force_deadlock=force_deadlock)
        valid: list[AgentMessage] = []
        invalid: list[dict] = []
        # Snapshot at round start: agents in the same round propose independently of each other.
        seen_before = dict(seen_last)

        for agent in agents:
            role = agent.role
            others = [seen_before[a.role] for a in agents
                      if a is not agent and a.role in seen_before]
            msg, failure, metrics = _call_agent(agent, s, candidates, rnd, own_last.get(role),
                                                others, emit)
            if failure is None:
                reason, error = _validate(msg, role, rnd, set(cand_ids), own_last.get(role))
                if reason is not None:
                    failure = {"agent": role, "round": rnd, "reason": reason,
                               "raw_text": msg.model_dump_json() if isinstance(msg, AgentMessage)
                               else repr(msg), "error": error}
            if failure is not None:
                invalid.append(failure)
                emit("message_invalid", **failure)
                continue

            own_last[role] = msg
            used = msg
            if force_deadlock:
                used = msg.model_copy(update={"acceptable": list(forced[role])})
            seen_last[role] = used
            valid.append(used)
            emit(
                "agent_message",
                round=rnd,
                agent=role,
                acceptable=used.acceptable,
                vetoes=used.vetoes,
                top_choice=used.ranking[0]["candidate_id"] if used.ranking else None,
                n_ranked=len(used.ranking),
                ranking=used.ranking,
                forced=force_deadlock,
                original_acceptable=msg.acceptable if force_deadlock else None,
                **metrics,
            )

        if invalid:
            turns.append(Turn(round=rnd, messages=valid, invalid_messages=invalid, intersection=[]))
            first = invalid[0]["reason"]
            reason = "monotonic_violation" if first == "monotonic_violation" else "invalid_message"
            return _fallback(s, candidates, rules, weights, reason, rnd, emit), turns

        common = set.intersection(*(set(m.acceptable) for m in valid))
        acceptable_inter = [cid for cid in cand_ids if cid in common]
        safe = [cid for cid in acceptable_inter if cid in rules_pass]
        turns.append(Turn(round=rnd, messages=valid, invalid_messages=[],
                          intersection=acceptable_inter))
        emit("intersection", round=rnd, acceptable_intersection=acceptable_inter,
             rules_pass_intersection=safe)

        if safe:
            summed = {cid: round(sum(_score(m, cid) for m in valid), 9) for cid in safe}
            best = min(safe, key=lambda cid: (-summed[cid],
                                              by_id[cid].est_delay_min + by_id[cid].est_knock_on_min,
                                              cid))
            emit("consensus", round=rnd, candidate_id=best, summed_score=summed[best],
                 per_agent_scores={m.agent: _score(m, best) for m in valid}, summed_scores=summed)
            rec = Recommendation(
                scenario_id=s.scenario_id,
                chosen=by_id[best],
                decided_by="consensus",
                rounds_used=rnd,
                rule_results=list(rules),
                reviewer_verdict="APPROVE",  # placeholder; the CLI sets it after review()
                reviewer_notes=[],
                log_path="",  # set by the caller
            )
            return rec, turns

    reason = "forced_deadlock" if force_deadlock else "no_consensus"
    return _fallback(s, candidates, rules, weights, reason, max_rounds, emit), turns


def _call_agent(agent, s, candidates, rnd, prior, others, emit):
    """Call propose() once. Returns (message, failure_dict_or_None, metrics). Never retries,
    except the one interface retry without `others=` for agents that predate the kwarg."""
    calls = getattr(agent, "calls", None)
    n_before = len(calls) if isinstance(calls, list) else 0
    t0 = time.perf_counter()
    msg, failure = None, None
    try:
        try:
            msg = agent.propose(s, candidates, rnd, prior, others=others)
        except TypeError as e:
            if "unexpected keyword argument 'others'" not in str(e):
                raise
            emit("agent_interface", round=rnd, agent=agent.role, interface="legacy")
            msg = agent.propose(s, candidates, rnd, prior)
    except InvalidMessage as e:
        failure = {"agent": agent.role, "round": rnd, "reason": "schema",
                   "raw_text": e.raw_text, "error": e.error}
    except Exception as e:  # network, timeout, bugs: captured as text, never swallowed
        failure = {"agent": agent.role, "round": rnd, "reason": "exception",
                   "raw_text": traceback.format_exc(limit=5), "error": f"{type(e).__name__}: {e}"}
    latency = time.perf_counter() - t0

    metrics = {"tokens_in": None, "tokens_out": None, "cost_usd": None, "latency_s": round(latency, 4)}
    calls = getattr(agent, "calls", None)
    if isinstance(calls, list) and len(calls) > n_before and isinstance(calls[-1], dict):
        last = calls[-1]
        for key in ("tokens_in", "tokens_out", "cost_usd", "latency_s"):
            if last.get(key) is not None:
                metrics[key] = last[key]
    return msg, failure, metrics


def _validate(msg, role: str, rnd: int, cand_set: set[str], prev: AgentMessage | None):
    """Return (reason, error) for an invalid message, or (None, None)."""
    if not isinstance(msg, AgentMessage):
        return "schema", f"propose() returned {type(msg).__name__}, not AgentMessage"
    if msg.agent != role:
        return "schema", f"message agent {msg.agent!r} does not match caller role {role!r}"
    if msg.round != rnd:
        return "schema", f"message round {msg.round} does not match mediator round {rnd}"
    for entry in msg.ranking:
        if not isinstance(entry, dict) or not isinstance(entry.get("candidate_id"), str):
            return "schema", f"ranking entry without a string candidate_id: {entry!r}"
        score = entry.get("score")
        if isinstance(score, bool) or not isinstance(score, (int, float)) or score != score:
            return "schema", f"ranking entry for {entry['candidate_id']} has non-numeric score {score!r}"
    for veto in msg.vetoes:
        if not isinstance(veto, dict) or not isinstance(veto.get("candidate_id"), str):
            return "schema", f"veto without a string candidate_id: {veto!r}"

    veto_ids = [v["candidate_id"] for v in msg.vetoes]
    named = list(msg.acceptable) + [e["candidate_id"] for e in msg.ranking] + veto_ids
    unknown = sorted({cid for cid in named if cid not in cand_set})
    if unknown:
        return "unknown_candidate", f"ids not on the candidate menu: {unknown}"
    conflict = sorted(set(msg.acceptable) & set(veto_ids))
    if conflict:
        return "veto_acceptable_conflict", f"ids both acceptable and vetoed: {conflict}"
    if prev is not None:
        dropped = sorted(set(prev.acceptable) - set(msg.acceptable))
        if dropped:
            return ("monotonic_violation",
                    f"round {rnd} acceptable drops {dropped} accepted in round {prev.round}")
    return None, None


def _score(msg: AgentMessage, cid: str) -> float:
    """The agent's score for cid, clamped to [0, 1]; 0 if unranked (first entry wins)."""
    for entry in msg.ranking:
        if entry.get("candidate_id") == cid:
            return max(0.0, min(1.0, float(entry["score"])))
    return 0.0


def _fallback(s, candidates, rules, weights, reason, rounds_used, emit) -> Recommendation:
    chosen = fallback_pick(candidates, rules, weights)
    info = fallback_explain(candidates, rules, weights)
    emit(
        "fallback_fired",
        reason=reason,
        candidate_id=info["chosen"],
        objective=info["objective"],
        n_eligible=info["n_eligible"],
        weights=dict(weights),
        excluded=info["excluded"],
        eligible_ids=info["eligible_ids"],
        unchecked=info["unchecked"],
        rounds_used=rounds_used,
    )
    return Recommendation(
        scenario_id=s.scenario_id,
        chosen=chosen,
        decided_by="fallback",
        rounds_used=rounds_used,
        rule_results=list(rules),
        reviewer_verdict="APPROVE",  # placeholder; the CLI sets it after review()
        reviewer_notes=[],
        log_path="",
        fallback={"fired": True, "reason": reason, **info, "weights": dict(weights)},
    )
