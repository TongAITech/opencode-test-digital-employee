from __future__ import annotations

from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.autonomous_contract import NodeDeliveryPackage
from rc7_runtime.autonomous_node_control import AutonomousNodeControl, AutonomousNodeControlError
from rc7_runtime.models import Artifact, Evidence, Gap, GapSeverity, Mission, Task
from rc7_runtime.truth_overlay import append_entity


RELEASE = "RC7.1-AUTONOMOUS-LOOP"
MISSION = "MISSION-AUTONOMOUS-NODE-CONTROL"
RUN = "RUN-001"


def _truth(tmp_path: Path) -> TruthRuntime:
    truth = TruthRuntime(tmp_path / "runtime-state" / "r1" / "event-stream.jsonl")
    if not truth.query("rc7_mission", mission_id=MISSION):
        append_entity(
            truth,
            Mission(mission_id=MISSION, release_id=RELEASE, goal="prove durable autonomous node control"),
            release_id=RELEASE,
        )
    return truth


def _seed_task_artifact_evidence(truth: TruthRuntime):
    task = Task(
        task_id="TASK-N2-001",
        mission_id=MISSION,
        node="REQUIREMENT_ANALYSIS",
        task_type="ANALYZE_REQUIREMENTS",
        objective="produce requirement analysis candidate",
    )
    append_entity(truth, task, release_id=RELEASE)
    evidence = Evidence(
        evidence_id="EVD-N2-001",
        mission_id=MISSION,
        kind="REQUIREMENT_SOURCE_PROOF",
        source_ref="runtime://test",
        content_ref="runtime://test/evidence",
        subject_refs=[task.task_id],
    )
    append_entity(truth, evidence, release_id=RELEASE)
    artifact = Artifact(
        artifact_id="ART-N2-001",
        mission_id=MISSION,
        artifact_type="REQUIREMENT_MODEL",
        producer_task_id=task.task_id,
        content_ref="runtime://test/artifact",
        evidence_refs=[evidence.evidence_id],
    )
    append_entity(truth, artifact, release_id=RELEASE)
    return task, artifact, evidence


def test_iteration_reconstructs_from_r1_after_controller_restart(tmp_path: Path) -> None:
    truth = _truth(tmp_path)
    first = AutonomousNodeControl(truth, release_id=RELEASE, evidence_root=str(tmp_path / "evidence"))
    started = first.start_iteration(
        mission_id=MISSION,
        run_id=RUN,
        node_id="N2",
        input_version="input-v1",
        delta_hash="sha256:delta-1",
    )
    assert started.iteration_count == 1

    restarted = AutonomousNodeControl(truth, release_id=RELEASE, evidence_root=str(tmp_path / "evidence"))
    recovered = restarted.latest_iteration(mission_id=MISSION, run_id=RUN, node_id="N2")
    assert recovered == started


def test_next_iteration_requires_durable_gap_or_repair_and_real_delta(tmp_path: Path) -> None:
    truth = _truth(tmp_path)
    control = AutonomousNodeControl(truth, release_id=RELEASE, evidence_root=str(tmp_path / "evidence"))
    first = control.start_iteration(
        mission_id=MISSION,
        run_id=RUN,
        node_id="N2",
        input_version="input-v1",
        delta_hash="sha256:delta-1",
    )

    with pytest.raises(AutonomousNodeControlError, match="NEXT_ITERATION_REQUIRES_DURABLE_REPAIR_OR_REJECTION"):
        control.start_iteration(
            mission_id=MISSION,
            run_id=RUN,
            node_id="N2",
            input_version="input-v1",
            delta_hash="sha256:delta-2",
        )

    evidence = Evidence(
        evidence_id="EVD-GAP-001",
        mission_id=MISSION,
        kind="REQUIREMENT_GAP_PROOF",
        source_ref="runtime://test",
        content_ref="runtime://test/gap-proof",
    )
    append_entity(truth, evidence, release_id=RELEASE)
    gap = Gap(
        gap_id="GAP-N2-001",
        mission_id=MISSION,
        source_node="REQUIREMENT_ANALYSIS",
        category="REQUIREMENT_REVIEW_GAP",
        severity=GapSeverity.HIGH,
        target_node="REQUIREMENT_ANALYSIS",
        description="missing source obligation",
        evidence_refs=[evidence.evidence_id],
    )
    append_entity(truth, gap, release_id=RELEASE)
    control.record_gap_detected(first, gap_ids=[gap.gap_id], evidence_refs=[evidence.evidence_id])

    with pytest.raises(AutonomousNodeControlError, match="ITERATION_MUST_PRODUCE_DELTA"):
        control.start_iteration(
            mission_id=MISSION,
            run_id=RUN,
            node_id="N2",
            input_version="input-v1",
            delta_hash="sha256:delta-1",
        )

    control.record_repair_completed(first, repair_refs=[gap.gap_id], delta_hash="sha256:repair-delta")
    second = control.start_iteration(
        mission_id=MISSION,
        run_id=RUN,
        node_id="N2",
        input_version="input-v1",
        delta_hash="sha256:delta-2",
    )
    assert second.iteration_count == 2
    assert second.previous_iteration_event_id == first.start_event_id


