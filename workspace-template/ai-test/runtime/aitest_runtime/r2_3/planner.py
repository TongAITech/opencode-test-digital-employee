"""Pure R2.3 plan derivation.

The functions in this module only normalize an immutable PlannerInput and
construct the exact content accepted by the R1.2 Work Graph extension.  They
do not inspect runtime state, persist anything, or execute capabilities.
"""

from __future__ import annotations

from typing import Any, Mapping

from aitest_runtime.durable_core import canonical_sha256

from .contracts import (
    APPLIED,
    BLOCKED,
    GOAL_REVISION_REQUIRED,
    NO_CHANGE,
    REJECTED,
    PlanDecision,
    PlannerError,
    PlannerInput,
)


WORK_GRAPH_SCHEMA_VERSION = 1
DEPENDENCY_KIND = "FINISH_TO_START"


def _base_decision(value: Any, outcome: str, *, reason_code: str | None = None, reason: str | None = None) -> PlanDecision:
    if isinstance(value, PlannerInput):
        item = value
    elif isinstance(value, Mapping):
        raw = dict(value)
        item = None
        mission_id = str(raw.get("mission_id", ""))
        active_goal_id = str(raw.get("active_goal_id", raw.get("goal_id", "")))
        planner_request_id = str(raw.get("planner_request_id", raw.get("request_id", "")))
        request_digest = str(raw.get("request_digest", raw.get("digest", "")))
        return PlanDecision(
            outcome,
            mission_id,
            active_goal_id,
            planner_request_id,
            request_digest,
            reason_code=reason_code,
            reason=reason,
        )
    else:
        item = None
    if item is None:
        return PlanDecision(outcome, "", "", "", "", reason_code=reason_code, reason=reason)
    return PlanDecision(
        outcome,
        item.mission_id,
        item.active_goal_id,
        item.planner_request_id,
        item.request_digest,
        reason_code=reason_code,
        reason=reason,
        input=item,
    )


def _task_text(raw: Mapping[str, Any], keys: tuple[str, ...], default: str, name: str) -> str:
    for key in keys:
        value = raw.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    if default.strip():
        return default.strip()
    raise PlannerError("PLANNER_CANDIDATE_INVALID", f"{name} must be a non-empty string")


def _normalize_criteria(raw: Mapping[str, Any], task_key: str, intent: str) -> list[dict[str, str]]:
    criteria = raw.get("acceptance_criteria", raw.get("acceptance", raw.get("criteria", [])))
    if criteria is None:
        criteria = []
    if not isinstance(criteria, (list, tuple)):
        raise PlannerError("PLANNER_CANDIDATE_INVALID", f"acceptance_criteria for {task_key} must be an array")
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, item in enumerate(criteria):
        if not isinstance(item, Mapping):
            raise PlannerError("PLANNER_CANDIDATE_INVALID", f"acceptance_criteria[{index}] must be an object")
        criterion_id = _task_text(
            item,
            ("criterion_id", "id", "key"),
            f"{task_key}:criterion:{index + 1}",
            "criterion_id",
        )
        description = _task_text(
            item,
            ("description", "statement", "expected", "value"),
            intent,
            "criterion description",
        )
        if criterion_id in seen:
            raise PlannerError("PLANNER_CANDIDATE_INVALID", f"duplicate criterion_id: {criterion_id}")
        seen.add(criterion_id)
        result.append({"criterion_id": criterion_id, "description": description})
    return result


def _normalize_tasks(item: PlannerInput, revision_id: str) -> tuple[list[dict[str, Any]], dict[str, str]]:
    result: list[dict[str, Any]] = []
    references: dict[str, str] = {}
    keys: set[str] = set()
    for index, raw in enumerate(item.task_definitions):
        task_key = _task_text(
            raw,
            ("task_key", "key", "semantic_key", "name"),
            f"task-{index + 1}",
            "task_key",
        )
        if task_key in keys:
            raise PlannerError("TASK_KEY_CONFLICT", f"semantic task_key repeated: {task_key}")
        keys.add(task_key)
        intent = _task_text(
            raw,
            ("intent", "description", "statement", "action"),
            task_key,
            "intent",
        )
        task_id = f"r2.3:{revision_id}:TASK:{index + 1}:{task_key}"
        task = {
            "task_id": task_id,
            "task_key": task_key,
            "intent": intent,
            "acceptance_criteria": _normalize_criteria(raw, task_key, intent),
        }
        result.append(task)
        references[task_key] = task_id
        references[str(raw.get("task_id"))] = task_id if raw.get("task_id") is not None else task_id
        references[str(index + 1)] = task_id
    return result, references


