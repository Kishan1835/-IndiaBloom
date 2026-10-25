"""Group stocks into sector tabs (IT, Banks, Manufacturing, Pharma) for the UI.

The group rules live in data/sectors.json. A stock is classified by its NSE
industry label. Banks are picked out by name inside the Financial Services
industry, so non-bank lenders are not counted as banks.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

SECTORS_FILE = Path(__file__).resolve().parent.parent / "data" / "sectors.json"
OTHER = "Other"


@dataclass(frozen=True)
class SectorRule:
    group: str
    industries: frozenset[str]
    name_contains: tuple[str, ...]


def load_rules(path: Path = SECTORS_FILE) -> list[SectorRule]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    rules = []
    for group, spec in raw.items():
        industries = spec.get("industries", [])
        if not isinstance(industries, list) or not all(isinstance(i, str) for i in industries):
            raise ValueError(f"{group}: industries must be a list of strings")
        names = spec.get("name_contains", [])
        rules.append(SectorRule(group, frozenset(industries), tuple(names)))
    return rules


def classify(company: str, industry: str, rules: list[SectorRule]) -> str:
    """First matching group wins. Name rules are checked before industry-only rules."""
    lowered = company.lower()
    for rule in rules:
        if rule.name_contains and industry in rule.industries:
            if any(part.lower() in lowered for part in rule.name_contains):
                return rule.group
    for rule in rules:
        if not rule.name_contains and industry in rule.industries:
            return rule.group
    return OTHER
