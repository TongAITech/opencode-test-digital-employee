from __future__ import annotations

from typing import Any, Mapping

from aitest_runtime.durable_core import ComposedRuntimeState, PendingEvent, RuntimeError, SessionStatus, canonical_sha256
from aitest_runtime.execution_resume import EXTENSION_ID as EXECUTION_RESUME_EXTENSION_ID, ExecutionResumeState
from aitest_runtime.work_graph import EXTENSION_ID as WORK_GRAPH_EXTENSION_ID, TaskLifecycleState, WorkGraphState
from aitest_runtime.work_graph.contracts import TASK_TERMINAL

from .contracts import (
    BIND_LOGICAL_AGENT,
    CHILD_RESULT_RECORDED,
    DELEGATION_REGISTERED,
    JOINED,
    JOIN_CHILD_RESULT,
    LOGICAL_AGENT_BOUND,
    RECORD_CHILD_RESULT,
    REGISTER_DELEGATION,
    R25Error,
    SessionOrchestrationState,
    TASK_TRUTH_CONFLICT,
)


COMMAND_TYPES = frozenset({BIND_LOGICAL_AGENT, REGISTER_DELEGATION, RECORD_CHILD_RESULT, JOIN_CHILD_RESULT})
EVENT_TYPES = frozenset({LOGICAL_AGENT_BOUND, DELEGATION_REGISTERED, CHILD_RESULT_RECORDED, JOINED})


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise R25Error("R2_5_SCHEMA_INVALID", f"{name} must be a non-empty string")
    return value


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _non_negative(value: Any, name: str, *, optional: bool = False) -> int | None:
    if value is None and optional:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise R25Error("R2_5_SCHEMA_INVALID", f"{name} must be a non-negative integer")
    return value


def _positive(value: Any, name: str, *, optional: bool = False) -> int | None:
    if value is None and optional:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise R25Error("R2_5_SCHEMA_INVALID", f"{name} must be a positive integer")
    return value


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise R25Error("R2_5_SCHEMA_INVALID", f"{name} must be an object")
    return dict(value)


def _canonical_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _canonical_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    return value


def _canonical_child_digest(task: Any, terminal_state: str) -> str:
    outcome = _canonical_value(task.outcome) if task.outcome is not None else None
    return canonical_sha256({
        "task_id": task.task_id,
        "plan_revision_id": task.plan_revision_id,
        "terminal_state": terminal_state,
        "outcome": outcome,
    })


def _state_mapping(value: Any) -> Any:
    if isinstance(value, Mapping):
        return value
    to_dict = getattr(value, "to_dict", None)
    return to_dict() if callable(to_dict) else None


def _find_fact(value: Any, identifiers: Mapping[str, str]) -> Mapping[str, Any] | None:
    mapped = _state_mapping(value)
    if mapped is not None:
        if all(mapped.get(key) == expected for key, expected in identifiers.items()):
            return mapped
        for child in mapped.values():
            found = _find_fact(child, identifiers)
            if found is not None:
                return found
    elif isinstance(value, (tuple, list)):
        for child in value:
            found = _find_fact(child, identifiers)
            if found is not None:
                return found
    return None


def _validate_execution_reference(
    composed: ComposedRuntimeState,
    *,
    result_ref: Mapping[str, Any],
    result_digest: str | None,
    outcome: Mapping[str, Any] | None,
) -> Mapping[str, Any] | None:
    """Validate an explicitly referenced R1.4 fact without copying it into R2.5."""
    identifiers = {
        key: str(result_ref[key])
        for key in ("execution_fact_id", "evidence_id", "tool_execution_id")
        if result_ref.get(key) is not None
    }
    if not identifiers:
        return None
    extension_id = result_ref.get("extension_id")
    states = composed.extension_states.items()
    if extension_id is not None:
        selected = composed.extension_states.get(str(extension_id))
        states = () if selected is None else ((str(extension_id), selected),)
    fact = None
    for _, state in states:
        fact = _find_fact(state, identifiers)
        if fact is not None:
            break
    if fact is None:
        raise R25Error(TASK_TRUTH_CONFLICT, "ChildResult references a missing canonical execution/evidence fact")
    canonical_digest = fact.get("result_digest") or fact.get("content_digest")
    if result_digest is not None and canonical_digest is not None and result_digest != canonical_digest:
        raise R25Error(TASK_TRUTH_CONFLICT, "ChildResult result_digest disagrees with canonical execution/evidence truth")
    if outcome is not None:
        canonical_outcome = fact.get("outcome")
        if canonical_outcome is None:
            canonical_outcome = fact.get("redacted_result")
        if canonical_outcome is not None and _canonical_value(outcome) != _canonical_value(canonical_outcome):
            raise R25Error(TASK_TRUTH_CONFLICT, "ChildResult outcome disagrees with canonical execution/evidence truth")
    return fact


