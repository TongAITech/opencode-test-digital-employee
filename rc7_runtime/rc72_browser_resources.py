"""RC7.2 browser resource pool and lease ownership.

Browser control is a runtime resource, not a shared global singleton.  This
module persists BrowserInstance/BrowserLease metadata in canonical R1 and binds
leases to the existing WorkItemAttemptBinding.  It deliberately does not launch
or automate a real browser; BSK/CDP process integration remains a Field/runtime
adapter concern built on top of these ownership contracts.
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


_BROWSER_INSTANCE = "rc72_browser_instance"
_BROWSER_LEASE = "rc72_browser_lease"

_EVENT_TYPES = {
    "RC72_BROWSER_INSTANCE_UPSERTED": (_BROWSER_INSTANCE, "browser_instance_id"),
    "RC72_BROWSER_LEASE_UPSERTED": (_BROWSER_LEASE, "browser_lease_id"),
}
_BUCKETS = {
    _BROWSER_INSTANCE: "rc72_browser_instances",
    _BROWSER_LEASE: "rc72_browser_leases",
}


class BrowserAccessMode(str, Enum):
    READ = "READ"
    WRITE = "WRITE"


class BrowserResourceConflict(ContractError):
    pass


@dataclass(frozen=True)
class BrowserLeaseGrant:
    browser_lease_id: str
    browser_instance_id: str
    access_mode: BrowserAccessMode
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


def _validate_instance(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, _BROWSER_INSTANCE, "browser_instance_id")
    for name in ("profile_dir", "cdp_endpoint", "bsk_endpoint", "state"):
        out[name] = _required(out, name)
    out["state"] = out["state"].upper()
    if out["state"] not in {"READY", "RETIRED", "BROKEN"}:
        raise _contracts.DomainValidationError("BROWSER_INSTANCE_STATE_INVALID")
    _optional(out, "auth_asset_ref")
    if not isinstance(out.get("created_at"), int) or out["created_at"] < 0:
        raise _contracts.DomainValidationError("BROWSER_INSTANCE_CREATED_AT_INVALID")
    return out


def _validate_lease(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, _BROWSER_LEASE, "browser_lease_id")
    for name in (
        "browser_instance_id", "mission_id", "workitem_id", "attempt_id", "worker_id",
        "access_mode", "purpose", "state",
    ):
        out[name] = _required(out, name)
    try:
        out["access_mode"] = BrowserAccessMode(out["access_mode"].upper()).value
    except ValueError as exc:
        raise _contracts.DomainValidationError("BROWSER_ACCESS_MODE_INVALID") from exc
    out["state"] = out["state"].upper()
    if out["state"] not in {"ACTIVE", "RELEASED", "EXPIRED"}:
        raise _contracts.DomainValidationError("BROWSER_LEASE_STATE_INVALID")
    for name in ("issued_at", "expires_at"):
        if not isinstance(out.get(name), int) or out[name] < 0:
            raise _contracts.DomainValidationError("BROWSER_LEASE_%s_INVALID" % name.upper())
    if out["expires_at"] <= out["issued_at"]:
        raise _contracts.DomainValidationError("BROWSER_LEASE_WINDOW_INVALID")
    _optional(out, "release_reason")
    released_at = out.get("released_at")
    if released_at is not None and (not isinstance(released_at, int) or released_at < 0):
        raise _contracts.DomainValidationError("BROWSER_LEASE_RELEASED_AT_INVALID")
    if out["state"] == "RELEASED" and (released_at is None or not out.get("release_reason")):
        raise _contracts.DomainValidationError("BROWSER_LEASE_RELEASE_AUDIT_REQUIRED")
    return out


def install_rc72_browser_overlay() -> None:
    install_rc7_truth_overlay()
    _contracts.VALIDATORS[_BROWSER_INSTANCE] = _validate_instance
    _contracts.VALIDATORS[_BROWSER_LEASE] = _validate_lease
    for artifact_type in (_BROWSER_INSTANCE, _BROWSER_LEASE):
        _truth.BUCKETS[artifact_type] = _BUCKETS[artifact_type]
    for event_type, (artifact_type, identity) in _EVENT_TYPES.items():
        _truth.EVENT_TYPES[event_type] = (artifact_type, identity)
        _truth.IDENTITY_FIELDS[artifact_type] = identity


class BrowserPool:
    def __init__(self, truth: TruthRuntime, *, release_id: str) -> None:
        install_rc72_browser_overlay()
        if not isinstance(release_id, str) or not release_id.strip():
            raise ContractError("BROWSER_RELEASE_ID_REQUIRED")
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
            raise ContractError("BROWSER_TRUTH_NOT_UNIQUE:%s:%d" % (artifact_type, len(rows)))
        return rows[0]

    def register_instance(
        self,
        *,
        browser_instance_id: str,
        profile_dir: str,
        cdp_endpoint: str,
        bsk_endpoint: str,
        auth_asset_ref: Optional[str] = None,
    ) -> None:
        for value, name in (
            (browser_instance_id, "browser_instance_id"),
            (profile_dir, "profile_dir"),
            (cdp_endpoint, "cdp_endpoint"),
            (bsk_endpoint, "bsk_endpoint"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ContractError("%s_REQUIRED" % name.upper())
        if self.truth.query(_BROWSER_INSTANCE, browser_instance_id=browser_instance_id):
            raise ContractError("BROWSER_INSTANCE_ID_CONFLICT")
        for row in self.truth.query(_BROWSER_INSTANCE):
            if row.get("profile_dir") == profile_dir or row.get("cdp_endpoint") == cdp_endpoint or row.get("bsk_endpoint") == bsk_endpoint:
                raise ContractError("BROWSER_INSTANCE_RESOURCE_IDENTITY_CONFLICT")
        self._append(
            "RC72_BROWSER_INSTANCE_UPSERTED",
            {
                "browser_instance_id": browser_instance_id,
                "profile_dir": profile_dir,
                "cdp_endpoint": cdp_endpoint,
                "bsk_endpoint": bsk_endpoint,
                "auth_asset_ref": auth_asset_ref,
                "state": "READY",
                "created_at": _now(),
            },
        )

    def _binding(self, *, mission_id: str, workitem_id: str, attempt_id: str, worker_id: str) -> Dict[str, Any]:
        rows = self.truth.query("rc72_workitem_attempt_binding", workitem_id=workitem_id)
        rows = [row for row in rows if row.get("mission_id") == mission_id]
        rows = [row for row in rows if row.get("attempt_id") == attempt_id]
        rows = [row for row in rows if row.get("worker_id") == worker_id]
        if len(rows) != 1:
            raise ContractError("BROWSER_LEASE_ATTEMPT_BINDING_MISMATCH")
        if rows[0].get("state") not in {"PREPARED", "RUNNING", "EVIDENCE_READY"}:
            raise ContractError("BROWSER_LEASE_ATTEMPT_NOT_ACTIVE")
        return rows[0]

    def _expire_due(self, now: int) -> None:
        for row in self.truth.query(_BROWSER_LEASE):
            if row.get("state") != "ACTIVE" or int(row.get("expires_at") or 0) >= now:
                continue
            updated = dict(row)
            updated.pop("artifact_type", None)
            updated["artifact_version"] = int(row.get("artifact_version", 1)) + 1
            updated["state"] = "EXPIRED"
            self.truth.append_atomic("RC72_BROWSER_LEASE_UPSERTED", updated)

    def _active_for_instance(self, browser_instance_id: str, now: int) -> List[Dict[str, Any]]:
        self._expire_due(now)
        return [
            row for row in self.truth.query(_BROWSER_LEASE, browser_instance_id=browser_instance_id)
            if row.get("state") == "ACTIVE" and int(row.get("expires_at") or 0) >= now
        ]

    def acquire(
        self,
        *,
        mission_id: str,
        workitem_id: str,
        attempt_id: str,
        worker_id: str,
        access_mode: BrowserAccessMode,
        purpose: str,
        ttl_seconds: int,
        now: Optional[int] = None,
    ) -> BrowserLeaseGrant:
        if not isinstance(access_mode, BrowserAccessMode):
            access_mode = BrowserAccessMode(str(access_mode).upper())
        if str(purpose or "").upper() == "CAPTAIN" or str(worker_id or "").upper() == "CAPTAIN":
            raise ContractError("CAPTAIN_BROWSER_CONTROL_FORBIDDEN")
        for value, name in (
            (mission_id, "mission_id"), (workitem_id, "workitem_id"), (attempt_id, "attempt_id"),
            (worker_id, "worker_id"), (purpose, "purpose"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ContractError("%s_REQUIRED" % name.upper())
        if not isinstance(ttl_seconds, int) or ttl_seconds < 1:
            raise ContractError("BROWSER_LEASE_TTL_INVALID")
        self._binding(mission_id=mission_id, workitem_id=workitem_id, attempt_id=attempt_id, worker_id=worker_id)
        current = _now() if now is None else int(now)

        candidates = sorted(
            [row for row in self.truth.query(_BROWSER_INSTANCE) if row.get("state") == "READY"],
            key=lambda row: row["browser_instance_id"],
        )
        selected = None
        for instance in candidates:
            active = self._active_for_instance(instance["browser_instance_id"], current)
            if access_mode == BrowserAccessMode.WRITE and any(row.get("access_mode") == "WRITE" for row in active):
                continue
            selected = instance
            break
        if selected is None:
            raise BrowserResourceConflict("RESOURCE_CONFLICT:BROWSER_%s_UNAVAILABLE" % access_mode.value)

        lease_id = _new("BRLEASE")
        expires_at = current + ttl_seconds
        self._append(
            "RC72_BROWSER_LEASE_UPSERTED",
            {
                "browser_lease_id": lease_id,
                "browser_instance_id": selected["browser_instance_id"],
                "mission_id": mission_id,
                "workitem_id": workitem_id,
                "attempt_id": attempt_id,
                "worker_id": worker_id,
                "access_mode": access_mode.value,
                "purpose": purpose,
                "issued_at": current,
                "expires_at": expires_at,
                "state": "ACTIVE",
                "released_at": None,
                "release_reason": None,
            },
        )
        return BrowserLeaseGrant(
            browser_lease_id=lease_id,
            browser_instance_id=selected["browser_instance_id"],
            access_mode=access_mode,
            expires_at=expires_at,
        )

    def lease(self, browser_lease_id: str) -> Dict[str, Any]:
        return self._one(_BROWSER_LEASE, browser_lease_id=browser_lease_id)

    def assert_usable(
        self,
        *,
        browser_lease_id: str,
        mission_id: str,
        workitem_id: str,
        attempt_id: str,
        worker_id: str,
        access_mode: BrowserAccessMode,
        now: Optional[int] = None,
    ) -> Dict[str, Any]:
        row = self.lease(browser_lease_id)
        if row.get("state") != "ACTIVE":
            raise ContractError("BROWSER_LEASE_NOT_ACTIVE")
        expected = {
            "mission_id": mission_id,
            "workitem_id": workitem_id,
            "attempt_id": attempt_id,
            "worker_id": worker_id,
        }
        for field, value in expected.items():
            if row.get(field) != value:
                if field == "attempt_id":
                    raise ContractError("BROWSER_LEASE_ATTEMPT_MISMATCH")
                if field == "worker_id":
                    raise ContractError("BROWSER_LEASE_WORKER_MISMATCH")
                raise ContractError("BROWSER_LEASE_%s_MISMATCH" % field.upper())
        mode = access_mode if isinstance(access_mode, BrowserAccessMode) else BrowserAccessMode(str(access_mode).upper())
        if row.get("access_mode") != mode.value:
            raise ContractError("BROWSER_LEASE_ACCESS_MODE_MISMATCH")
        current = _now() if now is None else int(now)
        if current > int(row["expires_at"]):
            raise ContractError("BROWSER_LEASE_EXPIRED")
        self._binding(mission_id=mission_id, workitem_id=workitem_id, attempt_id=attempt_id, worker_id=worker_id)
        return row

    def release(self, browser_lease_id: str, *, reason: str) -> None:
        if not isinstance(reason, str) or not reason.strip():
            raise ContractError("BROWSER_RELEASE_REASON_REQUIRED")
        row = self.lease(browser_lease_id)
        if row.get("state") != "ACTIVE":
            raise ContractError("BROWSER_LEASE_NOT_ACTIVE")
        updated = dict(row)
        updated.pop("artifact_type", None)
        updated["artifact_version"] = int(row.get("artifact_version", 1)) + 1
        updated["state"] = "RELEASED"
        updated["released_at"] = _now()
        updated["release_reason"] = reason
        self.truth.append_atomic("RC72_BROWSER_LEASE_UPSERTED", updated)


install_rc72_browser_overlay()
