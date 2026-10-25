"""Strict RC7 L3 control-plane execution using parent-owned API receipts."""

from __future__ import annotations

import hashlib
import uuid
from typing import Mapping, Optional, Tuple

from rc6_runtime.automation import JUnitRunnerAdapter, PytestRunnerAdapter
from rc6_runtime.capability import ToolCapabilityBroker
from rc6_runtime.diagnosis import DiagnosisResult
from rc6_runtime.execution import ExecutionRuntime
from rc6_runtime.preparation import PreparedAttempt

from .authority import RC7AuthorityRuntime
from .closed_loop_control import ClosedLoopControlPlane
from .control_plane import WorkerOutput
from .controlled_api_execution_strict import StrictControlledApiRunnerAdapter
from .execution_diagnosis import ExecutionDiagnosisCoordinator, ExecutionTrustFacts
from .execution_loop import ExecutionClosedLoop
from .models import Evidence, TaskStatus
from .oracle_runtime import DeterministicOracleRuntime
from .real_executor_provenance import (
    contract_enabled as real_executor_contract_enabled,
    record_successful_execution_invocation,
)
from .runtime_execution import RuntimeExecutionError, VerifiedScriptExecutionBundle, _EvidenceBackedProcessHarness
from .runtime_execution_control import ClosedLoopExecutionResult, ClosedLoopRuntimeExecutionService


