"""RC7.2 independent diagnosis/recovery orchestration.

This module deliberately composes the existing RC7.2 state machine, canonical
WorkItemAttemptBinding and Phase-5 worker lifecycle truth.  It does not let the
execution worker repair itself in-place and it does not create a second Gap,
Mission or Attempt store.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.truth import TruthRuntime

from .models import ContractError
from .rc72_domain import AutonomousMissionNode
from .rc72_state_machine import DiagnosisRoute, FailureClass, RC72StateMachine
from .rc72_worker_lifecycle import WorkerLifecycleService, install_rc72_worker_lifecycle_overlay


_DIAGNOSIS_CASE = "rc72_diagnosis_case"
_DIAGNOSIS_OUTCOME = "rc72_diagnosis_outcome"
_DIAGNOSIS_RECOVERY = "rc72_diagnosis_recovery"
_WORKER_SESSION = "rc72_worker_session"

_EVENT_TYPES = {
    "RC72_DIAGNOSIS_CASE_UPSERTED": (_DIAGNOSIS_CASE, "diagnosis_id"),
    "RC72_DIAGNOSIS_OUTCOME_UPSERTED": (_DIAGNOSIS_OUTCOME, "diagnosis_id"),
    "RC72_DIAGNOSIS_RECOVERY_UPSERTED": (_DIAGNOSIS_RECOVERY, "diagnosis_id"),
}

_BUCKETS = {
    _DIAGNOSIS_CASE: "rc72_diagnosis_cases",
    _DIAGNOSIS_OUTCOME: "rc72_diagnosis_outcomes",
    _DIAGNOSIS_RECOVERY: "rc72_diagnosis_recoveries",
}

_DIAG_CONTEXT_KEYS = {
    "mission_id",
    "release_batch_id",
    "team_id",
    "role",
    "source_binding_id",
    "source_attempt_id",
    "source_workitem_id",
    "source_etu_id",
    "failure_evidence_refs",
    "executable_contract_refs",
}


def _now() -> int:
    return int(time.time())


def _new(prefix: str) -> str:
    return "%s-%s" % (prefix, uuid.uuid4().hex[:20])


def _required_str(out: Dict[str, Any], name: str) -> str:
    value = out.get(name)
    if not isinstance(value, str) or not value.strip():
        raise _contracts.DomainValidationError("%s_REQUIRED" % name.upper())
    return value.strip()


def _string_list(out: Dict[str, Any], name: str, *, nonempty: bool = False) -> List[str]:
    value = out.get(name, [])
    if isinstance(value, tuple):
        value = list(value)
        out[name] = value
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        raise _contracts.DomainValidationError("%s_INVALID" % name.upper())
    if nonempty and not value:
        raise _contracts.DomainValidationError("%s_REQUIRED" % name.upper())
    return value


def _base(payload: Dict[str, Any], artifact_type: str, identity: str) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    out[identity] = _required_str(out, identity)
    out["mission_id"] = _required_str(out, "mission_id")
    out["release_id"] = _required_str(out, "release_id")
    out["artifact_type"] = artifact_type
    version = out.get("artifact_version", 1)
    if not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError("ARTIFACT_VERSION_INVALID")
    out["artifact_version"] = version
    return out


def _validate_diagnosis_worker_session(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Phase-6 extension of the canonical Phase-5 worker-session contract."""
    purpose = str(payload.get("purpose") or "").upper()
    if purpose != "DIAGNOSIS":
        # Keep Phase-5 execution/review behavior unchanged.
        from . import rc72_worker_lifecycle as _wl

        return _wl._validate_worker_session(payload)

    out = _base(payload, _WORKER_SESSION, "session_id")
    for name in ("worker_id", "release_batch_id", "team_id", "role", "state"):
        out[name] = _required_str(out, name)
    out["purpose"] = "DIAGNOSIS"
    out["state"] = out["state"].upper()
    if out["state"] not in {"ACTIVE", "CLOSED"}:
        raise _contracts.DomainValidationError("WORKER_SESSION_STATE_INVALID")
    context = out.get("context_bundle")
    if not isinstance(context, dict):
        raise _contracts.DomainValidationError("WORKER_SESSION_CONTEXT_MUST_BE_OBJECT")
    if set(context).difference(_DIAG_CONTEXT_KEYS):
        raise _contracts.DomainValidationError("DIAGNOSIS_CONTEXT_KEY_NOT_ALLOWED")
    if {"chat_history", "messages", "previous_session_transcript"}.intersection(context):
        raise _contracts.DomainValidationError("WORKER_SESSION_CHAT_HISTORY_FORBIDDEN")
    for name in (
        "source_binding_id",
        "source_attempt_id",
        "source_workitem_id",
        "source_etu_id",
    ):
        out[name] = _required_str(out, name)
    _string_list(out, "failure_evidence_refs", nonempty=True)
    _string_list(out, "executable_contract_refs", nonempty=True)
    for name in (
        "parent_session_id",
        "checkpoint_id",
        "close_reason",
        "runtime_worker_id",
        "runtime_assignment_id",
        "task_lease_ref",
        "runtime_attempt_id",
        "dsh_session_id",
        "binding_id",
    ):
        value = out.get(name)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise _contracts.DomainValidationError("%s_INVALID" % name.upper())
    created_at = out.get("created_at")
    if not isinstance(created_at, int) or created_at < 0:
        raise _contracts.DomainValidationError("WORKER_SESSION_CREATED_AT_INVALID")
    closed_at = out.get("closed_at")
    if closed_at is not None and (not isinstance(closed_at, int) or closed_at < 0):
        raise _contracts.DomainValidationError("WORKER_SESSION_CLOSED_AT_INVALID")
    if out["state"] == "CLOSED" and not out.get("checkpoint_id"):
        raise _contracts.DomainValidationError("CLOSED_WORKER_SESSION_REQUIRES_CHECKPOINT")
    return out


