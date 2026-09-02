from __future__ import annotations

from typing import Any, Mapping

from aitest_runtime.durable_core import ComposedRuntimeState, PendingEvent

from .contracts import (
    COMMAND_TYPES,
    R4_3_OPEN_CONFIRMED_DEFECT_LIFECYCLE,
    R4_3_RECORD_FIX_DETECTION_ASSESSMENT,
    R4_3_RECORD_FIX_LINK,
    R4_3_REQUEST_FIX_DETECTION,
    R43_FIX_DETECTION_ASSESSMENT_RECORDED,
    R43_FIX_DETECTION_REQUESTED,
    R43_FIX_LINK_RECORDED,
    R43_LIFECYCLE_OPENED,
    DETECTION_POLICY_VERSION,
    FixDetectionOutcome,
    LifecycleState,
    R43State,
    ConfirmedDefectLifecycle,
    FixDetectionAssessment,
    FixLink,
    detection_ref,
    fix_detection_from_input,
    fix_link_from_input,
    lifecycle_from_input,
    request_from_input,
    validate_detection_rules,
)
from .errors import (
    CONFLICT,
    FIX_DETECTION_CONFLICT,
    FIX_LINK_INVALID,
    IDEMPOTENT_REPLAY,
    NOT_FOUND,
    R3_ASSESSMENT_DIGEST_CONFLICT,
    R43Error,
    SCOPE_MISMATCH,
)
from .r3_6_adapter import validate_r3_6_admission_from_state


def _require_common(command: Any) -> None:
    if command.type not in COMMAND_TYPES:
        raise R43Error("UNSUPPORTED_COMMAND_TYPE", f"unsupported R4.3 command: {command.type}")
    if command.session_id is not None:
        raise R43Error("R4_3_COMMAND_INVALID", "R4.3 commands are session-independent and require session_id=null")
    if not isinstance(command.idempotency_key, str) or not command.idempotency_key.strip():
        raise R43Error("R4_3_COMMAND_INVALID", "R4.3 commands require a non-empty idempotency_key")
    if not isinstance(command.correlation_id, str) or not command.correlation_id.strip():
        raise R43Error("R4_3_COMMAND_INVALID", "R4.3 commands require a non-empty correlation_id")
    if command.schema_version != 1:
        raise R43Error("UNSUPPORTED_COMMAND_SCHEMA", f"unsupported R4.3 command schema: {command.schema_version}")


def _payload(command: Any, required: set[str]) -> dict[str, Any]:
    value = dict(command.payload)
    if set(value) != required:
        raise R43Error("R4_3_COMMAND_INVALID", f"{command.type} payload contains unknown or missing fields")
    return value


def _r43_state(composed: ComposedRuntimeState) -> R43State:
    value = composed.extension_state("r4_3_confirmed_defect_fix_resolution_lifecycle")
    if not isinstance(value, R43State):
        raise R43Error("R4_3_STATE_INVALID", "R4.3 extension state is invalid")
    return value


def _validate_r41_refs(composed: ComposedRuntimeState, lifecycle: ConfirmedDefectLifecycle) -> None:
    r41 = composed.extension_states.get("r4_1_quality_version_campaign_foundation")
    if r41 is None:
        raise R43Error(NOT_FOUND, "R4.1 QualityVersion/Campaign state is required")
    qv = r41.quality_version(lifecycle.quality_version_ref.object_id)
    if qv is None or qv.stream_owner_mission_id != composed.mission_id or qv.version_digest != lifecycle.quality_version_ref.source_digest:
        raise R43Error(SCOPE_MISMATCH, "QualityVersion reference is not an exact same-Mission R4.1 reference")
    for campaign_ref in lifecycle.campaign_refs:
        campaign = r41.campaign(campaign_ref.object_id)
        if campaign is None or campaign.stream_owner_mission_id != composed.mission_id or campaign.campaign_digest != campaign_ref.source_digest:
            raise R43Error(SCOPE_MISMATCH, "Campaign reference is not an exact same-Mission R4.1 reference")


def _validate_lifecycle(composed: ComposedRuntimeState, payload: Mapping[str, Any], command: Any) -> ConfirmedDefectLifecycle:
    lifecycle = lifecycle_from_input(payload, created_seq=1, created_at="validated", correlation_id=command.correlation_id)
    if lifecycle.stream_owner_mission_id != command.mission_id:
        raise R43Error(SCOPE_MISMATCH, "lifecycle owner Mission differs from command Mission")
    if lifecycle.state is not LifecycleState.CONFIRMED:
        raise R43Error("R3_CONFIRMATION_INVALID", "new lifecycle state must be CONFIRMED")
    validate_r3_6_admission_from_state(composed, command.mission_id, lifecycle.r3_6_defect_assessment_ref)
    _validate_r41_refs(composed, lifecycle)
    for item in composed.extension_states.get("r4_3_confirmed_defect_fix_resolution_lifecycle", R43State(command.mission_id)).confirmed_defect_lifecycles:
        if item.r3_6_defect_assessment_ref.object_id == lifecycle.r3_6_defect_assessment_ref.object_id and item.r3_6_assessment_digest != lifecycle.r3_6_assessment_digest:
            raise R43Error(R3_ASSESSMENT_DIGEST_CONFLICT, "same R3.6 assessment ID has a different digest")
    return lifecycle


