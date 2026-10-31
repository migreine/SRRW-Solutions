"""Per-role domain views: the user message each agent receives. Owner: Reine (T2).

This is the single place that enforces "each agent sees only its own domain's data". The system
prompts (src/agents/prompts/) are static; all scenario data reaches an agent through
domain_view(). A role sees only the fields on its allow-list below. Every value is printed as a
"path=value (source)" line whose path resolves against `Scenario` (dotted keys, [i] indexes,
`Tagged` -> .value), so the reviewer can cross-check any value an agent quotes.

What never reaches any agent:
- rule results (the agents' picks are measured against the rules engine, so they must not see it);
- the outcome fields ARRIVAL_DELAY / ARRIVAL_TIME / WHEELS_ON / TAXI_IN (what the evaluation
  compares against), at the top level or inside downstream legs;
- another agent's cited_field values (round 2 shows other agents' positions only).

Nothing here computes, checks or compares anything; it only selects and prints.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any, Iterable

from src.schemas import AgentMessage, Candidate, Scenario, Tagged

LIST_CAP = 4  # list items shown before "...(n more)"
DICT_CAP = 15  # lines shown per dict before "...(n more)"

# Outcome fields: never shown to any agent, at any depth.
OUTCOME_KEYS = frozenset({"ARRIVAL_DELAY", "ARRIVAL_TIME", "WHEELS_ON", "TAXI_IN"})
# Later legs have not flown yet at decision time: every actual-outcome field on them is hidden.
LEG_OUTCOME_KEYS = OUTCOME_KEYS | frozenset({
    "DEPARTURE_DELAY", "DEPARTURE_TIME", "WHEELS_OFF", "TAXI_OUT", "ELAPSED_TIME", "AIR_TIME",
    "AIR_SYSTEM_DELAY", "SECURITY_DELAY", "AIRLINE_DELAY", "LATE_AIRCRAFT_DELAY", "WEATHER_DELAY",
})

# Keys shown for each downstream leg (when the leg dict uses flights.csv column names).
DOWNSTREAM_KEYS = (
    "AIRLINE",
    "FLIGHT_NUMBER",
    "ORIGIN_AIRPORT",
    "DESTINATION_AIRPORT",
    "SCHEDULED_DEPARTURE",
    "SCHEDULED_ARRIVAL",
)

# Default source tag for Scenario fields that are plain dicts/lists rather than Tagged values
# (docs/briefing.md section 5).
FIELD_SOURCES = {
    "flight": "data",
    "downstream_legs": "data",
    "alternates": "data",
    "gates": "synthetic",
    "connections": "estimated",
}

# Role allow-lists (docs/plan-reine.md D1 / section 3.1). ONLY these appear in the DATA block.
ROLE_FLIGHT_FIELDS: dict[str, tuple[str, ...]] = {
    "ATC": (
        "AIRLINE", "FLIGHT_NUMBER", "TAIL_NUMBER", "ORIGIN_AIRPORT", "DESTINATION_AIRPORT",
        "SCHEDULED_DEPARTURE", "SCHEDULED_ARRIVAL", "DEPARTURE_DELAY", "TAXI_OUT",
        "WEATHER_DELAY",
    ),
    "PILOT": (
        "AIRLINE", "FLIGHT_NUMBER", "ORIGIN_AIRPORT", "DESTINATION_AIRPORT", "SCHEDULED_ARRIVAL",
        "DEPARTURE_DELAY", "DISTANCE", "SCHEDULED_TIME", "WEATHER_DELAY",
    ),
    "GROUND": (
        "AIRLINE", "FLIGHT_NUMBER", "TAIL_NUMBER", "DESTINATION_AIRPORT", "SCHEDULED_ARRIVAL",
        "DEPARTURE_DELAY", "LATE_AIRCRAFT_DELAY",
    ),
}
ROLE_SCENARIO_FIELDS: dict[str, tuple[str, ...]] = {
    "ATC": ("dest_disruption", "taxi_congestion", "nominal_aar", "wake_category"),
    "PILOT": ("fuel_reserve_min", "crew_duty_remaining_min", "wake_category", "alternates",
              "connections"),
    "GROUND": ("gates", "downstream_legs", "taxi_congestion", "connections.count"),
}
# Candidate keys each role sees.
ROLE_CANDIDATE_KEYS: dict[str, tuple[str, ...]] = {
    "ATC": ("candidate_id", "kind", "params", "est_delay_min"),
    "PILOT": ("candidate_id", "kind", "params", "est_delay_min", "est_knock_on_min"),
    "GROUND": ("candidate_id", "kind", "params", "est_delay_min", "est_knock_on_min"),
}

ROLES = tuple(ROLE_FLIGHT_FIELDS)

# A "path=value" token as an agent would cite it, e.g. fuel_reserve_min=78 or
# alternates[0].distance_nm=190. Used to strip other domains' values from round-2 reasons.
_CITATION_RE = re.compile(r"[A-Za-z_][\w.\[\]]*\s*=\s*[^\s,;)]+")


def fmt_value(v: Any) -> str:
    """Print a value the way an agent should quote it. None/NaN -> null; 78.0 -> 78."""
    if isinstance(v, Tagged):
        v = v.value
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return "null"
        if v.is_integer():
            return str(int(v))
        return f"{v:.2f}".rstrip("0").rstrip(".")
    if hasattr(v, "item") and not isinstance(v, (str, bytes)):  # numpy scalar
        try:
            return fmt_value(v.item())
        except (TypeError, ValueError):
            pass
    return str(v)


def _is_tagged_dict(d: Any) -> bool:
    return isinstance(d, dict) and "value" in d and "source" in d


def flatten(obj: Any, prefix: str, source: str) -> list[str]:
    """Return "path=value (source)" lines for obj, with lists and dicts capped."""
    if isinstance(obj, Tagged):
        return [f"{prefix}={fmt_value(obj.value)} ({obj.source})"]
    if _is_tagged_dict(obj):
        return [f"{prefix}={fmt_value(obj['value'])} ({obj['source']})"]
    if isinstance(obj, dict):
        lines: list[str] = []
        for k in obj:
            if str(k).upper() in OUTCOME_KEYS:
                continue
            lines.extend(flatten(obj[k], f"{prefix}.{k}" if prefix else str(k), source))
        if len(lines) > DICT_CAP:
            lines = lines[:DICT_CAP] + [f"{prefix}...({len(lines) - DICT_CAP} more)"]
        return lines
    if isinstance(obj, (list, tuple)):
        if not obj:
            return [f"{prefix}=[] ({source})"]
        lines = []
        for i, item in enumerate(obj[:LIST_CAP]):
            lines.extend(flatten(item, f"{prefix}[{i}]", source))
        if len(obj) > LIST_CAP:
            lines.append(f"{prefix}...({len(obj) - LIST_CAP} more)")
        return lines
    return [f"{prefix}={fmt_value(obj)} ({source})"]


def _downstream_view(legs: list) -> list:
    """Keep only scheduled fields of each downstream leg (their actual delays are outcomes)."""
    out = []
    for leg in legs or []:
        if not isinstance(leg, dict):
            out.append(leg)
        elif any(k in leg for k in DOWNSTREAM_KEYS):
            out.append({k: leg[k] for k in DOWNSTREAM_KEYS if k in leg})
        else:
            out.append({k: v for k, v in leg.items() if str(k).upper() not in LEG_OUTCOME_KEYS})
    return out


def data_lines(s: Scenario, role: str) -> list[str]:
    """The DATA block for one role, as a list of "path=value (source)" lines."""
    if role not in ROLE_FLIGHT_FIELDS:
        raise ValueError(f"unknown role {role!r}")
    lines: list[str] = []
    flight = s.flight or {}
    for key in ROLE_FLIGHT_FIELDS[role]:
        if key in flight:
            lines.extend(flatten(flight[key], f"flight.{key}", "data"))
    for field in ROLE_SCENARIO_FIELDS[role]:
        if field == "connections.count":
            lines.append(f"connections.count={len(s.connections or [])} (estimated)")
            continue
        value = getattr(s, field, None)
        if value is None:
            continue
        if field == "downstream_legs":
            value = _downstream_view(value)
        lines.extend(flatten(value, field, FIELD_SOURCES.get(field, "data")))
    return lines


def own_citation(s: Scenario, path: str) -> str:
    """'path=value' for a top-level Scenario field, formatted exactly as in the DATA block."""
    return f"{path}={fmt_value(getattr(s, path))}"


def candidate_lines(candidates: Iterable[Candidate], role: str) -> list[str]:
    keys = ROLE_CANDIDATE_KEYS[role]
    out = []
    for c in candidates:
        d = c.model_dump()
        out.append(json.dumps({k: d[k] for k in keys}, ensure_ascii=False, default=str))
    return out


def redact(text: str) -> str:
    """Remove "path=value" tokens from another agent's free text (keeps domains separate)."""
    return _CITATION_RE.sub("[value withheld]", text or "")


