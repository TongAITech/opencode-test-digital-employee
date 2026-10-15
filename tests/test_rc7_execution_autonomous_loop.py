from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

from rc6_runtime.capability import ToolCapabilityBroker
from rc6_runtime.execution import ExecutionRecord
from rc6_runtime.preparation import PreparedAttempt
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.authority import RC7AuthorityRuntime
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.control_plane import WorkerOutput
from rc7_runtime.execution_autonomous_loop import AutonomousExecutionLoop
from rc7_runtime.execution_diagnosis import ExecutionTrustFacts
from rc7_runtime.execution_loop import ExecutionClosedLoop
from rc7_runtime.execution_recovery_control import ExecutionRecoveryController
from rc7_runtime.lineage_diagnosis import LineageAwareExecutionDiagnosisCoordinator
from rc7_runtime.models import Artifact, Evidence, Mission, Task
from rc7_runtime.runtime_execution_control import ClosedLoopExecutionResult


MISSION = "MISSION-AUTO-EXEC"
TASK = "TASK-AUTO-EXEC"
WORKER = "runtime-exec-worker"


def _prepared(attempt_id):
    return PreparedAttempt(
        status="PREPARED",
        attempt_id=attempt_id,
        tc_id="TC-AUTO-EXEC",
        case_version=1,
        target_id="TARGET-AUTO-EXEC",
        precondition_evidence=("EVD-PRE",),
        initial_state_bindings={"loan": "L-1"},
        input_data_bindings={},
        binding_evidence=("EVD-DATA",),
        cleanup_policy={"mode": "NONE"},
        oracle_snapshot={
            "checks": [
                {"id": "C1", "type": "BUSINESS_RULE", "actual_path": "code", "operator": "EQ", "expected": "OK"}
            ]
        },
    )


def _bundle():
    return SimpleNamespace(validation=SimpleNamespace(ready=True))


