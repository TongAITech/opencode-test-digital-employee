from __future__ import annotations

from typing import Any, Mapping

from aitest_runtime.durable_core import (
    CommandEnvelope,
    ComposedRuntimeState,
    MissionStatus,
    PendingEvent,
    RuntimeError,
    canonical_sha256,
)

from .contracts import (
    CANONICALIZATION_VERSION,
    EXTENSION_ID,
    PROJECTION_VERSION,
    TASK_TERMINAL,
    WORK_GRAPH_SCHEMA_VERSION,
    PlanLifecycleState,
    TaskLifecycleState,
    WorkGraphState,
    require_text,
)


COMMAND_TYPES = frozenset(
    {
        "CREATE_PLAN",
        "RECORD_PLAN_REVISION",
        "ACTIVATE_PLAN_REVISION",
        "CLOSE_PLAN",
        "ARCHIVE_PLAN",
        "TRANSITION_TASK",
        "RECORD_WORK_SNAPSHOT",
    }
)


def _state(composed: ComposedRuntimeState) -> WorkGraphState:
    state = composed.extension_state(EXTENSION_ID)
    if not isinstance(state, WorkGraphState):
        raise RuntimeError("EXTENSION_SCHEMA_MISMATCH", "invalid Work Graph extension state")
    return state


def _require_mutable_mission(composed: ComposedRuntimeState) -> None:
    mission = composed.core_state.mission
    if mission is None:
        raise RuntimeError("MISSION_NOT_FOUND", f"Mission not found: {composed.mission_id}")
    if mission.status in {MissionStatus.COMPLETED, MissionStatus.FAILED, MissionStatus.CANCELLED}:
        raise RuntimeError("INVALID_STATE_TRANSITION", "terminal Mission cannot mutate Work Graph")


def _require_list(payload: Mapping[str, Any], key: str) -> list[Any]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise RuntimeError("COMMAND_SCHEMA_INVALID", f"payload.{key} must be an array")
    return value