def _top_ids(msg: AgentMessage, n: int = 3) -> list[str]:
    return [str(r.get("candidate_id")) for r in (msg.ranking or [])[:n]]


def round2_lines(role: str, prior: AgentMessage | None,
                 others: list[AgentMessage] | None) -> list[str]:
    lines = ["YOUR ROUND-1 MESSAGE"]
    if prior is None:
        lines.append("none (treat this as a first position)")
    else:
        lines.append(f"acceptable: {json.dumps(list(prior.acceptable))}")
        vetoes = [str(v.get("candidate_id")) for v in prior.vetoes or []]
        lines.append(f"vetoes: {json.dumps(vetoes)}")
        lines.append(f"top-3 ranking: {json.dumps(_top_ids(prior))}")
    lines.append("")
    lines.append("OTHER AGENTS' ROUND-1 POSITIONS")
    shown = [m for m in (others or []) if m is not None and m.agent != role]
    if not shown:
        lines.append("not available")
    for m in shown:
        lines.append(f"{m.agent}: acceptable {json.dumps(list(m.acceptable))}")
        for v in m.vetoes or []:  # cited_field deliberately dropped
            reason = redact(str(v.get("reason", "")))
            lines.append(f"{m.agent} veto {v.get('candidate_id')}: {reason}")
    return lines


def domain_view(s: Scenario, candidates: list[Candidate], role: str, round: int,
                prior: AgentMessage | None = None,
                others: list[AgentMessage] | None = None) -> str:
    """Build the user message for one agent call."""
    parts = [f"ROLE: {role}", f"ROUND: {round} of at most 2", f"SCENARIO: {s.scenario_id}", ""]
    parts.append("DATA")
    parts.extend(data_lines(s, role))
    parts.append("")
    parts.append("CANDIDATES")
    parts.extend(candidate_lines(candidates, role))
    if round >= 2:
        parts.append("")
        parts.extend(round2_lines(role, prior, others))
    parts.append("")
    parts.append("Reply by calling submit_message exactly once.")
    return "\n".join(parts)
