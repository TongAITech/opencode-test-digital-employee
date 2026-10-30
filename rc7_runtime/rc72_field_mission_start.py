"""Admission-gated, ReleaseBatch-rooted Field Mission bootstrap for RC7.2.

This is the governed Field ingress for Q7 execution. Callers identify only the
canonical ReleaseBatch and exact source commit; Mission and release identities
are resolved from R1 and cannot be overridden by prompt/caller input.

A Mission may bootstrap only when an exact-lineage rc72_q7_admission receipt for
that Mission + ReleaseBatch + source commit is ADMITTED. HOLD, missing, stale,
or cross-lineage admissions fail closed before any MissionNode side effect.

Successful admission bootstraps the existing RC7.2 N1-N10 state machine and
persists a canonical start receipt binding the bootstrap to the admission. The
receipt is not Q7 PASS and never promotes field_verified or BANK_FINAL.
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.truth import TruthRuntime

from .models import ContractError
from .rc72_domain import AutonomousMissionNode, ReleaseBatch
from .rc72_q7_admission import install_rc72_q7_admission_overlay
from .rc72_state_machine import RC72StateMachine
from .rc72_truth import install_rc72_truth_overlay
from .truth_overlay import install_rc7_truth_overlay


_ARTIFACT = "rc72_field_mission_start_receipt"
_EVENT = "RC72_FIELD_MISSION_START_RECEIPT_UPSERTED"
_BUCKET = "rc72_field_mission_start_receipts"
_STATUS = "BOOTSTRAPPED"
_FORBIDDEN_PROMOTIONS = ("field_verified", "bank_final", "q7_pass", "q7_status")


class FieldMissionStartError(ContractError):
    pass


def _now() -> int:
    return int(time.time())


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FieldMissionStartError("FIELD_MISSION_%s_REQUIRED" % name.upper())
    return value.strip()


def _string_list(value: Any, name: str) -> List[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise _contracts.DomainValidationError("FIELD_MISSION_%s_INVALID" % name.upper())
    if len(set(value)) != len(value):
        raise _contracts.DomainValidationError("FIELD_MISSION_%s_DUPLICATE" % name.upper())
    return list(value)


def validate_rc72_field_mission_start_receipt(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "start_receipt_id", "release_id", "mission_id", "release_batch_id",
        "source_commit", "q7_admission_id", "n1_mission_node_id", "status",
    ):
        out[name] = _contracts._require_str(out, name)
    out["mission_node_ids"] = _string_list(out.get("mission_node_ids"), "mission_node_ids")
    if len(out["mission_node_ids"]) != len(AutonomousMissionNode.ordered()):
        raise _contracts.DomainValidationError("FIELD_MISSION_CANONICAL_NODE_COUNT_INVALID")
    if out["n1_mission_node_id"] != out["mission_node_ids"][0]:
        raise _contracts.DomainValidationError("FIELD_MISSION_N1_LINEAGE_INVALID")
    if out["status"].upper() != _STATUS:
        raise _contracts.DomainValidationError("FIELD_MISSION_STATUS_INVALID")
    out["status"] = _STATUS
    for name in _FORBIDDEN_PROMOTIONS:
        if name in out:
            raise _contracts.DomainValidationError("FIELD_MISSION_PROMOTION_FIELD_FORBIDDEN:%s" % name)
    for name in ("created_at", "updated_at"):
        value = out.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise _contracts.DomainValidationError("FIELD_MISSION_%s_INVALID" % name.upper())
    version = out.get("artifact_version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError("FIELD_MISSION_ARTIFACT_VERSION_INVALID")
    out["artifact_version"] = version
    out["artifact_type"] = _ARTIFACT
    return out


def install_rc72_field_mission_start_overlay() -> None:
    install_rc7_truth_overlay()
    install_rc72_truth_overlay()
    install_rc72_q7_admission_overlay()
    _contracts.VALIDATORS[_ARTIFACT] = validate_rc72_field_mission_start_receipt
    _truth.BUCKETS[_ARTIFACT] = _BUCKET
    _truth.IDENTITY_FIELDS[_ARTIFACT] = "start_receipt_id"
    _truth.EVENT_TYPES[_EVENT] = (_ARTIFACT, "start_receipt_id")


def _ensure_bucket(truth: TruthRuntime) -> None:
    projection = getattr(truth, "projection", None)
    if projection is None:
        return
    if not hasattr(projection, _BUCKET):
        setattr(projection, _BUCKET, {})
    versions = getattr(projection, "_versions", None)
    if isinstance(versions, dict):
        versions.setdefault(_ARTIFACT, {})


class ReleaseBatchFieldMissionLauncher:
    """Bootstrap canonical N1-N10 only after exact Q7 admission."""

    def __init__(self, truth: TruthRuntime, *, source_commit: str) -> None:
        install_rc72_field_mission_start_overlay()
        _ensure_bucket(truth)
        self.truth = truth
        self.source_commit = _required(source_commit, "source_commit")

    @staticmethod
    def _start_receipt_id(mission_id: str, release_batch_id: str, source_commit: str) -> str:
        raw = "\x1f".join((mission_id, release_batch_id, source_commit))
        return "FMSTART-%s" % hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    def _batch(self, release_batch_id: str) -> Dict[str, Any]:
        release_batch_id = _required(release_batch_id, "release_batch_id")
        rows = self.truth.query("rc72_release_batch", release_batch_id=release_batch_id)
        if len(rows) != 1:
            raise FieldMissionStartError("FIELD_MISSION_RELEASE_BATCH_NOT_UNIQUE:%d" % len(rows))
        row = rows[0]
        _required(row.get("mission_id"), "mission_id")
        _required(row.get("release_id"), "release_id")
        return row

    def _admission(self, batch: Mapping[str, Any]) -> Dict[str, Any]:
        mission_id = str(batch["mission_id"])
        release_id = str(batch["release_id"])
        release_batch_id = str(batch["release_batch_id"])
        batch_rows = self.truth.query("rc72_q7_admission", release_batch_id=release_batch_id)
        exact = [
            row for row in batch_rows
            if row.get("mission_id") == mission_id
            and row.get("release_id") == release_id
            and row.get("source_commit") == self.source_commit
        ]
        if len(exact) != 1:
            if not exact and any(row.get("source_commit") != self.source_commit for row in batch_rows):
                raise FieldMissionStartError("FIELD_MISSION_EXACT_SOURCE_COMMIT_ADMISSION_REQUIRED")
            raise FieldMissionStartError("FIELD_MISSION_Q7_ADMISSION_NOT_UNIQUE:%d" % len(exact))
        admission = exact[0]
        if admission.get("status") != "ADMITTED":
            raise FieldMissionStartError("FIELD_MISSION_Q7_ADMISSION_HOLD")
        return admission

    @staticmethod
    def _entity(batch: Mapping[str, Any]) -> ReleaseBatch:
        return ReleaseBatch(
            release_batch_id=str(batch["release_batch_id"]),
            mission_id=str(batch["mission_id"]),
            name=str(batch["name"]),
            planned_release_time=batch.get("planned_release_time"),
            version_ids=list(batch.get("version_ids") or []),
            application_ids=list(batch.get("application_ids") or []),
            requirement_ids=list(batch.get("requirement_ids") or []),
            state=str(batch.get("state") or "REGISTERED"),
            readiness=str(batch.get("readiness") or "UNKNOWN"),
            created_at=int(batch.get("created_at") or 0),
            updated_at=int(batch.get("updated_at") or 0),
        )

    @staticmethod
    def _receipt_signature(payload: Mapping[str, Any]) -> Dict[str, Any]:
        return {
            "release_id": payload.get("release_id"),
            "mission_id": payload.get("mission_id"),
            "release_batch_id": payload.get("release_batch_id"),
            "source_commit": payload.get("source_commit"),
            "q7_admission_id": payload.get("q7_admission_id"),
            "n1_mission_node_id": payload.get("n1_mission_node_id"),
            "mission_node_ids": list(payload.get("mission_node_ids") or []),
            "status": payload.get("status"),
        }

    def start(self, *, release_batch_id: str) -> Dict[str, Any]:
        # All fail-closed admission and preflight checks happen before MissionNode writes.
        batch = self._batch(release_batch_id)
        admission = self._admission(batch)
        mission_id = str(batch["mission_id"])
        release_id = str(batch["release_id"])
        scope_ref = "release-batch://%s" % str(batch["release_batch_id"])
        before = self.truth.query("rc72_mission_node", mission_id=mission_id)
        if any(row.get("scope_ref") != scope_ref for row in before):
            raise FieldMissionStartError("FIELD_MISSION_EXISTING_NODE_SCOPE_CONFLICT")

        state_machine = RC72StateMachine(self.truth, release_id=release_id)
        state_machine.bootstrap_release_batch(self._entity(batch))

        ordered_nodes: List[Dict[str, Any]] = []
        for node_type in AutonomousMissionNode.ordered():
            node = state_machine.node_by_type(mission_id, node_type)
            if node.get("scope_ref") != scope_ref:
                raise FieldMissionStartError("FIELD_MISSION_NODE_SCOPE_LINEAGE_MISMATCH")
            ordered_nodes.append(node)
        node_ids = [str(node["mission_node_id"]) for node in ordered_nodes]

        receipt_id = self._start_receipt_id(mission_id, str(batch["release_batch_id"]), self.source_commit)
        existing = self.truth.query(_ARTIFACT, start_receipt_id=receipt_id)
        if len(existing) > 1:
            raise FieldMissionStartError("FIELD_MISSION_START_RECEIPT_NOT_UNIQUE")
        now = _now()
        payload = {
            "start_receipt_id": receipt_id,
            "release_id": release_id,
            "mission_id": mission_id,
            "release_batch_id": str(batch["release_batch_id"]),
            "source_commit": self.source_commit,
            "q7_admission_id": str(admission["admission_id"]),
            "n1_mission_node_id": node_ids[0],
            "mission_node_ids": node_ids,
            "status": _STATUS,
            "created_at": int(existing[0].get("created_at", now)) if existing else now,
            "updated_at": now,
            "artifact_version": int(existing[0].get("artifact_version", 1)) if existing else 1,
        }
        if existing:
            if self._receipt_signature(existing[0]) != self._receipt_signature(payload):
                raise FieldMissionStartError("FIELD_MISSION_START_RECEIPT_CONFLICT")
            receipt = existing[0]
        else:
            self.truth.append_atomic(_EVENT, payload)
            rows = self.truth.query(_ARTIFACT, start_receipt_id=receipt_id)
            if len(rows) != 1:
                raise FieldMissionStartError("FIELD_MISSION_START_RECEIPT_PERSISTENCE_FAILED")
            receipt = rows[0]

        return {
            "status": "RESUMED" if before else "STARTED",
            "release_batch_id": str(batch["release_batch_id"]),
            "release_id": release_id,
            "mission_id": mission_id,
            "source_commit": self.source_commit,
            "q7_admission_id": str(admission["admission_id"]),
            "start_receipt_id": str(receipt["start_receipt_id"]),
            "n1_mission_node_id": node_ids[0],
            "mission_node_ids": node_ids,
        }


def start_release_batch_field_mission(
    *,
    r1_path: Path,
    release_batch_id: str,
    source_commit: str,
) -> Dict[str, Any]:
    """File-backed governed entrypoint; Mission/release are never caller inputs."""
    install_rc72_field_mission_start_overlay()
    truth = TruthRuntime(r1_path.resolve())
    return ReleaseBatchFieldMissionLauncher(
        truth,
        source_commit=source_commit,
    ).start(release_batch_id=release_batch_id)


install_rc72_field_mission_start_overlay()
