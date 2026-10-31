"""ATC, Pilot and Ground agents. Owner: Reine (T2).

Each agent is a separate call with its own system prompt (src/agents/prompts/) and only its own
domain's data (src/agents/views.py). Agents rank and veto candidates; they never judge legality
or do arithmetic. The rules engine, mediator, reviewer and fallback decide.

- StubAgent: deterministic preference heuristics, no API. Always returns a valid AgentMessage.
  It scores options by per-role kind weights and the menu's own delay estimates; it applies no
  thresholds and no compliance logic (that belongs in src/rules/).
- ClaudeAgent: one Anthropic Messages call per propose(), forced tool use (submit_message) for
  structured output, validated with Pydantic (extra keys forbidden). The model returns only
  acceptable / ranking / vetoes; code sets `agent` and `round`.

Retries, stated precisely so nobody counts them twice:
- The SDK client is built with max_retries=2. Those are TRANSPORT-level retries (429 / 5xx /
  connection errors) handled inside the anthropic SDK; they never see the reply content.
- Content validation gets exactly ONE retry: if the reply fails validation, the model is called
  once more with the validation error quoted back. If that also fails, InvalidMessage is raised
  carrying the raw text and both errors. Nothing is ever repaired or patched up.
- anthropic.APIError (after the SDK's own transport retries) propagates unchanged; the mediator
  logs it as an `exception` invalid message.

Every API attempt is recorded in `ClaudeAgent.calls` (one dict per attempt, additive), so the CLI
and eval harness can sum tokens, cost and latency.
"""

from __future__ import annotations

import json
import os
import time
import warnings
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.agents.views import domain_view, own_citation
from src.schemas import AgentMessage, Candidate, Scenario

Role = Literal["ATC", "PILOT", "GROUND"]
ROLES: tuple[str, ...] = ("ATC", "PILOT", "GROUND")

MODEL_IDS = {
    "haiku": os.getenv("HAIKU_MODEL", "claude-haiku-5-5"),
    "sonnet": os.getenv("SONNET_MODEL", "claude-sonnet-5-5"),
}
# USD per million tokens, from docs/briefing.md section 12; confirm in Console.
# Rohan's eval recomputes cost independently, so a wrong price here is caught.
PRICES = {"haiku": {"in": 0.10, "out": 0.50}, "sonnet": {"in": 2.0, "out": 10.0}}
CACHE_WRITE_MULT = 1.25  # cache writes billed at 1.25x input
CACHE_READ_MULT = 0.10  # cache reads billed at 0.1x input

PROMPT_DIR = Path(__file__).parent / "prompts"
TOOL_NAME = "submit_message"


class InvalidMessage(Exception):
    """An agent reply that failed schema validation. Carries the raw text for the log."""

    def __init__(self, role: Role, raw_text: str, error: str, attempts: list[dict] | None = None):
        super().__init__(f"{role}: {error}")
        self.role = role
        self.raw_text = raw_text
        self.error = error
        self.attempts = attempts or []  # [{attempt, raw_text, error}] for every failed attempt


class Agent:
    def __init__(self, role: Role):
        if role not in ROLES:
            raise ValueError(f"unknown role {role!r}")
        self.role = role

    def propose(
        self,
        s: Scenario,
        candidates: list[Candidate],
        round: int,
        prior: AgentMessage | None,
        others: list[AgentMessage] | None = None,
    ) -> AgentMessage:
        """others = the other two agents' most recent valid AgentMessages, or None."""
        raise NotImplementedError


# ---------------------------------------------------------------------------------------------
# StubAgent
# ---------------------------------------------------------------------------------------------

# Kind -> preference weight per role (higher = preferred). docs/plan-reine.md D1.
KIND_WEIGHTS: dict[str, dict[str, float]] = {
    "ATC": {"slot_shift": 1.0, "ground_hold": 0.9, "gate_swap": 0.7, "tail_swap": 0.6,
            "hold": 0.4, "divert": 0.3},
    "PILOT": {"slot_shift": 1.0, "gate_swap": 0.9, "ground_hold": 0.7, "hold": 0.5,
              "tail_swap": 0.4, "divert": 0.2},
    "GROUND": {"gate_swap": 1.0, "slot_shift": 0.9, "hold": 0.6, "ground_hold": 0.5,
               "tail_swap": 0.4, "divert": 0.1},
}
DEFAULT_KIND_WEIGHT = 0.5
# The one DATA-block field each stub role quotes in its citations.
STUB_CITED_FIELD = {"ATC": "dest_disruption", "PILOT": "fuel_reserve_min",
                    "GROUND": "taxi_congestion"}


