from __future__ import annotations

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.bank_mission import start_or_resume
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.control_plane import WorkerOutput
from rc7_runtime.mission_autonomous_driver import (
    MissionAutonomousDriver,
    MissionAutonomousDriverError,
)
from rc7_runtime.mission_stage_dispatch import MissionStageDispatcher
from rc7_runtime.models import (
    Artifact,
    Evaluation,
    EvaluationResult,
    Evidence,
    Gap,
    GapSeverity,
)
from rc7_runtime.reality_recon import RuntimeRealityReconService


MISSION = "MISSION-AUTONOMY"
RELEASE = "REL-AUTONOMY"
COMMIT = "a" * 40


def _bootstrap(monkeypatch, tmp_path):
    monkeypatch.setenv("PFC_RC7_SOURCE_COMMIT", COMMIT)
    r1 = tmp_path / "runtime-state" / "r1" / "event-stream.jsonl"
    start_or_resume(
        r1_path=str(r1),
        mission_id=MISSION,
        release_id=RELEASE,
        goal="prove bounded autonomous mission control",
        graph_version="v2",
    )
    truth = TruthRuntime(r1)
    control = ClosedLoopControlPlane(truth, RELEASE, MISSION)
    return r1, control


def _reality_handler(control, tmp_path):
    service = RuntimeRealityReconService(evidence_root=str(tmp_path / "reality-evidence"))

    def run(task):
        return service.reconcile(
            control,
            task.task_id,
            facts={
                "release_id": RELEASE,
                "source_revision": "commit:" + COMMIT,
                "repository_ref": "repo://TongAITech/opencode-test-digital-employee",
                "runtime_profile": "BANK_PROTECTED",
            },
            evidence_refs=("git://source/%s" % COMMIT, "runtime://profile/bank-protected"),
        )

    return run


def _requirement_producer(control):
    def run():
        task = control.lease_next(
            worker_ref="worker-requirement",
            capabilities=("requirement_reasoning",),
        )
        assert task is not None
        assert task.node == "REQUIREMENT_ANALYSIS"
        control.start(task.task_id, worker_ref="worker-requirement")
        evidence = Evidence(
            evidence_id="EVD-REQ-AUTONOMY",
            mission_id=MISSION,
            kind="REQUIREMENT_SOURCE",
            source_ref="worker://requirement",
            content_ref="memory://requirement-source",
            subject_refs=[task.task_id],
        )
        artifact = Artifact(
            artifact_id="ART-REQ-AUTONOMY",
            mission_id=MISSION,
            artifact_type="REQUIREMENT_MODEL",
            producer_task_id=task.task_id,
            content_ref="memory://requirement-candidate",
            evidence_refs=[evidence.evidence_id],
        )
        return control.submit_worker_output(
            WorkerOutput(
                task_id=task.task_id,
                worker_ref="worker-requirement",
                artifacts=(artifact,),
                evidence=(evidence,),
            )
        )

    return run


def _human_reviewer(control):
    def evaluate(task):
        assert task.node == "REQUIREMENT_ANALYSIS"
        gap = Gap(
            gap_id="GAP-HUMAN-AUTONOMY",
            mission_id=MISSION,
            source_node="REQUIREMENT_ANALYSIS",
            category="RESIDUAL_RISK_REQUIRES_ACCEPTANCE",
            severity=GapSeverity.HIGH,
            target_node="HUMAN_GATE",
            description="business owner acceptance required",
            subject_refs=list(task.output_artifact_refs),
            acceptance_criteria=["authorized human accepts residual risk"],
        )
        evaluation = Evaluation(
            evaluation_id="EVAL-REQ-HUMAN-AUTONOMY",
            mission_id=MISSION,
            node="REQUIREMENT_ANALYSIS",
            artifact_refs=list(task.output_artifact_refs),
            result=EvaluationResult.HUMAN_REQUIRED,
            evaluator_ref="independent-requirement-reviewer",
            gap_refs=[gap.gap_id],
        )
        return control.accept_evaluation(task.task_id, evaluation=evaluation, gaps=(gap,))

    return evaluate


