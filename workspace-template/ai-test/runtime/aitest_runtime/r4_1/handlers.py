from __future__ import annotations

from typing import Any

from aitest_runtime.durable_core import ComposedRuntimeState, PendingEvent

from .contracts import (
    CAMPAIGN_INPUT_FIELDS,
    CAMPAIGN_SELECTION_REVISION_RECORDED,
    COMMAND_TYPES,
    CREATE_QUALITY_VERSION,
    CREATE_TEST_CAMPAIGN,
    QUALITY_VERSION_INPUT_FIELDS,
    QUALITY_VERSION_CREATED,
    RECORD_CAMPAIGN_SELECTION_REVISION,
    SELECTION_INPUT_FIELDS,
    TEST_CAMPAIGN_CREATED,
    R41State,
    campaign_from_input,
    quality_version_from_input,
    selection_from_input,
)
from .errors import (
    R41_COMMAND_INVALID,
    R41_IDENTITY_CONFLICT,
    R41_IMMUTABLE_CONFLICT,
    R41_MISSION_INVALID,
    R41_REFERENCE_INVALID,
    R41_SUPERSESSION_INVALID,
    R41Error,
)


def _state(composed: ComposedRuntimeState) -> R41State:
    if not isinstance(composed, ComposedRuntimeState):
        raise R41Error(R41_COMMAND_INVALID, "R4.1 commands require a composed RuntimeService")
    if composed.core_state.mission is None:
        raise R41Error(R41_MISSION_INVALID, "R4.1 commands require a real existing R2 Mission")
    state = composed.extension_state("r4_1_quality_version_campaign_foundation")
    if not isinstance(state, R41State):
        raise R41Error(R41_COMMAND_INVALID, "R4.1 extension state is not registered")
    if state.mission_id != composed.mission_id:
        raise R41Error(R41_MISSION_INVALID, "R4.1 state Mission differs from Runtime Mission")
    return state


def _require_command(command: Any, expected: str, fields: frozenset[str]) -> dict[str, Any]:
    if command.type != expected:
        raise R41Error(R41_COMMAND_INVALID, f"unsupported R4.1 command: {command.type}")
    if command.session_id is not None:
        raise R41Error(R41_COMMAND_INVALID, "R4.1 commands are session-independent and require session_id=None")
    if not isinstance(command.payload, dict) and not hasattr(command.payload, "keys"):
        raise R41Error(R41_COMMAND_INVALID, "R4.1 command payload must be an object")
    payload = dict(command.payload)
    if set(payload) != fields:
        raise R41Error(R41_COMMAND_INVALID, f"{expected} payload contains unknown or missing fields")
    owner = payload.get("stream_owner_mission_id")
    if owner != command.mission_id:
        raise R41Error(R41_MISSION_INVALID, "stream_owner_mission_id must equal the command Mission")
    if not isinstance(command.idempotency_key, str) or not command.idempotency_key.strip():
        raise R41Error(R41_COMMAND_INVALID, "R4.1 command idempotency_key is required")
    return payload


def _require_key(command: Any, prefix: str, object_id: str) -> None:
    expected = f"r4.1:{prefix}:{object_id}"
    if command.idempotency_key != expected:
        raise R41Error(R41_COMMAND_INVALID, f"idempotency_key must be {expected}")


def _validate_quality_version(payload: dict[str, Any], command: Any, state: R41State) -> None:
    candidate = quality_version_from_input(
        payload, created_seq=1, created_at="1970-01-01T00:00:00Z", correlation_id=command.correlation_id,
    )
    _require_key(command, "qv", candidate.quality_version_id)
    if candidate.stream_owner_mission_id != state.mission_id:
        raise R41Error(R41_MISSION_INVALID, "QualityVersion owner Mission is not the current stream")
    existing = state.quality_version(candidate.quality_version_id)
    if existing is not None:
        if existing.version_digest != candidate.version_digest:
            raise R41Error(R41_IMMUTABLE_CONFLICT, "same QualityVersion identity has a different version_digest")
        raise R41Error(R41_IDENTITY_CONFLICT, "QualityVersion identity is already durable")
    if candidate.predecessor_version_ref is not None:
        predecessor = state.quality_version(candidate.predecessor_version_ref.object_id)
        if predecessor is None or predecessor.stream_owner_mission_id != state.mission_id:
            raise R41Error(R41_REFERENCE_INVALID, "predecessor_version_ref does not reference an existing same-Mission QualityVersion")


