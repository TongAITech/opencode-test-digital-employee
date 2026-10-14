"""Deterministic RC7 control-plane state transitions and convergence gates.

The LLM/worker may propose an output, repair, or gap. It does not own these
transitions. Runtime code must pass through this module (or an equivalent
policy implementation) before durable state can be accepted.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, Set, Tuple

from .models import (
    Artifact,
    ArtifactStatus,
    EvaluationResult,
    Gap,
    GapStatus,
    Mission,
    MissionStatus,
    Task,
    TaskStatus,
)


class TransitionError(RuntimeError):
    pass


TASK_TRANSITIONS: Dict[TaskStatus, Set[TaskStatus]] = {
    TaskStatus.REGISTERED: {TaskStatus.READY, TaskStatus.CANCELLED},
    TaskStatus.READY: {
        TaskStatus.LEASED,
        TaskStatus.BLOCKED,
        TaskStatus.HUMAN_REQUIRED,
        TaskStatus.STALE,
        TaskStatus.CANCELLED,
    },
    TaskStatus.LEASED: {
        TaskStatus.RUNNING,
        TaskStatus.READY,
        TaskStatus.BLOCKED,
        TaskStatus.HUMAN_REQUIRED,
        TaskStatus.FAILED,
        TaskStatus.STALE,
    },
    TaskStatus.RUNNING: {
        TaskStatus.OUTPUT_PRODUCED,
        TaskStatus.BLOCKED,
        TaskStatus.HUMAN_REQUIRED,
        TaskStatus.FAILED,
        TaskStatus.STALE,
    },
    TaskStatus.OUTPUT_PRODUCED: {TaskStatus.EVALUATING, TaskStatus.STALE},
    TaskStatus.EVALUATING: {
        TaskStatus.PASS,
        TaskStatus.REPAIR_REQUIRED,
        TaskStatus.BLOCKED,
        TaskStatus.HUMAN_REQUIRED,
        TaskStatus.FAILED,
        TaskStatus.STALE,
    },
    TaskStatus.REPAIR_REQUIRED: {TaskStatus.READY, TaskStatus.STALE, TaskStatus.CANCELLED},
    TaskStatus.BLOCKED: {TaskStatus.READY, TaskStatus.STALE, TaskStatus.CANCELLED},
    TaskStatus.HUMAN_REQUIRED: {TaskStatus.READY, TaskStatus.BLOCKED, TaskStatus.STALE, TaskStatus.CANCELLED},
    TaskStatus.FAILED: {TaskStatus.READY, TaskStatus.CANCELLED, TaskStatus.STALE},
    TaskStatus.PASS: {TaskStatus.STALE},
    TaskStatus.STALE: {TaskStatus.READY, TaskStatus.CANCELLED},
    TaskStatus.CANCELLED: set(),
}


GAP_TRANSITIONS: Dict[GapStatus, Set[GapStatus]] = {
    GapStatus.OPEN: {
        GapStatus.PLANNED,
        GapStatus.HUMAN_REQUIRED,
        GapStatus.BLOCKED,
        GapStatus.WAIVED,
        GapStatus.DUPLICATE,
        GapStatus.SUPERSEDED,
    },
    GapStatus.PLANNED: {GapStatus.REPAIRING, GapStatus.HUMAN_REQUIRED, GapStatus.BLOCKED, GapStatus.SUPERSEDED},
    GapStatus.REPAIRING: {GapStatus.EVIDENCE_PENDING, GapStatus.BLOCKED, GapStatus.HUMAN_REQUIRED, GapStatus.SUPERSEDED},
    GapStatus.EVIDENCE_PENDING: {
        GapStatus.RESOLVED,
        GapStatus.REPAIRING,
        GapStatus.BLOCKED,
        GapStatus.HUMAN_REQUIRED,
        GapStatus.SUPERSEDED,
    },
    GapStatus.HUMAN_REQUIRED: {GapStatus.PLANNED, GapStatus.BLOCKED, GapStatus.WAIVED, GapStatus.SUPERSEDED},
    GapStatus.BLOCKED: {GapStatus.PLANNED, GapStatus.HUMAN_REQUIRED, GapStatus.WAIVED, GapStatus.SUPERSEDED},
    GapStatus.RESOLVED: set(),
    GapStatus.WAIVED: set(),
    GapStatus.DUPLICATE: set(),
    GapStatus.SUPERSEDED: set(),
}


MISSION_TRANSITIONS: Dict[MissionStatus, Set[MissionStatus]] = {
    MissionStatus.REGISTERED: {MissionStatus.RUNNING, MissionStatus.BLOCKED},
    MissionStatus.RUNNING: {
        MissionStatus.EVALUATING,
        MissionStatus.REPAIRING,
        MissionStatus.WAITING_HUMAN,
        MissionStatus.BLOCKED,
    },
    MissionStatus.EVALUATING: {
        MissionStatus.RUNNING,
        MissionStatus.REPAIRING,
        MissionStatus.WAITING_HUMAN,
        MissionStatus.BLOCKED,
        MissionStatus.CONVERGED,
    },
    MissionStatus.REPAIRING: {
        MissionStatus.RUNNING,
        MissionStatus.EVALUATING,
        MissionStatus.WAITING_HUMAN,
        MissionStatus.BLOCKED,
    },
    MissionStatus.WAITING_HUMAN: {
        MissionStatus.RUNNING,
        MissionStatus.REPAIRING,
        MissionStatus.BLOCKED,
    },
    MissionStatus.BLOCKED: {MissionStatus.RUNNING, MissionStatus.WAITING_HUMAN},
    MissionStatus.CONVERGED: {MissionStatus.CLOSED},
    MissionStatus.CLOSED: set(),
}


def _require_transition(current, target, table, prefix: str) -> None:
    allowed = table[current]
    if target not in allowed:
        raise TransitionError("%s_TRANSITION_FORBIDDEN:%s->%s" % (prefix, current.value, target.value))


def transition_task(task: Task, target: TaskStatus, *, evaluation_id: str = "", lease_owner: str = "") -> Task:
    _require_transition(task.state, target, TASK_TRANSITIONS, "TASK")

    if target == TaskStatus.LEASED:
        if not isinstance(lease_owner, str) or not lease_owner.strip():
            raise TransitionError("TASK_LEASE_OWNER_REQUIRED")
        task.lease_owner = lease_owner.strip()

    if target == TaskStatus.RUNNING and not task.lease_owner:
        raise TransitionError("TASK_MUST_BE_LEASED_BEFORE_RUNNING")

    if target == TaskStatus.PASS:
        if task.state != TaskStatus.EVALUATING:
            raise TransitionError("TASK_PASS_REQUIRES_EVALUATING_STATE")
        if not isinstance(evaluation_id, str) or not evaluation_id.strip():
            raise TransitionError("TASK_PASS_REQUIRES_EVALUATION")
        task.evaluation_id = evaluation_id.strip()

    if target in {TaskStatus.REPAIR_REQUIRED, TaskStatus.BLOCKED, TaskStatus.HUMAN_REQUIRED}:
        if task.state == TaskStatus.EVALUATING and evaluation_id:
            task.evaluation_id = evaluation_id.strip()

    # A blocked/human/stale/cancelled task no longer belongs to the worker that
    # happened to hold the lease when a shared dependency or gate stopped it.
    if target in {
        TaskStatus.READY,
        TaskStatus.BLOCKED,
        TaskStatus.HUMAN_REQUIRED,
        TaskStatus.STALE,
        TaskStatus.CANCELLED,
    }:
        task.lease_owner = None

    task.state = target
    task.updated_at = int(time.time())
    return task


def transition_gap(gap: Gap, target: GapStatus, *, resolution_evaluation_id: str = "") -> Gap:
    _require_transition(gap.state, target, GAP_TRANSITIONS, "GAP")
    if target == GapStatus.RESOLVED:
        if gap.state != GapStatus.EVIDENCE_PENDING:
            raise TransitionError("GAP_RESOLUTION_REQUIRES_EVIDENCE_PENDING")
        if not isinstance(resolution_evaluation_id, str) or not resolution_evaluation_id.strip():
            raise TransitionError("GAP_RESOLUTION_REQUIRES_EVALUATION")
        gap.resolution_evaluation_id = resolution_evaluation_id.strip()
    gap.state = target
    gap.updated_at = int(time.time())
    return gap


def invalidate_artifact(artifact: Artifact, *, require_revalidation: bool = True) -> Artifact:
    if artifact.state == ArtifactStatus.SUPERSEDED:
        raise TransitionError("SUPERSEDED_ARTIFACT_CANNOT_BE_INVALIDATED")
    artifact.state = (
        ArtifactStatus.REVALIDATION_REQUIRED if require_revalidation else ArtifactStatus.STALE
    )
    return artifact


@dataclass(frozen=True)
class ConvergenceInput:
    mission_sufficiency_result: EvaluationResult
    open_critical_gaps: int = 0
    open_blocking_gaps: int = 0
    pending_defect_verifications: int = 0
    residual_risks_pending_acceptance: int = 0

    def __post_init__(self) -> None:
        for name in (
            "open_critical_gaps",
            "open_blocking_gaps",
            "pending_defect_verifications",
            "residual_risks_pending_acceptance",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or value < 0:
                raise ValueError("%s_INVALID" % name.upper())


@dataclass(frozen=True)
class ConvergenceDecision:
    converged: bool
    reasons: Tuple[str, ...]


def decide_convergence(data: ConvergenceInput) -> ConvergenceDecision:
    reasons = []
    if data.mission_sufficiency_result != EvaluationResult.PASS:
        reasons.append("MISSION_SUFFICIENCY_NOT_PASS")
    if data.open_critical_gaps:
        reasons.append("OPEN_CRITICAL_GAPS")
    if data.open_blocking_gaps:
        reasons.append("OPEN_BLOCKING_GAPS")
    if data.pending_defect_verifications:
        reasons.append("DEFECT_VERIFICATION_PENDING")
    if data.residual_risks_pending_acceptance:
        reasons.append("RESIDUAL_RISK_ACCEPTANCE_PENDING")
    return ConvergenceDecision(converged=not reasons, reasons=tuple(reasons))


def transition_mission(
    mission: Mission,
    target: MissionStatus,
    *,
    convergence: ConvergenceDecision = None,
    evaluation_id: str = "",
) -> Mission:
    _require_transition(mission.state, target, MISSION_TRANSITIONS, "MISSION")
    if target == MissionStatus.CONVERGED:
        if convergence is None or not convergence.converged:
            raise TransitionError("MISSION_CONVERGENCE_GATE_NOT_PASS")
        if not isinstance(evaluation_id, str) or not evaluation_id.strip():
            raise TransitionError("MISSION_CONVERGENCE_REQUIRES_EVALUATION")
        mission.latest_evaluation_id = evaluation_id.strip()
        mission.sufficiency_state = "SUFFICIENT"
    mission.state = target
    mission.updated_at = int(time.time())
    return mission
