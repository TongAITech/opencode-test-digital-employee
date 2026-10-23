from __future__ import annotations

from rc6_runtime.truth import TruthRuntime
from rc7_runtime import (
    Artifact,
    ClosedLoopControlPlane,
    Evaluation,
    EvaluationResult,
    Evidence,
    Gap,
    GapSeverity,
    Mission,
    Task,
    TaskStatus,
)
from rc7_runtime.control_plane import WorkerOutput
from rc7_runtime.gap_router import GapRouter


MISSION = "MISSION-RC71-SUFFICIENCY-CYCLE"
SOURCE_TASK = "TASK-RC71-DESIGN"
GAP_ID = "GAP-RC71-DENSITY"


def _output(task_id, worker, artifact_id, evidence_id):
    return WorkerOutput(
        task_id=task_id,
        worker_ref=worker,
        evidence=(
            Evidence(
                evidence_id=evidence_id,
                mission_id=MISSION,
                kind="TEST_DESIGN_PROOF",
                source_ref="worker://%s" % worker,
                content_ref="evidence://%s" % evidence_id,
                subject_refs=[task_id],
            ),
        ),
        artifacts=(
            Artifact(
                artifact_id=artifact_id,
                mission_id=MISSION,
                artifact_type="TEST_DESIGN_OUTPUT",
                producer_task_id=task_id,
                content_ref="artifact://%s" % artifact_id,
                evidence_refs=[evidence_id],
            ),
        ),
    )


def test_density_gap_repairs_reevaluates_and_resolves(tmp_path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(
            mission_id=MISSION,
            release_id="RC7.1",
            goal="prove sufficiency-v2 governed repair semantics",
        ),
    )
    source = Task(
        task_id=SOURCE_TASK,
        mission_id=MISSION,
        node="TEST_DESIGN",
        task_type="PRODUCE",
        objective="design sufficiently deep test set",
        required_capabilities=["test_design"],
    )
    control.register_task(source)

    # First design is produced but the new deterministic gate rejects the
    # shallow 100-obligation/20-case shape.
    leased = control.lease_next(worker_ref="designer-v1", capabilities=["test_design"])
    assert leased is not None and leased.task_id == SOURCE_TASK
    control.start(SOURCE_TASK, worker_ref="designer-v1")
    first = control.submit_worker_output(
        _output(SOURCE_TASK, "designer-v1", "ART-DESIGN-V1", "EVD-DESIGN-V1")
    )
    gap = Gap(
        gap_id=GAP_ID,
        mission_id=MISSION,
        source_node="TEST_DESIGN",
        category="TEST_CASE_DENSITY_INSUFFICIENT",
        severity=GapSeverity.HIGH,
        target_node="TEST_DESIGN",
        description="CASE_DENSITY_INSUFFICIENT:ALL:required=100:cases=20:min=25",
        subject_refs=["ART-DESIGN-V1", "OBL-001", "OBL-100"],
        evidence_refs=["EVD-DESIGN-V1"],
        acceptance_criteria=["RC7.1 sufficiency-v2 density/depth gates pass"],
    )
    route = GapRouter().route(gap)
    assert route.policy == "DETERMINISTIC"
    assert route.target_node == "TEST_DESIGN"
    rejected = Evaluation(
        evaluation_id="EVAL-DESIGN-V1",
        mission_id=MISSION,
        node="TEST_DESIGN",
        artifact_refs=list(first.output_artifact_refs),
        result=EvaluationResult.REPAIR_REQUIRED,
        evaluator_ref="independent-sufficiency-v2",
        dimensions={
            "test_design_sufficiency_v2_ready": False,
            "test_design_sufficiency_v2_reasons": [gap.description],
        },
        gap_refs=[GAP_ID],
        evidence_refs=["EVD-DESIGN-V1"],
    )
    control.accept_evaluation(SOURCE_TASK, evaluation=rejected, gaps=[gap])

    assert control.scheduler.task(SOURCE_TASK).state == TaskStatus.REPAIR_REQUIRED
    persisted_gap = truth.query("rc7_gap", gap_id=GAP_ID)[0]
    assert persisted_gap["state"] == "PLANNED"

    # The exact dynamic-dispatch path is covered separately against a canonical
    # Mission graph. This test isolates the governed Gap lifecycle so mission
    # conformance is never weakened merely to exercise a synthetic source task.
    control.refresh_ready()
    repair = control.lease_next(worker_ref="delta-designer", capabilities=["test_design"])
    assert repair is not None
    assert repair.task_type == "REPAIR"
    assert repair.node == "TEST_DESIGN"
    assert repair.gap_refs == [GAP_ID]
    control.start(repair.task_id, worker_ref="delta-designer")
    repair_candidate = control.submit_worker_output(
        _output(repair.task_id, "delta-designer", "ART-DESIGN-DELTA", "EVD-DESIGN-DELTA")
    )
    repair_pass = Evaluation(
        evaluation_id="EVAL-DESIGN-DELTA",
        mission_id=MISSION,
        node="TEST_DESIGN",
        artifact_refs=list(repair_candidate.output_artifact_refs),
        result=EvaluationResult.PASS,
        evaluator_ref="independent-delta-reviewer",
        dimensions={"delta_candidate_valid": True},
        evidence_refs=["EVD-DESIGN-DELTA"],
    )
    control.accept_evaluation(repair.task_id, evaluation=repair_pass)

    # Repair PASS is deliberately not resolution authority. It only advances
    # the original gap to EVIDENCE_PENDING and reactivates the source node.
    assert truth.query("rc7_gap", gap_id=GAP_ID)[0]["state"] == "EVIDENCE_PENDING"
    assert control.scheduler.task(SOURCE_TASK).state == TaskStatus.READY

    # The source design must be re-produced and independently re-evaluated.
    source_retry = control.lease_next(worker_ref="designer-v2", capabilities=["test_design"])
    assert source_retry is not None and source_retry.task_id == SOURCE_TASK
    control.start(SOURCE_TASK, worker_ref="designer-v2")
    second = control.submit_worker_output(
        _output(SOURCE_TASK, "designer-v2", "ART-DESIGN-V2", "EVD-DESIGN-V2")
    )
    accepted = Evaluation(
        evaluation_id="EVAL-DESIGN-V2",
        mission_id=MISSION,
        node="TEST_DESIGN",
        artifact_refs=list(second.output_artifact_refs),
        result=EvaluationResult.PASS,
        evaluator_ref="independent-sufficiency-v2-recheck",
        dimensions={
            "test_design_sufficiency_v2_ready": True,
            "test_design_sufficiency_v2_reasons": [],
            "case_count": 28,
            "required_subject_count": 100,
        },
        evidence_refs=["EVD-DESIGN-V2"],
    )
    control.accept_evaluation(SOURCE_TASK, evaluation=accepted)

    assert control.scheduler.task(SOURCE_TASK).state == TaskStatus.PASS
    resolved = truth.query("rc7_gap", gap_id=GAP_ID)[0]
    assert resolved["state"] == "RESOLVED"
    assert resolved["resolution_evaluation_id"] == "EVAL-DESIGN-V2"
    assert control.snapshot()["open_gap_ids"] == []

    # Restart/replay must retain the same closed-loop truth; chat/session state
    # is not needed to recover the repaired Mission state.
    replay = TruthRuntime(tmp_path / "r1.jsonl")
    recovered = ClosedLoopControlPlane(replay, "RC7.1", MISSION)
    assert recovered.scheduler.task(SOURCE_TASK).state == TaskStatus.PASS
    assert replay.query("rc7_gap", gap_id=GAP_ID)[0]["state"] == "RESOLVED"
