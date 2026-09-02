from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from aitest_runtime.durable_core import EventEnvelope, MissionStatus, RuntimeError, RuntimeState, canonical_sha256
from aitest_runtime.execution_context import EventCursor

from .contracts import (
    EVENT_TYPES,
    EVIDENCE_EVENT,
    ExecutionFact,
    EvidenceRecord,
    OUTCOME_EVENT,
    RECONCILE_EVENT,
    REQUEST_EVENT,
    ReconciliationFact,
    SideEffectState,
    ToolExecutionIntent,
    ToolExecutionRecord,
    ToolExecutionState,
    ToolObservation,
    _cursor,
)


def _payload(event: EventEnvelope) -> Mapping[str, Any]:
    if event.event_type not in EVENT_TYPES:
        raise RuntimeError("EXTENSION_EVENT_NOT_OWNED", f"unsupported Tool Execution event: {event.event_type}")
    if event.session_id is None:
        raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Tool Execution events require a Runtime Session")
    return dict(event.payload)


def _validate_core(state: ToolExecutionState, event: EventEnvelope, core_state: RuntimeState) -> None:
    if event.mission_id != state.mission_id or core_state.mission_id != state.mission_id:
        raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Tool Execution Mission identity mismatch")
    if core_state.seq != event.seq:
        raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Tool Execution event does not share Core seq")
    if core_state.mission is None or core_state.mission.status in {
        MissionStatus.COMPLETED, MissionStatus.FAILED, MissionStatus.CANCELLED,
    }:
        raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "terminal or missing Mission cannot accept Tool Execution facts")


def _intent_digest(payload: Mapping[str, Any]) -> str:
    return canonical_sha256({
        "mission_id": payload["mission_id"], "plan_id": payload["plan_id"], "plan_revision_id": payload["plan_revision_id"],
        "task_id": payload["task_id"], "attempt_id": payload["attempt_id"], "runtime_session_id": payload["runtime_session_id"],
        "tool_execution_id": payload["tool_execution_id"], "capability_id": payload["capability_id"],
        "capability_version": payload["capability_version"], "provider_binding_id": payload["provider_binding_id"],
        "provider_binding_digest": payload["provider_binding_digest"], "context_cursor": payload["context_cursor"],
        "context_semantic_digest": payload.get("context_semantic_digest"), "input_digest": payload["input_digest"],
        "side_effect_policy": payload["side_effect_policy"], "input_reference": payload.get("input_reference"),
        "redacted_input": payload.get("redacted_input") or {}, "authorization_id": payload.get("authorization_id"),
    })


def _request(event: EventEnvelope, state: ToolExecutionState, core_state: RuntimeState) -> ToolExecutionState:
    payload = _payload(event)
    required = {
        "mission_id", "tool_execution_id", "plan_id", "plan_revision_id", "task_id", "attempt_id", "runtime_session_id",
        "capability_id", "capability_version", "provider_binding_id", "provider_binding_digest", "context_cursor",
        "context_semantic_digest", "input_digest", "side_effect_policy", "intent_digest", "idempotency_key",
        "input_reference", "redacted_input", "authorization_id",
    }
    if set(payload) != required:
        raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Tool Execution request event contains unknown or missing fields")
    if payload["tool_execution_id"] != event.entity_id or payload["mission_id"] != event.mission_id:
        raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Tool Execution request identity mismatch")
    if payload["runtime_session_id"] != event.session_id:
        raise RuntimeError("TOOL_EXECUTION_LINEAGE_MISMATCH", "request event session mismatch")
    cursor = _cursor(payload["context_cursor"])
    if cursor.mission_id != event.mission_id or cursor.through_seq > event.seq - 1:
        raise RuntimeError("TOOL_EXECUTION_CONTEXT_MISMATCH", "request context cursor is not prior to the Event")
    if payload["intent_digest"] != _intent_digest(payload):
        raise RuntimeError("TOOL_EXECUTION_INTENT_DIGEST_MISMATCH", "request intent digest does not match its fields")
    if state.execution(event.entity_id) is not None:
        raise RuntimeError("TOOL_EXECUTION_DUPLICATE", "Tool Execution request was already replayed")
    intent = ToolExecutionIntent(
        tool_execution_id=payload["tool_execution_id"], mission_id=event.mission_id, plan_id=payload["plan_id"],
        plan_revision_id=payload["plan_revision_id"], task_id=payload["task_id"], attempt_id=payload["attempt_id"],
        runtime_session_id=payload["runtime_session_id"], capability_id=payload["capability_id"],
        capability_version=payload["capability_version"], provider_binding_id=payload["provider_binding_id"],
        provider_binding_digest=payload["provider_binding_digest"], context_cursor=cursor, input_digest=payload["input_digest"],
        side_effect_policy=payload["side_effect_policy"], intent_digest=payload["intent_digest"],
        idempotency_key=payload["idempotency_key"], command_id=event.command_id, created_seq=event.seq,
        created_at=event.created_at, created_by={"type": event.initiator_type, "id": event.initiator_id},
        correlation_id=event.correlation_id, input_reference=payload["input_reference"],
        redacted_input=payload["redacted_input"], authorization_id=payload["authorization_id"],
        context_semantic_digest=payload["context_semantic_digest"],
    )
    return replace(state, executions=state.executions + (ToolExecutionRecord(intent),))


