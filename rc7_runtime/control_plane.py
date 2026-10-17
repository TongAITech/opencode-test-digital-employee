"""RC7 R1-backed control plane.

This is intentionally a deterministic controller, not a super-agent. It owns
Task dependency readiness, leasing, worker-output persistence and Gap routing.
It never performs Requirement/Code/Test work itself and never accepts worker
output as PASS. PRODUCT_DEFECT is a downstream qualification handoff rather
than an ordinary repair task.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional, Sequence, Set, Tuple

from rc6_runtime.truth import TruthRuntime

from .execution_fanout_conformance import (
    EXECUTION_TERMINAL_KIND,
    ExecutionFanoutConformanceError,
    load_execution_terminal_receipt,
)
from .gap_router import GapRouter
from .models import (
    Artifact,
    ArtifactStatus,
    Evidence,
    Gap,
    GapStatus,
    Task,
    TaskStatus,
)
from .state_machine import transition_gap, transition_task
from .truth_overlay import append_entity


class ControlPlaneError(RuntimeError):
    pass


@dataclass(frozen=True)
class WorkerOutput:
    task_id: str
    worker_ref: str
    artifacts: Tuple[Artifact, ...] = ()
    evidence: Tuple[Evidence, ...] = ()


_CAPABILITIES_BY_NODE = {
    "REQUIREMENT_ANALYSIS": ("requirement_reasoning",),
    "CODE_ANALYSIS": ("code_reasoning", "code_reality"),
    "TEST_DESIGN": ("test_design",),
    "SCRIPT_READINESS": ("test_automation",),
    "EXECUTION": ("test_execution",),
    "DEFECT": ("defect_analysis",),
    "MISSION_EVALUATION": ("mission_evaluation",),
    "RUNTIME": ("runtime_recovery",),
}


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


class TaskScheduler:
    def __init__(self, truth: TruthRuntime, release_id: str) -> None:
        if not release_id:
            raise ControlPlaneError("RELEASE_ID_REQUIRED")
        self.truth = truth
        self.release_id = release_id

    def register(self, task: Task) -> Task:
        if self._row(task.task_id) is not None:
            raise ControlPlaneError("TASK_ALREADY_REGISTERED")
        for dependency_id in task.dependency_task_ids:
            row = self._row(dependency_id)
            if row is None:
                raise ControlPlaneError("TASK_DEPENDENCY_NOT_FOUND:%s" % dependency_id)
            if row["mission_id"] != task.mission_id:
                raise ControlPlaneError("TASK_DEPENDENCY_MISSION_MISMATCH")
            if self._depends_on(dependency_id, task.task_id):
                raise ControlPlaneError("TASK_DEPENDENCY_CYCLE_FORBIDDEN")
        append_entity(self.truth, task, release_id=self.release_id, artifact_version=1)
        return task

    def refresh_ready(self, mission_id: str) -> Tuple[Task, ...]:
        rows = self.truth.query("rc7_task", mission_id=mission_id)
        states = {row["task_id"]: row["state"] for row in rows}
        ready = []
        for row in rows:
            if row["state"] != TaskStatus.REGISTERED.value:
                continue
            dependencies = row.get("dependency_task_ids", [])
            if any(states.get(dep) != TaskStatus.PASS.value for dep in dependencies):
                continue
            if not self._inputs_valid(row.get("input_artifact_refs", [])):
                continue
            task = self._task_from_row(row)
            transition_task(task, TaskStatus.READY)
            self._persist_task(task, int(row["artifact_version"]) + 1)
            ready.append(task)
        return tuple(sorted(ready, key=lambda item: (item.priority, item.created_at, item.task_id)))

    def ready_tasks(self, mission_id: str) -> Tuple[Task, ...]:
        tasks = [
            self._task_from_row(row)
            for row in self.truth.query("rc7_task", mission_id=mission_id)
            if row["state"] == TaskStatus.READY.value
        ]
        return tuple(sorted(tasks, key=lambda item: (item.priority, item.created_at, item.task_id)))

    def lease_next(
        self,
        mission_id: str,
        *,
        worker_ref: str,
        capabilities: Iterable[str],
    ) -> Optional[Task]:
        capability_set = set(capabilities)
        for task in self.ready_tasks(mission_id):
            if not set(task.required_capabilities).issubset(capability_set):
                continue
            row = self._row(task.task_id)
            if row is None or row["state"] != TaskStatus.READY.value:
                continue
            transition_task(task, TaskStatus.LEASED, lease_owner=worker_ref)
            self._persist_task(task, int(row["artifact_version"]) + 1)
            return task
        return None

    def start(self, task_id: str, *, worker_ref: str) -> Task:
        row = self._required_row(task_id)
        task = self._task_from_row(row)
        if task.lease_owner != worker_ref:
            raise ControlPlaneError("TASK_LEASE_OWNER_MISMATCH")
        transition_task(task, TaskStatus.RUNNING)
        self._persist_task(task, int(row["artifact_version"]) + 1)
        return task

    def submit_worker_output(self, output: WorkerOutput) -> Task:
        row = self._required_row(output.task_id)
        task = self._task_from_row(row)
        if task.state != TaskStatus.RUNNING:
            raise ControlPlaneError("TASK_NOT_RUNNING")
        if task.lease_owner != output.worker_ref:
            raise ControlPlaneError("TASK_LEASE_OWNER_MISMATCH")
        for evidence in output.evidence:
            if evidence.mission_id != task.mission_id:
                raise ControlPlaneError("WORKER_EVIDENCE_MISSION_MISMATCH")
            append_entity(self.truth, evidence, release_id=self.release_id)
        for artifact in output.artifacts:
            if artifact.mission_id != task.mission_id or artifact.producer_task_id != task.task_id:
                raise ControlPlaneError("WORKER_ARTIFACT_OWNERSHIP_MISMATCH")
            append_entity(self.truth, artifact, release_id=self.release_id, artifact_version=artifact.version)
        task.output_artifact_refs = [item.artifact_id for item in output.artifacts]
        transition_task(task, TaskStatus.OUTPUT_PRODUCED)
        self._persist_task(task, int(row["artifact_version"]) + 1)
        return task

    def persist_evaluated_task(self, task: Task) -> Task:
        row = self._required_row(task.task_id)
        if task.state not in {
            TaskStatus.PASS,
            TaskStatus.REPAIR_REQUIRED,
            TaskStatus.BLOCKED,
            TaskStatus.HUMAN_REQUIRED,
            TaskStatus.FAILED,
            TaskStatus.STALE,
        }:
            raise ControlPlaneError("TASK_EVALUATION_TERMINAL_STATE_REQUIRED")
        self._persist_task(task, int(row["artifact_version"]) + 1)
        return task

    def task(self, task_id: str) -> Task:
        return self._task_from_row(self._required_row(task_id))

    def _inputs_valid(self, artifact_refs: Sequence[str]) -> bool:
        for artifact_id in artifact_refs:
            rows = self.truth.query("rc7_artifact", artifact_id=artifact_id)
            if not rows or rows[0]["state"] != ArtifactStatus.VALID.value:
                return False
        return True

    def _depends_on(self, task_id: str, target_id: str) -> bool:
        seen: Set[str] = set()
        queue = [task_id]
        while queue:
            current = queue.pop()
            if current in seen:
                continue
            seen.add(current)
            row = self._row(current)
            if row is None:
                continue
            for dependency in row.get("dependency_task_ids", []):
                if dependency == target_id:
                    return True
                queue.append(dependency)
        return False

    def _persist_task(self, task: Task, version: int) -> None:
        append_entity(self.truth, task, release_id=self.release_id, artifact_version=version)

    def _row(self, task_id: str):
        rows = self.truth.query("rc7_task", task_id=task_id)
        return rows[0] if rows else None

    def _required_row(self, task_id: str):
        row = self._row(task_id)
        if row is None:
            raise ControlPlaneError("TASK_NOT_FOUND")
        return row

    @staticmethod
    def _task_from_row(row: Mapping[str, object]) -> Task:
        return Task(
            task_id=str(row["task_id"]),
            mission_id=str(row["mission_id"]),
            node=str(row["node"]),
            task_type=str(row["task_type"]),
            objective=str(row["objective"]),
            state=TaskStatus(str(row["state"])),
            required_capabilities=list(row.get("required_capabilities", [])),
            dependency_task_ids=list(row.get("dependency_task_ids", [])),
            input_artifact_refs=list(row.get("input_artifact_refs", [])),
            gap_refs=list(row.get("gap_refs", [])),
            acceptance_criteria=list(row.get("acceptance_criteria", [])),
            priority=int(row.get("priority", 100)),
            lease_owner=row.get("lease_owner") if isinstance(row.get("lease_owner"), str) else None,
            output_artifact_refs=list(row.get("output_artifact_refs", [])),
            evaluation_id=row.get("evaluation_id") if isinstance(row.get("evaluation_id"), str) else None,
            created_at=int(row.get("created_at", 0)),
            updated_at=int(row.get("updated_at", 0)),
        )


class GapRepairPlanner:
    def __init__(self, truth: TruthRuntime, release_id: str, scheduler: TaskScheduler) -> None:
        self.truth = truth
        self.release_id = release_id
        self.scheduler = scheduler
        self.router = GapRouter()

    def plan(self, gap: Gap, *, priority: int = 50) -> Optional[Task]:
        decision = self.router.route(gap)
        if decision.target_node == "HUMAN_GATE":
            transition_gap(gap, GapStatus.HUMAN_REQUIRED)
            self._persist_gap(gap)
            return None
        if decision.requires_policy_review:
            raise ControlPlaneError("GAP_ROUTE_POLICY_REVIEW_REQUIRED:%s" % gap.category)
        if gap.state != GapStatus.OPEN:
            raise ControlPlaneError("GAP_MUST_BE_OPEN_FOR_PLANNING")

        is_product_defect = gap.category == "PRODUCT_DEFECT" and decision.target_node == "DEFECT"
        product_source = self._product_defect_source(gap) if is_product_defect else None

        transition_gap(gap, GapStatus.PLANNED)
        self._persist_gap(gap)
        if is_product_defect:
            assert product_source is not None
            return self._plan_product_defect(gap, product_source)

        task_id = _stable_id("TASK-REPAIR", gap.mission_id, gap.gap_id, decision.target_node)
        existing = self.scheduler._row(task_id)
        if existing is not None:
            return self.scheduler._task_from_row(existing)
        task = Task(
            task_id=task_id,
            mission_id=gap.mission_id,
            node=decision.target_node,
            task_type="REPAIR",
            objective="Resolve %s: %s" % (gap.category, gap.description),
            required_capabilities=list(_CAPABILITIES_BY_NODE.get(decision.target_node, ())),
            gap_refs=[gap.gap_id],
            acceptance_criteria=list(gap.acceptance_criteria),
            priority=priority,
        )
        self.scheduler.register(task)
        return task

    def _product_defect_source(self, gap: Gap) -> Tuple[str, str]:
        receipt_source = self._product_defect_source_from_terminal_receipt(gap)
        if receipt_source is not None:
            return receipt_source
        return self._legacy_product_defect_source(gap)

    def _product_defect_source_from_terminal_receipt(self, gap: Gap) -> Optional[Tuple[str, str]]:
        candidate_ids = []
        for evidence_id in gap.evidence_refs:
            rows = self.truth.query("rc7_evidence", evidence_id=evidence_id)
            if len(rows) == 1 and rows[0].get("kind") == EXECUTION_TERMINAL_KIND:
                candidate_ids.append(str(evidence_id))
        candidate_ids = sorted(set(candidate_ids))
        if not candidate_ids:
            return None
        if len(candidate_ids) != 1:
            raise ControlPlaneError("PRODUCT_DEFECT_TERMINAL_RECEIPT_NOT_UNIQUE")
        receipt_id = candidate_ids[0]
        try:
            payload = load_execution_terminal_receipt(
                self.truth,
                mission_id=gap.mission_id,
                receipt_id=receipt_id,
            )
        except ExecutionFanoutConformanceError as exc:
            raise ControlPlaneError("PRODUCT_DEFECT_TERMINAL_RECEIPT_INVALID:%s" % exc) from exc
        if payload.get("outcome") != "PRODUCT_DEFECT":
            raise ControlPlaneError("PRODUCT_DEFECT_TERMINAL_RECEIPT_OUTCOME_INVALID")
        snapshot = payload.get("product_defect_gap")
        if not isinstance(snapshot, dict) or snapshot.get("gap_id") != gap.gap_id:
            raise ControlPlaneError("PRODUCT_DEFECT_TERMINAL_GAP_BINDING_MISMATCH")
        artifact_id = str(payload.get("execution_artifact_id") or "")
        if not artifact_id:
            raise ControlPlaneError("PRODUCT_DEFECT_TERMINAL_SOURCE_ARTIFACT_REQUIRED")
        artifacts = self.truth.query("rc7_artifact", artifact_id=artifact_id)
        if len(artifacts) != 1:
            raise ControlPlaneError("PRODUCT_DEFECT_SOURCE_ARTIFACT_NOT_UNIQUE")
        artifact = artifacts[0]
        if artifact.get("mission_id") != gap.mission_id:
            raise ControlPlaneError("PRODUCT_DEFECT_SOURCE_ARTIFACT_MISSION_MISMATCH")
        if artifact.get("artifact_type_name") != "EXECUTION_CONCLUSION":
            raise ControlPlaneError("PRODUCT_DEFECT_SOURCE_EXECUTION_ARTIFACT_REQUIRED")
        producer_task_id = str(artifact.get("producer_task_id") or "")
        if not producer_task_id or producer_task_id != str(payload.get("execution_task_id") or ""):
            raise ControlPlaneError("PRODUCT_DEFECT_SOURCE_TASK_BINDING_MISMATCH")
        source_task = self.scheduler._row(producer_task_id)
        if source_task is None:
            raise ControlPlaneError("PRODUCT_DEFECT_SOURCE_TASK_NOT_FOUND")
        if source_task.get("mission_id") != gap.mission_id or source_task.get("node") != "EXECUTION":
            raise ControlPlaneError("PRODUCT_DEFECT_SOURCE_TASK_IDENTITY_MISMATCH")
        if source_task.get("state") != TaskStatus.PASS.value:
            raise ControlPlaneError("PRODUCT_DEFECT_SOURCE_EXECUTION_TASK_PASS_REQUIRED")
        return producer_task_id, artifact_id

    def _legacy_product_defect_source(self, gap: Gap) -> Tuple[str, str]:
        evaluations = [
            row
            for row in self.truth.query("rc7_evaluation", mission_id=gap.mission_id)
            if row.get("node") == "EXECUTION"
            and gap.gap_id in row.get("gap_refs", [])
            and isinstance(row.get("dimensions"), dict)
            and row["dimensions"].get("failure_class") == "PRODUCT"
            and row["dimensions"].get("test_result") == "FAIL"
        ]
        if len(evaluations) != 1:
            raise ControlPlaneError("PRODUCT_DEFECT_SOURCE_EVALUATION_NOT_UNIQUE")
        artifact_refs = evaluations[0].get("artifact_refs")
        if not isinstance(artifact_refs, list) or len(artifact_refs) != 1:
            raise ControlPlaneError("PRODUCT_DEFECT_SOURCE_ARTIFACT_REQUIRED")
        artifact_id = str(artifact_refs[0])
        artifacts = self.truth.query("rc7_artifact", artifact_id=artifact_id)
        if len(artifacts) != 1:
            raise ControlPlaneError("PRODUCT_DEFECT_SOURCE_ARTIFACT_NOT_UNIQUE")
        artifact = artifacts[0]
        if artifact.get("mission_id") != gap.mission_id:
            raise ControlPlaneError("PRODUCT_DEFECT_SOURCE_ARTIFACT_MISSION_MISMATCH")
        if artifact.get("artifact_type_name") != "EXECUTION_CONCLUSION":
            raise ControlPlaneError("PRODUCT_DEFECT_SOURCE_EXECUTION_ARTIFACT_REQUIRED")
        producer_task_id = artifact.get("producer_task_id")
        if not isinstance(producer_task_id, str) or not producer_task_id:
            raise ControlPlaneError("PRODUCT_DEFECT_SOURCE_TASK_REQUIRED")
        source_task = self.scheduler._row(producer_task_id)
        if source_task is None:
            raise ControlPlaneError("PRODUCT_DEFECT_SOURCE_TASK_NOT_FOUND")
        if source_task.get("mission_id") != gap.mission_id:
            raise ControlPlaneError("PRODUCT_DEFECT_SOURCE_TASK_MISSION_MISMATCH")
        if source_task.get("node") != "EXECUTION" or source_task.get("state") != TaskStatus.PASS.value:
            raise ControlPlaneError("PRODUCT_DEFECT_SOURCE_EXECUTION_TASK_PASS_REQUIRED")
        return producer_task_id, artifact_id

    def _plan_product_defect(self, gap: Gap, source: Tuple[str, str]) -> Task:
        source_task_id, source_artifact_id = source
        reproduction_task_id = _stable_id(
            "TASK-DEFECT-REPRO",
            gap.mission_id,
            gap.gap_id,
            source_artifact_id,
        )
        reproduction_row = self.scheduler._row(reproduction_task_id)
        if reproduction_row is None:
            reproduction = Task(
                task_id=reproduction_task_id,
                mission_id=gap.mission_id,
                node="EXECUTION",
                task_type="DEFECT_REPRODUCTION",
                objective="Reproduce trusted product mismatch before defect qualification: %s" % gap.description,
                required_capabilities=["test_execution"],
                dependency_task_ids=[source_task_id],
                input_artifact_refs=[source_artifact_id],
                gap_refs=[gap.gap_id],
                acceptance_criteria=[
                    "original failing Case is re-executed through the governed runtime",
                    "reproduction reaches a conclusive trusted business result",
                    "formal runtime execution evidence is persisted in R1",
                ],
                priority=10,
            )
            self.scheduler.register(reproduction)
        else:
            reproduction = self.scheduler._task_from_row(reproduction_row)
            if (
                reproduction.node != "EXECUTION"
                or reproduction.task_type != "DEFECT_REPRODUCTION"
                or reproduction.dependency_task_ids != [source_task_id]
                or reproduction.input_artifact_refs != [source_artifact_id]
                or reproduction.gap_refs != [gap.gap_id]
            ):
                raise ControlPlaneError("PRODUCT_DEFECT_REPRODUCTION_TASK_IDENTITY_MISMATCH")

        qualification_task_id = _stable_id("TASK-DEFECT", gap.mission_id, gap.gap_id, "DEFECT")
        qualification_row = self.scheduler._row(qualification_task_id)
        if qualification_row is not None:
            qualification = self.scheduler._task_from_row(qualification_row)
            if (
                qualification.node != "DEFECT"
                or qualification.task_type != "QUALIFY_DEFECT"
                or qualification.dependency_task_ids != [reproduction_task_id]
                or qualification.gap_refs != [gap.gap_id]
            ):
                raise ControlPlaneError("PRODUCT_DEFECT_QUALIFICATION_TASK_IDENTITY_MISMATCH")
            return qualification

        qualification = Task(
            task_id=qualification_task_id,
            mission_id=gap.mission_id,
            node="DEFECT",
            task_type="QUALIFY_DEFECT",
            objective="Qualify evidence-backed product defect: %s" % gap.description,
            required_capabilities=list(_CAPABILITIES_BY_NODE["DEFECT"]),
            dependency_task_ids=[reproduction_task_id],
            input_artifact_refs=[source_artifact_id],
            gap_refs=[gap.gap_id],
            acceptance_criteria=list(gap.acceptance_criteria),
            priority=20,
        )
        self.scheduler.register(qualification)
        return qualification

    def _persist_gap(self, gap: Gap) -> None:
        rows = self.truth.query("rc7_gap", gap_id=gap.gap_id)
        version = int(rows[0]["artifact_version"]) + 1 if rows else 1
        append_entity(self.truth, gap, release_id=self.release_id, artifact_version=version)
