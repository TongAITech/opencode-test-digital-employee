from __future__ import annotations

from typing import Any, Mapping

from aitest_runtime.durable_core import ComposedRuntimeState, PendingEvent, canonical_sha256

from .contracts import (
    COMMAND_TYPES,
    EVENT_TYPES,
    EXTENSION_ID,
    R48AuthorityOperation,
    R48AuthorityOperationInput,
    R48AuthorityReceiptInput,
    R48AuthorityResult,
    R48AuthorityOutcome,
    R48CapabilityObservationInput,
    R48CoordinationStatus,
    R48CycleCloseInput,
    R48CycleContext,
    R48CycleRegistrationInput,
    R48CycleState,
    R48Phase,
    R48ReconciliationInput,
    R48ReentryInput,
    R48ReentryRecord,
    R48StageDisposition,
    R48State,
    R48WaitingInput,
)
from .errors import R48Error


def _state(composed: ComposedRuntimeState) -> R48State:
    if not isinstance(composed, ComposedRuntimeState) or composed.core_state.mission is None:
        raise R48Error("MISSION_NOT_FOUND", "R4.8 commands require an existing Mission")
    value = composed.extension_state(EXTENSION_ID)
    if not isinstance(value, R48State):
        raise R48Error("RUNTIME_IDENTITY_MISMATCH", "R4.8 extension state is not registered")
    if value.owner_mission_id != composed.mission_id:
        raise R48Error("RUNTIME_IDENTITY_MISMATCH", "R4.8 state is bound to a different Mission")
    return value


def _payload(command: Any, key: str) -> dict[str, Any]:
    if command.session_id is not None or not command.idempotency_key:
        raise R48Error("COMMAND_SCHEMA_INVALID", "R4.8 commands are session-independent and require idempotency_key")
    raw = command.payload.get(key)
    if not isinstance(raw, Mapping):
        raise R48Error("COMMAND_SCHEMA_INVALID", f"payload.{key} must be an object")
    return dict(raw)


def _cycle(state: R48State, cycle_id: str) -> R48CycleState:
    value = next((item for item in state.cycles if item.context.cycle_id == cycle_id), None)
    if value is None:
        raise R48Error("CYCLE_NOT_FOUND", f"cycle not found: {cycle_id}")
    return value


def _operation(cycle: R48CycleState, operation_id: str) -> R48AuthorityOperation:
    value = next((item for item in cycle.operations if item.operation_id == operation_id), None)
    if value is None:
        raise R48Error("UNKNOWN_OPERATION", f"operation not found: {operation_id}")
    return value


def _input_digest(value: Any) -> str:
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    return canonical_sha256(value)


def _step_id(cycle_id: str, phase: R48Phase) -> str:
    return "r4.8/step/" + canonical_sha256({"cycle_id": cycle_id, "phase": phase.value})


def _step_payload(
    *,
    schema_version: int,
    step_id: str,
    cycle_id: str,
    step_revision: int,
    phase: R48Phase,
    status: R48CoordinationStatus,
    authority: Any,
    operation_kind: Any,
    input_refs: tuple[Any, ...],
    input_digest: str,
    source_cursor: int,
    stage_disposition: Any,
    policy_digest: str,
    reason_code: str | None,
    last_operation_id: str | None = None,
    last_receipt_id: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": schema_version,
        "step_id": step_id,
        "cycle_id": cycle_id,
        "step_revision": step_revision,
        "phase": phase.value,
        "status": status.value,
        "authority": authority.value,
        "operation_kind": operation_kind.value,
        "input_refs": [item.to_dict() for item in input_refs],
        "input_digest": input_digest,
        "source_cursor": source_cursor,
        "stage_disposition": stage_disposition.value,
        "policy_digest": policy_digest,
        "last_operation_id": last_operation_id,
        "last_receipt_id": last_receipt_id,
        "reason_code": reason_code,
    }


def _result_payload(result: R48AuthorityResult) -> dict[str, Any]:
    return result.to_dict()


