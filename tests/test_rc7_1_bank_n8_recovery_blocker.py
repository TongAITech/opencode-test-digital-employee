from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.bank_execution_autopilot import BankExecutionAutopilot
from rc7_runtime.bank_n8_recovery import BankN8RecoveryCoordinator, BankN8RecoveryError
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.control_plane import WorkerOutput
from rc7_runtime.models import (
    Artifact,
    Evaluation,
    EvaluationResult,
    Evidence,
    Gap,
    GapSeverity,
    Mission,
    Task,
    TaskStatus,
)


MISSION = "MISSION-RC7-1-N8-RECOVERY-BLOCKER"
SOURCE = "TASK-EXEC-N8-RECOVERY-BLOCKER"


def _control_with_ready_direct_repair(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "runtime-state" / "r1" / "event-stream.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(
            mission_id=MISSION,
            release_id="RC7.1-N8-RECOVERY-BLOCKER",
            goal="prove N8 recovery failures stop at a durable boundary",
        ),
    )
    control.register_task(
        Task(
            task_id=SOURCE,
            mission_id=MISSION,
            node="EXECUTION",
            task_type="EXECUTE",
            objective="execute one governed case",
            required_capabilities=["test_execution"],
        )
    )
    leased = control.lease_next(
        worker_ref="execution-worker",
        capabilities=("test_execution",),
    )
    assert leased is not None and leased.task_id == SOURCE
    control.start(SOURCE, worker_ref="execution-worker")
    evidence = Evidence(
        evidence_id="EVD-EXEC-N8-RECOVERY-BLOCKER",
        mission_id=MISSION,
        kind="RUNTIME_EXECUTION_RECORD",
        source_ref="runtime://execution",
        content_ref="evidence://attempt/ATT-1",
        subject_refs=[SOURCE, "ATT-1", "TC-1"],
    )
    artifact = Artifact(
        artifact_id="ART-EXEC-N8-RECOVERY-BLOCKER",
        mission_id=MISSION,
        artifact_type="EXECUTION_CONCLUSION",
        producer_task_id=SOURCE,
        content_ref="artifact://attempt/ATT-1",
        evidence_refs=[evidence.evidence_id],
    )
    control.submit_worker_output(
        WorkerOutput(
            task_id=SOURCE,
            worker_ref="execution-worker",
            artifacts=(artifact,),
            evidence=(evidence,),
        )
    )
    gap = Gap(
        gap_id="GAP-DIRECT-N8-RECOVERY-BLOCKER",
        mission_id=MISSION,
        source_node="EXECUTION",
        category="TRANSIENT_FAILURE",
        severity=GapSeverity.MEDIUM,
        target_node="EXECUTION",
        description="direct retry requires governed N8 authorization",
        subject_refs=["ATT-1", "TC-1"],
        evidence_refs=[evidence.evidence_id],
        acceptance_criteria=["authorize a fresh successor attempt"],
    )
    evaluation = Evaluation(
        evaluation_id="EVAL-EXEC-N8-RECOVERY-BLOCKER",
        mission_id=MISSION,
        node="EXECUTION",
        artifact_refs=[artifact.artifact_id],
        result=EvaluationResult.REPAIR_REQUIRED,
        evaluator_ref="runtime-execution-gate",
        dimensions={"attempt_id": "ATT-1", "recovery_action": "RETRY_SAME_STEP"},
        gap_refs=[gap.gap_id],
        evidence_refs=[evidence.evidence_id],
    )
    control.accept_evaluation(SOURCE, evaluation=evaluation, gaps=(gap,))
    repair_rows = [
        row
        for row in truth.query("rc7_task", mission_id=MISSION)
        if row.get("task_type") == "REPAIR"
        and row.get("node") == "EXECUTION"
        and row.get("gap_refs") == [gap.gap_id]
    ]
    assert len(repair_rows) == 1
    return truth, control, gap, control.scheduler.task(str(repair_rows[0]["task_id"]))