def _optional_text(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return None if value is None else require_text(value, f"payload.{key}")


def _plan(state: WorkGraphState, plan_id: str):
    plan = state.plan(plan_id)
    if plan is None:
        raise RuntimeError("PLAN_NOT_FOUND", f"Plan not found: {plan_id}")
    return plan


def _require_open_plan(state: WorkGraphState, plan_id: str):
    plan = _plan(state, plan_id)
    if plan.lifecycle_state == PlanLifecycleState.ARCHIVED:
        raise RuntimeError("PLAN_ARCHIVED", f"Plan is archived: {plan_id}")
    if plan.lifecycle_state != PlanLifecycleState.OPEN:
        raise RuntimeError("PLAN_NOT_OPEN", f"Plan is not OPEN: {plan_id}")
    return plan


def _normalized_constraints(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(_require_list(payload, "constraints")):
        if not isinstance(raw, Mapping):
            raise RuntimeError("COMMAND_SCHEMA_INVALID", f"payload.constraints[{index}] must be an object")
        kind = require_text(raw.get("kind"), f"payload.constraints[{index}].kind")
        if "value" not in raw:
            raise RuntimeError("COMMAND_SCHEMA_INVALID", f"payload.constraints[{index}].value is required")
        result.append({"kind": kind, "value": raw["value"]})
    return result


def _normalized_tasks(payload: Mapping[str, Any], state: WorkGraphState) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    task_ids: set[str] = set()
    task_keys: set[str] = set()
    for index, raw in enumerate(_require_list(payload, "task_definitions")):
        if not isinstance(raw, Mapping):
            raise RuntimeError("COMMAND_SCHEMA_INVALID", f"payload.task_definitions[{index}] must be an object")
        task_id = require_text(raw.get("task_id"), f"payload.task_definitions[{index}].task_id")
        task_key = require_text(raw.get("task_key"), f"payload.task_definitions[{index}].task_key")
        intent = require_text(raw.get("intent"), f"payload.task_definitions[{index}].intent")
        if task_id in task_ids or state.task(task_id) is not None:
            raise RuntimeError("TASK_ID_CONFLICT", f"Task id already used: {task_id}")
        if task_key in task_keys:
            raise RuntimeError("TASK_KEY_CONFLICT", f"Task key repeated in Revision: {task_key}")
        criteria_raw = raw.get("acceptance_criteria")
        if not isinstance(criteria_raw, list):
            raise RuntimeError(
                "COMMAND_SCHEMA_INVALID",
                f"payload.task_definitions[{index}].acceptance_criteria must be an array",
            )
        criteria: list[dict[str, str]] = []
        criterion_ids: set[str] = set()
        for criterion_index, criterion in enumerate(criteria_raw):
            if not isinstance(criterion, Mapping):
                raise RuntimeError("COMMAND_SCHEMA_INVALID", "acceptance criterion must be an object")
            criterion_id = require_text(
                criterion.get("criterion_id"),
                f"payload.task_definitions[{index}].acceptance_criteria[{criterion_index}].criterion_id",
            )
            description = require_text(
                criterion.get("description"),
                f"payload.task_definitions[{index}].acceptance_criteria[{criterion_index}].description",
            )
            if criterion_id in criterion_ids:
                raise RuntimeError("COMMAND_SCHEMA_INVALID", f"duplicate criterion_id: {criterion_id}")
            criterion_ids.add(criterion_id)
            criteria.append({"criterion_id": criterion_id, "description": description})
        task_ids.add(task_id)
        task_keys.add(task_key)
        result.append(
            {
                "task_id": task_id,
                "task_key": task_key,
                "intent": intent,
                "acceptance_criteria": criteria,
            }
        )
    return result


def _has_cycle(task_ids: set[str], dependencies: list[dict[str, str]]) -> bool:
    successors = {task_id: [] for task_id in task_ids}
    for dependency in dependencies:
        successors[dependency["predecessor_task_id"]].append(dependency["successor_task_id"])
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> bool:
        if task_id in visiting:
            return True
        if task_id in visited:
            return False
        visiting.add(task_id)
        if any(visit(successor) for successor in successors[task_id]):
            return True
        visiting.remove(task_id)
        visited.add(task_id)
        return False

    return any(visit(task_id) for task_id in task_ids)


def _normalized_dependencies(
    payload: Mapping[str, Any],
    state: WorkGraphState,
    tasks: list[dict[str, Any]],
) -> list[dict[str, str]]:
    task_ids = {item["task_id"] for item in tasks}
    result: list[dict[str, str]] = []
    edges: set[tuple[str, str]] = set()
    for index, raw in enumerate(_require_list(payload, "dependencies")):
        if not isinstance(raw, Mapping):
            raise RuntimeError("COMMAND_SCHEMA_INVALID", f"payload.dependencies[{index}] must be an object")
        predecessor = require_text(
            raw.get("predecessor_task_id"), f"payload.dependencies[{index}].predecessor_task_id"
        )
        successor = require_text(
            raw.get("successor_task_id"), f"payload.dependencies[{index}].successor_task_id"
        )
        kind = require_text(raw.get("dependency_kind"), f"payload.dependencies[{index}].dependency_kind")
        if kind != "FINISH_TO_START":
            raise RuntimeError("UNSUPPORTED_DEPENDENCY_KIND", f"unsupported dependency kind: {kind}")
        if predecessor == successor:
            raise RuntimeError("DEPENDENCY_SELF_REFERENCE", f"Task cannot depend on itself: {predecessor}")
        missing = [task_id for task_id in (predecessor, successor) if task_id not in task_ids]
        if missing:
            if any(state.task(task_id) is not None for task_id in missing):
                raise RuntimeError("CROSS_REVISION_DEPENDENCY_UNSUPPORTED", "dependency crosses Revision boundary")
            raise RuntimeError("DEPENDENCY_TARGET_NOT_FOUND", f"dependency Task not found: {missing[0]}")
        edge = (predecessor, successor)
        if edge in edges:
            raise RuntimeError("COMMAND_SCHEMA_INVALID", "duplicate Task dependency")
        edges.add(edge)
        result.append(
            {
                "predecessor_task_id": predecessor,
                "successor_task_id": successor,
                "dependency_kind": kind,
            }
        )
    if _has_cycle(task_ids, result):
        raise RuntimeError("DEPENDENCY_CYCLE", "Task dependencies must be acyclic")
    return result


def _revision_event(command: CommandEnvelope, state: WorkGraphState) -> PendingEvent:
    plan_id = require_text(command.payload.get("plan_id"), "payload.plan_id")
    _require_open_plan(state, plan_id)
    revision_id = require_text(command.payload.get("revision_id"), "payload.revision_id")
    if state.revision(revision_id) is not None:
        raise RuntimeError("REVISION_ID_CONFLICT", f"Revision id already used: {revision_id}")
    parent_revision_id = command.payload.get("parent_revision_id")
    if parent_revision_id is not None:
        parent_revision_id = require_text(parent_revision_id, "payload.parent_revision_id")
        parent = state.revision(parent_revision_id)
        if parent is None:
            raise RuntimeError("REVISION_NOT_FOUND", f"Revision not found: {parent_revision_id}")
        if parent.plan_id != plan_id:
            raise RuntimeError("REVISION_PLAN_MISMATCH", "parent Revision belongs to another Plan")
    objective = require_text(command.payload.get("objective"), "payload.objective")
    constraints = _normalized_constraints(command.payload)
    tasks = _normalized_tasks(command.payload, state)
    dependencies = _normalized_dependencies(command.payload, state, tasks)
    content = {
        "plan_id": plan_id,
        "revision_id": revision_id,
        "parent_revision_id": parent_revision_id,
        "content_schema_version": WORK_GRAPH_SCHEMA_VERSION,
        "objective": objective,
        "constraints": constraints,
        "task_definitions": tasks,
        "dependencies": dependencies,
    }
    return PendingEvent(
        "plan.revision_recorded.v1",
        "PLAN_REVISION",
        revision_id,
        {**content, "content_hash": canonical_sha256(content)},
    )


def _normalize_outcome(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise RuntimeError("TASK_OUTCOME_REQUIRED", "terminal Task transition requires payload.outcome")
    summary = require_text(value.get("summary"), "payload.outcome.summary")
    raw_references = value.get("external_references", [])
    if not isinstance(raw_references, list):
        raise RuntimeError("COMMAND_SCHEMA_INVALID", "payload.outcome.external_references must be an array")
    references = []
    for index, raw in enumerate(raw_references):
        if not isinstance(raw, Mapping):
            raise RuntimeError("COMMAND_SCHEMA_INVALID", "external reference must be an object")
        reference = {
            "namespace": require_text(raw.get("namespace"), f"external_references[{index}].namespace"),
            "id": require_text(raw.get("id"), f"external_references[{index}].id"),
        }
        if raw.get("version") is not None:
            reference["version"] = require_text(raw.get("version"), f"external_references[{index}].version")
        references.append(reference)
    return {"summary": summary, "external_references": references}


def _transition_event(command: CommandEnvelope, state: WorkGraphState) -> PendingEvent:
    plan_id = require_text(command.payload.get("plan_id"), "payload.plan_id")
    revision_id = require_text(command.payload.get("plan_revision_id"), "payload.plan_revision_id")
    task_id = require_text(command.payload.get("task_id"), "payload.task_id")
    plan = _plan(state, plan_id)
    task = state.task(task_id)
    if task is None:
        raise RuntimeError("TASK_NOT_FOUND", f"Task not found: {task_id}")
    if task.plan_id != plan_id or task.plan_revision_id != revision_id:
        raise RuntimeError("REVISION_PLAN_MISMATCH", "Task identity does not match Plan Revision")
    try:
        target = TaskLifecycleState(require_text(command.payload.get("target_state"), "payload.target_state"))
    except ValueError as exc:
        raise RuntimeError("COMMAND_SCHEMA_INVALID", "unsupported Task target_state") from exc
    if target == TaskLifecycleState.ACTIVE:
        if command.payload.get("outcome") is not None:
            raise RuntimeError("TASK_OUTCOME_NOT_ALLOWED", "ACTIVE transition cannot record outcome")
        if task.lifecycle_state != TaskLifecycleState.PENDING:
            if task.lifecycle_state in TASK_TERMINAL:
                raise RuntimeError("TASK_TERMINAL", f"Task is terminal: {task_id}")
            raise RuntimeError("INVALID_TASK_TRANSITION", "Task can enter ACTIVE only from PENDING")
        if plan.lifecycle_state != PlanLifecycleState.OPEN:
            raise RuntimeError("PLAN_NOT_OPEN", f"Plan is not OPEN: {plan_id}")
        if plan.current_revision_id != revision_id:
            raise RuntimeError("TASK_REVISION_NOT_CURRENT", "only current Revision Tasks may enter ACTIVE")
        event_type = "task.lifecycle_changed.v1"
        outcome = None
    elif target in TASK_TERMINAL:
        if task.lifecycle_state in TASK_TERMINAL:
            raise RuntimeError("TASK_TERMINAL", f"Task is terminal: {task_id}")
        if target in {TaskLifecycleState.SUCCEEDED, TaskLifecycleState.FAILED} and task.lifecycle_state != TaskLifecycleState.ACTIVE:
            raise RuntimeError("INVALID_TASK_TRANSITION", f"{target.value} requires ACTIVE Task")
        if target == TaskLifecycleState.CANCELLED and task.lifecycle_state not in {
            TaskLifecycleState.PENDING,
            TaskLifecycleState.ACTIVE,
        }:
            raise RuntimeError("INVALID_TASK_TRANSITION", "Task cannot be CANCELLED from current state")
        outcome = _normalize_outcome(command.payload.get("outcome"))
        event_type = "task.outcome_recorded.v1"
    else:
        raise RuntimeError("INVALID_TASK_TRANSITION", f"unsupported Task transition: {target.value}")
    event_payload = {
        "plan_id": plan_id,
        "plan_revision_id": revision_id,
        "task_id": task_id,
        "from_state": task.lifecycle_state.value,
        "to_state": target.value,
        "reason_code": _optional_text(command.payload, "reason_code"),
        "reason_summary": _optional_text(command.payload, "reason_summary"),
    }
    if outcome is not None:
        event_payload["outcome"] = outcome
    return PendingEvent(event_type, "TASK", task_id, event_payload)


def snapshot_state_payload(
    composed: ComposedRuntimeState,
    scope: str,
    plan_id: str | None,
) -> dict[str, Any]:
    work_graph = _state(composed)
    scoped = work_graph if scope == "MISSION" else work_graph.plan_scope(str(plan_id))
    return {
        "mission_id": composed.mission_id,
        "as_of_seq": composed.seq,
        "scope": scope,
        "plan_id": plan_id,
        "core_state": composed.core_state.to_dict(),
        "work_graph_state": scoped.to_dict(),
    }


class WorkGraphCommandContribution:
    def handle(self, command: CommandEnvelope, composed: ComposedRuntimeState) -> list[PendingEvent]:
        if command.type not in COMMAND_TYPES:
            raise RuntimeError("EXTENSION_COMMAND_NOT_OWNED", f"unsupported Work Graph command: {command.type}")
        _require_mutable_mission(composed)
        state = _state(composed)
        if command.type == "CREATE_PLAN":
            plan_id = require_text(command.payload.get("plan_id"), "payload.plan_id")
            if state.plan(plan_id) is not None:
                raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", f"Plan already exists: {plan_id}")
            return [PendingEvent("plan.created.v1", "PLAN", plan_id, {"plan_id": plan_id})]
        if command.type == "RECORD_PLAN_REVISION":
            return [_revision_event(command, state)]
        if command.type == "ACTIVATE_PLAN_REVISION":
            plan_id = require_text(command.payload.get("plan_id"), "payload.plan_id")
            revision_id = require_text(command.payload.get("revision_id"), "payload.revision_id")
            plan = _require_open_plan(state, plan_id)
            revision = state.revision(revision_id)
            if revision is None:
                raise RuntimeError("REVISION_NOT_FOUND", f"Revision not found: {revision_id}")
            if revision.plan_id != plan_id:
                raise RuntimeError("REVISION_PLAN_MISMATCH", "Revision belongs to another Plan")
            if plan.current_revision_id == revision_id:
                raise RuntimeError("REVISION_ALREADY_CURRENT", f"Revision already current: {revision_id}")
            return [
                PendingEvent(
                    "plan.revision_activated.v1",
                    "PLAN_REVISION",
                    revision_id,
                    {
                        "plan_id": plan_id,
                        "revision_id": revision_id,
                        "previous_revision_id": plan.current_revision_id,
                    },
                )
            ]
        if command.type in {"CLOSE_PLAN", "ARCHIVE_PLAN"}:
            plan_id = require_text(command.payload.get("plan_id"), "payload.plan_id")
            reason_code = require_text(command.payload.get("reason_code"), "payload.reason_code")
            plan = _plan(state, plan_id)
            if command.type == "CLOSE_PLAN":
                if plan.lifecycle_state == PlanLifecycleState.ARCHIVED:
                    raise RuntimeError("PLAN_ARCHIVED", f"Plan is archived: {plan_id}")
                if plan.lifecycle_state != PlanLifecycleState.OPEN:
                    raise RuntimeError("PLAN_NOT_OPEN", f"Plan is not OPEN: {plan_id}")
                if any(task.lifecycle_state not in TASK_TERMINAL for task in state.tasks if task.plan_id == plan_id):
                    raise RuntimeError("PLAN_HAS_NONTERMINAL_TASKS", "Plan has non-terminal Tasks")
                target = PlanLifecycleState.CLOSED
            else:
                if plan.lifecycle_state == PlanLifecycleState.ARCHIVED:
                    raise RuntimeError("PLAN_ARCHIVED", f"Plan is archived: {plan_id}")
                if plan.lifecycle_state != PlanLifecycleState.CLOSED:
                    raise RuntimeError("PLAN_NOT_OPEN", "only CLOSED Plan can be archived")
                target = PlanLifecycleState.ARCHIVED
            return [
                PendingEvent(
                    "plan.lifecycle_changed.v1",
                    "PLAN",
                    plan_id,
                    {
                        "plan_id": plan_id,
                        "from_state": plan.lifecycle_state.value,
                        "to_state": target.value,
                        "reason_code": reason_code,
                        "reason_summary": _optional_text(command.payload, "reason_summary"),
                    },
                )
            ]
        if command.type == "TRANSITION_TASK":
            return [_transition_event(command, state)]
        snapshot_id = require_text(command.payload.get("snapshot_id"), "payload.snapshot_id")
        if "state_payload" in command.payload or "payload_hash" in command.payload:
            raise RuntimeError(
                "COMMAND_SCHEMA_INVALID",
                "Snapshot state_payload and payload_hash are generated by the Runtime",
            )
        if state.snapshot(snapshot_id) is not None:
            raise RuntimeError("SNAPSHOT_ID_CONFLICT", f"Snapshot id already used: {snapshot_id}")
        scope = require_text(command.payload.get("scope"), "payload.scope")
        plan_id = command.payload.get("plan_id")
        if scope == "MISSION":
            if plan_id is not None:
                raise RuntimeError("SNAPSHOT_SCOPE_INVALID", "MISSION Snapshot cannot specify plan_id")
        elif scope == "PLAN":
            plan_id = require_text(plan_id, "payload.plan_id")
            _plan(state, plan_id)
        else:
            raise RuntimeError("SNAPSHOT_SCOPE_INVALID", f"unsupported Snapshot scope: {scope}")
        as_of_seq = command.payload.get("as_of_seq")
        if not isinstance(as_of_seq, int) or isinstance(as_of_seq, bool) or as_of_seq != command.expected_seq:
            raise RuntimeError("SNAPSHOT_AS_OF_SEQ_MISMATCH", "Snapshot as_of_seq must equal command.expected_seq")
        state_payload = snapshot_state_payload(composed, scope, plan_id)
        return [
            PendingEvent(
                "snapshot.recorded.v1",
                "SNAPSHOT",
                snapshot_id,
                {
                    "snapshot_id": snapshot_id,
                    "scope": scope,
                    "plan_id": plan_id,
                    "as_of_seq": as_of_seq,
                    "work_graph_schema_version": WORK_GRAPH_SCHEMA_VERSION,
                    "projection_version": PROJECTION_VERSION,
                    "canonicalization_version": CANONICALIZATION_VERSION,
                    "payload_hash": canonical_sha256(state_payload),
                    "state_payload": state_payload,
                },
            )
        ]
