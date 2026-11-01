"""Finalize one hash-anchored RC7.2 N5 verifier result into canonical data truth.

The independent verifier's V2 JSON is not trusted until its exact raw bytes have
been SHA-256 anchored.  This service revalidates that anchor and deterministically
admits the semantic decision.  VERIFIED_CANDIDATE creates canonical verification
evidence, a verified DataResource, and an exact DataRequirement binding.  A
REPAIR_REQUIRED decision is persisted as canonical repair truth without creating
a resource or binding.

This boundary deliberately does not acquire a DataLease, PASS N5, release N6,
or make field/BANK_FINAL claims. Reservation belongs to a concrete consumer
Attempt; node completion belongs to the aggregate N5 delivery/gate.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc6_runtime.truth import TruthRuntime

from .models import ContractError, Evidence
from .rc72_data_resources import DataLeaseManager
from .rc72_n5_data_resolution import N5DataResolutionService
from .rc72_n5_data_verification_anchor import (
    N5DataVerificationEvidenceAnchorError,
    N5DataVerificationEvidenceAnchorService,
    install_rc72_n5_data_verification_anchor_overlay,
)
from .truth_overlay import append_entity, install_rc7_truth_overlay

_RESULT_ARTIFACT = "rc72_n5_data_verification_result"
_RESULT_EVENT = "RC72_N5_DATA_VERIFICATION_RESULT_UPSERTED"
_RESULT_BUCKET = "rc72_n5_data_verification_results"
_DECISIONS = {"VERIFIED_CANDIDATE", "REPAIR_REQUIRED"}
_INSTALLED = False


class N5DataVerificationFinalizationError(ContractError):
    pass


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise N5DataVerificationFinalizationError(
            "RC72_N5_VERIFY_FINAL_%s_REQUIRED" % name.upper()
        )
    return value.strip()


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:24])


def _sha256(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _string_list(value: Any, name: str, allow_empty: bool = False) -> List[str]:
    if not isinstance(value, list):
        raise N5DataVerificationFinalizationError(
            "RC72_N5_VERIFY_FINAL_%s_LIST_REQUIRED" % name.upper()
        )
    result = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    if len(result) != len(value) or len(result) != len(set(result)):
        raise N5DataVerificationFinalizationError(
            "RC72_N5_VERIFY_FINAL_%s_INVALID" % name.upper()
        )
    if not allow_empty and not result:
        raise N5DataVerificationFinalizationError(
            "RC72_N5_VERIFY_FINAL_%s_REQUIRED" % name.upper()
        )
    return result


def _validate_string_list(out: Dict[str, Any], name: str, allow_empty: bool = False) -> None:
    value = out.get(name)
    if not isinstance(value, list):
        raise _contracts.DomainValidationError(
            "RC72_N5_VERIFY_FINAL_%s_INVALID" % name.upper()
        )
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise _contracts.DomainValidationError(
            "RC72_N5_VERIFY_FINAL_%s_INVALID" % name.upper()
        )
    if len(value) != len(set(value)):
        raise _contracts.DomainValidationError(
            "RC72_N5_VERIFY_FINAL_%s_DUPLICATE" % name.upper()
        )
    if not allow_empty and not value:
        raise _contracts.DomainValidationError(
            "RC72_N5_VERIFY_FINAL_%s_REQUIRED" % name.upper()
        )


def validate_rc72_n5_data_verification_result(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "finalization_id", "release_id", "mission_id", "release_batch_id",
        "source_commit", "mission_node_id", "data_requirement_id",
        "resolution_plan_id", "source_case_sha256", "requirement_id", "sst_id",
        "obligation_id", "case_id", "workitem_id", "candidate_artifact_id",
        "candidate_content_hash", "verification_attempt_id", "verifier_worker_id",
        "verifier_dsh_session_id", "evidence_anchor_id", "raw_output_sha256",
        "verification_evidence_id", "decision", "verification",
    ):
        out[name] = _contracts._require_str(out, name)
    if out["decision"] not in _DECISIONS:
        raise _contracts.DomainValidationError("RC72_N5_VERIFY_FINAL_DECISION_INVALID")
    if not out["source_case_sha256"].startswith("sha256:"):
        raise _contracts.DomainValidationError("RC72_N5_VERIFY_FINAL_CASE_HASH_INVALID")
    if not out["candidate_content_hash"].startswith("sha256:"):
        raise _contracts.DomainValidationError("RC72_N5_VERIFY_FINAL_CANDIDATE_HASH_INVALID")
    if not out["raw_output_sha256"].startswith("sha256:") or len(out["raw_output_sha256"]) != 71:
        raise _contracts.DomainValidationError("RC72_N5_VERIFY_FINAL_RAW_HASH_INVALID")
    _validate_string_list(out, "precondition_refs")
    _validate_string_list(out, "unknowns", allow_empty=True)
    _validate_string_list(out, "gaps", allow_empty=True)
    if out["decision"] == "VERIFIED_CANDIDATE":
        for name in (
            "candidate_ref", "data_ref", "data_domain", "source_or_constructor",
            "validity_window", "cleanup_policy", "resource_metadata_ref", "binding_id",
            "reservation_mode",
        ):
            out[name] = _contracts._require_str(out, name)
        if not out["candidate_ref"].startswith("candidate://"):
            raise _contracts.DomainValidationError("RC72_N5_VERIFY_FINAL_CANDIDATE_REF_INVALID")
        if not out["data_ref"].startswith("data://"):
            raise _contracts.DomainValidationError("RC72_N5_VERIFY_FINAL_DATA_REF_INVALID")
        if not isinstance(out.get("mutable"), bool):
            raise _contracts.DomainValidationError("RC72_N5_VERIFY_FINAL_MUTABLE_INVALID")
        if out["unknowns"] or out["gaps"]:
            raise _contracts.DomainValidationError("RC72_N5_VERIFY_FINAL_VERIFIED_HAS_GAPS")
    else:
        if not out["unknowns"] and not out["gaps"]:
            raise _contracts.DomainValidationError("RC72_N5_VERIFY_FINAL_REPAIR_REASON_REQUIRED")
        for name in (
            "candidate_ref", "data_ref", "data_domain", "source_or_constructor",
            "validity_window", "cleanup_policy", "resource_metadata_ref", "binding_id",
            "reservation_mode", "mutable",
        ):
            if out.get(name) is not None:
                raise _contracts.DomainValidationError(
                    "RC72_N5_VERIFY_FINAL_REPAIR_RESOURCE_CLAIM_FORBIDDEN:%s" % name
                )
    for forbidden in (
        "data_lease_id", "reservation_owner", "reserved", "node_delivery_id",
        "node_gate_id", "node_pass", "n5_pass", "n6_ready", "field_verified", "bank_final",
    ):
        if forbidden in out:
            raise _contracts.DomainValidationError(
                "RC72_N5_VERIFY_FINAL_PREMATURE_CLAIM_FORBIDDEN:%s" % forbidden
            )
    created_at = out.get("created_at")
    if isinstance(created_at, bool) or not isinstance(created_at, int) or created_at < 0:
        raise _contracts.DomainValidationError("RC72_N5_VERIFY_FINAL_CREATED_AT_INVALID")
    version = out.get("artifact_version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError("RC72_N5_VERIFY_FINAL_ARTIFACT_VERSION_INVALID")
    out["artifact_version"] = version
    out["artifact_type"] = _RESULT_ARTIFACT
    return out


def install_rc72_n5_data_verification_finalization_overlay() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    install_rc7_truth_overlay()
    install_rc72_n5_data_verification_anchor_overlay()
    _contracts.VALIDATORS[_RESULT_ARTIFACT] = validate_rc72_n5_data_verification_result
    _truth.BUCKETS[_RESULT_ARTIFACT] = _RESULT_BUCKET
    _truth.IDENTITY_FIELDS[_RESULT_ARTIFACT] = "finalization_id"
    _truth.EVENT_TYPES[_RESULT_EVENT] = (_RESULT_ARTIFACT, "finalization_id")
    _INSTALLED = True


def _ensure_bucket(truth: TruthRuntime) -> None:
    projection = getattr(truth, "projection", None)
    if projection is None:
        return
    if not hasattr(projection, _RESULT_BUCKET):
        setattr(projection, _RESULT_BUCKET, {})
    versions = getattr(projection, "_versions", None)
    if isinstance(versions, dict):
        versions.setdefault(_RESULT_ARTIFACT, {})


class N5DataVerificationFinalizationService:
    """Admit one anchored verifier decision into canonical N5 data truth."""

    def __init__(
        self,
        truth: TruthRuntime,
        *,
        release_id: str,
        mission_id: str,
        source_commit: str,
        state_root: str,
    ) -> None:
        install_rc72_n5_data_verification_finalization_overlay()
        _ensure_bucket(truth)
        self.truth = truth
        self.release_id = _required(release_id, "release_id")
        self.mission_id = _required(mission_id, "mission_id")
        self.source_commit = _required(source_commit, "source_commit")
        self.state_root = Path(_required(state_root, "state_root")).expanduser().resolve()
        self.anchor_service = N5DataVerificationEvidenceAnchorService(
            truth,
            source_commit=self.source_commit,
            state_root=str(self.state_root),
        )
        self.resources = DataLeaseManager(truth, release_id=self.release_id)
        self.resolution = N5DataResolutionService(
            truth,
            release_id=self.release_id,
            source_commit=self.source_commit,
        )

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise N5DataVerificationFinalizationError(
                "RC72_N5_VERIFY_FINAL_TRUTH_NOT_UNIQUE:%s:%d" % (artifact_type, len(rows))
            )
        return rows[0]

    @staticmethod
    def _canonical_data_ref(candidate_ref: str) -> str:
        value = _required(candidate_ref, "candidate_ref")
        if not value.startswith("candidate://"):
            raise N5DataVerificationFinalizationError("RC72_N5_VERIFY_FINAL_CANDIDATE_REF_INVALID")
        suffix = value[len("candidate://"):].strip("/")
        if not suffix:
            raise N5DataVerificationFinalizationError("RC72_N5_VERIFY_FINAL_CANDIDATE_REF_EMPTY")
        return "data://" + suffix

    @staticmethod
    def _finalization_id(verification_attempt_id: str) -> str:
        return _stable_id("N5DATAVERFINAL", verification_attempt_id, "V2")

    @staticmethod
    def _evidence_id(anchor: Mapping[str, Any]) -> str:
        return _stable_id(
            "EVD-N5-DATA-VERIFY",
            str(anchor["verification_attempt_id"]),
            str(anchor["raw_output_sha256"]),
        )

    def _semantic(self, anchor: Mapping[str, Any]) -> Dict[str, Any]:
        raw_ref = _required(anchor.get("raw_output_ref"), "raw_output_ref")
        if not raw_ref.startswith("file://"):
            raise N5DataVerificationFinalizationError("RC72_N5_VERIFY_FINAL_RAW_REF_INVALID")
        path = Path(raw_ref[len("file://"):]).expanduser().resolve()
        try:
            path.relative_to(self.state_root)
        except ValueError as exc:
            raise N5DataVerificationFinalizationError("RC72_N5_VERIFY_FINAL_RAW_OUTSIDE_STATE_ROOT") from exc
        if not path.is_file():
            raise N5DataVerificationFinalizationError("RC72_N5_VERIFY_FINAL_RAW_NOT_FOUND")
        raw = path.read_bytes()
        if _sha256(raw) != anchor.get("raw_output_sha256"):
            raise N5DataVerificationFinalizationError("RC72_N5_VERIFY_FINAL_RAW_HASH_MISMATCH")
        try:
            events = tuple(DshHeadlessWorkerLauncher._parse_json_lines(raw.decode("utf-8")))
        except UnicodeDecodeError as exc:
            raise N5DataVerificationFinalizationError("RC72_N5_VERIFY_FINAL_RAW_NOT_UTF8") from exc
        finals = [
            event for event in events
            if str(event.get("type") or event.get("event") or event.get("kind") or "").lower() == "final"
        ]
        if len(finals) != 1 or not isinstance(finals[0].get("text"), str):
            raise N5DataVerificationFinalizationError("RC72_N5_VERIFY_FINAL_FINAL_EVENT_NOT_UNIQUE")
        try:
            value = json.loads(str(finals[0]["text"]))
        except json.JSONDecodeError as exc:
            raise N5DataVerificationFinalizationError("RC72_N5_VERIFY_FINAL_JSON_INVALID") from exc
        if not isinstance(value, dict):
            raise N5DataVerificationFinalizationError("RC72_N5_VERIFY_FINAL_OBJECT_REQUIRED")
        return value

    def _lineage(self, anchor: Mapping[str, Any]):
        if anchor.get("release_id") != self.release_id:
            raise N5DataVerificationFinalizationError("RC72_N5_VERIFY_FINAL_RELEASE_MISMATCH")
        if anchor.get("mission_id") != self.mission_id:
            raise N5DataVerificationFinalizationError("RC72_N5_VERIFY_FINAL_MISSION_MISMATCH")
        if anchor.get("source_commit") != self.source_commit:
            raise N5DataVerificationFinalizationError("RC72_N5_VERIFY_FINAL_SOURCE_MISMATCH")
        attempt = self._one(
            "rc72_n5_data_verification_attempt",
            verification_attempt_id=str(anchor["verification_attempt_id"]),
        )
        requirement = self._one(
            "rc72_n5_data_requirement",
            data_requirement_id=str(anchor["data_requirement_id"]),
        )
        plan = self._one(
            "rc72_n5_data_resolution_plan",
            plan_id=str(anchor["resolution_plan_id"]),
        )
        artifact = self._one(
            "rc7_artifact",
            artifact_id=str(anchor["candidate_artifact_id"]),
        )
        expected = {
            "release_id": self.release_id,
            "mission_id": self.mission_id,
            "release_batch_id": anchor.get("release_batch_id"),
            "source_commit": self.source_commit,
            "mission_node_id": anchor.get("mission_node_id"),
            "data_requirement_id": anchor.get("data_requirement_id"),
            "resolution_plan_id": anchor.get("resolution_plan_id"),
            "source_case_sha256": anchor.get("source_case_sha256"),
            "requirement_id": anchor.get("requirement_id"),
            "sst_id": anchor.get("sst_id"),
            "obligation_id": anchor.get("obligation_id"),
            "case_id": anchor.get("case_id"),
            "workitem_id": anchor.get("workitem_id"),
            "candidate_artifact_id": anchor.get("candidate_artifact_id"),
            "candidate_content_hash": anchor.get("candidate_content_hash"),
            "verifier_worker_id": anchor.get("verifier_worker_id"),
            "verifier_dsh_session_id": anchor.get("verifier_dsh_session_id"),
        }
        for field, target in expected.items():
            if attempt.get(field) != target:
                raise N5DataVerificationFinalizationError(
                    "RC72_N5_VERIFY_FINAL_ATTEMPT_LINEAGE_MISMATCH:%s" % field
                )
        for field in (
            "release_id", "mission_id", "release_batch_id", "source_commit",
            "mission_node_id", "data_requirement_id", "source_case_sha256",
            "requirement_id", "sst_id", "obligation_id", "case_id",
        ):
            if requirement.get(field) != anchor.get(field):
                raise N5DataVerificationFinalizationError(
                    "RC72_N5_VERIFY_FINAL_REQUIREMENT_LINEAGE_MISMATCH:%s" % field
                )
        if (
            plan.get("release_batch_id") != anchor.get("release_batch_id")
            or plan.get("data_requirement_id") != anchor.get("data_requirement_id")
            or plan.get("source_commit") != self.source_commit
            or str(plan.get("plan_id")) != str(anchor.get("resolution_plan_id"))
        ):
            raise N5DataVerificationFinalizationError("RC72_N5_VERIFY_FINAL_PLAN_LINEAGE_MISMATCH")
        if (
            artifact.get("mission_id") != self.mission_id
            or artifact.get("producer_task_id") != anchor.get("workitem_id")
            or artifact.get("content_hash") != anchor.get("candidate_content_hash")
            or artifact.get("state") != "VALID"
        ):
            raise N5DataVerificationFinalizationError("RC72_N5_VERIFY_FINAL_CANDIDATE_LINEAGE_MISMATCH")
        n5 = self._one("rc72_mission_node", mission_id=self.mission_id, node_type="N5_TEST_DATA")
        n6 = self._one("rc72_mission_node", mission_id=self.mission_id, node_type="N6_EXECUTABLE_READINESS")
        if n5.get("state") != "RUNNING" or n6.get("state") != "NOT_STARTED":
            raise N5DataVerificationFinalizationError("RC72_N5_VERIFY_FINAL_NODE_BOUNDARY_INVALID")
        return attempt, requirement, plan, artifact

    def _ensure_evidence(self, anchor: Mapping[str, Any]) -> str:
        evidence_id = self._evidence_id(anchor)
        expected = {
            "mission_id": self.mission_id,
            "kind": "N5_DATA_VERIFICATION_DSH_RAW_PROOF",
            "source_ref": "dsh://session/%s" % str(anchor["verifier_dsh_session_id"]),
            "content_ref": str(anchor["raw_output_ref"]),
            "subject_refs": [
                str(anchor["data_requirement_id"]),
                str(anchor["candidate_artifact_id"]),
                str(anchor["verification_attempt_id"]),
            ],
            "content_hash": str(anchor["raw_output_sha256"]),
        }
        existing = self.truth.query("rc7_evidence", evidence_id=evidence_id)
        if existing:
            if len(existing) != 1:
                raise N5DataVerificationFinalizationError("RC72_N5_VERIFY_FINAL_EVIDENCE_NOT_UNIQUE")
            for field, target in expected.items():
                if existing[0].get(field) != target:
                    raise N5DataVerificationFinalizationError(
                        "RC72_N5_VERIFY_FINAL_EVIDENCE_CONFLICT:%s" % field
                    )
            return evidence_id
        append_entity(
            self.truth,
            Evidence(
                evidence_id=evidence_id,
                mission_id=self.mission_id,
                kind=expected["kind"],
                source_ref=expected["source_ref"],
                content_ref=expected["content_ref"],
                subject_refs=list(expected["subject_refs"]),
                content_hash=expected["content_hash"],
            ),
            release_id=self.release_id,
        )
        return evidence_id

    def _ensure_resource(self, *, data_ref: str, candidate: Mapping[str, Any]) -> None:
        expected = {
            "release_id": self.release_id,
            "data_domain": _required(candidate.get("data_domain"), "data_domain"),
            "verified": True,
            "mutable": candidate.get("mutable"),
            "metadata_ref": _required(candidate.get("candidate_ref"), "candidate_ref"),
        }
        if not isinstance(expected["mutable"], bool):
            raise N5DataVerificationFinalizationError("RC72_N5_VERIFY_FINAL_MUTABLE_REQUIRED")
        existing = self.truth.query("rc72_data_resource", data_ref=data_ref)
        if existing:
            if len(existing) != 1:
                raise N5DataVerificationFinalizationError("RC72_N5_VERIFY_FINAL_RESOURCE_NOT_UNIQUE")
            for field, target in expected.items():
                if existing[0].get(field) != target:
                    raise N5DataVerificationFinalizationError(
                        "RC72_N5_VERIFY_FINAL_RESOURCE_CONFLICT:%s" % field
                    )
            return
        self.resources.register_data_ref(
            data_ref=data_ref,
            data_domain=str(expected["data_domain"]),
            verified=True,
            mutable=bool(expected["mutable"]),
            metadata_ref=str(expected["metadata_ref"]),
        )

    def _persist_result(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        finalization_id = str(payload["finalization_id"])
        existing = self.truth.query(_RESULT_ARTIFACT, finalization_id=finalization_id)
        if existing:
            if len(existing) != 1:
                raise N5DataVerificationFinalizationError("RC72_N5_VERIFY_FINAL_RESULT_NOT_UNIQUE")
            current = existing[0]
            for field, target in payload.items():
                if field in {"artifact_type", "artifact_version"}:
                    continue
                if current.get(field) != target:
                    raise N5DataVerificationFinalizationError(
                        "RC72_N5_VERIFY_FINAL_RESULT_CONFLICT:%s" % field
                    )
            return current
        self.truth.append_atomic(_RESULT_EVENT, payload)
        return self._one(_RESULT_ARTIFACT, finalization_id=finalization_id)

    def finalize(self, *, release_batch_id: str, data_requirement_id: str) -> Dict[str, Any]:
        release_batch_id = _required(release_batch_id, "release_batch_id")
        data_requirement_id = _required(data_requirement_id, "data_requirement_id")
        try:
            anchor = self.anchor_service.anchor(
                release_batch_id=release_batch_id,
                data_requirement_id=data_requirement_id,
            )
        except N5DataVerificationEvidenceAnchorError as exc:
            raise N5DataVerificationFinalizationError(
                "RC72_N5_VERIFY_FINAL_ANCHOR_INVALID:%s" % exc
            ) from exc
        if anchor.get("release_batch_id") != release_batch_id or anchor.get("data_requirement_id") != data_requirement_id:
            raise N5DataVerificationFinalizationError("RC72_N5_VERIFY_FINAL_ANCHOR_SCOPE_MISMATCH")
        _attempt, requirement, _plan, _artifact = self._lineage(anchor)
        candidate = self._semantic(anchor)
        decision = _required(candidate.get("status"), "decision").upper()
        if decision not in _DECISIONS:
            raise N5DataVerificationFinalizationError("RC72_N5_VERIFY_FINAL_DECISION_INVALID")
        evidence_id = self._ensure_evidence(anchor)
        finalization_id = self._finalization_id(str(anchor["verification_attempt_id"]))
        common = {
            "finalization_id": finalization_id,
            "release_id": self.release_id,
            "mission_id": self.mission_id,
            "release_batch_id": release_batch_id,
            "source_commit": self.source_commit,
            "mission_node_id": str(anchor["mission_node_id"]),
            "data_requirement_id": data_requirement_id,
            "resolution_plan_id": str(anchor["resolution_plan_id"]),
            "source_case_sha256": str(anchor["source_case_sha256"]),
            "requirement_id": str(anchor["requirement_id"]),
            "sst_id": str(anchor["sst_id"]),
            "obligation_id": str(anchor["obligation_id"]),
            "case_id": str(anchor["case_id"]),
            "workitem_id": str(anchor["workitem_id"]),
            "candidate_artifact_id": str(anchor["candidate_artifact_id"]),
            "candidate_content_hash": str(anchor["candidate_content_hash"]),
            "verification_attempt_id": str(anchor["verification_attempt_id"]),
            "verifier_worker_id": str(anchor["verifier_worker_id"]),
            "verifier_dsh_session_id": str(anchor["verifier_dsh_session_id"]),
            "evidence_anchor_id": str(anchor["anchor_id"]),
            "raw_output_sha256": str(anchor["raw_output_sha256"]),
            "verification_evidence_id": evidence_id,
            "decision": decision,
            "verification": _required(candidate.get("verification"), "verification"),
            "precondition_refs": _string_list(candidate.get("precondition_refs"), "precondition_refs"),
            "unknowns": _string_list(candidate.get("unknowns"), "unknowns", allow_empty=True),
            "gaps": _string_list(candidate.get("gaps"), "gaps", allow_empty=True),
            "created_at": int(anchor.get("created_at") or 0),
            "artifact_version": 1,
        }
        if decision == "REPAIR_REQUIRED":
            common.update({
                "candidate_ref": None,
                "data_ref": None,
                "data_domain": None,
                "mutable": None,
                "source_or_constructor": None,
                "validity_window": None,
                "cleanup_policy": None,
                "resource_metadata_ref": None,
                "binding_id": None,
                "reservation_mode": None,
            })
            result = self._persist_result(common)
            return {
                "status": "REPAIR_REQUIRED",
                "finalization_id": finalization_id,
                "verification_evidence_id": evidence_id,
                "data_requirement_id": data_requirement_id,
                "unknowns": list(result["unknowns"]),
                "gaps": list(result["gaps"]),
                "n5_state": "RUNNING",
                "n6_state": "NOT_STARTED",
            }

        candidate_ref = _required(candidate.get("candidate_ref"), "candidate_ref")
        data_ref = self._canonical_data_ref(candidate_ref)
        self._ensure_resource(data_ref=data_ref, candidate=candidate)
        bound = self.resolution.bind_verified(
            data_requirement_id=data_requirement_id,
            data_ref=data_ref,
            strategy=_required(candidate.get("strategy"), "strategy"),
            source_or_constructor=_required(candidate.get("source_or_constructor"), "source_or_constructor"),
            verification=str(common["verification"]),
            verification_evidence_refs=[evidence_id],
            precondition_refs=list(common["precondition_refs"]),
            validity_window=_required(candidate.get("validity_window"), "validity_window"),
            cleanup_policy=_required(candidate.get("cleanup_policy"), "cleanup_policy"),
        )
        common.update({
            "candidate_ref": candidate_ref,
            "data_ref": data_ref,
            "data_domain": _required(candidate.get("data_domain"), "data_domain"),
            "mutable": candidate.get("mutable"),
            "source_or_constructor": _required(candidate.get("source_or_constructor"), "source_or_constructor"),
            "validity_window": _required(candidate.get("validity_window"), "validity_window"),
            "cleanup_policy": _required(candidate.get("cleanup_policy"), "cleanup_policy"),
            "resource_metadata_ref": candidate_ref,
            "binding_id": str(bound["binding_id"]),
            "reservation_mode": str(bound["reservation_mode"]),
        })
        result = self._persist_result(common)
        return {
            "status": "FINALIZED_VERIFIED" if bound["status"] == "BOUND_VERIFIED" else "RESUMED",
            "finalization_id": finalization_id,
            "verification_evidence_id": evidence_id,
            "data_requirement_id": data_requirement_id,
            "data_ref": data_ref,
            "binding_id": str(result["binding_id"]),
            "reservation_mode": str(result["reservation_mode"]),
            "n5_state": "RUNNING",
            "n6_state": "NOT_STARTED",
        }


install_rc72_n5_data_verification_finalization_overlay()

__all__ = [
    "N5DataVerificationFinalizationError",
    "N5DataVerificationFinalizationService",
    "install_rc72_n5_data_verification_finalization_overlay",
    "validate_rc72_n5_data_verification_result",
]