def test_driver_runs_runtime_then_worker_then_independent_evaluator_and_stops_at_human(monkeypatch, tmp_path) -> None:
    _, control = _bootstrap(monkeypatch, tmp_path)
    dispatcher = MissionStageDispatcher(
        control,
        runtime_handlers={"REALITY_RECON": _reality_handler(control, tmp_path)},
        producer_runner=_requirement_producer(control),
    )
    driver = MissionAutonomousDriver(
        control,
        dispatcher,
        output_evaluators={"REQUIREMENT_ANALYSIS": _human_reviewer(control)},
    )

    result = driver.drive(max_steps=10)

    assert result.status == "HUMAN_REQUIRED"
    assert result.step_count == 3
    assert result.action == "WAIT_FOR_HUMAN_GATE"
    requirement = [
        row for row in control.truth.query("rc7_task", mission_id=MISSION)
        if row.get("node") == "REQUIREMENT_ANALYSIS" and row.get("task_type") == "PRODUCE"
    ][0]
    assert requirement["state"] == "HUMAN_REQUIRED"
    assert requirement["lease_owner"] == "worker-requirement"
    assert requirement["evaluation_id"] == "EVAL-REQ-HUMAN-AUTONOMY"
    assert control.truth.query("rc7_evaluation", evaluation_id="EVAL-REQ-HUMAN-AUTONOMY")[0]["evaluator_ref"] != requirement["lease_owner"]


def test_driver_rejects_success_looking_producer_that_does_not_change_r1(monkeypatch, tmp_path) -> None:
    _, control = _bootstrap(monkeypatch, tmp_path)
    dispatcher = MissionStageDispatcher(
        control,
        runtime_handlers={"REALITY_RECON": _reality_handler(control, tmp_path)},
        producer_runner=lambda: {"status": "PASS"},
    )
    driver = MissionAutonomousDriver(control, dispatcher)

    first = driver.step()
    assert first.status == "PROGRESSED"
    assert first.node == "REALITY_RECON"

    with pytest.raises(MissionAutonomousDriverError, match="DISPATCH_NO_DURABLE_PROGRESS"):
        driver.step()


def test_driver_requires_independent_evaluator_for_output_produced(monkeypatch, tmp_path) -> None:
    _, control = _bootstrap(monkeypatch, tmp_path)
    dispatcher = MissionStageDispatcher(
        control,
        runtime_handlers={"REALITY_RECON": _reality_handler(control, tmp_path)},
        producer_runner=_requirement_producer(control),
    )
    driver = MissionAutonomousDriver(control, dispatcher)

    assert driver.step().node == "REALITY_RECON"
    produced = driver.step()
    assert produced.node == "REQUIREMENT_ANALYSIS"
    assert control.scheduler.task(produced.task_id).state.value == "OUTPUT_PRODUCED"

    with pytest.raises(MissionAutonomousDriverError, match="OUTPUT_EVALUATOR_REQUIRED"):
        driver.step()


def test_driver_recreates_from_r1_without_private_progress_state(monkeypatch, tmp_path) -> None:
    r1, control_a = _bootstrap(monkeypatch, tmp_path)
    dispatcher_a = MissionStageDispatcher(
        control_a,
        runtime_handlers={"REALITY_RECON": _reality_handler(control_a, tmp_path)},
        producer_runner=lambda: None,
    )
    driver_a = MissionAutonomousDriver(control_a, dispatcher_a)
    assert driver_a.step().node == "REALITY_RECON"

    # Simulate a new process/session: reconstruct every controller from R1 only.
    control_b = ClosedLoopControlPlane(TruthRuntime(r1), RELEASE, MISSION)
    dispatcher_b = MissionStageDispatcher(
        control_b,
        runtime_handlers={"REALITY_RECON": _reality_handler(control_b, tmp_path)},
        producer_runner=_requirement_producer(control_b),
    )
    driver_b = MissionAutonomousDriver(control_b, dispatcher_b)

    route = dispatcher_b.next_route()
    assert route is not None
    assert route.node == "REQUIREMENT_ANALYSIS"
    progressed = driver_b.step()
    assert progressed.node == "REQUIREMENT_ANALYSIS"
    assert control_b.scheduler.task(progressed.task_id).state.value == "OUTPUT_PRODUCED"
