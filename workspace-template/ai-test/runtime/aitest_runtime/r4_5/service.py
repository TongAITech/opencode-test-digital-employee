from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from aitest_runtime.durable_core import ActorRef, CommandResult, RuntimeService
from aitest_runtime.durable_core.contracts import RuntimeError as DurableRuntimeError

from .contracts import *
from .errors import R45_COMMAND_INVALID, R45Error
from .extension import r4_5_extension
from .reducer import R45State


def _raw(value: Any, fields_value: Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(value, Mapping):
        result = dict(value)
    elif hasattr(value, "to_dict") and callable(value.to_dict):
        result = dict(value.to_dict())
    elif value is None:
        result = {}
    else:
        raise R45Error(R45_COMMAND_INVALID, "R4.5 request must be a record or mapping")
    result.update(fields_value)
    return result


def _provisional(record_type: type[Any], value: Any, fields_value: Mapping[str, Any]) -> Any:
    raw = _raw(value, fields_value)
    identity_name = {
        ReleaseRiskAssessment: "risk_assessment_id",
        ReleaseReadinessAssessment: "readiness_assessment_id",
        ReleaseWaitState: "wait_id",
        WakeLinkage: "wake_linkage_id",
        ResumeEligibilityAssessment: "eligibility_id",
        R2ResumeIntent: "resume_intent_id",
        R2ResumeReceipt: "resume_receipt_id",
        ReadinessDispositionLinkage: "disposition_id",
    }[record_type]
    raw.setdefault(identity_name, "pending")
    raw.setdefault("correlation_id", "r4.5")
    raw.setdefault("causation_id", "r4.5")
    raw.setdefault("created_by", {"type": "SYSTEM", "id": "r4.5"})
    raw.setdefault("created_seq", 0)
    raw.setdefault("created_at", "pending")
    raw["record_digest"] = None
    return record_type.from_dict(raw)


def make_release_risk_assessment(value: Mapping[str, Any] | ReleaseRiskAssessment | None = None, **fields_value: Any) -> ReleaseRiskAssessment:
    return _provisional(ReleaseRiskAssessment, value, fields_value)


def make_release_readiness_assessment(value: Mapping[str, Any] | ReleaseReadinessAssessment | None = None, **fields_value: Any) -> ReleaseReadinessAssessment:
    return _provisional(ReleaseReadinessAssessment, value, fields_value)


def make_release_wait(value: Mapping[str, Any] | ReleaseWaitState | None = None, **fields_value: Any) -> ReleaseWaitState:
    return _provisional(ReleaseWaitState, value, fields_value)


def make_wake_linkage(value: Mapping[str, Any] | WakeLinkage | None = None, **fields_value: Any) -> WakeLinkage:
    return _provisional(WakeLinkage, value, fields_value)


def make_resume_eligibility(value: Mapping[str, Any] | ResumeEligibilityAssessment | None = None, **fields_value: Any) -> ResumeEligibilityAssessment:
    return _provisional(ResumeEligibilityAssessment, value, fields_value)


def make_resume_intent(value: Mapping[str, Any] | R2ResumeIntent | None = None, **fields_value: Any) -> R2ResumeIntent:
    return _provisional(R2ResumeIntent, value, fields_value)


def make_resume_receipt(value: Mapping[str, Any] | R2ResumeReceipt | None = None, **fields_value: Any) -> R2ResumeReceipt:
    return _provisional(R2ResumeReceipt, value, fields_value)


def make_readiness_disposition(value: Mapping[str, Any] | ReadinessDispositionLinkage | None = None, **fields_value: Any) -> ReadinessDispositionLinkage:
    return _provisional(ReadinessDispositionLinkage, value, fields_value)


@dataclass(frozen=True)
class R45OperationResult:
    command_result: CommandResult
    entity: Any | None = None

    @property
    def ok(self) -> bool:
        return self.command_result.ok

    @property
    def outcome(self) -> str:
        return self.command_result.outcome

    @property
    def error_code(self) -> str | None:
        return self.command_result.error_code

    @property
    def first_seq(self) -> int | None:
        return self.command_result.first_seq

    @property
    def last_seq(self) -> int | None:
        return self.command_result.last_seq

    @property
    def duplicate_of(self) -> str | None:
        return self.command_result.duplicate_of

    def to_dict(self) -> dict[str, Any]:
        value = self.command_result.to_dict()
        value["entity"] = self.entity.to_dict() if hasattr(self.entity, "to_dict") else self.entity
        return value


def compose_r4_5_runtime(
    db_path: str | Path,
    base_extensions: Iterable[Any] = (),
    *,
    clock: Any = None,
    failure_injector: Any = None,
) -> RuntimeService:
    extensions = tuple(base_extensions)
    if any(getattr(item, "extension_id", None) == EXTENSION_ID for item in extensions):
        raise R45Error(R45_COMMAND_INVALID, "R4.5 extension is already present in explicit composition")
    return RuntimeService(
        db_path,
        clock=clock,
        failure_injector=failure_injector,
        extensions=extensions + (r4_5_extension(),),
    )


class R45ApplicationService:
    """Caller-owned service that persists only through the shared RuntimeService."""

    def __init__(self, runtime_service: RuntimeService, *, actor: ActorRef | None = None) -> None:
        if not isinstance(runtime_service, RuntimeService):
            raise TypeError("runtime_service must be the existing RuntimeService")
        runtime_service.extension_registry.manifest(EXTENSION_ID)
        self._runtime = runtime_service
        self.runtime_service = runtime_service
        self.runtime = runtime_service
        self.actor = actor or ActorRef("SYSTEM", "r4.5")

    def state(self, mission_id: str) -> R45State:
        value = self._runtime.get_composed_state(mission_id).extension_state(EXTENSION_ID)
        if not isinstance(value, R45State):
            raise R45Error(R45_COMMAND_INVALID, "R4.5 extension state is invalid")
        return value

    get_state = state

    def current_resolution(self, mission_id: str, release_scope: ReleaseScope | Mapping[str, Any]) -> CurrentReadinessResolution:
        return self.state(mission_id).current_resolution(release_scope)

    def _error(self, command_id: str, mission_id: str, exc: Exception) -> R45OperationResult:
        error = exc if isinstance(exc, (R45Error, DurableRuntimeError)) else R45Error(R45_COMMAND_INVALID, str(exc))
        return R45OperationResult(CommandResult("REJECTED", command_id, mission_id, error=error))

    def _entity(self, mission_id: str, kind: str, identity: str) -> Any | None:
        value = self.state(mission_id)
        return {
            "risk": value.risk(identity),
            "readiness": value.readiness(identity),
            "wait": value.wait(identity),
            "wake": value.wake(identity),
            "eligibility": value.eligibility(identity),
            "intent": value.intent(identity),
            "receipt": value.receipt(identity),
            "disposition": value.disposition(identity),
        }.get(kind)

    @staticmethod
    def _matches_existing(record: Any, existing: Any) -> bool:
        raw = record.to_dict()
        raw["created_seq"] = existing.created_seq
        raw["created_at"] = existing.created_at
        raw["correlation_id"] = existing.correlation_id
        raw["causation_id"] = existing.causation_id
        raw["record_digest"] = None
        if "eligibility_digest" in raw:
            raw["eligibility_digest"] = None
        try:
            normalized = type(existing).from_dict(raw)
        except Exception:
            return False
        return normalized.record_digest == existing.record_digest

    def _execute(
        self,
        record: Any,
        command_type: str,
        kind: str,
        identity: str,
        *,
        expected_seq: int | None = None,
        command_id: str | None = None,
        correlation_id: str | None = None,
        actor: ActorRef | None = None,
    ) -> R45OperationResult:
        mission_id = record.stream_owner_mission_id
        command_identifier = command_id or f"r4.5:{kind}:{identity}"
        payload = record.to_dict()
        for key in ("created_seq", "created_at", "record_digest", "eligibility_digest"):
            payload.pop(key, None)
        payload["causation_id"] = command_identifier
        if correlation_id is not None:
            payload["correlation_id"] = correlation_id
        try:
            existing = self._entity(mission_id, kind, identity)
            if existing is not None:
                if not self._matches_existing(record, existing):
                    return self._error(
                        command_identifier,
                        mission_id,
                        R45Error(R45_IDENTITY_CONFLICT, f"{kind} identity already owns a different digest"),
                    )
                return R45OperationResult(
                    CommandResult("DUPLICATE", command_identifier, mission_id, duplicate_of=f"r4.5:{kind}:{identity}"),
                    existing,
                )
            result = self._runtime.execute(
                {
                    "command_id": command_identifier,
                    "type": command_type,
                    "mission_id": mission_id,
                    "session_id": None,
                    "expected_seq": self._runtime.get_head_seq(mission_id) if expected_seq is None else expected_seq,
                    "actor": (actor or self.actor).to_dict(),
                    "payload": payload,
                    "idempotency_key": f"r4.5:{kind}:{identity}",
                    "correlation_id": correlation_id or record.correlation_id,
                    "schema_version": 1,
                }
            )
            entity = self._entity(mission_id, kind, identity) if result.ok else None
            return R45OperationResult(result, entity)
        except Exception as exc:
            return self._error(command_identifier, mission_id, exc)

    def evaluate_release_risk(self, value: Mapping[str, Any] | ReleaseRiskAssessment | None = None, *, expected_seq: int | None = None, command_id: str | None = None, correlation_id: str | None = None, actor: ActorRef | None = None, **fields_value: Any) -> R45OperationResult:
        record = make_release_risk_assessment(value, **fields_value)
        return self._execute(record, R4_5_EVALUATE_RELEASE_RISK, "risk", record.risk_assessment_id, expected_seq=expected_seq, command_id=command_id, correlation_id=correlation_id, actor=actor)

    assess_release_risk = evaluate_release_risk

    def evaluate_release_readiness(self, value: Mapping[str, Any] | ReleaseReadinessAssessment | None = None, *, expected_seq: int | None = None, command_id: str | None = None, correlation_id: str | None = None, actor: ActorRef | None = None, **fields_value: Any) -> R45OperationResult:
        record = make_release_readiness_assessment(value, **fields_value)
        return self._execute(record, R4_5_EVALUATE_RELEASE_READINESS, "readiness", record.readiness_assessment_id, expected_seq=expected_seq, command_id=command_id, correlation_id=correlation_id, actor=actor)

    assess_release_readiness = evaluate_release_readiness

    def open_release_wait(self, value: Mapping[str, Any] | ReleaseWaitState | None = None, *, expected_seq: int | None = None, command_id: str | None = None, correlation_id: str | None = None, actor: ActorRef | None = None, **fields_value: Any) -> R45OperationResult:
        record = make_release_wait(value, **fields_value)
        return self._execute(record, R4_5_OPEN_RELEASE_WAIT, "wait", record.wait_id, expected_seq=expected_seq, command_id=command_id, correlation_id=correlation_id, actor=actor)

    def record_wake_linkage(self, value: Mapping[str, Any] | WakeLinkage | None = None, *, expected_seq: int | None = None, command_id: str | None = None, correlation_id: str | None = None, actor: ActorRef | None = None, **fields_value: Any) -> R45OperationResult:
        record = make_wake_linkage(value, **fields_value)
        return self._execute(record, R4_5_RECORD_WAKE_LINKAGE, "wake", record.wake_linkage_id, expected_seq=expected_seq, command_id=command_id, correlation_id=correlation_id, actor=actor)

    def evaluate_resume_eligibility(self, value: Mapping[str, Any] | ResumeEligibilityAssessment | None = None, *, expected_seq: int | None = None, command_id: str | None = None, correlation_id: str | None = None, actor: ActorRef | None = None, **fields_value: Any) -> R45OperationResult:
        record = make_resume_eligibility(value, **fields_value)
        return self._execute(record, R4_5_EVALUATE_RESUME_ELIGIBILITY, "eligibility", record.eligibility_id, expected_seq=expected_seq, command_id=command_id, correlation_id=correlation_id, actor=actor)

    def record_resume_intent(self, value: Mapping[str, Any] | R2ResumeIntent | None = None, *, expected_seq: int | None = None, command_id: str | None = None, correlation_id: str | None = None, actor: ActorRef | None = None, **fields_value: Any) -> R45OperationResult:
        record = make_resume_intent(value, **fields_value)
        return self._execute(record, R4_5_RECORD_RESUME_INTENT, "intent", record.resume_intent_id, expected_seq=expected_seq, command_id=command_id, correlation_id=correlation_id, actor=actor)

    def reconcile_r2_resume_receipt(self, value: Mapping[str, Any] | R2ResumeReceipt | None = None, *, expected_seq: int | None = None, command_id: str | None = None, correlation_id: str | None = None, actor: ActorRef | None = None, **fields_value: Any) -> R45OperationResult:
        record = make_resume_receipt(value, **fields_value)
        return self._execute(record, R4_5_RECONCILE_R2_RESUME_RECEIPT, "receipt", record.resume_receipt_id, expected_seq=expected_seq, command_id=command_id, correlation_id=correlation_id, actor=actor)

    def record_readiness_disposition(self, value: Mapping[str, Any] | ReadinessDispositionLinkage | None = None, *, expected_seq: int | None = None, command_id: str | None = None, correlation_id: str | None = None, actor: ActorRef | None = None, **fields_value: Any) -> R45OperationResult:
        record = make_readiness_disposition(value, **fields_value)
        return self._execute(record, R4_5_RECORD_READINESS_DISPOSITION, "disposition", record.disposition_id, expected_seq=expected_seq, command_id=command_id, correlation_id=correlation_id, actor=actor)


__all__ = [
    "R45OperationResult", "R45ApplicationService", "compose_r4_5_runtime",
    "make_release_risk_assessment", "make_release_readiness_assessment", "make_release_wait", "make_wake_linkage",
    "make_resume_eligibility", "make_resume_intent", "make_resume_receipt", "make_readiness_disposition",
]