def _validate_link(composed: ComposedRuntimeState, payload: Mapping[str, Any], command: Any) -> FixLink:
    link = fix_link_from_input(payload, created_seq=1, created_at="validated", correlation_id=command.correlation_id)
    state = _r43_state(composed)
    lifecycle = state.lifecycle(link.confirmed_defect_lifecycle_ref.object_id)
    if lifecycle is None:
        raise R43Error(NOT_FOUND, "FixLink references a missing ConfirmedDefectLifecycle")
    if link.stream_owner_mission_id != command.mission_id or lifecycle.stream_owner_mission_id != command.mission_id:
        raise R43Error(SCOPE_MISMATCH, "FixLink owner Mission mismatch")
    if link.confirmed_defect_lifecycle_ref.source_digest != lifecycle.lifecycle_digest:
        raise R43Error(SCOPE_MISMATCH, "FixLink references a stale lifecycle digest")
    if not link.fix_candidate_refs and not (link.source_change_refs or link.commit_patch_pr_refs or link.source_ref):
        raise R43Error(FIX_LINK_INVALID, "FixLink requires a bounded candidate or source linkage")
    if link.supersedes_fix_link_ref is not None:
        previous = state.fix_link(link.supersedes_fix_link_ref.object_id)
        if previous is None or previous.confirmed_defect_lifecycle_ref.object_id != lifecycle.lifecycle_id:
            raise R43Error(SCOPE_MISMATCH, "supersedes_fix_link_ref must reference an existing same-lifecycle link")
    return link


def _validate_request(composed: ComposedRuntimeState, payload: Mapping[str, Any], command: Any):
    request = request_from_input(payload, created_seq=1, created_at="validated", correlation_id=command.correlation_id)
    state = _r43_state(composed)
    lifecycle = state.lifecycle(request.confirmed_defect_lifecycle_ref.object_id)
    link = state.fix_link(request.fix_link_ref.object_id)
    if lifecycle is None or link is None:
        raise R43Error(NOT_FOUND, "detection request references missing lifecycle or FixLink")
    if request.stream_owner_mission_id != command.mission_id or lifecycle.stream_owner_mission_id != command.mission_id:
        raise R43Error(SCOPE_MISMATCH, "detection request owner Mission mismatch")
    if request.confirmed_defect_lifecycle_ref.source_digest != lifecycle.lifecycle_digest or request.fix_link_ref.source_digest != link.link_digest:
        raise R43Error(SCOPE_MISMATCH, "detection request references stale lifecycle or FixLink digest")
    if request.quality_version_ref.object_id != lifecycle.quality_version_ref.object_id or request.quality_version_ref.source_digest != lifecycle.quality_version_ref.source_digest:
        raise R43Error(SCOPE_MISMATCH, "detection request QualityVersion scope mismatch")
    if request.campaign_ref.object_id not in {item.object_id for item in lifecycle.campaign_refs}:
        raise R43Error(SCOPE_MISMATCH, "detection request Campaign scope mismatch")
    return request


def _validate_detection(composed: ComposedRuntimeState, payload: Mapping[str, Any], command: Any) -> FixDetectionAssessment:
    assessment = fix_detection_from_input(payload, created_seq=1, created_at="validated", correlation_id=command.correlation_id)
    state = _r43_state(composed)
    lifecycle = state.lifecycle(assessment.confirmed_defect_lifecycle_ref.object_id)
    link = state.fix_link(assessment.fix_link_ref.object_id)
    if lifecycle is None or link is None:
        raise R43Error(NOT_FOUND, "FixDetectionAssessment references missing lifecycle or FixLink")
    if assessment.stream_owner_mission_id != command.mission_id or lifecycle.stream_owner_mission_id != command.mission_id:
        raise R43Error(SCOPE_MISMATCH, "FixDetectionAssessment owner Mission mismatch")
    if assessment.confirmed_defect_lifecycle_ref.source_digest != lifecycle.lifecycle_digest or assessment.fix_link_ref.source_digest != link.link_digest:
        raise R43Error(SCOPE_MISMATCH, "FixDetectionAssessment references stale lifecycle or FixLink digest")
    if assessment.quality_version_ref.object_id != lifecycle.quality_version_ref.object_id or assessment.quality_version_ref.source_digest != lifecycle.quality_version_ref.source_digest:
        raise R43Error(SCOPE_MISMATCH, "FixDetectionAssessment QualityVersion scope mismatch")
    if assessment.campaign_ref.object_id not in {item.object_id for item in lifecycle.campaign_refs}:
        raise R43Error(SCOPE_MISMATCH, "FixDetectionAssessment Campaign scope mismatch")
    validate_detection_rules(assessment, link)
    if assessment.outcome is FixDetectionOutcome.DETECTED and assessment.detection_scope.value == "DEPLOYMENT":
        for previous in state.fix_detection_assessments:
            if previous.detection_scope.value != "DEPLOYMENT":
                continue
            prior = {item.object_id: item.source_digest for item in previous.deployment_refs}
            current = {item.object_id: item.source_digest for item in assessment.deployment_refs}
            if set(prior) & set(current) and any(prior[key] != current[key] for key in set(prior) & set(current)):
                raise R43Error(FIX_DETECTION_CONFLICT, "same deployment identity has contradictory digests")
    return assessment


