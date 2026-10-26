from __future__ import annotations

from typing import Optional, Sequence

from .prepared_attempt import CenterPreparedAttemptService, PreparedAttempt, PreparedAttemptError
from .runtime_invalidation_projector import CenterRuntimeInvalidationProjector
from .runtime_invalidation_recorder import CenterRuntimeInvalidationRecorder


class CenterRuntimeInvalidationService:
    """Center-owned mutation boundary for N5/N6 runtime authority.

    Runtime and case mutations are recorded in canonical R1 first and only
    then projected into durable N5/N6 state. Callers identify the current
    attempt, but may not provide or mutate PreparedAttempt/ExecutableSpec
    state directly: the Center resolves the current N5 authority itself.
    Live mutation and restart replay therefore share the same authority path.
    """

    def __init__(
        self,
        *,
        recorder: CenterRuntimeInvalidationRecorder,
        projector: CenterRuntimeInvalidationProjector,
        prepared_attempts: CenterPreparedAttemptService,
    ) -> None:
        self._recorder = recorder
        self._projector = projector
        self._prepared_attempts = prepared_attempts

    def _current(
        self,
        *,
        test_run_id: str,
        case_id: str,
        attempt_id: str,
    ) -> PreparedAttempt:
        current = self._prepared_attempts.repository.current_for_attempt(
            test_run_id,
            case_id,
            attempt_id,
        )
        if current is None:
            raise PreparedAttemptError("RUNTIME_INVALIDATION_REQUIRES_CURRENT_PREPARED_ATTEMPT")
        return current

    def ensure_projected(self, event_id: Optional[str]) -> Optional[str]:
        if event_id is None:
            return None
        result = self._projector.replay()
        errors = tuple(result.get("errors") or ())
        pending = int(result.get("pending") or 0)
        if pending or errors:
            detail = "; ".join(str(error) for error in errors[:5])
            raise RuntimeError(
                "RUNTIME_INVALIDATION_PROJECTION_INCOMPLETE"
                + (":" + detail if detail else "")
            )
        if event_id not in self._projector.receipts:
            raise RuntimeError("RUNTIME_INVALIDATION_PROJECTION_RECEIPT_REQUIRED")
        return event_id

    def record_case_revision_change(
        self,
        *,
        test_run_id: str,
        work_item_id: str,
        case_id: str,
        attempt_id: str,
        frozen_case_revision_ref: str,
        observed_case_revision_ref: str,
        evidence_refs: Sequence[str],
        source_runtime_event_id: Optional[str] = None,
    ) -> Optional[str]:
        prepared = self._current(
            test_run_id=test_run_id,
            case_id=case_id,
            attempt_id=attempt_id,
        )
        event_id = self._recorder.record_case_revision_change(
            prepared_attempt=prepared,
            work_item_id=work_item_id,
            frozen_case_revision_ref=frozen_case_revision_ref,
            observed_case_revision_ref=observed_case_revision_ref,
            evidence_refs=evidence_refs,
            source_runtime_event_id=source_runtime_event_id,
        )
        return self.ensure_projected(event_id)

    def record_runtime_binding_change(
        self,
        *,
        test_run_id: str,
        work_item_id: str,
        case_id: str,
        attempt_id: str,
        binding: str,
        observed_ref: str,
        evidence_refs: Sequence[str],
        source_runtime_event_id: Optional[str] = None,
    ) -> Optional[str]:
        prepared = self._current(
            test_run_id=test_run_id,
            case_id=case_id,
            attempt_id=attempt_id,
        )
        event_id = self._recorder.record_runtime_binding_change(
            prepared_attempt=prepared,
            work_item_id=work_item_id,
            binding=binding,
            observed_ref=observed_ref,
            evidence_refs=evidence_refs,
            source_runtime_event_id=source_runtime_event_id,
        )
        return self.ensure_projected(event_id)
