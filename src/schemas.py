"""Shared types for every module. Owner: Rohan (L).

This file is the contract between modules: add fields freely, never rename or remove one.
"""

from typing import Literal

from pydantic import BaseModel

SourceTag = Literal["data", "estimated", "assumed", "synthetic"]


class Tagged(BaseModel):
    """A value with its provenance, shown in the log and the UI."""

    value: float | str | int
    source: SourceTag
    note: str = ""  # e.g. "FAA registry miss -> airline fleet default"


class Scenario(BaseModel):
    scenario_id: str  # f"{date}_{airline}{flight}_{tail}"
    row_index: int
    flight: dict  # raw flights.csv row, times normalised to minutes since midnight
    dest_disruption: Tagged  # delayed arrivals in the destination hour (data, proxy)
    taxi_congestion: Tagged  # TAXI_IN vs airport median (data, proxy)
    downstream_legs: list[dict]  # same tail later that day (data, partial)
    alternates: list[dict]  # {iata, distance_nm} from airports.csv
    wake_category: Tagged  # "H" | "L" | "S", assumed unless looked up
    fuel_reserve_min: Tagged  # estimated
    crew_duty_remaining_min: Tagged  # synthetic
    gates: dict  # synthetic gate model, seeded
    connections: list[dict]  # estimated
    nominal_aar: Tagged  # assumed


class Candidate(BaseModel):
    candidate_id: str  # "SLOT+15", "HOLD30", "DIVERT_AUS", "GATE_B12", ...
    kind: Literal["slot_shift", "hold", "divert", "gate_swap", "ground_hold", "tail_swap"]
    params: dict
    est_delay_min: float  # deterministic estimate
    est_knock_on_min: float


class RuleResult(BaseModel):
    rule_id: str  # "R-FUEL-01"
    candidate_id: str
    passed: bool
    observed: float | str
    threshold: float | str
    source: SourceTag
    citation: str  # "14 CFR 121.639" or "assumed: airline turnaround"


class AgentMessage(BaseModel):
    """What every agent call must return."""

    agent: Literal["ATC", "PILOT", "GROUND"]
    round: int
    acceptable: list[str]  # candidate_ids this agent can live with
    ranking: list[dict]  # [{candidate_id, score: 0-1, rationale, cited_fields: [str]}]
    vetoes: list[dict]  # [{candidate_id, reason, cited_field}]


class Turn(BaseModel):
    round: int
    messages: list[AgentMessage]
    invalid_messages: list[dict]  # raw text + validation error, never repaired
    intersection: list[str]


class Recommendation(BaseModel):
    scenario_id: str
    chosen: Candidate | None
    decided_by: Literal["consensus", "fallback"]
    rounds_used: int
    rule_results: list[RuleResult]
    reviewer_verdict: Literal["APPROVE", "REJECT", "MODIFY"]
    reviewer_notes: list[str]
    human_decision: Literal["pending", "approved", "rejected"] = "pending"
    log_path: str
    # Additive: set when the deterministic fallback decided. {"fired": True, "reason", "chosen",
    # "objective", "n_eligible", "eligible_ids", "excluded", "unchecked", "weights"}; None on consensus.
    fallback: dict | None = None
    reviewer_detail: dict | None = None
