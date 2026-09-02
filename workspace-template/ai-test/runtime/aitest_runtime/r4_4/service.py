from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Mapping

from aitest_runtime.durable_core import ActorRef, CommandResult, RuntimeService
from aitest_runtime.durable_core.contracts import RuntimeError as DurableRuntimeError

from .contracts import *
from .errors import R44Error
from .extension import r4_4_extension


def _raw(value: Any, fields: Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(value, Mapping):
        result = dict(value)
    elif hasattr(value, "to_dict"):
        result = dict(value.to_dict())
    else:
        result = {}
    result.update(fields)
    return result


def _strip_generated(value: dict[str, Any]) -> dict[str, Any]:
    for key in ("created_seq", "created_at", "correlation_id", "cycle_digest", "workset_digest", "linkage_digest", "validation_digest", "closure_digest", "receipt_digest"):
        value.pop(key, None)
    return value


def _reference(value: Any, kind: str, object_id: str, digest: str | None = None) -> ExactReference:
    if value is not None:
        return ExactReference.from_dict(value)
    return make_reference(kind, object_id, digest)


def make_cycle(value: Mapping[str, Any] | None = None, **fields: Any) -> PostFixValidationCycle:
    raw = _strip_generated(_raw(value, fields))
    raw.setdefault("cycle_id", "pending")
    raw.setdefault("target_build_ref", None)
    raw.setdefault("validation_case_refs", ())
    raw.setdefault("validation_case_version_digests", ())
    raw.setdefault("case_review_refs", ())
    raw.setdefault("execution_readiness_refs", ())
    raw.setdefault("oracle_specification_refs", ())
    raw.setdefault("evidence_requirement_refs", ())
    raw.setdefault("current_operational_state", PostFixOperationalState.VALIDATION_PENDING)
    raw.setdefault("supersedes_cycle_ref", None)
    raw.setdefault("origin_lineage", {})
    provisional = PostFixValidationCycle(**raw)
    return replace(provisional, cycle_id=cycle_id_for(provisional), cycle_digest=None)


def make_workset(value: Mapping[str, Any] | None = None, **fields: Any) -> TargetedRegressionWorkSet:
    raw = _strip_generated(_raw(value, fields))
    raw.setdefault("workset_id", "pending")
    for name in ("coverage_refs", "change_impact_refs", "reconciliation_refs", "test_strategy_refs", "impact_assessment_refs", "campaign_selection_revision_refs", "selected_case_refs", "selected_case_version_digests", "inclusion_basis_refs", "unknown_scope_refs", "blocked_scope_refs", "excluded_scope_refs", "completed_case_refs", "failed_case_refs", "pending_case_refs"):
        raw.setdefault(name, ())
    raw.setdefault("selection_policy_version", "r4.4.regression-selection.v1")
    raw.setdefault("selection_as_of_cursor", 0)
    raw.setdefault("selection_complete", True)
    raw.setdefault("tracking_state", RegressionTrackingState.NOT_STARTED)
    raw.setdefault("supersedes_workset_ref", None)
    provisional = TargetedRegressionWorkSet(**raw)
    return replace(provisional, workset_id=workset_id_for(provisional), workset_digest=None)


def make_binding(value: Mapping[str, Any] | None = None, **fields: Any) -> ExecutableCaseBinding:
    raw = _strip_generated(_raw(value, fields))
    raw.setdefault("binding_id", "pending")
    for name in ("environment_refs", "config_refs", "authorization_refs", "human_gate_refs", "mapping_provenance"):
        raw.setdefault(name, ())
    provisional = ExecutableCaseBinding(**raw)
    return replace(provisional, binding_id=binding_id_for(provisional.immutable_payload()), binding_digest=None)


def make_intent(value: Mapping[str, Any] | None = None, **fields: Any) -> ValidationExecutionIntent:
    raw = _strip_generated(_raw(value, fields))
    raw.setdefault("execution_intent_id", "pending")
    provisional = ValidationExecutionIntent(**raw)
    return replace(provisional, execution_intent_id=execution_intent_id_for(provisional), intent_digest=None)


@dataclass(frozen=True)
class R44OperationResult:
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
        return {**self.command_result.to_dict(), "entity": self.entity.to_dict() if hasattr(self.entity, "to_dict") else self.entity}


def compose_r4_4_runtime(
    db_path: str | Path,
    base_extensions: Iterable[Any] = (),
    *,
    clock: Any = None,
    failure_injector: Any = None,
) -> RuntimeService:
    extensions = tuple(base_extensions)
    if any(getattr(item, "extension_id", None) == EXTENSION_ID for item in extensions):
        raise R44Error("R4_4_COMPOSITION_INVALID", "R4.4 extension is already present in explicit composition")
    return RuntimeService(db_path, clock=clock, failure_injector=failure_injector, extensions=extensions + (r4_4_extension(),))


class R44ApplicationService:
    def __init__(self, runtime_service: RuntimeService, *, actor: ActorRef | None = None) -> None:
        if not isinstance(runtime_service, RuntimeService):
            raise TypeError("runtime_service must be the existing RuntimeService")
        runtime_service.extension_registry.manifest(EXTENSION_ID)
        self.runtime_service = runtime_service
        self.runtime = runtime_service
        self.actor = actor or ActorRef("SYSTEM", "r4.4")

    def state(self, mission_id: str) -> Any:
        return self.runtime_service.get_composed_state(mission_id).extension_state(EXTENSION_ID)

    get_state = state

    def _error(self, command_id: str, mission_id: str, exc: Exception) -> R44OperationResult:
        error = exc if isinstance(exc, (R44Error, DurableRuntimeError)) else R44Error("R4_4_COMMAND_INVALID", str(exc))
        return R44OperationResult(CommandResult("REJECTED", command_id, mission_id, error=error))

    def _entity(self, mission_id: str, kind: str, entity_id: str) -> Any | None:
        state = self.state(mission_id)
        return {
            "cycle": state.cycle(entity_id), "workset": state.workset(entity_id), "linkage": state.linkage(entity_id),
            "assessment": state.assessment(entity_id), "closure": state.closure(entity_id), "receipt": state.receipt(entity_id),
        }.get(kind)

    def _execute(self, *, mission_id: str, command_type: str, entity_id: str, kind: str, payload: Mapping[str, Any], expected_seq: int | None = None, command_id: str | None = None, correlation_id: str | None = None, actor: ActorRef | None = None) -> R44OperationResult:
        command_identifier = command_id or f"r4.4:{entity_id}"
        idempotency_key = f"r4.4:{entity_id}"
        try:
            existing = self._entity(mission_id, kind, entity_id)
            if existing is not None:
                type_by_kind = {"cycle": PostFixValidationCycle, "workset": TargetedRegressionWorkSet, "linkage": ExecutionLinkage, "assessment": FixValidationAssessment, "closure": TargetedRegressionClosure, "receipt": SufficiencyHandoffReceipt}
                candidate_type = type_by_kind.get(kind)
                candidate = candidate_type.from_dict(payload) if candidate_type is not None else None
                if candidate is not None and hasattr(candidate, "immutable_payload") and candidate.immutable_payload() != existing.immutable_payload():
                    return self._error(command_identifier, mission_id, R44Error("CONFLICT", f"immutable {kind} identity already owns a different digest"))
                return R44OperationResult(CommandResult("DUPLICATE", command_identifier, mission_id, duplicate_of=f"r4.4:{entity_id}"), existing)
            result = self.runtime_service.execute({
                "command_id": command_identifier, "type": command_type, "mission_id": mission_id, "session_id": None,
                "expected_seq": self.runtime_service.get_head_seq(mission_id) if expected_seq is None else expected_seq,
                "actor": (actor or self.actor).to_dict(), "payload": dict(payload), "idempotency_key": idempotency_key,
                "correlation_id": correlation_id or command_identifier, "schema_version": 1,
            })
            entity = self._entity(mission_id, kind, entity_id) if result.ok else None
            return R44OperationResult(result, entity)
        except Exception as exc:
            return self._error(command_identifier, mission_id, exc)

    def open_post_fix_validation(self, value: PostFixValidationCycle | Mapping[str, Any] | None = None, *, detection: Mapping[str, Any] | None = None, **kwargs: Any) -> R44OperationResult:
        raw = _raw(value, kwargs)
        if detection is not None:
            lineage = dict(raw.get("origin_lineage") or {})
            lineage["fix_detection_assessment"] = dict(detection)
            raw["origin_lineage"] = lineage
        try:
            cycle = make_cycle(raw) if "cycle_id" not in raw else PostFixValidationCycle.from_dict({**raw, "created_seq": 0, "created_at": "validated", "correlation_id": raw.get("correlation_id", "r4.4")})
            raw = cycle.to_dict()
            raw.pop("created_seq", None); raw.pop("created_at", None); raw.pop("correlation_id", None); raw.pop("cycle_digest", None)
            return self._execute(mission_id=cycle.stream_owner_mission_id, command_type=R4_4_OPEN_POST_FIX_VALIDATION, entity_id=cycle.cycle_id, kind="cycle", payload=raw)
        except Exception as exc:
            mission = str(raw.get("stream_owner_mission_id") or "")
            return self._error(str(raw.get("cycle_id") or ""), mission, exc)

    open = open_post_fix_validation

    def assemble_targeted_regression_workset(self, value: TargetedRegressionWorkSet | Mapping[str, Any] | None = None, **kwargs: Any) -> R44OperationResult:
        raw = _raw(value, kwargs)
        try:
            workset = make_workset(raw) if "workset_id" not in raw else TargetedRegressionWorkSet.from_dict({**raw, "created_seq": 0, "created_at": "validated", "correlation_id": raw.get("correlation_id", "r4.4")})
            payload = workset.to_dict(); [payload.pop(key, None) for key in ("created_seq", "created_at", "correlation_id", "workset_digest")]
            return self._execute(mission_id=workset.owner_mission_id, command_type=R4_4_ASSEMBLE_TARGETED_REGRESSION_WORKSET, entity_id=workset.workset_id, kind="workset", payload=payload)
        except Exception as exc:
            return self._error(str(raw.get("workset_id") or ""), str(raw.get("owner_mission_id") or ""), exc)

    assemble_workset = assemble_targeted_regression_workset

    def record_execution_linkage(self, value: ExecutionLinkage | Mapping[str, Any] | None = None, *, mission_id: str | None = None, **kwargs: Any) -> R44OperationResult:
        raw = _raw(value, kwargs)
        try:
            linkage = ExecutionLinkage.from_dict({**raw, "created_seq": 0, "created_at": "validated", "correlation_id": raw.get("correlation_id", "r4.4")})
            payload = linkage.to_dict(); [payload.pop(key, None) for key in ("created_seq", "created_at", "correlation_id", "linkage_digest")]
            selected_mission = mission_id or str(raw.get("mission_id") or "")
            if not selected_mission:
                raise R44Error("R4_4_SCOPE_MISMATCH", "mission_id is required when recording a linkage")
            return self._execute(mission_id=selected_mission, command_type=R4_4_RECORD_EXECUTION_LINKAGE, entity_id=linkage.linkage_id, kind="linkage", payload=payload)
        except Exception as exc:
            return self._error(str(raw.get("linkage_id") or ""), "", exc)

    def record_fix_validation_assessment(self, value: FixValidationAssessment | Mapping[str, Any] | None = None, *, mission_id: str | None = None, **kwargs: Any) -> R44OperationResult:
        raw = _raw(value, kwargs)
        try:
            assessment = FixValidationAssessment.from_dict({**raw, "created_seq": 0, "created_at": "validated", "correlation_id": raw.get("correlation_id", "r4.4")})
            payload = assessment.to_dict(); [payload.pop(key, None) for key in ("created_seq", "created_at", "correlation_id", "validation_digest")]
            selected_mission = mission_id or str(raw.get("stream_owner_mission_id") or "")
            return self._execute(mission_id=selected_mission, command_type=R4_4_RECORD_FIX_VALIDATION_ASSESSMENT, entity_id=assessment.fix_validation_id, kind="assessment", payload=payload)
        except Exception as exc:
            return self._error(str(raw.get("fix_validation_id") or ""), str(raw.get("stream_owner_mission_id") or ""), exc)

    assess_fix_validation = record_fix_validation_assessment

    def record_regression_closure(self, value: TargetedRegressionClosure | Mapping[str, Any] | None = None, *, mission_id: str | None = None, **kwargs: Any) -> R44OperationResult:
        raw = _raw(value, kwargs)
        try:
            closure = TargetedRegressionClosure.from_dict({**raw, "created_seq": 0, "created_at": "validated", "correlation_id": raw.get("correlation_id", "r4.4")})
            payload = closure.to_dict(); [payload.pop(key, None) for key in ("created_seq", "created_at", "correlation_id", "closure_digest")]
            selected_mission = mission_id or str(raw.get("owner_mission_id") or "")
            if not selected_mission:
                raise R44Error("R4_4_SCOPE_MISMATCH", "mission_id is required when recording a closure")
            return self._execute(mission_id=selected_mission, command_type=R4_4_RECORD_REGRESSION_CLOSURE, entity_id=closure.closure_id, kind="closure", payload=payload)
        except Exception as exc:
            return self._error(str(raw.get("closure_id") or ""), "", exc)

    def request_r3_sufficiency_evaluation(self, value: SufficiencyHandoffReceipt | Mapping[str, Any] | None = None, *, mission_id: str | None = None, **kwargs: Any) -> R44OperationResult:
        return self._record_receipt(R4_4_REQUEST_R3_SUFFICIENCY_EVALUATION, value, kwargs, "request", mission_id=mission_id)

    def acknowledge_r3_sufficiency_evaluation(self, value: SufficiencyHandoffReceipt | Mapping[str, Any] | None = None, *, mission_id: str | None = None, **kwargs: Any) -> R44OperationResult:
        return self._record_receipt(R4_4_ACK_R3_SUFFICIENCY_EVALUATION, value, kwargs, "receipt", mission_id=mission_id)

    ack_r3_sufficiency_evaluation = acknowledge_r3_sufficiency_evaluation

    def _record_receipt(self, command_type: str, value: Any, kwargs: Mapping[str, Any], kind: str, *, mission_id: str | None = None) -> R44OperationResult:
        raw = _raw(value, kwargs)
        try:
            if "receipt_id" not in raw:
                receipt_identity = {key: raw.get(key) for key in ("handoff_request_id", "input_digest", "decision_digest", "request_status")}
                raw["receipt_id"] = f"r4.4:receipt:{canonical_sha256(receipt_identity)}"
            receipt = SufficiencyHandoffReceipt.from_dict({**raw, "created_seq": 0, "created_at": "validated", "correlation_id": raw.get("correlation_id", "r4.4")})
            payload = receipt.to_dict(); [payload.pop(key, None) for key in ("created_seq", "created_at", "correlation_id", "receipt_digest")]
            selected_mission = mission_id or str(raw.get("owner_mission_id") or "")
            if not selected_mission:
                raise R44Error("R4_4_SCOPE_MISMATCH", "mission_id is required for sufficiency handoff")
            return self._execute(mission_id=selected_mission, command_type=command_type, entity_id=receipt.receipt_id, kind="receipt", payload=payload)
        except Exception as exc:
            return self._error(str(raw.get("receipt_id") or ""), "", exc)

    def supersede_operation(self, operation_kind: str, operation_id: str, superseding_ref: Mapping[str, Any], reason: str, *, mission_id: str, **kwargs: Any) -> R44OperationResult:
        payload = {"operation_kind": operation_kind, "operation_id": operation_id, "superseding_ref": dict(superseding_ref), "reason": reason}
        return self._execute(mission_id=mission_id, command_type=R4_4_SUPERSEDE_OPERATION, entity_id=f"{operation_kind}:{operation_id}", kind="cycle" if operation_kind == "CYCLE" else "workset", payload=payload, **kwargs)

__all__ = ["R44OperationResult", "R44ApplicationService", "compose_r4_4_runtime", "make_cycle", "make_workset", "make_binding", "make_intent"]
