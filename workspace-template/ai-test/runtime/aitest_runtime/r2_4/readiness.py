"""Pure R2.4 readiness and deterministic scheduling decisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Mapping

from aitest_runtime.work_graph import (
    PlanLifecycleState,
    TaskAvailability,
    TaskLifecycleState,
    WorkGraphState,
)
from aitest_runtime.work_graph.contracts import TASK_TERMINAL

from .contracts import (
    ACTIVE,
    BLOCKED,
    PLAN_COMPLETE,
    READY,
    WAIT,
    DispatchBinding,
    LoopBudget,
    LoopProgress,
    R2_4Error,
    SchedulingPolicy,
    TaskReadiness,
)


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise R2_4Error("R2_4_SCHEMA_INVALID", f"{name} must be an object")
    return value


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise R2_4Error("R2_4_SCHEMA_INVALID", f"{name} must be a non-empty string")
    return value.strip()


def _iso_expired(value: str | None, observed_at: str) -> bool:
    if value is None:
        return False
    try:
        left = datetime.fromisoformat(value.replace("Z", "+00:00"))
        right = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        return right >= left
    except ValueError:
        raise R2_4Error("R2_4_SCHEMA_INVALID", "validity timestamps must be ISO-8601")


def _status(value: Any) -> str:
    return value.value if isinstance(value, Enum) else str(value or "").upper()


def _resolution_capabilities(resolution: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = resolution.get("capabilities", resolution.get("capability_declarations", ()))
    if not isinstance(raw, (list, tuple)):
        raise R2_4Error("R2_4_RESOLUTION_INVALID", "resolution.capabilities must be an array")
    return [item for item in raw if isinstance(item, Mapping)]


def _matching_bindings(
    bindings: tuple[DispatchBinding, ...],
    *,
    mission_id: str,
    plan_id: str,
    revision_id: str,
    task_id: str,
) -> tuple[list[DispatchBinding], str | None]:
    candidates = [
        item
        for item in bindings
        if item.mission_id == mission_id
        and item.plan_id == plan_id
        and item.plan_revision_id == revision_id
        and item.task_id == task_id
    ]
    if not candidates:
        return [], "DISPATCH_BINDING_MISSING"
    identities = {
        (
            item.capability_id,
            item.capability_version,
            item.resolution_id,
            item.snapshot_id,
            item.binding_digest,
        )
        for item in candidates
    }
    if len(identities) != 1:
        return [], "DISPATCH_BINDING_CONFLICT"
    return candidates, None


def _binding_gate(
    binding: DispatchBinding,
    resolution: Mapping[str, Any],
    observed_at: str,
) -> tuple[str, str | None, str | None]:
    resolution_id = str(resolution.get("resolution_id") or "")
    if not resolution_id or binding.resolution_id != resolution_id:
        return BLOCKED, "RESOLUTION_MISMATCH", "Dispatch binding does not match the observed R2.1 resolution"
    snapshot_id = resolution.get("snapshot_id")
    if snapshot_id is not None and str(snapshot_id) != binding.snapshot_id:
        return BLOCKED, "RESOLUTION_SNAPSHOT_MISMATCH", "Dispatch binding does not match the resolution snapshot"
    if _iso_expired(binding.valid_until, observed_at):
        return BLOCKED, "DISPATCH_BINDING_EXPIRED", "Dispatch binding is no longer valid"
    if _iso_expired(resolution.get("valid_until"), observed_at):
        return BLOCKED, "RESOLUTION_EXPIRED", "R2.1 resolution is no longer valid"

    resolution_status = _status(resolution.get("status"))
    if resolution_status == "UNAVAILABLE":
        return WAIT, "CAPABILITY_UNAVAILABLE", "R2.1 capability resolution is temporarily unavailable"
    if resolution_status != "RESOLVED":
        return BLOCKED, "RESOLUTION_NOT_RESOLVED", "R2.1 resolution is not RESOLVED"

    source_refs = resolution.get("source_refs")
    if source_refs is not None and (not isinstance(source_refs, (list, tuple)) or not source_refs):
        return BLOCKED, "RESOLUTION_PROVENANCE_MISSING", "R2.1 resolution has no trusted source reference"
    fact_digest = resolution.get("fact_set_digest")
    if fact_digest is not None and (
        not isinstance(fact_digest, str)
        or len(fact_digest) != 64
        or any(character not in "0123456789abcdef" for character in fact_digest.lower())
    ):
        return BLOCKED, "RESOLUTION_DIGEST_INVALID", "R2.1 resolution digest is invalid"

    matches = [
        item
        for item in _resolution_capabilities(resolution)
        if str(item.get("capability_id", item.get("id", ""))) == binding.capability_id
        and str(item.get("version", item.get("capability_version", ""))) == binding.capability_version
    ]
    if not matches:
        return BLOCKED, "CAPABILITY_BINDING_MISMATCH", "No exact R2.1 capability matches the DispatchBinding"
    if len(matches) != 1:
        return BLOCKED, "CAPABILITY_RESOLUTION_CONFLICT", "R2.1 contains conflicting capability entries"
    capability = matches[0]
    capability_status = _status(capability.get("status"))
    if capability_status == "UNAVAILABLE":
        return WAIT, "CAPABILITY_UNAVAILABLE", "The bound capability is unavailable"
    if capability_status != "AVAILABLE":
        return BLOCKED, "CAPABILITY_NOT_AVAILABLE", "The bound capability is not AVAILABLE"
    capability_refs = capability.get("source_refs")
    if capability_refs is not None and (not isinstance(capability_refs, (list, tuple)) or not capability_refs):
        return BLOCKED, "CAPABILITY_PROVENANCE_MISSING", "The bound capability has no trusted source reference"
    return READY, None, None


def _dependency_gate(state: WorkGraphState, task: Any) -> tuple[str, str | None, str | None]:
    predecessors = [
        dependency.predecessor_task_id
        for dependency in state.dependencies
        if dependency.revision_id == task.plan_revision_id and dependency.successor_task_id == task.task_id
    ]
    for predecessor_id in predecessors:
        predecessor = state.task(predecessor_id)
        if predecessor is None:
            return BLOCKED, "DEPENDENCY_TARGET_MISSING", "A dependency target is missing from the current revision"
        if predecessor.lifecycle_state not in TASK_TERMINAL:
            return WAIT, "DEPENDENCY_NOT_COMPLETE", "An ordinary dependency has not completed"
        if predecessor.lifecycle_state != TaskLifecycleState.SUCCEEDED:
            return BLOCKED, "DEPENDENCY_FAILED", "A dependency did not succeed"
    return READY, None, None


@dataclass(frozen=True)
class ReadinessReport:
    mission_id: str
    plan_id: str | None
    plan_revision_id: str | None
    observed_seq: int
    tasks: tuple[TaskReadiness, ...]
    ready_tasks: tuple[TaskReadiness, ...]
    next_state: str
    reason_code: str | None = None
    reason: str | None = None

    @property
    def plan_complete(self) -> bool:
        return self.next_state == PLAN_COMPLETE

    @property
    def blockers(self) -> tuple[TaskReadiness, ...]:
        return tuple(item for item in self.tasks if item.status == BLOCKED)

    @property
    def ready_task_ids(self) -> tuple[str, ...]:
        return tuple(item.task_id for item in self.ready_tasks)

    @property
    def waits(self) -> tuple[TaskReadiness, ...]:
        return tuple(item for item in self.tasks if item.status == WAIT)

    @property
    def active_tasks(self) -> tuple[TaskReadiness, ...]:
        return tuple(item for item in self.tasks if item.status == ACTIVE)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "plan_id": self.plan_id,
            "plan_revision_id": self.plan_revision_id,
            "observed_seq": self.observed_seq,
            "tasks": [item.to_dict() for item in self.tasks],
            "ready_tasks": [item.to_dict() for item in self.ready_tasks],
            "next_state": self.next_state,
            "reason_code": self.reason_code,
            "reason": self.reason,
        }


def _request_parts(value: Any, **overrides: Any) -> tuple[str, str, str, int, Mapping[str, Any], tuple[DispatchBinding, ...], str]:
    if isinstance(value, WorkGraphState):
        raw: Mapping[str, Any] = overrides
        state = value
    else:
        raw = value if isinstance(value, Mapping) else getattr(value, "__dict__", {})
        state = overrides.get("work_graph") or raw.get("work_graph") or raw.get("state")
    if not isinstance(state, WorkGraphState):
        raise R2_4Error("R2_4_INPUT_INVALID", "R2.4 readiness requires the R1.2 WorkGraphState")
    mission_id = _text(overrides.get("mission_id", raw.get("mission_id", state.mission_id)), "mission_id")
    plan_id = _text(overrides.get("plan_id", raw.get("plan_id")), "plan_id")
    revision_id = _text(
        overrides.get("plan_revision_id", raw.get("plan_revision_id", raw.get("plan_revision"))),
        "plan_revision_id",
    )
    observed_seq = overrides.get("observed_seq", raw.get("observed_seq", raw.get("as_of_seq")))
    if isinstance(observed_seq, bool) or not isinstance(observed_seq, int) or observed_seq < 0:
        raise R2_4Error("R2_4_INPUT_INVALID", "observed_seq must be a non-negative integer")
    resolution = overrides.get("resolution", raw.get("resolution"))
    if not isinstance(resolution, Mapping):
        raise R2_4Error("R2_4_INPUT_INVALID", "R2.4 readiness requires the R2.1 resolution")
    raw_bindings = overrides.get("dispatch_bindings", raw.get("dispatch_bindings", raw.get("bindings", ())))
    if not isinstance(raw_bindings, (list, tuple)):
        raise R2_4Error("R2_4_INPUT_INVALID", "dispatch_bindings must be an array")
    bindings = tuple(item if isinstance(item, DispatchBinding) else DispatchBinding.from_mapping(item) for item in raw_bindings)
    observed_at = _text(overrides.get("observed_at", raw.get("observed_at")), "observed_at")
    return mission_id, plan_id, revision_id, observed_seq, resolution, bindings, observed_at


def evaluate_readiness(value: Any, **overrides: Any) -> ReadinessReport:
    """Evaluate readiness using only the R1.2 Work Graph READY predicate."""
    mission_id, plan_id, revision_id, observed_seq, resolution, bindings, observed_at = _request_parts(value, **overrides)
    state = value if isinstance(value, WorkGraphState) else overrides.get("work_graph") or (
        value.get("work_graph", value.get("state")) if isinstance(value, Mapping) else getattr(value, "work_graph", None)
    )
    plan = state.plan(plan_id)
    if plan is None:
        return ReadinessReport(mission_id, plan_id, revision_id, observed_seq, (), (), BLOCKED, "PLAN_NOT_FOUND", "Plan not found")
    if plan.lifecycle_state != PlanLifecycleState.OPEN:
        return ReadinessReport(mission_id, plan_id, revision_id, observed_seq, (), (), BLOCKED, "PLAN_NOT_OPEN", "Plan is not OPEN")
    if plan.current_revision_id is None:
        return ReadinessReport(mission_id, plan_id, revision_id, observed_seq, (), (), BLOCKED, "CURRENT_REVISION_MISSING", "Plan has no current Revision")
    if plan.current_revision_id != revision_id:
        return ReadinessReport(mission_id, plan_id, revision_id, observed_seq, (), (), BLOCKED, "CURRENT_REVISION_MISMATCH", "Input Revision is not current")
    revision = state.revision(revision_id)
    if revision is None:
        return ReadinessReport(mission_id, plan_id, revision_id, observed_seq, (), (), BLOCKED, "REVISION_NOT_FOUND", "Current Revision not found")

    revision_tasks = [item for item in state.tasks if item.plan_id == plan_id and item.plan_revision_id == revision_id]
    revision_tasks.sort(key=lambda item: (item.created_seq, item.task_id))
    if revision_tasks and all(item.lifecycle_state in TASK_TERMINAL for item in revision_tasks):
        return ReadinessReport(mission_id, plan_id, revision_id, observed_seq, (), (), PLAN_COMPLETE)
    if not revision_tasks:
        return ReadinessReport(mission_id, plan_id, revision_id, observed_seq, (), (), BLOCKED, "REVISION_HAS_NO_TASKS", "Current Revision has no Tasks")

    results: list[TaskReadiness] = []
    for task in revision_tasks:
        if task.lifecycle_state == TaskLifecycleState.ACTIVE:
            candidates, binding_error = _matching_bindings(
                bindings,
                mission_id=mission_id,
                plan_id=plan_id,
                revision_id=revision_id,
                task_id=task.task_id,
            )
            if binding_error:
                results.append(TaskReadiness(task.task_id, BLOCKED, binding_error, "An explicit DispatchBinding is required for reconciliation"))
                continue
            binding = candidates[0]
            gate_status, gate_code, gate_reason = _binding_gate(binding, resolution, observed_at)
            if gate_status == READY:
                results.append(TaskReadiness(task.task_id, ACTIVE, None, "Task is ACTIVE and requires execution reconciliation", binding, binding.capability_id, binding.capability_version))
            else:
                results.append(TaskReadiness(task.task_id, gate_status, gate_code, gate_reason, binding, binding.capability_id, binding.capability_version))
            continue
        if task.lifecycle_state != TaskLifecycleState.PENDING:
            results.append(TaskReadiness(task.task_id, "NOT_ELIGIBLE", "TASK_NOT_PENDING", "Task is not PENDING"))
            continue
        availability = state.task_availability(task.task_id)
        if availability != TaskAvailability.READY:
            dependency_status, dependency_code, dependency_reason = _dependency_gate(state, task)
            if dependency_status == WAIT:
                results.append(TaskReadiness(task.task_id, WAIT, dependency_code, dependency_reason))
            elif dependency_status == BLOCKED:
                results.append(TaskReadiness(task.task_id, BLOCKED, dependency_code, dependency_reason))
            else:
                results.append(TaskReadiness(task.task_id, BLOCKED, "TASK_NOT_READY", "R1.2 does not mark Task READY"))
            continue

        candidates, binding_error = _matching_bindings(
            bindings,
            mission_id=mission_id,
            plan_id=plan_id,
            revision_id=revision_id,
            task_id=task.task_id,
        )
        if binding_error:
            results.append(TaskReadiness(task.task_id, BLOCKED, binding_error, "An explicit DispatchBinding is required"))
            continue
        binding = candidates[0]
        gate_status, gate_code, gate_reason = _binding_gate(binding, resolution, observed_at)
        results.append(
            TaskReadiness(
                task.task_id,
                gate_status,
                gate_code,
                gate_reason,
                binding,
                binding.capability_id,
                binding.capability_version,
            )
        )

    ready = tuple(item for item in results if item.status == READY)
    if ready:
        return ReadinessReport(mission_id, plan_id, revision_id, observed_seq, tuple(results), ready, READY)
    if any(item.status == BLOCKED for item in results):
        first = next(item for item in results if item.status == BLOCKED)
        return ReadinessReport(mission_id, plan_id, revision_id, observed_seq, tuple(results), (), BLOCKED, first.reason_code, first.reason)
    return ReadinessReport(mission_id, plan_id, revision_id, observed_seq, tuple(results), (), WAIT, "NO_READY_TASK", "No Task is currently dispatch-ready")


def select_ready_tasks(
    report: ReadinessReport,
    policy: SchedulingPolicy | Mapping[str, Any],
    budget: LoopBudget | Mapping[str, Any],
    progress: LoopProgress | Mapping[str, Any],
) -> tuple[TaskReadiness, ...]:
    """Select a bounded prefix of the already ordered R1.2 READY set."""
    policy = SchedulingPolicy.from_mapping(policy)
    budget = LoopBudget.from_mapping(budget)
    progress = LoopProgress.from_mapping(progress)
    if budget.budget_id != progress.budget_id:
        raise R2_4Error("LOOP_BUDGET_MISMATCH", "LoopBudget and LoopProgress budget_id differ")
    remaining = budget.max_dispatches - progress.dispatches_used
    if remaining <= 0:
        return ()
    limit = min(policy.max_dispatches_per_cycle, remaining, len(report.ready_tasks))
    return tuple(report.ready_tasks[:limit])


def ready_tasks(value: Any, **overrides: Any) -> tuple[TaskReadiness, ...]:
    return evaluate_readiness(value, **overrides).ready_tasks


__all__ = [
    "ReadinessReport",
    "evaluate_readiness",
    "ready_tasks",
    "select_ready_tasks",
]
