"""Scripted agents that drive the mediator down every path. Owner: Rohan (L).

FixtureAgent subclasses src.agents.base.Agent and accepts the additive `others=None` kwarg.
Each mode reproduces one row of the table in docs/plan-rohan.md section 2:

| mode             | round 1                                   | round 2                 | outcome                     |
|------------------|-------------------------------------------|-------------------------|-----------------------------|
| converge         | pairwise overlap, empty 3-way intersection| each adds one id        | consensus SLOT+30, round 2  |
| converge_r1      | all three include SLOT+15                 | n/a                     | consensus SLOT+15, round 1  |
| unsafe_consensus | all three accept only HOLD40              | same (superset)         | fallback no_consensus       |
| deadlock         | disjoint                                  | still disjoint          | fallback no_consensus       |
| shrink           | as converge                               | PILOT drops HOLD20      | fallback monotonic_violation|
| invalid          | PILOT raises InvalidMessage               | -                       | fallback invalid_message    |
| unknown_id       | GROUND acceptable includes "BOGUS"        | -                       | fallback invalid_message    |
| veto_conflict    | PILOT accepts and vetoes HOLD20           | -                       | fallback invalid_message    |

No arithmetic or legality here: the agent only replays scripted sets.
"""

from src.agents.base import Agent, InvalidMessage
from src.schemas import AgentMessage, Candidate, Scenario

MODES = (
    "converge",
    "converge_r1",
    "unsafe_consensus",
    "deadlock",
    "shrink",
    "invalid",
    "unknown_id",
    "veto_conflict",
)

_R1_CONVERGE = {
    "ATC": ["SLOT+15", "SLOT+30"],
    "PILOT": ["SLOT+30", "HOLD20"],
    "GROUND": ["HOLD20", "GATE_B12"],
}
_R2_CONVERGE = {
    "ATC": ["SLOT+15", "SLOT+30", "GATE_B12"],
    "PILOT": ["SLOT+30", "HOLD20", "SLOT+15"],
    "GROUND": ["HOLD20", "GATE_B12", "SLOT+30"],
}
_CONVERGE_R1 = {
    "ATC": ["SLOT+15", "SLOT+30"],
    "PILOT": ["SLOT+15", "HOLD20"],
    "GROUND": ["SLOT+15", "GATE_B12"],
}
_UNSAFE = {"ATC": ["HOLD40"], "PILOT": ["HOLD40"], "GROUND": ["HOLD40"]}
_R1_DEADLOCK = {"ATC": ["SLOT+15"], "PILOT": ["HOLD20"], "GROUND": ["GATE_B12"]}
_R2_DEADLOCK = {
    "ATC": ["SLOT+15", "SLOT-15"],
    "PILOT": ["HOLD20", "GROUND_HOLD_MFE"],
    "GROUND": ["GATE_B12", "SLOT+30"],
}
_R2_SHRINK = {**_R2_CONVERGE, "PILOT": ["SLOT+30", "SLOT+15"]}  # HOLD20 dropped

# acceptable sets by mode -> round -> role
_SCRIPTS: dict[str, dict[int, dict[str, list[str]]]] = {
    "converge": {1: _R1_CONVERGE, 2: _R2_CONVERGE},
    "converge_r1": {1: _CONVERGE_R1, 2: _CONVERGE_R1},
    "unsafe_consensus": {1: _UNSAFE, 2: _UNSAFE},
    "deadlock": {1: _R1_DEADLOCK, 2: _R2_DEADLOCK},
    "shrink": {1: _R1_CONVERGE, 2: _R2_SHRINK},
    "invalid": {1: _R1_CONVERGE, 2: _R2_CONVERGE},
    "unknown_id": {1: {**_R1_CONVERGE, "GROUND": ["HOLD20", "GATE_B12", "BOGUS"]},
                   2: _R2_CONVERGE},
    "veto_conflict": {1: _R1_CONVERGE, 2: _R2_CONVERGE},
}

# Cited fields use the "<dotted.path>=<value>" format agreed in docs/plan-rohan.md section 0.
CITED_FIELDS = {
    "ATC": ["nominal_aar=90", "dest_disruption=14"],
    "PILOT": ["fuel_reserve_min=105.1", "alternates[2].distance_nm=190"],
    "GROUND": ["gates.assigned=C20", "downstream_legs[0].SCHEDULED_DEPARTURE=828"],
}

_DEFAULT_VETOES = {
    "ATC": [],
    "PILOT": [{"candidate_id": "HOLD40", "reason": "hold eats into reserve",
               "cited_field": "fuel_reserve_min=105.1"}],
    "GROUND": [{"candidate_id": "DIVERT_AUS", "reason": "crew stranded at AUS",
                "cited_field": "crew_duty_remaining_min=150"}],
}

INVALID_RAW_TEXT = '{"agent": "PILOT", "round": 1, "acceptable": "SLOT+30"'


class FixtureAgent(Agent):
    """Replays a scripted mode. Records every call so tests can inspect what it was given."""

    def __init__(self, role, mode: str = "converge"):
        if mode not in MODES:
            raise ValueError(f"unknown fixture mode {mode!r}; expected one of {MODES}")
        super().__init__(role)
        self.mode = mode
        self.calls: list[dict] = []  # same shape as ClaudeAgent.calls (cost is zero)
        self.received: list[dict] = []  # {round, prior, others} per call

    def _record(self, round: int, valid: bool) -> None:
        self.calls.append({
            "round": round, "tokens_in": 0, "tokens_out": 0, "cache_read_tokens": 0,
            "cost_usd": 0.0, "latency_s": 0.0, "valid": valid,
        })

    def propose(
        self,
        s: Scenario,
        candidates: list[Candidate],
        round: int,
        prior: AgentMessage | None,
        others: list[AgentMessage] | None = None,
    ) -> AgentMessage:
        self.received.append({"round": round, "prior": prior, "others": others})

        if self.mode == "invalid" and self.role == "PILOT" and round == 1:
            self._record(round, valid=False)
            raise InvalidMessage(self.role, INVALID_RAW_TEXT,
                                 "JSON decode error: unterminated object (after 1 retry)")

        script = _SCRIPTS[self.mode]
        acceptable = list(script[min(round, max(script))][self.role])
        vetoes = [v for v in _DEFAULT_VETOES[self.role] if v["candidate_id"] not in acceptable]
        if self.mode == "veto_conflict" and self.role == "PILOT" and round == 1:
            vetoes.append({"candidate_id": "HOLD20", "reason": "turbulence on hold fix",
                           "cited_field": "dest_disruption=14"})

        ranking = [
            {
                "candidate_id": cid,
                "score": round_score(0.9 - 0.2 * i),
                "rationale": f"{self.role} fixture preference #{i + 1}",
                "cited_fields": list(CITED_FIELDS[self.role]),
            }
            for i, cid in enumerate(acceptable)
        ]
        self._record(round, valid=True)
        return AgentMessage(agent=self.role, round=round, acceptable=acceptable,
                            ranking=ranking, vetoes=vetoes)


def round_score(x: float) -> float:
    return max(0.0, min(1.0, round(x, 2)))


def fixture_agents(mode: str = "converge") -> list[FixtureAgent]:
    """The three roles in mediator order."""
    return [FixtureAgent(role, mode=mode) for role in ("ATC", "PILOT", "GROUND")]
