"""Center-owned N5/N6 invalidation cascade.

Runtime prerequisites are per-attempt truth. A frozen-case revision or a change
in data/auth/environment/route/reality makes the existing N5 PreparedAttempt and
its N6 ExecutableSpec unusable. This coordinator performs both state changes so
N7 cannot keep executing a READY spec whose N5 input has become stale.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

from .executable_readiness import CenterExecutableReadinessService, ExecutableReadinessState, ExecutableSpec
from .prepared_attempt import CenterPreparedAttemptService, PreparedAttempt


@dataclass(frozen=True)
class RuntimeInvalidationResult:
    prepared_attempt: Optional[PreparedAttempt]
    executable_spec: Optional[ExecutableSpec]
    reason: str
    evidence_refs: Tuple[str, ...]


class CenterRuntimeInvalidationCoordinator:
    """Invalidate current N5 and N6 state for one concrete execution attempt.

    The cascade is fail-closed: a caller may not claim that a runtime mutation
    was handled when either current N5 or current N6 state is absent. Missing
    state means the Center cannot prove which preparation/spec was invalidated,
    so the mutation must be surfaced as an error instead of returning a
    misleading successful result.

    N5 is upstream runtime authority. It is quarantined before the derived N6
    executable readiness is revoked, so concurrent N7 admission cannot resolve
    a current PreparedAttempt during the invalidation window.
    """

    def __init__(self, prepared_attempts: CenterPreparedAttemptService, executable_readiness: CenterExecutableReadinessService) -> None:
        self.prepared_attempts = prepared_attempts
        self.executable_readiness = executable_readiness

    def invalidate_attempt(self, *, test_run_id: str, case_id: str, attempt_id: str, reason: str, evidence_refs: Sequence[str]) -> RuntimeInvalidationResult:
        reason = str(reason).strip()
        if not reason:
            raise ValueError("RUNTIME_INVALIDATION_REASON_REQUIRED")
        refs = tuple(dict.fromkeys(str(ref).strip() for ref in evidence_refs if str(ref).strip()))
        if not refs:
            raise ValueError("RUNTIME_INVALIDATION_EVIDENCE_REQUIRED")

        prepared = self.prepared_attempts.repository.current_for_attempt(test_run_id, case_id, attempt_id)
        executable = self.executable_readiness.repository.current_for_attempt(test_run_id, case_id, attempt_id)
        if prepared is None:
            raise ValueError("RUNTIME_INVALIDATION_CURRENT_N5_REQUIRED")
        if executable is None:
            raise ValueError("RUNTIME_INVALIDATION_CURRENT_N6_REQUIRED")
        if executable.prepared_attempt_id != prepared.prepared_attempt_id:
            raise ValueError("RUNTIME_INVALIDATION_N5_N6_BINDING_MISMATCH")

        # Dependency order is deliberate: N5 becomes non-current before the
        # derived N6 READY state is revoked. This closes the admission window
        # without weakening the existing evidence-bearing durable transitions.
        if not prepared.terminal:
            prepared = self.prepared_attempts.quarantine(prepared.prepared_attempt_id, reason=reason, evidence_refs=refs)
        if executable.state != ExecutableReadinessState.INVALIDATED:
            executable = self.executable_readiness.invalidate(executable.executable_spec_id, reason=reason, evidence_refs=refs)

        return RuntimeInvalidationResult(prepared_attempt=prepared, executable_spec=executable, reason=reason, evidence_refs=refs)

    def invalidate_for_case_revision(self, **kwargs) -> RuntimeInvalidationResult:
        kwargs["reason"] = "FROZEN_CASE_REVISION_CHANGED"
        return self.invalidate_attempt(**kwargs)

    def invalidate_for_runtime_binding_change(self, *, binding: str, **kwargs) -> RuntimeInvalidationResult:
        normalized = str(binding).strip().upper()
        allowed = {"DATA", "AUTH", "ENVIRONMENT", "ROUTE", "REALITY_SNAPSHOT"}
        if normalized not in allowed:
            raise ValueError("RUNTIME_BINDING_CHANGE_INVALID")
        kwargs["reason"] = "%s_BINDING_CHANGED" % normalized
        return self.invalidate_attempt(**kwargs)
