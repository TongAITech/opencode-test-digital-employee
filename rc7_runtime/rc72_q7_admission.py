"""Q7 admission gate for a real RC7.2 ReleaseBatch mission.

Admission is deliberately narrower than Q7 qualification. It proves only that
Q7 is allowed to start: the ReleaseBatch has canonical FIELD provenance, its
Requirement/SST/TestObligation denominator is complete, and Q3-Q6 each have an
exact-lineage FIELD PASS receipt for the same source commit.

This module never emits Q7 PASS, BANK_FINAL, or field_verified=true.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, List, Mapping, Sequence

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.truth import TruthRuntime

from .models import ContractError
from .rc72_field_qualification import install_rc72_field_qualification_overlay
from .rc72_release_provenance import FIELD, install_rc72_release_provenance_overlay
from .rc72_release_scope import install_rc72_release_scope_overlay
from .rc72_truth import install_rc72_truth_overlay
from .truth_overlay import install_rc7_truth_overlay


_ARTIFACT = "rc72_q7_admission"
_EVENT = "RC72_Q7_ADMISSION_UPSERTED"
_BUCKET = "rc72_q7_admissions"
_REQUIRED_GATES = ("Q3", "Q4", "Q5", "Q6")
_ALLOWED_STATUS = {"ADMITTED", "HOLD"}

REASON_ADMITTED = "FIELD_PREREQUISITES_COMPLETE"
REASON_HOLD = "FIELD_PREREQUISITES_INCOMPLETE"


def _now() -> int:
    return int(time.time())


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError("Q7_ADMISSION_%s_REQUIRED" % name.upper())
    return value.strip()


def _string_list(value: Any, name: str) -> List[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise _contracts.DomainValidationError("Q7_ADMISSION_%s_INVALID" % name.upper())
    if len(set(value)) != len(value):
        raise _contracts.DomainValidationError("Q7_ADMISSION_%s_DUPLICATE" % name.upper())
    return list(value)


def validate_rc72_q7_admission(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "admission_id", "release_id", "mission_id", "release_batch_id",
        "source_commit", "status", "reason", "provenance_id",
        "scope_snapshot_id", "input_digest",
    ):
        out[name] = _contracts._require_str(out, name)
    out["status"] = out["status"].upper()
    if out["status"] not in _ALLOWED_STATUS:
        raise _contracts.DomainValidationError("Q7_ADMISSION_STATUS_INVALID")
    if len(out["input_digest"]) != 64:
        raise _contracts.DomainValidationError("Q7_ADMISSION_INPUT_DIGEST_INVALID")
    out["qualification_receipt_ids"] = _string_list(out.get("qualification_receipt_ids"), "qualification_receipt_ids")
    out["hold_reasons"] = _string_list(out.get("hold_reasons"), "hold_reasons")
    if not isinstance(out.get("field_verified"), bool) or out["field_verified"]:
        raise _contracts.DomainValidationError("Q7_ADMISSION_CANNOT_SET_FIELD_VERIFIED")
    if not isinstance(out.get("bank_final"), bool) or out["bank_final"]:
        raise _contracts.DomainValidationError("Q7_ADMISSION_CANNOT_SET_BANK_FINAL")
    if out["status"] == "ADMITTED" and out["hold_reasons"]:
        raise _contracts.DomainValidationError("Q7_ADMISSION_ADMITTED_CANNOT_HAVE_HOLD_REASONS")
    if out["status"] == "HOLD" and not out["hold_reasons"]:
        raise _contracts.DomainValidationError("Q7_ADMISSION_HOLD_REASONS_REQUIRED")
    for name in ("created_at", "updated_at"):
        value = out.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise _contracts.DomainValidationError("Q7_ADMISSION_%s_INVALID" % name.upper())
    version = out.get("artifact_version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError("Q7_ADMISSION_ARTIFACT_VERSION_INVALID")
    out["artifact_version"] = version
    out["artifact_type"] = _ARTIFACT
    return out


def install_rc72_q7_admission_overlay() -> None:
    install_rc7_truth_overlay()
    install_rc72_truth_overlay()
    install_rc72_release_provenance_overlay()
    install_rc72_release_scope_overlay()
    install_rc72_field_qualification_overlay()
    _contracts.VALIDATORS[_ARTIFACT] = validate_rc72_q7_admission
    _truth.BUCKETS[_ARTIFACT] = _BUCKET
    _truth.IDENTITY_FIELDS[_ARTIFACT] = "admission_id"
    _truth.EVENT_TYPES[_EVENT] = (_ARTIFACT, "admission_id")


def _ensure_bucket(truth: TruthRuntime) -> None:
    projection = getattr(truth, "projection", None)
    if projection is None:
        return
    if not hasattr(projection, _BUCKET):
        setattr(projection, _BUCKET, {})
    versions = getattr(projection, "_versions", None)
    if isinstance(versions, dict):
        versions.setdefault(_ARTIFACT, {})


class Q7AdmissionService:
    """Evaluate and persist a fail-closed Q7 start decision."""

    def __init__(self, truth: TruthRuntime, *, release_id: str) -> None:
        install_rc72_q7_admission_overlay()
        _ensure_bucket(truth)
        self.truth = truth
        self.release_id = _required(release_id, "release_id")

    @staticmethod
    def _admission_id(mission_id: str, release_batch_id: str, source_commit: str) -> str:
        raw = "\x1f".join((mission_id, release_batch_id, source_commit))
        return "Q7ADM-%s" % hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    def _batch(self, release_batch_id: str) -> Dict[str, Any]:
        rows = self.truth.query("rc72_release_batch", release_batch_id=release_batch_id)
        if len(rows) != 1:
            raise ContractError("Q7_ADMISSION_BATCH_NOT_UNIQUE:%d" % len(rows))
        row = rows[0]
        if row.get("release_id") != self.release_id:
            raise ContractError("Q7_ADMISSION_BATCH_RELEASE_MISMATCH")
        return row

    def _one_or_reason(self, artifact_type: str, identity: str, value: str, reason: str, holds: List[str]):
        rows = self.truth.query(artifact_type, **{identity: value})
        if len(rows) != 1:
            holds.append("%s:%d" % (reason, len(rows)))
            return None
        return rows[0]

    @staticmethod
    def _signature(payload: Mapping[str, Any]) -> Dict[str, Any]:
        return {
            "status": payload.get("status"),
            "reason": payload.get("reason"),
            "provenance_id": payload.get("provenance_id"),
            "scope_snapshot_id": payload.get("scope_snapshot_id"),
            "qualification_receipt_ids": list(payload.get("qualification_receipt_ids") or []),
            "hold_reasons": list(payload.get("hold_reasons") or []),
            "input_digest": payload.get("input_digest"),
            "field_verified": payload.get("field_verified"),
            "bank_final": payload.get("bank_final"),
        }

    def evaluate(
        self,
        *,
        release_batch_id: str,
        source_commit: str,
        provenance_id: str,
        scope_snapshot_id: str,
        qualification_receipt_ids: Sequence[str],
    ) -> Dict[str, Any]:
        release_batch_id = _required(release_batch_id, "release_batch_id")
        source_commit = _required(source_commit, "source_commit")
        provenance_id = _required(provenance_id, "provenance_id")
        scope_snapshot_id = _required(scope_snapshot_id, "scope_snapshot_id")
        receipt_ids = [_required(value, "qualification_receipt_id") for value in qualification_receipt_ids]
        batch = self._batch(release_batch_id)
        mission_id = _required(batch.get("mission_id"), "mission_id")
        holds: List[str] = []

        provenance = self._one_or_reason(
            "rc72_release_batch_provenance", "provenance_id", provenance_id,
            "PROVENANCE_NOT_UNIQUE", holds,
        )
        if provenance is not None:
            if provenance.get("mission_id") != mission_id or provenance.get("release_id") != self.release_id or provenance.get("release_batch_id") != release_batch_id:
                holds.append("PROVENANCE_LINEAGE_MISMATCH")
            if provenance.get("provenance") != FIELD:
                holds.append("PROVENANCE_NOT_FIELD:%s" % str(provenance.get("provenance") or "UNKNOWN"))

        snapshot = self._one_or_reason(
            "rc72_scope_denominator_snapshot", "snapshot_id", scope_snapshot_id,
            "SCOPE_SNAPSHOT_NOT_UNIQUE", holds,
        )
        if snapshot is not None:
            if snapshot.get("mission_id") != mission_id or snapshot.get("release_id") != self.release_id or snapshot.get("release_batch_id") != release_batch_id:
                holds.append("SCOPE_SNAPSHOT_LINEAGE_MISMATCH")
            if snapshot.get("denominator_complete") is not True:
                holds.append("SCOPE_DENOMINATOR_INCOMPLETE")
            for name in ("expected_requirement_count", "expected_sst_count", "expected_required_level_count"):
                value = snapshot.get(name)
                if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                    holds.append("SCOPE_%s_EMPTY" % name.upper())
            manifest_id = str(snapshot.get("manifest_id") or "")
            manifests = self.truth.query("rc72_release_scope_manifest", manifest_id=manifest_id) if manifest_id else []
            if len(manifests) != 1:
                holds.append("SCOPE_MANIFEST_NOT_UNIQUE:%d" % len(manifests))
            elif (
                manifests[0].get("mission_id") != mission_id
                or manifests[0].get("release_id") != self.release_id
                or manifests[0].get("release_batch_id") != release_batch_id
            ):
                holds.append("SCOPE_MANIFEST_LINEAGE_MISMATCH")

        if len(receipt_ids) != len(set(receipt_ids)):
            holds.append("QUALIFICATION_RECEIPT_DUPLICATE")
        by_gate: Dict[str, Dict[str, Any]] = {}
        for receipt_id in sorted(set(receipt_ids)):
            rows = self.truth.query("rc72_field_qualification_receipt", qualification_receipt_id=receipt_id)
            if len(rows) != 1:
                holds.append("QUALIFICATION_RECEIPT_NOT_UNIQUE:%s:%d" % (receipt_id, len(rows)))
                continue
            receipt = rows[0]
            gate = str(receipt.get("gate") or "")
            if gate not in _REQUIRED_GATES:
                holds.append("QUALIFICATION_GATE_INVALID:%s" % gate)
                continue
            if gate in by_gate:
                holds.append("QUALIFICATION_GATE_DUPLICATE:%s" % gate)
                continue
            by_gate[gate] = receipt
            if (
                receipt.get("mission_id") != mission_id
                or receipt.get("release_id") != self.release_id
                or receipt.get("release_batch_id") != release_batch_id
            ):
                holds.append("QUALIFICATION_LINEAGE_MISMATCH:%s" % gate)
            if receipt.get("source_commit") != source_commit:
                holds.append("QUALIFICATION_SOURCE_COMMIT_MISMATCH:%s" % gate)
            if receipt.get("status") != "PASS" or receipt.get("field_verified") is not True:
                holds.append("QUALIFICATION_NOT_FIELD_PASS:%s" % gate)
            if receipt.get("bank_final") is not False:
                holds.append("QUALIFICATION_BANK_FINAL_FORBIDDEN:%s" % gate)
        for gate in _REQUIRED_GATES:
            if gate not in by_gate:
                holds.append("QUALIFICATION_MISSING:%s" % gate)

        holds = sorted(set(holds))
        status = "ADMITTED" if not holds else "HOLD"
        reason = REASON_ADMITTED if status == "ADMITTED" else REASON_HOLD
        input_digest = _sha({
            "mission_id": mission_id,
            "release_id": self.release_id,
            "release_batch_id": release_batch_id,
            "source_commit": source_commit,
            "provenance_id": provenance_id,
            "scope_snapshot_id": scope_snapshot_id,
            "qualification_receipt_ids": sorted(receipt_ids),
            "hold_reasons": holds,
        })
        admission_id = self._admission_id(mission_id, release_batch_id, source_commit)
        existing = self.truth.query(_ARTIFACT, admission_id=admission_id)
        if len(existing) > 1:
            raise ContractError("Q7_ADMISSION_RECEIPT_NOT_UNIQUE")
        now = _now()
        created_at = int(existing[0].get("created_at", now)) if existing else now
        version = int(existing[0].get("artifact_version", 1)) if existing else 1
        payload = {
            "admission_id": admission_id,
            "release_id": self.release_id,
            "mission_id": mission_id,
            "release_batch_id": release_batch_id,
            "source_commit": source_commit,
            "status": status,
            "reason": reason,
            "provenance_id": provenance_id,
            "scope_snapshot_id": scope_snapshot_id,
            "qualification_receipt_ids": sorted(set(receipt_ids)),
            "hold_reasons": holds,
            "input_digest": input_digest,
            "field_verified": False,
            "bank_final": False,
            "created_at": created_at,
            "updated_at": now,
            "artifact_version": version,
        }
        if existing and self._signature(existing[0]) == self._signature(payload):
            return existing[0]
        if existing:
            payload["artifact_version"] = version + 1
        self.truth.append_atomic(_EVENT, payload)
        rows = self.truth.query(_ARTIFACT, admission_id=admission_id)
        if len(rows) != 1:
            raise ContractError("Q7_ADMISSION_PERSISTENCE_FAILED")
        return rows[0]


install_rc72_q7_admission_overlay()
