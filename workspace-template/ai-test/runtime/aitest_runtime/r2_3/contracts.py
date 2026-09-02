"""Frozen R2.3 Planner and Plan Revision contracts.

R2.3 derives a candidate Work Graph revision from a frozen Goal observation.
Only the R1.2 Work Graph commands can make that candidate durable; this
module intentionally contains no persistence or runtime-service code.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from aitest_runtime.durable_core import CommandResult, RuntimeError as DurableRuntimeError
from aitest_runtime.durable_core import canonical_sha256


CONTRACT_VERSION = "R2.3_PLANNER_V1"
R2_3_CONTRACT_VERSION = CONTRACT_VERSION
SCHEMA_VERSION = 1


class PlanOutcome(str, Enum):
    APPLIED = "APPLIED"
    DUPLICATE = "DUPLICATE"
    NO_CHANGE = "NO_CHANGE"
    BLOCKED = "BLOCKED"
    GOAL_REVISION_REQUIRED = "GOAL_REVISION_REQUIRED"
    STALE_CURSOR = "STALE_CURSOR"
    REJECTED = "REJECTED"


APPLIED = PlanOutcome.APPLIED.value
DUPLICATE = PlanOutcome.DUPLICATE.value
NO_CHANGE = PlanOutcome.NO_CHANGE.value
BLOCKED = PlanOutcome.BLOCKED.value
GOAL_REVISION_REQUIRED = PlanOutcome.GOAL_REVISION_REQUIRED.value
STALE_CURSOR = PlanOutcome.STALE_CURSOR.value
REJECTED = PlanOutcome.REJECTED.value


class PlannerError(DurableRuntimeError):
    """A fail-closed R2.3 contract or orchestration error."""


class IdempotencyConflict(PlannerError):
    def __init__(self, planner_request_id: str, message: str | None = None) -> None:
        super().__init__(
            "IDEMPOTENCY_CONFLICT",
            message or f"planner_request_id already exists with a different request digest: {planner_request_id}",
            {"planner_request_id": planner_request_id},
        )


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PlannerError("PLANNER_INPUT_INVALID", f"{name} must be a non-empty string")
    return value.strip()


def _int(value: Any, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise PlannerError("PLANNER_INPUT_INVALID", f"{name} must be an integer >= {minimum}")
    return value


def _plain_json(value: Any, name: str = "value") -> Any:
    if value is None or isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise PlannerError("PLANNER_INPUT_INVALID", f"{name} contains a non-finite number")
        return value
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key.strip():
                raise PlannerError("PLANNER_INPUT_INVALID", f"{name} contains a non-string object key")
            result[key] = _plain_json(item, f"{name}.{key}")
        return result
    if isinstance(value, (list, tuple)):
        return [_plain_json(item, f"{name}[{index}]") for index, item in enumerate(value)]
    raise PlannerError("PLANNER_INPUT_INVALID", f"{name} contains an unsupported value of type {type(value).__name__}")


def _sequence(value: Any, name: str) -> tuple[Mapping[str, Any], ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise PlannerError("PLANNER_INPUT_INVALID", f"{name} must be an array")
    result: list[Mapping[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise PlannerError("PLANNER_INPUT_INVALID", f"{name}[{index}] must be an object")
        result.append(_plain_json(dict(item), f"{name}[{index}]"))
    return tuple(result)


def _optional_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise PlannerError("PLANNER_INPUT_INVALID", f"{name} must be an object")
    return _plain_json(dict(value), name)


@dataclass(frozen=True, init=False)
class PlannerInput:
    """The immutable observation handed to the pure planner.

    ``from_mapping`` and the constructor accept a few descriptive aliases so
    callers can pass a serialized boundary object without creating a second
    contract.  The serialized form is always the canonical field set below.
    """

    mission_id: str
    active_goal_id: str
    goal_revision: int
    goal_definition_digest: str
    scope_digest: str
    planning_cursor: int
    planner_request_id: str
    request_digest: str
    goal_definition: Mapping[str, Any]
    objective: str
    constraints: tuple[Mapping[str, Any], ...]
    task_definitions: tuple[Mapping[str, Any], ...]
    dependencies: tuple[Mapping[str, Any], ...]
    actor: Mapping[str, str]
    operation: str
    goal_mutation_required: bool
    scope_mutation_required: bool
    blocked: bool
    blockers: tuple[Mapping[str, Any], ...]
    current_content_hash: str | None
    current_revision_id: str | None
    existing_plan_id: str | None
    no_change: bool

    def __init__(
        self,
        mission_id: Any = None,
        active_goal_id: Any = None,
        goal_revision: Any = None,
        goal_definition_digest: Any = None,
        scope_digest: Any = None,
        planning_cursor: Any = None,
        planner_request_id: Any = None,
        request_digest: Any = None,
        goal_definition: Any = None,
        objective: Any = None,
        constraints: Any = None,
        task_definitions: Any = None,
        dependencies: Any = None,
        actor: Any = None,
        operation: Any = "PLAN",
        goal_mutation_required: Any = False,
        scope_mutation_required: Any = False,
        blocked: Any = False,
        blockers: Any = None,
        current_content_hash: Any = None,
        current_revision_id: Any = None,
        existing_plan_id: Any = None,
        no_change: Any = False,
        **aliases: Any,
    ) -> None:
        candidate = aliases.pop("candidate", aliases.pop("plan", aliases.pop("proposal", None)))
        if isinstance(candidate, Mapping):
            if existing_plan_id is None:
                existing_plan_id = candidate.get("plan_id")
            if objective is None:
                objective = candidate.get("objective", candidate.get("statement"))
            if constraints is None:
                constraints = candidate.get("constraints")
            if task_definitions is None:
                task_definitions = candidate.get("task_definitions", candidate.get("tasks"))
            if dependencies is None:
                dependencies = candidate.get("dependencies")
        active_goal_id = active_goal_id if active_goal_id is not None else aliases.pop("goal_id", None)
        goal_revision = goal_revision if goal_revision is not None else aliases.pop("expected_goal_revision", None)
        goal_definition_digest = (
            goal_definition_digest
            if goal_definition_digest is not None
            else aliases.pop("definition_digest", aliases.pop("goal_digest", None))
        )
        planning_cursor = planning_cursor if planning_cursor is not None else aliases.pop(
            "expected_seq", aliases.pop("cursor", aliases.pop("cursor_seq", None))
        )
        planner_request_id = (
            planner_request_id
            if planner_request_id is not None
            else aliases.pop("request_id", aliases.pop("planning_request_id", None))
        )
        request_digest = request_digest if request_digest is not None else aliases.pop("digest", None)
        goal_definition = goal_definition if goal_definition is not None else aliases.pop("goal", aliases.pop("definition", None))
        if task_definitions is None:
            task_definitions = aliases.pop("tasks", aliases.pop("steps", None))
        if dependencies is None:
            dependencies = aliases.pop("dependency_definitions", None)
        goal_mutation_required = aliases.pop("requires_goal_revision", goal_mutation_required)
        scope_mutation_required = aliases.pop("scope_changed", scope_mutation_required)
        blocked = aliases.pop("is_blocked", blocked)
        if current_content_hash is None:
            current_content_hash = aliases.pop("existing_content_hash", aliases.pop("current_plan_content_hash", None))
        if current_revision_id is None:
            current_revision_id = aliases.pop(
                "parent_revision_id",
                aliases.pop("existing_revision_id", aliases.pop("current_plan_revision_id", None)),
            )
        if existing_plan_id is None:
            existing_plan_id = aliases.pop("plan_id", aliases.pop("current_plan_id", None))
        no_change = aliases.pop("unchanged", no_change)
        status = aliases.pop("status", None)
        if status is not None:
            operation = status
        if current_content_hash is None:
            current_revision = aliases.pop("current_revision", None)
            if isinstance(current_revision, Mapping):
                current_content_hash = current_revision.get("content_hash")
                if current_revision_id is None:
                    current_revision_id = current_revision.get("revision_id")
        if aliases:
            raise PlannerError("PLANNER_INPUT_INVALID", f"unsupported PlannerInput fields: {sorted(aliases)}")

        goal_definition_map = _optional_mapping(goal_definition, "goal_definition")
        scope_digest = scope_digest if scope_digest is not None else goal_definition_map.get("scope_digest")
        if scope_digest is None:
            scope_digest = canonical_sha256(goal_definition_map.get("execution_scope", goal_definition_map.get("scope", {})))
        goal_definition_digest = goal_definition_digest or canonical_sha256(goal_definition_map)
        objective = objective or _goal_objective(goal_definition_map)
        constraints = constraints if constraints is not None else goal_definition_map.get("constraints", [])
        task_definitions = task_definitions if task_definitions is not None else goal_definition_map.get("task_definitions", goal_definition_map.get("tasks", []))
        dependencies = dependencies if dependencies is not None else goal_definition_map.get("dependencies", [])
        actor = actor or {"type": "SYSTEM", "id": "r2.3-planner"}
        actor_map = _optional_mapping(actor, "actor")
        actor_map = {"type": _text(actor_map.get("type"), "actor.type"), "id": _text(actor_map.get("id"), "actor.id")}

        normalized = {
            "schema_version": SCHEMA_VERSION,
            "mission_id": _text(mission_id, "mission_id"),
            "active_goal_id": _text(active_goal_id, "active_goal_id"),
            "goal_revision": _int(goal_revision, "goal_revision", minimum=1),
            "goal_definition_digest": _text(goal_definition_digest, "goal_definition_digest"),
            "scope_digest": _text(scope_digest, "scope_digest"),
            "planning_cursor": _int(planning_cursor, "planning_cursor", minimum=0),
            "planner_request_id": _text(planner_request_id, "planner_request_id"),
            "goal_definition": goal_definition_map,
            "objective": _text(objective, "objective"),
            "constraints": _sequence(constraints, "constraints"),
            "task_definitions": _sequence(task_definitions, "task_definitions"),
            "dependencies": _sequence(dependencies, "dependencies"),
            "actor": actor_map,
            "operation": _text(operation, "operation").upper(),
            "goal_mutation_required": bool(goal_mutation_required),
            "scope_mutation_required": bool(scope_mutation_required),
            "blocked": bool(blocked),
            "blockers": _sequence(blockers, "blockers"),
            "current_content_hash": None if current_content_hash is None else _text(current_content_hash, "current_content_hash"),
            "current_revision_id": None if current_revision_id is None else _text(current_revision_id, "current_revision_id"),
            "existing_plan_id": None if existing_plan_id is None else _text(existing_plan_id, "existing_plan_id"),
            "no_change": bool(no_change),
        }
        if request_digest is None or not str(request_digest).strip():
            request_digest = canonical_sha256(
                {
                    key: value
                    for key, value in normalized.items()
                    if key not in {"current_content_hash"}
                }
            )
        normalized["request_digest"] = _text(request_digest, "request_digest")
        for key, value in normalized.items():
            object.__setattr__(self, key, value)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | "PlannerInput") -> "PlannerInput":
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise PlannerError("PLANNER_INPUT_INVALID", "PlannerInput must be an object")
        return cls(**dict(value))

    def to_mapping(self, *, include_digest: bool = True) -> dict[str, Any]:
        result = {
            "schema_version": SCHEMA_VERSION,
            "mission_id": self.mission_id,
            "active_goal_id": self.active_goal_id,
            "goal_revision": self.goal_revision,
            "goal_definition_digest": self.goal_definition_digest,
            "scope_digest": self.scope_digest,
            "planning_cursor": self.planning_cursor,
            "planner_request_id": self.planner_request_id,
            "goal_definition": dict(self.goal_definition),
            "objective": self.objective,
            "constraints": [dict(item) for item in self.constraints],
            "task_definitions": [dict(item) for item in self.task_definitions],
            "dependencies": [dict(item) for item in self.dependencies],
            "actor": dict(self.actor),
            "operation": self.operation,
            "goal_mutation_required": self.goal_mutation_required,
            "scope_mutation_required": self.scope_mutation_required,
            "blocked": self.blocked,
            "blockers": [dict(item) for item in self.blockers],
            "current_content_hash": self.current_content_hash,
            "current_revision_id": self.current_revision_id,
            "existing_plan_id": self.existing_plan_id,
            "no_change": self.no_change,
        }
        if include_digest:
            result["request_digest"] = self.request_digest
        return result


def _goal_objective(goal_definition: Mapping[str, Any]) -> str:
    goal = goal_definition.get("goal")
    if isinstance(goal, Mapping):
        for key in ("objective", "statement", "intent", "title"):
            if goal.get(key):
                return str(goal[key])
    for key in ("objective", "statement", "intent", "title"):
        if goal_definition.get(key):
            return str(goal_definition[key])
    return "Execute the active Goal"


@dataclass(frozen=True)
class PlanDecision:
    outcome: str
    mission_id: str
    active_goal_id: str
    planner_request_id: str
    request_digest: str
    plan_id: str | None = None
    revision_id: str | None = None
    parent_revision_id: str | None = None
    objective: str | None = None
    constraints: tuple[Mapping[str, Any], ...] = ()
    task_definitions: tuple[Mapping[str, Any], ...] = ()
    dependencies: tuple[Mapping[str, Any], ...] = ()
    content_hash: str | None = None
    reason_code: str | None = None
    reason: str | None = None
    input: PlannerInput | None = field(default=None, repr=False, compare=False)

    @property
    def status(self) -> str:
        return self.outcome

    @property
    def applied(self) -> bool:
        return self.outcome in {APPLIED, DUPLICATE}

    @property
    def candidate(self) -> dict[str, Any] | None:
        if self.plan_id is None or self.revision_id is None:
            return None
        return {
            "plan_id": self.plan_id,
            "revision_id": self.revision_id,
            "parent_revision_id": self.parent_revision_id,
            "content_schema_version": 1,
            "objective": self.objective or "",
            "constraints": [dict(item) for item in self.constraints],
            "task_definitions": [dict(item) for item in self.task_definitions],
            "dependencies": [dict(item) for item in self.dependencies],
            "content_hash": self.content_hash,
        }

    @property
    def tasks(self) -> tuple[Mapping[str, Any], ...]:
        return self.task_definitions

    @property
    def plan_revision_id(self) -> str | None:
        return self.revision_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "status": self.outcome,
            "mission_id": self.mission_id,
            "active_goal_id": self.active_goal_id,
            "planner_request_id": self.planner_request_id,
            "request_digest": self.request_digest,
            "plan_id": self.plan_id,
            "revision_id": self.revision_id,
            "parent_revision_id": self.parent_revision_id,
            "objective": self.objective,
            "constraints": [dict(item) for item in self.constraints],
            "task_definitions": [dict(item) for item in self.task_definitions],
            "dependencies": [dict(item) for item in self.dependencies],
            "content_hash": self.content_hash,
            "reason_code": self.reason_code,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class PlanResult:
    outcome: str
    mission_id: str
    active_goal_id: str
    planner_request_id: str
    request_digest: str
    plan_id: str | None = None
    revision_id: str | None = None
    parent_revision_id: str | None = None
    content_hash: str | None = None
    command_results: tuple[CommandResult, ...] = ()
    reason_code: str | None = None
    reason: str | None = None
    decision: PlanDecision | None = field(default=None, repr=False, compare=False)
    replayed: bool = False

    @property
    def status(self) -> str:
        return self.outcome

    @property
    def error_code(self) -> str | None:
        return self.reason_code or (self.command_results[-1].error_code if self.command_results else None)

    @property
    def command_ids(self) -> tuple[str, ...]:
        return tuple(item.command_id for item in self.command_results)

    @property
    def plan_revision_id(self) -> str | None:
        return self.revision_id

    @property
    def ok(self) -> bool:
        return self.outcome in {APPLIED, DUPLICATE}

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "status": self.outcome,
            "mission_id": self.mission_id,
            "active_goal_id": self.active_goal_id,
            "planner_request_id": self.planner_request_id,
            "request_digest": self.request_digest,
            "plan_id": self.plan_id,
            "revision_id": self.revision_id,
            "parent_revision_id": self.parent_revision_id,
            "content_hash": self.content_hash,
            "command_results": [item.to_dict() for item in self.command_results],
            "command_ids": list(self.command_ids),
            "reason_code": self.reason_code,
            "reason": self.reason,
            "replayed": self.replayed,
        }


__all__ = [
    "APPLIED",
    "BLOCKED",
    "CONTRACT_VERSION",
    "DUPLICATE",
    "GOAL_REVISION_REQUIRED",
    "IdempotencyConflict",
    "NO_CHANGE",
    "PlanDecision",
    "PlanOutcome",
    "PlanResult",
    "PlannerError",
    "PlannerInput",
    "R2_3_CONTRACT_VERSION",
    "REJECTED",
    "SCHEMA_VERSION",
    "STALE_CURSOR",
]
