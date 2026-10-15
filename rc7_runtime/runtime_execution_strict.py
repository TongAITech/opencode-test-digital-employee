"""Strict production facade for RC7 runtime-owned execution.

The execution identity is minted immediately before formal execution, therefore
ToolCapabilityBroker visibility/permission must be bound to that exact identity
at runtime.  Target readiness and real probe evidence still have to exist first;
this facade only performs the identity-specific visibility/permission binding
that cannot be precomputed before the worker id exists.
"""

from __future__ import annotations

import uuid
from typing import Any, Callable, Dict, Mapping, Optional

from rc6_runtime.automation import JUnitRunnerAdapter, PytestRunnerAdapter
from rc6_runtime.capability import ToolCapabilityBroker
from rc6_runtime.execution import ExecutionRuntime
from rc6_runtime.preparation import PreparedAttempt

from .authority import RC7AuthorityRuntime
from .runtime_execution import (
    RuntimeExecutionError,
    RuntimeOwnedExecutionCoordinator,
    RuntimeOwnedExecutionResult,
    VerifiedScriptExecutionBundle,
    _EvidenceBackedProcessHarness,
)


class StrictRuntimeOwnedExecutionCoordinator(RuntimeOwnedExecutionCoordinator):
    def execute(
        self,
        *,
        bundle: VerifiedScriptExecutionBundle,
        prepared: PreparedAttempt,
        authority: RC7AuthorityRuntime,
        tool_broker: ToolCapabilityBroker,
        oracle_evaluator: Callable[[Dict[str, Any], Dict[str, Any], Dict[str, Any]], Dict[str, Any]],
        cwd: str,
        env: Optional[Mapping[str, str]] = None,
    ) -> RuntimeOwnedExecutionResult:
        if prepared.tc_id != bundle.spec.tc_id or prepared.case_version != bundle.spec.case_version:
            raise RuntimeExecutionError("PREPARED_ATTEMPT_SCRIPT_CASE_MISMATCH")
        if prepared.status != "PREPARED":
            raise RuntimeExecutionError("FORMAL_EXECUTION_REQUIRES_PREPARED_ATTEMPT")

        profile = self.profiles.get(bundle.spec.layer)
        identity = authority.issue_identity(
            profile.role,
            "EXECUTION",
            profile.layer,
            0,
            "runtime-execution-" + uuid.uuid4().hex,
        )
        lease = authority.issue_lease(
            identity.worker_id,
            "case:%s@%s" % (bundle.spec.tc_id, bundle.spec.case_version),
            ExecutionRuntime.REQUIRED_ARTIFACTS,
            profile.required_tools,
            ttl_seconds=max(self.timeout_seconds + 120, 300),
        )

        # Discovery/executable/registration/probe/target readiness must already
        # exist. Only dynamic worker binding is done here after the signed lease
        # identifies exactly which runtime identity may use the tool.
        for tool_id in profile.required_tools:
            try:
                tool_broker.bind_worker(
                    tool_id,
                    identity.worker_id,
                    visible=True,
                    permitted=True,
                )
            except Exception as exc:
                raise RuntimeExecutionError(
                    "EXECUTION_TOOL_RUNTIME_BIND_FAILED:%s:%s" % (tool_id, exc)
                ) from exc

        admission = tool_broker.admit(
            identity.worker_id,
            profile.required_tools,
            prepared.target_id,
        )
        if not admission.ready:
            raise RuntimeExecutionError(
                "EXECUTION_TOOL_ADMISSION_NOT_READY:%s" % admission.blocked
            )

        if bundle.spec.runner_type == "PYTEST":
            runner = PytestRunnerAdapter(timeout_seconds=self.timeout_seconds)
        elif bundle.spec.runner_type == "JUNIT":
            runner = JUnitRunnerAdapter(timeout_seconds=self.timeout_seconds)
        else:
            raise RuntimeExecutionError(
                "FORMAL_RUNNER_NOT_IMPLEMENTED:%s" % bundle.spec.runner_type
            )
        runner.harness = _EvidenceBackedProcessHarness(
            evidence_root=self.evidence_root,
            timeout_seconds=self.timeout_seconds,
        )
        runtime = ExecutionRuntime(
            authority=authority,
            tool_broker=tool_broker,
            oracle_evaluator=oracle_evaluator,
        )
        record = runtime.execute_with_runner(
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
        return RuntimeOwnedExecutionResult(
            record=record,
            runtime_worker_id=identity.worker_id,
            runtime_lease_id=lease.lease_id,
            runner_type=bundle.spec.runner_type,
        )