def test_direct_n8_repair_failure_becomes_durable_block_not_driver_exception(tmp_path: Path):
    truth, control, gap, repair_task = _control_with_ready_direct_repair(tmp_path)

    class _FailingN8:
        @staticmethod
        def handle_execution_repair(control, task):
            raise BankN8RecoveryError("BROKEN_DIRECT_REPAIR_AUTHORIZATION")

    autopilot = object.__new__(BankExecutionAutopilot)
    autopilot.n8_recovery = _FailingN8()
    autopilot.evidence_root = tmp_path / "evidence"

    # This must return at a durable R1 boundary. Runtime recovery faults are not
    # allowed to escape into MissionAutonomousDriver and terminate the session.
    autopilot.run(control, repair_task)

    assert control.scheduler.task(repair_task.task_id).state == TaskStatus.BLOCKED
    assert control.scheduler.task(SOURCE).state == TaskStatus.REPAIR_REQUIRED
    assert truth.query("rc7_gap", gap_id=gap.gap_id)[0]["state"] == "BLOCKED"
    assert truth.query("rc7_mission", mission_id=MISSION)[0]["state"] == "BLOCKED"

    blockers = [
        row
        for row in truth.query("rc7_evidence", mission_id=MISSION)
        if row.get("kind") == "N8_RECOVERY_BLOCKER"
    ]
    assert len(blockers) == 1
    blocker = blockers[0]
    assert repair_task.task_id in set(blocker.get("subject_refs") or [])
    assert gap.gap_id in set(blocker.get("subject_refs") or [])
    assert "TC-1" in set(blocker.get("subject_refs") or [])
    assert str(blocker.get("content_ref") or "").startswith("file://")
    payload = json.loads(
        Path(str(blocker["content_ref"])[len("file://"):]).read_text(encoding="utf-8")
    )
    assert payload["phase"] == "DIRECT_REPAIR"
    assert payload["reason"] == "BROKEN_DIRECT_REPAIR_AUTHORIZATION"
    assert payload["business_action_executed"] is False


