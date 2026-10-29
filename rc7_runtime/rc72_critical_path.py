"""RC7.2 canonical critical-path projection for economy scheduling.

Criticality is derived only from durable Task dependency truth.  It is never
inferred from node names, priorities, objectives, prompts, roles or IDs.  A
READY WorkItem that is a transitive prerequisite of unfinished downstream work
is forced to BLOCKING so cost-window policy cannot defer it.  If the dependency
graph is incomplete or invalid, the resolver also fails safe to BLOCKING: an
economy optimization may waste quota, but it must not delay Mission progress.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple

from rc6_runtime.truth import TruthRuntime

from .models import ContractError, Task, TaskStatus
from .rc72_context_economy import SemanticWorkDescriptor
from .rc72_model_economy import MissionCriticality
from .rc72_schedule_semantics import WorkScheduleSemanticsService


_TERMINAL_NONBLOCKING_STATES = {TaskStatus.PASS.value, TaskStatus.CANCELLED.value}


@dataclass(frozen=True)
class CriticalPathAssessment:
    workitem_id: str
    mission_id: str
    graph_status: str
    base_criticality: MissionCriticality
    effective_criticality: MissionCriticality
    reason: str
    downstream_workitem_ids: Tuple[str, ...] = ()

    @property
    def forced_blocking(self) -> bool:
        return (
            self.effective_criticality == MissionCriticality.BLOCKING
            and self.base_criticality != MissionCriticality.BLOCKING
        )


class CanonicalCriticalPathResolver:
    """Decorate explicit schedule semantics with deterministic dependency truth."""

    def __init__(
        self,
        truth: TruthRuntime,
        *,
        release_id: str,
        schedule_semantics: Optional[WorkScheduleSemanticsService] = None,
    ) -> None:
        if not isinstance(release_id, str) or not release_id.strip():
            raise ContractError("CRITICAL_PATH_RELEASE_ID_REQUIRED")
        self.truth = truth
        self.release_id = release_id.strip()
        self.schedule_semantics = schedule_semantics or WorkScheduleSemanticsService(
            truth, release_id=self.release_id
        )
        self.last_assessments: Dict[str, CriticalPathAssessment] = {}

    def resolve(self, task: Task) -> SemanticWorkDescriptor:
        if not isinstance(task, Task):
            raise ContractError("CRITICAL_PATH_TASK_REQUIRED")
        base = self.schedule_semantics.resolve(task)
        assessment = self._assess(task, base.mission_criticality)
        self.last_assessments[task.task_id] = assessment
        if assessment.effective_criticality == base.mission_criticality:
            return base
        return replace(base, mission_criticality=assessment.effective_criticality)

    def assessment(self, workitem_id: str) -> Optional[CriticalPathAssessment]:
        return self.last_assessments.get(workitem_id)

    def _assess(
        self,
        task: Task,
        base_criticality: MissionCriticality,
    ) -> CriticalPathAssessment:
        rows = self.truth.query("rc7_task", mission_id=task.mission_id)
        by_id: Dict[str, Mapping[str, Any]] = {}
        dependencies: Dict[str, Tuple[str, ...]] = {}

        for row in rows:
            task_id = row.get("task_id")
            if not isinstance(task_id, str) or not task_id.strip():
                return self._unsafe(task, base_criticality, "TASK_ID_INVALID")
            task_id = task_id.strip()
            if task_id in by_id:
                return self._unsafe(task, base_criticality, "TASK_ID_NOT_UNIQUE:%s" % task_id)
            if row.get("release_id") != self.release_id:
                return self._unsafe(task, base_criticality, "TASK_RELEASE_MISMATCH:%s" % task_id)
            state = row.get("state")
            try:
                TaskStatus(str(state))
            except ValueError:
                return self._unsafe(task, base_criticality, "TASK_STATE_INVALID:%s" % task_id)
            raw_dependencies = row.get("dependency_task_ids", [])
            if not isinstance(raw_dependencies, list) or not all(
                isinstance(value, str) and value.strip() for value in raw_dependencies
            ):
                return self._unsafe(task, base_criticality, "TASK_DEPENDENCIES_INVALID:%s" % task_id)
            if len(set(raw_dependencies)) != len(raw_dependencies):
                return self._unsafe(task, base_criticality, "TASK_DEPENDENCIES_DUPLICATE:%s" % task_id)
            by_id[task_id] = row
            dependencies[task_id] = tuple(raw_dependencies)

        if task.task_id not in by_id:
            return self._unsafe(task, base_criticality, "WORKITEM_NOT_IN_CANONICAL_GRAPH")

        for task_id, dependency_ids in dependencies.items():
            for dependency_id in dependency_ids:
                if dependency_id not in by_id:
                    return self._unsafe(
                        task,
                        base_criticality,
                        "DEPENDENCY_NOT_IN_MISSION_GRAPH:%s:%s" % (task_id, dependency_id),
                    )

        cycle = self._cycle_node(dependencies)
        if cycle is not None:
            return self._unsafe(task, base_criticality, "DEPENDENCY_CYCLE:%s" % cycle)

        downstream: List[str] = []
        memo: Dict[Tuple[str, str], bool] = {}
        for candidate_id, row in by_id.items():
            if candidate_id == task.task_id:
                continue
            if str(row.get("state")) in _TERMINAL_NONBLOCKING_STATES:
                continue
            if self._depends_transitively(candidate_id, task.task_id, dependencies, memo):
                downstream.append(candidate_id)

        if downstream:
            return CriticalPathAssessment(
                workitem_id=task.task_id,
                mission_id=task.mission_id,
                graph_status="VERIFIED",
                base_criticality=base_criticality,
                effective_criticality=MissionCriticality.BLOCKING,
                reason="CANONICAL_UNFINISHED_DOWNSTREAM_DEPENDENCY",
                downstream_workitem_ids=tuple(sorted(downstream)),
            )

        return CriticalPathAssessment(
            workitem_id=task.task_id,
            mission_id=task.mission_id,
            graph_status="VERIFIED",
            base_criticality=base_criticality,
            effective_criticality=base_criticality,
            reason=(
                "EXPLICIT_BLOCKING_PRESERVED"
                if base_criticality == MissionCriticality.BLOCKING
                else "NO_UNFINISHED_DOWNSTREAM_DEPENDENCY"
            ),
            downstream_workitem_ids=(),
        )

    @staticmethod
    def _unsafe(
        task: Task,
        base_criticality: MissionCriticality,
        reason: str,
    ) -> CriticalPathAssessment:
        return CriticalPathAssessment(
            workitem_id=task.task_id,
            mission_id=task.mission_id,
            graph_status="UNSAFE",
            base_criticality=base_criticality,
            effective_criticality=MissionCriticality.BLOCKING,
            reason="DEPENDENCY_GRAPH_UNSAFE_RUN_NOW:%s" % reason,
            downstream_workitem_ids=(),
        )

    @staticmethod
    def _cycle_node(dependencies: Mapping[str, Tuple[str, ...]]) -> Optional[str]:
        visiting: Set[str] = set()
        visited: Set[str] = set()

        def visit(task_id: str) -> Optional[str]:
            if task_id in visiting:
                return task_id
            if task_id in visited:
                return None
            visiting.add(task_id)
            for dependency_id in dependencies.get(task_id, ()):
                found = visit(dependency_id)
                if found is not None:
                    return found
            visiting.remove(task_id)
            visited.add(task_id)
            return None

        for task_id in sorted(dependencies):
            found = visit(task_id)
            if found is not None:
                return found
        return None

    @classmethod
    def _depends_transitively(
        cls,
        candidate_id: str,
        target_id: str,
        dependencies: Mapping[str, Tuple[str, ...]],
        memo: Dict[Tuple[str, str], bool],
    ) -> bool:
        key = (candidate_id, target_id)
        if key in memo:
            return memo[key]
        direct = dependencies.get(candidate_id, ())
        if target_id in direct:
            memo[key] = True
            return True
        result = any(
            cls._depends_transitively(dependency_id, target_id, dependencies, memo)
            for dependency_id in direct
        )
        memo[key] = result
        return result
