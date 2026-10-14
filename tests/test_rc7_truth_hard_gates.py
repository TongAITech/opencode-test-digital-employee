from __future__ import annotations

import pytest

from rc6_runtime.truth import EventValidationError, TruthRuntime
from rc7_runtime import (
    Evaluation,
    EvaluationResult,
    Gap,
    GapSeverity,
    GapStatus,
    Mission,
    MissionStatus,
    Task,
    TaskStatus,
)
from rc7_runtime.truth_overlay import append_entity


def test_r1_rejects_pass_task_without_evaluation(tmp_path) -> None:
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    task = Task(
        task_id="TASK-BYPASS",
        mission_id="MISSION-1",
        node="TEST_DESIGN",
        task_type="PRODUCE",
        objective="Try to bypass evaluator",
        state=TaskStatus.PASS,
    )

    with pytest.raises(EventValidationError, match="DURABLE_PASS_REQUIRES_EXISTING_EVALUATION"):
        append_entity(truth, task, release_id="RC7")


def test_r1_rejects_resolved_gap_without_resolution_evaluation(tmp_path) -> None:
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    gap = Gap(
        gap_id="GAP-BYPASS",
        mission_id="MISSION-1",
        source_node="TEST_DESIGN",
        category="UNCOVERED_REQUIREMENT",
        severity=GapSeverity.CRITICAL,
        target_node="TEST_DESIGN",
        description="Try to bypass reevaluation",
        state=GapStatus.RESOLVED,
    )

    with pytest.raises(EventValidationError, match="DURABLE_PASS_REQUIRES_EXISTING_EVALUATION"):
        append_entity(truth, gap, release_id="RC7")


def test_r1_rejects_converged_mission_without_sufficiency_evaluation(tmp_path) -> None:
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    mission = Mission(
        mission_id="MISSION-BYPASS",
        release_id="RC7",
        goal="Try to bypass Mission sufficiency",
        state=MissionStatus.CONVERGED,
        sufficiency_state="UNKNOWN",
    )

    with pytest.raises(EventValidationError, match="DURABLE_PASS_REQUIRES_EXISTING_EVALUATION"):
        append_entity(truth, mission, release_id="RC7")


def test_r1_rejects_fake_or_self_evaluation_authority(tmp_path) -> None:
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    fake = Task(
        task_id="TASK-FAKE-EVAL",
        mission_id="MISSION-1",
        node="TEST_DESIGN",
        task_type="PRODUCE",
        objective="fake evaluator id",
        state=TaskStatus.PASS,
        evaluation_id="EVAL-DOES-NOT-EXIST",
    )
    with pytest.raises(EventValidationError, match="DURABLE_PASS_REQUIRES_EXISTING_EVALUATION"):
        append_entity(truth, fake, release_id="RC7")

    self_eval = Evaluation(
        evaluation_id="EVAL-SELF",
        mission_id="MISSION-1",
        node="TEST_DESIGN",
        artifact_refs=["ART-SELF"],
        result=EvaluationResult.PASS,
        evaluator_ref="worker-self",
    )
    append_entity(truth, self_eval, release_id="RC7")
    self_task = Task(
        task_id="TASK-SELF",
        mission_id="MISSION-1",
        node="TEST_DESIGN",
        task_type="PRODUCE",
        objective="worker cannot accept own output",
        state=TaskStatus.PASS,
        lease_owner="worker-self",
        output_artifact_refs=["ART-SELF"],
        evaluation_id=self_eval.evaluation_id,
    )
    with pytest.raises(EventValidationError, match="WORKER_SELF_EVALUATION_FORBIDDEN"):
        append_entity(truth, self_task, release_id="RC7")


def test_r1_rejects_converged_mission_when_projection_still_has_active_task(tmp_path) -> None:
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    evaluation = Evaluation(
        evaluation_id="EVAL-MISSION-PROJECTION-BYPASS",
        mission_id="MISSION-PROJECTION-BYPASS",
        node="MISSION_EVALUATION",
        artifact_refs=["SNAPSHOT-PROJECTION"],
        result=EvaluationResult.PASS,
        evaluator_ref="mission-sufficiency-gate",
        dimensions={"sufficiency_state": "SUFFICIENT"},
    )
    append_entity(truth, evaluation, release_id="RC7")
    append_entity(
        truth,
        Task(
            task_id="TASK-STILL-READY",
            mission_id="MISSION-PROJECTION-BYPASS",
            node="EXECUTION",
            task_type="PRODUCE",
            objective="still pending despite mission object claiming no active tasks",
            state=TaskStatus.READY,
        ),
        release_id="RC7",
    )
    mission = Mission(
        mission_id="MISSION-PROJECTION-BYPASS",
        release_id="RC7",
        goal="cannot lie about projection state",
        state=MissionStatus.CONVERGED,
        sufficiency_state="SUFFICIENT",
        active_task_ids=[],
        open_gap_ids=[],
        latest_evaluation_id=evaluation.evaluation_id,
    )
    with pytest.raises(EventValidationError, match="CONVERGED_MISSION_HAS_ACTIVE_TASK_PROJECTION"):
        append_entity(truth, mission, release_id="RC7")


