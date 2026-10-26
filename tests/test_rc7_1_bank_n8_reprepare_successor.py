from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path

from rc6_runtime.preparation import PreparedAttempt
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.autonomous_recovery_orchestrator import N8RecoveryOrchestrator
from rc7_runtime.bank_n5_full_recovery_closure import BankN5FullRecoveryAwarePreparationClosureCoordinator
from rc7_runtime.bank_n8_upstream_successor import BankN8UpstreamSuccessorCoordinator
from rc7_runtime.case_runtime import PREPARED_ATTEMPT_KIND, _state_ref, _write_immutable_json
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.control_plane import WorkerOutput
from rc7_runtime.execution_recovery import RecoveryWorkPlan
from rc7_runtime.models import Artifact, Evaluation, EvaluationResult, Evidence, Gap, GapSeverity, Mission, Task, TaskStatus
from rc7_runtime.truth_overlay import append_entity


MISSION = "MISSION-RC7-1-N8-REPREPARE"
RELEASE = "RC7.1-N8-REPREPARE"
SOURCE = "TASK-EXEC-N8-REPREPARE"
DESIGN = "TASK-DESIGN-N8-REPREPARE"
DESIGN_ARTIFACT = "ART-DESIGN-N8-REPREPARE"
TARGET = "BANK-TARGET"
TC_ID = "TC-REPREPARE-1"


def _case() -> dict:
    return {
        "status": "FROZEN",
        "tc_id": TC_ID,
        "case_version": 1,
        "layer": "L4",
        "preconditions": [
            {"id": "auth-ready", "type": "AUTH", "requirement": "fresh authenticated bank session"},
        ],
        "test_data": {
            "initial_state": [
                {
                    "id": "loan-state",
                    "selectors": {"status": "PENDING"},
                    "allowed_strategies": ["REUSE_EXISTING"],
                }
            ],
            "input_data": [],
            "cleanup_policy": {"mode": "NONE"},
        },
        "oracle": {"type": "field_equals", "field": "status", "value": "APPROVED"},
    }