def _validate_case(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, _DIAGNOSIS_CASE, "diagnosis_id")
    for name in (
        "team_id",
        "source_binding_id",
        "source_attempt_id",
        "source_workitem_id",
        "source_etu_id",
        "diagnosis_worker_id",
        "diagnosis_session_id",
        "transition_id",
        "state",
        "reason",
    ):
        out[name] = _required_str(out, name)
    out["state"] = out["state"].upper()
    if out["state"] not in {"DISPATCHED", "CLASSIFIED", "RECOVERY_LINKED"}:
        raise _contracts.DomainValidationError("DIAGNOSIS_CASE_STATE_INVALID")
    _string_list(out, "failure_evidence_refs", nonempty=True)
    _string_list(out, "executable_contract_refs", nonempty=True)
    if not isinstance(out.get("created_at"), int) or out["created_at"] < 0:
        raise _contracts.DomainValidationError("DIAGNOSIS_CASE_CREATED_AT_INVALID")
    return out


def _validate_outcome(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, _DIAGNOSIS_OUTCOME, "diagnosis_id")
    for name in ("source_attempt_id", "failure_class", "action", "rationale"):
        out[name] = _required_str(out, name)
    try:
        FailureClass(out["failure_class"])
    except ValueError as exc:
        raise _contracts.DomainValidationError("DIAGNOSIS_FAILURE_CLASS_INVALID") from exc
    for name in ("responsible_node", "gap_id", "back_edge_id", "transition_id"):
        value = out.get(name)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise _contracts.DomainValidationError("%s_INVALID" % name.upper())
    _string_list(out, "evidence_refs", nonempty=True)
    _string_list(out, "affected_refs")
    if not isinstance(out.get("replacement_attempt_required"), bool):
        raise _contracts.DomainValidationError("REPLACEMENT_ATTEMPT_REQUIRED_INVALID")
    if not isinstance(out.get("created_at"), int) or out["created_at"] < 0:
        raise _contracts.DomainValidationError("DIAGNOSIS_OUTCOME_CREATED_AT_INVALID")
    return out


