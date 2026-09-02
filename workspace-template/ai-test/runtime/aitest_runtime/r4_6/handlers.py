from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from aitest_runtime.durable_core import ComposedRuntimeState, PendingEvent

from .contracts import *
from .errors import *


_GENERATED = {"created_seq", "created_at", "record_digest", "candidate_digest", "revision_digest", "assessment_digest", "request_digest", "receipt_digest", "disposition_digest"}
_DIGESTS = {"record_digest", "candidate_digest", "revision_digest", "assessment_digest", "request_digest", "receipt_digest", "disposition_digest"}


def _state(composed: ComposedRuntimeState) -> R46State:
    if not isinstance(composed, ComposedRuntimeState):
        raise R46Error(R46_COMMAND_INVALID, "R4.6 commands require composed runtime state")
    if composed.core_state.mission is None:
        raise R46Error(R46_SCOPE_MISMATCH, "R4.6 commands require an existing Mission")
    value = composed.extension_state(EXTENSION_ID)
    if not isinstance(value, R46State):
        raise R46Error(R46_COMMAND_INVALID, "R4.6 extension state is not registered")
    return value


def _record_payload(command: Any, key: str) -> dict[str, Any]:
    if command.session_id is not None or not command.idempotency_key:
        raise R46Error(R46_COMMAND_INVALID, "R4.6 commands are session-independent and require idempotency_key")
    raw = command.payload.get(key)
    if not isinstance(raw, Mapping):
        raise R46Error(R46_COMMAND_INVALID, f"payload.{key} must be an object")
    return dict(raw)


def _with_event_metadata(raw: Mapping[str, Any], composed: ComposedRuntimeState, command: Any) -> dict[str, Any]:
    value = dict(raw)
    value["owner_mission_id"] = command.mission_id
    value["created_seq"] = composed.seq + 1
    value["created_at"] = f"seq:{composed.seq + 1}"
    value["correlation_id"] = command.correlation_id
    value["causation_id"] = command.command_id
    value["created_by"] = command.actor.to_dict()
    value["as_of_seq"] = int(value.get("as_of_seq", composed.seq))
    value["source_cursor"] = int(value.get("source_cursor", composed.seq))
    value["owner_stream_key"] = str(value.get("owner_stream_key") or f"r4.6:{command.mission_id}")
    reset_names = {"record_digest"}
    if "candidate_id" in value:
        reset_names.update({"candidate_digest", "revision_digest"})
    if "eligibility_id" in value:
        reset_names.add("assessment_digest")
    if "request_id" in value:
        reset_names.add("request_digest")
    if "receipt_id" in value:
        reset_names.add("receipt_digest")
    if "disposition_id" in value:
        reset_names.add("disposition_digest")
    for name in reset_names:
        if name in value:
            value[name] = None
    return value


def _same_ref_digest(reference: Any, digest: str) -> bool:
    return reference is not None and getattr(reference, "source_digest", None) == digest


