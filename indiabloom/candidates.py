

def approve_many(candidate_ids: list[int], relations_path: Path = RELATIONS_FILE,
                 candidates_path: Path = CANDIDATES_FILE) -> list[Candidate]:
    """Approve a selected group atomically after validating every candidate ID."""
    unique_ids = list(dict.fromkeys(candidate_ids))
    rows, next_id = load_candidates(candidates_path)
    selected = []
    for candidate_id in unique_ids:
        row = next((r for r in rows if r.id == candidate_id), None)
        if row is None:
            raise KeyError(f"no candidate with id {candidate_id}")
        if row.status == "rejected":
            raise ValueError(f"candidate {candidate_id} is rejected")
        selected.append(row)

    raw = json.loads(relations_path.read_text(encoding="utf-8"))
    existing = {(r.get("relation"), r.get("source"), r.get("target")) for r in raw}
    for row in selected:
        key = (row.relation, row.source, row.target)
        if key in existing:
            raise ValueError(f"candidate {row.id} already exists in the verified graph")
        raw.append({
            "source": row.source, "target": row.target, "relation": row.relation,
            "confidence": row.confidence, "rationale": row.rationale,
            "sources": row.sources, "status": "verified", "source_type": row.source_type,
            "last_checked": date.today().isoformat(), "evidence_text": row.evidence_text,
        })
        existing.add(key)

    relations_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    for row in selected:
        row.status = "approved"
    save_candidates(rows, next_id, candidates_path)
    return selected
