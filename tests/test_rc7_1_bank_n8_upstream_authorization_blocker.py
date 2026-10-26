from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

from rc6_runtime.preparation import PreparedAttempt
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.autonomous_recovery_orchestrator import N8RecoveryOrchestrator
from rc7_runtime.bank_execution_autopilot import BankExecutionAutopilot
from rc7_runtime.bank_n8_upstream_successor import BankN8UpstreamSuccessorCoordinator
from rc7_runtime.case_runtime import PREPARED_ATTEMPT_KIND, _state_ref, _write_immutable_json
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.control_plane import WorkerOutput
from rc7_runtime.execution_recovery import RecoveryWorkPlan
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
from rc7_runtime.truth_overlay import append_entity


MISSION = "MISSION-RC7-1-N8-UPSTREAM-AUTH-BLOCKER"
SOURCE = "TASK-EXEC-N8-UPSTREAM-AUTH-BLOCKER"
TARGET = "BANK-TARGET"
TC_ID = "TC-UPSTREAM-AUTH-BLOCKER"


def _persist_prepared(truth: TruthRuntime, state_root: Path) -> Path:
    prepared = PreparedAttempt(
        status="PREPARED",
        attempt_id="ATT-1",
        tc_id=TC_ID,
        case_version=1,
        target_id=TARGET,
        precondition_evidence=("EVD-PRE",),
        initial_state_bindings={"loan_id": "L-1"},
        input_data_bindings={"amount": 100},
        binding_evidence=("EVD-DATA",),
        cleanup_policy={"mode": "RELEASE"},
        oracle_snapshot={
            "checks": [
                {
                    "id": "CHK-1",
                    "type": "BUSINESS_RULE",
                    "actual_path": "code",
                    "operator": "EQ",
                    "expected": "OK",
                }
            ]
        },
    )
    target, digest = _write_immutable_json(
        state_root,
        Path(MISSION) / prepared.attempt_id / "prepared-attempt.json",
        asdict(prepared),
    )
    append_entity(
        truth,
        Evidence(
            evidence_id="EVD-PREPARED-ATT-1",
            mission_id=MISSION,
            kind=PREPARED_ATTEMPT_KIND,
            source_ref="runtime://case-runtime/preparation",
            content_ref=_state_ref(state_root, target),
            subject_refs=[SOURCE, "execution-worker", prepared.attempt_id, TC_ID, TARGET],
            content_hash=digest,
        ),
        release_id="RC7.1-N8-UPSTREAM-AUTH-BLOCKER",
        artifact_version=1,
    )
    return target


