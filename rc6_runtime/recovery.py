"""RC6 Execution Closure Overlay: executable recovery and convergence.

Recovery decisions are not sufficient. This module executes bounded recovery
through explicit adapters, appends a fresh attempt for every rerunnable action,
prevents repeated identical failure signatures from blind retry loops, and
computes a small terminal-state vocabulary.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import time
import uuid
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

from .diagnosis import (
    AttemptHistory,
    AttemptHistoryEntry,
    DiagnosisResult,
    FailureContext,
    RecoveryDecision,
)


class RecoveryActionError(RuntimeError):
    pass


TERMINAL_STATES = {
    "PASS",
    "PRODUCT_DEFECT_CONFIRMED",
    "MANUAL_REQUIRED",
    "BLOCKED_EXTERNAL",
    "RETRY_BUDGET_EXHAUSTED",
    "UNKNOWN_ROOT_CAUSE",
}


@dataclass(frozen=True)
class ExecutionBudgets:
    max_execution_attempts: int = 5
    max_script_repairs: int = 2
    max_data_rebuilds: int = 2
    max_auth_refreshes: int = 2
    max_route_repairs: int = 2
    max_tool_repairs: int = 2
    max_environment_repairs: int = 1
    max_dependency_repairs: int = 2
    max_flaky_repeats: int = 3
    max_same_signature_repeats: int = 1

    def __post_init__(self) -> None:
        for key, value in asdict(self).items():
            if not isinstance(value, int) or value < 0:
                raise ValueError("INVALID_EXECUTION_BUDGET:%s" % key)
        if self.max_execution_attempts < 1:
            raise ValueError("max_execution_attempts must be >= 1")


@dataclass(frozen=True)
class RecoveryActionResult:
    recovery_action_id: str
    action: str
    prior_attempt_id: str
    next_attempt_id: Optional[str]
    status: str
    evidence_refs: Tuple[str, ...]
    output_refs: Tuple[str, ...]
    verified: bool
    terminal_status: Optional[str] = None


@dataclass(frozen=True)
class ConvergenceDecision:
    allow_recovery: bool
    terminal_status: Optional[str]
    reason: str


class ExecutionConvergenceController:
    """Runtime-owned budgets and repeated-signature loop breaker."""

    _BUDGET_BY_CLASS = {
        "SCRIPT": "max_script_repairs",
        "DATA": "max_data_rebuilds",
        "PRECONDITION": "max_data_rebuilds",
        "AUTH": "max_auth_refreshes",
        "ROUTE": "max_route_repairs",
        "TOOL": "max_tool_repairs",
        "ENVIRONMENT": "max_environment_repairs",
        "DEPENDENCY": "max_dependency_repairs",
        "FLAKY": "max_flaky_repeats",
    }

    def __init__(self, history: AttemptHistory, budgets: Optional[ExecutionBudgets] = None):
        self.history = history
        self.budgets = budgets or ExecutionBudgets()
        self._recovery_counts: Dict[str, int] = {}
        self._last_signature_id: Optional[str] = None
        self._same_signature_repeats = 0

    def evaluate_failure(self, diagnosis: DiagnosisResult) -> ConvergenceDecision:
        failure_class = diagnosis.failure_class
        if failure_class == "PRODUCT":
            return ConvergenceDecision(False, "PRODUCT_DEFECT_CONFIRMED", "PRODUCT_IS_TERMINAL")
        if failure_class == "UNKNOWN":
            return ConvergenceDecision(False, "UNKNOWN_ROOT_CAUSE", "UNKNOWN_FAILS_CLOSED")
        if failure_class == "ORACLE":
            return ConvergenceDecision(False, "MANUAL_REQUIRED", "ORACLE_CHANGE_REQUIRES_REVIEW")

        if len(self.history.entries()) >= self.budgets.max_execution_attempts:
            return ConvergenceDecision(False, "RETRY_BUDGET_EXHAUSTED", "MAX_EXECUTION_ATTEMPTS_REACHED")

        signature_id = diagnosis.failure_signature.signature_id if diagnosis.failure_signature else None
        if signature_id:
            if signature_id == self._last_signature_id:
                self._same_signature_repeats += 1
            else:
                self._last_signature_id = signature_id
                self._same_signature_repeats = 0
            if self._same_signature_repeats > self.budgets.max_same_signature_repeats:
                return ConvergenceDecision(False, "MANUAL_REQUIRED", "SAME_FAILURE_SIGNATURE_REPEATED")

        budget_name = self._BUDGET_BY_CLASS.get(failure_class)
        if budget_name:
            used = self._recovery_counts.get(failure_class, 0)
            allowed = getattr(self.budgets, budget_name)
            if used >= allowed:
                return ConvergenceDecision(False, "RETRY_BUDGET_EXHAUSTED", "%s_EXHAUSTED" % budget_name.upper())
        return ConvergenceDecision(True, None, "RECOVERY_ALLOWED")

    def record_recovery(self, failure_class: str) -> None:
        self._recovery_counts[failure_class] = self._recovery_counts.get(failure_class, 0) + 1

    @staticmethod
    def pass_result() -> ConvergenceDecision:
        return ConvergenceDecision(False, "PASS", "EXECUTION_AND_ORACLE_PASSED")


class RecoveryActionExecutor:
    """Execute deterministic recovery actions through real runtime adapters.

    Adapters are injected runtime surfaces for Script repair/validation, data,
    4A/auth, route/tool/target qualification, dependency repair and controlled
    repeat. A successful rerunnable action MUST return evidence and verification
    and the executor MUST append a new Attempt before re-execution.
    """

    TERMINAL_ACTIONS = {
        "PRODUCT_DEFECT": "PRODUCT_DEFECT_CONFIRMED",
        "ORACLE_CHANGE_REQUEST": "MANUAL_REQUIRED",
        "MANUAL_REQUIRED": "MANUAL_REQUIRED",
        "BLOCKED_DIAGNOSIS": "UNKNOWN_ROOT_CAUSE",
        "RETRY_BUDGET_EXHAUSTED": "RETRY_BUDGET_EXHAUSTED",
    }

    def __init__(
        self,
        *,
        history: AttemptHistory,
        adapters: Optional[Mapping[str, Callable[[FailureContext, DiagnosisResult, RecoveryDecision], Dict[str, Any]]]] = None,
        convergence: Optional[ExecutionConvergenceController] = None,
    ):
        self.history = history
        self.adapters = dict(adapters or {})
        self.convergence = convergence or ExecutionConvergenceController(history)

    def _append_successor(
        self,
        *,
        decision: RecoveryDecision,
        prior: AttemptHistoryEntry,
        diagnosis: DiagnosisResult,
        evidence_refs: Tuple[str, ...],
    ) -> AttemptHistoryEntry:
        if not decision.next_attempt_id:
            raise RecoveryActionError("NEW_ATTEMPT_REQUIRED_FOR_RECOVERY")
        if self.history.get(decision.next_attempt_id) is not None:
            raise RecoveryActionError("NEXT_ATTEMPT_ALREADY_EXISTS")
        entry = AttemptHistoryEntry(
            attempt_id=decision.next_attempt_id,
            parent_attempt_id=prior.attempt_id,
            tc_id=prior.tc_id,
            case_version=prior.case_version,
            target_id=prior.target_id,
            layer=prior.layer,
            status="RECOVERY_READY",
            evidence_refs=evidence_refs,
            recorded_at=int(time.time()),
            failure_signature_id=diagnosis.failure_signature.signature_id if diagnosis.failure_signature else None,
        )
        self.history.append(entry)
        return entry

    @staticmethod
    def _terminal_output_refs(
        context: FailureContext,
        diagnosis: DiagnosisResult,
        action: str,
    ) -> Tuple[str, ...]:
        if action == "PRODUCT_DEFECT":
            signature = diagnosis.failure_signature.signature_id if diagnosis.failure_signature else "no-signature"
            return ("defect-candidate://%s/%s" % (context.attempt_id, signature),)
        if action == "ORACLE_CHANGE_REQUEST":
            return ("oracle-change-request://%s" % context.attempt_id,)
        return ()

    def execute(
        self,
        *,
        context: FailureContext,
        diagnosis: DiagnosisResult,
        decision: RecoveryDecision,
    ) -> RecoveryActionResult:
        if diagnosis.attempt_id != context.attempt_id or decision.attempt_id != context.attempt_id:
            raise RecoveryActionError("RECOVERY_ATTEMPT_IDENTITY_MISMATCH")
        prior = self.history.get(context.attempt_id)
        if prior is None:
            raise RecoveryActionError("PRIOR_ATTEMPT_NOT_RECORDED")

        terminal = self.TERMINAL_ACTIONS.get(decision.action)
        if terminal:
            return RecoveryActionResult(
                recovery_action_id="REC-" + uuid.uuid4().hex,
                action=decision.action,
                prior_attempt_id=context.attempt_id,
                next_attempt_id=None,
                status="TERMINAL",
                evidence_refs=diagnosis.evidence_refs,
                output_refs=self._terminal_output_refs(context, diagnosis, decision.action),
                verified=True,
                terminal_status=terminal,
            )

        convergence = self.convergence.evaluate_failure(diagnosis)
        if not convergence.allow_recovery:
            return RecoveryActionResult(
                recovery_action_id="REC-" + uuid.uuid4().hex,
                action=decision.action,
                prior_attempt_id=context.attempt_id,
                next_attempt_id=None,
                status="TERMINAL",
                evidence_refs=diagnosis.evidence_refs,
                output_refs=(),
                verified=False,
                terminal_status=convergence.terminal_status,
            )

        adapter = self.adapters.get(decision.action)
        if adapter is None:
            raise RecoveryActionError("RECOVERY_ACTION_ADAPTER_REQUIRED:%s" % decision.action)
        raw = adapter(context, diagnosis, decision)
        if not isinstance(raw, dict):
            raise RecoveryActionError("RECOVERY_ACTION_RESULT_REQUIRED")
        evidence = raw.get("evidence_refs")
        outputs = raw.get("output_refs", [])
        verified = raw.get("verified")
        if not isinstance(evidence, list) or not evidence or not all(isinstance(x, str) and x for x in evidence):
            raise RecoveryActionError("RECOVERY_EVIDENCE_REQUIRED")
        if not isinstance(outputs, list) or not all(isinstance(x, str) and x for x in outputs):
            raise RecoveryActionError("RECOVERY_OUTPUT_REFS_INVALID")
        if verified is not True:
            raise RecoveryActionError("RECOVERY_ACTION_MUST_BE_VERIFIED")

        # Extra semantic guards prevent a callback from claiming success without
        # producing the required rebuilt/revalidated object.
        required_output_markers = {
            "REPAIR_SCRIPT": ("script://", "validation://"),
            "REOPEN_EXECUTABLE_SPEC": ("executable-spec://", "validation://"),
            "RESEARCH_OR_REBUILD_DATA": ("prepared-attempt://",),
            "RECONSTRUCT_PRECONDITION": ("prepared-attempt://",),
            "REAUTH": ("auth-evidence://",),
            "RECONCILE_ROUTE_BINDING": ("route-binding://",),
            "REPAIR_TOOL_BINDING": ("tool-binding://",),
            "REQUALIFY_TARGET": ("target://",),
            "REPAIR_DEPENDENCY_BINDING": ("dependency://",),
        }
        markers = required_output_markers.get(decision.action, ())
        for marker in markers:
            if not any(ref.startswith(marker) for ref in outputs):
                raise RecoveryActionError("RECOVERY_REQUIRED_OUTPUT_MISSING:%s" % marker)

        combined_evidence = tuple(dict.fromkeys(list(diagnosis.evidence_refs) + list(evidence)))
        successor = self._append_successor(
            decision=decision,
            prior=prior,
            diagnosis=diagnosis,
            evidence_refs=combined_evidence,
        )
        self.convergence.record_recovery(diagnosis.failure_class)
        return RecoveryActionResult(
            recovery_action_id="REC-" + uuid.uuid4().hex,
            action=decision.action,
            prior_attempt_id=context.attempt_id,
            next_attempt_id=successor.attempt_id,
            status="RECOVERY_EXECUTED",
            evidence_refs=combined_evidence,
            output_refs=tuple(outputs),
            verified=True,
            terminal_status=None,
        )
