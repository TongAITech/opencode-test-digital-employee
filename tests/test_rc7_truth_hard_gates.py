from __future__ import annotations

import pytest

from rc6_runtime.truth import EventValidationError, TruthRuntime
from rc7_runtime import Gap, GapSeverity, GapStatus, Mission, MissionStatus, Task, TaskStatus
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

    with pytest.raises(EventValidationError, match="TASK_PASS_REQUIRES_EVALUATION"):
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

    with pytest.raises(EventValidationError, match="GAP_RESOLUTION_REQUIRES_EVALUATION"):
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

    with pytest.raises(EventValidationError, match="CONVERGED_MISSION_REQUIRES_SUFFICIENT_STATE"):
        append_entity(truth, mission, release_id="RC7")


def test_r1_accepts_terminal_control_truth_with_evaluation_authority(tmp_path) -> None:
    truth = TruthRuntime(tmp_path / "r1.jsonl")

    task = Task(
        task_id="TASK-ACCEPTED",
        mission_id="MISSION-1",
        node="TEST_DESIGN",
        task_type="PRODUCE",
        objective="Accepted after evaluation",
        state=TaskStatus.PASS,
        evaluation_id="EVAL-TASK-1",
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
        resolution_evaluation_id="EVAL-GAP-1",
    )
    mission = Mission(
        mission_id="MISSION-1",
        release_id="RC7",
        goal="Converged after sufficiency evaluation",
        state=MissionStatus.CONVERGED,
        sufficiency_state="SUFFICIENT",
        latest_evaluation_id="EVAL-MISSION-1",
    )

    for entity in (task, gap, mission):
        receipt = append_entity(truth, entity, release_id="RC7")
        assert receipt.status == "PERSISTENCE_VERIFIED"

    assert truth.query("rc7_task", task_id=task.task_id)[0]["evaluation_id"] == "EVAL-TASK-1"
    assert truth.query("rc7_gap", gap_id=gap.gap_id)[0]["resolution_evaluation_id"] == "EVAL-GAP-1"
    assert truth.query("rc7_mission", mission_id=mission.mission_id)[0]["latest_evaluation_id"] == "EVAL-MISSION-1"
