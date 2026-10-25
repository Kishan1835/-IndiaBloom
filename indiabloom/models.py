"""Data model for the stock relationship graph.

A Relation links two tickers. Tickers are US symbols (e.g. MU) or NSE/BSE
symbols with a .NS or .BO suffix (e.g. INFY.NS).

Direction:
- `supplier` is directed: `source` supplies `target`.
- `peer` (competitor) and `thematic` are undirected.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

RELATION_TYPES = frozenset({"supplier", "peer", "thematic"})
DIRECTED_TYPES = frozenset({"supplier"})
CONFIDENCE_LEVELS = frozenset({"low", "medium", "high"})
CONFIDENCE_WEIGHTS = {"high": 1.0, "medium": 0.6, "low": 0.3}
INDIAN_SUFFIXES = (".NS", ".BO")
TICKER_PATTERN = re.compile(r"^[A-Z][A-Z0-9\-]{0,9}(\.(NS|BO))?$")


def is_indian(ticker: str) -> bool:
    return ticker.endswith(INDIAN_SUFFIXES)


@dataclass(frozen=True)
class Relation:
    source: str
    target: str
    relation: str
    confidence: str
    rationale: str
    sources: tuple[str, ...] = field(default_factory=tuple)

    @property
    def weight(self) -> float:
        return CONFIDENCE_WEIGHTS[self.confidence]

    @property
    def directed(self) -> bool:
        return self.relation in DIRECTED_TYPES

    def other(self, ticker: str) -> str | None:
        """The counterpart of `ticker` in this link, or None if it is not an endpoint."""
        if ticker == self.source:
            return self.target
        if ticker == self.target:
            return self.source
        return None
