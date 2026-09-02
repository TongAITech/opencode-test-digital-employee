from __future__ import annotations

from dataclasses import replace
from typing import Any

from aitest_runtime.durable_core import ComposedRuntimeState, EventEnvelope, RuntimeState

from .contracts import (
    EVENT_TYPES,
    R46_CANDIDATE_DISPOSITION_RECORDED,
    R46_CANDIDATE_REVISION_RECORDED,
    R46_PROMOTION_ELIGIBILITY_RECORDED,
    R46_PROMOTION_RECEIPT_RECORDED,
    R46_PROMOTION_REQUEST_CREATED,
    R46_PROMOTION_REQUEST_SUBMITTED,
    R46CandidateDisposition,
    R46CandidateRevision,
    R46KnowledgePromotionReceipt,
    R46KnowledgePromotionRequest,
    R46PromotionEligibilityAssessment,
    R46State,
    PromotionReceiptStatus,
    PromotionRequestState,
)
from .errors import R46Error, R46_REFERENCE_INVALID, R46_SCHEMA_INVALID, R46_UNKNOWN_EVENT


def _append(values: tuple[Any, ...], value: Any, identity: str) -> tuple[Any, ...]:
    existing = next((item for item in values if getattr(item, identity) == getattr(value, identity)), None)
    if existing is not None:
        if existing.to_dict() == value.to_dict():
            return values
        raise R46Error("R4_6_IDENTITY_CONFLICT", f"{identity} already owns a different value")
    return values + (value,)


def _context(state: R46State, event: EventEnvelope, core_state: RuntimeState) -> None:
    if event.schema_version != 1 or event.event_type not in EVENT_TYPES:
        raise R46Error(R46_UNKNOWN_EVENT, f"unsupported R4.6 event: {event.event_type}")
    if event.mission_id != state.mission_id or event.mission_id != core_state.mission_id:
        raise R46Error("R4_6_SCOPE_MISMATCH", "event Mission differs from R4.6 state")
    if event.seq != core_state.seq or event.session_id is not None:
        raise R46Error("R4_6_SEQUENCE_MISMATCH", "R4.6 event must share the core sequence and be session-independent")
    if not event.entity_id or not event.command_id or not event.correlation_id:
        raise R46Error(R46_SCHEMA_INVALID, "R4.6 event identity is required")


def _request_transition(state: R46State, value: R46KnowledgePromotionRequest, target: PromotionRequestState) -> R46State:
    request = state.request(value.request_id)
    if request is None:
        raise R46Error(R46_REFERENCE_INVALID, "promotion request is missing")
    return replace(state, promotion_requests=tuple(value if item.request_id == value.request_id else item for item in state.promotion_requests))


