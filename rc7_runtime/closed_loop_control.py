"""RC7 end-to-end control-plane composition.

This module composes the proven scheduler, Gap router and node evaluators into
a deterministic closed loop. Ordinary repair work never closes its own Gap:
repair PASS only moves the Gap to EVIDENCE_PENDING and the source node must be
re-executed and independently re-evaluated. A trusted PRODUCT FAIL is a
cross-node handoff: Execution work may PASS as a conclusive result while the
PRODUCT_DEFECT Gap remains open until the Defect lifecycle reaches a terminal,
evidence-backed state.
"""

from __future__ import annotations

from typing import Iterable, List, Mapping, Optional, Sequence, Tuple

from rc6_runtime.truth import TruthRuntime

from .control_plane import ControlPlaneError, GapRepairPlanner, TaskScheduler, WorkerOutput
from .models import (
    Evaluation,
    EvaluationResult,
    Gap,
    GapStatus,
    Mission,
    MissionStatus,
    Task,
    TaskStatus,
)
from .session_continuity import SessionContinuityManager
from .state_machine import (
    ConvergenceInput,
    decide_convergence,
    transition_gap,
    transition_mission,
    transition_task,
)
from .truth_overlay import append_entity, install_rc7_truth_overlay


class ClosedLoopControlError(ControlPlaneError):
    pass


_OPEN_GAP_STATES = {
    GapStatus.OPEN,
    GapStatus.PLANNED,
    GapStatus.REPAIRING,
    GapStatus.EVIDENCE_PENDING,
    GapStatus.HUMAN_REQUIRED,
    GapStatus.BLOCKED,
}

_ACTIVE_TASK_STATES = {
    TaskStatus.REGISTERED,
    TaskStatus.READY,
    TaskStatus.LEASED,
    TaskStatus.RUNNING,
    TaskStatus.OUTPUT_PRODUCED,
    TaskStatus.EVALUATING,
    TaskStatus.REPAIR_REQUIRED,
    TaskStatus.BLOCKED,
    TaskStatus.HUMAN_REQUIRED,
    TaskStatus.FAILED,
    TaskStatus.STALE,
}

_PASS_HANDOFF_GAPS = {
    ("EXECUTION", "PRODUCT_DEFECT", "DEFECT"),
}

_DEFECT_RESOLUTION_STATES = {"CLOSED", "DUPLICATE", "NOT_A_DEFECT"}


