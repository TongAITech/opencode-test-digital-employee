"""Deterministic RecoveryDecision -> RC7 recovery work planning.

A retry flag is not permission to blindly re-run.  RC7 distinguishes direct
successor attempts, re-preparation, upstream repair and terminal handoffs.  The
planner is side-effect free; later schedulers/executors consume this canonical
plan and remain bound to the original Diagnosis/Attempt evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from rc6_runtime.diagnosis import RecoveryDecision
from rc6_runtime.preparation import PreparedAttempt


class RecoveryPlanningError(RuntimeError):
    pass


@dataclass(frozen=True)
class RecoveryWorkPlan:
    diagnosis_id: str
    source_attempt_id: str
    action: str
    mode: str
    target_node: str
    retry_allowed: bool
    reprepare_required: bool
    terminal: bool
    successor_attempt_id: Optional[str]
    reason: str


_DIRECT_RETRY = {"RETRY_SAME_STEP", "CONTROLLED_REPEAT"}
_REPREPARE = {
    "REAUTH": "RUNTIME",
    "RESEARCH_OR_REBUILD_DATA": "SCRIPT_READINESS",
    "RECONSTRUCT_PRECONDITION": "SCRIPT_READINESS",
}
_UPSTREAM_REPAIR = {
    "REPAIR_SCRIPT": "SCRIPT_READINESS",
    "REOPEN_EXECUTABLE_SPEC": "SCRIPT_READINESS",
    "RECONCILE_ROUTE_BINDING": "CODE_ANALYSIS",
    "REPAIR_TOOL_BINDING": "RUNTIME",
    "REQUALIFY_TARGET": "RUNTIME",
    "REPAIR_DEPENDENCY_BINDING": "RUNTIME",
}
_TERMINAL = {
    "PRODUCT_DEFECT": "DEFECT",
    "ORACLE_CHANGE_REQUEST": "TEST_DESIGN",
    "MANUAL_REQUIRED": "HUMAN_GATE",
    "RETRY_BUDGET_EXHAUSTED": "RUNTIME",
    "BLOCKED_DIAGNOSIS": "RUNTIME",
}


class ExecutionRecoveryPlanner:
    def compile(self, decision: RecoveryDecision) -> RecoveryWorkPlan:
        action = str(decision.action).upper()
        if action in _DIRECT_RETRY:
            self._require_retry_identity(decision)
            if decision.reprepare_allowed:
                raise RecoveryPlanningError("DIRECT_RETRY_CANNOT_REQUIRE_REPREPARATION")
            return self._plan(decision, "DIRECT_RETRY", "EXECUTION", False)
        if action in _REPREPARE:
            self._require_retry_identity(decision)
            if not decision.reprepare_allowed:
                raise RecoveryPlanningError("REPREPARE_ACTION_MUST_REQUIRE_REPREPARATION")
            return self._plan(decision, "REPREPARE_THEN_RETRY", _REPREPARE[action], True)
        if action in _UPSTREAM_REPAIR:
            self._require_retry_identity(decision)
            return self._plan(
                decision,
                "UPSTREAM_REPAIR_THEN_RETRY",
                _UPSTREAM_REPAIR[action],
                bool(decision.reprepare_allowed),
            )
        if action in _TERMINAL:
            if decision.retry_allowed or decision.next_attempt_id is not None:
                raise RecoveryPlanningError("TERMINAL_RECOVERY_CANNOT_CREATE_RETRY")
            if not decision.terminal:
                raise RecoveryPlanningError("TERMINAL_RECOVERY_FLAG_REQUIRED")
            return self._plan(decision, "TERMINAL", _TERMINAL[action], False)
        raise RecoveryPlanningError("RECOVERY_ACTION_NOT_PLANNED:%s" % action)

    @staticmethod
    def _require_retry_identity(decision: RecoveryDecision) -> None:
        if not decision.retry_allowed:
            raise RecoveryPlanningError("RECOVERY_RETRY_PERMISSION_REQUIRED")
        if decision.terminal:
            raise RecoveryPlanningError("TERMINAL_RECOVERY_CANNOT_RETRY")
        if not isinstance(decision.next_attempt_id, str) or not decision.next_attempt_id:
            raise RecoveryPlanningError("RECOVERY_SUCCESSOR_ATTEMPT_REQUIRED")
        if decision.next_attempt_id == decision.attempt_id:
            raise RecoveryPlanningError("RECOVERY_SUCCESSOR_MUST_BE_NEW_ATTEMPT")

    @staticmethod
    def _plan(
        decision: RecoveryDecision,
        mode: str,
        target_node: str,
        reprepare_required: bool,
    ) -> RecoveryWorkPlan:
        return RecoveryWorkPlan(
            diagnosis_id=decision.diagnosis_id,
            source_attempt_id=decision.attempt_id,
            action=decision.action,
            mode=mode,
            target_node=target_node,
            retry_allowed=bool(decision.retry_allowed),
            reprepare_required=reprepare_required,
            terminal=bool(decision.terminal),
            successor_attempt_id=decision.next_attempt_id,
            reason=decision.reason,
        )

    @staticmethod
    def compile_successor_prepared_attempt(
        prepared: PreparedAttempt,
        plan: RecoveryWorkPlan,
    ) -> PreparedAttempt:
        if plan.mode not in {"DIRECT_RETRY", "UPSTREAM_REPAIR_THEN_RETRY"}:
            raise RecoveryPlanningError("PREPARED_ATTEMPT_REUSE_NOT_ALLOWED_FOR_MODE:%s" % plan.mode)
        if plan.reprepare_required:
            raise RecoveryPlanningError("REPREPARATION_REQUIRED_BEFORE_SUCCESSOR")
        if not plan.successor_attempt_id:
            raise RecoveryPlanningError("RECOVERY_SUCCESSOR_ATTEMPT_REQUIRED")
        return PreparedAttempt(
            status=prepared.status,
            attempt_id=plan.successor_attempt_id,
            tc_id=prepared.tc_id,
            case_version=prepared.case_version,
            target_id=prepared.target_id,
            precondition_evidence=tuple(prepared.precondition_evidence),
            initial_state_bindings=dict(prepared.initial_state_bindings),
            input_data_bindings=dict(prepared.input_data_bindings),
            binding_evidence=tuple(prepared.binding_evidence),
            cleanup_policy=dict(prepared.cleanup_policy),
            oracle_snapshot=dict(prepared.oracle_snapshot),
        )
