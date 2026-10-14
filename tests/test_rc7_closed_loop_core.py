from __future__ import annotations

import pytest

from rc7_runtime import (
    Artifact,
    ArtifactStatus,
    ConvergenceInput,
    EvaluationResult,
    Gap,
    GapSeverity,
    GapStatus,
    Mission,
    MissionStatus,
    Task,
    TaskStatus,
    decide_convergence,
    invalidate_artifact,
    transition_gap,
    transition_mission,
    transition_task,
)
from rc7_runtime.state_machine import TransitionError


def _task() -> Task:
    return Task(
        task_id="TASK-1",
        mission_id="MISSION-1",
        node="REQUIREMENT_ANALYSIS",
        task_type="PRODUCE",
        objective="Produce requirement model candidate",
        acceptance_criteria=["independent evaluation passes"],
    )


def _gap() -> Gap:
    return Gap(
        gap_id="GAP-1",
        mission_id="MISSION-1",
        source_node="REQUIREMENT_ANALYSIS",
        category="MISSING_BOUNDARY",
        severity=GapSeverity.CRITICAL,
        target_node="REQUIREMENT_ANALYSIS",
        description="Boundary semantics are not evidenced",
        acceptance_criteria=["boundary has evidence"],
    )


def test_worker_output_cannot_self_accept_task() -> None:
    task = _task()
    transition_task(task, TaskStatus.READY)
    transition_task(task, TaskStatus.LEASED, lease_owner="worker-session-A")
    transition_task(task, TaskStatus.RUNNING)
    transition_task(task, TaskStatus.OUTPUT_PRODUCED)

    with pytest.raises(TransitionError):
        transition_task(task, TaskStatus.PASS, evaluation_id="EVAL-should-not-bypass")

    assert task.state == TaskStatus.OUTPUT_PRODUCED


def test_task_pass_requires_independent_evaluation_reference() -> None:
    task = _task()
    transition_task(task, TaskStatus.READY)
    transition_task(task, TaskStatus.LEASED, lease_owner="worker-session-A")
    transition_task(task, TaskStatus.RUNNING)
    transition_task(task, TaskStatus.OUTPUT_PRODUCED)
    transition_task(task, TaskStatus.EVALUATING)

    with pytest.raises(TransitionError, match="TASK_PASS_REQUIRES_EVALUATION"):
        transition_task(task, TaskStatus.PASS)

    transition_task(task, TaskStatus.PASS, evaluation_id="EVAL-1")
    assert task.state == TaskStatus.PASS
    assert task.evaluation_id == "EVAL-1"


def test_gap_resolution_requires_evidence_pending_and_evaluation() -> None:
    gap = _gap()
    transition_gap(gap, GapStatus.PLANNED)
    transition_gap(gap, GapStatus.REPAIRING)

    with pytest.raises(TransitionError):
        transition_gap(gap, GapStatus.RESOLVED, resolution_evaluation_id="EVAL-1")

    transition_gap(gap, GapStatus.EVIDENCE_PENDING)
    with pytest.raises(TransitionError, match="GAP_RESOLUTION_REQUIRES_EVALUATION"):
        transition_gap(gap, GapStatus.RESOLVED)

    transition_gap(gap, GapStatus.RESOLVED, resolution_evaluation_id="EVAL-2")
    assert gap.state == GapStatus.RESOLVED
    assert gap.resolution_evaluation_id == "EVAL-2"


def test_upstream_change_can_invalidate_previously_valid_artifact() -> None:
    artifact = Artifact(
        artifact_id="ART-CASE-1",
        mission_id="MISSION-1",
        artifact_type="TEST_CASE_SET",
        producer_task_id="TASK-CASE-1",
        content_ref="artifact://case/v1",
        version=1,
    )
    assert artifact.state == ArtifactStatus.VALID

    invalidate_artifact(artifact, require_revalidation=True)
    assert artifact.state == ArtifactStatus.REVALIDATION_REQUIRED


def test_mission_cannot_converge_with_critical_gap_even_if_sufficiency_says_pass() -> None:
    mission = Mission(
        mission_id="MISSION-1",
        release_id="RC7",
        goal="Reach trustworthy test sufficiency",
        state=MissionStatus.EVALUATING,
    )
    decision = decide_convergence(
        ConvergenceInput(
            mission_sufficiency_result=EvaluationResult.PASS,
            open_critical_gaps=1,
        )
    )
    assert not decision.converged
    assert "OPEN_CRITICAL_GAPS" in decision.reasons

    with pytest.raises(TransitionError, match="MISSION_CONVERGENCE_GATE_NOT_PASS"):
        transition_mission(mission, MissionStatus.CONVERGED, convergence=decision, evaluation_id="EVAL-M-1")


def test_mission_converges_only_after_all_hard_gates_clear() -> None:
    mission = Mission(
        mission_id="MISSION-1",
        release_id="RC7",
        goal="Reach trustworthy test sufficiency",
        state=MissionStatus.EVALUATING,
    )
    decision = decide_convergence(
        ConvergenceInput(
            mission_sufficiency_result=EvaluationResult.PASS,
            open_critical_gaps=0,
            open_blocking_gaps=0,
            pending_defect_verifications=0,
            residual_risks_pending_acceptance=0,
        )
    )
    assert decision.converged

    transition_mission(mission, MissionStatus.CONVERGED, convergence=decision, evaluation_id="EVAL-M-2")
    assert mission.state == MissionStatus.CONVERGED
    assert mission.sufficiency_state == "SUFFICIENT"
    assert mission.latest_evaluation_id == "EVAL-M-2"


def test_passed_task_can_be_reopened_as_stale_after_upstream_change() -> None:
    task = _task()
    transition_task(task, TaskStatus.READY)
    transition_task(task, TaskStatus.LEASED, lease_owner="worker-session-A")
    transition_task(task, TaskStatus.RUNNING)
    transition_task(task, TaskStatus.OUTPUT_PRODUCED)
    transition_task(task, TaskStatus.EVALUATING)
    transition_task(task, TaskStatus.PASS, evaluation_id="EVAL-1")

    transition_task(task, TaskStatus.STALE)
    assert task.state == TaskStatus.STALE
    transition_task(task, TaskStatus.READY)
    assert task.state == TaskStatus.READY