class StubAgent(Agent):
    """Deterministic preference heuristics. No randomness, no thresholds, no API."""

    def _scores(self, candidates: list[Candidate]) -> list[tuple[Candidate, float]]:
        weights = KIND_WEIGHTS[self.role]
        if self.role == "GROUND":
            delays = [c.est_delay_min + c.est_knock_on_min for c in candidates]
        else:
            delays = [c.est_delay_min for c in candidates]
        lo, hi = min(delays), max(delays)
        scored = []
        for c, d in zip(candidates, delays):
            norm = (d - lo) / (hi - lo) if hi > lo else 0.0
            w = weights.get(c.kind, DEFAULT_KIND_WEIGHT)
            score = min(1.0, max(0.0, 0.6 * w + 0.4 * (1.0 - norm)))
            scored.append((c, round(score, 3)))
        # Stable sort: ties keep menu order, so the result is deterministic.
        return sorted(scored, key=lambda cs: -cs[1])

    def propose(self, s, candidates, round, prior, others=None):
        if not candidates:
            raise ValueError("StubAgent.propose needs at least one candidate")
        cited = own_citation(s, STUB_CITED_FIELD[self.role])
        scored = self._scores(list(candidates))
        ranked_ids = [c.candidate_id for c, _ in scored]
        ranking = [
            {
                "candidate_id": c.candidate_id,
                "score": sc,
                "rationale": f"{self.role} preference for {c.kind} given "
                             f"est_delay_min={c.est_delay_min:g} on this menu.",
                "cited_fields": [cited],
            }
            for c, sc in scored
        ]

        prior_acc = list(prior.acceptable) if (round >= 2 and prior is not None) else []
        veto_ids: list[str] = []
        if len(ranked_ids) > 1 and ranked_ids[-1] not in prior_acc:
            veto_ids = [ranked_ids[-1]]  # never add a veto on an id accepted in round 1

        acceptable: list[str] = []

        def add(cid: str) -> None:
            if cid not in acceptable and cid not in veto_ids:
                acceptable.append(cid)

        for cid in prior_acc:  # monotonic concession: round-1 set is always kept
            if cid not in acceptable:
                acceptable.append(cid)
        for cid in ranked_ids[:3]:
            add(cid)
        if round >= 2 and prior is not None:
            known = set(ranked_ids)
            for m in others or []:
                if m is None or m.agent == self.role:
                    continue
                for cid in m.acceptable:
                    if cid in known:
                        add(cid)
            if len(ranked_ids) >= 4:
                add(ranked_ids[3])

        vetoes = [
            {"candidate_id": cid, "reason": f"Least preferred option for {self.role} on this menu.",
             "cited_field": cited}
            for cid in veto_ids
        ]
        return AgentMessage(agent=self.role, round=round, acceptable=acceptable,
                            ranking=ranking, vetoes=vetoes)


# ---------------------------------------------------------------------------------------------
# ClaudeAgent
# ---------------------------------------------------------------------------------------------


class _RankingItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_id: str
    score: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(max_length=240)
    cited_fields: list[str]