class R43CommandContribution:
    def handle(self, command: Any, composed: ComposedRuntimeState) -> list[PendingEvent]:
        _require_common(command)
        state = _r43_state(composed)

        if command.type == R4_3_OPEN_CONFIRMED_DEFECT_LIFECYCLE:
            payload = _payload(command, LIFECYCLE_FIELDS)
            lifecycle = _validate_lifecycle(composed, payload, command)
            if state.lifecycle(lifecycle.lifecycle_id) is not None:
                raise R43Error(CONFLICT, "ConfirmedDefectLifecycle identity already exists")
            return [PendingEvent(R43_LIFECYCLE_OPENED, "R4_3_CONFIRMED_DEFECT_LIFECYCLE", lifecycle.lifecycle_id, payload, session_id=None)]

        if command.type == R4_3_RECORD_FIX_LINK:
            payload = _payload(command, FIX_LINK_FIELDS)
            link = _validate_link(composed, payload, command)
            if state.fix_link(link.fix_link_id) is not None:
                raise R43Error(CONFLICT, "FixLink identity already exists")
            return [PendingEvent(R43_FIX_LINK_RECORDED, "R4_3_FIX_LINK", link.fix_link_id, payload, session_id=None)]

        if command.type == R4_3_REQUEST_FIX_DETECTION:
            payload = _payload(command, REQUEST_FIELDS)
            request = _validate_request(composed, payload, command)
            if state.request(request.request_id) is not None:
                raise R43Error(CONFLICT, "fix detection request identity already exists")
            return [PendingEvent(R43_FIX_DETECTION_REQUESTED, "R4_3_FIX_DETECTION_REQUEST", request.request_id, payload, session_id=None)]

        if command.type == R4_3_RECORD_FIX_DETECTION_ASSESSMENT:
            payload = _payload(command, DETECTION_FIELDS)
            assessment = _validate_detection(composed, payload, command)
            if state.detection(assessment.fix_detection_id) is not None:
                raise R43Error(CONFLICT, "FixDetectionAssessment identity already exists")
            return [PendingEvent(R43_FIX_DETECTION_ASSESSMENT_RECORDED, "R4_3_FIX_DETECTION_ASSESSMENT", assessment.fix_detection_id, payload, session_id=None)]

        raise R43Error("UNSUPPORTED_COMMAND_TYPE", f"unsupported R4.3 command: {command.type}")


LIFECYCLE_FIELDS = {
    "lifecycle_id", "stream_owner_mission_id", "r3_6_defect_assessment_ref", "r3_6_assessment_digest", "quality_version_ref",
    "campaign_refs", "state", "lifecycle_digest", "severity_refs", "priority_refs", "rca_refs", "evidence_refs", "fix_link_refs",
    "fix_detection_refs", "origin_lineage",
}
FIX_LINK_FIELDS = {
    "fix_link_id", "stream_owner_mission_id", "confirmed_defect_lifecycle_ref", "fix_candidate_refs", "source_change_refs",
    "commit_patch_pr_refs", "build_ref", "deployment_ref", "environment_ref", "claimed_scope_refs", "link_origin", "actor_id",
    "source_ref", "confidence", "rationale_refs", "freshness", "availability", "provenance_refs", "supersedes_fix_link_ref",
    "attempt_key", "link_digest",
}
REQUEST_FIELDS = {
    "request_id", "stream_owner_mission_id", "confirmed_defect_lifecycle_ref", "fix_link_ref", "quality_version_ref", "campaign_ref",
    "detection_scope", "detection_policy_version",
}
DETECTION_FIELDS = {
    "fix_detection_id", "stream_owner_mission_id", "confirmed_defect_lifecycle_ref", "fix_link_ref", "quality_version_ref", "campaign_ref",
    "detection_scope", "source_revision_refs", "build_refs", "deployment_refs", "environment_refs", "observation_refs", "detection_basis",
    "outcome", "reason_refs", "freshness", "availability", "field_validation_state", "evidence_refs", "detection_policy_version", "detection_digest",
}


__all__ = ["R43CommandContribution", "LIFECYCLE_FIELDS", "FIX_LINK_FIELDS", "REQUEST_FIELDS", "DETECTION_FIELDS"]
