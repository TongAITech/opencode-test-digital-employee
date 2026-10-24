from __future__ import annotations

from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.autonomous_wave_e_nodes import (
    WaveENodeAdoptionControl,
    WaveENodeClosureError,
    WaveENodeClosureService,
)
from rc7_runtime.case_runtime import PREPARED_ATTEMPT_KIND
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.control_plane import WorkerOutput
from rc7_runtime.execution_recovery_conformance import persist_contract as persist_recovery_contract
from rc7_runtime.models import (
    Artifact,
    Evaluation,
    EvaluationResult,
    Evidence,
    Gap,
    GapSeverity,
    Mission,
    Task,
)
from rc7_runtime.node_tool_conformance import persist_contract as persist_node_tool_contract, record_successful_call
from rc7_runtime.truth_overlay import append_entity


MISSION = "MISSION-WAVE-E-CLOSURE"
RELEASE = "RC7.1-WAVE-E"
EXEC_TASK = "TASK-WAVE-E-EXECUTION"
EXEC_WORKER = "WORKER-WAVE-E-EXECUTION"


def _control(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(
            mission_id=MISSION,
            release_id=RELEASE,
            goal="prove N8 N9 node closure uses durable independent conformance",
        ),
    )
    return truth, control


def _closed_execution(tmp_path: Path):
    truth, control = _control(tmp_path)
    control.register_task(
        Task(
            task_id=EXEC_TASK,
            mission_id=MISSION,
            node="EXECUTION",
            task_type="PRODUCE",
            objective="execute a real canonical case",
            required_capabilities=["test_execution"],
        )
    )
    leased = control.lease_next(worker_ref=EXEC_WORKER, capabilities=("test_execution",))
    assert leased is not None and leased.task_id == EXEC_TASK
    control.start(EXEC_TASK, worker_ref=EXEC_WORKER)
    persist_node_tool_contract(
        truth,
        mission_id=MISSION,
        release_id=RELEASE,
        task_ids=[EXEC_TASK],
    )
    persist_recovery_contract(
        truth,
        mission_id=MISSION,
        release_id=RELEASE,
        execution_task_id=EXEC_TASK,
    )

    attempt_id = "ATTEMPT-WAVE-E-PASS"
    append_entity(
        truth,
        Evidence(
            evidence_id="EVD-PREP-WAVE-E",
            mission_id=MISSION,
            kind=PREPARED_ATTEMPT_KIND,
            source_ref="runtime://case-runtime/preparation",
            content_ref="state://case-runtime/wave-e/prepared-attempt.json",
            subject_refs=[EXEC_TASK, EXEC_WORKER, attempt_id, "TC-WAVE-E", "TARGET-1"],
            content_hash="a" * 64,
        ),
        release_id=RELEASE,
    )
    truth.append_atomic(
        "EXECUTION_ATTEMPT_UPSERTED",
        {
            "attempt_id": attempt_id,
            "release_id": RELEASE,
            "requirement_id": "REQ-WAVE-E",
            "tc_id": "TC-WAVE-E",
            "case_version": 1,
            "target_id": "TARGET-1",
            "layer": "L2",
            "status": "PASS",
            "actual_result": {"status": "PASS"},
            "tool_call_refs": ["tool://runner/wave-e"],
            "evidence_refs": ["evidence://runner/wave-e"],
        },
    )
    truth.append_atomic(
        "EXECUTION_CONVERGENCE_UPSERTED",
        {
            "convergence_id": "CONV-WAVE-E",
            "release_id": RELEASE,
            "attempt_id": attempt_id,
            "status": "PASS",
            "reason": "trusted execution pass",
            "evidence_refs": ["evidence://convergence/wave-e"],
        },
    )
    record_successful_call(
        truth,
        mission_id=MISSION,
        task_id=EXEC_TASK,
        worker_id=EXEC_WORKER,
        tool_name="runner_execute",
        result={"tool": "runner_execute", "status": "PASS"},
    )
    record_successful_call(
        truth,
        mission_id=MISSION,
        task_id=EXEC_TASK,
        worker_id=EXEC_WORKER,
        tool_name="execution_convergence",
        result={"tool": "execution_convergence", "status": "PASS"},
    )

    output_evidence = Evidence(
        evidence_id="EVD-EXEC-OUTPUT-WAVE-E",
        mission_id=MISSION,
        kind="RUNTIME_EXECUTION_RECORD",
        source_ref="runtime://formal-execution",
        content_ref="evidence://execution/wave-e",
        subject_refs=[EXEC_TASK, attempt_id, "TC-WAVE-E"],
    )
    output_artifact = Artifact(
        artifact_id="ART-EXEC-OUTPUT-WAVE-E",
        mission_id=MISSION,
        artifact_type="EXECUTION_CONCLUSION",
        producer_task_id=EXEC_TASK,
        content_ref="artifact://execution/wave-e",
        evidence_refs=[output_evidence.evidence_id],
    )
    control.submit_worker_output(
        WorkerOutput(
            task_id=EXEC_TASK,
            worker_ref=EXEC_WORKER,
            artifacts=(output_artifact,),
            evidence=(output_evidence,),
        )
    )
    evaluation = Evaluation(
        evaluation_id="EVAL-EXEC-WAVE-E-PASS",
        mission_id=MISSION,
        node="EXECUTION",
        artifact_refs=[output_artifact.artifact_id],
        result=EvaluationResult.PASS,
        evaluator_ref="rc7-runtime-owned-execution-gate",
        dimensions={"test_result": "PASS", "conclusive": True, "attempt_id": attempt_id},
        evidence_refs=[output_evidence.evidence_id],
    )
    accepted = control.accept_evaluation(EXEC_TASK, evaluation=evaluation)
    assert accepted.state.value == "PASS"
    return truth, control


