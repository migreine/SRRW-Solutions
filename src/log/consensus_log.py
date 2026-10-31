"""Append-only consensus log, one JSON object per line with an ISO timestamp. Owner: Rohan (L).

Records every agent message and validation result, every rule check, every concession and vote,
the reviewer verdict, whether the fallback fired and why, and the human decision.
"""

from pathlib import Path


class ConsensusLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def append(self, event: dict) -> None:
        raise NotImplementedError