def _ready_source_with_rejected_upstream_receipt(tmp_path: Path):
    state_root = tmp_path / "state"
    truth_path = tmp_path / "runtime-state" / "r1" / "event-stream.jsonl"
    truth = TruthRuntime(truth_path)
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(
            mission_id=MISSION,
            release_id="RC7.1-N8-UPSTREAM-AUTH-BLOCKER",
            goal="prove upstream N8 authorization failure becomes a durable blocker",
        ),
    )
    control.register_task(
        Task(
            task_id=SOURCE,
            mission_id=MISSION,
            node="EXECUTION",
            task_type="EXECUTE",
            objective="execute one governed case after upstream repair",
            required_capabilities=["test_execution"],
        )
    )
    source_path = _persist_prepared(truth, state_root)
    source_bytes = source_path.read_bytes()

    leased = control.lease_next(worker_ref="execution-worker", capabilities=("test_execution",))
    assert leased is not None and leased.task_id == SOURCE
    control.start(SOURCE, worker_ref="execution-worker")
    execution_evidence = Evidence(
        evidence_id="EVD-EXEC-UPSTREAM-AUTH-BLOCKER",
        mission_id=MISSION,
        kind="RUNTIME_EXECUTION_RECORD",
        source_ref="runtime://execution",
        content_ref="evidence://execution/ATT-1",
        subject_refs=[SOURCE, "ATT-1", TC_ID],
    )
    diagnosis_evidence = Evidence(
        evidence_id="EVD-DIAG-UPSTREAM-AUTH-BLOCKER",
        mission_id=MISSION,
        kind="RUNTIME_FAILURE_DIAGNOSIS",
        source_ref="runtime://diagnosis",
        content_ref="evidence://diagnosis/ATT-1",
        subject_refs=[SOURCE, "ATT-1", TC_ID],
    )
    execution_artifact = Artifact(
        artifact_id="ART-EXEC-UPSTREAM-AUTH-BLOCKER",
        mission_id=MISSION,
        artifact_type="EXECUTION_CONCLUSION",
        producer_task_id=SOURCE,
        content_ref="artifact://execution/ATT-1",
        evidence_refs=[execution_evidence.evidence_id, diagnosis_evidence.evidence_id],
    )
    control.submit_worker_output(
        WorkerOutput(
            task_id=SOURCE,
            worker_ref="execution-worker",
            artifacts=(execution_artifact,),
            evidence=(execution_evidence, diagnosis_evidence),
        )
    )
    gap = Gap(
        gap_id="GAP-SCRIPT-UPSTREAM-AUTH-BLOCKER",
        mission_id=MISSION,
        source_node="EXECUTION",
        category="SCRIPT_DEFECT",
        severity=GapSeverity.HIGH,
        target_node="SCRIPT_READINESS",
        description="owner repair passed but successor authorization receipt is invalid",
        subject_refs=["ATT-1", TC_ID],
        evidence_refs=[diagnosis_evidence.evidence_id],
        acceptance_criteria=["a valid owner delta authorizes a fresh successor attempt"],
    )
    control.accept_evaluation(
        SOURCE,
        evaluation=Evaluation(
            evaluation_id="EVAL-EXEC-UPSTREAM-AUTH-BLOCKER",
            mission_id=MISSION,
            node="EXECUTION",
            artifact_refs=[execution_artifact.artifact_id],
            result=EvaluationResult.REPAIR_REQUIRED,
            evaluator_ref="runtime-execution-gate",
            dimensions={"attempt_id": "ATT-1"},
            gap_refs=[gap.gap_id],
            evidence_refs=[diagnosis_evidence.evidence_id],
        ),
        gaps=(gap,),
    )
    plan = RecoveryWorkPlan(
        diagnosis_id="DIAG-SCRIPT-UPSTREAM-AUTH-BLOCKER",
        source_attempt_id="ATT-1",
        action="REPAIR_SCRIPT",
        mode="UPSTREAM_REPAIR_THEN_RETRY",
        target_node="SCRIPT_READINESS",
        retry_allowed=True,
        reprepare_required=False,
        terminal=False,
        successor_attempt_id="ATT-2",
        reason="repair script then retry exact case",
    )
    order = N8RecoveryOrchestrator(evidence_root=str(tmp_path / "n8")).create_work_order(
        control,
        source_task_id=SOURCE,
        gap_id=gap.gap_id,
        plan=plan,
        diagnosis_evidence_id=diagnosis_evidence.evidence_id,
        failure_signature_id="FSIG-SCRIPT-UPSTREAM-AUTH-BLOCKER",
    )

    repair_rows = [
        row
        for row in truth.query("rc7_task", mission_id=MISSION)
        if row.get("task_type") == "REPAIR" and row.get("gap_refs") == [gap.gap_id]
    ]
    assert len(repair_rows) == 1
    repair_task_id = str(repair_rows[0]["task_id"])
    repair_worker = "script-repair-worker"
    repair = control.lease_next(worker_ref=repair_worker, capabilities=("test_automation",))
    assert repair is not None and repair.task_id == repair_task_id
    control.start(repair_task_id, worker_ref=repair_worker)
    delta = Evidence(
        evidence_id="EVD-DELTA-UPSTREAM-AUTH-BLOCKER",
        mission_id=MISSION,
        kind="REPAIR_DELTA_EVIDENCE",
        source_ref="runtime://script-repair",
        content_ref="evidence://script/delta",
        subject_refs=[repair_task_id, gap.gap_id],
    )
    repair_artifact = Artifact(
        artifact_id="ART-REPAIR-UPSTREAM-AUTH-BLOCKER",
        mission_id=MISSION,
        artifact_type="OWNER_REPAIR_OUTPUT",
        producer_task_id=repair_task_id,
        content_ref="artifact://script/delta",
        evidence_refs=[delta.evidence_id],
    )
    control.submit_worker_output(
        WorkerOutput(
            task_id=repair_task_id,
            worker_ref=repair_worker,
            artifacts=(repair_artifact,),
            evidence=(delta,),
        )
    )
    control.accept_evaluation(
        repair_task_id,
        evaluation=Evaluation(
            evaluation_id="EVAL-REPAIR-UPSTREAM-AUTH-BLOCKER",
            mission_id=MISSION,
            node="SCRIPT_READINESS",
            artifact_refs=[repair_artifact.artifact_id],
            result=EvaluationResult.PASS,
            evaluator_ref="rc7-n8-owner-repair-independent-gate",
            dimensions={
                "repair_work_order_id": order.work_order_id,
                "repair_before_fingerprint": "script:same",
                "repair_after_fingerprint": "script:same",
                "repair_delta_refs": [delta.evidence_id],
            },
            evidence_refs=[delta.evidence_id],
        ),
    )
    source = control.scheduler.task(SOURCE)
    assert source.state == TaskStatus.READY
    assert source.gap_refs == [gap.gap_id]
    assert truth.query("rc7_gap", gap_id=gap.gap_id)[0]["state"] == "EVIDENCE_PENDING"
    return truth_path, truth, control, gap, source, state_root, source_path, source_bytes


