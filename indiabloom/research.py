"""Create reviewable relationship candidates from company news headlines.

This is intentionally conservative. It only creates a candidate when a known
company name appears alongside explicit relationship language. It never writes
to the verified graph automatically.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from indiabloom.candidates import CANDIDATES_FILE, Candidate, add_candidate, load_candidates
from indiabloom.companies import find_mentions
from indiabloom.news import NewsItem

SUPPLY_WORDS = re.compile(r"\b(supplier|supplies|supply|provides|manufactures for|contract manufacturer|customer|client|order from|procures from)\b", re.I)
COMPETE_WORDS = re.compile(r"\b(competes? with|competitor|rival|peers? with)\b", re.I)


@dataclass(frozen=True)
class ResearchResult:
    headlines: int
    candidates_added: int
    candidates: list[Candidate]


def _relation_for(text: str) -> str | None:
    if COMPETE_WORDS.search(text):
        return "peer"
    if SUPPLY_WORDS.search(text):
        return "supplier"
    return None


def discover_candidates(ticker: str, items: list[NewsItem], names: dict[str, tuple[str, ...]],
                        candidate_path=None) -> ResearchResult:
    """Find named counterparties in headlines and save review candidates.

    Direction is conservative and marked under_review. For supplier language, the
    headline's selected ticker is treated as the source only when it contains
    'supplies', 'provides', 'manufactures for' or 'supplier'. Other customer/order
    wording treats the mentioned company as the source. Review every result.
    """
    existing, _ = load_candidates(candidate_path) if candidate_path else load_candidates()
    existing_keys = {(c.source, c.target, c.relation, tuple(c.sources)) for c in existing
                     if c.status != "rejected"}
    added: list[Candidate] = []
    selected = ticker.upper()
    for item in items:
        mentioned = find_mentions(item.title, names) - {selected}
        relation = _relation_for(item.title)
        if relation is None:
            continue
        for other in sorted(mentioned):
            if relation == "peer":
                source, target = selected, other
            elif re.search(r"\b(supplies|provides|manufactures for|supplier)\b", item.title, re.I):
                source, target = selected, other
            else:
                source, target = other, selected
            key = (source, target, relation, (item.link,))
            if key in existing_keys:
                continue
            candidate = add_candidate(
                source, target, relation, "low",
                f"News headline suggests a {relation} relationship; verify the direction and company identity.",
                [item.link] if item.link else [], "reputable_news", item.title,
                candidate_path or CANDIDATES_FILE,
            )
            added.append(candidate)
            existing_keys.add(key)
    return ResearchResult(len(items), len(added), added)
