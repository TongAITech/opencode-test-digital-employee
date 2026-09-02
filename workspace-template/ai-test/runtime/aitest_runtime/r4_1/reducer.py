from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from aitest_runtime.durable_core import EventEnvelope, RuntimeState

from .contracts import (
    CAMPAIGN_SELECTION_REVISION_RECORDED,
    QUALITY_VERSION_CREATED,
    TEST_CAMPAIGN_CREATED,
    CampaignSelectionRevision,
    QualityVersion,
    R41State,
    TestCampaign,
    TypedReference,
    campaign_from_input,
    selection_from_input,
    quality_version_from_input,
)
from .errors import (
    R41_EVENT_INVALID,
    R41_EVENT_NOT_OWNED,
    R41_IDENTITY_CONFLICT,
    R41_IMMUTABLE_CONFLICT,
    R41_MISSION_INVALID,
    R41_REFERENCE_INVALID,
    R41_SUPERSESSION_INVALID,
    R41Error,
)


def initial_state(mission_id: str) -> R41State:
    return R41State(mission_id)


def _payload(event: EventEnvelope, required: set[str]) -> dict[str, Any]:
    payload = dict(event.payload)
    if set(payload) != required:
        raise R41Error(R41_EVENT_INVALID, f"{event.event_type} payload contains unknown or missing fields")
    return payload


def _validate_event_context(state: R41State, event: EventEnvelope, core_state: RuntimeState) -> None:
    if event.schema_version != 1:
        raise R41Error(R41_EVENT_INVALID, f"unsupported R4.1 event schema: {event.schema_version}")
    if event.event_type not in {
        QUALITY_VERSION_CREATED,
        TEST_CAMPAIGN_CREATED,
        CAMPAIGN_SELECTION_REVISION_RECORDED,
    }:
        raise R41Error(R41_EVENT_NOT_OWNED, f"unsupported R4.1 event: {event.event_type}")
    if event.mission_id != state.mission_id or core_state.mission_id != state.mission_id:
        raise R41Error(R41_MISSION_INVALID, "R4.1 Event Mission identity mismatch")
    if core_state.mission is None:
        raise R41Error(R41_MISSION_INVALID, "R4.1 event requires a real existing Mission")
    if core_state.seq != event.seq:
        raise R41Error(R41_EVENT_INVALID, "R4.1 Event does not share the Core sequence")
    if event.session_id is not None:
        raise R41Error(R41_EVENT_INVALID, "R4.1 events are session-independent and require session_id=null")
    if not isinstance(event.command_id, str) or not event.command_id.strip():
        raise R41Error(R41_EVENT_INVALID, "R4.1 Event command_id is required as causation")
    if not isinstance(event.correlation_id, str) or not event.correlation_id.strip():
        raise R41Error(R41_EVENT_INVALID, "R4.1 Event correlation_id is required")
    if not isinstance(event.created_at, str) or not event.created_at.strip():
        raise R41Error(R41_EVENT_INVALID, "R4.1 Event created_at is required")


def _revision_reference(revision: CampaignSelectionRevision, event: EventEnvelope) -> TypedReference:
    return TypedReference(
        ref_type="CAMPAIGN_SELECTION_REVISION",
        object_id=revision.selection_revision_id,
        object_version="1",
        revision=1,
        source_digest=revision.revision_digest,
        source_cursor=event.seq,
        origin="r4.1.campaign_selection_revision_recorded",
        observed_at=event.created_at,
        freshness="CURRENT",
        availability="AVAILABLE",
        field_validation_state="PASSED",
        correlation_id=event.correlation_id,
    )


def _append_unique(values: tuple[Any, ...], value: Any, field_name: str) -> tuple[Any, ...]:
    identity_name = {
        "quality_versions": "quality_version_id",
        "test_campaigns": "campaign_id",
        "selection_revisions": "selection_revision_id",
    }[field_name]
    identity = getattr(value, identity_name)
    if any(getattr(item, identity_name) == identity for item in values):
        raise R41Error(R41_IDENTITY_CONFLICT, f"{field_name} identity already exists: {identity}")
    return values + (value,)


