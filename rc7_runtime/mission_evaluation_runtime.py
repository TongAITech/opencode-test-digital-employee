"""Governed RC7 Mission Sufficiency runtime.

The Mission controller never accepts caller-supplied coverage counters.  This
runtime registers/leases a first-class MISSION_EVALUATION Task, derives an
immutable MissionEvidenceSnapshot from R1 truth, submits it as candidate output,
then applies the deterministic MissionSufficiencyClosedLoop.  PASS may converge
the Mission; gaps create ordinary routed repair work and reactivate this same
Task after evidence-backed repair.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Optional, Tuple

from .closed_loop_control import ClosedLoopControlPlane
from .control_plane import WorkerOutput
from .mission_evidence_builder import BuiltMissionEvidenceSnapshot, R1MissionEvidenceSnapshotBuilder
from .mission_sufficiency import MissionSufficiencyClosedLoop, MissionSufficiencyResult
from .models import MissionStatus, Task, TaskStatus


class MissionEvaluationRuntimeError(RuntimeError):
    pass


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


@dataclass(frozen=True)
class MissionEvaluationRuntimeResult:
    task_id: str
    task_state: str
    snapshot_artifact_id: str
    snapshot_evidence_id: str
    evaluation_id: str
    evaluation_result: str
    sufficiency_state: str
    release_recommendation: str
    mission_state: str
    gap_ids: Tuple[str, ...]


class MissionEvaluationRuntime:
    WORKER_REF = "rc7-runtime-mission-evidence-builder"

    def __init__(self, *, evidence_root: str) -> None:
        self.builder = R1MissionEvidenceSnapshotBuilder(evidence_root=evidence_root)
        self.gate = MissionSufficiencyClosedLoop()

    def run(self, control: ClosedLoopControlPlane) -> MissionEvaluationRuntimeResult:
        task = self._ensure_task(control)
        if task.state != TaskStatus.READY:
            raise MissionEvaluationRuntimeError("MISSION_EVALUATION_TASK_NOT_READY:%s" % task.state.value)

        ready = control.scheduler.ready_tasks(control.mission_id)
        if not ready or ready[0].task_id != task.task_id:
            raise MissionEvaluationRuntimeError("MISSION_EVALUATION_TASK_NOT_NEXT_READY")
        leased = control.lease_next(
            worker_ref=self.WORKER_REF,
            capabilities=("mission_evaluation",),
        )
        if leased is None or leased.task_id != task.task_id:
            raise MissionEvaluationRuntimeError("MISSION_EVALUATION_LEASE_MISMATCH")
        control.start(task.task_id, worker_ref=self.WORKER_REF)

        built = self.builder.build(
            control.truth,
            mission_id=control.mission_id,
            producer_task_id=task.task_id,
        )
        control.submit_worker_output(
            WorkerOutput(
                task_id=task.task_id,
                worker_ref=self.WORKER_REF,
                artifacts=(built.artifact,),
                evidence=(built.evidence,),
            )
        )
        result = self.gate.evaluate(built.snapshot)
        accepted = control.accept_evaluation(
            task.task_id,
            evaluation=result.evaluation,
            gaps=result.gaps,
        )

        if result.evaluation.result.value == "PASS":
            mission = control.converge_mission(
                result.evaluation,
                pending_defect_verifications=len(built.snapshot.pending_defect_verification_refs),
                residual_risks_pending_acceptance=sum(
                    1 for item in built.snapshot.residual_risks if item.disposition.upper() == "PENDING"
                ),
            )
        else:
            rows = control.truth.query("rc7_mission", mission_id=control.mission_id)
            if len(rows) != 1:
                raise MissionEvaluationRuntimeError("MISSION_TRUTH_NOT_UNIQUE_AFTER_EVALUATION")
            mission = None
            mission_state = str(rows[0]["state"])

        return MissionEvaluationRuntimeResult(
            task_id=task.task_id,
            task_state=accepted.state.value,
            snapshot_artifact_id=built.artifact.artifact_id,
            snapshot_evidence_id=built.evidence.evidence_id,
            evaluation_id=result.evaluation.evaluation_id,
            evaluation_result=result.evaluation.result.value,
            sufficiency_state=result.sufficiency_state,
            release_recommendation=result.release_recommendation,
            mission_state=mission.state.value if mission is not None else mission_state,
            gap_ids=tuple(gap.gap_id for gap in result.gaps),
        )

    def _ensure_task(self, control: ClosedLoopControlPlane) -> Task:
        task_id = _stable_id("TASK-MISSION-EVALUATION", control.mission_id)
        rows = control.truth.query("rc7_task", task_id=task_id)
        if rows:
            if len(rows) != 1:
                raise MissionEvaluationRuntimeError("MISSION_EVALUATION_TASK_NOT_UNIQUE")
            task = control.scheduler.task(task_id)
            if task.node != "MISSION_EVALUATION" or task.task_type != "EVALUATE":
                raise MissionEvaluationRuntimeError("MISSION_EVALUATION_TASK_IDENTITY_MISMATCH")
            return task

        blockers = []
        for row in control.truth.query("rc7_task", mission_id=control.mission_id):
            if row.get("node") == "MISSION_EVALUATION":
                continue
            state = str(row.get("state"))
            if state not in {
                TaskStatus.PASS.value,
                TaskStatus.CANCELLED.value,
                TaskStatus.SUPERSEDED.value,
            }:
                blockers.append(str(row.get("task_id")))
        if blockers:
            raise MissionEvaluationRuntimeError(
                "MISSION_EVALUATION_REQUIRES_SETTLED_BUSINESS_TASKS:%s" % ",".join(sorted(blockers))
            )

        task = Task(
            task_id=task_id,
            mission_id=control.mission_id,
            node="MISSION_EVALUATION",
            task_type="EVALUATE",
            objective="derive R1 evidence snapshot and decide Mission Test Sufficiency",
            required_capabilities=["mission_evaluation"],
            acceptance_criteria=[
                "MissionEvidenceSnapshot is derived exclusively from durable R1 truth",
                "critical requirements/obligations/code-impact/executions satisfy hard gates",
                "open defects/gaps and residual risk are explicitly dispositioned",
            ],
            priority=200,
        )
        control.register_task(task)
        return control.scheduler.task(task_id)
