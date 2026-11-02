import pytest

from indiabloom.graph import Graph, RelationValidationError, parse_relations


def _item(**overrides):
    item = {
        "source": "KAYNES.NS", "target": "AOSL", "relation": "supplier",
        "confidence": "high", "rationale": "official disclosed relationship", "sources": ["https://example.test"],
    }
    item.update(overrides)
    return item


def test_relation_evidence_defaults_are_backward_compatible():
    relation = parse_relations([_item()])[0]
    assert relation.status == "verified"
    assert relation.source_type == "unknown"
    link = Graph([relation]).links("KAYNES.NS")[0]
    assert link.status == "verified" and link.sources == ("https://example.test",)


def test_relation_evidence_fields_are_preserved():
    relation = parse_relations([_item(status="under_review", source_type="official_filing",
                                      last_checked="2026-11-01", evidence_text="The filing names AOSL.")])[0]
    assert relation.status == "under_review"
    assert relation.source_type == "official_filing"
    assert relation.evidence_text == "The filing names AOSL."


@pytest.mark.parametrize("field,value", [("status", "unknown"), ("source_type", "blog")])
def test_invalid_evidence_metadata_is_rejected(field, value):
    with pytest.raises(RelationValidationError, match=field):
        parse_relations([_item(**{field: value})])
