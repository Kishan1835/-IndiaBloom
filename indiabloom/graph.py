"""Load, validate, and query the relationship graph."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from indiabloom.models import (
    CONFIDENCE_LEVELS,
    RELATION_TYPES,
    TICKER_PATTERN,
    Relation,
    is_indian,
)

REQUIRED_FIELDS = ("source", "target", "relation", "confidence", "rationale")


class RelationValidationError(ValueError):
    """Raised when the relations file breaks the schema in SPEC section 5."""


def _clean_ticker(index: int, name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RelationValidationError(f"item {index}: field '{name}' is missing or empty")
    ticker = value.strip().upper()
    if not TICKER_PATTERN.match(ticker):
        raise RelationValidationError(f"item {index}: '{name}' value '{ticker}' is not a valid ticker")
    return ticker


def _parse_one(index: int, item: Any) -> Relation:
    if not isinstance(item, dict):
        raise RelationValidationError(f"item {index}: must be an object")
    for name in ("relation", "confidence", "rationale"):
        value = item.get(name)
        if not isinstance(value, str) or not value.strip():
            raise RelationValidationError(f"item {index}: field '{name}' is missing or empty")

    source = _clean_ticker(index, "source", item.get("source"))
    target = _clean_ticker(index, "target", item.get("target"))
    if source == target:
        raise RelationValidationError(f"item {index}: source and target are the same ticker")
    if item["relation"] not in RELATION_TYPES:
        raise RelationValidationError(
            f"item {index}: relation '{item['relation']}' not in {sorted(RELATION_TYPES)}"
        )
    if item["confidence"] not in CONFIDENCE_LEVELS:
        raise RelationValidationError(
            f"item {index}: confidence '{item['confidence']}' not in {sorted(CONFIDENCE_LEVELS)}"
        )
    sources = item.get("sources", [])
    if not isinstance(sources, list) or not all(isinstance(s, str) for s in sources):
        raise RelationValidationError(f"item {index}: sources must be a list of strings")

    return Relation(
        source=source,
        target=target,
        relation=item["relation"],
        confidence=item["confidence"],
        rationale=item["rationale"].strip(),
        sources=tuple(sources),
    )


def parse_relations(items: list[Any]) -> list[Relation]:
    """Validate raw JSON items and return Relation objects."""
    relations: list[Relation] = []
    seen: set[tuple[str, ...]] = set()
    for index, item in enumerate(items):
        relation = _parse_one(index, item)
        # Undirected links are identical in both orders, so normalise the key.
        if relation.directed:
            key = (relation.relation, relation.source, relation.target)
        else:
            key = (relation.relation, *sorted((relation.source, relation.target)))
        if key in seen:
            raise RelationValidationError(f"item {index}: duplicate link {key}")
        seen.add(key)
        relations.append(relation)
    return relations


def load_relations(path: str | Path) -> list[Relation]:
    """Read and validate the relations JSON file."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise RelationValidationError("top level must be a JSON array")
    return parse_relations(raw)


@dataclass(frozen=True)
class Link:
    """One row shown in the UI: a counterpart and how it relates to the selected stock."""

    other: str
    relation: str
    direction: str  # "supplies" (other supplies selected), "supplied-by", or "" for undirected
    confidence: str
    rationale: str


class Graph:
    """Read-only query layer over a validated list of relations."""

    def __init__(self, relations: list[Relation]) -> None:
        self._relations = list(relations)

    @property
    def relations(self) -> list[Relation]:
        return list(self._relations)

    def nodes(self) -> list[str]:
        found: set[str] = set()
        for rel in self._relations:
            found.add(rel.source)
            found.add(rel.target)
        return sorted(found)

    def links(self, ticker: str) -> list[Link]:
        """Every link touching `ticker`, with direction from its point of view."""
        key = ticker.strip().upper()
        out: list[Link] = []
        for rel in self._relations:
            other = rel.other(key)
            if other is None:
                continue
            if not rel.directed:
                direction = ""
            elif rel.source == key:
                direction = "supplies"
            else:
                direction = "supplied-by"
            out.append(Link(other, rel.relation, direction, rel.confidence, rel.rationale))
        out.sort(key=lambda link: (link.relation, link.other))
        return out

    def competitors(self, ticker: str) -> list[Link]:
        return [link for link in self.links(ticker) if link.relation == "peer"]

    def suppliers(self, ticker: str) -> list[Link]:
        return [link for link in self.links(ticker) if link.direction == "supplied-by"]

    def customers(self, ticker: str) -> list[Link]:
        return [link for link in self.links(ticker) if link.direction == "supplies"]

    def indian_counterparts(self, ticker: str) -> list[Relation]:
        """Relations linking `ticker` to a listed Indian stock (used by the scanner)."""
        key = ticker.strip().upper()
        return [
            rel for rel in self._relations
            if rel.other(key) is not None and is_indian(rel.other(key))
        ]
