"""RC7.2 test-data resource registration and leasing.

N5 owns discovery/construction/verification of DataRefs. This module only owns
runtime reservation semantics: exact verified DataRefs are leased to canonical
WorkItem/Attempt/Worker identities. It never guesses or substitutes another
DataRef when a conflict occurs.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.truth import TruthRuntime

from .models import ContractError
from .truth_overlay import install_rc7_truth_overlay


_DATA_RESOURCE = "rc72_data_resource"
_DATA_LEASE = "rc72_data_lease"
_EVENT_TYPES = {
    "RC72_DATA_RESOURCE_UPSERTED": (_DATA_RESOURCE, "data_ref"),
    "RC72_DATA_LEASE_UPSERTED": (_DATA_LEASE, "data_lease_id"),
}
_BUCKETS = {
    _DATA_RESOURCE: "rc72_data_resources",
    _DATA_LEASE: "rc72_data_leases",
}


class DataAccessMode(str, Enum):
    SHARED_READ = "SHARED_READ"
    EXCLUSIVE_WRITE = "EXCLUSIVE_WRITE"


class DataResourceConflict(ContractError):
    pass


@dataclass(frozen=True)
class DataLeaseGrant:
    data_lease_id: str
    data_ref: str
    mode: DataAccessMode
    expires_at: int


def _now() -> int:
    return int(time.time())


def _new(prefix: str) -> str:
    return "%s-%s" % (prefix, uuid.uuid4().hex[:20])


def _required(out: Dict[str, Any], name: str) -> str:
    return _contracts._require_str(out, name)


def _optional(out: Dict[str, Any], name: str) -> None:
    value = out.get(name)
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise _contracts.DomainValidationError("%s_INVALID" % name.upper())


def _base(payload: Dict[str, Any], artifact_type: str, identity: str) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    out[identity] = _required(out, identity)
    out["release_id"] = _required(out, "release_id")
    out["artifact_type"] = artifact_type
    out["artifact_version"] = _contracts._artifact_version(out)
    return out


def _validate_resource(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, _DATA_RESOURCE, "data_ref")
    out["data_domain"] = _required(out, "data_domain")
    out["metadata_ref"] = _required(out, "metadata_ref")
    if not isinstance(out.get("verified"), bool):
        raise _contracts.DomainValidationError("DATA_RESOURCE_VERIFIED_INVALID")
    if not isinstance(out.get("mutable"), bool):
        raise _contracts.DomainValidationError("DATA_RESOURCE_MUTABLE_INVALID")
    if not isinstance(out.get("created_at"), int) or out["created_at"] < 0:
        raise _contracts.DomainValidationError("DATA_RESOURCE_CREATED_AT_INVALID")
    return out


def _validate_lease(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, _DATA_LEASE, "data_lease_id")
    for name in (
        "data_ref", "mission_id", "workitem_id", "attempt_id", "worker_id",
        "mode", "cleanup_policy", "state",
    ):
        out[name] = _required(out, name)
    try:
        out["mode"] = DataAccessMode(out["mode"].upper()).value
    except ValueError as exc:
        raise _contracts.DomainValidationError("DATA_ACCESS_MODE_INVALID") from exc
    out["state"] = out["state"].upper()
    if out["state"] not in {"ACTIVE", "RELEASED", "EXPIRED"}:
        raise _contracts.DomainValidationError("DATA_LEASE_STATE_INVALID")
    for name in ("issued_at", "expires_at"):
        if not isinstance(out.get(name), int) or out[name] < 0:
            raise _contracts.DomainValidationError("DATA_LEASE_%s_INVALID" % name.upper())
    if out["expires_at"] <= out["issued_at"]:
        raise _contracts.DomainValidationError("DATA_LEASE_WINDOW_INVALID")
    _optional(out, "release_reason")
    _optional(out, "cleanup_evidence_ref")
    released_at = out.get("released_at")
    if released_at is not None and (not isinstance(released_at, int) or released_at < 0):
        raise _contracts.DomainValidationError("DATA_LEASE_RELEASED_AT_INVALID")
    if out["state"] == "RELEASED":
        if released_at is None or not out.get("release_reason") or not out.get("cleanup_evidence_ref"):
            raise _contracts.DomainValidationError("DATA_LEASE_RELEASE_AUDIT_REQUIRED")
    return out


def install_rc72_data_overlay() -> None:
    install_rc7_truth_overlay()
    _contracts.VALIDATORS[_DATA_RESOURCE] = _validate_resource
    _contracts.VALIDATORS[_DATA_LEASE] = _validate_lease
    for artifact_type in (_DATA_RESOURCE, _DATA_LEASE):
        _truth.BUCKETS[artifact_type] = _BUCKETS[artifact_type]
    for event_type, (artifact_type, identity) in _EVENT_TYPES.items():
        _truth.EVENT_TYPES[event_type] = (artifact_type, identity)
        _truth.IDENTITY_FIELDS[artifact_type] = identity


class DataLeaseManager:
    def __init__(self, truth: TruthRuntime, *, release_id: str) -> None:
        install_rc72_data_overlay()
        if not isinstance(release_id, str) or not release_id.strip():
            raise ContractError("DATA_RELEASE_ID_REQUIRED")
        self.truth = truth
        self.release_id = release_id.strip()

    def _append(self, event_type: str, payload: Dict[str, Any]):
        out = dict(payload)
        out["release_id"] = self.release_id
        out.setdefault("artifact_version", 1)
        return self.truth.append_atomic(event_type, out)

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise ContractError("DATA_TRUTH_NOT_UNIQUE:%s:%d" % (artifact_type, len(rows)))
        return rows[0]

    def register_data_ref(
        self,
        *,
        data_ref: str,
        data_domain: str,
        verified: bool,
        mutable: bool,
        metadata_ref: str,
    ) -> None:
        if self.truth.query(_DATA_RESOURCE, data_ref=data_ref):
            raise ContractError("DATA_REF_ALREADY_REGISTERED")
        self._append(
            "RC72_DATA_RESOURCE_UPSERTED",
            {
                "data_ref": data_ref,
                "data_domain": data_domain,
                "verified": verified,
                "mutable": mutable,
                "metadata_ref": metadata_ref,
                "created_at": _now(),
            },
        )

    def _binding(self, *, mission_id: str, workitem_id: str, attempt_id: str, worker_id: str) -> Dict[str, Any]:
        rows = self.truth.query("rc72_workitem_attempt_binding", workitem_id=workitem_id)
        rows = [row for row in rows if row.get("mission_id") == mission_id]
        rows = [row for row in rows if row.get("attempt_id") == attempt_id]
        rows = [row for row in rows if row.get("worker_id") == worker_id]
        if len(rows) != 1:
            raise ContractError("DATA_LEASE_ATTEMPT_BINDING_MISMATCH")
        if rows[0].get("state") not in {"PREPARED", "RUNNING", "EVIDENCE_READY"}:
            raise ContractError("DATA_LEASE_ATTEMPT_NOT_ACTIVE")
        return rows[0]

    def _expire_due(self, now: int) -> None:
        for row in self.truth.query(_DATA_LEASE):
            if row.get("state") != "ACTIVE" or int(row.get("expires_at") or 0) >= now:
                continue
            updated = dict(row)
            updated.pop("artifact_type", None)
            updated["artifact_version"] = int(row.get("artifact_version", 1)) + 1
            updated["state"] = "EXPIRED"
            self.truth.append_atomic("RC72_DATA_LEASE_UPSERTED", updated)

    def _active(self, data_ref: str, now: int) -> List[Dict[str, Any]]:
        self._expire_due(now)
        return [
            row for row in self.truth.query(_DATA_LEASE, data_ref=data_ref)
            if row.get("state") == "ACTIVE" and int(row.get("expires_at") or 0) >= now
        ]

    def acquire(
        self,
        *,
        data_ref: str,
        mission_id: str,
        workitem_id: str,
        attempt_id: str,
        worker_id: str,
        mode: DataAccessMode,
        ttl_seconds: int,
        cleanup_policy: str,
        data_lease_id: Optional[str] = None,
        now: Optional[int] = None,
    ) -> DataLeaseGrant:
        if not isinstance(mode, DataAccessMode):
            mode = DataAccessMode(str(mode).upper())
        for value, name in (
            (data_ref, "data_ref"), (mission_id, "mission_id"), (workitem_id, "workitem_id"),
            (attempt_id, "attempt_id"), (worker_id, "worker_id"), (cleanup_policy, "cleanup_policy"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ContractError("%s_REQUIRED" % name.upper())
        if not isinstance(ttl_seconds, int) or ttl_seconds < 1:
            raise ContractError("DATA_LEASE_TTL_INVALID")
        self._binding(mission_id=mission_id, workitem_id=workitem_id, attempt_id=attempt_id, worker_id=worker_id)
        resource = self._one(_DATA_RESOURCE, data_ref=data_ref)
        if not resource.get("verified"):
            raise ContractError("DATA_REF_NOT_VERIFIED")
        if resource.get("mutable") and mode != DataAccessMode.EXCLUSIVE_WRITE:
            raise ContractError("MUTABLE_DATA_REQUIRES_EXCLUSIVE_WRITE")
        current = _now() if now is None else int(now)
        active = self._active(data_ref, current)
        if mode == DataAccessMode.EXCLUSIVE_WRITE:
            if active:
                raise DataResourceConflict("DATA_RESOURCE_CONFLICT:EXCLUSIVE_OWNER_EXISTS")
        elif any(row.get("mode") == DataAccessMode.EXCLUSIVE_WRITE.value for row in active):
            raise DataResourceConflict("DATA_RESOURCE_CONFLICT:EXCLUSIVE_OWNER_EXISTS")

        lease_id = data_lease_id or _new("DATALEASE")
        if self.truth.query(_DATA_LEASE, data_lease_id=lease_id):
            raise ContractError("DATA_LEASE_ID_CONFLICT")
        expires_at = current + ttl_seconds
        self._append(
            "RC72_DATA_LEASE_UPSERTED",
            {
                "data_lease_id": lease_id,
                "data_ref": data_ref,
                "mission_id": mission_id,
                "workitem_id": workitem_id,
                "attempt_id": attempt_id,
                "worker_id": worker_id,
                "mode": mode.value,
                "cleanup_policy": cleanup_policy,
                "issued_at": current,
                "expires_at": expires_at,
                "state": "ACTIVE",
                "released_at": None,
                "release_reason": None,
                "cleanup_evidence_ref": None,
            },
        )
        return DataLeaseGrant(data_lease_id=lease_id, data_ref=data_ref, mode=mode, expires_at=expires_at)

    def lease(self, data_lease_id: str) -> Dict[str, Any]:
        return self._one(_DATA_LEASE, data_lease_id=data_lease_id)

    def assert_usable(
        self,
        *,
        data_lease_id: str,
        mission_id: str,
        workitem_id: str,
        attempt_id: str,
        worker_id: str,
        data_ref: str,
        now: Optional[int] = None,
    ) -> Dict[str, Any]:
        row = self.lease(data_lease_id)
        if row.get("state") != "ACTIVE":
            raise ContractError("DATA_LEASE_NOT_ACTIVE")
        expected = {
            "mission_id": mission_id,
            "workitem_id": workitem_id,
            "attempt_id": attempt_id,
            "worker_id": worker_id,
            "data_ref": data_ref,
        }
        for field, value in expected.items():
            if row.get(field) != value:
                if field == "attempt_id":
                    raise ContractError("DATA_LEASE_ATTEMPT_MISMATCH")
                if field == "worker_id":
                    raise ContractError("DATA_LEASE_WORKER_MISMATCH")
                if field == "data_ref":
                    raise ContractError("DATA_LEASE_DATA_REF_MISMATCH")
                raise ContractError("DATA_LEASE_%s_MISMATCH" % field.upper())
        current = _now() if now is None else int(now)
        if current > int(row["expires_at"]):
            raise ContractError("DATA_LEASE_EXPIRED")
        self._binding(mission_id=mission_id, workitem_id=workitem_id, attempt_id=attempt_id, worker_id=worker_id)
        resource = self._one(_DATA_RESOURCE, data_ref=data_ref)
        if not resource.get("verified"):
            raise ContractError("DATA_REF_NOT_VERIFIED")
        return row

    def release(
        self,
        data_lease_id: str,
        *,
        cleanup_evidence_ref: str,
        reason: str,
    ) -> None:
        if not isinstance(cleanup_evidence_ref, str) or not cleanup_evidence_ref.strip():
            raise ContractError("DATA_CLEANUP_EVIDENCE_REQUIRED")
        if not isinstance(reason, str) or not reason.strip():
            raise ContractError("DATA_RELEASE_REASON_REQUIRED")
        row = self.lease(data_lease_id)
        if row.get("state") != "ACTIVE":
            raise ContractError("DATA_LEASE_NOT_ACTIVE")
        updated = dict(row)
        updated.pop("artifact_type", None)
        updated["artifact_version"] = int(row.get("artifact_version", 1)) + 1
        updated["state"] = "RELEASED"
        updated["released_at"] = _now()
        updated["release_reason"] = reason
        updated["cleanup_evidence_ref"] = cleanup_evidence_ref
        self.truth.append_atomic("RC72_DATA_LEASE_UPSERTED", updated)


install_rc72_data_overlay()