class R46ReducerContribution:
    """Pure replay reducer for R4.6; it never performs I/O or authority reads."""

    def reduce(self, state: R46State, event: EventEnvelope, core_state: RuntimeState) -> R46State:
        _context(state, event, core_state)
        if event.event_type == R46_CANDIDATE_REVISION_RECORDED:
            value = R46CandidateRevision.from_dict(event.payload["candidate_revision"])
            if event.entity_id not in {value.revision_id, value.candidate_id}:
                raise R46Error(R46_SCHEMA_INVALID, "candidate revision event identity mismatch")
            return replace(state, candidate_revisions=_append(state.candidate_revisions, value, "revision_digest"))
        if event.event_type == R46_PROMOTION_ELIGIBILITY_RECORDED:
            value = R46PromotionEligibilityAssessment.from_dict(event.payload["eligibility"])
            if event.entity_id != value.eligibility_id:
                raise R46Error(R46_SCHEMA_INVALID, "eligibility event identity mismatch")
            if value.candidate_revision_ref and state.candidate_revision(value.candidate_revision_ref.object_id) is None:
                raise R46Error(R46_REFERENCE_INVALID, "eligibility event references missing candidate revision")
            return replace(state, eligibility_assessments=_append(state.eligibility_assessments, value, "eligibility_id"))
        if event.event_type == R46_PROMOTION_REQUEST_CREATED:
            value = R46KnowledgePromotionRequest.from_dict(event.payload["request"])
            if event.entity_id != value.request_id or value.state is not PromotionRequestState.READY:
                raise R46Error(R46_SCHEMA_INVALID, "request creation must start in READY")
            if value.eligibility_ref and state.eligibility(value.eligibility_ref.object_id) is None:
                raise R46Error(R46_REFERENCE_INVALID, "request references missing eligibility")
            return replace(state, promotion_requests=_append(state.promotion_requests, value, "request_id"))
        if event.event_type == R46_PROMOTION_REQUEST_SUBMITTED:
            raw = dict(event.payload)
            request = state.request(str(raw.get("request_id")))
            if request is None or request.request_digest != raw.get("request_digest") or request.state is not PromotionRequestState.READY:
                raise R46Error(R46_REFERENCE_INVALID, "request submission is stale or not READY")
            submitted = replace(
                request,
                state=PromotionRequestState.SUBMITTED,
                submission_attempt=int(raw.get("submission_attempt", request.submission_attempt + 1)),
                source_cursor=int(raw.get("source_cursor", request.source_cursor)),
                authority_command_id=str(raw["authority_command_id"]),
                authority_idempotency_key=str(raw["authority_idempotency_key"]),
                causation_id=event.command_id,
                created_seq=request.created_seq,
                record_digest=None,
            )
            return _request_transition(state, submitted, PromotionRequestState.SUBMITTED)
        if event.event_type == R46_PROMOTION_RECEIPT_RECORDED:
            value = R46KnowledgePromotionReceipt.from_dict(event.payload["receipt"])
            if event.entity_id != value.receipt_id or value.request_ref is None:
                raise R46Error(R46_SCHEMA_INVALID, "receipt event identity/request is invalid")
            request = state.request(value.request_ref.object_id)
            if request is None or request.request_digest != value.request_digest:
                raise R46Error(R46_REFERENCE_INVALID, "receipt event request lineage is invalid")
            target = {
                PromotionReceiptStatus.ACCEPTED: PromotionRequestState.COMPLETED,
                PromotionReceiptStatus.DUPLICATE: PromotionRequestState.COMPLETED,
                PromotionReceiptStatus.REJECTED: PromotionRequestState.REJECTED,
                PromotionReceiptStatus.BLOCKED: PromotionRequestState.BLOCKED,
                PromotionReceiptStatus.CONFLICT: PromotionRequestState.CONFLICT,
                PromotionReceiptStatus.RECONCILIATION_REQUIRED: PromotionRequestState.RECONCILIATION_REQUIRED,
            }[value.status]
            updated = replace(request, state=target, causation_id=event.command_id, record_digest=None)
            return replace(
                _request_transition(state, updated, target),
                promotion_receipts=_append(state.promotion_receipts, value, "receipt_id"),
            )
        if event.event_type == R46_CANDIDATE_DISPOSITION_RECORDED:
            value = R46CandidateDisposition.from_dict(event.payload["disposition"])
            if event.entity_id != value.disposition_id or value.target_candidate_revision_ref is None:
                raise R46Error(R46_SCHEMA_INVALID, "disposition event identity/target is invalid")
            if state.candidate_revision(value.target_candidate_revision_ref.object_id) is None:
                raise R46Error(R46_REFERENCE_INVALID, "disposition target does not exist")
            return replace(state, candidate_dispositions=_append(state.candidate_dispositions, value, "disposition_id"))
        raise R46Error(R46_UNKNOWN_EVENT, f"unsupported R4.6 event: {event.event_type}")


SUPPORTED_EVENTS = EVENT_TYPES


__all__ = ["R46State", "R46ReducerContribution", "SUPPORTED_EVENTS"]
