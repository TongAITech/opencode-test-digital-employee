"""Fail-closed Bank Field Reality provenance gate for RC7.1.

Controlled Engineering evidence may use fixtures.  Bank Field qualification may not.
This gate only accepts current Mission/EXECUTION/Target receipts that were emitted
by the runtime-owned bank field service probe path and that reference explicitly
trusted runtime protocols.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from rc6_runtime.truth import TruthRuntime

from .bank_field_services import (
    CAP_AUTH_4A,
    CAP_CAT,
    CAP_DB_READ,
    CAP_DB_WRITE,
    PROBE_KIND,
    REQUIRED_CAPABILITIES,
)


SCHEMA_VERSION = "pfc.aitest.rc7.bank-field-reality-gate.v1"

FORBIDDEN_SOURCE_PREFIXES: Tuple[str, ...] = (
    "engineering-fixture://",
    "fixture://",
    "mock://",
    "synthetic://",
    "test://",
    "migration://",
)

TRUSTED_TOOL_PREFIXES: Tuple[str, ...] = (
    "field-tool://",
    "dsh://",
    "mcp://",
    "browser://",
    "playwright://",
    "junit://",
    "pytest://",
    "api://",
    "db://",
    "cat://",
    "k6://",
    "zap://",
)

TRUSTED_EVIDENCE_PREFIXES: Tuple[str, ...] = (
    "field-evidence://",
    "evidence://",
    "r1://",
    "state://",
    "4a-evidence://",
    "cat-evidence://",
    "db-evidence://",
    "execution-evidence://",
)


def _probe_attempt_id(mission_id: str, target_id: str) -> str:
    return "BANK-FIELD-PROBE-" + hashlib.sha256(
        (mission_id + "\x1f" + target_id).encode("utf-8")
    ).hexdigest()[:20]


def _as_refs(row: Mapping[str, Any]) -> List[str]:
    return [
        str(value).strip()
        for value in list(row.get("subject_refs") or [])
        if isinstance(value, str) and value.strip()
    ]


def _has_prefix(value: str, prefixes: Sequence[str]) -> bool:
    return any(value.startswith(prefix) for prefix in prefixes)


def _forbidden_ref(values: Sequence[str]) -> str:
    for value in values:
        if _has_prefix(value, FORBIDDEN_SOURCE_PREFIXES):
            return value
    return ""


def _trusted_runtime_refs(refs: Sequence[str]) -> Tuple[List[str], List[str]]:
    tools = sorted({ref for ref in refs if _has_prefix(ref, TRUSTED_TOOL_PREFIXES)})
    evidence = sorted({ref for ref in refs if _has_prefix(ref, TRUSTED_EVIDENCE_PREFIXES)})
    return tools, evidence


def evaluate_bank_field_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    mission_id: str,
    execution_task_id: str,
    execution_updated_at: int,
    target_id: str,
    source_commit: str,
) -> Dict[str, Any]:
    """Validate the exact receipts allowed to support Bank Field Reality.

    Presence of engineering fixture evidence elsewhere in the Mission is not a
    failure.  A fixture only becomes a blocker when it attempts to occupy one
    of the authoritative BANK_FIELD_SERVICE_PROBE slots.
    """
    blockers: List[str] = []
    trusted: Dict[str, Dict[str, Any]] = {}
    expected_attempt = _probe_attempt_id(mission_id, target_id)

    if not mission_id:
        blockers.append("BANK_FIELD_MISSION_ID_REQUIRED")
    if not execution_task_id:
        blockers.append("BANK_FIELD_EXECUTION_TASK_ID_REQUIRED")
    if not target_id:
        blockers.append("BANK_FIELD_TARGET_ID_REQUIRED")
    if not source_commit:
        blockers.append("BANK_FIELD_SOURCE_COMMIT_REQUIRED")
    if not isinstance(execution_updated_at, int) or execution_updated_at <= 0:
        blockers.append("BANK_FIELD_EXECUTION_UPDATED_AT_REQUIRED")

    for capability in REQUIRED_CAPABILITIES:
        candidates = [
            row
            for row in rows
            if row.get("kind") == PROBE_KIND
            and capability in _as_refs(row)
        ]
        if len(candidates) != 1:
            blockers.append(
                "BANK_FIELD_REALITY_PROBE_NOT_UNIQUE:%s:%d"
                % (capability, len(candidates))
            )
            continue

        row = candidates[0]
        evidence_id = str(row.get("evidence_id") or "").strip()
        source_ref = str(row.get("source_ref") or "").strip()
        content_ref = str(row.get("content_ref") or "").strip()
        row_mission = str(row.get("mission_id") or "").strip()
        refs = _as_refs(row)
        created_at = row.get("created_at")

        forbidden = _forbidden_ref([source_ref, content_ref] + refs)
        if forbidden:
            blockers.append(
                "BANK_FIELD_FORBIDDEN_EVIDENCE_SOURCE:%s:%s"
                % (capability, forbidden.split("://", 1)[0])
            )
            continue

        if row_mission != mission_id:
            blockers.append("BANK_FIELD_REALITY_MISSION_MISMATCH:%s" % capability)
            continue
        if not evidence_id.startswith("EVD-BANK-SVC-"):
            blockers.append("BANK_FIELD_REALITY_EVIDENCE_ID_INVALID:%s" % capability)
            continue
        if not source_ref.startswith("provider://"):
            blockers.append("BANK_FIELD_REALITY_PROVIDER_SOURCE_REQUIRED:%s" % capability)
            continue
        if not source_ref.endswith("/" + capability):
            blockers.append("BANK_FIELD_REALITY_PROVIDER_CAPABILITY_MISMATCH:%s" % capability)
            continue
        if not content_ref.startswith("state://bank-field-services/"):
            blockers.append("BANK_FIELD_REALITY_RUNTIME_CONTENT_REQUIRED:%s" % capability)
            continue
        if execution_task_id not in refs:
            blockers.append("BANK_FIELD_REALITY_TASK_MISMATCH:%s" % capability)
            continue
        if target_id not in refs:
            blockers.append("BANK_FIELD_REALITY_TARGET_MISMATCH:%s" % capability)
            continue
        if expected_attempt not in refs:
            blockers.append("BANK_FIELD_REALITY_ATTEMPT_MISMATCH:%s" % capability)
            continue
        if not any(ref.startswith("provider:") for ref in refs):
            blockers.append("BANK_FIELD_REALITY_PROVIDER_IDENTITY_MISSING:%s" % capability)
            continue
        if not isinstance(created_at, int) or created_at < execution_updated_at:
            blockers.append("BANK_FIELD_REALITY_STALE_EVIDENCE:%s" % capability)
            continue

        tool_refs, evidence_refs = _trusted_runtime_refs(refs)
        if not tool_refs:
            blockers.append("BANK_FIELD_REALITY_TRUSTED_TOOL_REF_MISSING:%s" % capability)
            continue
        if not evidence_refs:
            blockers.append("BANK_FIELD_REALITY_TRUSTED_EVIDENCE_REF_MISSING:%s" % capability)
            continue

        if capability == CAP_DB_WRITE:
            approvals = [ref for ref in refs if ref.startswith("EVD-HGAPP-")]
            if len(approvals) != 1:
                blockers.append("BANK_FIELD_REALITY_DB_WRITE_APPROVAL_REQUIRED")
                continue

        trusted[capability] = {
            "evidence_id": evidence_id,
            "source_ref": source_ref,
            "content_ref": content_ref,
            "created_at": created_at,
            "tool_refs": tool_refs,
            "evidence_refs": evidence_refs,
        }

    deduped: List[str] = []
    for blocker in blockers:
        if blocker not in deduped:
            deduped.append(blocker)

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS" if not deduped else "HOLD",
        "qualification_kind": "BANK_FIELD_REALITY_RUNTIME_PROVENANCE",
        "mission_id": mission_id,
        "execution_task_id": execution_task_id,
        "execution_updated_at": execution_updated_at,
        "target_id": target_id,
        "source_commit": source_commit,
        "expected_probe_attempt_id": expected_attempt,
        "trusted_capabilities": trusted,
        "blocking_reasons": deduped,
    }


def evaluate_bank_field_reality(
    truth: TruthRuntime,
    *,
    mission_id: str,
    execution_task_id: str,
    target_id: str,
    source_commit: str,
) -> Dict[str, Any]:
    task_rows = [
        row
        for row in truth.query("rc7_task", task_id=execution_task_id)
        if row.get("mission_id") == mission_id and row.get("node") == "EXECUTION"
    ]
    if len(task_rows) != 1:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "HOLD",
            "qualification_kind": "BANK_FIELD_REALITY_RUNTIME_PROVENANCE",
            "mission_id": mission_id,
            "execution_task_id": execution_task_id,
            "target_id": target_id,
            "source_commit": source_commit,
            "trusted_capabilities": {},
            "blocking_reasons": [
                "BANK_FIELD_REALITY_EXECUTION_TASK_NOT_UNIQUE:%d" % len(task_rows)
            ],
        }

    execution_updated_at = task_rows[0].get("updated_at")
    rows = list(truth.query("rc7_evidence", mission_id=mission_id))
    return evaluate_bank_field_rows(
        rows,
        mission_id=mission_id,
        execution_task_id=execution_task_id,
        execution_updated_at=execution_updated_at,
        target_id=target_id,
        source_commit=source_commit,
    )
