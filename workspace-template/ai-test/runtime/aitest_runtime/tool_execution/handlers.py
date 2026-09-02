from __future__ import annotations

from typing import Any, Mapping

from aitest_runtime.durable_core import CommandEnvelope, ComposedRuntimeState, PendingEvent, RuntimeError, SessionStatus
from aitest_runtime.execution_context import EventCursor
from aitest_runtime.execution_resume import EXTENSION_ID as EXECUTION_RESUME_EXTENSION_ID, ExecutionResumeState
from aitest_runtime.provider_binding import EXTENSION_ID as PROVIDER_BINDING_EXTENSION_ID, ProviderBindingState
from aitest_runtime.work_graph import EXTENSION_ID as WORK_GRAPH_EXTENSION_ID, WorkGraphState

from .contracts import (
    COMMAND_TYPES,
    EVIDENCE_COMMAND,
    EVIDENCE_EVENT,
    EVENT_TYPES,
    ExecutionFact,
    EvidenceRecord,
    OUTCOME_COMMAND,
    OUTCOME_EVENT,
    RECONCILE_COMMAND,
    RECONCILE_EVENT,
    REQUEST_COMMAND,
    REQUEST_EVENT,
    ReconciliationFact,
    SideEffectPolicy,
    SideEffectState,
    ToolExecutionIntent,
    ToolExecutionRecord,
    ToolExecutionState,
    ToolObservation,
    _created_by,
    _cursor,
    _digest,
    _mapping,
    _text,
)


PAYLOAD_FIELDS = {
    REQUEST_COMMAND: frozenset({
        "tool_execution_id", "plan_id", "plan_revision_id", "task_id", "attempt_id", "runtime_session_id",
        "capability_id", "capability_version", "provider_binding_id", "provider_binding_digest", "context_cursor",
        "context_semantic_digest", "input_digest", "side_effect_policy", "intent_digest", "idempotency_key",
        "input_reference", "redacted_input", "authorization_id",
    }),
    OUTCOME_COMMAND: frozenset({"tool_execution_id", "observation"}),
    RECONCILE_COMMAND: frozenset({"tool_execution_id", "reconciliation_id", "observation"}),
    EVIDENCE_COMMAND: frozenset({"evidence"}),
}


def _state(composed: ComposedRuntimeState) -> ToolExecutionState:
    from .contracts import EXTENSION_ID

    value = composed.extension_state(EXTENSION_ID)
    if not isinstance(value, ToolExecutionState):
        raise RuntimeError("EXTENSION_SCHEMA_MISMATCH", "invalid Tool Execution state")
    return value


def _execution_state(composed: ComposedRuntimeState) -> ExecutionResumeState:
    value = composed.extension_state(EXECUTION_RESUME_EXTENSION_ID)
    if not isinstance(value, ExecutionResumeState):
        raise RuntimeError("EXTENSION_SCHEMA_MISMATCH", "invalid Execution Resume state")
    return value


def _binding_state(composed: ComposedRuntimeState) -> ProviderBindingState:
    value = composed.extension_state(PROVIDER_BINDING_EXTENSION_ID)
    if not isinstance(value, ProviderBindingState):
        raise RuntimeError("EXTENSION_SCHEMA_MISMATCH", "invalid Provider Binding state")
    return value


def _work_graph_state(composed: ComposedRuntimeState) -> WorkGraphState:
    value = composed.extension_state(WORK_GRAPH_EXTENSION_ID)
    if not isinstance(value, WorkGraphState):
        raise RuntimeError("EXTENSION_SCHEMA_MISMATCH", "invalid Work Graph state")
    return value


def _require_runtime(composed: ComposedRuntimeState, command: CommandEnvelope) -> None:
    mission = composed.core_state.mission
    if mission is None:
        raise RuntimeError("MISSION_NOT_FOUND", f"Mission not found: {command.mission_id}")
    if mission.status.value != "ACTIVE":
        raise RuntimeError("INVALID_STATE_TRANSITION", "Tool Execution requires an ACTIVE Mission")
    if command.session_id is None:
        raise RuntimeError("TOOL_EXECUTION_SESSION_REQUIRED", "Tool Execution requires a Runtime Session")
    session = composed.core_state.session(command.session_id)
    if session is None or session.mission_id != command.mission_id or session.status != SessionStatus.OPEN:
        raise RuntimeError("EXECUTION_SESSION_NOT_OPEN", f"Runtime Session is not OPEN: {command.session_id}")