def _deterministic_command(command, operation_id: str, operation: str) -> None:
    expected = f"r2.5:{operation_id}:{operation}"
    if command.command_id != expected:
        raise R25Error("DETERMINISTIC_IDENTITY_MISMATCH", f"expected command_id {expected}")
    if command.idempotency_key not in (None, expected):
        raise R25Error("DETERMINISTIC_IDENTITY_MISMATCH", "idempotency_key must equal command_id")


def _state(composed: ComposedRuntimeState) -> SessionOrchestrationState:
    value = composed.extension_state("r2_5_session_orchestration")
    if not isinstance(value, SessionOrchestrationState):
        raise R25Error("EXTENSION_SCHEMA_MISMATCH", "invalid R2.5 extension state")
    return value


def _work_graph(composed: ComposedRuntimeState) -> WorkGraphState:
    value = composed.extension_state(WORK_GRAPH_EXTENSION_ID)
    if not isinstance(value, WorkGraphState):
        raise R25Error("EXTENSION_DEPENDENCY_MISSING", "R2.5 requires the R1.2 Work Graph extension")
    return value


def _execution(composed: ComposedRuntimeState) -> ExecutionResumeState:
    value = composed.extension_state(EXECUTION_RESUME_EXTENSION_ID)
    if not isinstance(value, ExecutionResumeState):
        raise R25Error("EXTENSION_DEPENDENCY_MISSING", "R2.5 requires the R1.3B Execution Resume extension")
    return value


def _attempt_by_root(execution: ExecutionResumeState, root_attempt_id: str):
    values = tuple(item for item in execution.attempts if item.root_attempt_id == root_attempt_id)
    return values[-1] if values else None


def _require_parent(composed: ComposedRuntimeState, root_attempt_id: str, parent_attempt_id: str | None = None):
    execution = _execution(composed)
    attempt = execution.attempt(parent_attempt_id) if parent_attempt_id else _attempt_by_root(execution, root_attempt_id)
    if attempt is None or attempt.root_attempt_id != root_attempt_id:
        raise R25Error("PARENT_ATTEMPT_NOT_FOUND", f"Parent root Attempt not found: {root_attempt_id}")
    return execution, attempt


def _require_child_truth(
    composed: ComposedRuntimeState,
    *,
    delegation,
    child_task_id: str,
    child_attempt_id: str,
    child_root_attempt_id: str,
    plan_revision_id: str,
    terminal_state: str,
    result_ref: Mapping[str, Any],
    result_digest: str | None,
    canonical_source_seq: int,
    outcome: Mapping[str, Any] | None,
) -> tuple[Any, Any]:
    work_graph = _work_graph(composed)
    execution = _execution(composed)
    task = work_graph.task(child_task_id)
    attempt = execution.attempt(child_attempt_id)
    if task is None or attempt is None:
        raise R25Error(TASK_TRUTH_CONFLICT, "ChildResult does not match canonical Task/Attempt truth")
    if (
        task.task_id != delegation.child_task_id
        or (delegation.child_root_attempt_id is not None and delegation.child_root_attempt_id != child_root_attempt_id)
        or task.plan_id != attempt.plan_id
        or task.plan_revision_id != attempt.plan_revision_id
        or task.plan_revision_id != plan_revision_id
        or attempt.task_id != child_task_id
        or attempt.root_attempt_id != child_root_attempt_id
        or execution.latest_attempt(child_task_id) is None
        or execution.latest_attempt(child_task_id).attempt_id != child_attempt_id
    ):
        raise R25Error(TASK_TRUTH_CONFLICT, "ChildResult identity is inconsistent with canonical Task/Attempt truth")
    actual = task.lifecycle_state.value
    if actual not in {item.value for item in TASK_TERMINAL} or terminal_state != actual:
        raise R25Error(TASK_TRUTH_CONFLICT, "Caller cannot declare a non-terminal or mismatched ChildResult")
    canonical_outcome = _canonical_value(task.outcome) if task.outcome is not None else None
    if _canonical_value(outcome) != canonical_outcome:
        raise R25Error(TASK_TRUTH_CONFLICT, "ChildResult outcome disagrees with canonical Task truth")
    fact = _validate_execution_reference(
        composed, result_ref=result_ref, result_digest=result_digest, outcome=outcome,
    )
    if fact is None:
        if canonical_source_seq != task.updated_seq:
            raise R25Error(TASK_TRUTH_CONFLICT, "ChildResult source sequence does not identify the canonical terminal Task fact")
        if result_digest != _canonical_child_digest(task, actual):
            raise R25Error(TASK_TRUTH_CONFLICT, "ChildResult result_digest disagrees with canonical Task truth")
    else:
        fact_seq = fact.get("created_seq")
        if isinstance(fact_seq, int) and canonical_source_seq != fact_seq:
            raise R25Error(TASK_TRUTH_CONFLICT, "ChildResult source sequence does not identify the referenced canonical fact")
    return task, attempt


