from indiabloom.news import NewsItem
from indiabloom.research import discover_candidates


def test_news_research_creates_under_review_supplier_candidate(tmp_path):
    names = {"TATACHEM.NS": ("Tata Chemicals",), "AOSL": ("Alpha Omega",)}
    items = [NewsItem("Tata Chemicals supplies Alpha Omega under a new contract", "https://example.test/1", None, "Test")]
    result = discover_candidates("TATACHEM.NS", items, names, tmp_path / "candidates.json")
    assert result.candidates_added == 1
    candidate = result.candidates[0]
    assert candidate.source == "TATACHEM.NS"
    assert candidate.target == "AOSL"
    assert candidate.relation == "supplier"
    assert candidate.status == "candidate"
    assert candidate.evidence_text == items[0].title


def test_research_does_not_create_without_explicit_relationship_language(tmp_path):
    names = {"INFY.NS": ("Infosys",), "TCS.NS": ("TCS",)}
    items = [NewsItem("Infosys and TCS report quarterly results", "https://example.test/2", None, "Test")]
    result = discover_candidates("INFY.NS", items, names, tmp_path / "candidates.json")
    assert result.candidates_added == 0


def test_research_dedupes_same_source_headline(tmp_path):
    names = {"A.NS": ("Alpha",), "B.NS": ("Beta",)}
    item = NewsItem("Alpha competes with Beta in the market", "https://example.test/3", None, "Test")
    path = tmp_path / "candidates.json"
    first = discover_candidates("A.NS", [item], names, path)
    second = discover_candidates("A.NS", [item], names, path)
    assert first.candidates_added == 1 and second.candidates_added == 0


def test_broad_mode_turns_named_comention_into_thematic_candidate(tmp_path):
    names = {"A.NS": ("Alpha",), "B.NS": ("Beta",)}
    item = NewsItem("Alpha and Beta discuss a market collaboration", "https://example.test/4", None, "Test")
    result = discover_candidates("A.NS", [item], names, tmp_path / "candidates.json", broad=True)
    assert result.candidates_added == 1
    assert result.candidates[0].relation == "thematic"
