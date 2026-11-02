import json

import pytest

from indiabloom.candidates import add_candidate, approve_many, load_candidates


def _seed(tmp_path):
    candidates = tmp_path / "candidates.json"
    relations = tmp_path / "relations.json"
    relations.write_text("[]", encoding="utf-8")
    add_candidate("A.NS", "B.NS", "peer", "high", "source one", path=candidates)
    add_candidate("C.NS", "D.NS", "thematic", "medium", "source two", path=candidates)
    return candidates, relations


def test_approve_many_is_atomic_on_missing_id(tmp_path):
    candidates, relations = _seed(tmp_path)
    with pytest.raises(KeyError):
        approve_many([1, 99], relations, candidates)
    assert json.loads(relations.read_text()) == []
    assert all(r.status == "candidate" for r in load_candidates(candidates)[0])


def test_approve_many_writes_selected_ids_only(tmp_path):
    candidates, relations = _seed(tmp_path)
    approved = approve_many([2], relations, candidates)
    assert [r.id for r in approved] == [2]
    saved = json.loads(relations.read_text())
    assert len(saved) == 1 and saved[0]["source"] == "C.NS"
    rows, _ = load_candidates(candidates)
    assert rows[0].status == "candidate" and rows[1].status == "approved"


def test_approve_many_rejects_duplicate_verified_link(tmp_path):
    candidates, relations = _seed(tmp_path)
    approve_many([1], relations, candidates)
    with pytest.raises(ValueError, match="already exists"):
        approve_many([1], relations, candidates)
