from __future__ import annotations

from dataclasses import replace
from typing import Any

from aitest_runtime.durable_core import ComposedRuntimeState, EventEnvelope, RuntimeState, canonical_sha256

from .contracts import (
    EVENT_TYPES,
    EXTENSION_ID,
    R48AuthorityOperation,
    R48AuthorityOutcome,
    R48AuthorityReceipt,
    R48AuthorityResult,
    R48CoordinationStatus,
    R48CoordinationStep,
    R48CycleContext,
    R48CyclePolicySnapshot,
    R48CycleState,
    R48CycleCloseInput,
    R48Phase,
    R48ReentryRecord,
    R48State,
    R48OperationStatus,
)
from .errors import R48Error

SUPPORTED_EVENTS = EVENT_TYPES


def _digest(value: Any) -> str:
    return canonical_sha256(value)


def _state_digest(state: R48State) -> str:
    return _digest({"owner_mission_id": state.owner_mission_id, "cycles": [cycle.to_dict() for cycle in state.cycles], "last_seq": state.last_seq})


def _cycle_digest(cycle: R48CycleState) -> str:
    return _digest({"context": cycle.context.to_dict(), "phase": cycle.phase.value, "status": cycle.status.value, "steps": [item.to_dict() for item in cycle.steps], "operations": [item.to_dict() for item in cycle.operations], "receipts": [item.to_dict() for item in cycle.receipts], "reentries": [item.to_dict() for item in cycle.reentries], "last_seq": cycle.last_seq})


