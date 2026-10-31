"""Deterministic rules engine. No LLM. Owner: Waseem (T1).

Every check returns a RuleResult with its rule ID, observed value, threshold, source tag and citation:
- R-WAKE-01  wake separation       FAA JO 7110.65 §5-5-4 (approach speed assumed)
- R-FUEL-01  minimum fuel reserve  14 CFR 121.639 (fuel estimated)
- R-DUTY-01  crew duty limit       14 CFR Part 117 (duty state synthetic)
- R-GATE-01  gate conflict         synthetic gate model
- R-TURN-01  minimum turnaround    assumed per aircraft class
- R-AAR-01   arrival-rate cap      assumed nominal rate, reduced by disruption
Use the verified values from docs/regulatory_sources.md; anything unverified is cited as "assumed".
"""

from src.schemas import Candidate, RuleResult, Scenario


def check_all(s: Scenario, candidates: list[Candidate]) -> list[RuleResult]:
    raise NotImplementedError
