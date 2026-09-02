from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any

from .common import new_id, now_iso, sha256_bytes, sha256_file
from .repository import get_repository
from .storage import all_rows, jdump, jload, one, transaction, upsert


def register_release(project_id: str, release_id: str, name: str, release_branch: str = "UNKNOWN", source_ref: str | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    now = now_iso()
    existing = one("SELECT created_at FROM releases WHERE release_id=?", (release_id,))
    record = {
        "release_id": release_id,
        "project_id": project_id,
        "name": name,
        "release_branch": release_branch,
        "status": "OPEN",
        "source_ref": source_ref,
        "created_at": existing["created_at"] if existing else now,
        "updated_at": now,
        "metadata_json": jdump(metadata or {}),
    }
    upsert("releases", ["release_id"], record)
    return release(release_id)


def release(release_id: str) -> dict[str, Any]:
    row = one("SELECT * FROM releases WHERE release_id=?", (release_id,))
    if not row:
        raise KeyError(release_id)
    row["metadata"] = jload(row.pop("metadata_json"), {})
    return row


def register_requirement(project_id: str, release_id: str, requirement_id: str, title: str, *, source_ref: str | None = None, source_hash: str | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    now = now_iso()
    existing = one("SELECT created_at FROM requirements WHERE requirement_id=?", (requirement_id,))
    record = {
        "requirement_id": requirement_id,
        "project_id": project_id,
        "release_id": release_id,
        "title": title,
        "status": "DRAFT" if not existing else (one("SELECT status FROM requirements WHERE requirement_id=?", (requirement_id,)) or {}).get("status", "DRAFT"),
        "source_hash": source_hash,
        "source_ref": source_ref,
        "metadata_json": jdump(metadata or {}),
        "created_at": existing["created_at"] if existing else now,
        "updated_at": now,
    }
    upsert("requirements", ["requirement_id"], record)
    return requirement(requirement_id)


def requirement(requirement_id: str) -> dict[str, Any]:
    row = one("SELECT * FROM requirements WHERE requirement_id=?", (requirement_id,))
    if not row:
        raise KeyError(requirement_id)
    row["metadata"] = jload(row.pop("metadata_json"), {})
    return row


def baseline_requirement(requirement_id: str, reviewer: str, evidence: list[str] | None = None) -> dict[str, Any]:
    now = now_iso()
    with transaction() as conn:
        row = conn.execute("SELECT * FROM requirements WHERE requirement_id=?", (requirement_id,)).fetchone()
        if not row:
            raise KeyError(requirement_id)
        conn.execute("UPDATE requirements SET status='BASELINED', updated_at=? WHERE requirement_id=?", (now, requirement_id))
        gate_id = f"H1-{requirement_id}"
        conn.execute(
            "INSERT INTO gates(gate_id,project_id,release_id,requirement_id,sst_id,gate_type,status,decision,reviewer,evidence_json,reason,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(gate_id) DO UPDATE SET status=excluded.status,decision=excluded.decision,reviewer=excluded.reviewer,evidence_json=excluded.evidence_json,updated_at=excluded.updated_at",
            (gate_id, row["project_id"], row["release_id"], requirement_id, None, "H1", "PASS", "APPROVE", reviewer, jdump(evidence or []), "Requirement baseline approved", now),
        )
    return {"requirement_id": requirement_id, "status": "BASELINED", "gate": "H1", "reviewer": reviewer}


def link_version_sst(release_id: str, sst_id: str, *, relation_type: str = "VERSION_SCOPE", source_ref: str | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    record = {
        "release_id": release_id,
        "sst_id": sst_id,
        "relation_type": relation_type,
        "status": "ACTIVE",
        "source_ref": source_ref,
        "metadata_json": jdump(metadata or {}),
    }
    upsert("version_ssts", ["release_id", "sst_id"], record)
    return record


def link_requirement_sst(
    requirement_id: str,
    sst_id: str,
    *,
    title: str = "",
    owner_system_id: str | None = None,
    implementation_system_id: str | None = None,
    repository_id: str | None = None,
    module_name: str | None = None,
    feature_branch: str = "UNKNOWN",
    release_branch: str = "UNKNOWN",
    commit_range: str | None = None,
    source_ref: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record = {
        "requirement_id": requirement_id,
        "sst_id": sst_id,
        "title": title,
        "owner_system_id": owner_system_id,
        "implementation_system_id": implementation_system_id,
        "repository_id": repository_id,
        "module_name": module_name,
        "feature_branch": feature_branch,
        "release_branch": release_branch,
        "commit_range": commit_range,
        "status": "ACTIVE",
        "source_ref": source_ref,
        "metadata_json": jdump(metadata or {}),
    }
    upsert("requirement_ssts", ["requirement_id", "sst_id"], record)
    return sst(requirement_id, sst_id)


def sst(requirement_id: str, sst_id: str) -> dict[str, Any]:
    row = one("SELECT * FROM requirement_ssts WHERE requirement_id=? AND sst_id=?", (requirement_id, sst_id))
    if not row:
        raise KeyError(f"{requirement_id}/{sst_id}")
    row["metadata"] = jload(row.pop("metadata_json"), {})
    q = one("SELECT * FROM sst_quality_scope WHERE requirement_id=? AND sst_id=?", (requirement_id, sst_id))
    row["quality_scope"] = q or {}
    return row


def set_quality_scope(
    requirement_id: str,
    sst_id: str,
    *,
    performance_required: bool = False,
    performance_status: str | None = None,
    security_requirement_identified: bool = False,
    security_design_review_required: bool = False,
    security_design_review_status: str | None = None,
    security_test_required: bool = False,
    security_test_review_status: str | None = None,
    source_ref: str | None = None,
) -> dict[str, Any]:
    record = {
        "requirement_id": requirement_id,
        "sst_id": sst_id,
        "performance_required": int(performance_required),
        "performance_status": performance_status or ("PENDING" if performance_required else "NOT_REQUIRED"),
        "security_requirement_identified": int(security_requirement_identified),
        "security_design_review_required": int(security_design_review_required),
        "security_design_review_status": security_design_review_status or ("PENDING" if security_design_review_required else "NOT_REQUIRED"),
        "security_test_required": int(security_test_required),
        "security_test_review_status": security_test_review_status or ("PENDING" if security_test_required else "NOT_REQUIRED"),
        "source_ref": source_ref,
        "updated_at": now_iso(),
    }
    upsert("sst_quality_scope", ["requirement_id", "sst_id"], record)
    return record


def add_snapshot(project_id: str, kind: str, source_ref: str, payload: dict[str, Any], *, release_id: str | None = None, requirement_id: str | None = None, valid_until: str | None = None) -> dict[str, Any]:
    raw = jdump(payload).encode("utf-8")
    record = {
        "snapshot_id": new_id("TRUTH"),
        "project_id": project_id,
        "release_id": release_id,
        "requirement_id": requirement_id,
        "kind": kind.upper(),
        "source_ref": source_ref,
        "payload_json": raw.decode("utf-8"),
        "payload_hash": sha256_bytes(raw),
        "observed_at": now_iso(),
        "valid_until": valid_until,
        "status": "CURRENT",
    }
    with transaction() as conn:
        conn.execute(
            "UPDATE truth_snapshots SET status='SUPERSEDED' WHERE project_id=? AND kind=? AND COALESCE(release_id,'')=COALESCE(?, '') AND COALESCE(requirement_id,'')=COALESCE(?, '') AND status='CURRENT'",
            (project_id, kind.upper(), release_id, requirement_id),
        )
        conn.execute(
            "INSERT INTO truth_snapshots(snapshot_id,project_id,release_id,requirement_id,kind,source_ref,payload_json,payload_hash,observed_at,valid_until,status) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            tuple(record.values()),
        )
    return record


def import_submission(project_id: str, release_id: str, payload: dict[str, Any], *, environment_id: str | None = None) -> dict[str, Any]:
    sid = str(payload.get("submission_id") or new_id("SUB"))
    raw = jdump(payload)
    record = {
        "submission_id": sid,
        "project_id": project_id,
        "release_id": release_id,
        "environment_id": environment_id,
        "status": str(payload.get("status") or "UNKNOWN"),
        "payload_json": raw,
        "payload_hash": sha256_bytes(raw.encode()),
        "observed_at": now_iso(),
    }
    upsert("submissions", ["submission_id"], record)
    return {**record, "payload": payload}


def import_deployment(project_id: str, release_id: str, environment_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    did = str(payload.get("deployment_id") or new_id("DEP"))
    raw = jdump(payload)
    record = {
        "deployment_id": did,
        "project_id": project_id,
        "release_id": release_id,
        "environment_id": environment_id,
        "status": str(payload.get("status") or payload.get("deployment_status") or "UNKNOWN"),
        "payload_json": raw,
        "payload_hash": sha256_bytes(raw.encode()),
        "observed_at": now_iso(),
    }
    upsert("deployments", ["deployment_id"], record)
    return {**record, "payload": payload}


def latest_submission(project_id: str, release_id: str) -> dict[str, Any] | None:
    # observed_at is intentionally human-readable to seconds. rowid is the
    # deterministic tiebreaker when two truth refreshes occur in the same
    # second, which is common in an automated preflight/redeploy sequence.
    row = one("SELECT * FROM submissions WHERE project_id=? AND release_id=? ORDER BY observed_at DESC, rowid DESC LIMIT 1", (project_id, release_id))
    if row:
        row["payload"] = jload(row.pop("payload_json"), {})
    return row


def latest_deployment(project_id: str, release_id: str, environment_id: str) -> dict[str, Any] | None:
    row = one("SELECT * FROM deployments WHERE project_id=? AND release_id=? AND environment_id=? ORDER BY observed_at DESC, rowid DESC LIMIT 1", (project_id, release_id, environment_id))
    if row:
        row["payload"] = jload(row.pop("payload_json"), {})
    return row


def _repo_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    items = payload.get("repositories") or payload.get("repos") or []
    return {str(item.get("repository") or item.get("repository_name") or item.get("name")): item for item in items if isinstance(item, dict)}


def reconcile_baseline(project_id: str, release_id: str, requirement_id: str, environment_id: str) -> dict[str, Any]:
    ssts = all_rows("SELECT * FROM requirement_ssts WHERE requirement_id=? AND status='ACTIVE' ORDER BY sst_id", (requirement_id,))
    sub = latest_submission(project_id, release_id)
    dep = latest_deployment(project_id, release_id, environment_id)
    blockers: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    if not sub:
        blockers.append({"code": "SUBMISSION_MISSING"})
    if not dep:
        blockers.append({"code": "DEPLOYMENT_MISSING"})
    successful = {"SUCCESS", "SUCCEEDED", "DEPLOYED", "READY", "COMPLETED", "PASS"}
    if sub and str(sub.get("status") or "").upper() not in successful:
        blockers.append({"code": "SUBMISSION_STATUS_NOT_SUCCESSFUL", "status": sub.get("status")})
    if dep and str(dep.get("status") or "").upper() not in successful:
        blockers.append({"code": "DEPLOYMENT_STATUS_NOT_SUCCESSFUL", "status": dep.get("status")})
    max_age_minutes = 120
    env_row = one("SELECT config_json FROM environments WHERE project_id=? AND environment_id=?", (project_id, environment_id))
    if env_row:
        try:
            max_age_minutes = int((jload(env_row.get("config_json"), {}) or {}).get("truth_max_age_minutes") or 120)
        except (TypeError, ValueError):
            max_age_minutes = 120
    now = dt.datetime.now(dt.timezone.utc)
    for label, record in (("SUBMISSION", sub), ("DEPLOYMENT", dep)):
        if record and record.get("observed_at"):
            try:
                observed = dt.datetime.fromisoformat(str(record["observed_at"]).replace("Z", "+00:00"))
                if observed.tzinfo is None:
                    observed = observed.replace(tzinfo=dt.timezone.utc)
                age = (now - observed.astimezone(dt.timezone.utc)).total_seconds() / 60
                if age > max_age_minutes:
                    blockers.append({"code": f"{label}_QUERY_STALE", "age_minutes": round(age, 1), "max_age_minutes": max_age_minutes})
            except ValueError:
                blockers.append({"code": f"{label}_OBSERVED_AT_INVALID"})
    sub_payload = (sub or {}).get("payload") or {}
    dep_payload = (dep or {}).get("payload") or {}
    sub_map = _repo_map(sub_payload)
    dep_map = _repo_map(dep_payload)
    top_sub_build = sub_payload.get("build_id")
    top_dep_build = dep_payload.get("build_id")
    if top_sub_build and top_dep_build and top_sub_build != top_dep_build:
        blockers.append({"code": "TOP_LEVEL_BUILD_ID_MISMATCH", "submission": top_sub_build, "deployment": top_dep_build})
    for s in ssts:
        repo_id = s.get("repository_id")
        repo = get_repository(repo_id) if repo_id else None
        repo_name = (repo or {}).get("full_name") or "UNKNOWN"
        submitted = sub_map.get(repo_name)
        deployed = dep_map.get(repo_name)
        item_blockers = []
        if not repo:
            item_blockers.append("REPOSITORY_NOT_REGISTERED")
        if not submitted:
            item_blockers.append("SUBMISSION_MISSING_REPOSITORY")
        if not deployed:
            item_blockers.append("DEPLOYMENT_MISSING_REPOSITORY")
        local_head = (repo or {}).get("head_sha")
        sub_commit = (submitted or {}).get("commit") or (submitted or {}).get("head_sha")
        dep_commit = (deployed or {}).get("commit") or (deployed or {}).get("head_sha")
        if submitted and deployed and sub_commit and dep_commit and sub_commit != dep_commit:
            item_blockers.append("SUBMISSION_DEPLOYMENT_COMMIT_MISMATCH")
        if repo and dep_commit and local_head != dep_commit:
            item_blockers.append("LOCAL_HEAD_DIFFERS_DEPLOYED_COMMIT")
        sub_build = (submitted or {}).get("build_id")
        dep_build = (deployed or {}).get("build_id")
        if submitted and deployed and sub_build and dep_build and sub_build != dep_build:
            item_blockers.append("BUILD_ID_MISMATCH")
        rows.append({
            "sst_id": s["sst_id"],
            "repository_id": repo_id,
            "repository": repo_name,
            "expected": {"feature_branch": s.get("feature_branch"), "release_branch": s.get("release_branch"), "commit_range": s.get("commit_range")},
            "local": {"branch": (repo or {}).get("current_branch"), "commit": local_head},
            "submission": submitted,
            "deployment": deployed,
            "blockers": item_blockers,
        })
        blockers.extend({"code": code, "sst_id": s["sst_id"], "repository": repo_name} for code in item_blockers)
    quality = all_rows("SELECT * FROM sst_quality_scope WHERE requirement_id=?", (requirement_id,))
    for q in quality:
        if q["performance_required"] and q["performance_status"] not in {"APPROVED", "PASS", "READY"}:
            blockers.append({"code": "PERFORMANCE_SCOPE_NOT_READY", "sst_id": q["sst_id"]})
        if q["security_design_review_required"] and q["security_design_review_status"] not in {"APPROVED", "PASS"}:
            blockers.append({"code": "SECURITY_DESIGN_REVIEW_NOT_READY", "sst_id": q["sst_id"]})
        if q["security_test_required"] and q["security_test_review_status"] not in {"APPROVED", "PASS", "READY"}:
            blockers.append({"code": "SECURITY_TEST_REVIEW_NOT_READY", "sst_id": q["sst_id"]})
    fingerprint_payload = {
        "project_id": project_id,
        "release_id": release_id,
        "requirement_id": requirement_id,
        "environment_id": environment_id,
        "rows": rows,
        "submission_hash": (sub or {}).get("payload_hash"),
        "deployment_hash": (dep or {}).get("payload_hash"),
    }
    fingerprint = sha256_bytes(jdump(fingerprint_payload).encode())
    return {"ok": not blockers, "status": "BASELINE_READY" if not blockers else "BASELINE_BLOCKED", "fingerprint": fingerprint, "rows": rows, "blockers": blockers}


def gate_set(project_id: str, gate_type: str, status: str, *, release_id: str | None = None, requirement_id: str | None = None, sst_id: str | None = None, decision: str | None = None, reviewer: str | None = None, evidence: list[str] | None = None, reason: str | None = None) -> dict[str, Any]:
    key = "-".join(filter(None, [gate_type.upper(), requirement_id, sst_id, release_id]))
    record = {
        "gate_id": key,
        "project_id": project_id,
        "release_id": release_id,
        "requirement_id": requirement_id,
        "sst_id": sst_id,
        "gate_type": gate_type.upper(),
        "status": status.upper(),
        "decision": decision,
        "reviewer": reviewer,
        "evidence_json": jdump(evidence or []),
        "reason": reason,
        "updated_at": now_iso(),
    }
    upsert("gates", ["gate_id"], record)
    record["evidence"] = evidence or []
    return record


def gate_status(requirement_id: str, gate_type: str, *, sst_id: str | None = None) -> dict[str, Any] | None:
    row = one("SELECT * FROM gates WHERE requirement_id=? AND gate_type=? AND COALESCE(sst_id,'')=COALESCE(?, '') ORDER BY updated_at DESC LIMIT 1", (requirement_id, gate_type.upper(), sst_id))
    if row:
        row["evidence"] = jload(row.pop("evidence_json"), [])
    return row
