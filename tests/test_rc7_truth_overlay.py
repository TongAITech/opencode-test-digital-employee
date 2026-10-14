from __future__ import annotations

from pathlib import Path

from rc6_runtime.truth import TruthRuntime
from rc7_runtime import (
    Artifact,
    Evaluation,
    EvaluationResult,
    EventRecord,
    Evidence,
    Gap,
    GapSeverity,
    Mission,
    Task,
)
from rc7_runtime.truth_overlay import append_entity


def test_rc7_control_entities_share_r1_append_replay_projection(tmp_path: Path) -> None:
    event_path = tmp_path / "r1-events.jsonl"
    truth = TruthRuntime(event_path)

    mission = Mission(
        mission_id="M-RC7-1",
        release_id="RC7",
        goal="Closed-loop qualification",
    )
    task = Task(
        task_id="T-RC7-1",
        mission_id=mission.mission_id,
        node="REQUIREMENT_ANALYSIS",
        task_type="PRODUCE",
        objective="Produce requirement candidate",
    )
    evidence = Evidence(
        evidence_id="EVD-RC7-1",
        mission_id=mission.mission_id,
        kind="SOURCE_DOCUMENT",
        source_ref="sst://STB-1",
        content_ref="evidence://STB-1/hash",
        subject_refs=["REQ-1"],
    )
    artifact = Artifact(
        artifact_id="ART-RC7-1",
        mission_id=mission.mission_id,
        artifact_type="REQUIREMENT_MODEL",
        producer_task_id=task.task_id,
        content_ref="artifact://requirements/v1",
        evidence_refs=[evidence.evidence_id],
    )
    gap = Gap(
        gap_id="GAP-RC7-1",
        mission_id=mission.mission_id,
        source_node="REQUIREMENT_ANALYSIS",
        category="MISSING_BOUNDARY",
        severity=GapSeverity.CRITICAL,
        target_node="REQUIREMENT_ANALYSIS",
        description="Boundary semantics are not evidenced",
        evidence_refs=[evidence.evidence_id],
    )
    evaluation = Evaluation(
        evaluation_id="EVAL-RC7-1",
        mission_id=mission.mission_id,
        node="REQUIREMENT_ANALYSIS",
        artifact_refs=[artifact.artifact_id],
        result=EvaluationResult.REPAIR_REQUIRED,
        evaluator_ref="independent-requirement-evaluator",
        dimensions={"boundary": {"gate": "FAIL"}},
        gap_refs=[gap.gap_id],
        evidence_refs=[evidence.evidence_id],
    )
    event = EventRecord(
        event_id="EV-RC7-1",
        mission_id=mission.mission_id,
        event_type="RC7_REQUIREMENT_GAP_OPENED",
        subject_type="GAP",
        subject_id=gap.gap_id,
        refs=[evaluation.evaluation_id],
        data={"severity": "CRITICAL"},
    )

    for entity in (mission, task, evidence, artifact, gap, evaluation, event):
        receipt = append_entity(truth, entity, release_id="RC7")
        assert receipt.status == "PERSISTENCE_VERIFIED"
        assert receipt.persisted_count == 1
        assert receipt.queryable_count == 1

    assert truth.query("rc7_mission", mission_id=mission.mission_id)[0]["goal"] == mission.goal
    assert truth.query("rc7_task", mission_id=mission.mission_id)[0]["task_id"] == task.task_id
    assert truth.query("rc7_gap", mission_id=mission.mission_id)[0]["gap_id"] == gap.gap_id
    assert truth.query("rc7_evaluation", mission_id=mission.mission_id)[0]["result"] == "REPAIR_REQUIRED"

    # A fresh runtime must derive the same state exclusively from the JSONL
    # event stream; no RC7 shadow store is allowed.
    replayed = TruthRuntime(event_path)
    assert replayed.query("rc7_mission", mission_id=mission.mission_id)[0]["mission_id"] == mission.mission_id
    assert replayed.query("rc7_artifact", mission_id=mission.mission_id)[0]["artifact_type_name"] == "REQUIREMENT_MODEL"
    assert replayed.query("rc7_control_event", mission_id=mission.mission_id)[0]["event_type_name"] == "RC7_REQUIREMENT_GAP_OPENED"