class _BundleResolver:
    @staticmethod
    def resolve(*_args, **_kwargs):
        return SimpleNamespace(spec=SimpleNamespace(layer="L3"))


class _Profiles:
    @staticmethod
    def get(_layer):
        return SimpleNamespace(required_tools=())


class _BusinessExecutionMustNotRun:
    def __init__(self) -> None:
        self.activate_calls = 0
        self.execute_calls = 0

    def activate_task(self, *_args, **_kwargs):
        self.activate_calls += 1
        raise AssertionError("business execution activation must not happen after upstream authorization failure")

    def execute_active_task(self, *_args, **_kwargs):
        self.execute_calls += 1
        raise AssertionError("business action must not execute after upstream authorization failure")


def test_upstream_authorization_failure_becomes_durable_block_before_business_action(tmp_path: Path):
    truth_path, truth, control, gap, source, state_root, source_path, source_bytes = (
        _ready_source_with_rejected_upstream_receipt(tmp_path)
    )
    execution = _BusinessExecutionMustNotRun()
    autopilot = object.__new__(BankExecutionAutopilot)
    autopilot.evidence_root = tmp_path / "autopilot-evidence"
    autopilot.state_root = state_root
    autopilot.package_root = tmp_path
    autopilot.target_id = TARGET
    autopilot.bundle_resolver = _BundleResolver()
    autopilot.profiles = _Profiles()
    autopilot.execution = execution
    autopilot.n8_upstream_successor = BankN8UpstreamSuccessorCoordinator(
        state_root=str(state_root),
        evidence_root=str(tmp_path / "n8"),
    )
    autopilot._case_for_task = lambda _control, _task: TC_ID
    autopilot._capability_broker = lambda _required_tools: object()

    # A real upstream work order reaches receipt authorization with an invalid
    # owner delta (same before/after fingerprint). The runtime must fail closed
    # into R1 instead of escaping into MissionAutonomousDriver.
    autopilot.run(control, source)

    assert execution.activate_calls == 0
    assert execution.execute_calls == 0
    assert source_path.read_bytes() == source_bytes
    assert not [
        row
        for row in truth.query("rc7_evidence", mission_id=MISSION)
        if row.get("kind") == N8RecoveryOrchestrator.RECEIPT_TYPE
    ]
    assert not [
        row
        for row in truth.query("rc7_evidence", mission_id=MISSION)
        if row.get("kind") == PREPARED_ATTEMPT_KIND and "ATT-2" in set(row.get("subject_refs") or [])
    ]

    fresh_truth = TruthRuntime(truth_path)
    blockers = [
        row
        for row in fresh_truth.query("rc7_evidence", mission_id=MISSION)
        if row.get("kind") == "N8_RECOVERY_BLOCKER"
    ]
    assert len(blockers) == 1
    blocker = blockers[0]
    assert SOURCE in set(blocker.get("subject_refs") or [])
    assert gap.gap_id in set(blocker.get("subject_refs") or [])
    assert TC_ID in set(blocker.get("subject_refs") or [])
    content_ref = str(blocker.get("content_ref") or "")
    assert content_ref.startswith("file://")
    blocker_path = Path(content_ref[len("file://"):])
    blocker_bytes = blocker_path.read_bytes()
    assert blocker["content_hash"] == "sha256:" + hashlib.sha256(blocker_bytes).hexdigest()
    payload = json.loads(blocker_bytes.decode("utf-8"))
    assert payload["mission_id"] == MISSION
    assert payload["task_id"] == SOURCE
    assert payload["gap_id"] == gap.gap_id
    assert payload["phase"] == "UPSTREAM_AUTHORIZATION"
    assert payload["reason"] == "BANK_N8_UPSTREAM_RECEIPT_REJECTED:SAME_FAILURE_SIGNATURE_NO_DELTA"
    assert payload["business_action_executed"] is False

    # A new R1 reader models the driver's next truth read: the durable boundary
    # must already be visible without relying on the throwing process memory.
    assert fresh_truth.query("rc7_gap", gap_id=gap.gap_id)[0]["state"] == "BLOCKED"
    assert fresh_truth.query("rc7_task", task_id=SOURCE)[0]["state"] == "BLOCKED"
    assert fresh_truth.query("rc7_mission", mission_id=MISSION)[0]["state"] == "BLOCKED"
