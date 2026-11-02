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
from indiabloom.jev import HeadlineClassifier, classify_with_fallback, headline_key
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
                        candidate_path=None, classifier: HeadlineClassifier | None = None) -> ResearchResult:
    """Find named counterparties in headlines and save review candidates.

    Direction is conservative and marked under_review. For supplier language, the
    headline's selected ticker is treated as the source only when it contains
    'supplies', 'provides', 'manufactures for' or 'supplier'. Other customer/order
    wording treats the mentioned company as the source. Review every result.
    """
    existing, _ = load_candidates(candidate_path) if candidate_path else load_candidates()
    existing_keys = {(c.source, c.target, c.relation, tuple(c.sources)) for c in existing
                     if c.status != "rejected"}
    classifications = {}
    if classifier is not None:
        results = classify_with_fallback(items, classifier)
        classifications = {r.headline_key: r for r in results}
    added: list[Candidate] = []
    selected = ticker.upper()
    for item in items:
        mentioned = find_mentions(item.title, names) - {selected}
        relation = _relation_for(item.title)
        classification = classifications.get(headline_key(item))
        if relation is None or (classification is not None and classification.relevance == "low"):
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
            rationale = f"News headline suggests a {relation} relationship; verify the direction and company identity."
            if classification is not None:
                rationale += f" Jev relevance={classification.relevance}, confidence={classification.confidence:.2f}."
            candidate = add_candidate(
                source, target, relation, "low", rationale,
                [item.link] if item.link else [], "reputable_news", item.title,
                candidate_path or CANDIDATES_FILE,
            )
            added.append(candidate)
            existing_keys.add(key)
    return ResearchResult(len(items), len(added), added)