def _record_digest(value: dict[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key not in {"record_digest", "state_digest"}}
    return _digest(body)


def _materialize(value: dict[str, Any], event: EventEnvelope) -> dict[str, Any]:
    result = dict(value)
    result["created_seq"] = event.seq
    result["created_at"] = event.created_at
    result["record_digest"] = _record_digest(result)
    return result


def _materialize_step(value: dict[str, Any], event: EventEnvelope) -> R48CoordinationStep:
    raw = dict(value)
    raw["origin_event_seq"] = event.seq
    raw["origin_event_at"] = event.created_at
    raw["state_digest"] = ""
    item = R48CoordinationStep.from_dict(raw)
    return replace(item, state_digest=_digest(item.to_dict()))


def _replace_cycle(state: R48State, cycle: R48CycleState) -> R48State:
    cycles = tuple(cycle if item.context.cycle_id == cycle.context.cycle_id else item for item in state.cycles)
    candidate = replace(state, cycles=cycles)
    return replace(candidate, state_digest=_state_digest(candidate))


def _find_cycle(state: R48State, cycle_id: str) -> R48CycleState:
    for cycle in state.cycles:
        if cycle.context.cycle_id == cycle_id:
            return cycle
    raise R48Error("CYCLE_NOT_FOUND", f"cycle not found: {cycle_id}")


def _find_operation(cycle: R48CycleState, operation_id: str) -> R48AuthorityOperation:
    for operation in cycle.operations:
        if operation.operation_id == operation_id:
            return operation
    raise R48Error("UNKNOWN_OPERATION", f"operation not found: {operation_id}")


def initial_state(mission_id: str) -> R48State:
    value = R48State(mission_id, (), 0, "")
    return replace(value, state_digest=_state_digest(value))


class R48StateContribution:
    def initial_state(self, mission_id: str) -> R48State:
        return initial_state(mission_id)

    def encode(self, state: R48State) -> dict[str, Any]:
        return state.to_dict()

    def decode(self, value: dict[str, Any]) -> R48State:
        cycles = []
        for raw in value.get("cycles", []):
            context = R48CycleContext.from_dict(raw["context"])
            cycles.append(
                R48CycleState(
                    context=context,
                    phase=R48Phase(raw["phase"]),
                    status=R48CoordinationStatus(raw["status"]),
                    steps=tuple(R48CoordinationStep.from_dict(item) for item in raw.get("steps", [])),
                    operations=tuple(R48AuthorityOperation.from_dict(item) for item in raw.get("operations", [])),
                    receipts=tuple(R48AuthorityReceipt.from_dict(item) for item in raw.get("receipts", [])),
                    reentries=tuple(R48ReentryRecord.from_dict(item) for item in raw.get("reentries", [])),
                    last_seq=int(raw.get("last_seq", 0)),
                    state_digest=str(raw.get("state_digest", "")),
                )
            )
        return R48State(str(value["owner_mission_id"]), tuple(cycles), int(value.get("last_seq", 0)), str(value.get("state_digest", "")))

    def hash(self, state: R48State) -> str:
        return state.state_digest


class R48ReducerContribution:
    """Pure replay of R4.8 coordination facts."""

    def reduce(self, state: R48State, event: EventEnvelope, core_state: RuntimeState) -> R48State:
        if event.schema_version != 1 or event.event_type not in EVENT_TYPES:
            raise R48Error("UNKNOWN_EVENT", f"unsupported R4.8 event: {event.event_type}")
        if event.mission_id != state.owner_mission_id or event.mission_id != core_state.mission_id:
            raise R48Error("RUNTIME_IDENTITY_MISMATCH", "R4.8 event mission differs from state")
        if event.seq != core_state.seq or event.session_id is not None:
            raise R48Error("INVALID_STATUS_TRANSITION", "R4.8 events must share the core sequence and be session-independent")
        payload = dict(event.payload)

        if event.event_type == "r4.8.cycle.registered.v1":
            context_raw = _materialize(dict(payload["context"]), event)
            context = R48CycleContext.from_dict(context_raw)
            if any(item.context.cycle_id == context.cycle_id for item in state.cycles):
                raise R48Error("CYCLE_IDENTITY_MISMATCH", "cycle already exists")
            step = _materialize_step(dict(payload["step"]), event)
            cycle = R48CycleState(context, R48Phase.REGISTERED, R48CoordinationStatus.ACTIVE, (step,), (), (), (), event.seq, "")
            cycle = replace(cycle, state_digest=_cycle_digest(cycle))
            result = replace(state, cycles=state.cycles + (cycle,), last_seq=event.seq)
            return replace(result, state_digest=_state_digest(result))

        cycle_id = str(payload.get("cycle_id") or payload.get("context", {}).get("cycle_id") or "")
        cycle = _find_cycle(state, cycle_id)

        if event.event_type == "r4.8.capability.observed.v1":
            step = _materialize_step(dict(payload["step"]), event)
            steps = tuple(sorted(tuple(item for item in cycle.steps if item.step_id != step.step_id) + (step,), key=lambda item: item.step_id))
            updated = replace(cycle, phase=step.phase, status=step.status, steps=steps, last_seq=event.seq)
        elif event.event_type == "r4.8.authority_action.requested.v1":
            operation_raw = dict(payload["operation"])
            operation_raw["request_created_seq"] = event.seq
            operation_raw["request_created_at"] = event.created_at
            operation_raw["request_record_digest"] = _record_digest(operation_raw)
            operation = R48AuthorityOperation.from_dict(operation_raw)
            if any(item.operation_id == operation.operation_id for item in cycle.operations):
                raise R48Error("OPERATION_ID_CONFLICT", "operation already exists")
            updated = replace(cycle, operations=cycle.operations + (operation,), last_seq=event.seq)
        elif event.event_type in {"r4.8.authority_action.received.v1", "r4.8.operation.reconciled.v1"}:
            receipt = R48AuthorityReceipt.from_dict(_materialize(dict(payload["receipt"]), event))
            operation = _find_operation(cycle, receipt.operation_id)
            same = next((item for item in cycle.receipts if item.semantic_identity == receipt.semantic_identity), None)
            if same is not None:
                return replace(state, last_seq=event.seq, state_digest=_state_digest(replace(state, last_seq=event.seq)))
            receipts = cycle.receipts + (receipt,)
            outcome_status = {
                "APPLIED": R48OperationStatus.APPLIED,
                "REJECTED": R48OperationStatus.REJECTED,
                "BLOCKED": R48OperationStatus.BLOCKED,
                "STALE": R48OperationStatus.STALE,
                "UNKNOWN": R48OperationStatus.UNKNOWN,
                "CONFLICT": R48OperationStatus.CONFLICT,
            }[receipt.outcome.value]
            if operation.current_status is R48OperationStatus.APPLIED and receipt.authority_revision is not None and operation.authority_revision is not None and receipt.authority_revision < operation.authority_revision:
                updated = replace(cycle, status=R48CoordinationStatus.RECONCILIATION_REQUIRED, receipts=receipts, last_seq=event.seq)
            else:
                changed_operation = replace(operation, current_status=outcome_status, current_receipt_id=receipt.receipt_id, authority_operation_id=receipt.authority_operation_id, result_ref=receipt.result_ref, result_digest=receipt.result_digest, authority_revision=receipt.authority_revision, authority_outcome=receipt.outcome, proof_digest=receipt.proof_digest, owner_cursor=receipt.owner_cursor, observed_source_cursor=receipt.observed_source_cursor, current_state_digest="")
                changed_operation = replace(changed_operation, current_state_digest=_digest(changed_operation.to_dict()))
                operations = tuple(changed_operation if item.operation_id == operation.operation_id else item for item in cycle.operations)
                status = R48CoordinationStatus.ACTIVE if receipt.outcome is R48AuthorityOutcome.APPLIED else R48CoordinationStatus.RECONCILIATION_REQUIRED if receipt.outcome in {R48AuthorityOutcome.UNKNOWN, R48AuthorityOutcome.CONFLICT} else R48CoordinationStatus.BLOCKED if receipt.outcome is R48AuthorityOutcome.BLOCKED else R48CoordinationStatus.STALE
                updated = replace(cycle, operations=operations, receipts=receipts, status=status, last_seq=event.seq)
        elif event.event_type == "r4.8.cycle.waiting.v1":
            updated = replace(cycle, status=R48CoordinationStatus.WAITING, last_seq=event.seq)
        elif event.event_type == "r4.8.cycle.reentered.v1":
            record = R48ReentryRecord.from_dict(_materialize(dict(payload["reentry"]), event))
            step = _materialize_step(dict(payload["step"]), event)
            status = R48CoordinationStatus.RECONCILIATION_REQUIRED if record.kind.value in {"RECONCILE", "REVALIDATE"} else R48CoordinationStatus.ACTIVE
            steps = tuple(sorted(tuple(item for item in cycle.steps if item.step_id != step.step_id) + (step,), key=lambda item: item.step_id))
            updated = replace(cycle, phase=record.target_phase, status=status, steps=steps, reentries=cycle.reentries + (record,), last_seq=event.seq)
        elif event.event_type == "r4.8.cycle.closed.v1":
            updated = replace(cycle, phase=R48Phase.CLOSED, status=R48CoordinationStatus.COMPLETE, last_seq=event.seq)
        else:
            raise R48Error("UNKNOWN_EVENT", f"unsupported R4.8 event: {event.event_type}")
        updated = replace(updated, state_digest=_cycle_digest(updated))
        return _replace_cycle(replace(state, last_seq=event.seq), updated)


__all__ = ["R48State", "R48StateContribution", "R48ReducerContribution", "SUPPORTED_EVENTS", "initial_state"]