class ControlledL3ClosedLoopExecutionService(ClosedLoopRuntimeExecutionService):
    """Formal L3 execution; child manifest is never API truth."""

    @staticmethod
    def _parent_api_call_refs(record) -> Tuple[str, ...]:
        return tuple(
            ref for ref in tuple(record.tool_call_refs or ())
            if str(ref).startswith("api-runtime://APIREC-")
        )

    def _persist_real_api_provenance(
        self,
        control: ClosedLoopControlPlane,
        *,
        task_id: str,
        prepared: PreparedAttempt,
        runtime_worker_id: str,
        record,
    ) -> Tuple[str, ...]:
        """Promote only parent-owned API receipts into unified executor truth.

        StrictControlledApiRunnerAdapter has already removed child-authored
        ``api-runtime`` claims before this method runs.  We deliberately do not
        create provenance when no parent receipt exists: the final real-executor
        gate must fail closed instead of accepting a runner self-report.
        """
        if not real_executor_contract_enabled(control.truth, control.mission_id):
            return ()
        evidence_ids = []
        for call_ref in self._parent_api_call_refs(record):
            evidence = record_successful_execution_invocation(
                control.truth,
                evidence_root=str(self.evidence_root),
                mission_id=control.mission_id,
                task_id=task_id,
                attempt_id=prepared.attempt_id,
                runtime_worker_id=runtime_worker_id,
                layer="L3",
                target_id=prepared.target_id,
                tool_name="api-runtime",
                invocation_ref=call_ref,
                result={
                    "call_ref": call_ref,
                    "status": str(record.status),
                    "actual_result": record.actual_result,
                    "evidence_refs": list(record.evidence_refs or ()),
                },
            )
            evidence_ids.append(evidence.evidence_id)
        return tuple(evidence_ids)

    def execute_task(
        self,
        control: ClosedLoopControlPlane,
        task_id: str,
        *,
        bundle: VerifiedScriptExecutionBundle,
        prepared: PreparedAttempt,
        authority: RC7AuthorityRuntime,
        tool_broker: ToolCapabilityBroker,
        target_base_url: str,
        cwd: str,
        env: Optional[Mapping[str, str]] = None,
        diagnosis=None,
        recovery=None,
        diagnosis_coordinator: Optional[ExecutionDiagnosisCoordinator] = None,
        diagnosis_trust: Optional[ExecutionTrustFacts] = None,
    ) -> ClosedLoopExecutionResult:
        task = control.scheduler.task(task_id)
        if task.node != "EXECUTION":
            raise RuntimeExecutionError("FORMAL_EXECUTION_TASK_NODE_MISMATCH")
        if task.state != TaskStatus.READY:
            raise RuntimeExecutionError("FORMAL_EXECUTION_TASK_NOT_READY")
        if bundle.spec.layer != "L3":
            raise RuntimeExecutionError("CONTROLLED_API_EXECUTION_IS_L3_ONLY")
        if prepared.tc_id != bundle.spec.tc_id or prepared.case_version != bundle.spec.case_version:
            raise RuntimeExecutionError("PREPARED_ATTEMPT_SCRIPT_CASE_MISMATCH")
        if prepared.status != "PREPARED":
            raise RuntimeExecutionError("FORMAL_EXECUTION_REQUIRES_PREPARED_ATTEMPT")
        DeterministicOracleRuntime.validate_contract(prepared.oracle_snapshot)

        runtime = ExecutionRuntime(
            authority=authority,
            tool_broker=tool_broker,
            oracle_evaluator=DeterministicOracleRuntime(),
        )
        profile = runtime.profiles.get("L3")
        identity = authority.issue_identity(
            profile.role,
            "EXECUTION",
            profile.layer,
            0,
            "runtime-controlled-l3-" + uuid.uuid4().hex,
        )
        lease = authority.issue_lease(
            identity.worker_id,
            "case:%s@%s" % (bundle.spec.tc_id, bundle.spec.case_version),
            ExecutionRuntime.REQUIRED_ARTIFACTS,
            profile.required_tools,
            ttl_seconds=max(self.timeout_seconds + 120, 300),
        )
        for tool_id in profile.required_tools:
            try:
                tool_broker.bind_worker(tool_id, identity.worker_id, visible=True, permitted=True)
            except Exception as exc:
                raise RuntimeExecutionError(
                    "EXECUTION_TOOL_RUNTIME_BIND_FAILED:%s:%s" % (tool_id, exc)
                ) from exc
        admission = tool_broker.admit(identity.worker_id, profile.required_tools, prepared.target_id)
        if not admission.ready:
            raise RuntimeExecutionError("EXECUTION_TOOL_ADMISSION_NOT_READY:%s" % admission.blocked)

        leased = control.lease_next(worker_ref=identity.worker_id, capabilities=("test_execution",))
        if leased is None or leased.task_id != task_id:
            raise RuntimeExecutionError("FORMAL_EXECUTION_SCHEDULER_LEASE_MISMATCH")
        control.start(task_id, worker_ref=identity.worker_id)

        if bundle.spec.runner_type == "PYTEST":
            delegate = PytestRunnerAdapter(timeout_seconds=self.timeout_seconds)
        elif bundle.spec.runner_type == "JUNIT":
            delegate = JUnitRunnerAdapter(timeout_seconds=self.timeout_seconds)
        else:
            raise RuntimeExecutionError("FORMAL_RUNNER_NOT_IMPLEMENTED:%s" % bundle.spec.runner_type)
        delegate.harness = _EvidenceBackedProcessHarness(
            evidence_root=str(self.evidence_root),
            timeout_seconds=self.timeout_seconds,
        )
        runner = StrictControlledApiRunnerAdapter(
            delegate=delegate,
            target_base_url=target_base_url,
            evidence_root=str(self.evidence_root),
            attempt_id=prepared.attempt_id,
            proxy_timeout_seconds=min(self.timeout_seconds, 60),
        )
        raw_record = runtime.execute_with_runner(
            case=bundle.frozen_case,
            executable_spec=bundle.spec,
            script=bundle.script,
            validation=bundle.validation,
            prepared=prepared,
            worker_id=identity.worker_id,
            lease_id=lease.lease_id,
            runner=runner,
            cwd=cwd,
            env=env,
        )
        provenance_evidence_ids = self._persist_real_api_provenance(
            control,
            task_id=task_id,
            prepared=prepared,
            runtime_worker_id=identity.worker_id,
            record=raw_record,
        )
        record, artifact, record_evidence, evidence = self._persistable_output(
            control,
            task_id=task_id,
            bundle=bundle,
            raw_record=raw_record,
        )

        diagnostic_evidence = None
        effective_diagnosis = diagnosis
        effective_recovery = recovery
        if effective_diagnosis is None and effective_recovery is None and str(record.status).upper() != "PASS":
            coordinator = diagnosis_coordinator or ExecutionDiagnosisCoordinator(
                authority=authority,
                tool_broker=tool_broker,
                evidence_root=str(self.evidence_root),
            )
            closure = coordinator.diagnose(
                record=record,
                bundle=bundle,
                prepared=prepared,
                trust=diagnosis_trust,
            )
            if closure.evidence_ref and closure.evidence_sha256:
                evidence_id = "EVD-EXEC-DIAG-%s" % hashlib.sha256(
                    (control.mission_id + "\x1f" + record.attempt_id + "\x1f" + closure.evidence_sha256).encode("utf-8")
                ).hexdigest()[:20]
                diagnostic_evidence = Evidence(
                    evidence_id=evidence_id,
                    mission_id=control.mission_id,
                    kind="RUNTIME_FAILURE_DIAGNOSIS",
                    source_ref="runtime://execution-diagnosis",
                    content_ref=closure.evidence_ref,
                    subject_refs=[task_id, record.attempt_id, record.tc_id],
                    content_hash="sha256:" + closure.evidence_sha256,
                )
            if closure.complete and closure.diagnosis is not None:
                effective_diagnosis = DiagnosisResult(
                    diagnosis_id=closure.diagnosis.diagnosis_id,
                    attempt_id=closure.diagnosis.attempt_id,
                    failure_class=closure.diagnosis.failure_class,
                    evidence_refs=tuple(
                        dict.fromkeys(
                            tuple(record.evidence_refs)
                            + ((diagnostic_evidence.evidence_id,) if diagnostic_evidence is not None else ())
                        )
                    ),
                    cat_required=closure.diagnosis.cat_required,
                    cat_queried=closure.diagnosis.cat_queried,
                    rationale=closure.diagnosis.rationale,
                    classifier_ref=closure.diagnosis.classifier_ref,
                    failure_signature=closure.diagnosis.failure_signature,
                    root_cause_candidate=closure.diagnosis.root_cause_candidate,
                )
                effective_recovery = closure.recovery

        output_evidence = tuple(evidence) + (record_evidence,)
        if diagnostic_evidence is not None:
            output_evidence = output_evidence + (diagnostic_evidence,)
        control.submit_worker_output(
            WorkerOutput(
                task_id=task_id,
                worker_ref=identity.worker_id,
                artifacts=(artifact,),
                evidence=output_evidence,
            )
        )
        loop_result = ExecutionClosedLoop().evaluate(
            mission_id=control.mission_id,
            artifact_ref=artifact.artifact_id,
            record=record,
            diagnosis=effective_diagnosis,
            recovery=effective_recovery,
            evaluator_ref="rc7-controlled-l3-runtime-execution-gate",
        )
        accepted = control.accept_evaluation(
            task_id,
            evaluation=loop_result.evaluation,
            gaps=loop_result.gaps,
        )
        persisted_evidence_ids = tuple(item.evidence_id for item in evidence) + (record_evidence.evidence_id,) + provenance_evidence_ids
        if diagnostic_evidence is not None:
            persisted_evidence_ids = persisted_evidence_ids + (diagnostic_evidence.evidence_id,)
        return ClosedLoopExecutionResult(
            execution_record=record,
            record_artifact_id=artifact.artifact_id,
            record_evidence_id=record_evidence.evidence_id,
            evidence_ids=persisted_evidence_ids,
            loop_result=loop_result,
            task_state=accepted.state.value,
            runtime_worker_id=identity.worker_id,
            runtime_lease_id=lease.lease_id,
        )