def _validate_recovery(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, _DIAGNOSIS_RECOVERY, "diagnosis_id")
    for name in (
        "original_binding_id",
        "original_attempt_id",
        "replacement_binding_id",
        "replacement_attempt_id",
    ):
        out[name] = _required_str(out, name)
    if out["original_attempt_id"] == out["replacement_attempt_id"]:
        raise _contracts.DomainValidationError("REPLACEMENT_ATTEMPT_MUST_BE_NEW")
    if not isinstance(out.get("created_at"), int) or out["created_at"] < 0:
        raise _contracts.DomainValidationError("DIAGNOSIS_RECOVERY_CREATED_AT_INVALID")
    return out


def install_rc72_diagnosis_overlay() -> None:
    install_rc72_worker_lifecycle_overlay()
    _contracts.VALIDATORS[_WORKER_SESSION] = _validate_diagnosis_worker_session
    _contracts.VALIDATORS[_DIAGNOSIS_CASE] = _validate_case
    _contracts.VALIDATORS[_DIAGNOSIS_OUTCOME] = _validate_outcome
    _contracts.VALIDATORS[_DIAGNOSIS_RECOVERY] = _validate_recovery
    for event_type, (artifact_type, identity) in _EVENT_TYPES.items():
        _truth.EVENT_TYPES[event_type] = (artifact_type, identity)
        _truth.IDENTITY_FIELDS[artifact_type] = identity
        _truth.BUCKETS[artifact_type] = _BUCKETS[artifact_type]


@dataclass(frozen=True)
class FreshDiagnosisAssignment:
    diagnosis_id: str
    worker_id: str
    session_id: str
    source_attempt_id: str
    context_bundle: Dict[str, Any]
    transition_id: str


@dataclass(frozen=True)
class DiagnosisOutcome:
    diagnosis_id: str
    failure_class: FailureClass
    responsible_node: Optional[AutonomousMissionNode]
    action: str
    gap_id: Optional[str]
    back_edge_id: Optional[str]
    transition_id: Optional[str]


@dataclass(frozen=True)
class RecoveryAttemptLink:
    diagnosis_id: str
    original_attempt_id: str
    replacement_attempt_id: str
    replacement_binding_id: str


