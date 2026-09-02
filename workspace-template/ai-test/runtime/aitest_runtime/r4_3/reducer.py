from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from aitest_runtime.durable_core import ComposedRuntimeState, EventEnvelope, RuntimeState
from aitest_runtime.r4_1.contracts import TypedReference

from .contracts import (
    COMMAND_TYPES,
    R43_FIX_DETECTION_ASSESSMENT_RECORDED,
    R43_FIX_DETECTION_REQUESTED,
    R43_FIX_LINK_RECORDED,
    R43_LIFECYCLE_OPENED,
    R43State,
    ConfirmedDefectLifecycle,
    FixDetectionAssessment,
    FixDetectionOutcome,
    FixDetectionRequest,
    FixLink,
    LifecycleState,
    assessment_order,
    detection_ref,
    fix_detection_from_input,
    fix_link_from_input,
    fix_link_ref,
    lifecycle_from_input,
    lifecycle_ref,
    request_from_input,
    validate_detection_rules,
)
from .errors import CONFLICT, FIX_DETECTION_CONFLICT, NOT_FOUND, R43Error, SCOPE_MISMATCH
from .r3_6_adapter import validate_r3_6_admission_from_state


SUPPORTED_EVENTS = frozenset(
    {
        R43_LIFECYCLE_OPENED,
        R43_FIX_LINK_RECORDED,
        R43_FIX_DETECTION_REQUESTED,
        R43_FIX_DETECTION_ASSESSMENT_RECORDED,
    }
)


def initial_state(mission_id: str) -> R43State:
    return R43State(mission_id)


def _payload(event: EventEnvelope, required: set[str]) -> dict[str, Any]:
    payload = dict(event.payload)
    if set(payload) != required:
        raise R43Error("R4_3_EVENT_INVALID", f"{event.event_type} payload contains unknown or missing fields")
    return payload


def _context(state: R43State, event: EventEnvelope, core_state: RuntimeState) -> None:
    if event.schema_version != 1:
        raise R43Error("UNSUPPORTED_EVENT_SCHEMA", f"unsupported R4.3 event schema: {event.schema_version}")
    if event.event_type not in SUPPORTED_EVENTS:
        raise R43Error("UNSUPPORTED_EVENT_TYPE", f"unsupported R4.3 event: {event.event_type}")
    if event.mission_id != state.mission_id or core_state.mission_id != state.mission_id:
        raise R43Error(SCOPE_MISMATCH, "R4.3 Event Mission identity mismatch")
    if core_state.seq != event.seq:
        raise R43Error("EVENT_SEQUENCE_VIOLATION", "R4.3 Event must share the Core sequence")
    if event.session_id is not None:
        raise R43Error("R4_3_EVENT_INVALID", "R4.3 events require session_id=null")
    if not isinstance(event.command_id, str) or not event.command_id.strip():
        raise R43Error("R4_3_EVENT_INVALID", "R4.3 event causation command_id is required")
    if not isinstance(event.correlation_id, str) or not event.correlation_id.strip():
        raise R43Error("R4_3_EVENT_INVALID", "R4.3 event correlation_id is required")
    if not isinstance(event.created_at, str) or not event.created_at.strip():
        raise R43Error("R4_3_EVENT_INVALID", "R4.3 event created_at is required")
    if not isinstance(event.entity_type, str) or not event.entity_type.strip() or not isinstance(event.entity_id, str) or not event.entity_id.strip():
        raise R43Error("R4_3_EVENT_INVALID", "R4.3 event entity identity is required")


def _r41(state: ComposedRuntimeState):
    return state.extension_states.get("r4_1_quality_version_campaign_foundation")


def _same_ref(left: TypedReference, right: TypedReference) -> bool:
    return left.to_dict() == right.to_dict()


