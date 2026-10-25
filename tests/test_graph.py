import json
from pathlib import Path

import pytest

from indiabloom.graph import Graph, RelationValidationError, load_relations, parse_relations

BUNDLED = Path(__file__).resolve().parent.parent / "data" / "relations.json"


def _item(**overrides):
    base = {
        "source": "MU",
        "target": "KAYNES.NS",
        "relation": "thematic",
        "confidence": "low",
        "rationale": "test link",
        "sources": [],
    }
    base.update(overrides)
    return base


def test_bundled_relations_file_is_valid():
    relations = load_relations(BUNDLED)
    assert relations
    assert Graph(relations).nodes()


def test_missing_field_rejected():
    bad = _item()
    del bad["rationale"]
    with pytest.raises(RelationValidationError, match="rationale"):
        parse_relations([bad])


def test_invalid_ticker_rejected():
    with pytest.raises(RelationValidationError, match="not a valid ticker"):
        parse_relations([_item(target="BAD TICKER")])


def test_wrong_indian_suffix_rejected():
    with pytest.raises(RelationValidationError, match="not a valid ticker"):
        parse_relations([_item(target="KAYNES.US")])


def test_self_link_rejected():
    with pytest.raises(RelationValidationError, match="same ticker"):
        parse_relations([_item(source="MU", target="MU")])


def test_old_relation_type_rejected():
    with pytest.raises(RelationValidationError, match="relation"):
        parse_relations([_item(relation="customer")])


def test_bad_confidence_rejected():
    with pytest.raises(RelationValidationError, match="confidence"):
        parse_relations([_item(confidence="certain")])


def test_undirected_duplicate_in_either_order_rejected():
    peer_ab = _item(relation="peer", source="TCS.NS", target="INFY.NS")
    peer_ba = _item(relation="peer", source="INFY.NS", target="TCS.NS")
    with pytest.raises(RelationValidationError, match="duplicate"):
        parse_relations([peer_ab, peer_ba])


def test_supplier_links_are_directed_so_both_orders_allowed():
    a = _item(relation="supplier", source="X.NS", target="Y")
    b = _item(relation="supplier", source="Y", target="X.NS")
    assert len(parse_relations([a, b])) == 2


def test_top_level_must_be_array(tmp_path):
    path = tmp_path / "r.json"
    path.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
    with pytest.raises(RelationValidationError, match="array"):
        load_relations(path)


def _graph():
    return Graph(parse_relations([
        _item(relation="peer", source="TCS.NS", target="INFY.NS", confidence="high"),
        _item(relation="peer", source="WIPRO.NS", target="INFY.NS"),
        _item(relation="supplier", source="KAYNES.NS", target="MU"),
        _item(relation="supplier", source="MU", target="ACN"),
        _item(relation="thematic", source="MU", target="CGPOWER.NS"),
    ]))


def test_competitors_are_peer_links_either_side():
    names = [l.other for l in _graph().competitors("INFY.NS")]
    assert names == ["TCS.NS", "WIPRO.NS"]


def test_thematic_links_are_not_competitors():
    assert all(l.relation == "peer" for l in _graph().competitors("MU"))


def test_suppliers_and_customers_follow_direction():
    g = _graph()
    assert [l.other for l in g.suppliers("MU")] == ["KAYNES.NS"]
    assert [l.other for l in g.customers("MU")] == ["ACN"]
    # reverse view: Kaynes's customer is MU
    assert [l.other for l in g.customers("KAYNES.NS")] == ["MU"]


def test_unknown_ticker_has_no_links():
    g = _graph()
    assert g.links("NOSUCH") == []
    assert g.suppliers("NOSUCH") == []


def test_indian_counterparts_include_either_side():
    names = sorted(r.other("MU") for r in _graph().indian_counterparts("MU"))
    assert names == ["CGPOWER.NS", "KAYNES.NS"]