def test_r1_rejects_product_gap_resolution_without_terminal_defect_record(tmp_path) -> None:
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    evaluation = Evaluation(
        evaluation_id="EVAL-DEFECT-FAKE-CLOSED",
        mission_id="MISSION-1",
        node="DEFECT",
        artifact_refs=["ART-DEFECT-FAKE"],
        result=EvaluationResult.PASS,
        evaluator_ref="evaluator-defect-independent",
        dimensions={"defect_id": "DEFECT-NOT-PERSISTED", "defect_state": "CLOSED"},
    )
    append_entity(truth, evaluation, release_id="RC7")
    gap = Gap(
        gap_id="GAP-PRODUCT-FAKE-CLOSED",
        mission_id="MISSION-1",
        source_node="EXECUTION",
        category="PRODUCT_DEFECT",
        severity=GapSeverity.HIGH,
        target_node="DEFECT",
        description="must not close from evaluation dimensions alone",
        state=GapStatus.RESOLVED,
        resolution_evaluation_id=evaluation.evaluation_id,
    )
    with pytest.raises(EventValidationError, match="PRODUCT_DEFECT_RESOLUTION_REQUIRES_TERMINAL_DEFECT_RECORD"):
        append_entity(truth, gap, release_id="RC7")


def test_r1_accepts_terminal_control_truth_with_evaluation_authority(tmp_path) -> None:
    truth = TruthRuntime(tmp_path / "r1.jsonl")

    task_eval = Evaluation(
        evaluation_id="EVAL-TASK-1",
        mission_id="MISSION-1",
        node="TEST_DESIGN",
        artifact_refs=["ART-TASK-1"],
        result=EvaluationResult.PASS,
        evaluator_ref="evaluator-test-design",
    )
    gap_eval = Evaluation(
        evaluation_id="EVAL-GAP-1",
        mission_id="MISSION-1",
        node="TEST_DESIGN",
        artifact_refs=["ART-TASK-1"],
        result=EvaluationResult.PASS,
        evaluator_ref="evaluator-test-design-recheck",
    )
    mission_eval = Evaluation(
        evaluation_id="EVAL-MISSION-1",
        mission_id="MISSION-1",
        node="MISSION_EVALUATION",
        artifact_refs=["SNAPSHOT-1"],
        result=EvaluationResult.PASS,
        evaluator_ref="mission-sufficiency-gate",
        dimensions={"sufficiency_state": "SUFFICIENT"},
    )
    for evaluation in (task_eval, gap_eval, mission_eval):
        receipt = append_entity(truth, evaluation, release_id="RC7")
        assert receipt.status == "PERSISTENCE_VERIFIED"

    task = Task(
        task_id="TASK-ACCEPTED",
        mission_id="MISSION-1",
        node="TEST_DESIGN",
        task_type="PRODUCE",
        objective="Accepted after evaluation",
        state=TaskStatus.PASS,
        output_artifact_refs=["ART-TASK-1"],
        evaluation_id=task_eval.evaluation_id,
    )
    gap = Gap(
        gap_id="GAP-ACCEPTED",
        mission_id="MISSION-1",
        source_node="TEST_DESIGN",
        category="UNCOVERED_REQUIREMENT",
        severity=GapSeverity.HIGH,
        target_node="TEST_DESIGN",
        description="Closed after reevaluation",
        state=GapStatus.RESOLVED,
        resolution_evaluation_id=gap_eval.evaluation_id,
    )
    mission = Mission(
        mission_id="MISSION-1",
        release_id="RC7",
        goal="Converged after sufficiency evaluation",
        state=MissionStatus.CONVERGED,
        sufficiency_state="SUFFICIENT",
        latest_evaluation_id=mission_eval.evaluation_id,
    )

    for entity in (task, gap, mission):
        receipt = append_entity(truth, entity, release_id="RC7")
        assert receipt.status == "PERSISTENCE_VERIFIED"

    assert truth.query("rc7_task", task_id=task.task_id)[0]["evaluation_id"] == "EVAL-TASK-1"
    assert truth.query("rc7_gap", gap_id=gap.gap_id)[0]["resolution_evaluation_id"] == "EVAL-GAP-1"
    assert truth.query("rc7_mission", mission_id=mission.mission_id)[0]["latest_evaluation_id"] == "EVAL-MISSION-1"
