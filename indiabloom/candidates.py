"""Review queue for supplier/customer/competitor relationship candidates.

Candidates are deliberately separate from data/relations.json. News and company
documents can suggest a relationship, but only an explicit approval moves it into
the verified graph.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from indiabloom.models import CONFIDENCE_LEVELS, EVIDENCE_STATUSES, RELATION_TYPES

CANDIDATES_FILE = Path(__file__).resolve().parent.parent / "data" / "relationship_candidates.json"
RELATIONS_FILE = Path(__file__).resolve().parent.parent / "data" / "relations.json"
CANDIDATE_STATUSES = frozenset({"candidate", "under_review", "approved", "rejected"})


@dataclass
class Candidate:
    id: int
    source: str
    target: str
    relation: str
    confidence: str
    rationale: str
    sources: list[str] = field(default_factory=list)
    source_type: str = "unknown"
    evidence_text: str | None = None
    discovered_at: str = field(default_factory=lambda: date.today().isoformat())
    status: str = "candidate"


def _validate(candidate: Candidate) -> None:
    if candidate.relation not in RELATION_TYPES:
        raise ValueError(f"relation must be one of {sorted(RELATION_TYPES)}")
    if candidate.confidence not in CONFIDENCE_LEVELS:
        raise ValueError(f"confidence must be one of {sorted(CONFIDENCE_LEVELS)}")
    if candidate.status not in CANDIDATE_STATUSES:
        raise ValueError(f"status must be one of {sorted(CANDIDATE_STATUSES)}")
    if not candidate.source or not candidate.target or candidate.source == candidate.target:
        raise ValueError("source and target must be different non-empty tickers")
    if not candidate.rationale.strip():
        raise ValueError("rationale is required")


def load_candidates(path: Path = CANDIDATES_FILE) -> tuple[list[Candidate], int]:
    if not path.exists():
        return [], 1
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = [Candidate(**item) for item in raw.get("candidates", [])]
    for row in rows:
        _validate(row)
    return rows, int(raw.get("next_id", max((r.id for r in rows), default=0) + 1))


def save_candidates(rows: list[Candidate], next_id: int, path: Path = CANDIDATES_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"next_id": next_id, "candidates": [asdict(r) for r in rows]}, indent=1),
                    encoding="utf-8")


def add_candidate(source: str, target: str, relation: str, confidence: str, rationale: str,
                  sources: list[str] | None = None, source_type: str = "unknown",
                  evidence_text: str | None = None, path: Path = CANDIDATES_FILE) -> Candidate:
    rows, next_id = load_candidates(path)
    candidate = Candidate(next_id, source.strip().upper(), target.strip().upper(), relation,
                          confidence, rationale.strip(), sources or [], source_type,
                          evidence_text, status="candidate")
    _validate(candidate)
    rows.append(candidate)
    save_candidates(rows, next_id + 1, path)
    return candidate


def candidates_for(ticker: str, rows: list[Candidate]) -> list[Candidate]:
    code = ticker.upper()
    return [r for r in rows if (r.source == code or r.target == code) and r.status != "rejected"]


def update_status(candidate_id: int, status: str, path: Path = CANDIDATES_FILE) -> Candidate:
    if status not in CANDIDATE_STATUSES:
        raise ValueError(f"status must be one of {sorted(CANDIDATE_STATUSES)}")
    rows, next_id = load_candidates(path)
    for row in rows:
        if row.id == candidate_id:
            row.status = status
            save_candidates(rows, next_id, path)
            return row
    raise KeyError(f"no candidate with id {candidate_id}")


def approve_candidate(candidate_id: int, relations_path: Path = RELATIONS_FILE,
                       candidates_path: Path = CANDIDATES_FILE) -> Candidate:
    """Move one candidate into the verified graph after explicit approval."""
    rows, next_id = load_candidates(candidates_path)
    selected = next((r for r in rows if r.id == candidate_id), None)
    if selected is None:
        raise KeyError(f"no candidate with id {candidate_id}")
    if selected.status == "rejected":
        raise ValueError("a rejected candidate cannot be approved")
    raw: list[dict[str, Any]] = json.loads(relations_path.read_text(encoding="utf-8"))
    raw.append({
        "source": selected.source, "target": selected.target, "relation": selected.relation,
        "confidence": selected.confidence, "rationale": selected.rationale,
        "sources": selected.sources, "status": "verified", "source_type": selected.source_type,
        "last_checked": date.today().isoformat(), "evidence_text": selected.evidence_text,
    })
    relations_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    selected.status = "approved"
    save_candidates(rows, next_id, candidates_path)
    return selected
