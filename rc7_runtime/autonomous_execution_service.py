"""Public RC7 execution facade with governed preparation/diagnosis/recovery.

Low-level execute_generic/execute_l3 remain compatibility surfaces for callers
that already own a verified PreparedAttempt.  The formal product entrypoints
prepare_and_execute_generic/prepare_and_execute_l3 start from the frozen Case:
Runtime resolves preconditions and data, persists immutable R1 preparation
truth, then owns execution, diagnosis, recovery planning and bounded retry.

L3 is deliberately excluded from the generic path because API truth must be
produced by the parent-controlled API runtime, never by a child-authored runner
manifest.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Optional

from rc6_runtime.capability import ToolCapabilityBroker
from rc6_runtime.preparation import PreparedAttempt

from .authority import RC7AuthorityRuntime
from .closed_loop_control import ClosedLoopControlPlane
from .controlled_l3_execution import ControlledL3ClosedLoopExecutionService
from .execution_autonomous_loop import AutonomousExecutionLoop, AutonomousExecutionLoopResult
from .execution_diagnosis import ExecutionTrustFacts
from .execution_recovery_control import ExecutionRecoveryController
from .lineage_diagnosis import LineageAwareExecutionDiagnosisCoordinator
from .preparation_control import RuntimePreparationService, RuntimePreparedAttempt
from .runtime_execution import VerifiedScriptExecutionBundle
from .runtime_execution_control import ClosedLoopRuntimeExecutionService


class AutonomousExecutionServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class PreparedAutonomousExecutionResult:
    preparation: RuntimePreparedAttempt
    execution: AutonomousExecutionLoopResult


class AutonomousClosedLoopExecutionService:
    def __init__(
        self,
        *,
        evidence_root: str,
        timeout_seconds: int = 300,
        max_cycles: int = 4,
        max_transient_retries: int = 2,
    ) -> None:
        self.evidence_root = evidence_root
        self.timeout_seconds = int(timeout_seconds)
        self.max_cycles = int(max_cycles)
        self.max_transient_retries = int(max_transient_retries)

    def _coordinator(
        self,
        *,
        authority: RC7AuthorityRuntime,
        tool_broker: ToolCapabilityBroker,
        cat_query=None,
        evidence_collectors=None,
        rca_resolver=None,
    ) -> LineageAwareExecutionDiagnosisCoordinator:
        return LineageAwareExecutionDiagnosisCoordinator(
            authority=authority,
            tool_broker=tool_broker,
            evidence_root=self.evidence_root,
            cat_query=cat_query,
            evidence_collectors=evidence_collectors,
            rca_resolver=rca_resolver,
            max_transient_retries=self.max_transient_retries,
        )

    def prepare_and_execute_generic(
        self,
        control: ClosedLoopControlPlane,
        task_id: str,
        *,
        bundle: VerifiedScriptExecutionBundle,
        attempt_id: str,
        target_id: str,
        precondition_resolvers: Mapping[str, Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]],
        data_strategies: Mapping[str, Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]],
        data_verifier: Callable[[Dict[str, Any], Dict[str, Any], Dict[str, Any]], Dict[str, Any]],
        authority: RC7AuthorityRuntime,
        tool_broker: ToolCapabilityBroker,
        oracle_evaluator: Callable[[Dict[str, Any], Dict[str, Any], Dict[str, Any]], Dict[str, Any]],
        cwd: str,
        human_gate: Optional[Callable[[Dict[str, Any]], Optional[str]]] = None,
        env: Optional[Mapping[str, str]] = None,
        diagnosis_trust: Optional[ExecutionTrustFacts] = None,
        cat_query=None,
        evidence_collectors=None,
        rca_resolver=None,
    ) -> PreparedAutonomousExecutionResult:
        if str(bundle.spec.layer).upper() == "L3":
            raise AutonomousExecutionServiceError("L3_REQUIRES_CONTROLLED_EXECUTION")
        preparation = RuntimePreparationService(evidence_root=self.evidence_root).prepare(
            control,
            task_id,
            case=bundle.frozen_case,
            attempt_id=attempt_id,
            target_id=target_id,
            precondition_resolvers=precondition_resolvers,
            data_strategies=data_strategies,
            data_verifier=data_verifier,
            human_gate=human_gate,
        )
        execution = self.execute_generic(
            control,
            task_id,
            bundle=bundle,
            prepared=preparation.prepared,
            authority=authority,
            tool_broker=tool_broker,
            oracle_evaluator=oracle_evaluator,
            cwd=cwd,
            env=env,
            diagnosis_trust=diagnosis_trust,
            cat_query=cat_query,
            evidence_collectors=evidence_collectors,
            rca_resolver=rca_resolver,
        )
        return PreparedAutonomousExecutionResult(preparation=preparation, execution=execution)

    def prepare_and_execute_l3(
        self,
        control: ClosedLoopControlPlane,
        task_id: str,
        *,
        bundle: VerifiedScriptExecutionBundle,
        attempt_id: str,
        target_id: str,
        precondition_resolvers: Mapping[str, Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]],
        data_strategies: Mapping[str, Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]],
        data_verifier: Callable[[Dict[str, Any], Dict[str, Any], Dict[str, Any]], Dict[str, Any]],
        authority: RC7AuthorityRuntime,
        tool_broker: ToolCapabilityBroker,
        target_base_url: str,
        cwd: str,
        human_gate: Optional[Callable[[Dict[str, Any]], Optional[str]]] = None,
        env: Optional[Mapping[str, str]] = None,
        diagnosis_trust: Optional[ExecutionTrustFacts] = None,
        cat_query=None,
        evidence_collectors=None,
        rca_resolver=None,
    ) -> PreparedAutonomousExecutionResult:
        if str(bundle.spec.layer).upper() != "L3":
            raise AutonomousExecutionServiceError("CONTROLLED_L3_EXECUTION_REQUIRES_L3_SPEC")
        preparation = RuntimePreparationService(evidence_root=self.evidence_root).prepare(
            control,
            task_id,
            case=bundle.frozen_case,
            attempt_id=attempt_id,
            target_id=target_id,
            precondition_resolvers=precondition_resolvers,
            data_strategies=data_strategies,
            data_verifier=data_verifier,
            human_gate=human_gate,
        )
        execution = self.execute_l3(
            control,
            task_id,
            bundle=bundle,
            prepared=preparation.prepared,
            authority=authority,
            tool_broker=tool_broker,
            target_base_url=target_base_url,
            cwd=cwd,
            env=env,
            diagnosis_trust=diagnosis_trust,
            cat_query=cat_query,
            evidence_collectors=evidence_collectors,
            rca_resolver=rca_resolver,
        )
        return PreparedAutonomousExecutionResult(preparation=preparation, execution=execution)

    def execute_generic(
        self,
        control: ClosedLoopControlPlane,
        task_id: str,
        *,
        bundle: VerifiedScriptExecutionBundle,
        prepared: PreparedAttempt,
        authority: RC7AuthorityRuntime,
        tool_broker: ToolCapabilityBroker,
        oracle_evaluator: Callable[[Dict[str, Any], Dict[str, Any], Dict[str, Any]], Dict[str, Any]],
        cwd: str,
        env: Optional[Mapping[str, str]] = None,
        diagnosis_trust: Optional[ExecutionTrustFacts] = None,
        cat_query=None,
        evidence_collectors=None,
        rca_resolver=None,
    ) -> AutonomousExecutionLoopResult:
        if str(bundle.spec.layer).upper() == "L3":
            raise AutonomousExecutionServiceError("L3_REQUIRES_CONTROLLED_EXECUTION")
        coordinator = self._coordinator(
            authority=authority,
            tool_broker=tool_broker,
            cat_query=cat_query,
            evidence_collectors=evidence_collectors,
            rca_resolver=rca_resolver,
        )
        service = ClosedLoopRuntimeExecutionService(
            evidence_root=self.evidence_root,
            timeout_seconds=self.timeout_seconds,
        )
        loop = AutonomousExecutionLoop(
            recovery_controller=ExecutionRecoveryController(evidence_root=self.evidence_root),
            max_cycles=self.max_cycles,
        )

        def run_once(current: PreparedAttempt, current_coordinator: LineageAwareExecutionDiagnosisCoordinator):
            attempt_env = dict(env or {})
            attempt_env["RC7_EXECUTION_ATTEMPT_ID"] = current.attempt_id
            return service.execute_task(
                control,
                task_id,
                bundle=bundle,
                prepared=current,
                authority=authority,
                tool_broker=tool_broker,
                oracle_evaluator=oracle_evaluator,
                cwd=cwd,
                env=attempt_env,
                diagnosis_coordinator=current_coordinator,
                diagnosis_trust=diagnosis_trust,
            )

        return loop.run(
            control,
            source_task_id=task_id,
            prepared=prepared,
            coordinator=coordinator,
            run_once=run_once,
        )

    def execute_l3(
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
        diagnosis_trust: Optional[ExecutionTrustFacts] = None,
        cat_query=None,
        evidence_collectors=None,
        rca_resolver=None,
    ) -> AutonomousExecutionLoopResult:
        if str(bundle.spec.layer).upper() != "L3":
            raise AutonomousExecutionServiceError("CONTROLLED_L3_EXECUTION_REQUIRES_L3_SPEC")
        coordinator = self._coordinator(
            authority=authority,
            tool_broker=tool_broker,
            cat_query=cat_query,
            evidence_collectors=evidence_collectors,
            rca_resolver=rca_resolver,
        )
        service = ControlledL3ClosedLoopExecutionService(
            evidence_root=self.evidence_root,
            timeout_seconds=self.timeout_seconds,
        )
        loop = AutonomousExecutionLoop(
            recovery_controller=ExecutionRecoveryController(evidence_root=self.evidence_root),
            max_cycles=self.max_cycles,
        )

        def run_once(current: PreparedAttempt, current_coordinator: LineageAwareExecutionDiagnosisCoordinator):
            attempt_env = dict(env or {})
            attempt_env["RC7_EXECUTION_ATTEMPT_ID"] = current.attempt_id
            return service.execute_task(
                control,
                task_id,
                bundle=bundle,
                prepared=current,
                authority=authority,
                tool_broker=tool_broker,
                target_base_url=target_base_url,
                cwd=cwd,
                env=attempt_env,
                diagnosis_coordinator=current_coordinator,
                diagnosis_trust=diagnosis_trust,
            )

        return loop.run(
            control,
            source_task_id=task_id,
            prepared=prepared,
            coordinator=coordinator,
            run_once=run_once,
        )