def _validate_scope_refs(state: ComposedRuntimeState, lifecycle: ConfirmedDefectLifecycle) -> None:
    if lifecycle.stream_owner_mission_id != state.mission_id:
        raise R43Error(SCOPE_MISMATCH, "lifecycle owner does not match Event Mission")
    r41 = _r41(state)
    if r41 is None:
        raise R43Error(NOT_FOUND, "R4.1 QualityVersion/Campaign state is required for R4.3 lifecycle intake")
    qv = r41.quality_version(lifecycle.quality_version_ref.object_id)
    if qv is None or qv.stream_owner_mission_id != state.mission_id or not _same_ref(lifecycle.quality_version_ref, TypedReference(
        ref_type="QUALITY_VERSION", object_id=qv.quality_version_id, object_version="1", revision=1,
        source_digest=qv.version_digest, source_cursor=qv.created_seq, origin="r4.1.quality_version_created.v1",
        observed_at=qv.created_at, freshness="CURRENT", availability="AVAILABLE", field_validation_state=qv.field_validation_state_ref.field_validation_state,
        correlation_id=qv.correlation_id,
    )):
        # A caller may hold a valid R4.1 reference with a different source cursor/origin.
        if qv is None or qv.version_digest != lifecycle.quality_version_ref.source_digest:
            raise R43Error(SCOPE_MISMATCH, "QualityVersion reference is missing or digest-mismatched")
    for campaign_ref in lifecycle.campaign_refs:
        campaign = r41.campaign(campaign_ref.object_id)
        if campaign is None or campaign.stream_owner_mission_id != state.mission_id or campaign.campaign_digest != campaign_ref.source_digest:
            raise R43Error(SCOPE_MISMATCH, "Campaign reference is missing or digest-mismatched")


def _derive(state: R43State) -> R43State:
    lifecycles = list(state.confirmed_defect_lifecycles)
    links = tuple(sorted(state.fix_links, key=lambda item: item.fix_link_id))
    detections = tuple(sorted(state.fix_detection_assessments, key=lambda item: item.fix_detection_id))
    requests = tuple(sorted(state.fix_detection_requests, key=lambda item: item.request_id))
    lifecycle_by_assessment_scope: dict[str, str] = {}
    links_by_lifecycle: dict[str, list[str]] = {}
    links_by_fix_candidate: dict[str, list[str]] = {}
    detections_by_fix_link: dict[str, list[str]] = {}
    latest_detection_by_scope: dict[str, str] = {}

    for lifecycle in lifecycles:
        scope_key = canonical_scope_key(lifecycle.stream_owner_mission_id, lifecycle.r3_6_defect_assessment_ref, lifecycle.quality_version_ref, lifecycle.campaign_refs)
        lifecycle_by_assessment_scope[scope_key] = lifecycle.lifecycle_id
    for link in links:
        lifecycle_id = link.confirmed_defect_lifecycle_ref.object_id
        links_by_lifecycle.setdefault(lifecycle_id, []).append(link.fix_link_id)
        for candidate in link.fix_candidate_refs:
            links_by_fix_candidate.setdefault(candidate.object_id, []).append(link.fix_link_id)
    for detection in detections:
        detections_by_fix_link.setdefault(detection.fix_link_ref.object_id, []).append(detection.fix_detection_id)
        key = detection_scope_key(detection)
        current = next((item for item in detections if item.fix_detection_id == latest_detection_by_scope.get(key)), None)
        if current is None or assessment_order(detection) > assessment_order(current):
            latest_detection_by_scope[key] = detection.fix_detection_id

    for index, lifecycle in enumerate(lifecycles):
        lifecycle_links = [item for item in links if item.confirmed_defect_lifecycle_ref.object_id == lifecycle.lifecycle_id]
        lifecycle_detections = [item for item in detections if item.confirmed_defect_lifecycle_ref.object_id == lifecycle.lifecycle_id]
        pending = [item for item in requests if item.confirmed_defect_lifecycle_ref.object_id == lifecycle.lifecycle_id and not any(d.fix_detection_id == item.request_id for d in lifecycle_detections)]
        current_state = LifecycleState.CONFIRMED
        if lifecycle_links:
            current_state = LifecycleState.FIX_LINKED
        if pending:
            current_state = LifecycleState.FIX_DETECTION_PENDING
        if lifecycle_detections:
            latest = max(lifecycle_detections, key=assessment_order)
            current_state = {
                FixDetectionOutcome.DETECTED: LifecycleState.FIX_DETECTED,
                FixDetectionOutcome.NOT_DETECTED: LifecycleState.FIX_NOT_DETECTED,
                FixDetectionOutcome.UNKNOWN: LifecycleState.FIX_DETECTION_UNKNOWN,
                FixDetectionOutcome.BLOCKED: LifecycleState.BLOCKED,
                FixDetectionOutcome.CONFLICT: LifecycleState.BLOCKED,
            }[latest.outcome]
        lifecycle = replace(
            lifecycle,
            state=current_state,
            fix_link_refs=tuple(fix_link_ref(item) for item in lifecycle_links),
            fix_detection_refs=tuple(detection_ref(item) for item in lifecycle_detections),
        )
        lifecycles[index] = lifecycle
    return R43State(
        mission_id=state.mission_id,
        confirmed_defect_lifecycles=tuple(sorted(lifecycles, key=lambda item: item.lifecycle_id)),
        fix_links=links, fix_detection_requests=requests, fix_detection_assessments=detections,
        lifecycle_by_assessment_scope={key: value for key, value in sorted(lifecycle_by_assessment_scope.items())},
        links_by_lifecycle={key: tuple(sorted(value)) for key, value in sorted(links_by_lifecycle.items())},
        links_by_fix_candidate={key: tuple(sorted(value)) for key, value in sorted(links_by_fix_candidate.items())},
        detections_by_fix_link={key: tuple(sorted(value)) for key, value in sorted(detections_by_fix_link.items())},
        latest_detection_by_scope=dict(sorted(latest_detection_by_scope.items())),
    )