class R46CommandContribution:
    def handle(self, command: Any, composed: ComposedRuntimeState) -> list[PendingEvent]:
        state = _state(composed)
        if command.type == R4_6_RECORD_CANDIDATE_REVISION:
            raw = _with_event_metadata(_record_payload(command, "candidate_revision"), composed, command)
            value = R46CandidateRevision.from_dict(raw)
            if value.owner_mission_id != command.mission_id or value.candidate_scope.scope_class is R46ScopeClass.PERSONAL_PRIVATE and value.promotion_target_scope.scope_class is R46ScopeClass.PROJECT_SHARED:
                raise R46Error(R46_SCOPE_MISMATCH, "candidate ownership/scope is invalid")
            if state.candidate_revision(value.revision_id) is not None:
                raise R46Error(R46_IDENTITY_CONFLICT, "candidate revision identity already exists")
            if any(item.candidate_id == value.candidate_id and value.parent_revision_ref is None for item in state.candidate_revisions):
                raise R46Error(R46_IDENTITY_CONFLICT, "same candidate root already owns a different revision digest")
            return [PendingEvent(R46_CANDIDATE_REVISION_RECORDED, "R4_6_CANDIDATE_REVISION", value.revision_id, {"candidate_revision": value.to_dict()})]
        if command.type == R4_6_RECORD_PROMOTION_ELIGIBILITY:
            raw = _with_event_metadata(_record_payload(command, "eligibility"), composed, command)
            value = R46PromotionEligibilityAssessment.from_dict(raw)
            revision = state.candidate_revision(value.candidate_revision_ref.object_id) if value.candidate_revision_ref else None
            if revision is None or not _same_ref_digest(value.candidate_revision_ref, revision.record_digest):
                raise R46Error(R46_REFERENCE_INVALID, "eligibility references missing/stale candidate revision")
            if value.status is PromotionEligibilityStatus.ELIGIBLE and revision.validation_outcome is not CandidateValidationOutcome.VALIDATED:
                raise R46Error(R46_NOT_ELIGIBLE, "ELIGIBLE assessment requires VALIDATED candidate")
            if state.eligibility(value.eligibility_id) is not None:
                raise R46Error(R46_IDENTITY_CONFLICT, "eligibility identity already exists")
            return [PendingEvent(R46_PROMOTION_ELIGIBILITY_RECORDED, "R4_6_PROMOTION_ELIGIBILITY", value.eligibility_id, {"eligibility": value.to_dict()})]
        if command.type == R4_6_CREATE_PROMOTION_REQUEST:
            raw = _with_event_metadata(_record_payload(command, "request"), composed, command)
            value = R46KnowledgePromotionRequest.from_dict(raw)
            assessment = state.eligibility(value.eligibility_ref.object_id) if value.eligibility_ref else None
            if assessment is None or assessment.assessment_digest != value.eligibility_digest:
                raise R46Error(R46_REFERENCE_INVALID, "request eligibility reference is missing or stale")
            if assessment.status is not PromotionEligibilityStatus.ELIGIBLE:
                raise R46Error(R46_NOT_ELIGIBLE, "request creation requires ELIGIBLE assessment")
            if value.state is not PromotionRequestState.READY or state.request(value.request_id) is not None:
                raise R46Error(R46_COMMAND_INVALID, "request must be created once in READY state")
            return [PendingEvent(R46_PROMOTION_REQUEST_CREATED, "R4_6_KNOWLEDGE_PROMOTION_REQUEST", value.request_id, {"request": value.to_dict()})]
        if command.type == R4_6_SUBMIT_PROMOTION_REQUEST:
            required = {"request_id", "request_digest", "submission_attempt", "source_cursor", "authority_command_id", "authority_idempotency_key"}
            if set(command.payload) != required:
                raise R46Error(R46_COMMAND_INVALID, "submit payload has invalid fields")
            request = state.request(str(command.payload["request_id"]))
            if request is None or request.request_digest != command.payload["request_digest"] or request.state is not PromotionRequestState.READY:
                raise R46Error(R46_REFERENCE_INVALID, "only the exact READY request can be submitted")
            return [PendingEvent(R46_PROMOTION_REQUEST_SUBMITTED, "R4_6_KNOWLEDGE_PROMOTION_REQUEST", request.request_id, dict(command.payload))]
        if command.type == R4_6_RECORD_PROMOTION_RECEIPT:
            raw = _with_event_metadata(_record_payload(command, "receipt"), composed, command)
            value = R46KnowledgePromotionReceipt.from_dict(raw)
            request = state.request(value.request_ref.object_id) if value.request_ref else None
            if request is None or request.request_digest != value.request_digest or request.state is not PromotionRequestState.SUBMITTED:
                raise R46Error(R46_REFERENCE_INVALID, "receipt must match a SUBMITTED request")
            if state.receipt(value.receipt_id) is not None:
                raise R46Error(R46_IDENTITY_CONFLICT, "receipt identity already exists")
            return [PendingEvent(R46_PROMOTION_RECEIPT_RECORDED, "R4_6_KNOWLEDGE_PROMOTION_RECEIPT", value.receipt_id, {"receipt": value.to_dict()})]
        if command.type == R4_6_RECORD_CANDIDATE_DISPOSITION:
            raw = _with_event_metadata(_record_payload(command, "disposition"), composed, command)
            value = R46CandidateDisposition.from_dict(raw)
            target = state.candidate_revision(value.target_candidate_revision_ref.object_id) if value.target_candidate_revision_ref else None
            if target is None or not _same_ref_digest(value.target_candidate_revision_ref, target.record_digest):
                raise R46Error(R46_REFERENCE_INVALID, "disposition target is missing or stale")
            if state.disposition(value.disposition_id) is not None:
                raise R46Error(R46_IDENTITY_CONFLICT, "disposition identity already exists")
            return [PendingEvent(R46_CANDIDATE_DISPOSITION_RECORDED, "R4_6_CANDIDATE_DISPOSITION", value.disposition_id, {"disposition": value.to_dict()})]
        raise R46Error("UNSUPPORTED_COMMAND_TYPE", f"unsupported R4.6 command: {command.type}")


__all__ = ["R46CommandContribution"]