def test_n8_replays_execution_recovery_truth_then_requires_director_accept(tmp_path: Path):
    truth, control = _closed_execution(tmp_path)
    service = WaveENodeClosureService(evidence_root=str(tmp_path / "wave-e"))
    delivery = service.publish_n8_ready(control, run_id="RUN-WAVE-E")
    assert delivery.node_id == "N8"
    package = truth.query("rc7_artifact", artifact_id=delivery.package_artifact_id)[0]
    assert package["artifact_type_name"] == "NODE_DELIVERY_PACKAGE"

    adoption = WaveENodeAdoptionControl(
        truth,
        release_id=RELEASE,
        evidence_root=str(tmp_path / "wave-e"),
    )
    decision = adoption.director_accept(
        mission_id=MISSION,
        run_id="RUN-WAVE-E",
        node_id="N8",
        director_ref="director-wave-e",
    )
    assert decision.accepted is True
    terminal = truth.query("rc7_control_event", event_id=decision.terminal_event_id)[0]
    assert terminal["data"]["state"] == "PASS"


def test_n9_not_triggered_is_explicit_converged_node_not_fake_defect_pass(tmp_path: Path):
    truth, control = _control(tmp_path)
    service = WaveENodeClosureService(evidence_root=str(tmp_path / "wave-e"))
    delivery = service.publish_n9_ready(control, run_id="RUN-N9-CLEAN")
    aggregate = [
        row
        for row in truth.query("rc7_task", mission_id=MISSION)
        if row.get("task_type") == "N9_CONVERGENCE"
    ]
    assert len(aggregate) == 1
    assert aggregate[0]["state"] == "PASS"
    evaluation = truth.query("rc7_evaluation", evaluation_id=aggregate[0]["evaluation_id"])[0]
    assert evaluation["dimensions"]["triggered"] is False

    adoption = WaveENodeAdoptionControl(
        truth,
        release_id=RELEASE,
        evidence_root=str(tmp_path / "wave-e"),
    )
    decision = adoption.director_accept(
        mission_id=MISSION,
        run_id="RUN-N9-CLEAN",
        node_id="N9",
        director_ref="director-n9-clean",
    )
    assert decision.accepted is True
    assert delivery.node_id == "N9"


def test_n9_refuses_delivery_while_product_gap_has_no_terminal_disposition(tmp_path: Path):
    truth, control = _control(tmp_path)
    append_entity(
        truth,
        Gap(
            gap_id="GAP-UNRESOLVED-PRODUCT",
            mission_id=MISSION,
            source_node="EXECUTION",
            category="PRODUCT_DEFECT",
            severity=GapSeverity.HIGH,
            target_node="DEFECT",
            description="trusted product failure still awaiting defect disposition",
            subject_refs=["TC-UNRESOLVED", "ATT-UNRESOLVED"],
            evidence_refs=["EVD-UNRESOLVED"],
            acceptance_criteria=["terminal independently reviewed defect disposition"],
        ),
        release_id=RELEASE,
    )
    with pytest.raises(WaveENodeClosureError, match="N9_DEFECT_REVIEW_CONFORMANCE_FAILED"):
        WaveENodeClosureService(evidence_root=str(tmp_path / "wave-e")).publish_n9_ready(
            control,
            run_id="RUN-N9-BLOCKED",
        )
    assert not [
        row
        for row in truth.query("rc7_task", mission_id=MISSION)
        if row.get("task_type") == "N9_CONVERGENCE"
    ]