class DiagnosisOrchestrator:
    def __init__(
        self,
        truth: TruthRuntime,
        *,
        release_id: str,
        state_machine: RC72StateMachine,
        worker_lifecycle: WorkerLifecycleService,
    ) -> None:
        install_rc72_diagnosis_overlay()
        if not isinstance(release_id, str) or not release_id.strip():
            raise ContractError("DIAGNOSIS_RELEASE_ID_REQUIRED")
        self.truth = truth
        self.release_id = release_id.strip()
        self.state_machine = state_machine
        self.worker_lifecycle = worker_lifecycle

    def _append(self, event_type: str, payload: Dict[str, Any]):
        out = dict(payload)
        out["release_id"] = self.release_id
        out.setdefault("artifact_version", 1)
        return self.truth.append_atomic(event_type, out)

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise ContractError("%s_NOT_UNIQUE" % artifact_type.upper())
        return rows[0]

    def _batch_for_mission(self, mission_id: str) -> Dict[str, Any]:
        return self._one("rc72_release_batch", mission_id=mission_id)

    def _validate_evidence(self, mission_id: str, evidence_refs: Sequence[str]) -> List[str]:
        refs = list(evidence_refs)
        if not refs or not all(isinstance(v, str) and v.strip() for v in refs):
            raise ContractError("DIAGNOSIS_FAILURE_EVIDENCE_REQUIRED")
        for ref in refs:
            evidence = self._one("rc7_evidence", evidence_id=ref)
            if evidence.get("mission_id") != mission_id:
                raise ContractError("DIAGNOSIS_EVIDENCE_MISSION_MISMATCH")
        return refs

    def begin_failure_diagnosis(
        self,
        *,
        mission_id: str,
        team_id: str,
        source_binding_id: str,
        failure_evidence_refs: Sequence[str],
        executable_contract_refs: Sequence[str],
        reason: str,
    ) -> FreshDiagnosisAssignment:
        for value, name in (
            (mission_id, "mission_id"),
            (team_id, "team_id"),
            (source_binding_id, "source_binding_id"),
            (reason, "reason"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ContractError("%s_REQUIRED" % name.upper())
        binding = self._one("rc72_workitem_attempt_binding", binding_id=source_binding_id)
        if binding.get("mission_id") != mission_id:
            raise ContractError("DIAGNOSIS_BINDING_MISSION_MISMATCH")
        evidence_refs = self._validate_evidence(mission_id, failure_evidence_refs)
        executable_refs = list(executable_contract_refs)
        if not executable_refs or not all(isinstance(v, str) and v.strip() for v in executable_refs):
            raise ContractError("DIAGNOSIS_EXECUTABLE_CONTRACT_REQUIRED")

        transition = self.state_machine.route_execution_failure(
            failure_evidence_refs=evidence_refs,
            reason=reason,
        )
        batch = self._batch_for_mission(mission_id)
        diagnosis_id = _new("DIAG")
        worker_id = _new("DIAGWRK")
        session_id = _new("DIAGSES")
        context = {
            "mission_id": mission_id,
            "release_batch_id": batch["release_batch_id"],
            "team_id": team_id,
            "role": "diagnosis-worker",
            "source_binding_id": source_binding_id,
            "source_attempt_id": binding["attempt_id"],
            "source_workitem_id": binding["workitem_id"],
            "source_etu_id": binding["etu_id"],
            "failure_evidence_refs": evidence_refs,
            "executable_contract_refs": executable_refs,
        }
        self.truth.append_atomic(
            "RC72_WORKER_SESSION_UPSERTED",
            {
                "session_id": session_id,
                "worker_id": worker_id,
                "mission_id": mission_id,
                "release_id": self.release_id,
                "artifact_version": 1,
                "release_batch_id": batch["release_batch_id"],
                "team_id": team_id,
                "role": "diagnosis-worker",
                "purpose": "DIAGNOSIS",
                "state": "ACTIVE",
                "source_binding_id": source_binding_id,
                "source_attempt_id": binding["attempt_id"],
                "source_workitem_id": binding["workitem_id"],
                "source_etu_id": binding["etu_id"],
                "failure_evidence_refs": evidence_refs,
                "executable_contract_refs": executable_refs,
                "context_bundle": context,
                "parent_session_id": None,
                "checkpoint_id": None,
                "close_reason": None,
                "runtime_worker_id": None,
                "runtime_assignment_id": None,
                "task_lease_ref": None,
                "runtime_attempt_id": None,
                "dsh_session_id": None,
                "binding_id": None,
                "created_at": _now(),
                "closed_at": None,
            },
        )
        self._append(
            "RC72_DIAGNOSIS_CASE_UPSERTED",
            {
                "diagnosis_id": diagnosis_id,
                "mission_id": mission_id,
                "team_id": team_id,
                "source_binding_id": source_binding_id,
                "source_attempt_id": binding["attempt_id"],
                "source_workitem_id": binding["workitem_id"],
                "source_etu_id": binding["etu_id"],
                "diagnosis_worker_id": worker_id,
                "diagnosis_session_id": session_id,
                "transition_id": transition.transition_id,
                "failure_evidence_refs": evidence_refs,
                "executable_contract_refs": executable_refs,
                "state": "DISPATCHED",
                "reason": reason,
                "created_at": _now(),
            },
        )
        return FreshDiagnosisAssignment(
            diagnosis_id=diagnosis_id,
            worker_id=worker_id,
            session_id=session_id,
            source_attempt_id=binding["attempt_id"],
            context_bundle=context,
            transition_id=transition.transition_id,
        )

    def accept_classification(
        self,
        *,
        diagnosis_id: str,
        failure_class: FailureClass,
        source_delivery_id: str,
        evidence_refs: Sequence[str],
        affected_refs: Sequence[str],
        rationale: str,
    ) -> DiagnosisOutcome:
        case = self._one(_DIAGNOSIS_CASE, diagnosis_id=diagnosis_id)
        if not isinstance(failure_class, FailureClass):
            failure_class = FailureClass(str(failure_class))
        evidence = self._validate_evidence(case["mission_id"], evidence_refs)
        route: DiagnosisRoute = self.state_machine.route_diagnosis(
            failure_class,
            source_delivery_id=source_delivery_id,
            evidence_refs=evidence,
            affected_refs=list(affected_refs),
            rationale=rationale,
        )
        replacement_required = failure_class in {
            FailureClass.ANALYSIS_GAP,
            FailureClass.TEST_DESIGN_GAP,
            FailureClass.TEST_DATA_GAP,
            FailureClass.EXECUTABLE_GAP,
            FailureClass.ENVIRONMENT_GAP,
            FailureClass.REQUIREMENT_GAP,
        }
        self._append(
            "RC72_DIAGNOSIS_OUTCOME_UPSERTED",
            {
                "diagnosis_id": diagnosis_id,
                "mission_id": case["mission_id"],
                "source_attempt_id": case["source_attempt_id"],
                "failure_class": failure_class.value,
                "responsible_node": route.responsible_node.value if route.responsible_node else None,
                "action": route.action,
                "gap_id": route.gap_id,
                "back_edge_id": route.back_edge_id,
                "transition_id": route.transition_id,
                "evidence_refs": evidence,
                "affected_refs": list(affected_refs),
                "rationale": rationale,
                "replacement_attempt_required": replacement_required,
                "created_at": _now(),
            },
        )
        updated_case = dict(case)
        updated_case["state"] = "CLASSIFIED"
        updated_case["artifact_version"] = int(case.get("artifact_version", 1)) + 1
        self.truth.append_atomic("RC72_DIAGNOSIS_CASE_UPSERTED", updated_case)
        return DiagnosisOutcome(
            diagnosis_id=diagnosis_id,
            failure_class=failure_class,
            responsible_node=route.responsible_node,
            action=route.action,
            gap_id=route.gap_id,
            back_edge_id=route.back_edge_id,
            transition_id=route.transition_id,
        )

    def record_replacement_attempt(
        self,
        *,
        diagnosis_id: str,
        replacement_binding_id: str,
    ) -> RecoveryAttemptLink:
        case = self._one(_DIAGNOSIS_CASE, diagnosis_id=diagnosis_id)
        original = self._one("rc72_workitem_attempt_binding", binding_id=case["source_binding_id"])
        replacement = self._one("rc72_workitem_attempt_binding", binding_id=replacement_binding_id)
        if replacement.get("mission_id") != case.get("mission_id"):
            raise ContractError("REPLACEMENT_ATTEMPT_MISSION_MISMATCH")
        for field in ("workitem_id", "etu_id", "case_id"):
            if replacement.get(field) != original.get(field):
                raise ContractError("REPLACEMENT_ATTEMPT_LINEAGE_MISMATCH")
        if replacement.get("parent_attempt_id") != original.get("attempt_id"):
            raise ContractError("REPLACEMENT_ATTEMPT_PARENT_REQUIRED")
        if replacement.get("attempt_id") == original.get("attempt_id"):
            raise ContractError("REPLACEMENT_ATTEMPT_MUST_BE_NEW")
        self._append(
            "RC72_DIAGNOSIS_RECOVERY_UPSERTED",
            {
                "diagnosis_id": diagnosis_id,
                "mission_id": case["mission_id"],
                "original_binding_id": original["binding_id"],
                "original_attempt_id": original["attempt_id"],
                "replacement_binding_id": replacement["binding_id"],
                "replacement_attempt_id": replacement["attempt_id"],
                "created_at": _now(),
            },
        )
        updated_case = dict(case)
        updated_case["state"] = "RECOVERY_LINKED"
        updated_case["artifact_version"] = int(case.get("artifact_version", 1)) + 1
        self.truth.append_atomic("RC72_DIAGNOSIS_CASE_UPSERTED", updated_case)
        return RecoveryAttemptLink(
            diagnosis_id=diagnosis_id,
            original_attempt_id=original["attempt_id"],
            replacement_attempt_id=replacement["attempt_id"],
            replacement_binding_id=replacement_binding_id,
        )


install_rc72_diagnosis_overlay()