def _bind(command, composed: ComposedRuntimeState) -> list[PendingEvent]:
    payload = dict(command.payload)
    required = {"binding_id", "logical_agent_id", "root_attempt_id", "attempt_id", "task_id", "session_id"}
    if set(payload) != required:
        raise R25Error("R2_5_SCHEMA_INVALID", "BIND_LOGICAL_AGENT payload contains unknown or missing fields")
    state = _state(composed)
    binding_id = _text(payload["binding_id"], "binding_id")
    _deterministic_command(command, binding_id, "BIND_LOGICAL_AGENT")
    if state.binding(binding_id) is not None:
        raise R25Error("BINDING_IMMUTABLE", f"LogicalAgent binding already exists: {binding_id}")
    session_id = _text(payload["session_id"], "session_id")
    session = composed.core_state.session(session_id)
    if session is None or session.mission_id != command.mission_id or session.status != SessionStatus.OPEN:
        raise R25Error("R2_5_SESSION_NOT_OPEN", "LogicalAgent binding requires an existing OPEN Core Session")
    execution = _execution(composed)
    attempt = execution.attempt(_text(payload["attempt_id"], "attempt_id"))
    if attempt is None:
        raise R25Error("ATTEMPT_NOT_FOUND", f"Attempt not found: {payload['attempt_id']}")
    if (
        attempt.root_attempt_id != _text(payload["root_attempt_id"], "root_attempt_id")
        or attempt.task_id != _text(payload["task_id"], "task_id")
        or attempt.runtime_session_id != session_id
    ):
        raise R25Error("LOGICAL_AGENT_BINDING_CONFLICT", "LogicalAgent binding is not an additive relation to the Attempt")
    if any(
        item.logical_agent_id == payload["logical_agent_id"]
        and item.root_attempt_id != attempt.root_attempt_id
        for item in state.bindings
    ):
        raise R25Error("LOGICAL_AGENT_BINDING_CONFLICT", "LogicalAgent is already bound to another root Attempt")
    if any(
        item.logical_agent_id == payload["logical_agent_id"] and item.root_attempt_id == attempt.root_attempt_id
        for item in state.bindings
    ):
        raise R25Error("LOGICAL_AGENT_BINDING_CONFLICT", "LogicalAgent is already bound to this root Attempt")
    if any(item.attempt_id == attempt.attempt_id and item.logical_agent_id != payload["logical_agent_id"] for item in state.bindings):
        raise R25Error("LOGICAL_AGENT_BINDING_CONFLICT", "Attempt is already related to another LogicalAgent")
    return [PendingEvent(LOGICAL_AGENT_BOUND, "LOGICAL_AGENT_BINDING", binding_id, payload, session_id=command.session_id)]