def _candidate_bytes() -> bytes:
    envelope = {
        "task_id": DESIGN,
        "artifact": {
            "artifact_id": DESIGN_ARTIFACT,
            "artifact_type": "TEST_DESIGN_MODEL",
            "content_ref": "runtime://accepted-test-design",
            "parent_refs": [],
            "evidence_refs": ["EVD-DESIGN-SOURCE"],
        },
        "semantic_payload": {"cases": [_case()], "obligations": [{"obligation_id": "OB-REPREPARE"}]},
        "evidence": [],
    }
    return (json.dumps(envelope, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _prepared(attempt_id: str) -> PreparedAttempt:
    return PreparedAttempt(
        status="PREPARED",
        attempt_id=attempt_id,
        tc_id=TC_ID,
        case_version=1,
        target_id=TARGET,
        precondition_evidence=("EVD-AUTH-OLD",),
        initial_state_bindings={"loan-state": {"business_id": "LOAN-OLD", "status": "PENDING"}},
        input_data_bindings={},
        binding_evidence=("EVD-DATA-OLD",),
        cleanup_policy={"mode": "NONE"},
        oracle_snapshot={"type": "field_equals", "field": "status", "value": "APPROVED"},
    )


def _persist_prepared(truth: TruthRuntime, state_root: Path, prepared: PreparedAttempt) -> Path:
    target, digest = _write_immutable_json(
        state_root,
        Path(MISSION) / prepared.attempt_id / "prepared-attempt.json",
        asdict(prepared),
    )
    append_entity(
        truth,
        Evidence(
            evidence_id="EVD-PREPARED-" + prepared.attempt_id,
            mission_id=MISSION,
            kind=PREPARED_ATTEMPT_KIND,
            source_ref="runtime://case-runtime/preparation",
            content_ref=_state_ref(state_root, target),
            subject_refs=[SOURCE, "execution-worker", prepared.attempt_id, TC_ID, TARGET],
            content_hash=digest,
        ),
        release_id=RELEASE,
        artifact_version=1,
    )
    return target


def _provider_config(tmp_path: Path, log_path: Path) -> Path:
    provider = tmp_path / "provider.py"
    provider.write_text(
        "import json, os, sys\n"
        "payload=json.loads(sys.stdin.read())\n"
        "cap=payload['capability']\n"
        "with open(os.environ['CALL_LOG'], 'a', encoding='utf-8') as h: h.write(cap+'\\n')\n"
        "if cap.startswith('PRECONDITION_'):\n"
        "    out={'success': True, 'detail': 'fresh-auth'}\n"
        "elif cap.startswith('DATA_') and cap != 'DATA_VERIFY':\n"
        "    out={'success': True, 'binding': {'business_id': 'LOAN-NEW', 'status': 'PENDING'}}\n"
        "elif cap == 'DATA_VERIFY':\n"
        "    out={'success': True}\n"
        "else:\n"
        "    out={'success': False, 'reason': 'unsupported'}\n"
        "print(json.dumps(out))\n",
        encoding="utf-8",
    )
    command = [sys.executable, str(provider)]
    config = {
        "providers": {
            "PRECONDITION_AUTH": {
                "provider_id": "auth-fixture",
                "command": command,
                "environment": {"CALL_LOG": str(log_path)},
            },
            "DATA_REUSE_EXISTING": {
                "provider_id": "data-fixture",
                "command": command,
                "environment": {"CALL_LOG": str(log_path)},
            },
            "DATA_VERIFY": {
                "provider_id": "verify-fixture",
                "command": command,
                "environment": {"CALL_LOG": str(log_path)},
            },
        }
    }
    path = tmp_path / "providers.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def _setup(tmp_path: Path):
    state_root = tmp_path / "state"
    truth = TruthRuntime(tmp_path / "runtime-state" / "r1" / "event-stream.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(mission_id=MISSION, release_id=RELEASE, goal="prove real N8 reprepare successor closure"),
    )
    control.register_task(
        Task(
            task_id=SOURCE,
            mission_id=MISSION,
            node="EXECUTION",
            task_type="EXECUTE",
            objective="execute governed case",
            required_capabilities=["test_execution"],
        )
    )
    control.register_task(
        Task(
            task_id=DESIGN,
            mission_id=MISSION,
            node="TEST_DESIGN",
            task_type="PRODUCE",
            objective="provide accepted frozen case",
        )
    )
    design_source = Evidence(
        evidence_id="EVD-DESIGN-SOURCE",
        mission_id=MISSION,
        kind="TEST_DESIGN_SOURCE",
        source_ref="runtime://test-design",
        content_ref="evidence://design/source",
        subject_refs=[DESIGN],
    )
    append_entity(truth, design_source, release_id=RELEASE, artifact_version=1)
    raw = _candidate_bytes()
    design_path = tmp_path / "accepted-test-design.json"
    design_path.write_bytes(raw)
    append_entity(
        truth,
        Artifact(
            artifact_id=DESIGN_ARTIFACT,
            mission_id=MISSION,
            artifact_type="TEST_DESIGN_MODEL",
            producer_task_id=DESIGN,
            content_ref="file://" + str(design_path.resolve()),
            evidence_refs=[design_source.evidence_id],
            content_hash="sha256:" + hashlib.sha256(raw).hexdigest(),
        ),
        release_id=RELEASE,
        artifact_version=1,
    )
    design_eval = Evaluation(
        evaluation_id="EVAL-DESIGN-PASS",
        mission_id=MISSION,
        node="TEST_DESIGN",
        artifact_refs=[DESIGN_ARTIFACT],
        result=EvaluationResult.PASS,
        evaluator_ref="independent-design-gate",
        dimensions={"accepted": True},
        evidence_refs=[design_source.evidence_id],
    )
    append_entity(truth, design_eval, release_id=RELEASE, artifact_version=1)
    design_task = control.scheduler.task(DESIGN)
    design_task.state = TaskStatus.PASS
    design_task.output_artifact_refs = [DESIGN_ARTIFACT]
    design_task.evaluation_id = design_eval.evaluation_id
    control.scheduler.persist_evaluated_task(design_task)

    source_prepared = _prepared("ATT-1")
    source_path = _persist_prepared(truth, state_root, source_prepared)
    source_bytes = source_path.read_bytes()

    leased = control.lease_next(worker_ref="execution-worker", capabilities=("test_execution",))
    assert leased is not None and leased.task_id == SOURCE
    control.start(SOURCE, worker_ref="execution-worker")
    execution_evidence = Evidence(
        evidence_id="EVD-EXEC-REPREPARE",
        mission_id=MISSION,
        kind="RUNTIME_EXECUTION_RECORD",
        source_ref="runtime://execution",
        content_ref="evidence://execution/ATT-1",
        subject_refs=[SOURCE, "ATT-1", TC_ID],
    )
    diagnosis_evidence = Evidence(
        evidence_id="EVD-DIAG-REPREPARE",
        mission_id=MISSION,
        kind="RUNTIME_FAILURE_DIAGNOSIS",
        source_ref="runtime://diagnosis",
        content_ref="evidence://diagnosis/ATT-1",
        subject_refs=[SOURCE, "ATT-1", TC_ID],
    )
    execution_artifact = Artifact(
        artifact_id="ART-EXEC-REPREPARE",
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
        gap_id="GAP-AUTH-REPREPARE",
        mission_id=MISSION,
        source_node="EXECUTION",
        category="AUTH_DEFECT",
        severity=GapSeverity.HIGH,
        target_node="RUNTIME",
        description="fresh auth and data preparation required",
        subject_refs=["ATT-1", TC_ID],
        evidence_refs=[diagnosis_evidence.evidence_id],
        acceptance_criteria=["restore fresh auth then prepare a new successor attempt"],
    )
    control.accept_evaluation(
        SOURCE,
        evaluation=Evaluation(
            evaluation_id="EVAL-EXEC-REPREPARE",
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
        diagnosis_id="DIAG-AUTH-REPREPARE",
        source_attempt_id="ATT-1",
        action="REAUTH_AND_REPREPARE",
        mode="REPREPARE_THEN_RETRY",
        target_node="RUNTIME",
        retry_allowed=True,
        reprepare_required=True,
        terminal=False,
        successor_attempt_id="ATT-2",
        reason="fresh auth and test data are required before retry",
    )
    order = N8RecoveryOrchestrator(evidence_root=str(tmp_path / "n8")).create_work_order(
        control,
        source_task_id=SOURCE,
        gap_id=gap.gap_id,
        plan=plan,
        diagnosis_evidence_id=diagnosis_evidence.evidence_id,
        failure_signature_id="FSIG-AUTH-REPREPARE",
    )
    repair_rows = [
        row for row in truth.query("rc7_task", mission_id=MISSION)
        if row.get("task_type") == "REPAIR" and row.get("gap_refs") == [gap.gap_id]
    ]
    assert len(repair_rows) == 1
    repair_task_id = str(repair_rows[0]["task_id"])
    repair_worker = "runtime-repair-worker"
    repair = control.lease_next(worker_ref=repair_worker, capabilities=("runtime_recovery",))
    assert repair is not None and repair.task_id == repair_task_id
    control.start(repair_task_id, worker_ref=repair_worker)
    delta = Evidence(
        evidence_id="EVD-DELTA-REPREPARE",
        mission_id=MISSION,
        kind="REPAIR_DELTA_EVIDENCE",
        source_ref="runtime://recovery_execute/foura_auth",
        content_ref="evidence://auth/fresh",
        subject_refs=[repair_task_id, gap.gap_id],
    )
    repair_artifact = Artifact(
        artifact_id="ART-REPAIR-REPREPARE",
        mission_id=MISSION,
        artifact_type="OWNER_REPAIR_OUTPUT",
        producer_task_id=repair_task_id,
        content_ref="artifact://auth/fresh",
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
            evaluation_id="EVAL-REPAIR-REPREPARE",
            mission_id=MISSION,
            node="RUNTIME",
            artifact_refs=[repair_artifact.artifact_id],
            result=EvaluationResult.PASS,
            evaluator_ref="rc7-n8-owner-repair-independent-gate",
            dimensions={
                "repair_work_order_id": order.work_order_id,
                "repair_before_fingerprint": "auth:expired",
                "repair_after_fingerprint": "auth:fresh",
                "repair_delta_refs": [delta.evidence_id],
            },
            evidence_refs=[delta.evidence_id],
        ),
    )
    assert control.scheduler.task(SOURCE).state == TaskStatus.READY
    return truth, control, state_root, source_path, source_bytes, order


def test_auth_reprepare_runs_real_provider_and_authorizes_att2(tmp_path: Path):
    truth, control, state_root, source_path, source_bytes, order = _setup(tmp_path)
    log_path = tmp_path / "provider-calls.log"
    provider_config = _provider_config(tmp_path, log_path)
    coordinator = BankN8UpstreamSuccessorCoordinator(
        state_root=str(state_root),
        evidence_root=str(tmp_path / "n8"),
        provider_config=str(provider_config),
    )

    # Reprepare must not authorize while the source task is merely READY.
    assert coordinator.authorize_if_ready(
        control,
        source_task_id=SOURCE,
        tc_id=TC_ID,
        target_id=TARGET,
    ) is None
    assert not [
        row for row in truth.query("rc7_evidence", mission_id=MISSION)
        if row.get("kind") == N8RecoveryOrchestrator.RECEIPT_TYPE
    ]

    leased = control.lease_next(worker_ref="retry-worker", capabilities=("test_execution",))
    assert leased is not None and leased.task_id == SOURCE
    result = coordinator.materialize_if_authorized(
        control,
        source_task_id=SOURCE,
        worker_id="retry-worker",
        tc_id=TC_ID,
        target_id=TARGET,
    )
    assert result is not None
    assert result["status"] == "PREPARED"
    assert result["n8_successor"] is True
    assert result["n8_reprepare"] is True
    assert result["source_attempt_id"] == "ATT-1"
    assert result["prepared_attempt"]["attempt_id"] == "ATT-2"
    assert result["prepared_attempt"]["initial_state_bindings"]["loan-state"]["business_id"] == "LOAN-NEW"
    assert source_path.read_bytes() == source_bytes
    assert log_path.read_text(encoding="utf-8").splitlines() == [
        "PRECONDITION_AUTH",
        "DATA_REUSE_EXISTING",
        "DATA_VERIFY",
    ]

    receipts = [
        row for row in truth.query("rc7_evidence", mission_id=MISSION)
        if row.get("kind") == N8RecoveryOrchestrator.RECEIPT_TYPE
    ]
    assert len(receipts) == 1
    receipt_payload = json.loads(Path(receipts[0]["content_ref"][len("file://"):]).read_text(encoding="utf-8"))
    assert receipt_payload["work_order_id"] == order.work_order_id
    assert receipt_payload["successor_attempt_id"] == "ATT-2"
    assert receipt_payload["reprepare_required"] is True

    canonical_artifact_id = "ART-PREPARED-" + hashlib.sha256(
        (MISSION + "\x1f" + SOURCE + "\x1f" + "ATT-2").encode("utf-8")
    ).hexdigest()[:20]
    canonical = truth.query("rc7_artifact", artifact_id=canonical_artifact_id)
    assert len(canonical) == 1
    assert canonical[0]["artifact_type_name"] == "PREPARED_ATTEMPT"

    edge = BankN5FullRecoveryAwarePreparationClosureCoordinator._n8_direct_edge(
        control,
        execution_task_id=SOURCE,
        tc_id=TC_ID,
        successor_attempt_id="ATT-2",
    )
    assert edge == ("ATT-1", "ATT-2")


def test_auth_reprepare_missing_provider_fails_closed_without_receipt(tmp_path: Path):
    truth, control, state_root, _source_path, _source_bytes, _order = _setup(tmp_path)
    coordinator = BankN8UpstreamSuccessorCoordinator(
        state_root=str(state_root),
        evidence_root=str(tmp_path / "n8"),
    )
    leased = control.lease_next(worker_ref="retry-worker", capabilities=("test_execution",))
    assert leased is not None and leased.task_id == SOURCE
    result = coordinator.materialize_if_authorized(
        control,
        source_task_id=SOURCE,
        worker_id="retry-worker",
        tc_id=TC_ID,
        target_id=TARGET,
    )
    assert result is not None
    assert result["status"] == "FIELD_REQUIRED"
    assert result["field_required_capability"] == "PRECONDITION_AUTH"
    assert not [
        row for row in truth.query("rc7_evidence", mission_id=MISSION)
        if row.get("kind") == N8RecoveryOrchestrator.RECEIPT_TYPE
    ]
    prepared_att2 = [
        row for row in truth.query("rc7_evidence", mission_id=MISSION)
        if row.get("kind") == PREPARED_ATTEMPT_KIND and "ATT-2" in set(row.get("subject_refs") or [])
    ]
    assert prepared_att2 == []
