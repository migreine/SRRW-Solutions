"""ATC, Pilot and Ground agents. Owner: Reine (T2).

Each agent is a separate call with its own system prompt (src/agents/prompts/) and only its own
domain's data. Agents rank and veto candidates; they never judge legality or do arithmetic.

Task card (docs/timeline.md, build block 1):
- StubAgent: deterministic domain heuristics that always return a valid AgentMessage.
- ClaudeAgent(model): anthropic SDK, prompt caching on the system prompt, one retry on invalid
  JSON, then raise InvalidMessage carrying the raw text. Record tokens and cost per call.
"""

from typing import Literal

from src.schemas import AgentMessage, Candidate, Scenario

Role = Literal["ATC", "PILOT", "GROUND"]


class InvalidMessage(Exception):
    """An agent reply that failed schema validation. Carries the raw text for the log."""

    def __init__(self, role: Role, raw_text: str, error: str):
        super().__init__(f"{role}: {error}")
        self.role = role
        self.raw_text = raw_text
        self.error = error


class Agent:
    def __init__(self, role: Role):
        self.role = role

    def propose(
        self,
        s: Scenario,
        candidates: list[Candidate],
        round: int,
        prior: AgentMessage | None,
    ) -> AgentMessage:
        raise NotImplementedError


class StubAgent(Agent):
    def propose(self, s, candidates, round, prior):
        raise NotImplementedError


class ClaudeAgent(Agent):
    def __init__(self, role: Role, model: str):
        super().__init__(role)
        self.model = model

    def propose(self, s, candidates, round, prior):
        raise NotImplementedError