def _register(command, composed: ComposedRuntimeState) -> list[PendingEvent]:
    payload = dict(command.payload)
    required = {
        "delegation_id", "parent_root_attempt_id", "parent_attempt_id", "parent_task_id", "child_task_id",
        "expected_delegation_version", "expected_active_child_count",
        "max_total_children_per_parent", "max_active_children_per_parent", "logical_agent_id", "child_root_attempt_id",
    }
    if set(payload) != required:
        raise R25Error("R2_5_SCHEMA_INVALID", "REGISTER_DELEGATION payload contains unknown or missing fields")
    state = _state(composed)
    delegation_id = _text(payload["delegation_id"], "delegation_id")
    _deterministic_command(command, delegation_id, "REGISTER_DELEGATION")
    if state.delegation(delegation_id) is not None:
        raise R25Error("DELEGATION_IMMUTABLE", f"Delegation already exists: {delegation_id}")
    root = _text(payload["parent_root_attempt_id"], "parent_root_attempt_id")
    execution, parent = _require_parent(composed, root, _text(payload["parent_attempt_id"], "parent_attempt_id"))
    if parent.task_id != _text(payload["parent_task_id"], "parent_task_id"):
        raise R25Error("PARENT_ATTEMPT_CONFLICT", "Parent root Attempt and parent Task disagree")
    child_task_id = _text(payload["child_task_id"], "child_task_id")
    child = _work_graph(composed).task(child_task_id)
    if child is None:
        raise R25Error("CHILD_TASK_NOT_FOUND", f"Existing child Task not found: {child_task_id}")
    if child_task_id == parent.task_id:
        raise R25Error("CHILD_TASK_NOT_DISTINCT", "Child Task must be distinct from the parent Task")
    _optional_text(payload["logical_agent_id"], "logical_agent_id")
    version = _non_negative(payload["expected_delegation_version"], "expected_delegation_version")
    active = _non_negative(payload["expected_active_child_count"], "expected_active_child_count")
    if version != state.delegation_version(root):
        raise R25Error("DELEGATION_CAS_CONFLICT", "delegation_version does not match Event Stream history")
    if active != state.active_child_count(root):
        raise R25Error("DELEGATION_CAS_CONFLICT", "active_child_count does not match Event Stream replay")
    total_limit = _positive(payload["max_total_children_per_parent"], "max_total_children_per_parent", optional=True)
    active_limit = _positive(payload["max_active_children_per_parent"], "max_active_children_per_parent", optional=True)
    prior = state.delegations_for_parent(root)
    if prior:
        prior_total = prior[0].max_total_children_per_parent
        prior_active = prior[0].max_active_children_per_parent
        if total_limit != prior_total or active_limit != prior_active:
            raise R25Error("DELEGATION_QUOTA_POLICY_CONFLICT", "a Parent root Attempt cannot change its quota policy")
        total_limit, active_limit = prior_total, prior_active
    if total_limit is not None and version >= total_limit:
        raise R25Error("DELEGATION_TOTAL_BOUND_EXCEEDED", "max_total_children_per_parent has been reached")
    if active_limit is not None and active >= active_limit:
        raise R25Error("DELEGATION_ACTIVE_BOUND_EXCEEDED", "max_active_children_per_parent has been reached")
    child_root = _optional_text(payload["child_root_attempt_id"], "child_root_attempt_id")
    if child_root is not None and _attempt_by_root(execution, child_root) is None:
        raise R25Error("CHILD_ATTEMPT_NOT_FOUND", "child_root_attempt_id is not a canonical Attempt root")
    normalized = {
        **payload,
        "delegation_version": version + 1,
        "parent_root_attempt_id": root,
        "parent_attempt_id": parent.attempt_id,
        "parent_task_id": parent.task_id,
        "child_task_id": child_task_id,
    }
    return [PendingEvent(DELEGATION_REGISTERED, "DELEGATION", delegation_id, normalized, session_id=command.session_id)]