def _normalize_dependencies(
    raw_dependencies: tuple[Mapping[str, Any], ...],
    references: Mapping[str, str],
) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    edges: set[tuple[str, str]] = set()
    adjacency: dict[str, list[str]] = {}
    for item in raw_dependencies:
        predecessor_raw = item.get("predecessor_task_id", item.get("predecessor", item.get("from")))
        successor_raw = item.get("successor_task_id", item.get("successor", item.get("to")))
        predecessor = references.get(str(predecessor_raw), str(predecessor_raw))
        successor = references.get(str(successor_raw), str(successor_raw))
        if not predecessor or not successor or predecessor not in references.values() or successor not in references.values():
            raise PlannerError("DEPENDENCY_TARGET_NOT_FOUND", "dependency must target Tasks in this revision")
        kind = str(item.get("dependency_kind", item.get("kind", DEPENDENCY_KIND)))
        if kind != DEPENDENCY_KIND:
            raise PlannerError("UNSUPPORTED_DEPENDENCY_KIND", f"unsupported dependency kind: {kind}")
        if predecessor == successor:
            raise PlannerError("DEPENDENCY_SELF_REFERENCE", f"Task cannot depend on itself: {predecessor}")
        edge = (predecessor, successor)
        if edge in edges:
            raise PlannerError("COMMAND_SCHEMA_INVALID", "duplicate Task dependency")
        edges.add(edge)
        adjacency.setdefault(predecessor, []).append(successor)
        result.append(
            {
                "predecessor_task_id": predecessor,
                "successor_task_id": successor,
                "dependency_kind": DEPENDENCY_KIND,
            }
        )

    visiting: set[str] = set()
    visited: set[str] = set()

    def cyclic(task_id: str) -> bool:
        if task_id in visiting:
            return True
        if task_id in visited:
            return False
        visiting.add(task_id)
        if any(cyclic(successor) for successor in adjacency.get(task_id, [])):
            return True
        visiting.remove(task_id)
        visited.add(task_id)
        return False

    if any(cyclic(task_id) for task_id in references.values()):
        raise PlannerError("DEPENDENCY_CYCLE", "Task dependencies must be acyclic")
    return result


def _normalize_constraints(value: tuple[Mapping[str, Any], ...]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        kind = item.get("kind")
        if not isinstance(kind, str) or not kind.strip() or "value" not in item:
            raise PlannerError("PLANNER_CANDIDATE_INVALID", f"constraints[{index}] requires kind and value")
        result.append({"kind": kind.strip(), "value": item["value"]})
    return result


def derive_plan(value: Mapping[str, Any] | PlannerInput) -> PlanDecision:
    """Derive a deterministic PlanDecision without touching durable runtime state."""
    try:
        item = PlannerInput.from_mapping(value)
        if item.goal_mutation_required or item.scope_mutation_required or item.operation in {
            "GOAL_REVISION_REQUIRED",
            "SCOPE_CHANGE",
        }:
            return _base_decision(
                item,
                GOAL_REVISION_REQUIRED,
                reason_code="GOAL_REVISION_REQUIRED",
                reason="Goal or execution scope mutation is outside the Planner boundary",
            )
        if item.blocked or item.blockers or item.operation in {"BLOCKED", "WAIT"}:
            return _base_decision(
                item,
                BLOCKED,
                reason_code="PLANNING_BLOCKED",
                reason="Planner input contains an unresolved planning blocker",
            )

        plan_id = item.existing_plan_id or f"r2.3:{item.mission_id}:{item.active_goal_id}:PLAN"
        revision_id = f"r2.3:{item.planner_request_id}:REVISION"
        parent_revision_id = item.current_revision_id
        tasks, references = _normalize_tasks(item, revision_id)
        dependencies = _normalize_dependencies(item.dependencies, references)
        constraints = _normalize_constraints(item.constraints)
        objective = item.objective
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
        content_hash = canonical_sha256(content)
        if item.no_change or item.operation in {"NO_CHANGE", "UNCHANGED"} or (
            item.current_content_hash is not None
            and item.current_content_hash == content_hash
            and item.current_revision_id != revision_id
        ):
            return PlanDecision(
                NO_CHANGE,
                item.mission_id,
                item.active_goal_id,
                item.planner_request_id,
                item.request_digest,
                plan_id=plan_id,
                revision_id=revision_id,
                parent_revision_id=parent_revision_id,
                objective=objective,
                constraints=tuple(constraints),
                task_definitions=tuple(tasks),
                dependencies=tuple(dependencies),
                content_hash=content_hash,
                reason_code="PLAN_UNCHANGED",
                reason="Candidate content matches the current revision",
                input=item,
            )
        return PlanDecision(
            APPLIED,
            item.mission_id,
            item.active_goal_id,
            item.planner_request_id,
            item.request_digest,
            plan_id=plan_id,
            revision_id=revision_id,
            parent_revision_id=parent_revision_id,
            objective=objective,
            constraints=tuple(constraints),
            task_definitions=tuple(tasks),
            dependencies=tuple(dependencies),
            content_hash=content_hash,
            input=item,
        )
    except PlannerError as exc:
        return _base_decision(value, REJECTED, reason_code=exc.code, reason=exc.message)
    except (TypeError, ValueError, KeyError) as exc:
        return _base_decision(value, REJECTED, reason_code="PLANNER_INPUT_INVALID", reason=str(exc))


__all__ = ["DEPENDENCY_KIND", "WORK_GRAPH_SCHEMA_VERSION", "derive_plan"]