class R48CommandContribution:
    def handle(self, command: Any, composed: ComposedRuntimeState) -> list[PendingEvent]:
        state = _state(composed)
        if command.type == "R4_8_REGISTER_CYCLE.v1":
            value = R48CycleRegistrationInput.from_dict(_payload(command, "registration"))
            if value.owner_mission_id != command.mission_id:
                raise R48Error("RUNTIME_IDENTITY_MISMATCH", "registration owner Mission differs from command Mission")
            cycle_id = str(command.payload.get("cycle_id") or "")
            context = dict(command.payload.get("context") or {})
            if not cycle_id or not context:
                raise R48Error("COMMAND_SCHEMA_INVALID", "service must materialize cycle identity and policy")
            if any(item.context.cycle_id == cycle_id for item in state.cycles):
                raise R48Error("CYCLE_IDENTITY_MISMATCH", "cycle identity already exists")
            step = dict(command.payload.get("step") or {})
            return [PendingEvent("r4.8.cycle.registered.v1", "R4_8_CYCLE", cycle_id, {"context": context, "step": step})]

        if command.type == "R4_8_RECORD_CAPABILITY_OBSERVATION.v1":
            value = R48CapabilityObservationInput.from_dict(_payload(command, "observation"))
            cycle = _cycle(state, value.cycle_id)
            if cycle.status is R48CoordinationStatus.COMPLETE:
                raise R48Error("INVALID_STATUS_TRANSITION", "closed cycle cannot accept observations")
            phase_authority = {
                R48Phase.TRIGGER_OBSERVED: "R4_2",
                R48Phase.IMPACT_OBSERVED: "R4_2",
                R48Phase.WORK_ACTIVE: "R2",
                R48Phase.DEFECT_FIX_OBSERVED: "R4_3",
                R48Phase.FIX_VALIDATION_OBSERVED: "R4_4",
                R48Phase.REGRESSION_OBSERVED: "R4_4",
                R48Phase.SUFFICIENCY_OBSERVED: "R3_7",
                R48Phase.READINESS_OBSERVED: "R4_5",
                R48Phase.LEARNING_ELIGIBLE: "R4_6",
                R48Phase.PROMOTION_OBSERVED: "R4_6",
                R48Phase.LEGACY_RECONCILIATION_OBSERVED: "R4_7",
            }.get(value.target_phase)
            if phase_authority is not None and value.authority.value != phase_authority:
                raise R48Error("READINESS_AUTHORITY_VIOLATION", f"{value.target_phase.value} is owned by {phase_authority}")
            step_id = _step_id(value.cycle_id, value.target_phase)
            previous = next((item for item in cycle.steps if item.step_id == step_id), None)
            step_revision = (previous.step_revision + 1) if previous else 1
            step = _step_payload(
                schema_version=value.schema_version,
                step_id=step_id,
                cycle_id=value.cycle_id,
                step_revision=step_revision,
                phase=value.target_phase,
                status=R48CoordinationStatus.ACTIVE,
                authority=value.authority,
                operation_kind=value.operation_kind,
                input_refs=value.input_refs,
                input_digest=_input_digest({"input_refs": [item.to_dict() for item in value.input_refs], "source_cursor": value.source_cursor}),
                source_cursor=value.source_cursor,
                stage_disposition=value.stage_disposition,
                policy_digest=value.policy_digest,
                reason_code=value.reason_code,
            )
            return [PendingEvent("r4.8.capability.observed.v1", "R4_8_CYCLE", value.cycle_id, {"cycle_id": value.cycle_id, "step": step})]

        if command.type == "R4_8_REQUEST_AUTHORITY_ACTION.v1":
            value = R48AuthorityOperationInput.from_dict(_payload(command, "operation"))
            cycle = _cycle(state, value.cycle_id)
            if cycle.status is R48CoordinationStatus.COMPLETE:
                raise R48Error("INVALID_STATUS_TRANSITION", "closed cycle cannot request authority work")
            step = next((item for item in cycle.steps if item.step_id == value.step_id and item.step_revision == value.step_revision), None)
            if step is None:
                raise R48Error("REFERENCE_DIGEST_CONFLICT", "operation step lineage is not current")
            operation_id = str(command.payload.get("operation_id") or "")
            if not operation_id:
                raise R48Error("COMMAND_SCHEMA_INVALID", "service must materialize operation identity")
            if any(item.operation_id == operation_id for item in cycle.operations):
                raise R48Error("OPERATION_ID_CONFLICT", "operation identity already exists")
            operation = dict(command.payload.get("materialized_operation") or {})
            if not operation:
                operation = {
                    "schema_version": value.schema_version,
                    "operation_id": operation_id,
                    "owner_mission_id": value.owner_mission_id,
                    "cycle_id": value.cycle_id,
                    "step_id": value.step_id,
                    "step_revision": value.step_revision,
                    "authority": value.authority.value,
                    "operation_kind": value.operation_kind.value,
                    "request_ref": value.request_ref.to_dict() if value.request_ref else None,
                    "input_refs": [item.to_dict() for item in value.input_refs],
                    "input_digest": str(command.payload.get("input_digest") or _input_digest(value.input_refs)),
                    "policy_digest": value.policy_digest,
                    "source_cursor": value.source_cursor,
                    "authority_idempotency_key": "r4.8/authority-idempotency/" + operation_id,
                    "correlation_id": command.correlation_id,
                    "causation_id": str(command.payload.get("causation_id") or command.command_id),
                    "current_status": "REQUESTED",
                    "current_receipt_id": None,
                    "authority_operation_id": None,
                    "result_ref": None,
                    "result_digest": None,
                    "authority_revision": None,
                    "authority_outcome": None,
                    "proof_digest": None,
                    "owner_cursor": None,
                    "observed_source_cursor": None,
                    "current_state_digest": "",
                }
            return [PendingEvent("r4.8.authority_action.requested.v1", "R4_8_OPERATION", operation_id, {"cycle_id": value.cycle_id, "operation": operation})]

        if command.type == "R4_8_RECORD_AUTHORITY_RECEIPT.v1":
            value = R48AuthorityReceiptInput.from_dict(_payload(command, "receipt"))
            cycle, operation = self._operation_for_receipt(state, value.operation_id)
            receipt = dict(command.payload.get("materialized_receipt") or {})
            if not receipt:
                receipt = self._receipt_payload(value, cycle, operation, command)
            return [PendingEvent("r4.8.authority_action.received.v1", "R4_8_RECEIPT", str(receipt["receipt_id"]), {"cycle_id": cycle.context.cycle_id, "receipt": receipt})]

        if command.type == "R4_8_MARK_WAITING.v1":
            value = R48WaitingInput.from_dict(_payload(command, "waiting"))
            _cycle(state, value.cycle_id)
            return [PendingEvent("r4.8.cycle.waiting.v1", "R4_8_CYCLE", value.cycle_id, {"cycle_id": value.cycle_id, "reason_code": value.reason_code, "step_id": value.step_id})]

        if command.type == "R4_8_REENTER_CYCLE.v1":
            value = R48ReentryInput.from_dict(_payload(command, "reentry"))
            cycle = _cycle(state, value.cycle_id)
            if cycle.status is R48CoordinationStatus.COMPLETE:
                raise R48Error("REENTRY_NOT_ALLOWED", "closed cycle cannot be reentered")
            prior = next((item for item in cycle.steps if item.step_id == value.prior_step_id and item.step_revision == value.prior_step_revision), None)
            if prior is None:
                raise R48Error("REFERENCE_DIGEST_CONFLICT", "reentry prior step is not current")
            target_step_id = _step_id(value.cycle_id, value.target_phase)
            current_target = next((item for item in cycle.steps if item.step_id == target_step_id), None)
            target_revision = (current_target.step_revision + 1) if current_target else 1
            reentry_id = str(command.payload.get("reentry_id") or "")
            if not reentry_id:
                raise R48Error("COMMAND_SCHEMA_INVALID", "service must materialize reentry identity")
            record = dict(command.payload.get("materialized_reentry") or {})
            if not record:
                record = {
                    "schema_version": value.schema_version,
                    "reentry_id": reentry_id,
                    "owner_mission_id": value.owner_mission_id,
                    "cycle_id": value.cycle_id,
                    "prior_step_id": value.prior_step_id,
                    "prior_step_revision": value.prior_step_revision,
                    "target_phase": value.target_phase.value,
                    "target_step_id": target_step_id,
                    "target_step_revision": target_revision,
                    "kind": value.kind.value,
                    "operation_id": value.operation_id,
                    "new_input_refs": [item.to_dict() for item in value.new_input_refs],
                    "input_digest": _input_digest(value.new_input_refs),
                    "observed_owner_cursor": value.observed_owner_cursor,
                    "reason_code": value.reason_code,
                    "reconciliation_evidence": value.reconciliation_evidence.to_dict() if value.reconciliation_evidence else None,
                    "record_digest": "",
                }
            step = _step_payload(
                schema_version=value.schema_version,
                step_id=target_step_id,
                cycle_id=value.cycle_id,
                step_revision=target_revision,
                phase=value.target_phase,
                status=R48CoordinationStatus.RECONCILIATION_REQUIRED if value.kind.value in {"RECONCILE", "REVALIDATE"} else R48CoordinationStatus.ACTIVE,
                authority=prior.authority,
                operation_kind=prior.operation_kind,
                input_refs=value.new_input_refs,
                input_digest=record["input_digest"],
                source_cursor=int(value.observed_owner_cursor or prior.source_cursor),
                stage_disposition=prior.stage_disposition,
                policy_digest=prior.policy_digest,
                reason_code=value.reason_code,
            )
            return [PendingEvent("r4.8.cycle.reentered.v1", "R4_8_REENTRY", reentry_id, {"cycle_id": value.cycle_id, "reentry": record, "step": step})]

        if command.type == "R4_8_RECORD_RECONCILIATION.v1":
            value = R48ReconciliationInput.from_dict(_payload(command, "reconciliation"))
            cycle, operation = self._operation_for_receipt(state, value.operation_id)
            receipt = dict(command.payload.get("materialized_receipt") or {})
            if not receipt:
                receipt_input = R48AuthorityReceiptInput(value.schema_version, value.owner_mission_id, value.operation_id, value.authority_result, value.observed_source_cursor)
                receipt = self._receipt_payload(receipt_input, cycle, operation, command)
            return [PendingEvent("r4.8.operation.reconciled.v1", "R4_8_RECEIPT", str(receipt["receipt_id"]), {"cycle_id": cycle.context.cycle_id, "receipt": receipt, "reason_code": value.reason_code})]

        if command.type == "R4_8_CLOSE_CYCLE.v1":
            value = R48CycleCloseInput.from_dict(_payload(command, "close"))
            cycle = _cycle(state, value.cycle_id)
            if cycle.status is R48CoordinationStatus.COMPLETE:
                raise R48Error("CYCLE_NOT_CLOSABLE", "cycle is already closed")
            return [PendingEvent("r4.8.cycle.closed.v1", "R4_8_CYCLE", value.cycle_id, {"cycle_id": value.cycle_id, "closure_ref": value.closure_ref.to_dict(), "source_cursor": value.source_cursor})]

        raise R48Error("COMMAND_SCHEMA_INVALID", f"unsupported R4.8 command: {command.type}")

    @staticmethod
    def _operation_for_receipt(state: R48State, operation_id: str) -> tuple[R48CycleState, R48AuthorityOperation]:
        for cycle in state.cycles:
            for operation in cycle.operations:
                if operation.operation_id == operation_id:
                    return cycle, operation
        raise R48Error("UNKNOWN_OPERATION", f"operation not found: {operation_id}")

    @staticmethod
    def _receipt_payload(value: R48AuthorityReceiptInput, cycle: R48CycleState, operation: R48AuthorityOperation, command: Any) -> dict[str, Any]:
        result = value.authority_result
        semantic = {
            "operation_id": operation.operation_id,
            "authority": result.authority.value,
            "authority_operation_id": result.authority_operation_id,
            "result_ref": result.result_ref.to_dict() if result.result_ref else None,
            "result_digest": result.result_digest,
            "authority_revision": result.authority_revision,
            "outcome": result.outcome.value,
            "proof_digest": result.proof_digest,
        }
        semantic_identity = canonical_sha256(semantic)
        receipt_id = "r4.8/receipt/" + semantic_identity
        return {
            "schema_version": value.schema_version,
            "receipt_id": receipt_id,
            "owner_mission_id": value.owner_mission_id,
            "operation_id": operation.operation_id,
            "cycle_id": cycle.context.cycle_id,
            "step_id": operation.step_id,
            "step_revision": operation.step_revision,
            "authority": result.authority.value,
            "authority_operation_id": result.authority_operation_id,
            "result_ref": result.result_ref.to_dict() if result.result_ref else None,
            "result_digest": result.result_digest,
            "authority_revision": result.authority_revision,
            "owner_cursor": result.owner_cursor,
            "outcome": result.outcome.value,
            "proof_refs": [item.to_dict() for item in result.proof_refs],
            "proof_digest": result.proof_digest,
            "semantic_identity": semantic_identity,
            "observed_source_cursor": value.observed_source_cursor,
            "correlation_id": command.correlation_id,
            "causation_id": str(command.payload.get("causation_id") or command.command_id),
            "record_digest": "",
        }


__all__ = ["R48CommandContribution", "COMMAND_TYPES", "EVENT_TYPES"]