def _require_lineage(composed: ComposedRuntimeState, command: CommandEnvelope, payload: Mapping[str, Any]) -> Any:
    execution_state = _execution_state(composed)
    attempt_id = _text(payload["attempt_id"], "attempt_id")
    attempt = execution_state.attempt(attempt_id)
    if attempt is None:
        raise RuntimeError("TOOL_EXECUTION_ATTEMPT_NOT_FOUND", f"Attempt not found: {attempt_id}")
    if attempt.mission_id != command.mission_id or attempt.runtime_session_id != command.session_id:
        raise RuntimeError("TOOL_EXECUTION_LINEAGE_MISMATCH", "Attempt does not belong to the Runtime Session")
    if execution_state.latest_attempt(attempt.task_id) != attempt:
        raise RuntimeError("TOOL_EXECUTION_ATTEMPT_NOT_LATEST", "Tool Execution requires the latest Attempt")
    for name in ("plan_id", "plan_revision_id", "task_id"):
        if payload[name] != getattr(attempt, name):
            raise RuntimeError("TOOL_EXECUTION_LINEAGE_MISMATCH", f"{name} does not match Attempt")
    cursor = _cursor(payload["context_cursor"])
    if cursor != attempt.context_cursor:
        raise RuntimeError("TOOL_EXECUTION_CONTEXT_MISMATCH", "context cursor does not match Attempt")
    if payload.get("context_semantic_digest") not in {None, attempt.context_semantic_digest}:
        raise RuntimeError("TOOL_EXECUTION_CONTEXT_MISMATCH", "context semantic digest does not match Attempt")
    binding = _binding_state(composed).binding(attempt.attempt_id)
    if binding is None:
        raise RuntimeError("TOOL_EXECUTION_PROVIDER_BINDING_NOT_FOUND", "ProviderBinding was not found in Runtime replay")
    if payload["provider_binding_id"] != binding.attempt_id:
        raise RuntimeError("TOOL_EXECUTION_PROVIDER_BINDING_MISMATCH", "ProviderBinding identity does not match Attempt")
    from aitest_runtime.durable_core import canonical_sha256

    if payload["provider_binding_digest"] != canonical_sha256(binding.to_dict()):
        raise RuntimeError("TOOL_EXECUTION_PROVIDER_BINDING_MISMATCH", "ProviderBinding digest does not match Runtime fact")
    graph = _work_graph_state(composed)
    task = graph.task(attempt.task_id)
    if task is None or task.plan_id != attempt.plan_id or task.plan_revision_id != attempt.plan_revision_id:
        raise RuntimeError("TOOL_EXECUTION_TASK_NOT_FOUND", "Attempt Task is not present in the Work Graph")
    return attempt


def _request_payload(command: CommandEnvelope) -> dict[str, Any]:
    optional = {"context_semantic_digest", "input_reference", "redacted_input", "authorization_id", "idempotency_key"}
    required = PAYLOAD_FIELDS[REQUEST_COMMAND] - optional
    if not required <= set(command.payload) or set(command.payload) - PAYLOAD_FIELDS[REQUEST_COMMAND]:
        raise RuntimeError("COMMAND_SCHEMA_INVALID", "Tool Execution request contains unknown or missing fields")
    payload = dict(command.payload)
    payload.setdefault("context_semantic_digest", None)
    payload.setdefault("input_reference", None)
    payload.setdefault("redacted_input", {})
    payload.setdefault("authorization_id", None)
    payload.setdefault("idempotency_key", command.idempotency_key)
    if payload["runtime_session_id"] != command.session_id:
        raise RuntimeError("TOOL_EXECUTION_LINEAGE_MISMATCH", "payload Runtime Session differs from Command")
    if payload["idempotency_key"] != command.idempotency_key:
        raise RuntimeError("TOOL_EXECUTION_IDEMPOTENCY_MISMATCH", "payload idempotency key differs from Command")
    payload["context_cursor"] = _cursor(payload["context_cursor"]).to_dict()
    payload["provider_binding_digest"] = _digest(payload["provider_binding_digest"], "provider_binding_digest")
    payload["input_digest"] = _digest(payload["input_digest"], "input_digest")
    payload["redacted_input"] = _mapping(payload["redacted_input"], "redacted_input")
    policy = payload["side_effect_policy"]
    try:
        payload["side_effect_policy"] = policy if isinstance(policy, SideEffectPolicy) else SideEffectPolicy(policy)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("TOOL_EXECUTION_POLICY_INVALID", "side_effect_policy is invalid") from exc
    if payload["side_effect_policy"] == SideEffectPolicy.IRREVERSIBLE and not payload.get("authorization_id"):
        raise RuntimeError("TOOL_EXECUTION_AUTHORIZATION_REQUIRED", "IRREVERSIBLE side effects require explicit authorization")
    _text(payload["tool_execution_id"], "tool_execution_id")
    _text(payload["capability_id"], "capability_id")
    _text(payload["provider_binding_id"], "provider_binding_id")
    if not isinstance(payload["capability_version"], int) or isinstance(payload["capability_version"], bool) or payload["capability_version"] < 1:
        raise RuntimeError("COMMAND_SCHEMA_INVALID", "capability_version must be positive")
    _text(payload["intent_digest"], "intent_digest")
    return payload


