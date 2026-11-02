import pytest

from indiabloom.jev import (
    JevError,
    JsonResponseClassifier,
    LocalHeadlineClassifier,
    cache_key,
    classify_with_fallback,
    headline_key,
    parse_decision,
)
from indiabloom.news import NewsItem


ITEMS = [
    NewsItem("Infosys wins a major contract", "https://example.test/1", None, "Test"),
    NewsItem("Company reports weak profit", "https://example.test/2", None, "Test"),
]


def test_headline_key_and_cache_key_are_stable():
    assert headline_key(ITEMS[0]) == headline_key(ITEMS[0])
    assert headline_key(ITEMS[0]) != headline_key(ITEMS[1])
    assert cache_key(ITEMS, "jev", "v1") == cache_key(list(reversed(ITEMS)), "jev", "v1")


def test_parse_decision_accepts_and_derives_review_status():
    result = parse_decision({
        "headline_key": headline_key(ITEMS[0]), "sentiment": "positive",
        "relevance": "high", "confidence": 0.91, "rationale": "contract language",
    }, expected_key=headline_key(ITEMS[0]), model="test")
    assert result.status == "accepted"
    assert result.provider == "jev"

    review = parse_decision({
        "headline_key": headline_key(ITEMS[0]), "sentiment": "neutral",
        "relevance": "medium", "confidence": 0.79,
    })
    assert review.status == "review_required"


@pytest.mark.parametrize("raw", [
    {"sentiment": "positive", "relevance": "high", "confidence": 0.9},
    {"headline_key": "x", "sentiment": "maybe", "relevance": "high", "confidence": 0.9},
    {"headline_key": "x", "sentiment": "positive", "relevance": "high", "confidence": 1.2},
    {"headline_key": "x", "sentiment": "positive", "relevance": "high", "confidence": 0.9, "rationale": 3},
])
def test_invalid_decisions_are_rejected(raw):
    with pytest.raises(JevError):
        parse_decision(raw)


def test_json_response_classifier_sends_only_headlines_and_validates_all_results():
    seen = {}

    def request(payload):
        seen.update(payload)
        return {"decisions": [
            {"headline_key": headline_key(item), "sentiment": "neutral", "relevance": "medium",
             "confidence": 0.82, "rationale": "test"}
            for item in ITEMS
        ]}

    results = JsonResponseClassifier(request, model="fake").classify(ITEMS)
    assert len(results) == 2
    assert set(seen["headlines"][0]) == {"headline_key", "title", "link"}
    assert "holdings" not in seen and "watchlist" not in seen


def test_json_response_requires_exactly_one_result_per_headline():
    def incomplete(_payload):
        return {"decisions": []}

    with pytest.raises(JevError, match="exactly one"):
        JsonResponseClassifier(incomplete).classify(ITEMS)


def test_empty_input_does_not_call_provider():
    called = False

    def request(_payload):
        nonlocal called
        called = True
        return {}

    assert JsonResponseClassifier(request).classify([]) == []
    assert not called


def test_local_fallback_is_low_confidence_review_only():
    result = classify_with_fallback(ITEMS, None)
    assert len(result) == 2
    assert all(r.provider == "local" and r.status == "review_required" and r.confidence == 0.5 for r in result)


def test_provider_failure_falls_back_unless_strict():
    class Broken:
        def classify(self, items):
            raise JevError("offline")

    fallback = classify_with_fallback(ITEMS, Broken())
    assert all(r.provider == "local" for r in fallback)
    with pytest.raises(JevError):
        classify_with_fallback(ITEMS, Broken(), strict=True)