def test_node_delivery_is_immutable_r1_backed_and_restart_recoverable(tmp_path: Path) -> None:
    truth = _truth(tmp_path)
    task, artifact, evidence = _seed_task_artifact_evidence(truth)
    evidence_root = tmp_path / "evidence"
    control = AutonomousNodeControl(truth, release_id=RELEASE, evidence_root=str(evidence_root))
    iteration = control.start_iteration(
        mission_id=MISSION,
        run_id=RUN,
        node_id="N2",
        input_version="input-v1",
        delta_hash="sha256:delivery-delta",
    )
    package = NodeDeliveryPackage(
        mission_id=MISSION,
        run_id=RUN,
        node_id="N2",
        input_version="input-v1",
        iteration_count=1,
        artifact_refs=(artifact.artifact_id,),
        evidence_refs=(evidence.evidence_id,),
        unresolved_gap_ids=(),
        blocked_item_ids=(),
        terminal_status="READY_FOR_DIRECTOR_REVIEW",
        r1_refs=(iteration.start_event_id,),
        team_id="TEAM-N2",
        assignment_ids=("ASSIGN-N2",),
        member_ids=("MEMBER-N2",),
    )
    receipt = control.ready_for_director_review(iteration, package, producer_task_id=task.task_id)
    assert truth.query("rc7_artifact", artifact_id=receipt.package_artifact_id)
    evidence_rows = truth.query("rc7_evidence", evidence_id=receipt.package_evidence_id)
    assert len(evidence_rows) == 1
    path = Path(str(evidence_rows[0]["content_ref"])[len("file://"):])
    assert path.is_file()

    restarted = AutonomousNodeControl(truth, release_id=RELEASE, evidence_root=str(evidence_root))
    assert restarted.latest_delivery(mission_id=MISSION, run_id=RUN, node_id="N2") == receipt


def test_delivery_rejects_non_current_artifact_reference(tmp_path: Path) -> None:
    truth = _truth(tmp_path)
    task, _artifact, evidence = _seed_task_artifact_evidence(truth)
    control = AutonomousNodeControl(truth, release_id=RELEASE, evidence_root=str(tmp_path / "evidence"))
    iteration = control.start_iteration(
        mission_id=MISSION,
        run_id=RUN,
        node_id="N2",
        input_version="input-v1",
        delta_hash="sha256:delivery-delta",
    )
    package = NodeDeliveryPackage(
        mission_id=MISSION,
        run_id=RUN,
        node_id="N2",
        input_version="input-v1",
        iteration_count=1,
        artifact_refs=("ART-NOT-DURABLE",),
        evidence_refs=(evidence.evidence_id,),
        unresolved_gap_ids=(),
        blocked_item_ids=(),
        terminal_status="READY_FOR_DIRECTOR_REVIEW",
        r1_refs=(iteration.start_event_id,),
    )
    with pytest.raises(AutonomousNodeControlError, match="NODE_DELIVERY_ARTIFACT_NOT_CURRENT"):
        control.ready_for_director_review(iteration, package, producer_task_id=task.task_id)
