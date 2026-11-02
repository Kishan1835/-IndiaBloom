"""Typed headline-classification boundary for Jev or another provider.

This module deliberately does not contain a guessed Jev HTTP endpoint. The
provider contract is isolated behind `HeadlineClassifier`, so the rest of
IndiaBloom can be built and tested without a key or network access.

Only normalized NewsItem data crosses into a classifier. Holdings, watchlists,
prices and alert rules are never sent by this boundary.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from indiabloom.news import NewsItem, sentiment, sentiment_label

Sentiment = Literal["positive", "negative", "neutral"]
Relevance = Literal["high", "medium", "low"]
DecisionStatus = Literal["accepted", "review_required", "rejected"]


class JevError(RuntimeError):
    """Raised when a provider response is unavailable or invalid."""


@dataclass(frozen=True)
class HeadlineClassification:
    """Validated result attached to one normalized headline."""

    headline_key: str
    sentiment: Sentiment
    relevance: Relevance
    confidence: float
    status: DecisionStatus
    rationale: str
    provider: str = "local"
    model: str = "heuristic"


class HeadlineClassifier(Protocol):
    def classify(self, items: list[NewsItem]) -> list[HeadlineClassification]: ...


def headline_key(item: NewsItem) -> str:
    """Stable identity for caching and matching provider results."""
    raw = f"{item.title.strip().lower()}\n{item.link.strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _choice(value: Any, allowed: tuple[str, ...], field: str) -> str:
    if not isinstance(value, str) or value.lower() not in allowed:
        raise JevError(f"invalid {field}; expected one of {', '.join(allowed)}")
    return value.lower()


def parse_decision(raw: dict[str, Any], expected_key: str | None = None,
                   provider: str = "jev", model: str = "unknown") -> HeadlineClassification:
    """Validate one provider decision at the trust boundary.

    Accepted JSON fields: headline_key, sentiment, relevance, confidence,
    rationale. `status` is derived from confidence, so the provider cannot
    silently bypass India's review threshold.
    """
    key = raw.get("headline_key")
    if expected_key is not None:
        key = expected_key if key is None else key
    if not isinstance(key, str) or not key:
        raise JevError("decision is missing headline_key")
    if expected_key is not None and key != expected_key:
        raise JevError("provider decision headline_key does not match the requested headline")
    sentiment_value = _choice(raw.get("sentiment"), ("positive", "negative", "neutral"), "sentiment")
    relevance_value = _choice(raw.get("relevance"), ("high", "medium", "low"), "relevance")
    confidence = raw.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        raise JevError("confidence must be a number from 0 to 1")
    rationale = raw.get("rationale", "")
    if not isinstance(rationale, str):
        raise JevError("rationale must be text")
    status: DecisionStatus = "accepted" if confidence >= 0.80 else "review_required"
    return HeadlineClassification(key, sentiment_value, relevance_value, float(confidence),
                                  status, rationale[:500], provider, model)


class LocalHeadlineClassifier:
    """Offline fallback. It never claims model confidence above 0.60."""

    def classify(self, items: list[NewsItem]) -> list[HeadlineClassification]:
        results = []
        for item in items:
            label = sentiment_label(sentiment(item.title))
            results.append(HeadlineClassification(
                headline_key(item), label, "low", 0.50, "review_required",
                "Local word-count heuristic; not Jev.", "local", "heuristic"))
        return results


class JsonResponseClassifier:
    """Provider-neutral JSON adapter used by tests and the future Jev transport.

    `request` is injected because TypeSafe's official endpoint and SDK contract
    are not present in the repository. It must return a JSON object containing
    `decisions`, a list of typed decision objects.
    """

    def __init__(self, request: Callable[[dict[str, Any]], dict[str, Any]],
                 provider: str = "jev", model: str = "unknown") -> None:
        self.request = request
        self.provider = provider
        self.model = model

    def classify(self, items: list[NewsItem]) -> list[HeadlineClassification]:
        if not items:
            return []
        payload = {"headlines": [{"headline_key": headline_key(i), "title": i.title,
                                   "link": i.link} for i in items]}
        try:
            response = self.request(payload)
        except Exception as exc:
            raise JevError(f"classifier request failed: {exc}") from exc
        if not isinstance(response, dict) or not isinstance(response.get("decisions"), list):
            raise JevError("classifier response must contain a decisions list")
        expected = {headline_key(i) for i in items}
        decisions = [parse_decision(x, provider=self.provider, model=self.model)
                     for x in response["decisions"] if isinstance(x, dict)]
        if {d.headline_key for d in decisions} != expected:
            raise JevError("classifier must return exactly one decision for every headline")
        return decisions


def classify_with_fallback(items: list[NewsItem], classifier: HeadlineClassifier | None,
                           strict: bool = False) -> list[HeadlineClassification]:
    """Use the optional classifier; fall back locally unless strict mode is requested."""
    if classifier is None:
        return LocalHeadlineClassifier().classify(items)
    try:
        return classifier.classify(items)
    except Exception:
        if strict:
            raise
        return LocalHeadlineClassifier().classify(items)


def cache_key(items: Iterable[NewsItem], provider: str, model: str) -> str:
    """Key for a future classification cache, stable across process restarts."""
    keys = sorted(headline_key(item) for item in items)
    return hashlib.sha256(json.dumps([provider, model, keys]).encode()).hexdigest()
