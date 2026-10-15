"""Strict RC7 L3 control-plane execution using parent-owned API receipts."""

from __future__ import annotations

import uuid
from typing import Mapping, Optional

from rc6_runtime.automation import JUnitRunnerAdapter, PytestRunnerAdapter
from rc6_runtime.capability import ToolCapabilityBroker
from rc6_runtime.execution import ExecutionRuntime
from rc6_runtime.preparation import PreparedAttempt

from .authority import RC7AuthorityRuntime
from .closed_loop_control import ClosedLoopControlPlane
from .control_plane import WorkerOutput
from .controlled_api_execution import ControlledApiRunnerAdapter
from .execution_loop import ExecutionClosedLoop
from .models import TaskStatus
from .oracle_runtime import DeterministicOracleRuntime
from .runtime_execution import RuntimeExecutionError, VerifiedScriptExecutionBundle, _EvidenceBackedProcessHarness
from .runtime_execution_control import ClosedLoopExecutionResult, ClosedLoopRuntimeExecutionService


class ControlledL3ClosedLoopExecutionService(ClosedLoopRuntimeExecutionService):
    """Formal L3 execution; child manifest is never API truth."""

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

        oracle = DeterministicOracleRuntime()
        runtime = ExecutionRuntime(
            authority=authority,
            tool_broker=tool_broker,
            oracle_evaluator=oracle,
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
        runner = ControlledApiRunnerAdapter(
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
        record, artifact, record_evidence, evidence = self._persistable_output(
            control,
            task_id=task_id,
            bundle=bundle,
            raw_record=raw_record,
        )
        control.submit_worker_output(
            WorkerOutput(
                task_id=task_id,
                worker_ref=identity.worker_id,
                artifacts=(artifact,),
                evidence=tuple(evidence) + (record_evidence,),
            )
        )
        loop_result = ExecutionClosedLoop().evaluate(
            mission_id=control.mission_id,
            artifact_ref=artifact.artifact_id,
            record=record,
            diagnosis=diagnosis,
            recovery=recovery,
            evaluator_ref="rc7-controlled-l3-runtime-execution-gate",
        )
        accepted = control.accept_evaluation(
            task_id,
            evaluation=loop_result.evaluation,
            gaps=loop_result.gaps,
        )
        return ClosedLoopExecutionResult(
            execution_record=record,
            record_artifact_id=artifact.artifact_id,
            record_evidence_id=record_evidence.evidence_id,
            evidence_ids=tuple(item.evidence_id for item in evidence) + (record_evidence.evidence_id,),
            loop_result=loop_result,
            task_state=accepted.state.value,
            runtime_worker_id=identity.worker_id,
            runtime_lease_id=lease.lease_id,
        )