def test_capture_after_execution_failure_blocks_recovery_without_rewriting_real_execution(tmp_path: Path):
    capture_mission = "MISSION-RC7-1-N8-CAPTURE-BLOCKER"
    capture_source = "TASK-EXEC-N8-CAPTURE-BLOCKER"
    tc_id = "TC-CAPTURE-1"
    target_id = "BANK-TARGET-CAPTURE"
    attempt_id = "ATT-CAPTURE-1"
    successor_attempt_id = "ATT-CAPTURE-2"
    truth_path = tmp_path / "runtime-state-capture" / "r1" / "event-stream.jsonl"
    truth = TruthRuntime(truth_path)
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(
            mission_id=capture_mission,
            release_id="RC7.1-N8-CAPTURE-BLOCKER",
            goal="prove post-execution N8 capture faults become durable blockers",
        ),
    )
    control.register_task(
        Task(
            task_id=capture_source,
            mission_id=capture_mission,
            node="EXECUTION",
            task_type="EXECUTE",
            objective="execute one real business action then capture governed recovery",
            required_capabilities=["test_execution"],
        )
    )

    class _BundleResolver:
        @staticmethod
        def resolve(*_args, **_kwargs):
            return SimpleNamespace(
                spec=SimpleNamespace(layer="L3", case_version=1),
                frozen_case={"tc_id": tc_id, "case_version": 1, "layer": "L3"},
            )

    class _Profiles:
        @staticmethod
        def get(_layer):
            return SimpleNamespace(required_tools=())

    class _UpstreamSuccessor:
        @staticmethod
        def authorize_if_ready(*_args, **_kwargs):
            return None

        @staticmethod
        def materialize_if_authorized(*_args, **_kwargs):
            return {"status": "PREPARED"}

    class _DirectSuccessor:
        @staticmethod
        def materialize_direct_successor(*_args, **_kwargs):
            raise AssertionError("upstream fixture already supplied preparation")

    class _PreparationClosure:
        @staticmethod
        def adopt_case_and_gate(*_args, **_kwargs):
            return SimpleNamespace(prepared=SimpleNamespace(status="PREPARED"))

    class _Execution:
        def __init__(self):
            self.activate_calls = 0
            self.execute_calls = 0
            self.repair_task_id = ""
            self.source_before_capture = None
            self.gap_before_capture = None
            self.attempt_before_capture = None
            self.artifact_before_capture = None
            self.execution_evidence_before_capture = None
            self.diagnosis_evidence_before_capture = None

        def activate_task(self, local_control, task_id, **_kwargs):
            self.activate_calls += 1
            leased = local_control.lease_next(
                worker_ref="capture-runtime-worker",
                capabilities=("test_execution",),
            )
            assert leased is not None and leased.task_id == task_id
            return SimpleNamespace(runtime_worker_id="capture-runtime-worker")

        def execute_active_task(self, local_control, task_id, *, active, **_kwargs):
            self.execute_calls += 1
            local_control.start(task_id, worker_ref=active.runtime_worker_id)

            execution_payload = {
                "attempt_id": attempt_id,
                "tc_id": tc_id,
                "target_id": target_id,
                "status": "FAIL",
                "business_action_executed": True,
                "actual_result": {"business_code": "ERROR", "origin": "runtime-business-action"},
            }
            execution_path = tmp_path / "capture-execution.json"
            execution_body = (
                json.dumps(execution_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            ).encode("utf-8")
            execution_path.write_bytes(execution_body)
            execution_hash = hashlib.sha256(execution_body).hexdigest()

            diagnosis_payload = {
                "context": {
                    "attempt_id": attempt_id,
                    "tc_id": tc_id,
                    "target_id": target_id,
                    "case_version": 1,
                },
                "diagnosis": {
                    "diagnosis_id": "DIAG-CAPTURE-1",
                    "failure_signature": {"signature_id": "FSIG-CAPTURE-1"},
                },
                "recovery": {
                    "attempt_id": attempt_id,
                    "diagnosis_id": "DIAG-CAPTURE-1",
                },
                "work_plan": {
                    "diagnosis_id": "DIAG-CAPTURE-1",
                    "source_attempt_id": attempt_id,
                    "action": "UNSUPPORTED_CAPTURE_ACTION",
                    "mode": "UNSUPPORTED_CAPTURE_MODE",
                    "target_node": "EXECUTION",
                    "retry_allowed": True,
                    "reprepare_required": False,
                    "terminal": False,
                    "successor_attempt_id": successor_attempt_id,
                    "reason": "exercise the post-execution capture fail-closed boundary",
                },
            }
            diagnosis_path = tmp_path / "capture-diagnosis.json"
            diagnosis_body = (
                json.dumps(diagnosis_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            ).encode("utf-8")
            diagnosis_path.write_bytes(diagnosis_body)
            diagnosis_hash = hashlib.sha256(diagnosis_body).hexdigest()

            execution_evidence = Evidence(
                evidence_id="EVD-EXEC-N8-CAPTURE-BLOCKER",
                mission_id=capture_mission,
                kind="RUNTIME_EXECUTION_RECORD",
                source_ref="runtime://execution",
                content_ref="file://" + str(execution_path),
                subject_refs=[capture_source, attempt_id, tc_id],
                content_hash="sha256:" + execution_hash,
            )
            diagnosis_evidence = Evidence(
                evidence_id="EVD-DIAG-N8-CAPTURE-BLOCKER",
                mission_id=capture_mission,
                kind="RUNTIME_FAILURE_DIAGNOSIS",
                source_ref="runtime://execution-diagnosis",
                content_ref="file://" + str(diagnosis_path),
                subject_refs=[capture_source, attempt_id, tc_id],
                content_hash="sha256:" + diagnosis_hash,
            )
            artifact = Artifact(
                artifact_id="ART-EXEC-N8-CAPTURE-BLOCKER",
                mission_id=capture_mission,
                artifact_type="EXECUTION_CONCLUSION",
                producer_task_id=capture_source,
                content_ref="file://" + str(execution_path),
                evidence_refs=[execution_evidence.evidence_id, diagnosis_evidence.evidence_id],
                content_hash="sha256:" + execution_hash,
            )
            local_control.truth.append_atomic(
                "EXECUTION_ATTEMPT_UPSERTED",
                {
                    "attempt_id": attempt_id,
                    "release_id": "RC7.1-N8-CAPTURE-BLOCKER",
                    "artifact_version": 1,
                    "requirement_id": "REQ-CAPTURE-1",
                    "tc_id": tc_id,
                    "case_version": 1,
                    "target_id": target_id,
                    "layer": "L3",
                    "status": "FAIL",
                    "actual_result": execution_payload["actual_result"],
                    "tool_call_refs": [],
                    "evidence_refs": [execution_evidence.evidence_id],
                },
            )
            local_control.submit_worker_output(
                WorkerOutput(
                    task_id=capture_source,
                    worker_ref=active.runtime_worker_id,
                    artifacts=(artifact,),
                    evidence=(execution_evidence, diagnosis_evidence),
                )
            )
            gap = Gap(
                gap_id="GAP-N8-CAPTURE-BLOCKER",
                mission_id=capture_mission,
                source_node="EXECUTION",
                category="TRANSIENT_FAILURE",
                severity=GapSeverity.HIGH,
                target_node="EXECUTION",
                description="real execution needs governed recovery capture",
                subject_refs=[attempt_id, tc_id],
                evidence_refs=[execution_evidence.evidence_id, diagnosis_evidence.evidence_id],
                acceptance_criteria=["capture a supported N8 recovery order before retry"],
            )
            evaluation = Evaluation(
                evaluation_id="EVAL-N8-CAPTURE-BLOCKER",
                mission_id=capture_mission,
                node="EXECUTION",
                artifact_refs=[artifact.artifact_id],
                result=EvaluationResult.REPAIR_REQUIRED,
                evaluator_ref="rc7-runtime-owned-execution-gate",
                dimensions={
                    "attempt_id": attempt_id,
                    "test_result": "INCONCLUSIVE",
                    "recovery_action": "UNSUPPORTED_CAPTURE_ACTION",
                },
                gap_refs=[gap.gap_id],
                evidence_refs=[execution_evidence.evidence_id, diagnosis_evidence.evidence_id],
            )
            local_control.accept_evaluation(capture_source, evaluation=evaluation, gaps=(gap,))
            repair_rows = [
                row
                for row in local_control.truth.query("rc7_task", mission_id=capture_mission)
                if row.get("task_type") == "REPAIR"
                and row.get("node") == "EXECUTION"
                and row.get("gap_refs") == [gap.gap_id]
            ]
            assert len(repair_rows) == 1
            self.repair_task_id = str(repair_rows[0]["task_id"])
            self.source_before_capture = dict(
                local_control.truth.query("rc7_task", task_id=capture_source)[0]
            )
            self.gap_before_capture = dict(
                local_control.truth.query("rc7_gap", gap_id=gap.gap_id)[0]
            )
            self.attempt_before_capture = dict(
                local_control.truth.query("execution_attempt", attempt_id=attempt_id)[0]
            )
            self.artifact_before_capture = dict(
                local_control.truth.query("rc7_artifact", artifact_id=artifact.artifact_id)[0]
            )
            self.execution_evidence_before_capture = dict(
                local_control.truth.query("rc7_evidence", evidence_id=execution_evidence.evidence_id)[0]
            )
            self.diagnosis_evidence_before_capture = dict(
                local_control.truth.query("rc7_evidence", evidence_id=diagnosis_evidence.evidence_id)[0]
            )
            assert self.source_before_capture["state"] == "REPAIR_REQUIRED"
            assert self.gap_before_capture["state"] == "PLANNED"
            assert repair_rows[0]["state"] == "READY"
            return SimpleNamespace(
                execution_record=SimpleNamespace(attempt_id=attempt_id),
                evidence_ids=(execution_evidence.evidence_id, diagnosis_evidence.evidence_id),
                loop_result=SimpleNamespace(evaluation=evaluation, gaps=(gap,)),
            )

    execution = _Execution()
    autopilot = object.__new__(BankExecutionAutopilot)
    autopilot.authority = object()
    autopilot.state_root = tmp_path / "state"
    autopilot.evidence_root = tmp_path / "autopilot-evidence"
    autopilot.package_root = tmp_path
    autopilot.target_id = target_id
    autopilot.bundle_resolver = _BundleResolver()
    autopilot.profiles = _Profiles()
    autopilot.execution = execution
    autopilot.n8_upstream_successor = _UpstreamSuccessor()
    autopilot.n8_successor = _DirectSuccessor()
    autopilot.preparation_closure = _PreparationClosure()
    autopilot.n8_recovery = BankN8RecoveryCoordinator(evidence_root=str(tmp_path / "n8"))
    autopilot.oracle = object()
    autopilot._case_for_task = lambda _control, _task: tc_id
    autopilot._capability_broker = lambda _required_tools: object()
    autopilot._autonomous_run_id = lambda _control: "RUN-CAPTURE-1"
    autopilot._accepted_frozen_cases = lambda _control: ({"tc_id": tc_id},)

    # The business action and its REPAIR_REQUIRED conclusion are already real
    # R1 truth before N8 capture rejects an unsupported recovery mode. The
    # capture fault must become a durable blocker; it must not escape the
    # autonomous driver or rewrite the execution conclusion.
    autopilot.run(control, control.scheduler.task(capture_source))

    assert execution.activate_calls == 1
    assert execution.execute_calls == 1
    assert control.scheduler.task(capture_source).state == TaskStatus.REPAIR_REQUIRED
    assert control.scheduler.task(execution.repair_task_id).state == TaskStatus.BLOCKED

    fresh_truth = TruthRuntime(truth_path)
    assert fresh_truth.query("rc7_task", task_id=capture_source)[0]["state"] == "REPAIR_REQUIRED"
    assert fresh_truth.query("rc7_task", task_id=execution.repair_task_id)[0]["state"] == "BLOCKED"
    assert fresh_truth.query("rc7_gap", gap_id="GAP-N8-CAPTURE-BLOCKER")[0]["state"] == "BLOCKED"
    assert fresh_truth.query("rc7_mission", mission_id=capture_mission)[0]["state"] == "BLOCKED"

    assert fresh_truth.query("execution_attempt", attempt_id=attempt_id)[0] == execution.attempt_before_capture
    assert fresh_truth.query("rc7_artifact", artifact_id="ART-EXEC-N8-CAPTURE-BLOCKER")[0] == execution.artifact_before_capture
    assert fresh_truth.query("rc7_evidence", evidence_id="EVD-EXEC-N8-CAPTURE-BLOCKER")[0] == execution.execution_evidence_before_capture
    assert fresh_truth.query("rc7_evidence", evidence_id="EVD-DIAG-N8-CAPTURE-BLOCKER")[0] == execution.diagnosis_evidence_before_capture

    blockers = [
        row
        for row in fresh_truth.query("rc7_evidence", mission_id=capture_mission)
        if row.get("kind") == "N8_RECOVERY_BLOCKER"
    ]
    assert len(blockers) == 1
    blocker = blockers[0]
    assert capture_source in set(blocker.get("subject_refs") or [])
    assert execution.repair_task_id in set(blocker.get("subject_refs") or [])
    assert "GAP-N8-CAPTURE-BLOCKER" in set(blocker.get("subject_refs") or [])
    assert tc_id in set(blocker.get("subject_refs") or [])
    content_ref = str(blocker.get("content_ref") or "")
    assert content_ref.startswith("file://")
    blocker_bytes = Path(content_ref[len("file://"):]).read_bytes()
    assert blocker["content_hash"] == "sha256:" + hashlib.sha256(blocker_bytes).hexdigest()
    payload = json.loads(blocker_bytes.decode("utf-8"))
    assert payload["mission_id"] == capture_mission
    assert payload["task_id"] == capture_source
    assert payload["gap_id"] == "GAP-N8-CAPTURE-BLOCKER"
    assert payload["phase"] == "CAPTURE_AFTER_EXECUTION"
    assert payload["reason"] == "BANK_N8_RECOVERY_MODE_UNSUPPORTED:UNSUPPORTED_CAPTURE_MODE"
    assert payload["business_action_executed"] is True

    assert not [
        row
        for row in fresh_truth.query("rc7_evidence", mission_id=capture_mission)
        if str(row.get("kind") or "").startswith("N8_DIRECT_RETRY")
        or row.get("kind") == "N8_RECOVERY_WORK_ORDER"
    ]
