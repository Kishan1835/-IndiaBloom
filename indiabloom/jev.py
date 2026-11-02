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
import os
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


@dataclass(frozen=True)
class ClassifiedNews:
    items: list[NewsItem]
    classifications: dict[str, HeadlineClassification]


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
        result = classifier.classify(items) if hasattr(classifier, "classify") else classifier(items)  # type: ignore[operator]
        return result
    except Exception:
        if strict:
            raise
        return LocalHeadlineClassifier().classify(items)


def cache_key(items: Iterable[NewsItem], provider: str, model: str) -> str:
    """Key for a future classification cache, stable across process restarts."""
    keys = sorted(headline_key(item) for item in items)
    return hashlib.sha256(json.dumps([provider, model, keys]).encode()).hexdigest()


@dataclass(frozen=True)
class JevConfig:
    api_key: str
    model: str = "jev-latest"
    base_url: str | None = None
    timeout: float = 30.0


def load_config(env_path: str | None = ".env") -> JevConfig:
    """Read Jev config without printing or logging secrets.

    Environment variables win. The lowercase `jev_api` name is accepted because
    that is the key name currently used in this workspace's .env file.
    """
    values: dict[str, str] = {}
    if env_path and os.path.exists(env_path):
        for line in open(env_path, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    def get(*names: str) -> str | None:
        for name in names:
            value = os.getenv(name) or values.get(name)
            if value:
                return value
        return None
    api_key = get("TYPESAFE_API_KEY", "OPENROUTER_API_KEY", "JEV_API_KEY", "jev_api")
    if not api_key:
        raise JevError("missing Jev API key; set TYPESAFE_API_KEY or JEV_API_KEY in .env")
    return JevConfig(api_key, get("JEV_MODEL", "TYPESAFE_MODEL") or "jev-latest",
                     get("TYPESAFE_BASE_URL", "JEV_BASE_URL"),
                     float(get("JEV_TIMEOUT") or "30"))


class TypeSafeHeadlineClassifier:
    """Real Jev classifier using the official TypeSafe Python SDK."""

    def __init__(self, config: JevConfig | None = None, batch_size: int = 25) -> None:
        self.config = config or load_config()
        self.batch_size = max(1, batch_size)
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                from typesafe_sdk import TypeSafeClient
            except ImportError as exc:
                raise JevError("install typesafe-sdk before using the Jev classifier") from exc
            kwargs: dict[str, Any] = {"api_key": self.config.api_key, "model": self.config.model,
                                      "timeout": self.config.timeout}
            if self.config.base_url:
                kwargs["base_url"] = self.config.base_url
            self._client = TypeSafeClient(**kwargs)
        return self._client

    def classify(self, items: list[NewsItem]) -> list[HeadlineClassification]:
        if not items:
            return []
        from typesafe_sdk import Choice

        results: list[HeadlineClassification] = []
        for start in range(0, len(items), self.batch_size):
            batch = items[start:start + self.batch_size]
            questions = {}
            state = {"headlines": []}
            for index, item in enumerate(batch):
                state["headlines"].append({"id": index, "title": item.title, "source": item.source})
                questions[f"sentiment_{index}"] = Choice(
                    instructions=f"What is the financial sentiment of headline {index} for its named company?",
                    criteria={"positive": None, "negative": None, "neutral": None},
                )
                questions[f"relevance_{index}"] = Choice(
                    instructions=f"How relevant is headline {index} to a public company's stock price?",
                    criteria={"high": None, "medium": None, "low": None},
                )
            try:
                response = self._get_client().system_one(state=state, model=self.config.model, questions=questions)
                for index, item in enumerate(batch):
                    sentiment_answer = response.choices[f"sentiment_{index}"]
                    relevance_answer = response.choices[f"relevance_{index}"]
                    confidence = min(float(getattr(sentiment_answer, "confidence", 0.0)),
                                     float(getattr(relevance_answer, "confidence", 0.0)))
                    key = headline_key(item)
                    results.append(parse_decision({
                        "headline_key": key,
                        "sentiment": sentiment_answer.choice,
                        "relevance": relevance_answer.choice,
                        "confidence": confidence,
                        "rationale": "Jev typed decision; Jev does not return reasoning text.",
                    }, expected_key=key, provider="jev", model=self.config.model))
            except Exception as exc:
                sample = batch[0].title[:80] if batch else "empty batch"
                raise JevError(f"Jev failed for batch starting with '{sample}': {exc}") from exc
        return results

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
