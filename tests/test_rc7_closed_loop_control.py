from __future__ import annotations

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime import (
    Artifact,
    Evaluation,
    EvaluationResult,
    Evidence,
    Gap,
    GapSeverity,
    Mission,
    MissionStatus,
    Task,
    TaskStatus,
)
from rc7_runtime.closed_loop_control import ClosedLoopControlError, ClosedLoopControlPlane
from rc7_runtime.control_plane import WorkerOutput


def _output(task_id: str, worker: str, artifact_id: str, evidence_id: str, mission_id: str = "MISSION-1") -> WorkerOutput:
    return WorkerOutput(
        task_id=task_id,
        worker_ref=worker,
        evidence=(
            Evidence(
                evidence_id=evidence_id,
                mission_id=mission_id,
                kind="RUNTIME_PROOF",
                source_ref="worker://%s" % worker,
                content_ref="evidence://%s" % evidence_id,
            ),
        ),
        artifacts=(
            Artifact(
                artifact_id=artifact_id,
                mission_id=mission_id,
                artifact_type="TEST_DESIGN_OUTPUT",
                producer_task_id=task_id,
                content_ref="artifact://%s" % artifact_id,
                evidence_refs=[evidence_id],
            ),
        ),
    )


def test_gap_repair_requires_source_reexecution_and_reevaluation_before_resolution(tmp_path) -> None:
    event_path = tmp_path / "r1.jsonl"
    truth = TruthRuntime(event_path)
    mission = Mission(
        mission_id="MISSION-1",
        release_id="RC7",
        goal="prove true repair loop",
    )
    control = ClosedLoopControlPlane.bootstrap(truth, mission)
    source = Task(
        task_id="TASK-DESIGN",
        mission_id="MISSION-1",
        node="TEST_DESIGN",
        task_type="PRODUCE",
        objective="produce sufficient design",
        required_capabilities=["test_design"],
    )
    control.register_task(source)

    leased = control.lease_next(worker_ref="worker-design-A", capabilities=["test_design"])
    assert leased is not None and leased.task_id == source.task_id
    control.start(source.task_id, worker_ref="worker-design-A")
    candidate = control.submit_worker_output(
        _output(source.task_id, "worker-design-A", "ART-DESIGN-V1", "EVD-DESIGN-V1")
    )
    assert candidate.state == TaskStatus.OUTPUT_PRODUCED

    gap = Gap(
        gap_id="GAP-DESIGN-BOUNDARY",
        mission_id="MISSION-1",
        source_node="TEST_DESIGN",
        category="UNCOVERED_BOUNDARY",
        severity=GapSeverity.CRITICAL,
        target_node="TEST_DESIGN",
        description="critical amount boundary is not covered",
        subject_refs=["OBL-BOUNDARY-1"],
        evidence_refs=["EVD-DESIGN-V1"],
        acceptance_criteria=["boundary obligation has executable case and oracle"],
    )
    rejected = Evaluation(
        evaluation_id="EVAL-DESIGN-V1",
        mission_id="MISSION-1",
        node="TEST_DESIGN",
        artifact_refs=["ART-DESIGN-V1"],
        result=EvaluationResult.REPAIR_REQUIRED,
        evaluator_ref="evaluator-design",
        gap_refs=[gap.gap_id],
        evidence_refs=["EVD-DESIGN-V1"],
    )
    control.accept_evaluation(source.task_id, evaluation=rejected, gaps=[gap])
    assert control.scheduler.task(source.task_id).state == TaskStatus.REPAIR_REQUIRED
    assert truth.query("rc7_gap", gap_id=gap.gap_id)[0]["state"] == "PLANNED"
    assert control.snapshot()["mission_state"] == "REPAIRING"

    # The routed repair work becomes executable, but its PASS is not allowed to
    # close the original Gap.
    control.refresh_ready()
    repair = control.lease_next(worker_ref="worker-repair-B", capabilities=["test_design"])
    assert repair is not None and repair.task_type == "REPAIR"
    assert truth.query("rc7_gap", gap_id=gap.gap_id)[0]["state"] == "REPAIRING"
    control.start(repair.task_id, worker_ref="worker-repair-B")
    repair_candidate = control.submit_worker_output(
        _output(repair.task_id, "worker-repair-B", "ART-REPAIR-1", "EVD-REPAIR-1")
    )
    repair_pass = Evaluation(
        evaluation_id="EVAL-REPAIR-1",
        mission_id="MISSION-1",
        node="TEST_DESIGN",
        artifact_refs=list(repair_candidate.output_artifact_refs),
        result=EvaluationResult.PASS,
        evaluator_ref="evaluator-repair",
        evidence_refs=["EVD-REPAIR-1"],
    )
    control.accept_evaluation(repair.task_id, evaluation=repair_pass)
    assert truth.query("rc7_gap", gap_id=gap.gap_id)[0]["state"] == "EVIDENCE_PENDING"
    assert control.scheduler.task(source.task_id).state == TaskStatus.READY

    # The source task must execute again and a source-node evaluator must PASS.
    source_retry = control.lease_next(worker_ref="worker-design-C", capabilities=["test_design"])
    assert source_retry is not None and source_retry.task_id == source.task_id
    control.start(source.task_id, worker_ref="worker-design-C")
    retry_candidate = control.submit_worker_output(
        _output(source.task_id, "worker-design-C", "ART-DESIGN-V2", "EVD-DESIGN-V2")
    )
    accepted = Evaluation(
        evaluation_id="EVAL-DESIGN-V2",
        mission_id="MISSION-1",
        node="TEST_DESIGN",
        artifact_refs=list(retry_candidate.output_artifact_refs),
        result=EvaluationResult.PASS,
        evaluator_ref="evaluator-design-recheck",
        evidence_refs=["EVD-DESIGN-V2"],
    )
    control.accept_evaluation(source.task_id, evaluation=accepted)
    assert control.scheduler.task(source.task_id).state == TaskStatus.PASS
    assert truth.query("rc7_gap", gap_id=gap.gap_id)[0]["state"] == "RESOLVED"
    assert control.snapshot()["open_gap_ids"] == []

    # Mission convergence is a separate independent sufficiency gate.
    mission_eval = Evaluation(
        evaluation_id="EVAL-MISSION-1",
        mission_id="MISSION-1",
        node="MISSION_EVALUATION",
        artifact_refs=["SNAPSHOT-MISSION-1"],
        result=EvaluationResult.PASS,
        evaluator_ref="mission-sufficiency-gate",
        dimensions={"sufficiency_state": "SUFFICIENT"},
        evidence_refs=["EVD-MISSION-SNAPSHOT"],
    )
    converged = control.converge_mission(mission_eval)
    assert converged.state == MissionStatus.CONVERGED

    # A brand-new process reconstructs the same control truth from R1 only.
    replay = TruthRuntime(event_path)
    recovered = ClosedLoopControlPlane(replay, "RC7", "MISSION-1")
    assert recovered.scheduler.task(source.task_id).state == TaskStatus.PASS
    assert replay.query("rc7_gap", gap_id=gap.gap_id)[0]["state"] == "RESOLVED"
    assert recovered.snapshot()["mission_state"] == "CONVERGED"


def test_worker_cannot_accept_own_candidate_even_with_real_evaluation_record(tmp_path) -> None:
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(mission_id="MISSION-1", release_id="RC7", goal="independent evaluation"),
    )
    task = Task(
        task_id="TASK-SELF",
        mission_id="MISSION-1",
        node="TEST_DESIGN",
        task_type="PRODUCE",
        objective="candidate",
        required_capabilities=["test_design"],
    )
    control.register_task(task)
    control.lease_next(worker_ref="same-agent", capabilities=["test_design"])
    control.start(task.task_id, worker_ref="same-agent")
    candidate = control.submit_worker_output(
        _output(task.task_id, "same-agent", "ART-SELF", "EVD-SELF")
    )
    self_eval = Evaluation(
        evaluation_id="EVAL-SELF-CONTROL",
        mission_id="MISSION-1",
        node="TEST_DESIGN",
        artifact_refs=list(candidate.output_artifact_refs),
        result=EvaluationResult.PASS,
        evaluator_ref="same-agent",
    )
    with pytest.raises(ClosedLoopControlError, match="WORKER_SELF_EVALUATION_FORBIDDEN"):
        control.accept_evaluation(task.task_id, evaluation=self_eval)