def _observe(event: EventEnvelope, state: ToolExecutionState, core_state: RuntimeState) -> ToolExecutionState:
    payload = _payload(event)
    if set(payload) != {"status", "side_effect_state", "result_digest", "result_reference", "redacted_result", "external_request_id", "error_code"}:
        raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Tool Execution observation event contains unknown or missing fields")
    record = state.execution(event.entity_id)
    if record is None:
        raise RuntimeError("TOOL_EXECUTION_NOT_FOUND", "observation has no prior execution intent")
    if event.session_id != record.intent.runtime_session_id:
        raise RuntimeError("TOOL_EXECUTION_LINEAGE_MISMATCH", "observation session differs from intent")
    if record.facts:
        raise RuntimeError("TOOL_EXECUTION_OUTCOME_ALREADY_RECORDED", "only one immutable Execution Fact is permitted")
    observation = ToolObservation.from_dict(payload)
    fact = ExecutionFact(
        **observation.__dict__, execution_fact_id=f"{event.entity_id}:fact:{event.seq}", tool_execution_id=event.entity_id,
        mission_id=event.mission_id, command_id=event.command_id, created_seq=event.seq, created_at=event.created_at,
        created_by={"type": event.initiator_type, "id": event.initiator_id},
    )
    return replace(state, executions=tuple(replace(item, facts=(fact,)) if item is record else item for item in state.executions))


def _reconcile(event: EventEnvelope, state: ToolExecutionState, core_state: RuntimeState) -> ToolExecutionState:
    payload = _payload(event)
    if set(payload) != {"reconciliation_id", "observation"}:
        raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Tool Execution reconciliation event contains unknown or missing fields")
    record = state.execution(event.entity_id)
    if record is None:
        raise RuntimeError("TOOL_EXECUTION_NOT_FOUND", "reconciliation has no prior execution intent")
    if event.session_id != record.intent.runtime_session_id:
        raise RuntimeError("TOOL_EXECUTION_LINEAGE_MISMATCH", "reconciliation session differs from intent")
    if any(item.reconciliation_id == payload["reconciliation_id"] for item in record.reconciliations):
        raise RuntimeError("TOOL_EXECUTION_RECONCILIATION_DUPLICATE", "reconciliation_id is already present")
    observation = ToolObservation.from_dict(payload["observation"])
    reconciliation = ReconciliationFact(
        **observation.__dict__, reconciliation_id=payload["reconciliation_id"], tool_execution_id=event.entity_id,
        mission_id=event.mission_id, command_id=event.command_id, created_seq=event.seq, created_at=event.created_at,
        created_by={"type": event.initiator_type, "id": event.initiator_id},
    )
    return replace(state, executions=tuple(replace(item, reconciliations=item.reconciliations + (reconciliation,)) if item is record else item for item in state.executions))


def _evidence(event: EventEnvelope, state: ToolExecutionState, core_state: RuntimeState) -> ToolExecutionState:
    payload = _payload(event)
    record = state.execution(payload.get("tool_execution_id"))
    if record is None:
        raise RuntimeError("TOOL_EXECUTION_NOT_FOUND", "evidence has no prior execution intent")
    if set(payload) != {
        "evidence_id", "tool_execution_id", "execution_fact_id", "mission_id", "evidence_type", "content_digest",
        "artifact_reference", "provenance", "metadata", "verification_method", "verified", "command_id", "created_seq", "created_at", "created_by",
    }:
        raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Evidence event contains unknown or missing fields")
    if event.entity_id != payload["evidence_id"] or payload["mission_id"] != event.mission_id or event.session_id != record.intent.runtime_session_id:
        raise RuntimeError("EVIDENCE_LINEAGE_MISMATCH", "Evidence identity does not match Tool Execution")
    if record.execution_fact is None or record.execution_fact.execution_fact_id != payload["execution_fact_id"]:
        raise RuntimeError("EVIDENCE_FACT_NOT_FOUND", "Evidence must reference the immutable Execution Fact")
    if any(item.evidence_id == event.entity_id for item in record.evidence):
        raise RuntimeError("EVIDENCE_DUPLICATE", "evidence_id is already present")
    evidence = EvidenceRecord(
        **{**dict(payload), "command_id": event.command_id, "created_seq": event.seq, "created_at": event.created_at,
           "created_by": {"type": event.initiator_type, "id": event.initiator_id}}
    )
    return replace(state, executions=tuple(replace(item, evidence=item.evidence + (evidence,)) if item is record else item for item in state.executions))


class ToolExecutionReducerContribution:
    def reduce(self, state: ToolExecutionState, event: EventEnvelope, core_state: RuntimeState) -> ToolExecutionState:
        if not isinstance(state, ToolExecutionState):
            raise RuntimeError("EXTENSION_SCHEMA_MISMATCH", "invalid Tool Execution state")
        _validate_core(state, event, core_state)
        if event.event_type == REQUEST_EVENT:
            return _request(event, state, core_state)
        if event.event_type == OUTCOME_EVENT:
            return _observe(event, state, core_state)
        if event.event_type == RECONCILE_EVENT:
            return _reconcile(event, state, core_state)
        if event.event_type == EVIDENCE_EVENT:
            return _evidence(event, state, core_state)
        raise RuntimeError("EXTENSION_EVENT_NOT_OWNED", f"unsupported Tool Execution event: {event.event_type}")


__all__ = ["ToolExecutionReducerContribution"]
