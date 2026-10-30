"""Canonical Q3-Q6 field qualification receipts for RC7.2.

The service normalizes already-durable R1 Evidence into one qualification
receipt per Mission + ReleaseBatch + gate + source commit. It never promotes a
GitHub check, fixture, prompt, release name or caller boolean to FIELD PASS.

Q3-Q5 require provider-backed evidence explicitly bound to the target
ReleaseBatch, gate and source commit. Q6 additionally requires a trusted Human
Gate approval (human:// + CASE_HUMAN_GATE_APPROVAL) with the same binding.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.truth import TruthRuntime

from .case_runtime import HUMAN_GATE_APPROVAL_KIND
from .models import ContractError
from .rc72_truth import install_rc72_truth_overlay
from .truth_overlay import install_rc7_truth_overlay


_ARTIFACT = "rc72_field_qualification_receipt"
_EVENT = "RC72_FIELD_QUALIFICATION_RECEIPT_UPSERTED"
_BUCKET = "rc72_field_qualification_receipts"

_REQUIRED_GATES = ("Q3", "Q4", "Q5", "Q6")
_ALLOWED_STATUS = {"PASS", "FAIL", "HOLD", "NOT_RUN"}
QUALIFICATION_PROOF_KIND = "RC72_FIELD_QUALIFICATION_PROOF"

REASON_PASS = "FIELD_EVIDENCE_VERIFIED"
REASON_EVIDENCE_INVALID = "FIELD_EVIDENCE_INVALID_OR_UNBOUND"
REASON_REQUESTED_FAIL = "QUALIFICATION_REPORTED_FAIL"
REASON_NOT_RUN = "QUALIFICATION_NOT_RUN"
REASON_REQUESTED_HOLD = "QUALIFICATION_REPORTED_HOLD"


def _now() -> int:
    return int(time.time())


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError("FIELD_QUALIFICATION_%s_REQUIRED" % name.upper())
    return value.strip()


def _string_list(value: Any, name: str) -> List[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise _contracts.DomainValidationError("FIELD_QUALIFICATION_%s_INVALID" % name.upper())
    if len(set(value)) != len(value):
        raise _contracts.DomainValidationError("FIELD_QUALIFICATION_%s_DUPLICATE" % name.upper())
    return list(value)


def validate_rc72_field_qualification_receipt(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "qualification_receipt_id", "release_id", "mission_id", "release_batch_id",
        "gate", "source_commit", "platform_family", "platform_release",
        "architecture", "python_version", "status", "reason", "evidence_digest",
    ):
        out[name] = _contracts._require_str(out, name)
    out["gate"] = out["gate"].upper()
    out["status"] = out["status"].upper()
    if out["gate"] not in _REQUIRED_GATES:
        raise _contracts.DomainValidationError("FIELD_QUALIFICATION_GATE_INVALID")
    if out["status"] not in _ALLOWED_STATUS:
        raise _contracts.DomainValidationError("FIELD_QUALIFICATION_STATUS_INVALID")
    if len(out["evidence_digest"]) != 64:
        raise _contracts.DomainValidationError("FIELD_QUALIFICATION_EVIDENCE_DIGEST_INVALID")
    out["evidence_refs"] = _string_list(out.get("evidence_refs"), "evidence_refs")
    out["rejected_evidence_refs"] = _string_list(out.get("rejected_evidence_refs"), "rejected_evidence_refs")
    out["notes"] = _string_list(out.get("notes"), "notes")
    if not isinstance(out.get("field_verified"), bool):
        raise _contracts.DomainValidationError("FIELD_QUALIFICATION_FIELD_VERIFIED_INVALID")
    if not isinstance(out.get("bank_final"), bool):
        raise _contracts.DomainValidationError("FIELD_QUALIFICATION_BANK_FINAL_INVALID")
    if out["bank_final"]:
        raise _contracts.DomainValidationError("FIELD_QUALIFICATION_CANNOT_SET_BANK_FINAL")
    if out["status"] == "PASS" and (not out["field_verified"] or not out["evidence_refs"]):
        raise _contracts.DomainValidationError("FIELD_QUALIFICATION_PASS_REQUIRES_FIELD_EVIDENCE")
    if out["status"] != "PASS" and out["field_verified"]:
        raise _contracts.DomainValidationError("FIELD_QUALIFICATION_NON_PASS_CANNOT_BE_FIELD_VERIFIED")
    for name in ("created_at", "updated_at"):
        value = out.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise _contracts.DomainValidationError("FIELD_QUALIFICATION_%s_INVALID" % name.upper())
    version = out.get("artifact_version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError("FIELD_QUALIFICATION_ARTIFACT_VERSION_INVALID")
    out["artifact_version"] = version
    out["artifact_type"] = _ARTIFACT
    return out


def install_rc72_field_qualification_overlay() -> None:
    install_rc7_truth_overlay()
    install_rc72_truth_overlay()
    _contracts.VALIDATORS[_ARTIFACT] = validate_rc72_field_qualification_receipt
    _truth.BUCKETS[_ARTIFACT] = _BUCKET
    _truth.IDENTITY_FIELDS[_ARTIFACT] = "qualification_receipt_id"
    _truth.EVENT_TYPES[_EVENT] = (_ARTIFACT, "qualification_receipt_id")


def _ensure_bucket(truth: TruthRuntime) -> None:
    projection = getattr(truth, "projection", None)
    if projection is None:
        return
    if not hasattr(projection, _BUCKET):
        setattr(projection, _BUCKET, {})
    versions = getattr(projection, "_versions", None)
    if isinstance(versions, dict):
        versions.setdefault(_ARTIFACT, {})


class FieldQualificationService:
    """Persist fail-closed Q3-Q6 qualification receipts from canonical evidence."""

    def __init__(self, truth: TruthRuntime, *, release_id: str) -> None:
        install_rc72_field_qualification_overlay()
        _ensure_bucket(truth)
        self.truth = truth
        self.release_id = _required(release_id, "release_id")

    @staticmethod
    def _receipt_id(mission_id: str, release_batch_id: str, gate: str, source_commit: str) -> str:
        raw = "\x1f".join((mission_id, release_batch_id, gate, source_commit))
        return "FQ-%s" % hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    def _batch(self, release_batch_id: str) -> Dict[str, Any]:
        rows = self.truth.query("rc72_release_batch", release_batch_id=release_batch_id)
        if len(rows) != 1:
            raise ContractError("FIELD_QUALIFICATION_BATCH_NOT_UNIQUE:%d" % len(rows))
        row = rows[0]
        if row.get("release_id") != self.release_id:
            raise ContractError("FIELD_QUALIFICATION_BATCH_RELEASE_MISMATCH")
        return row

    def _evidence(self, evidence_id: str) -> Mapping[str, Any]:
        rows = self.truth.query("rc7_evidence", evidence_id=evidence_id)
        if len(rows) != 1:
            raise ContractError("FIELD_QUALIFICATION_EVIDENCE_NOT_UNIQUE:%s:%d" % (evidence_id, len(rows)))
        return rows[0]

    @staticmethod
    def _is_trusted_for_gate(evidence: Mapping[str, Any], gate: str) -> bool:
        source_ref = str(evidence.get("source_ref") or "")
        kind = str(evidence.get("kind") or "")
        if gate == "Q6":
            return kind == HUMAN_GATE_APPROVAL_KIND and source_ref.startswith("human://")
        return kind == QUALIFICATION_PROOF_KIND and source_ref.startswith("provider://")

    def _classify_evidence(
        self,
        evidence_refs: Sequence[str],
        *,
        mission_id: str,
        release_batch_id: str,
        gate: str,
        source_commit: str,
    ) -> Tuple[List[str], List[str]]:
        accepted: List[str] = []
        rejected: List[str] = []
        required_subjects = {release_batch_id, gate, source_commit}
        for evidence_id in sorted(set(evidence_refs)):
            evidence = self._evidence(evidence_id)
            subjects = set(str(ref) for ref in list(evidence.get("subject_refs") or []))
            valid = (
                evidence.get("mission_id") == mission_id
                and evidence.get("release_id") == self.release_id
                and required_subjects.issubset(subjects)
                and self._is_trusted_for_gate(evidence, gate)
            )
            (accepted if valid else rejected).append(evidence_id)
        return accepted, rejected

    @staticmethod
    def _signature(payload: Mapping[str, Any]) -> Dict[str, Any]:
        return {
            "status": payload.get("status"),
            "reason": payload.get("reason"),
            "field_verified": payload.get("field_verified"),
            "bank_final": payload.get("bank_final"),
            "evidence_refs": list(payload.get("evidence_refs") or []),
            "rejected_evidence_refs": list(payload.get("rejected_evidence_refs") or []),
            "notes": list(payload.get("notes") or []),
            "evidence_digest": payload.get("evidence_digest"),
            "platform_family": payload.get("platform_family"),
            "platform_release": payload.get("platform_release"),
            "architecture": payload.get("architecture"),
            "python_version": payload.get("python_version"),
        }

    def record(
        self,
        *,
        release_batch_id: str,
        gate: str,
        source_commit: str,
        requested_status: str,
        evidence_refs: Sequence[str],
        platform_family: str,
        platform_release: str,
        architecture: str,
        python_version: str,
        notes: Sequence[str] = (),
    ) -> Dict[str, Any]:
        gate = _required(gate, "gate").upper()
        if gate not in _REQUIRED_GATES:
            raise ContractError("FIELD_QUALIFICATION_GATE_INVALID")
        source_commit = _required(source_commit, "source_commit")
        requested = _required(requested_status, "requested_status").upper()
        if requested not in _ALLOWED_STATUS:
            raise ContractError("FIELD_QUALIFICATION_STATUS_INVALID")
        batch = self._batch(_required(release_batch_id, "release_batch_id"))
        mission_id = _required(batch.get("mission_id"), "mission_id")
        refs = [_required(ref, "evidence_ref") for ref in evidence_refs]
        if len(set(refs)) != len(refs):
            raise ContractError("FIELD_QUALIFICATION_EVIDENCE_REF_DUPLICATE")
        note_list = [_required(note, "note") for note in notes]

        accepted, rejected = self._classify_evidence(
            refs,
            mission_id=mission_id,
            release_batch_id=release_batch_id,
            gate=gate,
            source_commit=source_commit,
        )
        if requested == "PASS":
            if accepted and not rejected and len(accepted) == len(refs):
                status = "PASS"
                reason = REASON_PASS
                field_verified = True
            else:
                status = "HOLD"
                reason = REASON_EVIDENCE_INVALID
                field_verified = False
        elif requested == "FAIL":
            status = "FAIL"
            reason = REASON_REQUESTED_FAIL
            field_verified = False
        elif requested == "NOT_RUN":
            status = "NOT_RUN"
            reason = REASON_NOT_RUN
            field_verified = False
        else:
            status = "HOLD"
            reason = REASON_REQUESTED_HOLD
            field_verified = False

        evidence_digest = _sha({
            "mission_id": mission_id,
            "release_id": self.release_id,
            "release_batch_id": release_batch_id,
            "gate": gate,
            "source_commit": source_commit,
            "requested_status": requested,
            "accepted": accepted,
            "rejected": rejected,
        })
        receipt_id = self._receipt_id(mission_id, release_batch_id, gate, source_commit)
        existing = self.truth.query(_ARTIFACT, qualification_receipt_id=receipt_id)
        if len(existing) > 1:
            raise ContractError("FIELD_QUALIFICATION_RECEIPT_NOT_UNIQUE")
        now = _now()
        created_at = int(existing[0].get("created_at", now)) if existing else now
        version = int(existing[0].get("artifact_version", 1)) if existing else 1
        payload = {
            "qualification_receipt_id": receipt_id,
            "release_id": self.release_id,
            "mission_id": mission_id,
            "release_batch_id": release_batch_id,
            "gate": gate,
            "source_commit": source_commit,
            "platform_family": _required(platform_family, "platform_family"),
            "platform_release": _required(platform_release, "platform_release"),
            "architecture": _required(architecture, "architecture"),
            "python_version": _required(python_version, "python_version"),
            "status": status,
            "reason": reason,
            "field_verified": field_verified,
            "bank_final": False,
            "evidence_refs": accepted,
            "rejected_evidence_refs": rejected,
            "notes": note_list,
            "evidence_digest": evidence_digest,
            "created_at": created_at,
            "updated_at": now,
            "artifact_version": version,
        }
        if existing and self._signature(existing[0]) == self._signature(payload):
            return existing[0]
        if existing:
            payload["artifact_version"] = version + 1
        self.truth.append_atomic(_EVENT, payload)
        rows = self.truth.query(_ARTIFACT, qualification_receipt_id=receipt_id)
        if len(rows) != 1:
            raise ContractError("FIELD_QUALIFICATION_PERSISTENCE_FAILED")
        return rows[0]


install_rc72_field_qualification_overlay()