class _Veto(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_id: str
    reason: str = Field(max_length=240)
    cited_field: str


class _Reply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    acceptable: list[str]
    ranking: list[_RankingItem]
    vetoes: list[_Veto]


TOOL = {
    "name": TOOL_NAME,
    "description": "Submit your negotiation position",
    "input_schema": _Reply.model_json_schema(),
}
TOOL_CHOICE = {"type": "tool", "name": TOOL_NAME}


def load_prompt(role: str) -> str:
    return (PROMPT_DIR / f"{role.lower()}.txt").read_text(encoding="utf-8")


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _int(v: Any) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _block_param(block: Any) -> dict | None:
    """Turn a response content block into a request content block (for the retry turn)."""
    btype = _get(block, "type")
    if btype == "text":
        return {"type": "text", "text": _get(block, "text", "")}
    if btype == "tool_use":
        return {"type": "tool_use", "id": _get(block, "id"), "name": _get(block, "name"),
                "input": _get(block, "input", {})}
    return None


class ClaudeAgent(Agent):
    def __init__(self, role: Role, model: str, client: Any = None, max_tokens: int = 1200,
                 temperature: float = 0):
        super().__init__(role)
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        if client is None:
            import anthropic

            client = anthropic.Anthropic(max_retries=2, timeout=60)
        self.client = client
        self.system_prompt = load_prompt(role)
        self.calls: list[dict] = []

    # -- accounting ----------------------------------------------------------------------------
    def _prices(self) -> dict:
        alias = {v: k for k, v in MODEL_IDS.items()}.get(self.model)
        if alias is None and self.model in PRICES:
            alias = self.model
        if alias is None:
            warnings.warn(f"model {self.model!r} not in MODEL_IDS; costing at haiku prices")
            alias = "haiku"
        return PRICES[alias]

    def _record(self, round: int, attempt: int, resp: Any, latency: float, valid: bool,
                error: str | None) -> None:
        usage = _get(resp, "usage")
        t_in = _int(_get(usage, "input_tokens"))
        t_out = _int(_get(usage, "output_tokens"))
        c_read = _int(_get(usage, "cache_read_input_tokens"))
        c_write = _int(_get(usage, "cache_creation_input_tokens"))
        p = self._prices()
        cost = (t_in * p["in"] + c_write * CACHE_WRITE_MULT * p["in"]
                + c_read * CACHE_READ_MULT * p["in"] + t_out * p["out"]) / 1e6
        self.calls.append({
            "agent": self.role, "model": self.model, "round": round, "attempt": attempt,
            "tokens_in": t_in, "tokens_out": t_out, "cache_read_tokens": c_read,
            "cache_write_tokens": c_write, "cost_usd": cost, "latency_s": round_s(latency),
            "valid": valid, "error": (error or None) and error[:300],
        })

    # -- one attempt -----------------------------------------------------------------------------
    @staticmethod
    def _parse(resp: Any) -> tuple[_Reply | None, str, str | None, Any]:
        """Return (reply or None, raw_text, error or None, tool_use block or None)."""
        content = _get(resp, "content") or []
        tool_use = next((b for b in content if _get(b, "type") == "tool_use"
                         and _get(b, "name", TOOL_NAME) == TOOL_NAME), None)
        texts = [_get(b, "text", "") for b in content if _get(b, "type") == "text"]
        if tool_use is None:
            return None, "\n".join(texts), "no submit_message tool call in reply (prose only)", None
        raw_input = _get(tool_use, "input", {})
        raw_text = json.dumps(raw_input, ensure_ascii=False, default=str)
        if _get(resp, "stop_reason") == "max_tokens":
            return None, raw_text, "reply truncated at max_tokens", tool_use
        try:
            return _Reply.model_validate(raw_input), raw_text, None, tool_use
        except ValidationError as e:
            return None, raw_text, str(e), tool_use

    def propose(self, s, candidates, round, prior, others=None):
        user = domain_view(s, candidates, self.role, round, prior, others)
        messages: list[dict] = [{"role": "user", "content": user}]
        failures: list[dict] = []
        raw_text = ""
        for attempt in (1, 2):
            t0 = time.perf_counter()
            resp = self.client.messages.create(
                model=self.model,
                system=[{"type": "text", "text": self.system_prompt,
                         "cache_control": {"type": "ephemeral"}}],
                messages=messages,
                tools=[TOOL],
                tool_choice=TOOL_CHOICE,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )
            latency = time.perf_counter() - t0
            reply, raw_text, error, tool_use = self._parse(resp)
            self._record(round, attempt, resp, latency, reply is not None, error)
            if reply is not None:
                return AgentMessage(
                    agent=self.role, round=round, acceptable=reply.acceptable,
                    ranking=[i.model_dump() for i in reply.ranking],
                    vetoes=[v.model_dump() for v in reply.vetoes],
                )
            failures.append({"attempt": attempt, "raw_text": raw_text, "error": error})
            if attempt == 1:
                messages = self._retry_messages(messages, resp, tool_use, error)
        summary = "; ".join(f"attempt {f['attempt']}: {f['error']}" for f in failures)
        raise InvalidMessage(self.role, raw_text, summary, attempts=failures)

    @staticmethod
    def _retry_messages(messages: list[dict], resp: Any, tool_use: Any, error: str) -> list[dict]:
        note = (f"Your reply failed validation: {error}. Call {TOOL_NAME} once more with a "
                "payload that satisfies the schema. Do not change your position.")
        assistant = [b for b in (_block_param(b) for b in _get(resp, "content") or []) if b]
        if not assistant:
            # Nothing to echo back: restate the original request with the error appended.
            return [{"role": "user", "content": f"{messages[0]['content']}\n\n{note}"}]
        user_content: list[dict] = []
        if tool_use is not None:
            # The API requires a tool_result for every tool_use in the previous turn.
            user_content.append({"type": "tool_result", "tool_use_id": _get(tool_use, "id"),
                                 "content": note, "is_error": True})
        user_content.append({"type": "text", "text": note})
        return messages + [{"role": "assistant", "content": assistant},
                           {"role": "user", "content": user_content}]


def round_s(x: float) -> float:
    return round(x, 3)