def _validate_campaign(payload: dict[str, Any], command: Any, state: R41State) -> None:
    candidate = campaign_from_input(
        payload, created_seq=1, created_at="1970-01-01T00:00:00Z", correlation_id=command.correlation_id,
    )
    _require_key(command, "campaign", candidate.campaign_id)
    if candidate.stream_owner_mission_id != state.mission_id:
        raise R41Error(R41_MISSION_INVALID, "TestCampaign owner Mission is not the current stream")
    if candidate.baseline_selection_revision_ref is not None or candidate.current_selection_revision_ref is not None:
        raise R41Error(R41_COMMAND_INVALID, "new TestCampaign cannot point at a selection revision")
    if state.quality_version(candidate.quality_version_ref.object_id) is None:
        raise R41Error(R41_REFERENCE_INVALID, "quality_version_ref does not reference a durable QualityVersion")
    if state.campaign(candidate.campaign_id) is not None:
        raise R41Error(R41_IDENTITY_CONFLICT, "TestCampaign identity is already durable")
    if any(item.campaign_key == candidate.campaign_key for item in state.test_campaigns):
        raise R41Error(R41_IDENTITY_CONFLICT, "campaign_key is already used in this Mission stream")


def _validate_selection(payload: dict[str, Any], command: Any, state: R41State) -> None:
    candidate = selection_from_input(
        payload, created_seq=1, created_at="1970-01-01T00:00:00Z", correlation_id=command.correlation_id,
    )
    _require_key(command, "selection", candidate.selection_revision_id)
    if candidate.stream_owner_mission_id != state.mission_id:
        raise R41Error(R41_MISSION_INVALID, "selection owner Mission is not the current stream")
    campaign = state.campaign(candidate.campaign_ref.object_id)
    if campaign is None:
        raise R41Error(R41_REFERENCE_INVALID, "campaign_ref does not reference a durable TestCampaign")
    if state.selection_revision(candidate.selection_revision_id) is not None:
        raise R41Error(R41_IDENTITY_CONFLICT, "selection_revision_id is already durable")
    selected_ids = [item.object_id for item in candidate.selected_input_refs]
    if len(selected_ids) != len(set(selected_ids)):
        raise R41Error(R41_IDENTITY_CONFLICT, "selected_input_refs must not contain duplicate aggregate identities")
    if candidate.supersedes_revision_ref is None:
        if campaign.current_selection_revision_ref is not None:
            raise R41Error(R41_SUPERSESSION_INVALID, "selection revision would fork the campaign line")
    else:
        if campaign.current_selection_revision_ref != candidate.supersedes_revision_ref:
            raise R41Error(R41_SUPERSESSION_INVALID, "supersedes_revision_ref must equal the current campaign revision")
        superseded = state.selection_revision(candidate.supersedes_revision_ref.object_id)
        if superseded is None or superseded.campaign_ref.object_id != campaign.campaign_id:
            raise R41Error(R41_SUPERSESSION_INVALID, "supersedes_revision_ref must belong to the same campaign")


def handle(command: Any, composed: ComposedRuntimeState) -> list[PendingEvent]:
    state = _state(composed)
    if command.type == CREATE_QUALITY_VERSION:
        payload = _require_command(command, CREATE_QUALITY_VERSION, QUALITY_VERSION_INPUT_FIELDS)
        _validate_quality_version(payload, command, state)
        return [PendingEvent(QUALITY_VERSION_CREATED, "QUALITY_VERSION", payload["quality_version_id"], payload, None)]
    if command.type == CREATE_TEST_CAMPAIGN:
        payload = _require_command(command, CREATE_TEST_CAMPAIGN, CAMPAIGN_INPUT_FIELDS)
        _validate_campaign(payload, command, state)
        return [PendingEvent(TEST_CAMPAIGN_CREATED, "TEST_CAMPAIGN", payload["campaign_id"], payload, None)]
    if command.type == RECORD_CAMPAIGN_SELECTION_REVISION:
        payload = _require_command(command, RECORD_CAMPAIGN_SELECTION_REVISION, SELECTION_INPUT_FIELDS)
        _validate_selection(payload, command, state)
        return [
            PendingEvent(
                CAMPAIGN_SELECTION_REVISION_RECORDED,
                "CAMPAIGN_SELECTION_REVISION",
                payload["selection_revision_id"],
                payload,
                None,
            )
        ]
    raise R41Error(R41_COMMAND_INVALID, f"unsupported R4.1 command: {command.type}")


class R41CommandContribution:
    def handle(self, command: Any, composed: ComposedRuntimeState) -> list[PendingEvent]:
        return handle(command, composed)

