"""RC7.2 N5 independent-verifier raw DSH evidence anchor.

This boundary replays the verifier JSONL and binds its exact bytes with SHA-256.
It admits integrity/lineage only: no DataRef, binding, DataLease, N5 PASS, N6
release, field status, or BANK_FINAL truth is created here.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Tuple

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc6_runtime.truth import TruthRuntime

from .candidate_payload import CandidatePayloadReader
from .models import ContractError
from .rc72_n5_data_verification_handoff import install_rc72_n5_data_verification_handoff_overlay
from .truth_overlay import install_rc7_truth_overlay

_ARTIFACT = "rc72_n5_data_verification_evidence_anchor"
_EVENT = "RC72_N5_DATA_VERIFICATION_EVIDENCE_ANCHOR_UPSERTED"
_BUCKET = "rc72_n5_data_verification_evidence_anchors"
_SCHEMA = "RC72_N5_DATA_VERIFICATION_CANDIDATE_V2"
_ATTEMPT_STATE = "VERIFIER_COMPLETED_PENDING_RAW_ANCHOR"
_NODE = "N5_TEST_DATA"
_NEXT_NODE = "N6_EXECUTABLE_READINESS"
_INSTALLED = False


class N5DataVerificationEvidenceAnchorError(ContractError):
    pass


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise N5DataVerificationEvidenceAnchorError(
            "RC72_N5_VERIFY_ANCHOR_%s_REQUIRED" % name.upper()
        )
    return value.strip()


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:24])


def _sha256(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _strings(value: Any, name: str, allow_empty: bool = False) -> List[str]:
    if not isinstance(value, list):
        raise N5DataVerificationEvidenceAnchorError(
            "RC72_N5_VERIFY_ANCHOR_%s_LIST_REQUIRED" % name.upper()
        )
    result = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    if len(result) != len(value) or len(result) != len(set(result)):
        raise N5DataVerificationEvidenceAnchorError(
            "RC72_N5_VERIFY_ANCHOR_%s_INVALID" % name.upper()
        )
    if not allow_empty and not result:
        raise N5DataVerificationEvidenceAnchorError(
            "RC72_N5_VERIFY_ANCHOR_%s_REQUIRED" % name.upper()
        )
    return result


def validate_rc72_n5_data_verification_evidence_anchor(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    required = (
        "anchor_id", "release_id", "mission_id", "release_batch_id", "source_commit",
        "mission_node_id", "data_requirement_id", "resolution_plan_id",
        "source_case_sha256", "requirement_id", "sst_id", "obligation_id", "case_id",
        "workitem_id", "candidate_artifact_id", "candidate_content_hash",
        "verification_attempt_id", "producer_worker_id", "producer_dsh_session_id",
        "verifier_worker_id", "verifier_dsh_session_id", "runtime_assignment_id",
        "authority_lease_id", "candidate_output_ref", "raw_output_ref",
        "raw_output_sha256", "candidate_schema",
    )
    for name in required:
        out[name] = _contracts._require_str(out, name)
    if not out["source_case_sha256"].startswith("sha256:"):
        raise _contracts.DomainValidationError("RC72_N5_VERIFY_ANCHOR_CASE_HASH_INVALID")
    if not out["candidate_content_hash"].startswith("sha256:"):
        raise _contracts.DomainValidationError("RC72_N5_VERIFY_ANCHOR_CANDIDATE_HASH_INVALID")
    if not out["producer_dsh_session_id"].startswith("session-") or not out["verifier_dsh_session_id"].startswith("session-"):
        raise _contracts.DomainValidationError("RC72_N5_VERIFY_ANCHOR_DSH_SESSION_INVALID")
    if out["producer_worker_id"] == out["verifier_worker_id"]:
        raise _contracts.DomainValidationError("RC72_N5_VERIFY_ANCHOR_WORKER_INDEPENDENCE_FAIL")
    if out["producer_dsh_session_id"] == out["verifier_dsh_session_id"]:
        raise _contracts.DomainValidationError("RC72_N5_VERIFY_ANCHOR_SESSION_INDEPENDENCE_FAIL")
    if not out["raw_output_ref"].startswith("file://"):
        raise _contracts.DomainValidationError("RC72_N5_VERIFY_ANCHOR_RAW_OUTPUT_REF_INVALID")
    if not out["raw_output_sha256"].startswith("sha256:") or len(out["raw_output_sha256"]) != 71:
        raise _contracts.DomainValidationError("RC72_N5_VERIFY_ANCHOR_RAW_OUTPUT_SHA256_INVALID")
    if out["candidate_schema"] != _SCHEMA:
        raise _contracts.DomainValidationError("RC72_N5_VERIFY_ANCHOR_CANDIDATE_SCHEMA_INVALID")
    created_at = out.get("created_at")
    if isinstance(created_at, bool) or not isinstance(created_at, int) or created_at < 0:
        raise _contracts.DomainValidationError("RC72_N5_VERIFY_ANCHOR_CREATED_AT_INVALID")
    forbidden = (
        "semantic_payload", "decision", "status", "candidate_ref", "data_domain", "mutable",
        "source_or_constructor", "verification", "validity_window", "cleanup_policy",
        "precondition_refs", "data_ref", "resource_metadata_ref", "binding_id", "verified",
        "reserved", "data_lease_id", "node_delivery_id", "node_gate_id", "node_pass",
        "n5_pass", "n6_ready", "field_verified", "bank_final",
    )
    for name in forbidden:
        if name in out:
            raise _contracts.DomainValidationError(
                "RC72_N5_VERIFY_ANCHOR_DATA_TRUTH_CLAIM_FORBIDDEN:%s" % name
            )
    version = out.get("artifact_version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError("RC72_N5_VERIFY_ANCHOR_ARTIFACT_VERSION_INVALID")
    out["artifact_version"] = version
    out["artifact_type"] = _ARTIFACT
    return out


def install_rc72_n5_data_verification_anchor_overlay() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    install_rc7_truth_overlay()
    install_rc72_n5_data_verification_handoff_overlay()
    _contracts.VALIDATORS[_ARTIFACT] = validate_rc72_n5_data_verification_evidence_anchor
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
        if str(event.get("type") or event.get("event") or event.get("kind") or "").lower() == "final"
    ]
    if len(finals) != 1:
        raise N5DataVerificationEvidenceAnchorError(
            "RC72_N5_VERIFY_ANCHOR_FINAL_EVENT_NOT_UNIQUE:%d" % len(finals)
        )
    text = finals[0].get("text")
    if not isinstance(text, str) or not text.strip():
        raise N5DataVerificationEvidenceAnchorError("RC72_N5_VERIFY_ANCHOR_FINAL_TEXT_REQUIRED")
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise N5DataVerificationEvidenceAnchorError("RC72_N5_VERIFY_ANCHOR_FINAL_JSON_INVALID") from exc
    if not isinstance(value, dict):
        raise N5DataVerificationEvidenceAnchorError("RC72_N5_VERIFY_ANCHOR_FINAL_OBJECT_REQUIRED")
    return value


class N5DataVerificationEvidenceAnchorService:
    """Replay and SHA-256 anchor one successful DATA_VERIFIER runtime output."""

    def __init__(self, truth: TruthRuntime, *, source_commit: str, state_root: str) -> None:
        install_rc72_n5_data_verification_anchor_overlay()
        _ensure_bucket(truth)
        self.truth = truth
        self.source_commit = _required(source_commit, "source_commit")
        self.state_root = Path(_required(state_root, "state_root")).expanduser().resolve()
        self.reader = CandidatePayloadReader()

    @staticmethod
    def _anchor_id(verification_attempt_id: str) -> str:
        return _stable_id("N5DATAVERANCH", verification_attempt_id, "DSH_RAW_OUTPUT_V2")

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise N5DataVerificationEvidenceAnchorError(
                "RC72_N5_VERIFY_ANCHOR_TRUTH_NOT_UNIQUE:%s:%d" % (artifact_type, len(rows))
            )
        return rows[0]

    @staticmethod
    def _precondition_refs(requirement: Mapping[str, Any]) -> List[str]:
        data_requirement_id = str(requirement["data_requirement_id"])
        values = list(requirement.get("case_preconditions") or [])
        if not values:
            return ["data-requirement://%s" % data_requirement_id]
        return [
            "data-requirement://%s/precondition/%d" % (data_requirement_id, index)
            for index, _item in enumerate(values)
        ]

    def _lineage(self, release_batch_id: str, data_requirement_id: str):
        rows = [
            row for row in self.truth.query("rc72_n5_data_verification_attempt", release_batch_id=release_batch_id)
            if row.get("source_commit") == self.source_commit
            and row.get("data_requirement_id") == data_requirement_id
            and row.get("state") == _ATTEMPT_STATE
            and row.get("process_outcome") == "SUCCEEDED"
            and row.get("candidate_schema") == _SCHEMA
        ]
        if len(rows) != 1:
            raise N5DataVerificationEvidenceAnchorError(
                "RC72_N5_VERIFY_ANCHOR_EXACT_ATTEMPT_REQUIRED:%d" % len(rows)
            )
        attempt = rows[0]
        requirement = self._one("rc72_n5_data_requirement", data_requirement_id=data_requirement_id)
        plan = self._one("rc72_n5_data_resolution_plan", plan_id=str(attempt["resolution_plan_id"]))
        artifact = self._one("rc7_artifact", artifact_id=str(attempt["candidate_artifact_id"]))
        for field in (
            "release_id", "mission_id", "release_batch_id", "source_commit", "mission_node_id",
            "data_requirement_id", "source_case_sha256", "requirement_id", "sst_id",
            "obligation_id", "case_id",
        ):
            if requirement.get(field) != attempt.get(field):
                raise N5DataVerificationEvidenceAnchorError(
                    "RC72_N5_VERIFY_ANCHOR_REQUIREMENT_LINEAGE_MISMATCH:%s" % field
                )
        if (
            plan.get("release_batch_id") != release_batch_id
            or plan.get("data_requirement_id") != data_requirement_id
            or plan.get("source_commit") != self.source_commit
            or str(plan.get("plan_id")) != str(attempt.get("resolution_plan_id"))
        ):
            raise N5DataVerificationEvidenceAnchorError("RC72_N5_VERIFY_ANCHOR_PLAN_LINEAGE_MISMATCH")
        if (
            artifact.get("producer_task_id") != attempt.get("workitem_id")
            or artifact.get("content_hash") != attempt.get("candidate_content_hash")
            or artifact.get("state") != "VALID"
        ):
            raise N5DataVerificationEvidenceAnchorError(
                "RC72_N5_VERIFY_ANCHOR_CANDIDATE_ARTIFACT_LINEAGE_MISMATCH"
            )
        n5 = self._one("rc72_mission_node", mission_id=str(attempt["mission_id"]), node_type=_NODE)
        n6 = self._one("rc72_mission_node", mission_id=str(attempt["mission_id"]), node_type=_NEXT_NODE)
        if n5.get("state") != "RUNNING" or n6.get("state") != "NOT_STARTED":
            raise N5DataVerificationEvidenceAnchorError("RC72_N5_VERIFY_ANCHOR_NODE_BOUNDARY_INVALID")
        durable = self.reader.load(
            self.truth,
            str(artifact["artifact_id"]),
            expected_mission_id=str(attempt["mission_id"]),
            expected_task_id=str(attempt["workitem_id"]),
        )
        return attempt, requirement, plan, artifact, dict(durable.semantic_payload)

    def _validate_v2(self, value, *, attempt, requirement, plan, artifact, producer_semantic) -> None:
        expected_keys = {
            "status", "release_batch_id", "data_requirement_id", "resolution_plan_id", "case_id",
            "candidate_artifact_id", "strategy", "candidate_ref", "data_domain", "mutable",
            "source_or_constructor", "verification", "validity_window", "cleanup_policy",
            "precondition_refs", "unknowns", "gaps",
        }
        if set(value.keys()) != expected_keys:
            raise N5DataVerificationEvidenceAnchorError("RC72_N5_VERIFY_ANCHOR_V2_TOP_LEVEL_CONTRACT_INVALID")
        decision = _required(value.get("status"), "v2_status").upper()
        if decision not in ("VERIFIED_CANDIDATE", "REPAIR_REQUIRED"):
            raise N5DataVerificationEvidenceAnchorError("RC72_N5_VERIFY_ANCHOR_V2_STATUS_INVALID")
        expected = {
            "release_batch_id": str(attempt["release_batch_id"]),
            "data_requirement_id": str(attempt["data_requirement_id"]),
            "resolution_plan_id": str(plan["plan_id"]),
            "case_id": str(requirement["case_id"]),
            "candidate_artifact_id": str(artifact["artifact_id"]),
            "strategy": str(producer_semantic["strategy"]),
        }
        for field, target in expected.items():
            if value.get(field) != target:
                raise N5DataVerificationEvidenceAnchorError(
                    "RC72_N5_VERIFY_ANCHOR_V2_LINEAGE_MISMATCH:%s" % field
                )
        refs = _strings(value.get("precondition_refs"), "precondition_refs")
        if refs != self._precondition_refs(requirement):
            raise N5DataVerificationEvidenceAnchorError("RC72_N5_VERIFY_ANCHOR_V2_PRECONDITION_SCOPE_MISMATCH")
        unknowns = _strings(value.get("unknowns"), "unknowns", allow_empty=True)
        gaps = _strings(value.get("gaps"), "gaps", allow_empty=True)
        _required(value.get("verification"), "verification")
        if decision == "VERIFIED_CANDIDATE":
            candidate_ref = _required(value.get("candidate_ref"), "candidate_ref")
            if not candidate_ref.startswith("candidate://"):
                raise N5DataVerificationEvidenceAnchorError("RC72_N5_VERIFY_ANCHOR_CANONICAL_DATA_REF_FORBIDDEN")
            _required(value.get("data_domain"), "data_domain")
            if not isinstance(value.get("mutable"), bool):
                raise N5DataVerificationEvidenceAnchorError("RC72_N5_VERIFY_ANCHOR_MUTABLE_BOOL_REQUIRED")
            for name in ("source_or_constructor", "validity_window", "cleanup_policy"):
                _required(value.get(name), name)
            if unknowns or gaps:
                raise N5DataVerificationEvidenceAnchorError("RC72_N5_VERIFY_ANCHOR_VERIFIED_CANNOT_HAVE_GAPS")
        else:
            if not unknowns and not gaps:
                raise N5DataVerificationEvidenceAnchorError("RC72_N5_VERIFY_ANCHOR_REPAIR_REASON_REQUIRED")
            for name in ("candidate_ref", "data_domain", "source_or_constructor", "validity_window", "cleanup_policy"):
                if value.get(name) not in (None, ""):
                    raise N5DataVerificationEvidenceAnchorError(
                        "RC72_N5_VERIFY_ANCHOR_REPAIR_RESOURCE_CLAIM_FORBIDDEN:%s" % name
                    )
            if value.get("mutable") is not None:
                raise N5DataVerificationEvidenceAnchorError("RC72_N5_VERIFY_ANCHOR_REPAIR_MUTABILITY_CLAIM_FORBIDDEN")

    def _raw(self, attempt, requirement, plan, artifact, producer_semantic) -> Tuple[str, str]:
        refs = [
            ref for ref in list(attempt.get("runtime_evidence_refs") or [])
            if isinstance(ref, str) and ref.startswith("file://")
        ]
        if len(refs) != 1:
            raise N5DataVerificationEvidenceAnchorError(
                "RC72_N5_VERIFY_ANCHOR_RAW_DSH_EVIDENCE_REQUIRED:%d" % len(refs)
            )
        content_ref = refs[0]
        path = Path(content_ref[len("file://"):]).expanduser().resolve()
        try:
            path.relative_to(self.state_root)
        except ValueError as exc:
            raise N5DataVerificationEvidenceAnchorError("RC72_N5_VERIFY_ANCHOR_RAW_EVIDENCE_OUTSIDE_STATE_ROOT") from exc
        if not path.is_file():
            raise N5DataVerificationEvidenceAnchorError("RC72_N5_VERIFY_ANCHOR_RAW_EVIDENCE_NOT_FOUND")
        raw = path.read_bytes()
        if not raw:
            raise N5DataVerificationEvidenceAnchorError("RC72_N5_VERIFY_ANCHOR_RAW_EVIDENCE_EMPTY")
        try:
            events = tuple(DshHeadlessWorkerLauncher._parse_json_lines(raw.decode("utf-8")))
        except UnicodeDecodeError as exc:
            raise N5DataVerificationEvidenceAnchorError("RC72_N5_VERIFY_ANCHOR_RAW_EVIDENCE_NOT_UTF8") from exc
        if not events:
            raise N5DataVerificationEvidenceAnchorError("RC72_N5_VERIFY_ANCHOR_RAW_EVENTS_REQUIRED")
        if DshHeadlessWorkerLauncher._session_id(events) != attempt.get("verifier_dsh_session_id"):
            raise N5DataVerificationEvidenceAnchorError("RC72_N5_VERIFY_ANCHOR_DSH_SESSION_MISMATCH")
        parsed_calls = tuple(DshHeadlessWorkerLauncher._tool_calls(events))
        observed_calls = tuple(
            {"call_ref": str(item.get("call_ref") or ""), "tool_name": str(item.get("tool_name") or "")}
            for item in list(attempt.get("observed_tool_calls") or [])
        )
        if parsed_calls != observed_calls:
            raise N5DataVerificationEvidenceAnchorError("RC72_N5_VERIFY_ANCHOR_TOOL_CALL_EVIDENCE_MISMATCH")
        self._validate_v2(
            _strict_final_json(events), attempt=attempt, requirement=requirement,
            plan=plan, artifact=artifact, producer_semantic=producer_semantic,
        )
        return content_ref, _sha256(raw)

    def anchor(self, *, release_batch_id: str, data_requirement_id: str) -> Dict[str, Any]:
        release_batch_id = _required(release_batch_id, "release_batch_id")
        data_requirement_id = _required(data_requirement_id, "data_requirement_id")
        attempt, requirement, plan, artifact, producer_semantic = self._lineage(
            release_batch_id, data_requirement_id
        )
        content_ref, raw_hash = self._raw(attempt, requirement, plan, artifact, producer_semantic)
        anchor_id = self._anchor_id(str(attempt["verification_attempt_id"]))
        expected = {
            "release_id": attempt.get("release_id"), "mission_id": attempt.get("mission_id"),
            "release_batch_id": attempt.get("release_batch_id"), "source_commit": self.source_commit,
            "mission_node_id": attempt.get("mission_node_id"), "data_requirement_id": attempt.get("data_requirement_id"),
            "resolution_plan_id": attempt.get("resolution_plan_id"), "source_case_sha256": attempt.get("source_case_sha256"),
            "requirement_id": attempt.get("requirement_id"), "sst_id": attempt.get("sst_id"),
            "obligation_id": attempt.get("obligation_id"), "case_id": attempt.get("case_id"),
            "workitem_id": attempt.get("workitem_id"), "candidate_artifact_id": attempt.get("candidate_artifact_id"),
            "candidate_content_hash": attempt.get("candidate_content_hash"),
            "verification_attempt_id": attempt.get("verification_attempt_id"),
            "producer_worker_id": attempt.get("producer_worker_id"), "producer_dsh_session_id": attempt.get("producer_dsh_session_id"),
            "verifier_worker_id": attempt.get("verifier_worker_id"), "verifier_dsh_session_id": attempt.get("verifier_dsh_session_id"),
            "runtime_assignment_id": attempt.get("runtime_assignment_id"), "authority_lease_id": attempt.get("authority_lease_id"),
            "candidate_output_ref": attempt.get("candidate_output_ref"), "raw_output_ref": content_ref,
            "raw_output_sha256": raw_hash, "candidate_schema": _SCHEMA,
        }
        existing = self.truth.query(_ARTIFACT, anchor_id=anchor_id)
        if existing:
            if len(existing) != 1:
                raise N5DataVerificationEvidenceAnchorError("RC72_N5_VERIFY_ANCHOR_NOT_UNIQUE")
            for key, value in expected.items():
                if existing[0].get(key) != value:
                    raise N5DataVerificationEvidenceAnchorError("RC72_N5_VERIFY_ANCHOR_CONFLICT:%s" % key)
            return dict(existing[0])
        payload = dict(expected)
        payload.update({
            "anchor_id": anchor_id,
            "created_at": int(attempt.get("updated_at") or attempt.get("created_at") or 0),
            "artifact_version": 1,
        })
        self.truth.append_atomic(_EVENT, payload)
        rows = self.truth.query(_ARTIFACT, anchor_id=anchor_id)
        if len(rows) != 1:
            raise N5DataVerificationEvidenceAnchorError("RC72_N5_VERIFY_ANCHOR_PERSISTENCE_FAILED")
        return rows[0]


install_rc72_n5_data_verification_anchor_overlay()

__all__ = [
    "N5DataVerificationEvidenceAnchorError",
    "N5DataVerificationEvidenceAnchorService",
    "install_rc72_n5_data_verification_anchor_overlay",
    "validate_rc72_n5_data_verification_evidence_anchor",
]