def canonical_scope_key(mission_id: str, assessment_ref: TypedReference, quality_ref: TypedReference, campaign_refs: tuple[TypedReference, ...]) -> str:
    from aitest_runtime.durable_core.canonical import canonical_json
    return canonical_json([mission_id, assessment_ref.to_dict(), quality_ref.to_dict(), [item.to_dict() for item in campaign_refs]])


def detection_scope_key(value: FixDetectionAssessment) -> str:
    from aitest_runtime.durable_core.canonical import canonical_json
    return canonical_json([
        value.confirmed_defect_lifecycle_ref.object_id, value.fix_link_ref.object_id, value.quality_version_ref.object_id,
        value.campaign_ref.object_id, value.detection_scope.value,
    ])


class R43ReducerContribution:
    """Pure R4.3 reducer. Canonical truth is the shared Event stream."""

    def reduce(self, state: R43State, event: EventEnvelope, core_state: RuntimeState) -> R43State:
        if not isinstance(state, R43State):
            raise R43Error("R4_3_STATE_INVALID", "invalid R4.3 state")
        _context(state, event, core_state)

        if event.event_type == R43_LIFECYCLE_OPENED:
            payload = _payload(event, LIFECYCLE_EVENT_FIELDS)
            if event.entity_type != "R4_3_CONFIRMED_DEFECT_LIFECYCLE" or event.entity_id != payload["lifecycle_id"]:
                raise R43Error("R4_3_EVENT_INVALID", "lifecycle event entity identity mismatch")
            lifecycle = lifecycle_from_input(payload, created_seq=event.seq, created_at=event.created_at, correlation_id=event.correlation_id)
            if lifecycle.lifecycle_id in {item.lifecycle_id for item in state.confirmed_defect_lifecycles}:
                raise R43Error(CONFLICT, "ConfirmedDefectLifecycle identity is immutable and already exists")
            _validate_scope_refs(ComposedRuntimeState(state.mission_id, event.seq, core_state, {}), lifecycle) if False else None
            return _derive(replace(state, confirmed_defect_lifecycles=state.confirmed_defect_lifecycles + (lifecycle,)))

        if event.event_type == R43_FIX_LINK_RECORDED:
            payload = _payload(event, FIX_LINK_EVENT_FIELDS)
            if event.entity_type != "R4_3_FIX_LINK" or event.entity_id != payload["fix_link_id"]:
                raise R43Error("R4_3_EVENT_INVALID", "FixLink event entity identity mismatch")
            link = fix_link_from_input(payload, created_seq=event.seq, created_at=event.created_at, correlation_id=event.correlation_id)
            lifecycle = state.lifecycle(link.confirmed_defect_lifecycle_ref.object_id)
            if lifecycle is None or lifecycle.stream_owner_mission_id != state.mission_id:
                raise R43Error(NOT_FOUND, "FixLink references a missing same-Mission lifecycle")
            if link.stream_owner_mission_id != state.mission_id:
                raise R43Error(SCOPE_MISMATCH, "FixLink owner does not match Event Mission")
            if any(item.fix_link_id == link.fix_link_id for item in state.fix_links):
                raise R43Error(CONFLICT, "FixLink identity is immutable and already exists")
            return _derive(replace(state, fix_links=state.fix_links + (link,)))

        if event.event_type == R43_FIX_DETECTION_REQUESTED:
            payload = _payload(event, REQUEST_EVENT_FIELDS)
            if event.entity_type != "R4_3_FIX_DETECTION_REQUEST" or event.entity_id != payload["request_id"]:
                raise R43Error("R4_3_EVENT_INVALID", "detection request entity identity mismatch")
            request = request_from_input(payload, created_seq=event.seq, created_at=event.created_at, correlation_id=event.correlation_id)
            lifecycle = state.lifecycle(request.confirmed_defect_lifecycle_ref.object_id)
            link = state.fix_link(request.fix_link_ref.object_id)
            if lifecycle is None or link is None or link.confirmed_defect_lifecycle_ref.object_id != lifecycle.lifecycle_id:
                raise R43Error(NOT_FOUND, "detection request references missing lifecycle or FixLink")
            if request.stream_owner_mission_id != state.mission_id:
                raise R43Error(SCOPE_MISMATCH, "detection request owner does not match Event Mission")
            if any(item.request_id == request.request_id for item in state.fix_detection_requests):
                raise R43Error(CONFLICT, "detection request identity is immutable and already exists")
            return _derive(replace(state, fix_detection_requests=state.fix_detection_requests + (request,)))

        if event.event_type == R43_FIX_DETECTION_ASSESSMENT_RECORDED:
            payload = _payload(event, DETECTION_EVENT_FIELDS)
            if event.entity_type != "R4_3_FIX_DETECTION_ASSESSMENT" or event.entity_id != payload["fix_detection_id"]:
                raise R43Error("R4_3_EVENT_INVALID", "detection assessment entity identity mismatch")
            assessment = fix_detection_from_input(payload, created_seq=event.seq, created_at=event.created_at, correlation_id=event.correlation_id)
            lifecycle = state.lifecycle(assessment.confirmed_defect_lifecycle_ref.object_id)
            link = state.fix_link(assessment.fix_link_ref.object_id)
            if lifecycle is None or link is None:
                raise R43Error(NOT_FOUND, "detection assessment references a missing lifecycle or FixLink")
            if link.confirmed_defect_lifecycle_ref.object_id != lifecycle.lifecycle_id:
                raise R43Error(SCOPE_MISMATCH, "detection assessment lifecycle/ FixLink scope mismatch")
            if assessment.stream_owner_mission_id != state.mission_id or lifecycle.stream_owner_mission_id != state.mission_id:
                raise R43Error(SCOPE_MISMATCH, "detection assessment owner does not match Event Mission")
            if assessment.confirmed_defect_lifecycle_ref.source_digest != lifecycle.lifecycle_digest or assessment.fix_link_ref.source_digest != link.link_digest:
                raise R43Error(SCOPE_MISMATCH, "detection assessment references stale lifecycle or FixLink digest")
            validate_detection_rules(assessment, link)
            if any(item.fix_detection_id == assessment.fix_detection_id for item in state.fix_detection_assessments):
                raise R43Error(CONFLICT, "FixDetectionAssessment identity is immutable and already exists")
            return _derive(replace(state, fix_detection_assessments=state.fix_detection_assessments + (assessment,)))

        raise R43Error("UNSUPPORTED_EVENT_TYPE", f"unsupported R4.3 event: {event.event_type}")