class ClosedLoopControlPlane:
    def __init__(self, truth: TruthRuntime, release_id: str, mission_id: str) -> None:
        install_rc7_truth_overlay()
        self.truth = truth
        self.release_id = release_id
        self.mission_id = mission_id
        self.scheduler = TaskScheduler(truth, release_id)
        self.gap_planner = GapRepairPlanner(truth, release_id, self.scheduler)
        self.sessions = SessionContinuityManager(truth, release_id)
        self._mission_row()

    @classmethod
    def bootstrap(cls, truth: TruthRuntime, mission: Mission) -> "ClosedLoopControlPlane":
        install_rc7_truth_overlay()
        if truth.query("rc7_mission", mission_id=mission.mission_id):
            raise ClosedLoopControlError("MISSION_ALREADY_REGISTERED")
        append_entity(truth, mission, release_id=mission.release_id, artifact_version=1)
        return cls(truth, mission.release_id, mission.mission_id)

    def register_task(self, task: Task) -> Task:
        if task.mission_id != self.mission_id:
            raise ClosedLoopControlError("TASK_MISSION_MISMATCH")
        registered = self.scheduler.register(task)
        mission = self._mission()
        if mission.state == MissionStatus.REGISTERED:
            transition_mission(mission, MissionStatus.RUNNING)
        self.scheduler.refresh_ready(self.mission_id)
        self._sync_mission(mission)
        return registered

    def refresh_ready(self) -> Tuple[Task, ...]:
        ready = self.scheduler.refresh_ready(self.mission_id)
        self._sync_mission(self._mission())
        return ready

    def lease_next(
        self,
        *,
        worker_ref: str,
        capabilities: Iterable[str],
    ) -> Optional[Task]:
        task = self.scheduler.lease_next(
            self.mission_id,
            worker_ref=worker_ref,
            capabilities=capabilities,
        )
        if task is None:
            return None
        if task.task_type in {"REPAIR", "QUALIFY_DEFECT"}:
            for gap_id in task.gap_refs:
                gap = self._gap(gap_id)
                if gap.state != GapStatus.PLANNED:
                    raise ClosedLoopControlError("OWNERSHIP_TASK_LEASE_REQUIRES_PLANNED_GAP")
                transition_gap(gap, GapStatus.REPAIRING)
                self._persist_gap(gap)
        self._sync_mission(self._mission())
        return task

    def start(self, task_id: str, *, worker_ref: str) -> Task:
        task = self.scheduler.start(task_id, worker_ref=worker_ref)
        self._sync_mission(self._mission())
        return task

    def submit_worker_output(self, output: WorkerOutput) -> Task:
        task = self.scheduler.submit_worker_output(output)
        self._sync_mission(self._mission())
        return task

    def accept_evaluation(
        self,
        task_id: str,
        *,
        evaluation: Evaluation,
        gaps: Sequence[Gap] = (),
    ) -> Task:
        task = self.scheduler.task(task_id)
        if task.state != TaskStatus.OUTPUT_PRODUCED:
            raise ClosedLoopControlError("TASK_CANDIDATE_OUTPUT_REQUIRED")
        if evaluation.mission_id != task.mission_id or evaluation.node != task.node:
            raise ClosedLoopControlError("EVALUATION_TASK_IDENTITY_MISMATCH")
        if task.lease_owner and evaluation.evaluator_ref == task.lease_owner:
            raise ClosedLoopControlError("WORKER_SELF_EVALUATION_FORBIDDEN")
        if task.output_artifact_refs and not set(task.output_artifact_refs).intersection(evaluation.artifact_refs):
            raise ClosedLoopControlError("EVALUATION_DOES_NOT_REFERENCE_TASK_OUTPUT")
        if set(evaluation.gap_refs) != {gap.gap_id for gap in gaps}:
            raise ClosedLoopControlError("EVALUATION_GAP_SET_MISMATCH")
        if task.task_type == "QUALIFY_DEFECT" and evaluation.result == EvaluationResult.PASS:
            raise ClosedLoopControlError("DEFECT_TASK_REQUIRES_TERMINAL_DEFECT_RESOLUTION")
        if evaluation.result == EvaluationResult.PASS and gaps:
            invalid = [gap for gap in gaps if not self._is_pass_handoff_gap(task, gap)]
            if invalid:
                raise ClosedLoopControlError("PASS_EVALUATION_GAP_NOT_HANDOFF_ELIGIBLE")
        if evaluation.result == EvaluationResult.REPAIR_REQUIRED and not gaps:
            raise ClosedLoopControlError("REPAIR_EVALUATION_REQUIRES_GAPS")

        append_entity(self.truth, evaluation, release_id=self.release_id, artifact_version=1)
        transition_task(task, TaskStatus.EVALUATING)

        if evaluation.result == EvaluationResult.PASS:
            if task.task_type == "REPAIR":
                transition_task(task, TaskStatus.PASS, evaluation_id=evaluation.evaluation_id)
                self.scheduler.persist_evaluated_task(task)
                for gap_id in task.gap_refs:
                    gap = self._gap(gap_id)
                    if gap.state != GapStatus.REPAIRING:
                        raise ClosedLoopControlError("REPAIR_PASS_REQUIRES_REPAIRING_GAP")
                    transition_gap(gap, GapStatus.EVIDENCE_PENDING)
                    self._persist_gap(gap)
                self._reactivate_source_tasks(task.gap_refs)
            else:
                self._resolve_source_gaps(task, evaluation)
                for gap in gaps:
                    self._validate_new_gap(task, gap)
                    if gap.gap_id not in task.gap_refs:
                        task.gap_refs.append(gap.gap_id)
                transition_task(task, TaskStatus.PASS, evaluation_id=evaluation.evaluation_id)
                self.scheduler.persist_evaluated_task(task)
                for gap in gaps:
                    self.gap_planner.plan(gap, priority=20)
                self.scheduler.refresh_ready(self.mission_id)
        elif evaluation.result == EvaluationResult.REPAIR_REQUIRED:
            for gap in gaps:
                self._validate_new_gap(task, gap)
                if gap.gap_id not in task.gap_refs:
                    task.gap_refs.append(gap.gap_id)
                self.gap_planner.plan(gap)
            transition_task(task, TaskStatus.REPAIR_REQUIRED, evaluation_id=evaluation.evaluation_id)
            self.scheduler.persist_evaluated_task(task)
            mission = self._mission()
            if mission.state == MissionStatus.RUNNING:
                transition_mission(mission, MissionStatus.REPAIRING)
                self._persist_mission(mission)
        elif evaluation.result == EvaluationResult.BLOCKED:
            if not gaps:
                raise ClosedLoopControlError("BLOCKED_EVALUATION_REQUIRES_GAP")
            for gap in gaps:
                self._validate_new_gap(task, gap)
                if gap.gap_id not in task.gap_refs:
                    task.gap_refs.append(gap.gap_id)
                self.gap_planner.plan(gap)
            transition_task(task, TaskStatus.BLOCKED, evaluation_id=evaluation.evaluation_id)
            self.scheduler.persist_evaluated_task(task)
            mission = self._mission()
            if mission.state in {MissionStatus.RUNNING, MissionStatus.REPAIRING}:
                transition_mission(mission, MissionStatus.BLOCKED)
                self._persist_mission(mission)
        elif evaluation.result == EvaluationResult.HUMAN_REQUIRED:
            if not gaps:
                raise ClosedLoopControlError("HUMAN_EVALUATION_REQUIRES_GAP")
            for gap in gaps:
                self._validate_new_gap(task, gap)
                append_entity(self.truth, gap, release_id=self.release_id, artifact_version=1)
                transition_gap(gap, GapStatus.HUMAN_REQUIRED)
                self._persist_gap(gap)
                if gap.gap_id not in task.gap_refs:
                    task.gap_refs.append(gap.gap_id)
            transition_task(task, TaskStatus.HUMAN_REQUIRED, evaluation_id=evaluation.evaluation_id)
            self.scheduler.persist_evaluated_task(task)
            mission = self._mission()
            if mission.state in {MissionStatus.RUNNING, MissionStatus.REPAIRING}:
                transition_mission(mission, MissionStatus.WAITING_HUMAN)
                self._persist_mission(mission)
        else:
            raise ClosedLoopControlError("UNSUPPORTED_EVALUATION_RESULT")

        self._sync_mission(self._mission())
        return self.scheduler.task(task_id)

    def accept_defect_resolution(self, task_id: str, *, defect, evaluation: Evaluation) -> Task:
        """Close a PRODUCT_DEFECT handoff only with terminal Defect truth."""
        task = self.scheduler.task(task_id)
        if task.node != "DEFECT" or task.task_type != "QUALIFY_DEFECT":
            raise ClosedLoopControlError("PRODUCT_DEFECT_TASK_REQUIRED")
        if task.state != TaskStatus.OUTPUT_PRODUCED:
            raise ClosedLoopControlError("DEFECT_TERMINAL_OUTPUT_REQUIRED")
        if len(task.gap_refs) != 1:
            raise ClosedLoopControlError("DEFECT_TASK_REQUIRES_SINGLE_PRODUCT_GAP")
        gap = self._gap(task.gap_refs[0])
        if gap.category != "PRODUCT_DEFECT" or gap.target_node != "DEFECT":
            raise ClosedLoopControlError("DEFECT_TASK_GAP_IDENTITY_INVALID")
        if gap.state != GapStatus.REPAIRING:
            raise ClosedLoopControlError("DEFECT_RESOLUTION_REQUIRES_ACTIVE_OWNERSHIP")

        defect_state = getattr(getattr(defect, "state", None), "value", str(getattr(defect, "state", "")))
        defect_id = str(getattr(defect, "defect_id", ""))
        if getattr(defect, "mission_id", None) != self.mission_id:
            raise ClosedLoopControlError("DEFECT_MISSION_MISMATCH")
        if getattr(defect, "source_gap_id", None) != gap.gap_id:
            raise ClosedLoopControlError("DEFECT_SOURCE_GAP_MISMATCH")
        if defect_state not in _DEFECT_RESOLUTION_STATES:
            raise ClosedLoopControlError("DEFECT_NOT_TERMINAL_FOR_GAP_RESOLUTION")

        if evaluation.mission_id != self.mission_id or evaluation.node != "DEFECT":
            raise ClosedLoopControlError("DEFECT_RESOLUTION_EVALUATION_IDENTITY_MISMATCH")
        if evaluation.result != EvaluationResult.PASS:
            raise ClosedLoopControlError("DEFECT_RESOLUTION_REQUIRES_PASS_EVALUATION")
        if task.lease_owner and evaluation.evaluator_ref == task.lease_owner:
            raise ClosedLoopControlError("WORKER_SELF_EVALUATION_FORBIDDEN")
        if task.output_artifact_refs and not set(task.output_artifact_refs).intersection(evaluation.artifact_refs):
            raise ClosedLoopControlError("DEFECT_EVALUATION_DOES_NOT_REFERENCE_OUTPUT")
        if evaluation.dimensions.get("defect_id") != defect_id:
            raise ClosedLoopControlError("DEFECT_EVALUATION_ID_MISMATCH")
        if evaluation.dimensions.get("defect_state") != defect_state:
            raise ClosedLoopControlError("DEFECT_EVALUATION_STATE_MISMATCH")
        if getattr(defect, "latest_evaluation_id", None) != evaluation.evaluation_id:
            raise ClosedLoopControlError("DEFECT_LATEST_EVALUATION_MISMATCH")

        append_entity(self.truth, evaluation, release_id=self.release_id, artifact_version=1)
        defect_rows = self.truth.query("rc7_defect", defect_id=defect_id)
        defect_version = int(defect_rows[0]["artifact_version"]) + 1 if defect_rows else 1
        append_entity(self.truth, defect, release_id=self.release_id, artifact_version=defect_version)

        transition_task(task, TaskStatus.EVALUATING)
        transition_task(task, TaskStatus.PASS, evaluation_id=evaluation.evaluation_id)
        self.scheduler.persist_evaluated_task(task)

        transition_gap(gap, GapStatus.EVIDENCE_PENDING)
        self._persist_gap(gap)
        transition_gap(gap, GapStatus.RESOLVED, resolution_evaluation_id=evaluation.evaluation_id)
        self._persist_gap(gap)
        self._sync_mission(self._mission())
        return self.scheduler.task(task_id)

    def converge_mission(
        self,
        evaluation: Evaluation,
        *,
        pending_defect_verifications: int = 0,
        residual_risks_pending_acceptance: int = 0,
    ) -> Mission:
        if evaluation.mission_id != self.mission_id or evaluation.node != "MISSION_EVALUATION":
            raise ClosedLoopControlError("MISSION_EVALUATION_IDENTITY_MISMATCH")
        if evaluation.result != EvaluationResult.PASS:
            raise ClosedLoopControlError("MISSION_EVALUATION_MUST_PASS")
        active = [
            row["task_id"]
            for row in self.truth.query("rc7_task", mission_id=self.mission_id)
            if TaskStatus(str(row["state"])) in _ACTIVE_TASK_STATES
        ]
        if active:
            raise ClosedLoopControlError("MISSION_HAS_ACTIVE_TASKS:%s" % ",".join(sorted(active)))
        open_gaps = [
            row
            for row in self.truth.query("rc7_gap", mission_id=self.mission_id)
            if GapStatus(str(row["state"])) in _OPEN_GAP_STATES
        ]
        if open_gaps:
            raise ClosedLoopControlError("MISSION_HAS_OPEN_GAPS")
        convergence = decide_convergence(
            ConvergenceInput(
                mission_sufficiency_result=evaluation.result,
                pending_defect_verifications=pending_defect_verifications,
                residual_risks_pending_acceptance=residual_risks_pending_acceptance,
            )
        )
        if not convergence.converged:
            raise ClosedLoopControlError("MISSION_CONVERGENCE_REJECTED:%s" % ",".join(convergence.reasons))
        sufficiency_state = str(evaluation.dimensions.get("sufficiency_state", ""))
        if sufficiency_state not in {"SUFFICIENT", "SUFFICIENT_WITH_RESIDUAL_RISK"}:
            raise ClosedLoopControlError("MISSION_SUFFICIENCY_STATE_INVALID")

        mission = self._mission()
        if mission.state == MissionStatus.RUNNING:
            transition_mission(mission, MissionStatus.EVALUATING)
        elif mission.state == MissionStatus.REPAIRING:
            transition_mission(mission, MissionStatus.EVALUATING)
        elif mission.state != MissionStatus.EVALUATING:
            raise ClosedLoopControlError("MISSION_NOT_READY_FOR_EVALUATION")
        self._persist_mission(mission)
        append_entity(self.truth, evaluation, release_id=self.release_id, artifact_version=1)
        transition_mission(
            mission,
            MissionStatus.CONVERGED,
            convergence=convergence,
            evaluation_id=evaluation.evaluation_id,
        )
        mission.sufficiency_state = sufficiency_state
        self._sync_mission(mission)
        return mission

    def snapshot(self) -> Mapping[str, object]:
        mission = self._mission_row()
        tasks = self.truth.query("rc7_task", mission_id=self.mission_id)
        gaps = self.truth.query("rc7_gap", mission_id=self.mission_id)
        return {
            "mission_id": self.mission_id,
            "mission_state": mission["state"],
            "active_task_ids": list(mission.get("active_task_ids", [])),
            "open_gap_ids": list(mission.get("open_gap_ids", [])),
            "ready_task_ids": sorted(row["task_id"] for row in tasks if row["state"] == TaskStatus.READY.value),
            "gap_states": {row["gap_id"]: row["state"] for row in gaps},
        }

    @staticmethod
    def _is_pass_handoff_gap(task: Task, gap: Gap) -> bool:
        return (task.node, gap.category, gap.target_node) in _PASS_HANDOFF_GAPS

    def _validate_new_gap(self, task: Task, gap: Gap) -> None:
        if gap.mission_id != self.mission_id or gap.source_node != task.node:
            raise ClosedLoopControlError("GAP_SOURCE_IDENTITY_MISMATCH")
        if self.truth.query("rc7_gap", gap_id=gap.gap_id):
            raise ClosedLoopControlError("GAP_ALREADY_EXISTS")

    def _resolve_source_gaps(self, task: Task, evaluation: Evaluation) -> None:
        for gap_id in task.gap_refs:
            rows = self.truth.query("rc7_gap", gap_id=gap_id)
            if not rows:
                continue
            gap = self._gap_from_row(rows[0])
            if gap.state != GapStatus.EVIDENCE_PENDING:
                continue
            if gap.source_node != task.node:
                raise ClosedLoopControlError("GAP_SOURCE_REEVALUATION_NODE_MISMATCH")
            transition_gap(gap, GapStatus.RESOLVED, resolution_evaluation_id=evaluation.evaluation_id)
            self._persist_gap(gap)
        mission = self._mission()
        if mission.state == MissionStatus.REPAIRING and not self._open_gap_rows():
            transition_mission(mission, MissionStatus.RUNNING)
            self._persist_mission(mission)

    def _reactivate_source_tasks(self, repaired_gap_ids: Sequence[str]) -> None:
        repaired = set(repaired_gap_ids)
        rows = self.truth.query("rc7_task", mission_id=self.mission_id)
        for row in rows:
            if row["task_type"] == "REPAIR":
                continue
            if row["state"] not in {TaskStatus.REPAIR_REQUIRED.value, TaskStatus.BLOCKED.value}:
                continue
            refs = set(row.get("gap_refs", []))
            if not refs.intersection(repaired):
                continue
            gap_rows = [self.truth.query("rc7_gap", gap_id=gap_id) for gap_id in refs]
            flattened = [items[0] for items in gap_rows if items]
            if not flattened or not all(
                item["state"] in {GapStatus.EVIDENCE_PENDING.value, GapStatus.RESOLVED.value}
                for item in flattened
            ):
                continue
            task = self.scheduler._task_from_row(row)
            task.output_artifact_refs = []
            task.evaluation_id = None
            transition_task(task, TaskStatus.READY)
            append_entity(
                self.truth,
                task,
                release_id=self.release_id,
                artifact_version=int(row["artifact_version"]) + 1,
            )
        mission = self._mission()
        if mission.state == MissionStatus.BLOCKED:
            transition_mission(mission, MissionStatus.RUNNING)
            self._persist_mission(mission)

    def _sync_mission(self, mission: Mission) -> None:
        task_rows = self.truth.query("rc7_task", mission_id=self.mission_id)
        gap_rows = self.truth.query("rc7_gap", mission_id=self.mission_id)
        mission.active_task_ids = sorted(
            row["task_id"]
            for row in task_rows
            if TaskStatus(str(row["state"])) in _ACTIVE_TASK_STATES
        )
        mission.open_gap_ids = sorted(
            row["gap_id"]
            for row in gap_rows
            if GapStatus(str(row["state"])) in _OPEN_GAP_STATES
        )
        self._persist_mission(mission)

    def _open_gap_rows(self) -> List[Mapping[str, object]]:
        return [
            row
            for row in self.truth.query("rc7_gap", mission_id=self.mission_id)
            if GapStatus(str(row["state"])) in _OPEN_GAP_STATES
        ]

    def _mission_row(self) -> Mapping[str, object]:
        rows = self.truth.query("rc7_mission", mission_id=self.mission_id)
        if len(rows) != 1:
            raise ClosedLoopControlError("MISSION_PROJECTION_NOT_FOUND")
        return rows[0]

    def _mission(self) -> Mission:
        row = self._mission_row()
        return Mission(
            mission_id=str(row["mission_id"]),
            release_id=str(row["release_id"]),
            goal=str(row["goal"]),
            state=MissionStatus(str(row["state"])),
            sufficiency_state=str(row.get("sufficiency_state", "UNKNOWN")),
            artifact_refs=list(row.get("artifact_refs", [])),
            open_gap_ids=list(row.get("open_gap_ids", [])),
            active_task_ids=list(row.get("active_task_ids", [])),
            residual_risk_ids=list(row.get("residual_risk_ids", [])),
            latest_evaluation_id=row.get("latest_evaluation_id") if isinstance(row.get("latest_evaluation_id"), str) else None,
            revision=int(row.get("revision", 1)),
            created_at=int(row.get("created_at", 0)),
            updated_at=int(row.get("updated_at", 0)),
        )

    def _persist_mission(self, mission: Mission) -> None:
        row = self._mission_row()
        append_entity(
            self.truth,
            mission,
            release_id=self.release_id,
            artifact_version=int(row["artifact_version"]) + 1,
        )

    def _gap(self, gap_id: str) -> Gap:
        rows = self.truth.query("rc7_gap", gap_id=gap_id)
        if not rows:
            raise ClosedLoopControlError("GAP_NOT_FOUND:%s" % gap_id)
        return self._gap_from_row(rows[0])

    @staticmethod
    def _gap_from_row(row: Mapping[str, object]) -> Gap:
        from .models import GapSeverity

        return Gap(
            gap_id=str(row["gap_id"]),
            mission_id=str(row["mission_id"]),
            source_node=str(row["source_node"]),
            category=str(row["category"]),
            severity=GapSeverity(str(row["severity"])),
            target_node=str(row["target_node"]),
            description=str(row["description"]),
            state=GapStatus(str(row["state"])),
            subject_refs=list(row.get("subject_refs", [])),
            evidence_refs=list(row.get("evidence_refs", [])),
            root_gap_id=row.get("root_gap_id") if isinstance(row.get("root_gap_id"), str) else None,
            acceptance_criteria=list(row.get("acceptance_criteria", [])),
            resolution_evaluation_id=row.get("resolution_evaluation_id") if isinstance(row.get("resolution_evaluation_id"), str) else None,
            created_at=int(row.get("created_at", 0)),
            updated_at=int(row.get("updated_at", 0)),
        )

    def _persist_gap(self, gap: Gap) -> None:
        rows = self.truth.query("rc7_gap", gap_id=gap.gap_id)
        version = int(rows[0]["artifact_version"]) + 1 if rows else 1
        append_entity(self.truth, gap, release_id=self.release_id, artifact_version=version)
