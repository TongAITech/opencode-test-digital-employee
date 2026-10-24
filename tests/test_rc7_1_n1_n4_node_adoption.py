from __future__ import annotations

from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.autonomous_node_adoption import (
    AutonomousNodeAdoptionControl,
    AutonomousNodeAdoptionError,
)
from rc7_runtime.models import (
    Artifact,
    Evaluation,
    EvaluationResult,
    Evidence,
    Mission,
    Task,
    TaskStatus,
)
from rc7_runtime.truth_overlay import append_entity


RELEASE = "RC7.1-WAVE-B"
MISSION = "MISSION-RC7-1-WAVE-B"


@pytest.fixture()
def truth(tmp_path: Path) -> TruthRuntime:
    runtime = TruthRuntime(tmp_path / "runtime-state" / "r1" / "event-stream.jsonl")
    append_entity(
        runtime,
        Mission(mission_id=MISSION, release_id=RELEASE, goal="prove N1-N4 director-gated adoption"),
        release_id=RELEASE,
    )
    return runtime


def _seed_passed_subtask(truth: TruthRuntime, *, node_id: str, source_node: str, suffix: str):
    task_id = "TASK-%s-%s" % (node_id, suffix)
    artifact_id = "ART-%s-%s" % (node_id, suffix)
    evidence_id = "EVD-%s-%s" % (node_id, suffix)
    evaluation_id = "EVAL-%s-%s" % (node_id, suffix)
    producer = "specialist-%s" % node_id.lower()
    reviewer = "independent-reviewer-%s" % node_id.lower()

    # Durable truth already forbids a PASS Task whose independent PASS
    # evaluation does not exist. Seed proof -> artifact -> evaluation -> PASS
    # task in the same order the production control plane must respect.
    evidence = Evidence(
        evidence_id=evidence_id,
        mission_id=MISSION,
        kind="%s_SUFFICIENCY_PROOF" % source_node,
        source_ref="runtime://independent-review",
        content_ref="runtime://proof/%s" % suffix,
        subject_refs=[task_id, artifact_id, evaluation_id],
    )
    append_entity(truth, evidence, release_id=RELEASE)
    artifact = Artifact(
        artifact_id=artifact_id,
        mission_id=MISSION,
        artifact_type="%s_MODEL" % source_node,
        producer_task_id=task_id,
        content_ref="runtime://artifact/%s" % suffix,
        evidence_refs=[evidence_id],
    )
    append_entity(truth, artifact, release_id=RELEASE)
    evaluation = Evaluation(
        evaluation_id=evaluation_id,
        mission_id=MISSION,
        node=source_node,
        artifact_refs=[artifact_id],
        result=EvaluationResult.PASS,
        evaluator_ref=reviewer,
        dimensions={"gate_status": "SUFFICIENT", "independent_review": True},
        gap_refs=[],
        evidence_refs=[evidence_id],
    )
    append_entity(truth, evaluation, release_id=RELEASE)
    task = Task(
        task_id=task_id,
        mission_id=MISSION,
        node=source_node,
        task_type="PRODUCE_AND_EVALUATE",
        objective="produce evaluated candidate for %s" % node_id,
        state=TaskStatus.PASS,
        lease_owner=producer,
        output_artifact_refs=[artifact_id],
        evaluation_id=evaluation_id,
    )
    append_entity(truth, task, release_id=RELEASE)
    return task, artifact, evidence, evaluation, producer, reviewer


