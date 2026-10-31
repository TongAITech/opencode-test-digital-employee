"""RC7.2 N5 data-discovery raw DSH evidence anchor.

A successful DATA_PREPARER handoff proves that one governed fresh DSH worker
ran and returned a strict raw candidate.  It does not prove that the candidate
is valid test data.  This layer replays the exact JSONL, proves session/tool/
candidate lineage, and binds the raw bytes with SHA-256 before any semantic
promotion is allowed.

The anchor is integrity truth only: it creates no DataRef, binding, DataLease,
verification, N5 PASS, N6 release, field status, or BANK_FINAL claim.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Mapping, Tuple

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc6_runtime.truth import TruthRuntime

from .models import ContractError
from .rc72_n5_data_discovery_handoff import (
    N5DataDiscoveryDshHandoffService,
    N5DataDiscoveryHandoffError,
    install_rc72_n5_data_discovery_handoff_overlay,
)
from .truth_overlay import install_rc7_truth_overlay


_ARTIFACT = "rc72_n5_data_discovery_evidence_anchor"
_EVENT = "RC72_N5_DATA_DISCOVERY_EVIDENCE_ANCHOR_UPSERTED"
_BUCKET = "rc72_n5_data_discovery_evidence_anchors"
_CANDIDATE_SCHEMA = "RC72_N5_DATA_DISCOVERY_CANDIDATE_V1"
_ATTEMPT_STATE = "WORKER_COMPLETED_PENDING_RAW_ANCHOR"
_HANDOFF_STATUS = "DSH_SESSION_OBSERVED"
_PROCESS_OUTCOME = "SUCCEEDED"
_INSTALLED = False


class N5DataDiscoveryEvidenceAnchorError(ContractError):
    pass


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise N5DataDiscoveryEvidenceAnchorError(
            "RC72_N5_DISCOVERY_ANCHOR_%s_REQUIRED" % name.upper()
        )
    return value.strip()


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:24])


def _sha256(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def validate_rc72_n5_data_discovery_evidence_anchor(
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "anchor_id", "release_id", "mission_id", "release_batch_id",
        "source_commit", "data_requirement_id", "resolution_plan_id",
        "source_case_sha256", "requirement_id", "sst_id", "obligation_id",
        "case_id", "attempt_id", "assignment_id", "dispatch_id",
        "mission_node_id", "workitem_id", "worker_instance_id",
        "dsh_session_id", "candidate_output_ref", "raw_output_ref",
        "raw_output_sha256", "candidate_schema",
    ):
        out[name] = _contracts._require_str(out, name)
    if not out["source_case_sha256"].startswith("sha256:"):
        raise _contracts.DomainValidationError(
            "RC72_N5_DISCOVERY_ANCHOR_CASE_HASH_INVALID"
        )
    if not out["dsh_session_id"].startswith("session-"):
        raise _contracts.DomainValidationError(
            "RC72_N5_DISCOVERY_ANCHOR_DSH_SESSION_INVALID"
        )
    if not out["raw_output_ref"].startswith("file://"):
        raise _contracts.DomainValidationError(
            "RC72_N5_DISCOVERY_ANCHOR_RAW_OUTPUT_REF_INVALID"
        )
    if (
        not out["raw_output_sha256"].startswith("sha256:")
        or len(out["raw_output_sha256"]) != 71
    ):
        raise _contracts.DomainValidationError(
            "RC72_N5_DISCOVERY_ANCHOR_RAW_OUTPUT_SHA256_INVALID"
        )
    if out["candidate_schema"] != _CANDIDATE_SCHEMA:
        raise _contracts.DomainValidationError(
            "RC72_N5_DISCOVERY_ANCHOR_CANDIDATE_SCHEMA_INVALID"
        )
    value = out.get("created_at")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _contracts.DomainValidationError(
            "RC72_N5_DISCOVERY_ANCHOR_CREATED_AT_INVALID"
        )
    for forbidden in (
        "semantic_payload", "strategy", "observations", "verification_plan",
        "unknowns", "gaps", "data_ref", "binding_id", "verification",
        "verified", "resource_metadata_ref", "reserved", "data_lease_id",
        "node_delivery_id", "node_gate", "node_gate_id", "node_pass",
        "n5_pass", "n6_ready", "q7_pass", "field_verified", "bank_final",
    ):
        if forbidden in out:
            raise _contracts.DomainValidationError(
                "RC72_N5_DISCOVERY_ANCHOR_DATA_TRUTH_CLAIM_FORBIDDEN:%s"
                % forbidden
            )
    version = out.get("artifact_version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError(
            "RC72_N5_DISCOVERY_ANCHOR_ARTIFACT_VERSION_INVALID"
        )
    out["artifact_version"] = version
    out["artifact_type"] = _ARTIFACT
    return out


def install_rc72_n5_data_discovery_anchor_overlay() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    install_rc7_truth_overlay()
    install_rc72_n5_data_discovery_handoff_overlay()
    _contracts.VALIDATORS[_ARTIFACT] = validate_rc72_n5_data_discovery_evidence_anchor
    _truth.BUCKETS[_ARTIFACT] = _BUCKET
    _truth.IDENTITY_FIELDS[_ARTIFACT] = "anchor_id"
    _truth.EVENT_TYPES[_EVENT] = (_ARTIFACT, "anchor_id")
    _INSTALLED = True


def _ensure_bucket(truth: TruthRuntime) -> None:
    projection = getattr(truth, "projection", None)
    if projection is None:
        return
    if not hasattr(projection, _BUCKET):
        setattr(projection, _BUCKET, {})
    versions = getattr(projection, "_versions", None)
    if isinstance(versions, dict):
        versions.setdefault(_ARTIFACT, {})


def _strict_final_json(events: Tuple[Dict[str, Any], ...]) -> Dict[str, Any]:
    finals = [
        event for event in events
        if str(event.get("type") or event.get("event") or event.get("kind") or "").lower()
        == "final"
    ]
    if len(finals) != 1:
        raise N5DataDiscoveryEvidenceAnchorError(
            "RC72_N5_DISCOVERY_ANCHOR_FINAL_EVENT_NOT_UNIQUE:%d" % len(finals)
        )
    value = finals[0].get("text")
    if not isinstance(value, str) or not value.strip():
        raise N5DataDiscoveryEvidenceAnchorError(
            "RC72_N5_DISCOVERY_ANCHOR_FINAL_TEXT_REQUIRED"
        )
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise N5DataDiscoveryEvidenceAnchorError(
            "RC72_N5_DISCOVERY_ANCHOR_FINAL_JSON_INVALID"
        ) from exc
    if not isinstance(parsed, dict):
        raise N5DataDiscoveryEvidenceAnchorError(
            "RC72_N5_DISCOVERY_ANCHOR_FINAL_OBJECT_REQUIRED"
        )
    return parsed


class N5DataDiscoveryEvidenceAnchorService:
    """Hash-anchor one successful N5 DATA_PREPARER DSH Attempt."""

    def __init__(
        self,
        truth: TruthRuntime,
        *,
        source_commit: str,
        state_root: str,
    ) -> None:
        install_rc72_n5_data_discovery_anchor_overlay()
        _ensure_bucket(truth)
        self.truth = truth
        self.source_commit = _required(source_commit, "source_commit")
        self.state_root = Path(_required(state_root, "state_root")).expanduser().resolve()

    @staticmethod
    def _anchor_id(attempt_id: str) -> str:
        return _stable_id("N5DATAANCH", attempt_id, "DSH_RAW_OUTPUT")

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise N5DataDiscoveryEvidenceAnchorError(
                "RC72_N5_DISCOVERY_ANCHOR_TRUTH_NOT_UNIQUE:%s:%d"
                % (artifact_type, len(rows))
            )
        return rows[0]

    def _attempt(
        self, release_batch_id: str, data_requirement_id: str
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        exact = [
            row for row in self.truth.query(
                "rc72_n5_data_discovery_attempt", release_batch_id=release_batch_id
            )
            if row.get("source_commit") == self.source_commit
            and row.get("data_requirement_id") == data_requirement_id
            and row.get("state") == _ATTEMPT_STATE
            and row.get("handoff_status") == _HANDOFF_STATUS
            and row.get("process_outcome") == _PROCESS_OUTCOME
            and row.get("candidate_schema") == _CANDIDATE_SCHEMA
        ]
        if len(exact) != 1:
            raise N5DataDiscoveryEvidenceAnchorError(
                "RC72_N5_DISCOVERY_ANCHOR_EXACT_ATTEMPT_REQUIRED:%d" % len(exact)
            )
        attempt = exact[0]
        assignment = self._one(
            "rc72_n5_data_discovery_assignment",
            assignment_id=str(attempt["assignment_id"]),
        )
        immutable = (
            "release_id", "mission_id", "release_batch_id", "source_commit",
            "mission_node_id", "data_requirement_id", "resolution_plan_id",
            "source_case_sha256", "requirement_id", "sst_id", "obligation_id",
            "case_id", "dispatch_id", "workitem_id", "worker_instance_id",
        )
        for field in immutable:
            if assignment.get(field) != attempt.get(field):
                raise N5DataDiscoveryEvidenceAnchorError(
                    "RC72_N5_DISCOVERY_ANCHOR_ASSIGNMENT_LINEAGE_MISMATCH:%s"
                    % field
                )
        return attempt, assignment

    def _raw_candidate(
        self,
        attempt: Mapping[str, Any],
        assignment: Mapping[str, Any],
    ) -> Tuple[Dict[str, Any], str, str, Tuple[Dict[str, Any], ...]]:
        file_refs = [
            ref for ref in list(attempt.get("runtime_evidence_refs") or [])
            if isinstance(ref, str) and ref.startswith("file://")
        ]
        if len(file_refs) != 1:
            raise N5DataDiscoveryEvidenceAnchorError(
                "RC72_N5_DISCOVERY_ANCHOR_RAW_DSH_EVIDENCE_REQUIRED:%d"
                % len(file_refs)
            )
        content_ref = file_refs[0]
        path = Path(content_ref[len("file://"):]).expanduser().resolve()
        try:
            path.relative_to(self.state_root)
        except ValueError as exc:
            raise N5DataDiscoveryEvidenceAnchorError(
                "RC72_N5_DISCOVERY_ANCHOR_RAW_EVIDENCE_OUTSIDE_STATE_ROOT"
            ) from exc
        if not path.is_file():
            raise N5DataDiscoveryEvidenceAnchorError(
                "RC72_N5_DISCOVERY_ANCHOR_RAW_EVIDENCE_NOT_FOUND"
            )
        raw = path.read_bytes()
        if not raw:
            raise N5DataDiscoveryEvidenceAnchorError(
                "RC72_N5_DISCOVERY_ANCHOR_RAW_EVIDENCE_EMPTY"
            )
        raw_hash = _sha256(raw)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise N5DataDiscoveryEvidenceAnchorError(
                "RC72_N5_DISCOVERY_ANCHOR_RAW_EVIDENCE_NOT_UTF8"
            ) from exc
        events = tuple(DshHeadlessWorkerLauncher._parse_json_lines(text))
        if not events:
            raise N5DataDiscoveryEvidenceAnchorError(
                "RC72_N5_DISCOVERY_ANCHOR_RAW_EVENTS_REQUIRED"
            )
        if DshHeadlessWorkerLauncher._session_id(events) != attempt.get("dsh_session_id"):
            raise N5DataDiscoveryEvidenceAnchorError(
                "RC72_N5_DISCOVERY_ANCHOR_DSH_SESSION_MISMATCH"
            )
        parsed_calls = tuple(DshHeadlessWorkerLauncher._tool_calls(events))
        observed_calls = tuple(
            {
                "call_ref": str(item.get("call_ref") or ""),
                "tool_name": str(item.get("tool_name") or ""),
            }
            for item in list(attempt.get("observed_tool_calls") or [])
        )
        if parsed_calls != observed_calls:
            raise N5DataDiscoveryEvidenceAnchorError(
                "RC72_N5_DISCOVERY_ANCHOR_TOOL_CALL_EVIDENCE_MISMATCH"
            )
        candidate = _strict_final_json(events)
        try:
            normalized = N5DataDiscoveryDshHandoffService._validate_candidate(
                candidate, assignment
            )
        except N5DataDiscoveryHandoffError as exc:
            raise N5DataDiscoveryEvidenceAnchorError(str(exc)) from exc
        return normalized, content_ref, raw_hash, parsed_calls

    def anchor(
        self, *, release_batch_id: str, data_requirement_id: str
    ) -> Dict[str, Any]:
        release_batch_id = _required(release_batch_id, "release_batch_id")
        data_requirement_id = _required(data_requirement_id, "data_requirement_id")
        attempt, assignment = self._attempt(release_batch_id, data_requirement_id)
        _candidate, content_ref, raw_hash, _calls = self._raw_candidate(
            attempt, assignment
        )
        anchor_id = self._anchor_id(str(attempt["attempt_id"]))
        expected = {
            "release_id": attempt.get("release_id"),
            "mission_id": attempt.get("mission_id"),
            "release_batch_id": attempt.get("release_batch_id"),
            "source_commit": self.source_commit,
            "data_requirement_id": data_requirement_id,
            "resolution_plan_id": attempt.get("resolution_plan_id"),
            "source_case_sha256": attempt.get("source_case_sha256"),
            "requirement_id": attempt.get("requirement_id"),
            "sst_id": attempt.get("sst_id"),
            "obligation_id": attempt.get("obligation_id"),
            "case_id": attempt.get("case_id"),
            "attempt_id": attempt.get("attempt_id"),
            "assignment_id": attempt.get("assignment_id"),
            "dispatch_id": attempt.get("dispatch_id"),
            "mission_node_id": attempt.get("mission_node_id"),
            "workitem_id": attempt.get("workitem_id"),
            "worker_instance_id": attempt.get("worker_instance_id"),
            "dsh_session_id": attempt.get("dsh_session_id"),
            "candidate_output_ref": attempt.get("candidate_output_ref"),
            "raw_output_ref": content_ref,
            "raw_output_sha256": raw_hash,
            "candidate_schema": _CANDIDATE_SCHEMA,
        }
        existing = self.truth.query(_ARTIFACT, anchor_id=anchor_id)
        if existing:
            if len(existing) != 1:
                raise N5DataDiscoveryEvidenceAnchorError(
                    "RC72_N5_DISCOVERY_ANCHOR_NOT_UNIQUE"
                )
            for key, value in expected.items():
                if existing[0].get(key) != value:
                    raise N5DataDiscoveryEvidenceAnchorError(
                        "RC72_N5_DISCOVERY_ANCHOR_CONFLICT:%s" % key
                    )
            return dict(existing[0])
        payload = dict(expected)
        payload.update(
            {
                "anchor_id": anchor_id,
                "created_at": int(
                    attempt.get("updated_at") or attempt.get("created_at") or 0
                ),
                "artifact_version": 1,
            }
        )
        self.truth.append_atomic(_EVENT, payload)
        rows = self.truth.query(_ARTIFACT, anchor_id=anchor_id)
        if len(rows) != 1:
            raise N5DataDiscoveryEvidenceAnchorError(
                "RC72_N5_DISCOVERY_ANCHOR_PERSISTENCE_FAILED"
            )
        return rows[0]


install_rc72_n5_data_discovery_anchor_overlay()

__all__ = [
    "N5DataDiscoveryEvidenceAnchorError",
    "N5DataDiscoveryEvidenceAnchorService",
    "install_rc72_n5_data_discovery_anchor_overlay",
    "validate_rc72_n5_data_discovery_evidence_anchor",
]
