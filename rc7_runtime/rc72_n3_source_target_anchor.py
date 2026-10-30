"""RC7.2 N3 source-target DSH raw-evidence anchor.

The N3 handoff proves a fresh worker/session/tool execution happened and stores
only execution/evidence Attempt truth. This layer immediately binds that
Attempt to the exact raw DSH JSONL bytes with SHA-256 after replaying session,
tool-call and strict top-level candidate contracts.

The anchor is integrity truth only. It does not accept repository/revision
mapping, create canonical source targets, create CODE_ANALYSIS WorkItems,
decide N3 PASS, release N4, or claim field/BANK_FINAL status.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, Mapping, Tuple

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc6_runtime.truth import TruthRuntime

from .models import ContractError
from .rc72_n3_source_target_handoff import (
    N3SourceTargetDshHandoffService,
    N3SourceTargetHandoffError,
    install_rc72_n3_source_target_handoff_overlay,
)
from .truth_overlay import install_rc7_truth_overlay


_ARTIFACT = "rc72_n3_dsh_evidence_anchor"
_EVENT = "RC72_N3_DSH_EVIDENCE_ANCHOR_UPSERTED"
_BUCKET = "rc72_n3_dsh_evidence_anchors"
_CANDIDATE_SCHEMA = "RC72_N3_SOURCE_TARGET_CANDIDATE_V1"


class N3SourceTargetEvidenceAnchorError(ContractError):
    pass


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise N3SourceTargetEvidenceAnchorError(
            "RC72_N3_ANCHOR_%s_REQUIRED" % name.upper()
        )
    return value.strip()


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:24])


def _sha256(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def validate_rc72_n3_dsh_evidence_anchor(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "anchor_id", "release_id", "mission_id", "release_batch_id",
        "source_commit", "application_id", "attempt_id", "assignment_id",
        "dispatch_id", "mission_node_id", "workitem_id", "worker_instance_id",
        "dsh_session_id", "candidate_output_ref", "raw_output_ref",
        "raw_output_sha256", "candidate_schema",
    ):
        out[name] = _contracts._require_str(out, name)
    if not out["dsh_session_id"].startswith("session-"):
        raise _contracts.DomainValidationError(
            "RC72_N3_ANCHOR_DSH_SESSION_INVALID"
        )
    if not out["raw_output_ref"].startswith("file://"):
        raise _contracts.DomainValidationError(
            "RC72_N3_ANCHOR_RAW_OUTPUT_REF_INVALID"
        )
    if (
        not out["raw_output_sha256"].startswith("sha256:")
        or len(out["raw_output_sha256"]) != 71
    ):
        raise _contracts.DomainValidationError(
            "RC72_N3_ANCHOR_RAW_OUTPUT_SHA256_INVALID"
        )
    if out["candidate_schema"] != _CANDIDATE_SCHEMA:
        raise _contracts.DomainValidationError(
            "RC72_N3_ANCHOR_CANDIDATE_SCHEMA_INVALID"
        )
    value = out.get("created_at")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _contracts.DomainValidationError("RC72_N3_ANCHOR_CREATED_AT_INVALID")
    for forbidden in (
        "targets", "repository", "repository_ref", "source_revision",
        "base_revision", "head_revision", "target_id", "source_mapping",
        "source_mapping_accepted", "changed_files", "changed_symbols",
        "codegraph_result", "evaluation", "node_delivery_id", "node_gate",
        "node_pass", "code_analysis_task_ids", "n4_started", "q7_pass",
        "field_verified", "bank_final",
    ):
        if forbidden in out:
            raise _contracts.DomainValidationError(
                "RC72_N3_ANCHOR_SOURCE_TRUTH_CLAIM_FORBIDDEN:%s" % forbidden
            )
    version = out.get("artifact_version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError(
            "RC72_N3_ANCHOR_ARTIFACT_VERSION_INVALID"
        )
    out["artifact_version"] = version
    out["artifact_type"] = _ARTIFACT
    return out


def install_rc72_n3_source_target_anchor_overlay() -> None:
    install_rc7_truth_overlay()
    install_rc72_n3_source_target_handoff_overlay()
    _contracts.VALIDATORS[_ARTIFACT] = validate_rc72_n3_dsh_evidence_anchor
    _truth.BUCKETS[_ARTIFACT] = _BUCKET
    _truth.IDENTITY_FIELDS[_ARTIFACT] = "anchor_id"
    _truth.EVENT_TYPES[_EVENT] = (_ARTIFACT, "anchor_id")


def _ensure_bucket(truth: TruthRuntime) -> None:
    projection = getattr(truth, "projection", None)
    if projection is None:
        return
    if not hasattr(projection, _BUCKET):
        setattr(projection, _BUCKET, {})
    versions = getattr(projection, "_versions", None)
    if isinstance(versions, dict):
        versions.setdefault(_ARTIFACT, {})


class N3SourceTargetEvidenceAnchorService:
    """Hash-anchor one successful N3 source-target DSH Attempt."""

    def __init__(
        self,
        truth: TruthRuntime,
        *,
        source_commit: str,
        state_root: str,
    ) -> None:
        install_rc72_n3_source_target_anchor_overlay()
        _ensure_bucket(truth)
        self.truth = truth
        self.source_commit = _required(source_commit, "source_commit")
        self.state_root = Path(_required(state_root, "state_root")).expanduser().resolve()

    @staticmethod
    def _anchor_id(attempt_id: str) -> str:
        return _stable_id("N3SRCANCH", attempt_id, "DSH_RAW_OUTPUT")

    def _attempt(
        self, release_batch_id: str, application_id: str
    ) -> Dict[str, Any]:
        rows = self.truth.query(
            "rc72_n3_source_target_attempt", release_batch_id=release_batch_id
        )
        exact = [
            row for row in rows
            if row.get("source_commit") == self.source_commit
            and row.get("application_id") == application_id
            and row.get("state") == "WORKER_COMPLETED_PENDING_DELIVERY"
            and row.get("handoff_status") == "DSH_SESSION_OBSERVED"
            and row.get("process_outcome") == "SUCCEEDED"
            and row.get("candidate_schema") == _CANDIDATE_SCHEMA
        ]
        if len(exact) != 1:
            raise N3SourceTargetEvidenceAnchorError(
                "RC72_N3_ANCHOR_EXACT_ATTEMPT_REQUIRED:%d" % len(exact)
            )
        return exact[0]

    def _raw_candidate(
        self, attempt: Mapping[str, Any]
    ) -> Tuple[Dict[str, Any], str, str, Tuple[Dict[str, Any], ...]]:
        file_refs = [
            ref for ref in list(attempt.get("runtime_evidence_refs") or [])
            if isinstance(ref, str) and ref.startswith("file://")
        ]
        if len(file_refs) != 1:
            raise N3SourceTargetEvidenceAnchorError(
                "RC72_N3_ANCHOR_RAW_DSH_EVIDENCE_REQUIRED:%d" % len(file_refs)
            )
        content_ref = file_refs[0]
        path = Path(content_ref[len("file://"):]).expanduser().resolve()
        try:
            path.relative_to(self.state_root)
        except ValueError as exc:
            raise N3SourceTargetEvidenceAnchorError(
                "RC72_N3_ANCHOR_RAW_EVIDENCE_OUTSIDE_STATE_ROOT"
            ) from exc
        if not path.is_file():
            raise N3SourceTargetEvidenceAnchorError(
                "RC72_N3_ANCHOR_RAW_EVIDENCE_NOT_FOUND"
            )
        raw = path.read_bytes()
        if not raw:
            raise N3SourceTargetEvidenceAnchorError(
                "RC72_N3_ANCHOR_RAW_EVIDENCE_EMPTY"
            )
        raw_hash = _sha256(raw)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise N3SourceTargetEvidenceAnchorError(
                "RC72_N3_ANCHOR_RAW_EVIDENCE_NOT_UTF8"
            ) from exc
        events = tuple(DshHeadlessWorkerLauncher._parse_json_lines(text))
        if not events:
            raise N3SourceTargetEvidenceAnchorError(
                "RC72_N3_ANCHOR_RAW_EVENTS_REQUIRED"
            )
        session_id = DshHeadlessWorkerLauncher._session_id(events)
        if session_id != attempt.get("dsh_session_id"):
            raise N3SourceTargetEvidenceAnchorError(
                "RC72_N3_ANCHOR_DSH_SESSION_MISMATCH"
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
            raise N3SourceTargetEvidenceAnchorError(
                "RC72_N3_ANCHOR_TOOL_CALL_EVIDENCE_MISMATCH"
            )
        try:
            candidate = N3SourceTargetDshHandoffService._strict_top_level_final_json(events)
            normalized = N3SourceTargetDshHandoffService._validate_candidate(
                candidate, str(attempt["application_id"])
            )
        except N3SourceTargetHandoffError as exc:
            raise N3SourceTargetEvidenceAnchorError(str(exc)) from exc
        return normalized, content_ref, raw_hash, parsed_calls

    def anchor(
        self, *, release_batch_id: str, application_id: str
    ) -> Dict[str, Any]:
        release_batch_id = _required(release_batch_id, "release_batch_id")
        application_id = _required(application_id, "application_id")
        attempt = self._attempt(release_batch_id, application_id)
        _candidate, content_ref, raw_hash, _calls = self._raw_candidate(attempt)
        anchor_id = self._anchor_id(str(attempt["attempt_id"]))
        expected = {
            "release_id": attempt.get("release_id"),
            "mission_id": attempt.get("mission_id"),
            "release_batch_id": attempt.get("release_batch_id"),
            "source_commit": self.source_commit,
            "application_id": application_id,
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
                raise N3SourceTargetEvidenceAnchorError(
                    "RC72_N3_ANCHOR_NOT_UNIQUE"
                )
            for key, value in expected.items():
                if existing[0].get(key) != value:
                    raise N3SourceTargetEvidenceAnchorError(
                        "RC72_N3_ANCHOR_CONFLICT:%s" % key
                    )
            return dict(existing[0])
        payload = dict(expected)
        payload.update({
            "anchor_id": anchor_id,
            "created_at": int(
                attempt.get("updated_at") or attempt.get("created_at") or 0
            ),
            "artifact_version": 1,
        })
        self.truth.append_atomic(_EVENT, payload)
        rows = self.truth.query(_ARTIFACT, anchor_id=anchor_id)
        if len(rows) != 1:
            raise N3SourceTargetEvidenceAnchorError(
                "RC72_N3_ANCHOR_PERSISTENCE_FAILED"
            )
        return rows[0]


install_rc72_n3_source_target_anchor_overlay()