@pytest.mark.parametrize(
    "node_id,source_node",
    [
        ("N2", "REQUIREMENT_ANALYSIS"),
        ("N3", "CODE_ANALYSIS"),
        ("N4", "TEST_DESIGN"),
    ],
)
def test_passed_specialist_subtask_is_not_node_pass_until_director_accepts(
    tmp_path: Path,
    truth: TruthRuntime,
    node_id: str,
    source_node: str,
) -> None:
    task, artifact, evidence, evaluation, producer, _reviewer = _seed_passed_subtask(
        truth, node_id=node_id, source_node=source_node, suffix=node_id.lower()
    )
    adoption = AutonomousNodeAdoptionControl(
        truth,
        release_id=RELEASE,
        evidence_root=str(tmp_path / "evidence"),
    )
    iteration = adoption.node_control.start_iteration(
        mission_id=MISSION,
        run_id="RUN-" + node_id,
        node_id=node_id,
        input_version="input-v1",
        delta_hash="sha256:delta-%s-v1" % node_id.lower(),
    )
    delivery = adoption.publish_ready_from_evaluated_task(
        iteration=iteration,
        source_task_id=task.task_id,
        source_evaluation_id=evaluation.evaluation_id,
        artifact_refs=(artifact.artifact_id,),
        evidence_refs=(evidence.evidence_id,),
        team_id="TEAM-" + node_id,
        assignment_ids=("ASSIGN-" + node_id,),
        member_ids=(producer,),
    )
    assert delivery.iteration_count == 1

    terminal_before = [
        row
        for row in truth.query("rc7_control_event", mission_id=MISSION)
        if row.get("event_type_name") == "NODE_TERMINAL"
        and row.get("data", {}).get("node_id") == node_id
    ]
    assert terminal_before == []

    decision = adoption.director_accept(
        mission_id=MISSION,
        run_id="RUN-" + node_id,
        node_id=node_id,
        director_ref="director-runtime-authority",
    )
    assert decision.accepted is True
    accepted = truth.query("rc7_evaluation", evaluation_id=decision.evaluation_id)
    assert len(accepted) == 1
    assert accepted[0]["node"] == "AUTONOMOUS_NODE_GATE"
    assert accepted[0]["result"] == "PASS"
    assert accepted[0]["evaluator_ref"] == "director-runtime-authority"

    terminal_after = [
        row
        for row in truth.query("rc7_control_event", mission_id=MISSION)
        if row.get("event_id") == decision.terminal_event_id
    ]
    assert len(terminal_after) == 1
    assert terminal_after[0]["data"]["state"] == "PASS"


def test_director_cannot_impersonate_specialist_or_source_reviewer(
    tmp_path: Path,
    truth: TruthRuntime,
) -> None:
    task, artifact, evidence, evaluation, producer, reviewer = _seed_passed_subtask(
        truth, node_id="N2", source_node="REQUIREMENT_ANALYSIS", suffix="self-review"
    )
    adoption = AutonomousNodeAdoptionControl(
        truth, release_id=RELEASE, evidence_root=str(tmp_path / "evidence")
    )
    iteration = adoption.node_control.start_iteration(
        mission_id=MISSION,
        run_id="RUN-SELF-REVIEW",
        node_id="N2",
        input_version="input-v1",
        delta_hash="sha256:self-review-v1",
    )
    adoption.publish_ready_from_evaluated_task(
        iteration=iteration,
        source_task_id=task.task_id,
        source_evaluation_id=evaluation.evaluation_id,
        artifact_refs=(artifact.artifact_id,),
        evidence_refs=(evidence.evidence_id,),
        member_ids=(producer,),
    )

    with pytest.raises(AutonomousNodeAdoptionError, match="DIRECTOR_SPECIALIST_SELF_APPROVAL_FORBIDDEN"):
        adoption.director_accept(
            mission_id=MISSION,
            run_id="RUN-SELF-REVIEW",
            node_id="N2",
            director_ref=producer,
        )
    with pytest.raises(AutonomousNodeAdoptionError, match="DIRECTOR_CANNOT_REUSE_SOURCE_EVALUATOR_IDENTITY"):
        adoption.director_accept(
            mission_id=MISSION,
            run_id="RUN-SELF-REVIEW",
            node_id="N2",
            director_ref=reviewer,
        )


