"""RC7.2 model/provider assignment and failover runtime.

Model identity is bound to a Worker/Attempt/Session, never the whole Mission.
Provider failures are persisted in the provider namespace, the old Attempt is
blocked and checkpointed, and approved fallback creates a fresh Worker plus a
new child Attempt for the same WorkItem.  Existing long-running sessions are
never hot-swapped to another model.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.truth import TruthRuntime

from .models import ContractError
from .rc72_linkage import WorkItemAttemptBinding, WorkItemAttemptState
from .rc72_repository import CanonicalRC72Repository
from .rc72_worker_lifecycle import WorkerLifecycleService
from .truth_overlay import install_rc7_truth_overlay


_MODEL_READINESS = "rc72_model_readiness"
_MODEL_ASSIGNMENT = "rc72_model_assignment"
_PROVIDER_FAILURE = "rc72_provider_failure"
_MODEL_FAILOVER = "rc72_model_failover"

_EVENT_TYPES = {
    "RC72_MODEL_READINESS_UPSERTED": (_MODEL_READINESS, "readiness_id"),
    "RC72_MODEL_ASSIGNMENT_UPSERTED": (_MODEL_ASSIGNMENT, "assignment_id"),
    "RC72_PROVIDER_FAILURE_UPSERTED": (_PROVIDER_FAILURE, "failure_id"),
    "RC72_MODEL_FAILOVER_UPSERTED": (_MODEL_FAILOVER, "failover_id"),
}
_BUCKETS = {
    _MODEL_READINESS: "rc72_model_readiness",
    _MODEL_ASSIGNMENT: "rc72_model_assignments",
    _PROVIDER_FAILURE: "rc72_provider_failures",
    _MODEL_FAILOVER: "rc72_model_failovers",
}


class ProviderFailureClass(str, Enum):
    PROVIDER_AUTH = "PROVIDER_AUTH"
    PROVIDER_QUOTA = "PROVIDER_QUOTA"
    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    PROVIDER_CONFIG_INVALID = "PROVIDER_CONFIG_INVALID"


class ProviderReadinessState(str, Enum):
    MODEL_AUTH_READY = "MODEL_AUTH_READY"
    MODEL_AUTH_EXPIRED = "MODEL_AUTH_EXPIRED"
    MODEL_PROVIDER_READY = "MODEL_PROVIDER_READY"
    MODEL_PROVIDER_UNAVAILABLE = "MODEL_PROVIDER_UNAVAILABLE"
    MODEL_CONFIG_INVALID = "MODEL_CONFIG_INVALID"
    MODEL_READY_TIMEOUT = "MODEL_READY_TIMEOUT"
    MODEL_READY = "MODEL_READY"


@dataclass(frozen=True)
class ModelFailoverResult:
    failover_id: str
    assignment_id: str
    attempt_id: str
    worker_id: str
    session_id: str
    provider: str
    model: str


def _now() -> int:
    return int(time.time())


def _new(prefix: str) -> str:
    return "%s-%s" % (prefix, uuid.uuid4().hex[:20])


def _required(out: Dict[str, Any], name: str) -> str:
    return _contracts._require_str(out, name)


def _string_list(out: Dict[str, Any], name: str, *, allow_empty: bool = True) -> List[str]:
    value = out.get(name)
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise _contracts.DomainValidationError("%s_INVALID" % name.upper())
    if not allow_empty and not value:
        raise _contracts.DomainValidationError("%s_REQUIRED" % name.upper())
    out[name] = list(value)
    return out[name]


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


def _validate_readiness(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, _MODEL_READINESS, "readiness_id")
    for name in ("provider", "model", "state", "evidence_ref"):
        out[name] = _required(out, name)
    try:
        out["state"] = ProviderReadinessState(out["state"].upper()).value
    except ValueError as exc:
        raise _contracts.DomainValidationError("MODEL_READINESS_STATE_INVALID") from exc
    if not isinstance(out.get("checked_at"), int) or out["checked_at"] < 0:
        raise _contracts.DomainValidationError("MODEL_READINESS_CHECKED_AT_INVALID")
    return out


def _validate_assignment(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, _MODEL_ASSIGNMENT, "assignment_id")
    for name in (
        "mission_id", "workitem_id", "attempt_id", "worker_id", "session_id",
        "provider", "model", "capability_profile", "state",
    ):
        out[name] = _required(out, name)
    _string_list(out, "fallback_chain")
    out["state"] = out["state"].upper()
    if out["state"] not in {"ACTIVE", "BLOCKED_PROVIDER", "SUPERSEDED"}:
        raise _contracts.DomainValidationError("MODEL_ASSIGNMENT_STATE_INVALID")
    _optional(out, "failure_id")
    if not isinstance(out.get("created_at"), int) or out["created_at"] < 0:
        raise _contracts.DomainValidationError("MODEL_ASSIGNMENT_CREATED_AT_INVALID")
    if out.get("updated_at") is not None and (not isinstance(out["updated_at"], int) or out["updated_at"] < 0):
        raise _contracts.DomainValidationError("MODEL_ASSIGNMENT_UPDATED_AT_INVALID")
    return out


def _validate_failure(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, _PROVIDER_FAILURE, "failure_id")
    for name in (
        "assignment_id", "mission_id", "workitem_id", "attempt_id", "worker_id",
        "session_id", "provider", "model", "failure_class", "namespace", "reason", "state",
    ):
        out[name] = _required(out, name)
    try:
        out["failure_class"] = ProviderFailureClass(out["failure_class"].upper()).value
    except ValueError as exc:
        raise _contracts.DomainValidationError("PROVIDER_FAILURE_CLASS_INVALID") from exc
    if out["namespace"] != "PROVIDER_FAILURE":
        raise _contracts.DomainValidationError("PROVIDER_FAILURE_NAMESPACE_INVALID")
    out["state"] = out["state"].upper()
    if out["state"] not in {"BLOCKED_PROVIDER", "FAILED_OVER", "OPERATOR_REPAIR_REQUIRED"}:
        raise _contracts.DomainValidationError("PROVIDER_FAILURE_STATE_INVALID")
    _string_list(out, "evidence_refs", allow_empty=False)
    for name in ("checkpoint_id", "failover_id", "replacement_attempt_id"):
        _optional(out, name)
    if not isinstance(out.get("created_at"), int) or out["created_at"] < 0:
        raise _contracts.DomainValidationError("PROVIDER_FAILURE_CREATED_AT_INVALID")
    if out.get("updated_at") is not None and (not isinstance(out["updated_at"], int) or out["updated_at"] < 0):
        raise _contracts.DomainValidationError("PROVIDER_FAILURE_UPDATED_AT_INVALID")
    return out


def _validate_failover(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, _MODEL_FAILOVER, "failover_id")
    for name in (
        "failure_id", "mission_id", "workitem_id", "source_assignment_id", "source_attempt_id",
        "source_worker_id", "source_session_id", "replacement_assignment_id",
        "replacement_attempt_id", "replacement_worker_id", "replacement_session_id",
        "provider", "model", "reason", "state",
    ):
        out[name] = _required(out, name)
    out["state"] = out["state"].upper()
    if out["state"] != "PREPARED":
        raise _contracts.DomainValidationError("MODEL_FAILOVER_STATE_INVALID")
    if out["source_attempt_id"] == out["replacement_attempt_id"]:
        raise _contracts.DomainValidationError("MODEL_FAILOVER_REQUIRES_NEW_ATTEMPT")
    if out["source_worker_id"] == out["replacement_worker_id"]:
        raise _contracts.DomainValidationError("MODEL_FAILOVER_REQUIRES_FRESH_WORKER")
    if out["source_session_id"] == out["replacement_session_id"]:
        raise _contracts.DomainValidationError("MODEL_FAILOVER_REQUIRES_FRESH_SESSION")
    if not isinstance(out.get("created_at"), int) or out["created_at"] < 0:
        raise _contracts.DomainValidationError("MODEL_FAILOVER_CREATED_AT_INVALID")
    return out


def install_rc72_model_failover_overlay() -> None:
    install_rc7_truth_overlay()
    validators = {
        _MODEL_READINESS: _validate_readiness,
        _MODEL_ASSIGNMENT: _validate_assignment,
        _PROVIDER_FAILURE: _validate_failure,
        _MODEL_FAILOVER: _validate_failover,
    }
    for artifact_type, validator in validators.items():
        _contracts.VALIDATORS[artifact_type] = validator
        _truth.BUCKETS[artifact_type] = _BUCKETS[artifact_type]
    for event_type, (artifact_type, identity) in _EVENT_TYPES.items():
        _truth.EVENT_TYPES[event_type] = (artifact_type, identity)
        _truth.IDENTITY_FIELDS[artifact_type] = identity


class ModelFailoverManager:
    def __init__(
        self,
        truth: TruthRuntime,
        *,
        release_id: str,
        worker_lifecycle: WorkerLifecycleService,
    ) -> None:
        install_rc72_model_failover_overlay()
        if not isinstance(release_id, str) or not release_id.strip():
            raise ContractError("MODEL_FAILOVER_RELEASE_ID_REQUIRED")
        self.truth = truth
        self.release_id = release_id.strip()
        self.workers = worker_lifecycle
        self.repository = CanonicalRC72Repository(truth, release_id=self.release_id)

    def install_overlay(self) -> None:
        install_rc72_model_failover_overlay()

    def _append(self, event_type: str, payload: Dict[str, Any]):
        out = dict(payload)
        out["release_id"] = self.release_id
        out.setdefault("artifact_version", 1)
        return self.truth.append_atomic(event_type, out)

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise ContractError("MODEL_FAILOVER_TRUTH_NOT_UNIQUE:%s:%d" % (artifact_type, len(rows)))
        return rows[0]

    def _upsert(self, event_type: str, row: Mapping[str, Any], **changes: Any) -> Dict[str, Any]:
        updated = dict(row)
        updated.pop("artifact_type", None)
        updated.update(changes)
        updated["artifact_version"] = int(row.get("artifact_version", 1)) + 1
        updated["updated_at"] = _now()
        self._append(event_type, updated)
        return updated

    def _binding(
        self,
        *,
        mission_id: str,
        workitem_id: str,
        attempt_id: str,
        worker_id: str,
        session_id: str,
    ) -> Dict[str, Any]:
        rows = self.truth.query("rc72_workitem_attempt_binding", workitem_id=workitem_id)
        rows = [row for row in rows if row.get("mission_id") == mission_id]
        rows = [row for row in rows if row.get("attempt_id") == attempt_id]
        rows = [row for row in rows if row.get("worker_id") == worker_id]
        rows = [row for row in rows if row.get("session_id") == session_id]
        if len(rows) != 1:
            raise ContractError("MODEL_ASSIGNMENT_ATTEMPT_BINDING_MISMATCH")
        return rows[0]

    @staticmethod
    def _parse_fallback(value: str) -> Tuple[str, str]:
        if not isinstance(value, str) or ":" not in value:
            raise ContractError("MODEL_FALLBACK_FORMAT_INVALID")
        provider, model = value.split(":", 1)
        provider, model = provider.strip(), model.strip()
        if not provider or not model:
            raise ContractError("MODEL_FALLBACK_FORMAT_INVALID")
        return provider, model

    def set_provider_readiness(
        self,
        *,
        provider: str,
        model: str,
        state: ProviderReadinessState,
        evidence_ref: str,
    ) -> None:
        try:
            state = state if isinstance(state, ProviderReadinessState) else ProviderReadinessState(str(state))
        except ValueError as exc:
            raise ContractError("MODEL_READINESS_STATE_INVALID") from exc
        readiness_id = "%s:%s" % (provider, model)
        existing = self.truth.query(_MODEL_READINESS, readiness_id=readiness_id)
        version = int(existing[0].get("artifact_version", 0)) + 1 if existing else 1
        self._append(
            "RC72_MODEL_READINESS_UPSERTED",
            {
                "readiness_id": readiness_id,
                "provider": provider,
                "model": model,
                "state": state.value,
                "evidence_ref": evidence_ref,
                "checked_at": _now(),
                "artifact_version": version,
            },
        )

    def _assert_ready(self, provider: str, model: str) -> None:
        readiness_id = "%s:%s" % (provider, model)
        rows = self.truth.query(_MODEL_READINESS, readiness_id=readiness_id)
        if len(rows) != 1 or rows[0].get("state") != ProviderReadinessState.MODEL_READY.value:
            raise ContractError("MODEL_NOT_READY")

    def assign_model(
        self,
        *,
        assignment_id: str,
        mission_id: str,
        workitem_id: str,
        attempt_id: str,
        worker_id: str,
        session_id: str,
        provider: str,
        model: str,
        capability_profile: str,
        fallback_chain: Sequence[str],
    ) -> None:
        if self.truth.query(_MODEL_ASSIGNMENT, assignment_id=assignment_id):
            raise ContractError("MODEL_ASSIGNMENT_ALREADY_EXISTS")
        self._assert_ready(provider, model)
        binding = self._binding(
            mission_id=mission_id,
            workitem_id=workitem_id,
            attempt_id=attempt_id,
            worker_id=worker_id,
            session_id=session_id,
        )
        if binding.get("state") not in {"PREPARED", "RUNNING", "EVIDENCE_READY"}:
            raise ContractError("MODEL_ASSIGNMENT_ATTEMPT_NOT_ACTIVE")
        for item in fallback_chain:
            self._parse_fallback(item)
        self._append(
            "RC72_MODEL_ASSIGNMENT_UPSERTED",
            {
                "assignment_id": assignment_id,
                "mission_id": mission_id,
                "workitem_id": workitem_id,
                "attempt_id": attempt_id,
                "worker_id": worker_id,
                "session_id": session_id,
                "provider": provider,
                "model": model,
                "capability_profile": capability_profile,
                "fallback_chain": list(fallback_chain),
                "state": "ACTIVE",
                "failure_id": None,
                "created_at": _now(),
                "updated_at": _now(),
            },
        )

    def record_provider_failure(
        self,
        *,
        failure_id: str,
        assignment_id: str,
        failure_class: ProviderFailureClass,
        reason: str,
        evidence_refs: Sequence[str],
    ) -> None:
        try:
            failure_class = failure_class if isinstance(failure_class, ProviderFailureClass) else ProviderFailureClass(str(failure_class))
        except ValueError as exc:
            raise ContractError("PROVIDER_FAILURE_CLASS_INVALID") from exc
        if not evidence_refs:
            raise ContractError("PROVIDER_FAILURE_EVIDENCE_REQUIRED")
        if self.truth.query(_PROVIDER_FAILURE, failure_id=failure_id):
            raise ContractError("PROVIDER_FAILURE_ALREADY_EXISTS")
        assignment = self._one(_MODEL_ASSIGNMENT, assignment_id=assignment_id)
        if assignment.get("state") != "ACTIVE":
            raise ContractError("MODEL_ASSIGNMENT_NOT_ACTIVE")
        binding = self._binding(
            mission_id=str(assignment["mission_id"]),
            workitem_id=str(assignment["workitem_id"]),
            attempt_id=str(assignment["attempt_id"]),
            worker_id=str(assignment["worker_id"]),
            session_id=str(assignment["session_id"]),
        )
        checkpoint = self.workers.checkpoint_and_close(
            str(assignment["session_id"]),
            reason="provider failure: %s" % failure_class.value,
        )
        blocked = WorkItemAttemptBinding(
            binding_id=str(binding["binding_id"]),
            mission_id=str(binding["mission_id"]),
            etu_id=str(binding["etu_id"]),
            workitem_id=str(binding["workitem_id"]),
            case_id=str(binding["case_id"]),
            attempt_id=str(binding["attempt_id"]),
            worker_id=str(binding["worker_id"]),
            session_id=str(binding["session_id"]),
            task_lease_ref=str(binding["task_lease_ref"]),
            capability_lease_refs=list(binding.get("capability_lease_refs") or []),
            resource_lease_refs=list(binding.get("resource_lease_refs") or []),
            parent_attempt_id=binding.get("parent_attempt_id"),
            state=WorkItemAttemptState.BLOCKED,
        )
        self.repository.persist(blocked, artifact_version=int(binding.get("artifact_version", 1)) + 1)
        self._upsert(
            "RC72_MODEL_ASSIGNMENT_UPSERTED",
            assignment,
            state="BLOCKED_PROVIDER",
            failure_id=failure_id,
        )
        self._append(
            "RC72_PROVIDER_FAILURE_UPSERTED",
            {
                "failure_id": failure_id,
                "assignment_id": assignment_id,
                "mission_id": assignment["mission_id"],
                "workitem_id": assignment["workitem_id"],
                "attempt_id": assignment["attempt_id"],
                "worker_id": assignment["worker_id"],
                "session_id": assignment["session_id"],
                "provider": assignment["provider"],
                "model": assignment["model"],
                "failure_class": failure_class.value,
                "namespace": "PROVIDER_FAILURE",
                "reason": reason,
                "evidence_refs": list(evidence_refs),
                "checkpoint_id": checkpoint.checkpoint_id,
                "state": "BLOCKED_PROVIDER",
                "failover_id": None,
                "replacement_attempt_id": None,
                "created_at": _now(),
                "updated_at": _now(),
            },
        )

    def _select_fallback(self, assignment: Mapping[str, Any]) -> Tuple[str, str]:
        for item in list(assignment.get("fallback_chain") or []):
            provider, model = self._parse_fallback(item)
            if provider == assignment.get("provider") and model == assignment.get("model"):
                continue
            readiness_id = "%s:%s" % (provider, model)
            rows = self.truth.query(_MODEL_READINESS, readiness_id=readiness_id)
            if len(rows) == 1 and rows[0].get("state") == ProviderReadinessState.MODEL_READY.value:
                return provider, model
        raise ContractError("NO_READY_FALLBACK_MODEL")

    @staticmethod
    def _canonical_refs_from_session(session: Mapping[str, Any]) -> Dict[str, List[str]]:
        context = dict(session.get("context_bundle") or {})
        keys = (
            "etu_refs", "executable_contract_refs", "data_refs", "evidence_refs", "gap_refs",
            "coverage_refs", "lease_refs",
        )
        return {key: list(context.get(key) or []) for key in keys}

    def failover(self, *, failure_id: str, reason: str) -> ModelFailoverResult:
        failure = self._one(_PROVIDER_FAILURE, failure_id=failure_id)
        if failure.get("state") != "BLOCKED_PROVIDER":
            raise ContractError("PROVIDER_FAILURE_NOT_FAILOVER_ELIGIBLE")
        if failure.get("failure_class") == ProviderFailureClass.PROVIDER_CONFIG_INVALID.value:
            self._upsert(
                "RC72_PROVIDER_FAILURE_UPSERTED",
                failure,
                state="OPERATOR_REPAIR_REQUIRED",
            )
            raise ContractError("PROVIDER_CONFIG_INVALID_REQUIRES_OPERATOR_REPAIR")
        assignment = self._one(_MODEL_ASSIGNMENT, assignment_id=str(failure["assignment_id"]))
        provider, model = self._select_fallback(assignment)
        binding = self._binding(
            mission_id=str(assignment["mission_id"]),
            workitem_id=str(assignment["workitem_id"]),
            attempt_id=str(assignment["attempt_id"]),
            worker_id=str(assignment["worker_id"]),
            session_id=str(assignment["session_id"]),
        )
        old_session = self._one("rc72_worker_session", session_id=str(assignment["session_id"]))
        fresh = self.workers.assign_fresh_worker(
            mission_id=str(assignment["mission_id"]),
            team_id=str(old_session["team_id"]),
            role=str(old_session["role"]),
            etu_id=str(binding["etu_id"]),
            workitem_id=str(binding["workitem_id"]),
            canonical_refs=self._canonical_refs_from_session(old_session),
            parent_session_id=str(assignment["session_id"]),
        )
        replacement_attempt_id = _new("ATT")
        replacement_binding_id = _new("BIND")
        self.repository.persist(
            WorkItemAttemptBinding(
                binding_id=replacement_binding_id,
                mission_id=str(binding["mission_id"]),
                etu_id=str(binding["etu_id"]),
                workitem_id=str(binding["workitem_id"]),
                case_id=str(binding["case_id"]),
                attempt_id=replacement_attempt_id,
                worker_id=fresh.worker_id,
                session_id=fresh.session_id,
                parent_attempt_id=str(binding["attempt_id"]),
                state=WorkItemAttemptState.PREPARED,
            )
        )
        replacement_assignment_id = _new("MA")
        self.assign_model(
            assignment_id=replacement_assignment_id,
            mission_id=str(assignment["mission_id"]),
            workitem_id=str(assignment["workitem_id"]),
            attempt_id=replacement_attempt_id,
            worker_id=fresh.worker_id,
            session_id=fresh.session_id,
            provider=provider,
            model=model,
            capability_profile=str(assignment["capability_profile"]),
            fallback_chain=[
                item for item in list(assignment.get("fallback_chain") or [])
                if self._parse_fallback(item) != (provider, model)
            ],
        )
        failover_id = _new("MFO")
        self._append(
            "RC72_MODEL_FAILOVER_UPSERTED",
            {
                "failover_id": failover_id,
                "failure_id": failure_id,
                "mission_id": assignment["mission_id"],
                "workitem_id": assignment["workitem_id"],
                "source_assignment_id": assignment["assignment_id"],
                "source_attempt_id": assignment["attempt_id"],
                "source_worker_id": assignment["worker_id"],
                "source_session_id": assignment["session_id"],
                "replacement_assignment_id": replacement_assignment_id,
                "replacement_attempt_id": replacement_attempt_id,
                "replacement_worker_id": fresh.worker_id,
                "replacement_session_id": fresh.session_id,
                "provider": provider,
                "model": model,
                "reason": reason,
                "state": "PREPARED",
                "created_at": _now(),
            },
        )
        self._upsert(
            "RC72_PROVIDER_FAILURE_UPSERTED",
            failure,
            state="FAILED_OVER",
            failover_id=failover_id,
            replacement_attempt_id=replacement_attempt_id,
        )
        return ModelFailoverResult(
            failover_id=failover_id,
            assignment_id=replacement_assignment_id,
            attempt_id=replacement_attempt_id,
            worker_id=fresh.worker_id,
            session_id=fresh.session_id,
            provider=provider,
            model=model,
        )
