"""Center-owned producer for canonical N5/N6 invalidation facts.

Runtime mutation is not allowed to jump directly into PostgreSQL N5/N6 state.
The Center first records the mutation in canonical R1; the restart-safe
``CenterRuntimeInvalidationProjector`` then applies the durable fact.  This
keeps mutation truth replayable and prevents worker/LLM claims from revoking or
preserving execution readiness on their own.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence, Tuple

from rc8_runtime import CentralR1RuntimeLedger, RuntimeProducerKind, runtime_event

from .prepared_attempt import PreparedAttempt


class RuntimeInvalidationRecordingError(ValueError):
    pass


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeInvalidationRecordingError("%s_REQUIRED" % name.upper())
    return value.strip()


def _refs(values: Sequence[str]) -> Tuple[str, ...]:
    if not isinstance(values, (tuple, list)):
        raise RuntimeInvalidationRecordingError("INVALIDATION_EVIDENCE_REFS_MUST_BE_LIST")
    result = tuple(dict.fromkeys(_required(value, "evidence_ref") for value in values))
    if not result:
        raise RuntimeInvalidationRecordingError("INVALIDATION_EVIDENCE_REQUIRED")
    return result


class CenterRuntimeInvalidationRecorder:
    """Persist real runtime mutations before any N5/N6 state transition.

    Callers must provide the current PreparedAttempt and evidence for the
    observed mutation.  The recorder compares the observed binding with the
    binding frozen into N5 and emits nothing when it has not changed.  When it
    has changed, one canonical ``INVALIDATION_RECORDED`` event is appended to
    R1.  Applying the event remains the projector's responsibility.
    """

    _BINDING_REASONS = {
        "DATA": "DATA_BINDING_CHANGED",
        "AUTH": "AUTH_BINDING_CHANGED",
        "ENVIRONMENT": "ENVIRONMENT_BINDING_CHANGED",
        "ROUTE": "ROUTE_BINDING_CHANGED",
        "REALITY_SNAPSHOT": "REALITY_SNAPSHOT_BINDING_CHANGED",
    }

    def __init__(self, ledger: CentralR1RuntimeLedger) -> None:
        self.ledger = ledger

    def record_case_revision_change(
        self,
        *,
        prepared_attempt: PreparedAttempt,
        work_item_id: str,
        frozen_case_revision_ref: str,
        observed_case_revision_ref: str,
        evidence_refs: Sequence[str],
    ) -> str | None:
        frozen = _required(frozen_case_revision_ref, "frozen_case_revision_ref")
        observed = _required(observed_case_revision_ref, "observed_case_revision_ref")
        if frozen == observed:
            return None
        return self._append(
            prepared_attempt=prepared_attempt,
            work_item_id=work_item_id,
            reason="FROZEN_CASE_REVISION_CHANGED",
            source_ref=frozen,
            observed_ref=observed,
            evidence_refs=evidence_refs,
        )

    def record_runtime_binding_change(
        self,
        *,
        prepared_attempt: PreparedAttempt,
        work_item_id: str,
        binding: str,
        observed_ref: str,
        evidence_refs: Sequence[str],
    ) -> str | None:
        normalized = _required(binding, "binding").upper()
        reason = self._BINDING_REASONS.get(normalized)
        if reason is None:
            raise RuntimeInvalidationRecordingError("RUNTIME_BINDING_CHANGE_INVALID")
        frozen_ref = self._frozen_binding_ref(prepared_attempt, normalized)
        observed = _required(observed_ref, "observed_ref")
        if frozen_ref == observed:
            return None
        return self._append(
            prepared_attempt=prepared_attempt,
            work_item_id=work_item_id,
            reason=reason,
            source_ref=frozen_ref,
            observed_ref=observed,
            evidence_refs=evidence_refs,
        )

    @staticmethod
    def _frozen_binding_ref(prepared: PreparedAttempt, binding: str) -> str:
        if binding == "DATA":
            # Data binding is the complete reserved input set, not one arbitrary
            # member.  Stable ordering prevents false invalidation from ordering.
            return "data-set:" + "|".join(sorted(prepared.data_refs))
        if binding == "AUTH":
            return _required(prepared.auth_session_ref, "prepared_auth_session_ref")
        if binding == "ENVIRONMENT":
            return _required(prepared.environment_ref, "prepared_environment_ref")
        if binding == "ROUTE":
            return _required(prepared.route_ref, "prepared_route_ref")
        if binding == "REALITY_SNAPSHOT":
            return _required(prepared.reality_snapshot_id, "prepared_reality_snapshot_id")
        raise RuntimeInvalidationRecordingError("RUNTIME_BINDING_CHANGE_INVALID")

    def _append(
        self,
        *,
        prepared_attempt: PreparedAttempt,
        work_item_id: str,
        reason: str,
        source_ref: str,
        observed_ref: str,
        evidence_refs: Sequence[str],
    ) -> str:
        refs = _refs(evidence_refs)
        work_item = _required(work_item_id, "work_item_id")
        source = _required(source_ref, "source_ref")
        observed = _required(observed_ref, "observed_ref")
        node_id = "center-runtime-invalidation-recorder"
        sequence = self.ledger.latest_node_sequence(
            test_run_id=prepared_attempt.test_run_id,
            node_id=node_id,
        ) + 1
        event_id = "runtime-invalidation:%s:%s:%s" % (
            prepared_attempt.attempt_id,
            reason.lower(),
            sequence,
        )
        envelope = runtime_event(
            event_id=event_id,
            test_run_id=prepared_attempt.test_run_id,
            work_item_id=work_item,
            node_id=node_id,
            producer_kind=RuntimeProducerKind.TOOL,
            producer_ref="rc8_center.runtime_invalidation_recorder",
            event_type="INVALIDATION_RECORDED",
            sequence=sequence,
            case_id=prepared_attempt.case_id,
            attempt_id=prepared_attempt.attempt_id,
            refs=list(refs),
            data={
                "invalidation_id": event_id,
                "source_ref": source,
                "observed_ref": observed,
                "target_refs": [
                    "prepared-attempt:%s" % prepared_attempt.prepared_attempt_id,
                    "attempt:%s" % prepared_attempt.attempt_id,
                ],
                "reason": reason,
                "evidence_refs": list(refs),
            },
        )
        self.ledger.assert_next_node_sequence(envelope)
        self.ledger.append_runtime(envelope)
        return event_id