class R41ReducerContribution:
    """Pure R4.1 event reducer; state is derived exclusively from the event stream."""

    def reduce(self, state: R41State, event: EventEnvelope, core_state: RuntimeState) -> R41State:
        if not isinstance(state, R41State):
            raise R41Error(R41_EVENT_INVALID, "invalid R4.1 state")
        _validate_event_context(state, event, core_state)

        if event.event_type == QUALITY_VERSION_CREATED:
            if event.entity_type != "QUALITY_VERSION":
                raise R41Error(R41_EVENT_INVALID, "QualityVersion event must target a QUALITY_VERSION aggregate")
            payload = _payload(
                event,
                {
                    "quality_version_id", "stream_owner_mission_id", "project_ref", "sut_ref", "environment_scope",
                    "version_label", "requirement_baseline_refs", "sst_baseline_refs", "design_baseline_refs",
                    "source_refs", "scope_digest", "version_digest", "predecessor_version_ref",
                    "field_validation_state_ref",
                },
            )
            if event.entity_id != payload["quality_version_id"]:
                raise R41Error(R41_EVENT_INVALID, "QualityVersion entity_id differs from payload identity")
            version = quality_version_from_input(
                payload, created_seq=event.seq, created_at=event.created_at, correlation_id=event.correlation_id,
            )
            if version.stream_owner_mission_id != event.mission_id:
                raise R41Error(R41_MISSION_INVALID, "QualityVersion stream owner is not the Event Mission")
            if state.quality_version(version.quality_version_id) is not None:
                raise R41Error(R41_IMMUTABLE_CONFLICT, "QualityVersion identity is immutable and already exists")
            if version.predecessor_version_ref is not None:
                predecessor = state.quality_version(version.predecessor_version_ref.object_id)
                if predecessor is None or predecessor.stream_owner_mission_id != state.mission_id:
                    raise R41Error(R41_REFERENCE_INVALID, "predecessor_version_ref does not reference an existing same-Mission QualityVersion")
            return replace(state, quality_versions=_append_unique(state.quality_versions, version, "quality_versions"))

        if event.event_type == TEST_CAMPAIGN_CREATED:
            if event.entity_type != "TEST_CAMPAIGN":
                raise R41Error(R41_EVENT_INVALID, "TestCampaign event must target a TEST_CAMPAIGN aggregate")
            payload = _payload(
                event,
                {
                    "campaign_id", "stream_owner_mission_id", "quality_version_ref", "campaign_key", "campaign_kind",
                    "campaign_digest", "baseline_selection_revision_ref", "current_selection_revision_ref", "provenance",
                },
            )
            if event.entity_id != payload["campaign_id"]:
                raise R41Error(R41_EVENT_INVALID, "TestCampaign entity_id differs from payload identity")
            campaign = campaign_from_input(
                payload, created_seq=event.seq, created_at=event.created_at, correlation_id=event.correlation_id,
            )
            if campaign.stream_owner_mission_id != event.mission_id:
                raise R41Error(R41_MISSION_INVALID, "TestCampaign stream owner is not the Event Mission")
            if campaign.baseline_selection_revision_ref is not None or campaign.current_selection_revision_ref is not None:
                raise R41Error(R41_EVENT_INVALID, "new TestCampaign cannot point at a selection revision")
            quality_version = state.quality_version(campaign.quality_version_ref.object_id)
            if quality_version is None or quality_version.stream_owner_mission_id != state.mission_id:
                raise R41Error(R41_REFERENCE_INVALID, "quality_version_ref does not reference an existing same-Mission QualityVersion")
            if state.campaign(campaign.campaign_id) is not None:
                raise R41Error(R41_IMMUTABLE_CONFLICT, "TestCampaign identity is immutable and already exists")
            if any(item.campaign_key == campaign.campaign_key for item in state.test_campaigns):
                raise R41Error(R41_IDENTITY_CONFLICT, "campaign_key is already used in this Mission stream")
            return replace(state, test_campaigns=_append_unique(state.test_campaigns, campaign, "test_campaigns"))

        if event.event_type == CAMPAIGN_SELECTION_REVISION_RECORDED:
            if event.entity_type != "CAMPAIGN_SELECTION_REVISION":
                raise R41Error(R41_EVENT_INVALID, "selection event must target a CAMPAIGN_SELECTION_REVISION aggregate")
            payload = _payload(
                event,
                {
                    "selection_revision_id", "stream_owner_mission_id", "campaign_ref", "supersedes_revision_ref",
                    "selected_input_refs", "excluded_scope", "unknown_scope", "blocked_scope", "source_refs",
                    "revision_digest",
                },
            )
            if event.entity_id != payload["selection_revision_id"]:
                raise R41Error(R41_EVENT_INVALID, "selection entity_id differs from payload identity")
            revision = selection_from_input(
                payload, created_seq=event.seq, created_at=event.created_at, correlation_id=event.correlation_id,
            )
            if revision.stream_owner_mission_id != event.mission_id:
                raise R41Error(R41_MISSION_INVALID, "selection stream owner is not the Event Mission")
            if state.selection_revision(revision.selection_revision_id) is not None:
                raise R41Error(R41_IMMUTABLE_CONFLICT, "CampaignSelectionRevision identity is immutable and already exists")
            campaign = state.campaign(revision.campaign_ref.object_id)
            if campaign is None or campaign.stream_owner_mission_id != state.mission_id:
                raise R41Error(R41_REFERENCE_INVALID, "campaign_ref does not reference an existing same-Mission TestCampaign")
            if revision.supersedes_revision_ref is None:
                if campaign.current_selection_revision_ref is not None:
                    raise R41Error(R41_SUPERSESSION_INVALID, "selection revision would fork an existing campaign line")
            else:
                current = campaign.current_selection_revision_ref
                if current is None or revision.supersedes_revision_ref != current:
                    raise R41Error(R41_SUPERSESSION_INVALID, "supersedes_revision_ref must equal the campaign current revision")
                superseded = state.selection_revision(revision.supersedes_revision_ref.object_id)
                if superseded is None or superseded.campaign_ref.object_id != campaign.campaign_id:
                    raise R41Error(R41_SUPERSESSION_INVALID, "supersedes_revision_ref must belong to the same campaign")
            updated_campaign_ref = _revision_reference(revision, event)
            updated_campaign = replace(
                campaign,
                baseline_selection_revision_ref=(
                    updated_campaign_ref
                    if campaign.baseline_selection_revision_ref is None and campaign.current_selection_revision_ref is None
                    and campaign.campaign_kind.value == "BASELINE"
                    else campaign.baseline_selection_revision_ref
                ),
                current_selection_revision_ref=updated_campaign_ref,
            )
            campaigns = tuple(updated_campaign if item.campaign_id == campaign.campaign_id else item for item in state.test_campaigns)
            return replace(
                state,
                test_campaigns=campaigns,
                selection_revisions=_append_unique(state.selection_revisions, revision, "selection_revisions"),
            )

        raise R41Error(R41_EVENT_NOT_OWNED, f"unsupported R4.1 event: {event.event_type}")