def _stable(prefix, *parts):
    raw = "\x1f".join(str(x) for x in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


def test_autonomous_loop_consumes_persisted_direct_retry_then_resolves_gap(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(mission_id=MISSION, release_id="RC7-AUTO-EXEC", goal="bounded autonomous retry"),
    )
    control.register_task(
        Task(
            task_id=TASK,
            mission_id=MISSION,
            node="EXECUTION",
            task_type="EXECUTE",
            objective="run one case with governed transient retry",
            required_capabilities=["test_execution"],
        )
    )
    coordinator = LineageAwareExecutionDiagnosisCoordinator(
        authority=RC7AuthorityRuntime(b"0123456789abcdef0123456789abcdef"),
        tool_broker=ToolCapabilityBroker(),
        evidence_root=str(tmp_path / "diagnosis"),
        max_transient_retries=2,
    )
    recovery_controller = ExecutionRecoveryController(evidence_root=str(tmp_path / "recovery"))
    calls = []

    def run_once(prepared, coord):
        calls.append(prepared.attempt_id)
        leased = control.lease_next(worker_ref=WORKER, capabilities=("test_execution",))
        assert leased is not None and leased.task_id == TASK
        control.start(TASK, worker_ref=WORKER)

        if len(calls) == 1:
            record = ExecutionRecord(
                attempt_id=prepared.attempt_id,
                tc_id=prepared.tc_id,
                case_version=prepared.case_version,
                target_id=prepared.target_id,
                layer="L2",
                worker_id=WORKER,
                lease_id="lease-1",
                status="FAIL",
                integrity_passed=False,
                actual_result=None,
                tool_call_refs=(),
                evidence_refs=("EVD-RAW-%s" % prepared.attempt_id,),
                assertion_ref=None,
                assertion_passed=None,
                reason="TIMEOUT",
            )
            closure = coord.diagnose(
                record=record,
                bundle=_bundle(),
                prepared=prepared,
                trust=ExecutionTrustFacts(exception_type="TimeoutError"),
            )
            assert closure.complete and closure.work_plan is not None
            diagnosis_evidence = Evidence(
                evidence_id=_stable("EVD-DIAG", prepared.attempt_id, closure.evidence_sha256),
                mission_id=MISSION,
                kind="RUNTIME_FAILURE_DIAGNOSIS",
                source_ref="runtime://diagnosis",
                content_ref=closure.evidence_ref,
                subject_refs=[TASK, prepared.attempt_id, prepared.tc_id],
                content_hash="sha256:" + closure.evidence_sha256,
            )
            exec_evidence = Evidence(
                evidence_id=_stable("EVD-EXEC", prepared.attempt_id),
                mission_id=MISSION,
                kind="RUNTIME_EXECUTION_RECORD",
                source_ref="runtime://execution",
                content_ref="evidence://%s" % prepared.attempt_id,
                subject_refs=[TASK, prepared.attempt_id],
            )
            canonical_record = ExecutionRecord(
                attempt_id=record.attempt_id,
                tc_id=record.tc_id,
                case_version=record.case_version,
                target_id=record.target_id,
                layer=record.layer,
                worker_id=record.worker_id,
                lease_id=record.lease_id,
                status=record.status,
                integrity_passed=record.integrity_passed,
                actual_result=record.actual_result,
                tool_call_refs=record.tool_call_refs,
                evidence_refs=(exec_evidence.evidence_id,),
                assertion_ref=record.assertion_ref,
                assertion_passed=record.assertion_passed,
                reason=record.reason,
            )
            artifact = Artifact(
                artifact_id=_stable("ART-EXEC", prepared.attempt_id),
                mission_id=MISSION,
                artifact_type="EXECUTION_CONCLUSION",
                producer_task_id=TASK,
                content_ref="artifact://%s" % prepared.attempt_id,
                evidence_refs=[exec_evidence.evidence_id, diagnosis_evidence.evidence_id],
            )
            control.submit_worker_output(
                WorkerOutput(
                    task_id=TASK,
                    worker_ref=WORKER,
                    artifacts=(artifact,),
                    evidence=(exec_evidence, diagnosis_evidence),
                )
            )
            loop = ExecutionClosedLoop().evaluate(
                mission_id=MISSION,
                artifact_ref=artifact.artifact_id,
                record=canonical_record,
                diagnosis=closure.diagnosis,
                recovery=closure.recovery,
                evaluator_ref="runtime-execution-gate",
            )
            accepted = control.accept_evaluation(TASK, evaluation=loop.evaluation, gaps=loop.gaps)
            return ClosedLoopExecutionResult(
                execution_record=canonical_record,
                record_artifact_id=artifact.artifact_id,
                record_evidence_id=exec_evidence.evidence_id,
                evidence_ids=(exec_evidence.evidence_id, diagnosis_evidence.evidence_id),
                loop_result=loop,
                task_state=accepted.state.value,
                runtime_worker_id=WORKER,
                runtime_lease_id="lease-1",
            )

        assert prepared.attempt_id != calls[0]
        exec_evidence = Evidence(
            evidence_id=_stable("EVD-EXEC", prepared.attempt_id),
            mission_id=MISSION,
            kind="RUNTIME_EXECUTION_RECORD",
            source_ref="runtime://execution",
            content_ref="evidence://%s" % prepared.attempt_id,
            subject_refs=[TASK, prepared.attempt_id],
        )
        record = ExecutionRecord(
            attempt_id=prepared.attempt_id,
            tc_id=prepared.tc_id,
            case_version=prepared.case_version,
            target_id=prepared.target_id,
            layer="L2",
            worker_id=WORKER,
            lease_id="lease-2",
            status="PASS",
            integrity_passed=True,
            actual_result={"code": "OK"},
            tool_call_refs=("business-action://success",),
            evidence_refs=(exec_evidence.evidence_id,),
            assertion_ref="oracle://pass",
            assertion_passed=True,
            reason=None,
        )
        artifact = Artifact(
            artifact_id=_stable("ART-EXEC", prepared.attempt_id),
            mission_id=MISSION,
            artifact_type="EXECUTION_CONCLUSION",
            producer_task_id=TASK,
            content_ref="artifact://%s" % prepared.attempt_id,
            evidence_refs=[exec_evidence.evidence_id],
        )
        control.submit_worker_output(
            WorkerOutput(
                task_id=TASK,
                worker_ref=WORKER,
                artifacts=(artifact,),
                evidence=(exec_evidence,),
            )
        )
        loop = ExecutionClosedLoop().evaluate(
            mission_id=MISSION,
            artifact_ref=artifact.artifact_id,
            record=record,
            evaluator_ref="runtime-execution-gate",
        )
        accepted = control.accept_evaluation(TASK, evaluation=loop.evaluation, gaps=loop.gaps)
        return ClosedLoopExecutionResult(
            execution_record=record,
            record_artifact_id=artifact.artifact_id,
            record_evidence_id=exec_evidence.evidence_id,
            evidence_ids=(exec_evidence.evidence_id,),
            loop_result=loop,
            task_state=accepted.state.value,
            runtime_worker_id=WORKER,
            runtime_lease_id="lease-2",
        )

    result = AutonomousExecutionLoop(
        recovery_controller=recovery_controller,
        max_cycles=3,
    ).run(
        control,
        source_task_id=TASK,
        prepared=_prepared("ATT-ROOT"),
        coordinator=coordinator,
        run_once=run_once,
    )

    assert len(result.attempts) == 2
    assert len(result.authorizations) == 1
    assert result.final_task_state == "PASS"
    assert result.stopped_reason == "EXECUTION_CONCLUSION_REACHED"
    assert result.converged is True
    assert calls[0] == "ATT-ROOT"
    assert calls[1] == result.authorizations[0].successor_attempt_id
    gaps = truth.query("rc7_gap", mission_id=MISSION)
    assert len(gaps) == 1
    assert gaps[0]["category"] == "TRANSIENT_FAILURE"
    assert gaps[0]["state"] == "RESOLVED"