def _observation(value: Any) -> ToolObservation:
    try:
        return value if isinstance(value, ToolObservation) else ToolObservation.from_dict(value)
    except (TypeError, ValueError, RuntimeError) as exc:
        if isinstance(exc, RuntimeError) and exc.code == "TOOL_EXECUTION_SCHEMA_INVALID":
            raise RuntimeError("TOOL_EXECUTION_OBSERVATION_INVALID", exc.message) from exc
        raise RuntimeError("TOOL_EXECUTION_OBSERVATION_INVALID", "observation is invalid") from exc


def _handle_request(command: CommandEnvelope, composed: ComposedRuntimeState) -> list[PendingEvent]:
    _require_runtime(composed, command)
    payload = _request_payload(command)
    attempt_payload = {**payload, "attempt_id": payload["attempt_id"]}
    attempt = _require_lineage(composed, command, attempt_payload)
    if payload["context_semantic_digest"] is None:
        payload["context_semantic_digest"] = attempt.context_semantic_digest
    state = _state(composed)
    existing = state.execution(payload["tool_execution_id"])
    if existing is not None:
        if existing.intent.intent_digest == payload["intent_digest"]:
            raise RuntimeError("TOOL_EXECUTION_DUPLICATE", "tool_execution_id already has the same intent")
        raise RuntimeError("TOOL_EXECUTION_INTENT_CONFLICT", "tool_execution_id already has a different intent")
    if payload["idempotency_key"] is not None:
        by_key = state.by_idempotency_key(payload["idempotency_key"])
        if by_key is not None:
            if by_key.intent.intent_digest == payload["intent_digest"]:
                raise RuntimeError("TOOL_EXECUTION_DUPLICATE", "idempotency key already owns this intent")
            raise RuntimeError("TOOL_EXECUTION_SAME_KEY_CONFLICT", "idempotency key already owns a different intent")
    event_payload = dict(payload)
    event_payload["mission_id"] = command.mission_id
    event_payload["context_cursor"] = _cursor(payload["context_cursor"]).to_dict()
    event_payload["context_semantic_digest"] = payload.get("context_semantic_digest") or attempt.context_semantic_digest
    event_payload["side_effect_policy"] = payload["side_effect_policy"].value
    return [PendingEvent(REQUEST_EVENT, "TOOL_EXECUTION", payload["tool_execution_id"], event_payload, session_id=command.session_id)]


def _handle_outcome(command: CommandEnvelope, composed: ComposedRuntimeState) -> list[PendingEvent]:
    _require_runtime(composed, command)
    if set(command.payload) != PAYLOAD_FIELDS[OUTCOME_COMMAND]:
        raise RuntimeError("COMMAND_SCHEMA_INVALID", "Tool Execution outcome contains unknown or missing fields")
    execution_id = _text(command.payload["tool_execution_id"], "tool_execution_id")
    state = _state(composed)
    record = state.execution(execution_id)
    if record is None:
        raise RuntimeError("TOOL_EXECUTION_NOT_FOUND", f"Tool Execution not found: {execution_id}")
    observation = _observation(command.payload["observation"])
    if record.facts:
        raise RuntimeError("TOOL_EXECUTION_OUTCOME_ALREADY_RECORDED", "Tool Execution already has an immutable Execution Fact")
    return [PendingEvent(OUTCOME_EVENT, "TOOL_EXECUTION", execution_id, observation.to_dict(), session_id=command.session_id)]


