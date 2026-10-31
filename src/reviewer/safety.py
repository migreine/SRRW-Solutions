"""Adversarial safety reviewer. Deterministic, no LLM. Owner: Rohan (L).

Written independently of src/rules/ (separate session, separate prompt):
- re-derive the fuel and wake checks for the chosen candidate
- check every value an agent cited in `cited_fields` against the Scenario
- REJECT if any rule fails or a cited value mismatches beyond tolerance
"""

from typing import Literal

from src.schemas import Recommendation, Scenario, Turn

Verdict = Literal["APPROVE", "REJECT", "MODIFY"]


def review(s: Scenario, rec: Recommendation, turns: list[Turn]) -> tuple[Verdict, list[str]]:
    raise NotImplementedError
