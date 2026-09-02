from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from aitest_runtime.durable_core import EventEnvelope, MissionStatus, RuntimeError, RuntimeState, canonical_sha256

from .contracts import (
    TASK_TERMINAL,
    WORK_GRAPH_SCHEMA_VERSION,
    PlanLifecycleState,
    PlanRevisionState,
    PlanState,
    SnapshotIndex,
    TaskDependency,
    TaskLifecycleState,
    TaskState,
    WorkGraphState,
)


EVENT_TYPES = frozenset(
    {
        "plan.created.v1",
        "plan.lifecycle_changed.v1",
        "plan.revision_recorded.v1",
        "plan.revision_activated.v1",
        "task.lifecycle_changed.v1",
        "task.outcome_recorded.v1",
        "snapshot.recorded.v1",
    }
)


def _replace_plan(state: WorkGraphState, plan: PlanState) -> tuple[PlanState, ...]:
    return tuple(plan if item.plan_id == plan.plan_id else item for item in state.plans)


def _replace_task(state: WorkGraphState, task: TaskState) -> tuple[TaskState, ...]:
    return tuple(task if item.task_id == task.task_id else item for item in state.tasks)


def _require_plan(state: WorkGraphState, plan_id: str) -> PlanState:
    plan = state.plan(plan_id)
    if plan is None:
        raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", f"Work Graph event references missing Plan: {plan_id}")
    return plan


def _actor(event: EventEnvelope) -> dict[str, str]:
    return {"type": event.initiator_type, "id": event.initiator_id}


def _revision_content(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "plan_id": payload.get("plan_id"),
        "revision_id": payload.get("revision_id"),
        "parent_revision_id": payload.get("parent_revision_id"),
        "content_schema_version": payload.get("content_schema_version"),
        "objective": payload.get("objective"),
        "constraints": payload.get("constraints"),
        "task_definitions": payload.get("task_definitions"),
        "dependencies": payload.get("dependencies"),
    }


def _reduce_revision(state: WorkGraphState, event: EventEnvelope, payload: Mapping[str, Any]) -> WorkGraphState:
    plan_id = str(payload.get("plan_id") or "")
    revision_id = str(payload.get("revision_id") or "")
    plan = _require_plan(state, plan_id)
    if plan.lifecycle_state != PlanLifecycleState.OPEN:
        raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Revision fact requires OPEN Plan")
    if not revision_id or revision_id != event.entity_id or state.revision(revision_id) is not None:
        raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Revision identity is invalid or already used")
    if payload.get("content_schema_version") != WORK_GRAPH_SCHEMA_VERSION:
        raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "unsupported Work Graph content schema")
    if payload.get("content_hash") != canonical_sha256(_revision_content(payload)):
        raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Revision content hash mismatch")
    parent_revision_id = payload.get("parent_revision_id")
    if parent_revision_id is not None:
        parent = state.revision(str(parent_revision_id))
        if parent is None or parent.plan_id != plan_id:
            raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Revision parent is invalid")
    raw_tasks = payload.get("task_definitions")
    raw_dependencies = payload.get("dependencies")
    raw_constraints = payload.get("constraints")
    if not isinstance(raw_tasks, list) or not isinstance(raw_dependencies, list) or not isinstance(raw_constraints, list):
        raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Revision collections must be arrays")
    task_ids: set[str] = set()
    task_keys: set[str] = set()
    tasks: list[TaskState] = []
    for raw in raw_tasks:
        if not isinstance(raw, Mapping):
            raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Task definition must be an object")
        task_id = str(raw.get("task_id") or "")
        task_key = str(raw.get("task_key") or "")
        intent = str(raw.get("intent") or "")
        criteria = raw.get("acceptance_criteria")
        if (
            not task_id
            or not task_key
            or not intent
            or not isinstance(criteria, list)
            or task_id in task_ids
            or task_key in task_keys
            or state.task(task_id) is not None
        ):
            raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Task definition invariant violated")
        task_ids.add(task_id)
        task_keys.add(task_key)
        tasks.append(
            TaskState(
                task_id=task_id,
                task_key=task_key,
                plan_id=plan_id,
                plan_revision_id=revision_id,
                intent=intent,
                acceptance_criteria=tuple(dict(item) for item in criteria),
                lifecycle_state=TaskLifecycleState.PENDING,
                outcome=None,
                created_seq=event.seq,
                updated_seq=event.seq,
            )
        )
    dependencies: list[TaskDependency] = []
    edges: set[tuple[str, str]] = set()
    adjacency = {task_id: [] for task_id in task_ids}
    for raw in raw_dependencies:
        if not isinstance(raw, Mapping):
            raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Task dependency must be an object")
        predecessor = str(raw.get("predecessor_task_id") or "")
        successor = str(raw.get("successor_task_id") or "")
        kind = str(raw.get("dependency_kind") or "")
        edge = (predecessor, successor)
        if (
            predecessor not in task_ids
            or successor not in task_ids
            or predecessor == successor
            or kind != "FINISH_TO_START"
            or edge in edges
        ):
            raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Task dependency invariant violated")
        edges.add(edge)
        adjacency[predecessor].append(successor)
        dependencies.append(TaskDependency(revision_id, predecessor, successor, kind))
    visiting: set[str] = set()
    visited: set[str] = set()

    def cyclic(task_id: str) -> bool:
        if task_id in visiting:
            return True
        if task_id in visited:
            return False
        visiting.add(task_id)
        if any(cyclic(successor) for successor in adjacency[task_id]):
            return True
        visiting.remove(task_id)
        visited.add(task_id)
        return False

    if any(cyclic(task_id) for task_id in task_ids):
        raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Task dependencies contain a cycle")
    revision = PlanRevisionState(
        revision_id=revision_id,
        plan_id=plan_id,
        parent_revision_id=str(parent_revision_id) if parent_revision_id is not None else None,
        content_schema_version=WORK_GRAPH_SCHEMA_VERSION,
        content_hash=str(payload["content_hash"]),
        objective=str(payload.get("objective") or ""),
        constraints=tuple(dict(item) for item in raw_constraints),
        task_definitions=tuple(dict(item) for item in raw_tasks),
        dependencies=tuple(dict(item) for item in raw_dependencies),
        declared_at=event.created_at,
        declared_by=_actor(event),
    )
    return replace(
        state,
        revisions=state.revisions + (revision,),
        tasks=state.tasks + tuple(tasks),
        dependencies=state.dependencies + tuple(dependencies),
    )


