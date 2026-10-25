from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .executable_readiness import CenterExecutableReadinessService, ExecutableSpec
from .prepared_attempt import CenterPreparedAttemptService, PreparedAttempt


@dataclass(frozen=True)
class RuntimeInvalidationResult:
    prepared_attempt: PreparedAttempt
    executable_spec: ExecutableSpec


class RuntimeInvalidationCoordinator:
    """Center-owned invalidation authority for N5/N6 runtime mutations.

    Runtime mutations are projected in dependency order. N5 is the upstream
    prepared-attempt authority, so it is quarantined before the derived N6
    executable specification is invalidated. If either durable transition
    fails the coordinator raises and the caller must fail closed; it must not
    manufacture a READY state or silently continue to N7.
    """

    def __init__(
        self,
        *,
        prepared_attempt_service: CenterPreparedAttemptService,
        executable_readiness_service: CenterExecutableReadinessService,
    ) -> None:
        self._prepared = prepared_attempt_service
        self._readiness = executable_readiness_service

    def invalidate(
        self,
        *,
        test_run_id: str,
        case_id: str,
        attempt_id: str,
        reason: str,
        now: datetime | None = None,
    ) -> RuntimeInvalidationResult:
        ts = now or datetime.now(timezone.utc)

        # N5 is the upstream runtime authority. Quarantine it first so that
        # concurrent/retried N7 admission can no longer resolve a current
        # prepared attempt while the derived N6 readiness is being revoked.
        prepared = self._prepared.quarantine_current_for_attempt(
            test_run_id=test_run_id,
            case_id=case_id,
            attempt_id=attempt_id,
            reason=reason,
            now=ts,
        )
        spec = self._readiness.invalidate_current_for_attempt(
            test_run_id=test_run_id,
            case_id=case_id,
            attempt_id=attempt_id,
            reason=reason,
            now=ts,
        )
        return RuntimeInvalidationResult(
            prepared_attempt=prepared,
            executable_spec=spec,
        )
