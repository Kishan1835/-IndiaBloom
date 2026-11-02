import json

import pytest

from indiabloom.candidates import (
    add_candidate,
    approve_candidate,
    candidates_for,
    load_candidates,
    update_status,
)


def test_candidate_queue_add_status_and_filter(tmp_path):
    path = tmp_path / "candidates.json"
    row = add_candidate("TATACHEM.NS", "CUSTOMER.NS", "supplier", "medium",
                        "A filing names the relationship.", ["https://example.test"],
                        "official_filing", "The filing names the customer.", path)
    assert row.id == 1
    rows, next_id = load_candidates(path)
    assert next_id == 2
    assert candidates_for("TATACHEM.NS", rows)[0].status == "candidate"
    update_status(1, "under_review", path)
    assert load_candidates(path)[0][0].status == "under_review"
    update_status(1, "rejected", path)
    assert candidates_for("TATACHEM.NS", load_candidates(path)[0]) == []


def test_approve_moves_candidate_to_verified_relations(tmp_path):
    candidates = tmp_path / "candidates.json"
    relations = tmp_path / "relations.json"
    relations.write_text("[]", encoding="utf-8")
    add_candidate("KAYNES.NS", "AOSL", "supplier", "high", "Official announcement.",
                  ["https://example.test"], "company_release", "evidence", candidates)
    approved = approve_candidate(1, relations, candidates)
    assert approved.status == "approved"
    saved = json.loads(relations.read_text(encoding="utf-8"))
    assert saved[0]["status"] == "verified"
    assert saved[0]["evidence_text"] == "evidence"


def test_candidate_validation_rejects_bad_relationship(tmp_path):
    with pytest.raises(ValueError):
        add_candidate("A.NS", "B.NS", "customer", "low", "bad", path=tmp_path / "x.json")