class WorkGraphReducerContribution:
    def reduce(
        self,
        state: WorkGraphState,
        event: EventEnvelope,
        core_state: RuntimeState,
    ) -> WorkGraphState:
        if event.event_type not in EVENT_TYPES:
            raise RuntimeError("EXTENSION_EVENT_NOT_OWNED", f"unsupported Work Graph event: {event.event_type}")
        if event.mission_id != state.mission_id or core_state.mission_id != state.mission_id:
            raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Work Graph Mission identity mismatch")
        if core_state.seq != event.seq:
            raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Work Graph event does not share Core seq")
        if core_state.mission is None or core_state.mission.status in {
            MissionStatus.COMPLETED,
            MissionStatus.FAILED,
            MissionStatus.CANCELLED,
        }:
            raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "terminal or missing Mission cannot accept Work Graph facts")
        payload = dict(event.payload)
        if event.event_type == "plan.created.v1":
            plan_id = str(payload.get("plan_id") or "")
            if not plan_id or plan_id != event.entity_id or state.plan(plan_id) is not None:
                raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Plan creation fact is invalid")
            return replace(
                state,
                plans=state.plans
                + (
                    PlanState(
                        plan_id=plan_id,
                        lifecycle_state=PlanLifecycleState.OPEN,
                        current_revision_id=None,
                        created_at=event.created_at,
                        created_by=_actor(event),
                    ),
                ),
            )
        if event.event_type == "plan.revision_recorded.v1":
            return _reduce_revision(state, event, payload)
        if event.event_type == "plan.revision_activated.v1":
            plan_id = str(payload.get("plan_id") or "")
            revision_id = str(payload.get("revision_id") or "")
            plan = _require_plan(state, plan_id)
            revision = state.revision(revision_id)
            if (
                plan.lifecycle_state != PlanLifecycleState.OPEN
                or revision is None
                or revision.plan_id != plan_id
                or plan.current_revision_id == revision_id
                or payload.get("previous_revision_id") != plan.current_revision_id
            ):
                raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Revision activation fact is invalid")
            return replace(state, plans=_replace_plan(state, replace(plan, current_revision_id=revision_id)))
        if event.event_type == "plan.lifecycle_changed.v1":
            plan_id = str(payload.get("plan_id") or "")
            plan = _require_plan(state, plan_id)
            try:
                source = PlanLifecycleState(str(payload.get("from_state")))
                target = PlanLifecycleState(str(payload.get("to_state")))
            except ValueError as exc:
                raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "invalid Plan lifecycle fact") from exc
            if source != plan.lifecycle_state or (source, target) not in {
                (PlanLifecycleState.OPEN, PlanLifecycleState.CLOSED),
                (PlanLifecycleState.CLOSED, PlanLifecycleState.ARCHIVED),
            }:
                raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Plan lifecycle fact violates transition rules")
            if target == PlanLifecycleState.CLOSED and any(
                task.lifecycle_state not in TASK_TERMINAL for task in state.tasks if task.plan_id == plan_id
            ):
                raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Plan closed with non-terminal Tasks")
            return replace(state, plans=_replace_plan(state, replace(plan, lifecycle_state=target)))
        if event.event_type in {"task.lifecycle_changed.v1", "task.outcome_recorded.v1"}:
            task_id = str(payload.get("task_id") or "")
            task = state.task(task_id)
            if task is None or task_id != event.entity_id:
                raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Task event references missing Task")
            if payload.get("plan_id") != task.plan_id or payload.get("plan_revision_id") != task.plan_revision_id:
                raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Task event identity mismatch")
            try:
                source = TaskLifecycleState(str(payload.get("from_state")))
                target = TaskLifecycleState(str(payload.get("to_state")))
            except ValueError as exc:
                raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "invalid Task lifecycle fact") from exc
            if source != task.lifecycle_state:
                raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Task event source state mismatch")
            outcome = payload.get("outcome")
            if event.event_type == "task.lifecycle_changed.v1":
                plan = _require_plan(state, task.plan_id)
                if (
                    source != TaskLifecycleState.PENDING
                    or target != TaskLifecycleState.ACTIVE
                    or outcome is not None
                    or plan.lifecycle_state != PlanLifecycleState.OPEN
                    or plan.current_revision_id != task.plan_revision_id
                ):
                    raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Task activation fact is invalid")
                normalized_outcome = None
            else:
                if target not in TASK_TERMINAL or not isinstance(outcome, Mapping):
                    raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Task outcome fact is invalid")
                if target in {TaskLifecycleState.SUCCEEDED, TaskLifecycleState.FAILED} and source != TaskLifecycleState.ACTIVE:
                    raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Task outcome transition is invalid")
                if target == TaskLifecycleState.CANCELLED and source not in {
                    TaskLifecycleState.PENDING,
                    TaskLifecycleState.ACTIVE,
                }:
                    raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Task cancellation fact is invalid")
                normalized_outcome = dict(outcome)
            changed = replace(
                task,
                lifecycle_state=target,
                outcome=normalized_outcome,
                updated_seq=event.seq,
            )
            return replace(state, tasks=_replace_task(state, changed))
        snapshot_id = str(payload.get("snapshot_id") or "")
        if not snapshot_id or snapshot_id != event.entity_id or state.snapshot(snapshot_id) is not None:
            raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Snapshot identity is invalid")
        state_payload = payload.get("state_payload")
        if not isinstance(state_payload, Mapping) or payload.get("payload_hash") != canonical_sha256(state_payload):
            raise RuntimeError("SNAPSHOT_CHECKSUM_MISMATCH", "Snapshot payload hash mismatch")
        if payload.get("work_graph_schema_version") != WORK_GRAPH_SCHEMA_VERSION:
            raise RuntimeError("SNAPSHOT_SCHEMA_UNSUPPORTED", "unsupported Snapshot schema")
        as_of_seq = payload.get("as_of_seq")
        if not isinstance(as_of_seq, int) or as_of_seq != event.seq - 1:
            raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Snapshot does not anchor the prior shared seq")
        scope = payload.get("scope")
        plan_id = payload.get("plan_id")
        if scope == "PLAN":
            _require_plan(state, str(plan_id or ""))
        elif scope != "MISSION" or plan_id is not None:
            raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Snapshot scope fact is invalid")
        if (
            state_payload.get("mission_id") != state.mission_id
            or state_payload.get("as_of_seq") != as_of_seq
            or state_payload.get("scope") != scope
            or state_payload.get("plan_id") != plan_id
        ):
            raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Snapshot payload anchor mismatch")
        prior_core_state = replace(core_state, seq=as_of_seq)
        expected_work_graph = state if scope == "MISSION" else state.plan_scope(str(plan_id))
        expected_payload = {
            "mission_id": state.mission_id,
            "as_of_seq": as_of_seq,
            "scope": scope,
            "plan_id": plan_id,
            "core_state": prior_core_state.to_dict(),
            "work_graph_state": expected_work_graph.to_dict(),
        }
        if dict(state_payload) != expected_payload:
            raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "Snapshot payload is not the exact prior state")
        snapshot = SnapshotIndex(
            snapshot_id=snapshot_id,
            scope=str(scope),
            plan_id=str(plan_id) if plan_id is not None else None,
            as_of_seq=as_of_seq,
            work_graph_schema_version=WORK_GRAPH_SCHEMA_VERSION,
            projection_version=int(payload.get("projection_version")),
            canonicalization_version=int(payload.get("canonicalization_version")),
            payload_hash=str(payload["payload_hash"]),
            state_payload=dict(state_payload),
            recorded_seq=event.seq,
        )
        return replace(state, snapshots=state.snapshots + (snapshot,))