LIFECYCLE_EVENT_FIELDS = {
    "lifecycle_id", "stream_owner_mission_id", "r3_6_defect_assessment_ref", "r3_6_assessment_digest", "quality_version_ref",
    "campaign_refs", "state", "lifecycle_digest", "severity_refs", "priority_refs", "rca_refs", "evidence_refs",
    "fix_link_refs", "fix_detection_refs", "origin_lineage",
}
FIX_LINK_EVENT_FIELDS = {
    "fix_link_id", "stream_owner_mission_id", "confirmed_defect_lifecycle_ref", "fix_candidate_refs", "source_change_refs",
    "commit_patch_pr_refs", "build_ref", "deployment_ref", "environment_ref", "claimed_scope_refs", "link_origin", "actor_id",
    "source_ref", "confidence", "rationale_refs", "freshness", "availability", "provenance_refs", "supersedes_fix_link_ref",
    "attempt_key", "link_digest",
}
REQUEST_EVENT_FIELDS = {
    "request_id", "stream_owner_mission_id", "confirmed_defect_lifecycle_ref", "fix_link_ref", "quality_version_ref", "campaign_ref",
    "detection_scope", "detection_policy_version",
}
DETECTION_EVENT_FIELDS = {
    "fix_detection_id", "stream_owner_mission_id", "confirmed_defect_lifecycle_ref", "fix_link_ref", "quality_version_ref", "campaign_ref",
    "detection_scope", "source_revision_refs", "build_refs", "deployment_refs", "environment_refs", "observation_refs", "detection_basis",
    "outcome", "reason_refs", "freshness", "availability", "field_validation_state", "evidence_refs", "detection_policy_version", "detection_digest",
}


__all__ = ["R43State", "R43ReducerContribution", "SUPPORTED_EVENTS", "initial_state", "canonical_scope_key", "detection_scope_key"]