def test_director_rejection_preserves_lineage_and_allows_only_delta_next_iteration(
    tmp_path: Path,
    truth: TruthRuntime,
) -> None:
    task, artifact, evidence, evaluation, producer, _reviewer = _seed_passed_subtask(
        truth, node_id="N3", source_node="CODE_ANALYSIS", suffix="reject"
    )
    adoption = AutonomousNodeAdoptionControl(
        truth, release_id=RELEASE, evidence_root=str(tmp_path / "evidence")
    )
    first = adoption.node_control.start_iteration(
        mission_id=MISSION,
        run_id="RUN-REJECT",
        node_id="N3",
        input_version="git:abc123",
        delta_hash="sha256:code-delta-v1",
    )
    adoption.publish_ready_from_evaluated_task(
        iteration=first,
        source_task_id=task.task_id,
        source_evaluation_id=evaluation.evaluation_id,
        artifact_refs=(artifact.artifact_id,),
        evidence_refs=(evidence.evidence_id,),
        member_ids=(producer,),
    )
    rejected = adoption.director_reject(
        mission_id=MISSION,
        run_id="RUN-REJECT",
        node_id="N3",
        director_ref="director-runtime-authority",
        reason="graph frontier evidence is current but the delivery omits a required impact summary",
        evidence_refs=(evidence.evidence_id,),
    )
    assert rejected.accepted is False

    with pytest.raises(Exception, match="ITERATION_MUST_PRODUCE_DELTA"):
        adoption.node_control.start_iteration(
            mission_id=MISSION,
            run_id="RUN-REJECT",
            node_id="N3",
            input_version="git:abc123",
            delta_hash="sha256:code-delta-v1",
        )

    second = adoption.node_control.start_iteration(
        mission_id=MISSION,
        run_id="RUN-REJECT",
        node_id="N3",
        input_version="git:abc123",
        delta_hash="sha256:code-delta-v2",
    )
    assert second.iteration_count == 2
    assert second.previous_iteration_event_id == first.start_event_id


def test_nonpass_source_task_cannot_publish_ready(
    tmp_path: Path,
    truth: TruthRuntime,
) -> None:
    _task, artifact, evidence, _evaluation, producer, _reviewer = _seed_passed_subtask(
        truth, node_id="N4", source_node="TEST_DESIGN", suffix="not-pass-base"
    )
    repair_eval = Evaluation(
        evaluation_id="EVAL-N4-REPAIR",
        mission_id=MISSION,
        node="TEST_DESIGN",
        artifact_refs=[artifact.artifact_id],
        result=EvaluationResult.REPAIR_REQUIRED,
        evaluator_ref="independent-reviewer-n4-repair",
        dimensions={"gate_status": "NOT_SUFFICIENT"},
        gap_refs=[],
        evidence_refs=[evidence.evidence_id],
    )
    append_entity(truth, repair_eval, release_id=RELEASE)
    repair_task = Task(
        task_id="TASK-N4-REPAIR",
        mission_id=MISSION,
        node="TEST_DESIGN",
        task_type="PRODUCE_AND_EVALUATE",
        objective="insufficient test design",
        state=TaskStatus.REPAIR_REQUIRED,
        lease_owner=producer,
        output_artifact_refs=[artifact.artifact_id],
        evaluation_id=repair_eval.evaluation_id,
    )
    append_entity(truth, repair_task, release_id=RELEASE)

    adoption = AutonomousNodeAdoptionControl(
        truth, release_id=RELEASE, evidence_root=str(tmp_path / "evidence")
    )
    iteration = adoption.node_control.start_iteration(
        mission_id=MISSION,
        run_id="RUN-NONPASS",
        node_id="N4",
        input_version="design-v1",
        delta_hash="sha256:design-v1",
    )
    with pytest.raises(AutonomousNodeAdoptionError, match="SOURCE_SUBTASK_PASS_REQUIRED"):
        adoption.publish_ready_from_evaluated_task(
            iteration=iteration,
            source_task_id=repair_task.task_id,
            source_evaluation_id=repair_eval.evaluation_id,
            artifact_refs=(artifact.artifact_id,),
            evidence_refs=(evidence.evidence_id,),
        )
