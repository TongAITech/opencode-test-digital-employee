from __future__ import annotations

from typing import Optional, Sequence

from .r1_projection import CenterR1RuntimeProjector
from .runtime_invalidation_recorder import CenterRuntimeInvalidationRecorder


class CenterRuntimeInvalidationService:
    """Center-owned mutation boundary for N5/N6 runtime authority.

    Runtime and case mutations are recorded in canonical R1 first and only
    then projected into durable N5/N6 state. Callers must not mutate
    PreparedAttempt or ExecutableSpec directly; live mutation and restart
    replay therefore share the same authority path.
    """

    def __init__(
        self,
        *,
        recorder: CenterRuntimeInvalidationRecorder,
        projector: CenterR1RuntimeProjector,
    ) -> None:
        self._recorder = recorder
        self._projector = projector

    def record_case_revision_change(
        self,
        *,
        attempt_id: str,
        case_id: str,
        frozen_case_revision_ref: str,
        observed_case_revision_ref: str,
        evidence_refs: Sequence[str],
    ) -> Optional[str]:
        event_id = self._recorder.record_case_revision_change(
            attempt_id=attempt_id,
            case_id=case_id,
            frozen_case_revision_ref=frozen_case_revision_ref,
            observed_case_revision_ref=observed_case_revision_ref,
            evidence_refs=evidence_refs,
        )
        if event_id is None:
            return None
        self._projector.project_new_events()
        return event_id

    def record_runtime_binding_change(
        self,
        *,
        attempt_id: str,
        case_id: str,
        binding: str,
        observed_ref: str,
        evidence_refs: Sequence[str],
    ) -> Optional[str]:
        event_id = self._recorder.record_runtime_binding_change(
            attempt_id=attempt_id,
            case_id=case_id,
            binding=binding,
            observed_ref=observed_ref,
            evidence_refs=evidence_refs,
        )
        if event_id is None:
            return None
        self._projector.project_new_events()
        return event_id