def _record_child_result(command, composed: ComposedRuntimeState) -> list[PendingEvent]:
    payload = dict(command.payload)
    required = {
        "child_result_id", "delegation_id", "parent_root_attempt_id", "child_task_id", "child_attempt_id",
        "child_root_attempt_id", "plan_revision_id", "terminal_state", "result_ref", "result_digest",
        "canonical_source_seq", "outcome",
    }
    if set(payload) != required:
        raise R25Error("R2_5_SCHEMA_INVALID", "RECORD_CHILD_RESULT payload contains unknown or missing fields")
    state = _state(composed)
    child_result_id = _text(payload["child_result_id"], "child_result_id")
    _deterministic_command(command, child_result_id, "RECORD_CHILD_RESULT")
    if state.child_result(child_result_id) is not None:
        raise R25Error("CHILD_RESULT_IMMUTABLE", f"ChildResult already exists: {child_result_id}")
    delegation = state.delegation(_text(payload["delegation_id"], "delegation_id"))
    if delegation is None:
        raise R25Error("DELEGATION_NOT_FOUND", f"Delegation not found: {payload['delegation_id']}")
    if delegation.parent_root_attempt_id != _text(payload["parent_root_attempt_id"], "parent_root_attempt_id"):
        raise R25Error(TASK_TRUTH_CONFLICT, "ChildResult parent lineage does not match Delegation")
    if any(item.delegation_id == delegation.delegation_id for item in state.child_results):
        raise R25Error("CHILD_RESULT_IMMUTABLE", "A Delegation accepts at most one immutable ChildResult")
    _require_child_truth(
        composed,
        delegation=delegation,
        child_task_id=_text(payload["child_task_id"], "child_task_id"),
        child_attempt_id=_text(payload["child_attempt_id"], "child_attempt_id"),
        child_root_attempt_id=_text(payload["child_root_attempt_id"], "child_root_attempt_id"),
        plan_revision_id=_text(payload["plan_revision_id"], "plan_revision_id"),
        terminal_state=_text(payload["terminal_state"], "terminal_state"),
        result_ref=_mapping(payload["result_ref"], "result_ref"),
        result_digest=payload["result_digest"],
        canonical_source_seq=_positive(payload["canonical_source_seq"], "canonical_source_seq"),
        outcome=None if payload["outcome"] is None else _mapping(payload["outcome"], "outcome"),
    )
    return [PendingEvent(CHILD_RESULT_RECORDED, "CHILD_RESULT", child_result_id, payload, session_id=command.session_id)]


def _join(command, composed: ComposedRuntimeState) -> list[PendingEvent]:
    payload = dict(command.payload)
    required = {
        "join_id", "parent_root_attempt_id", "delegation_id", "child_result_id", "expected_join_version", "metadata",
    }
    if set(payload) != required:
        raise R25Error("R2_5_SCHEMA_INVALID", "JOIN_CHILD_RESULT payload contains unknown or missing fields")
    state = _state(composed)
    join_id = _text(payload["join_id"], "join_id")
    _deterministic_command(command, join_id, "JOIN_CHILD_RESULT")
    if state.join(join_id) is not None:
        raise R25Error("JOIN_IMMUTABLE", f"Join already exists: {join_id}")
    root = _text(payload["parent_root_attempt_id"], "parent_root_attempt_id")
    _require_parent(composed, root)
    delegation = state.delegation(_text(payload["delegation_id"], "delegation_id"))
    result = state.child_result(_text(payload["child_result_id"], "child_result_id"))
    if delegation is None or result is None:
        raise R25Error("CHILD_RESULT_NOT_FOUND", "Join requires an immutable recorded ChildResult")
    if delegation.parent_root_attempt_id != root or result.delegation_id != delegation.delegation_id:
        raise R25Error("JOIN_LINEAGE_CONFLICT", "Join does not match Parent lineage and Delegation")
    expected = _non_negative(payload["expected_join_version"], "expected_join_version")
    if expected != state.join_version(delegation.delegation_id):
        raise R25Error("JOIN_CAS_CONFLICT", "join_version does not match Event Stream history")
    _mapping(payload["metadata"], "metadata")
    normalized = {**payload, "join_version": expected + 1, "parent_root_attempt_id": root}
    return [PendingEvent(JOINED, "CHILD_RESULT_JOIN", join_id, normalized, session_id=command.session_id)]


def handle(command, composed: ComposedRuntimeState) -> list[PendingEvent]:
    if command.type == BIND_LOGICAL_AGENT:
        return _bind(command, composed)
    if command.type == REGISTER_DELEGATION:
        return _register(command, composed)
    if command.type == RECORD_CHILD_RESULT:
        return _record_child_result(command, composed)
    if command.type == JOIN_CHILD_RESULT:
        return _join(command, composed)
    raise R25Error("EXTENSION_COMMAND_NOT_OWNED", f"unsupported R2.5 command: {command.type}")


class R25CommandContribution:
    def handle(self, command, composed):
        return handle(command, composed)
