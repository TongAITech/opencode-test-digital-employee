"""RC7.2 dynamic least-privilege capability broker.

The broker never grants Full Access and never copies coordinator credentials.
It reuses the existing HMAC-signed TaskLease authority: a safe grant creates a
new, short-lived child TaskLease for the same worker and canonical task scope.
Request/decision/lease audit metadata is persisted in the same R1, while the
TaskLease signature and signing key remain inside AuthorityRuntime.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Mapping, Optional

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.authority import AuthorityError
from rc6_runtime.truth import TruthRuntime

from .authority import RC7AuthorityRuntime
from .models import ContractError
from .truth_overlay import install_rc7_truth_overlay


_CAPABILITY_REQUEST = "rc72_capability_request"
_CAPABILITY_DECISION = "rc72_capability_decision"
_CAPABILITY_LEASE = "rc72_capability_lease"

_EVENT_TYPES = {
    "RC72_CAPABILITY_REQUEST_UPSERTED": (_CAPABILITY_REQUEST, "request_id"),
    "RC72_CAPABILITY_DECISION_UPSERTED": (_CAPABILITY_DECISION, "request_id"),
    "RC72_CAPABILITY_LEASE_UPSERTED": (_CAPABILITY_LEASE, "capability_lease_id"),
}
_BUCKETS = {
    _CAPABILITY_REQUEST: "rc72_capability_requests",
    _CAPABILITY_DECISION: "rc72_capability_decisions",
    _CAPABILITY_LEASE: "rc72_capability_leases",
}


class CapabilityDecision(str, Enum):
    AUTO_GRANT_TEMP_LEASE = "AUTO_GRANT_TEMP_LEASE"
    DELEGATE_TO_SPECIALIST = "DELEGATE_TO_SPECIALIST"
    HUMAN_GATE = "HUMAN_GATE"
    DENY = "DENY"


@dataclass(frozen=True)
class CapabilityPolicyRule:
    decision: CapabilityDecision
    max_ttl_seconds: int = 300
    delegate_role: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.decision, CapabilityDecision):
            object.__setattr__(self, "decision", CapabilityDecision(str(self.decision)))
        if not isinstance(self.max_ttl_seconds, int) or self.max_ttl_seconds < 1:
            raise ContractError("CAPABILITY_POLICY_TTL_INVALID")
        if self.decision == CapabilityDecision.DELEGATE_TO_SPECIALIST:
            if not isinstance(self.delegate_role, str) or not self.delegate_role.strip():
                raise ContractError("CAPABILITY_POLICY_DELEGATE_ROLE_REQUIRED")


@dataclass(frozen=True)
class CapabilityBrokerResult:
    request_id: str
    decision: CapabilityDecision
    capability_lease_id: Optional[str]
    signed_task_lease_id: Optional[str]
    delegate_role: Optional[str]


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
    for name in (identity, "mission_id", "release_id"):
        out[name] = _required(out, name)
    out["artifact_type"] = artifact_type
    out["artifact_version"] = _contracts._artifact_version(out)
    return out


def _validate_request(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, _CAPABILITY_REQUEST, "request_id")
    for name in (
        "workitem_id", "attempt_id", "worker_id", "parent_task_lease_id",
        "requested_capability", "reason", "state",
    ):
        out[name] = _required(out, name)
    out["state"] = out["state"].upper()
    if out["state"] != "REQUESTED":
        raise _contracts.DomainValidationError("CAPABILITY_REQUEST_STATE_INVALID")
    if not isinstance(out.get("created_at"), int) or out["created_at"] < 0:
        raise _contracts.DomainValidationError("CAPABILITY_REQUEST_CREATED_AT_INVALID")
    return out


def _validate_decision(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, _CAPABILITY_DECISION, "request_id")
    for name in ("workitem_id", "attempt_id", "worker_id", "requested_capability", "decision", "reason"):
        out[name] = _required(out, name)
    try:
        CapabilityDecision(out["decision"])
    except ValueError as exc:
        raise _contracts.DomainValidationError("CAPABILITY_DECISION_INVALID") from exc
    _optional(out, "delegate_role")
    _optional(out, "capability_lease_id")
    if not isinstance(out.get("decided_at"), int) or out["decided_at"] < 0:
        raise _contracts.DomainValidationError("CAPABILITY_DECISION_AT_INVALID")
    return out


def _validate_lease(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, _CAPABILITY_LEASE, "capability_lease_id")
    for name in (
        "request_id", "workitem_id", "attempt_id", "worker_id", "parent_task_lease_id",
        "signed_task_lease_id", "requested_capability", "scope_ref", "state",
    ):
        out[name] = _required(out, name)
    out["state"] = out["state"].upper()
    if out["state"] not in {"ACTIVE", "REVOKED"}:
        raise _contracts.DomainValidationError("CAPABILITY_LEASE_STATE_INVALID")
    for name in ("issued_at", "expires_at"):
        if not isinstance(out.get(name), int) or out[name] < 0:
            raise _contracts.DomainValidationError("CAPABILITY_LEASE_%s_INVALID" % name.upper())
    if out["expires_at"] <= out["issued_at"]:
        raise _contracts.DomainValidationError("CAPABILITY_LEASE_WINDOW_INVALID")
    _optional(out, "revoked_reason")
    revoked_at = out.get("revoked_at")
    if revoked_at is not None and (not isinstance(revoked_at, int) or revoked_at < 0):
        raise _contracts.DomainValidationError("CAPABILITY_LEASE_REVOKED_AT_INVALID")
    if out["state"] == "REVOKED" and (revoked_at is None or not out.get("revoked_reason")):
        raise _contracts.DomainValidationError("REVOKED_CAPABILITY_LEASE_AUDIT_REQUIRED")
    # Secrets/signatures never belong in R1 capability metadata.
    forbidden = {"signature", "signing_key", "captain_token", "captain_credential", "full_access"}
    if forbidden.intersection(out):
        raise _contracts.DomainValidationError("CAPABILITY_LEASE_SECRET_FIELD_FORBIDDEN")
    return out


def install_rc72_capability_overlay() -> None:
    install_rc7_truth_overlay()
    validators = {
        _CAPABILITY_REQUEST: _validate_request,
        _CAPABILITY_DECISION: _validate_decision,
        _CAPABILITY_LEASE: _validate_lease,
    }
    for artifact_type, validator in validators.items():
        _contracts.VALIDATORS[artifact_type] = validator
        _truth.BUCKETS[artifact_type] = _BUCKETS[artifact_type]
    for event_type, (artifact_type, identity) in _EVENT_TYPES.items():
        _truth.EVENT_TYPES[event_type] = (artifact_type, identity)
        _truth.IDENTITY_FIELDS[artifact_type] = identity


class CapabilityBroker:
    def __init__(
        self,
        truth: TruthRuntime,
        *,
        release_id: str,
        authority: RC7AuthorityRuntime,
        policies: Mapping[str, CapabilityPolicyRule],
    ) -> None:
        install_rc72_capability_overlay()
        if not isinstance(release_id, str) or not release_id.strip():
            raise ContractError("CAPABILITY_RELEASE_ID_REQUIRED")
        if not isinstance(authority, RC7AuthorityRuntime):
            raise ContractError("CAPABILITY_BROKER_REQUIRES_RC7_AUTHORITY")
        self.truth = truth
        self.release_id = release_id.strip()
        self.authority = authority
        self.policies = dict(policies)

    def _append(self, event_type: str, payload: Dict[str, Any]):
        out = dict(payload)
        out["release_id"] = self.release_id
        out.setdefault("artifact_version", 1)
        return self.truth.append_atomic(event_type, out)

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise ContractError("CAPABILITY_TRUTH_NOT_UNIQUE:%s:%d" % (artifact_type, len(rows)))
        return rows[0]

    @staticmethod
    def _exact_capability(value: str) -> str:
        capability = str(value or "").strip()
        lowered = capability.lower()
        if not capability or "*" in capability or lowered in {"full_access", "full-access", "all", "root"}:
            raise ContractError("EXACT_CAPABILITY_REQUIRED")
        return capability

    def _binding(
        self,
        *,
        mission_id: str,
        workitem_id: str,
        attempt_id: str,
        worker_id: str,
        parent_task_lease_id: str,
    ) -> Dict[str, Any]:
        rows = self.truth.query("rc72_workitem_attempt_binding", workitem_id=workitem_id)
        rows = [row for row in rows if row.get("mission_id") == mission_id]
        rows = [row for row in rows if row.get("attempt_id") == attempt_id]
        rows = [row for row in rows if row.get("worker_id") == worker_id]
        rows = [row for row in rows if row.get("task_lease_ref") == parent_task_lease_id]
        if len(rows) != 1:
            raise ContractError("CAPABILITY_REQUEST_ATTEMPT_BINDING_MISMATCH")
        if rows[0].get("state") not in {"PREPARED", "RUNNING", "EVIDENCE_READY"}:
            raise ContractError("CAPABILITY_REQUEST_ATTEMPT_NOT_ACTIVE")
        return rows[0]

    def request(
        self,
        *,
        request_id: str,
        mission_id: str,
        workitem_id: str,
        attempt_id: str,
        worker_id: str,
        parent_task_lease_id: str,
        requested_capability: str,
        reason: str,
    ) -> CapabilityBrokerResult:
        for value, name in (
            (request_id, "request_id"), (mission_id, "mission_id"), (workitem_id, "workitem_id"),
            (attempt_id, "attempt_id"), (worker_id, "worker_id"),
            (parent_task_lease_id, "parent_task_lease_id"), (reason, "reason"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ContractError("%s_REQUIRED" % name.upper())
        capability = self._exact_capability(requested_capability)
        binding = self._binding(
            mission_id=mission_id,
            workitem_id=workitem_id,
            attempt_id=attempt_id,
            worker_id=worker_id,
            parent_task_lease_id=parent_task_lease_id,
        )
        parent = self.authority.get_lease(parent_task_lease_id)
        identity = self.authority.get_identity(worker_id)
        self.authority._validate_lease(identity, parent, None)
        if parent.worker_id != worker_id:
            raise ContractError("CAPABILITY_REQUEST_PARENT_WORKER_MISMATCH")
        valid_scopes = {"task:%s" % workitem_id, str(binding.get("etu_id") or "")}
        if parent.scope_ref not in valid_scopes:
            raise ContractError("CAPABILITY_REQUEST_PARENT_SCOPE_MISMATCH")

        now = _now()
        self._append(
            "RC72_CAPABILITY_REQUEST_UPSERTED",
            {
                "request_id": request_id,
                "mission_id": mission_id,
                "workitem_id": workitem_id,
                "attempt_id": attempt_id,
                "worker_id": worker_id,
                "parent_task_lease_id": parent_task_lease_id,
                "requested_capability": capability,
                "reason": reason,
                "state": "REQUESTED",
                "created_at": now,
            },
        )

        rule = self.policies.get(capability, CapabilityPolicyRule(CapabilityDecision.DENY))
        capability_lease_id: Optional[str] = None
        signed_task_lease_id: Optional[str] = None
        decision_reason = "policy:%s" % rule.decision.value

        if rule.decision == CapabilityDecision.AUTO_GRANT_TEMP_LEASE:
            remaining = parent.expires_at - now
            ttl = min(rule.max_ttl_seconds, remaining)
            if ttl < 1:
                raise ContractError("CAPABILITY_PARENT_LEASE_EXPIRED")
            child = self.authority.issue_lease(
                worker_id,
                parent.scope_ref,
                parent.allowed_artifact_types,
                tuple(sorted(set(parent.allowed_tools) | {capability})),
                ttl_seconds=ttl,
            )
            capability_lease_id = _new("CAPLEASE")
            signed_task_lease_id = child.lease_id
            self._append(
                "RC72_CAPABILITY_LEASE_UPSERTED",
                {
                    "capability_lease_id": capability_lease_id,
                    "request_id": request_id,
                    "mission_id": mission_id,
                    "workitem_id": workitem_id,
                    "attempt_id": attempt_id,
                    "worker_id": worker_id,
                    "parent_task_lease_id": parent_task_lease_id,
                    "signed_task_lease_id": child.lease_id,
                    "requested_capability": capability,
                    "scope_ref": child.scope_ref,
                    "issued_at": child.issued_at,
                    "expires_at": child.expires_at,
                    "state": "ACTIVE",
                    "revoked_at": None,
                    "revoked_reason": None,
                },
            )

        self._append(
            "RC72_CAPABILITY_DECISION_UPSERTED",
            {
                "request_id": request_id,
                "mission_id": mission_id,
                "workitem_id": workitem_id,
                "attempt_id": attempt_id,
                "worker_id": worker_id,
                "requested_capability": capability,
                "decision": rule.decision.value,
                "reason": decision_reason,
                "delegate_role": rule.delegate_role,
                "capability_lease_id": capability_lease_id,
                "decided_at": now,
            },
        )
        return CapabilityBrokerResult(
            request_id=request_id,
            decision=rule.decision,
            capability_lease_id=capability_lease_id,
            signed_task_lease_id=signed_task_lease_id,
            delegate_role=rule.delegate_role,
        )

    def assert_capability_lease_usable(
        self,
        *,
        capability_lease_id: str,
        mission_id: str,
        workitem_id: str,
        attempt_id: str,
        worker_id: str,
        now: Optional[int] = None,
    ) -> Dict[str, Any]:
        row = self._one(_CAPABILITY_LEASE, capability_lease_id=capability_lease_id)
        if row.get("state") != "ACTIVE":
            raise ContractError("CAPABILITY_LEASE_NOT_ACTIVE")
        expected = {
            "mission_id": mission_id,
            "workitem_id": workitem_id,
            "attempt_id": attempt_id,
            "worker_id": worker_id,
        }
        for field, value in expected.items():
            if row.get(field) != value:
                if field == "attempt_id":
                    raise ContractError("CAPABILITY_REQUEST_ATTEMPT_MISMATCH")
                raise ContractError("CAPABILITY_LEASE_%s_MISMATCH" % field.upper())
        current = _now() if now is None else int(now)
        if current > int(row["expires_at"]):
            raise ContractError("CAPABILITY_LEASE_EXPIRED")
        self._binding(
            mission_id=mission_id,
            workitem_id=workitem_id,
            attempt_id=attempt_id,
            worker_id=worker_id,
            parent_task_lease_id=str(row["parent_task_lease_id"]),
        )
        self.authority.authorize_tool(
            worker_id,
            str(row["signed_task_lease_id"]),
            str(row["requested_capability"]),
            now=current,
        )
        return row

    def revoke(self, capability_lease_id: str, *, reason: str) -> None:
        if not isinstance(reason, str) or not reason.strip():
            raise ContractError("CAPABILITY_REVOKE_REASON_REQUIRED")
        row = self._one(_CAPABILITY_LEASE, capability_lease_id=capability_lease_id)
        if row.get("state") != "ACTIVE":
            raise ContractError("CAPABILITY_LEASE_NOT_ACTIVE")
        self.authority.revoke_lease(str(row["signed_task_lease_id"]))
        updated = dict(row)
        updated.pop("artifact_type", None)
        updated["artifact_version"] = int(row.get("artifact_version", 1)) + 1
        updated["state"] = "REVOKED"
        updated["revoked_at"] = _now()
        updated["revoked_reason"] = reason
        self.truth.append_atomic("RC72_CAPABILITY_LEASE_UPSERTED", updated)


install_rc72_capability_overlay()
