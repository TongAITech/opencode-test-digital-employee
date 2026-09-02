from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from aitest_runtime.durable_core import RuntimeError


EXTENSION_ID = "r1_2_work_graph"
WORK_GRAPH_SCHEMA_VERSION = 1
PROJECTION_VERSION = 1
CANONICALIZATION_VERSION = 1


class PlanLifecycleState(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    ARCHIVED = "ARCHIVED"


class TaskLifecycleState(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class TaskAvailability(str, Enum):
    READY = "READY"
    BLOCKED = "BLOCKED"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"


TASK_TERMINAL = {
    TaskLifecycleState.SUCCEEDED,
    TaskLifecycleState.FAILED,
    TaskLifecycleState.CANCELLED,
}


def require_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError("COMMAND_SCHEMA_INVALID", f"{name} must be a non-empty string")
    return value


@dataclass(frozen=True)
class PlanState:
    plan_id: str
    lifecycle_state: PlanLifecycleState
    current_revision_id: str | None
    created_at: str
    created_by: Mapping[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "lifecycle_state": self.lifecycle_state.value,
            "current_revision_id": self.current_revision_id,
            "created_at": self.created_at,
            "created_by": dict(self.created_by),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> PlanState:
        return cls(
            str(value["plan_id"]),
            PlanLifecycleState(str(value["lifecycle_state"])),
            value.get("current_revision_id"),
            str(value["created_at"]),
            dict(value.get("created_by") or {}),
        )


@dataclass(frozen=True)
class PlanRevisionState:
    revision_id: str
    plan_id: str
    parent_revision_id: str | None
    content_schema_version: int
    content_hash: str
    objective: str
    constraints: tuple[Mapping[str, Any], ...]
    task_definitions: tuple[Mapping[str, Any], ...]
    dependencies: tuple[Mapping[str, Any], ...]
    declared_at: str
    declared_by: Mapping[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "revision_id": self.revision_id,
            "plan_id": self.plan_id,
            "parent_revision_id": self.parent_revision_id,
            "content_schema_version": self.content_schema_version,
            "content_hash": self.content_hash,
            "objective": self.objective,
            "constraints": [dict(item) for item in self.constraints],
            "task_definitions": [dict(item) for item in self.task_definitions],
            "dependencies": [dict(item) for item in self.dependencies],
            "declared_at": self.declared_at,
            "declared_by": dict(self.declared_by),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> PlanRevisionState:
        return cls(
            revision_id=str(value["revision_id"]),
            plan_id=str(value["plan_id"]),
            parent_revision_id=value.get("parent_revision_id"),
            content_schema_version=int(value["content_schema_version"]),
            content_hash=str(value["content_hash"]),
            objective=str(value["objective"]),
            constraints=tuple(dict(item) for item in value.get("constraints") or ()),
            task_definitions=tuple(dict(item) for item in value.get("task_definitions") or ()),
            dependencies=tuple(dict(item) for item in value.get("dependencies") or ()),
            declared_at=str(value["declared_at"]),
            declared_by=dict(value.get("declared_by") or {}),
        )


@dataclass(frozen=True)
class TaskState:
    task_id: str
    task_key: str
    plan_id: str
    plan_revision_id: str
    intent: str
    acceptance_criteria: tuple[Mapping[str, str], ...]
    lifecycle_state: TaskLifecycleState
    outcome: Mapping[str, Any] | None
    created_seq: int
    updated_seq: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_key": self.task_key,
            "plan_id": self.plan_id,
            "plan_revision_id": self.plan_revision_id,
            "intent": self.intent,
            "acceptance_criteria": [dict(item) for item in self.acceptance_criteria],
            "lifecycle_state": self.lifecycle_state.value,
            "outcome": dict(self.outcome) if self.outcome is not None else None,
            "created_seq": self.created_seq,
            "updated_seq": self.updated_seq,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> TaskState:
        outcome = value.get("outcome")
        return cls(
            task_id=str(value["task_id"]),
            task_key=str(value["task_key"]),
            plan_id=str(value["plan_id"]),
            plan_revision_id=str(value["plan_revision_id"]),
            intent=str(value["intent"]),
            acceptance_criteria=tuple(dict(item) for item in value.get("acceptance_criteria") or ()),
            lifecycle_state=TaskLifecycleState(str(value["lifecycle_state"])),
            outcome=dict(outcome) if isinstance(outcome, Mapping) else None,
            created_seq=int(value["created_seq"]),
            updated_seq=int(value["updated_seq"]),
        )


@dataclass(frozen=True)
class TaskDependency:
    revision_id: str
    predecessor_task_id: str
    successor_task_id: str
    dependency_kind: str = "FINISH_TO_START"

    def to_dict(self) -> dict[str, str]:
        return {
            "revision_id": self.revision_id,
            "predecessor_task_id": self.predecessor_task_id,
            "successor_task_id": self.successor_task_id,
            "dependency_kind": self.dependency_kind,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> TaskDependency:
        return cls(
            revision_id=str(value["revision_id"]),
            predecessor_task_id=str(value["predecessor_task_id"]),
            successor_task_id=str(value["successor_task_id"]),
            dependency_kind=str(value["dependency_kind"]),
        )


@dataclass(frozen=True)
class SnapshotIndex:
    snapshot_id: str
    scope: str
    plan_id: str | None
    as_of_seq: int
    work_graph_schema_version: int
    projection_version: int
    canonicalization_version: int
    payload_hash: str
    state_payload: Mapping[str, Any]
    recorded_seq: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "scope": self.scope,
            "plan_id": self.plan_id,
            "as_of_seq": self.as_of_seq,
            "work_graph_schema_version": self.work_graph_schema_version,
            "projection_version": self.projection_version,
            "canonicalization_version": self.canonicalization_version,
            "payload_hash": self.payload_hash,
            "state_payload": dict(self.state_payload),
            "recorded_seq": self.recorded_seq,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SnapshotIndex:
        return cls(
            snapshot_id=str(value["snapshot_id"]),
            scope=str(value["scope"]),
            plan_id=value.get("plan_id"),
            as_of_seq=int(value["as_of_seq"]),
            work_graph_schema_version=int(value["work_graph_schema_version"]),
            projection_version=int(value["projection_version"]),
            canonicalization_version=int(value.get("canonicalization_version", 1)),
            payload_hash=str(value["payload_hash"]),
            state_payload=dict(value.get("state_payload") or {}),
            recorded_seq=int(value["recorded_seq"]),
        )


@dataclass(frozen=True)
class WorkGraphState:
    mission_id: str
    plans: tuple[PlanState, ...] = ()
    revisions: tuple[PlanRevisionState, ...] = ()
    tasks: tuple[TaskState, ...] = ()
    dependencies: tuple[TaskDependency, ...] = ()
    snapshots: tuple[SnapshotIndex, ...] = ()

    def plan(self, plan_id: str) -> PlanState | None:
        return next((item for item in self.plans if item.plan_id == plan_id), None)

    def revision(self, revision_id: str) -> PlanRevisionState | None:
        return next((item for item in self.revisions if item.revision_id == revision_id), None)

    def task(self, task_id: str) -> TaskState | None:
        return next((item for item in self.tasks if item.task_id == task_id), None)

    def snapshot(self, snapshot_id: str) -> SnapshotIndex | None:
        return next((item for item in self.snapshots if item.snapshot_id == snapshot_id), None)

    def revision_dependencies(self, revision_id: str) -> tuple[TaskDependency, ...]:
        return tuple(item for item in self.dependencies if item.revision_id == revision_id)

    def task_availability(self, task_id: str) -> TaskAvailability:
        task = self.task(task_id)
        if task is None:
            raise RuntimeError("TASK_NOT_FOUND", f"Task not found: {task_id}")
        if task.lifecycle_state != TaskLifecycleState.PENDING:
            return TaskAvailability.NOT_ELIGIBLE
        plan = self.plan(task.plan_id)
        if (
            plan is None
            or plan.lifecycle_state != PlanLifecycleState.OPEN
            or plan.current_revision_id != task.plan_revision_id
        ):
            return TaskAvailability.BLOCKED
        predecessors = [
            dependency.predecessor_task_id
            for dependency in self.dependencies
            if dependency.revision_id == task.plan_revision_id
            and dependency.successor_task_id == task.task_id
        ]
        if any(
            self.task(predecessor) is None
            or self.task(predecessor).lifecycle_state != TaskLifecycleState.SUCCEEDED
            for predecessor in predecessors
        ):
            return TaskAvailability.BLOCKED
        return TaskAvailability.READY

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "plans": {item.plan_id: item.to_dict() for item in sorted(self.plans, key=lambda item: item.plan_id)},
            "revisions": {
                item.revision_id: item.to_dict()
                for item in sorted(self.revisions, key=lambda item: item.revision_id)
            },
            "tasks": {item.task_id: item.to_dict() for item in sorted(self.tasks, key=lambda item: item.task_id)},
            "dependencies": [
                item.to_dict()
                for item in sorted(
                    self.dependencies,
                    key=lambda item: (item.revision_id, item.predecessor_task_id, item.successor_task_id),
                )
            ],
            "snapshots": {
                item.snapshot_id: item.to_dict()
                for item in sorted(self.snapshots, key=lambda item: item.snapshot_id)
            },
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> WorkGraphState:
        return cls(
            mission_id=str(value["mission_id"]),
            plans=tuple(PlanState.from_dict(item) for item in (value.get("plans") or {}).values()),
            revisions=tuple(
                PlanRevisionState.from_dict(item) for item in (value.get("revisions") or {}).values()
            ),
            tasks=tuple(TaskState.from_dict(item) for item in (value.get("tasks") or {}).values()),
            dependencies=tuple(TaskDependency.from_dict(item) for item in value.get("dependencies") or ()),
            snapshots=tuple(
                SnapshotIndex.from_dict(item) for item in (value.get("snapshots") or {}).values()
            ),
        )

    def plan_scope(self, plan_id: str) -> WorkGraphState:
        if self.plan(plan_id) is None:
            raise RuntimeError("PLAN_NOT_FOUND", f"Plan not found: {plan_id}")
        revision_ids = {item.revision_id for item in self.revisions if item.plan_id == plan_id}
        task_ids = {item.task_id for item in self.tasks if item.plan_id == plan_id}
        return WorkGraphState(
            mission_id=self.mission_id,
            plans=tuple(item for item in self.plans if item.plan_id == plan_id),
            revisions=tuple(item for item in self.revisions if item.plan_id == plan_id),
            tasks=tuple(item for item in self.tasks if item.plan_id == plan_id),
            dependencies=tuple(
                item
                for item in self.dependencies
                if item.revision_id in revision_ids
                and item.predecessor_task_id in task_ids
                and item.successor_task_id in task_ids
            ),
            snapshots=tuple(item for item in self.snapshots if item.plan_id == plan_id),
        )