def _handle_reconcile(command: CommandEnvelope, composed: ComposedRuntimeState) -> list[PendingEvent]:
    _require_runtime(composed, command)
    if set(command.payload) != PAYLOAD_FIELDS[RECONCILE_COMMAND]:
        raise RuntimeError("COMMAND_SCHEMA_INVALID", "Tool Execution reconciliation contains unknown or missing fields")
    execution_id = _text(command.payload["tool_execution_id"], "tool_execution_id")
    reconciliation_id = _text(command.payload["reconciliation_id"], "reconciliation_id")
    record = _state(composed).execution(execution_id)
    if record is None:
        raise RuntimeError("TOOL_EXECUTION_NOT_FOUND", f"Tool Execution not found: {execution_id}")
    if any(item.reconciliation_id == reconciliation_id for item in record.reconciliations):
        raise RuntimeError("TOOL_EXECUTION_RECONCILIATION_DUPLICATE", "reconciliation_id is already recorded")
    observation = _observation(command.payload["observation"])
    if observation.status == SideEffectState.ATTEMPTED:
        raise RuntimeError("TOOL_EXECUTION_RECONCILIATION_INVALID", "reconciliation must classify an external result")
    if record.execution_fact is not None and record.execution_fact.side_effect_state == SideEffectState.CONFIRMED:
        raise RuntimeError("TOOL_EXECUTION_ALREADY_CONFIRMED", "a confirmed Execution Fact cannot be reconciled")
    return [
        PendingEvent(
            RECONCILE_EVENT,
            "TOOL_EXECUTION",
            execution_id,
            {"reconciliation_id": reconciliation_id, "observation": observation.to_dict()},
            session_id=command.session_id,
        )
    ]


def _handle_evidence(command: CommandEnvelope, composed: ComposedRuntimeState) -> list[PendingEvent]:
    _require_runtime(composed, command)
    if set(command.payload) != PAYLOAD_FIELDS[EVIDENCE_COMMAND]:
        raise RuntimeError("COMMAND_SCHEMA_INVALID", "Evidence command contains unknown or missing fields")
    raw = command.payload["evidence"]
    if not isinstance(raw, Mapping):
        raise RuntimeError("EVIDENCE_SCHEMA_INVALID", "evidence must be an object")
    evidence = EvidenceRecord.from_dict({
        **dict(raw),
        "mission_id": command.mission_id,
        "command_id": command.command_id,
        "created_seq": command.expected_seq + 1,
        "created_at": str(raw.get("created_at") or "pending"),
        "created_by": {"type": command.actor.type, "id": command.actor.id},
    })
    record = _state(composed).execution(evidence.tool_execution_id)
    if record is None:
        raise RuntimeError("TOOL_EXECUTION_NOT_FOUND", f"Tool Execution not found: {evidence.tool_execution_id}")
    fact = record.execution_fact
    if fact is None or fact.execution_fact_id != evidence.execution_fact_id:
        raise RuntimeError("EVIDENCE_FACT_NOT_FOUND", "Evidence must reference an immutable Execution Fact")
    if any(item.evidence_id == evidence.evidence_id for item in record.evidence):
        raise RuntimeError("EVIDENCE_DUPLICATE", "evidence_id is already recorded")
    return [PendingEvent(EVIDENCE_EVENT, "TOOL_EVIDENCE", evidence.evidence_id, evidence.to_dict(), session_id=command.session_id)]


class ToolExecutionCommandContribution:
    def handle(self, command: CommandEnvelope, composed: ComposedRuntimeState) -> list[PendingEvent]:
        if command.type == REQUEST_COMMAND:
            return _handle_request(command, composed)
        if command.type == OUTCOME_COMMAND:
            return _handle_outcome(command, composed)
        if command.type == RECONCILE_COMMAND:
            return _handle_reconcile(command, composed)
        if command.type == EVIDENCE_COMMAND:
            return _handle_evidence(command, composed)
        raise RuntimeError("EXTENSION_COMMAND_NOT_OWNED", f"unsupported Tool Execution command: {command.type}")


__all__ = ["COMMAND_TYPES", "EVENT_TYPES", "PAYLOAD_FIELDS", "ToolExecutionCommandContribution"]
