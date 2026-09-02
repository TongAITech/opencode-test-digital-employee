from __future__ import annotations

from typing import Any

from .common import new_id, now_iso
from .storage import all_rows, jdump, jload, one, transaction

VALID_STATUS = {"CANDIDATE", "VERIFIED", "INVALIDATED", "SUPERSEDED"}
VALID_CONFIDENCE = {"LOW", "MEDIUM", "HIGH"}


def create_candidate(
    project_id: str,
    subject: str,
    predicate: str,
    obj: Any,
    *,
    scope: dict[str, Any] | None = None,
    source_type: str = "OBSERVATION",
    source_ref: str = "runtime",
    confidence: str = "MEDIUM",
    valid_from: str | None = None,
    valid_to: str | None = None,
) -> dict[str, Any]:
    confidence = confidence.upper()
    if confidence not in VALID_CONFIDENCE:
        raise ValueError(confidence)
    kid = new_id("KNOW")
    with transaction() as conn:
        conn.execute(
            "INSERT INTO knowledge_records(knowledge_id,project_id,subject,predicate,object_json,scope_json,source_type,source_ref,confidence,status,valid_from,valid_to,reviewed_by,reviewed_at,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (kid, project_id, subject, predicate, jdump(obj), jdump(scope or {}), source_type.upper(), source_ref, confidence, "CANDIDATE", valid_from, valid_to, None, None, now_iso()),
        )
    return get(kid)


def get(knowledge_id: str) -> dict[str, Any]:
    row = one("SELECT * FROM knowledge_records WHERE knowledge_id=?", (knowledge_id,))
    if not row:
        raise KeyError(knowledge_id)
    row["object"] = jload(row.pop("object_json"), None)
    row["scope"] = jload(row.pop("scope_json"), {})
    return row


def list_records(project_id: str, *, status: str | None = None, subject: str | None = None) -> list[dict[str, Any]]:
    sql = "SELECT * FROM knowledge_records WHERE project_id=?"
    params: list[Any] = [project_id]
    if status:
        sql += " AND status=?"
        params.append(status.upper())
    if subject:
        sql += " AND subject=?"
        params.append(subject)
    sql += " ORDER BY created_at DESC"
    rows = all_rows(sql, params)
    for row in rows:
        row["object"] = jload(row.pop("object_json"), None)
        row["scope"] = jload(row.pop("scope_json"), {})
    return rows


def verify(knowledge_id: str, reviewer: str, *, confidence: str = "HIGH") -> dict[str, Any]:
    confidence = confidence.upper()
    if confidence not in VALID_CONFIDENCE:
        raise ValueError(confidence)
    record = get(knowledge_id)
    if record["status"] not in {"CANDIDATE", "VERIFIED"}:
        raise ValueError(f"knowledge cannot be verified from {record['status']}")
    # Invalidate conflicting verified facts only inside the same exact scope.
    with transaction() as conn:
        conn.execute(
            "UPDATE knowledge_records SET status='SUPERSEDED' WHERE project_id=? AND subject=? AND predicate=? AND scope_json=? AND status='VERIFIED' AND knowledge_id<>?",
            (record["project_id"], record["subject"], record["predicate"], jdump(record["scope"]), knowledge_id),
        )
        conn.execute(
            "UPDATE knowledge_records SET status='VERIFIED',confidence=?,reviewed_by=?,reviewed_at=? WHERE knowledge_id=?",
            (confidence, reviewer, now_iso(), knowledge_id),
        )
    return get(knowledge_id)


def invalidate(knowledge_id: str, reviewer: str, reason: str) -> dict[str, Any]:
    record = get(knowledge_id)
    obj = record["object"]
    if isinstance(obj, dict):
        obj = {**obj, "invalidation_reason": reason}
    else:
        obj = {"value": obj, "invalidation_reason": reason}
    with transaction() as conn:
        conn.execute(
            "UPDATE knowledge_records SET status='INVALIDATED',object_json=?,reviewed_by=?,reviewed_at=? WHERE knowledge_id=?",
            (jdump(obj), reviewer, now_iso(), knowledge_id),
        )
    return get(knowledge_id)


def resolve(
    project_id: str,
    *,
    subject: str | None = None,
    predicate: str | None = None,
    context: dict[str, Any] | None = None,
    include_candidates: bool = False,
) -> list[dict[str, Any]]:
    statuses = ["VERIFIED"] + (["CANDIDATE"] if include_candidates else [])
    sql = "SELECT * FROM knowledge_records WHERE project_id=? AND status IN (" + ",".join("?" for _ in statuses) + ")"
    params: list[Any] = [project_id, *statuses]
    if subject:
        sql += " AND subject=?"
        params.append(subject)
    if predicate:
        sql += " AND predicate=?"
        params.append(predicate)
    sql += " ORDER BY CASE confidence WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 ELSE 3 END, reviewed_at DESC, created_at DESC"
    rows = all_rows(sql, params)
    context = context or {}
    result = []
    for row in rows:
        scope = jload(row.pop("scope_json"), {})
        # Every scoped key must match the current context. Global records have empty scope.
        if any(context.get(k) != v for k, v in scope.items() if v not in (None, "", "*")):
            continue
        row["scope"] = scope
        row["object"] = jload(row.pop("object_json"), None)
        result.append(row)
    return result
