from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from aitest_runtime.durable_core import ComposedRuntimeState, EventEnvelope, RuntimeState

from .contracts import (
    BRIDGE_RECEIPT_INPUT_FIELDS,
    EVENT_TYPES,
    R42_IMPACT_ASSESSMENT_RECORDED,
    R42_R2_PLAN_REVISION_BRIDGE_REQUESTED,
    R42_R2_PLAN_REVISION_BRIDGE_RESULT_RECORDED,
    R42_SELECTION_REVISION_LINKED,
    R42_TRIGGER_RECORDED,
    ASSESSMENT_INPUT_FIELDS,
    ContinuousTestTrigger,
    ImpactAssessment,
    PlanRevisionBridgeReceipt,
    PlanRevisionIntent,
    R42State,
    SelectionRevisionLink,
    BridgeStatus,
)
from .errors import (
    ARCHITECTURE_BOUNDARY_VIOLATION,
    R42Error,
    R42_EVENT_INVALID,
    R42_EVENT_NOT_OWNED,
    R42_IDENTITY_CONFLICT,
    R42_IMMUTABLE_CONFLICT,
    R42_MISSION_INVALID,
    R42_REFERENCE_INVALID,
    R42_STATE_TRANSITION_INVALID,
)


def initial_state(mission_id: str) -> R42State:
    return R42State(mission_id)


def _state(composed: ComposedRuntimeState | R42State) -> R42State:
    if isinstance(composed, R42State):
        return composed
    value = composed.extension_state("r4_2_continuous_trigger_impact_r2_bridge")
    if not isinstance(value, R42State):
        raise R42Error(R42_EVENT_INVALID, "invalid R4.2 extension state")
    return value


def _require_context(state: R42State, event: EventEnvelope, core_state: RuntimeState) -> None:
    if event.event_type not in EVENT_TYPES:
        if event.event_type.startswith("r4.2."):
            raise R42Error(R42_EVENT_NOT_OWNED, f"unsupported R4.2 event: {event.event_type}")
        raise R42Error(R42_EVENT_NOT_OWNED, f"event is not owned by R4.2: {event.event_type}")
    if event.schema_version != 1:
        raise R42Error(R42_EVENT_INVALID, "R4.2 events require schema_version=1")
    if event.mission_id != state.mission_id or core_state.mission_id != state.mission_id:
        raise R42Error(R42_MISSION_INVALID, "R4.2 Event Mission identity mismatch")
    if core_state.mission is None:
        raise R42Error(R42_MISSION_INVALID, "R4.2 events require a real existing Mission")
    if core_state.seq != event.seq:
        raise R42Error(R42_EVENT_INVALID, "R4.2 Event does not share the Core sequence")
    if event.session_id is not None:
        raise R42Error(R42_EVENT_INVALID, "R4.2 events require session_id=null")
    if not event.command_id or not event.correlation_id or not event.created_at:
        raise R42Error(R42_EVENT_INVALID, "R4.2 events require causation, correlation, and created_at metadata")


def _payload(event: EventEnvelope, required: set[str]) -> dict[str, Any]:
    value = dict(event.payload)
    if set(value) != required:
        raise R42Error(R42_EVENT_INVALID, f"{event.event_type} payload contains unknown or missing fields")
    return value


def _with_event_time(value: Mapping[str, Any], event: EventEnvelope) -> dict[str, Any]:
    raw = dict(value)
    raw["created_seq"] = event.seq
    raw["created_at"] = event.created_at
    raw["correlation_id"] = event.correlation_id
    return raw


def _append(values: tuple[Any, ...], item: Any, identity: str, digest: str | None = None) -> tuple[Any, ...]:
    existing = next((value for value in values if getattr(value, identity) == getattr(item, identity)), None)
    if existing is not None:
        if digest is not None and getattr(existing, digest) == getattr(item, digest):
            raise R42Error(R42_IDENTITY_CONFLICT, f"{identity} is already durable")
        raise R42Error(R42_IMMUTABLE_CONFLICT, f"{identity} is immutable and already has a different digest")
    return values + (item,)


def _same_mission(reference: Any, mission_id: str, name: str) -> None:
    # TypedReference does not carry an owner Mission.  Mission ownership is
    # established by the referenced R4.1/R2 aggregate and is checked at the
    # application boundary; this reducer still rejects explicit foreign
    # Mission references when the object id is encoded as a Mission ref.
    if getattr(reference, "ref_type", None) == "MISSION" and reference.object_id != mission_id:
        raise R42Error(R42_MISSION_INVALID, f"{name} points to a different Mission")


def reduce(state: R42State, event: EventEnvelope, core_state: RuntimeState) -> R42State:
    if not isinstance(state, R42State):
        raise R42Error(R42_EVENT_INVALID, "invalid R4.2 state")
    _require_context(state, event, core_state)

    if event.event_type == R42_TRIGGER_RECORDED:
        payload = _payload(event, set(ContinuousTestTrigger.__dataclass_fields__))
        trigger = ContinuousTestTrigger.from_dict(payload)
        if trigger.stream_owner_mission_id != state.mission_id:
            raise R42Error(R42_MISSION_INVALID, "trigger owner Mission differs from Event Mission")
        if event.entity_type != "CONTINUOUS_TEST_TRIGGER" or event.entity_id != trigger.trigger_id:
            raise R42Error(R42_EVENT_INVALID, "trigger event aggregate identity is invalid")
        if any(item.dedupe_key == trigger.dedupe_key and item.trigger_digest != trigger.trigger_digest for item in state.triggers):
            raise R42Error("TRIGGER_SOURCE_CONFLICT", "same dedupe identity has a different source digest")
        _same_mission(trigger.quality_version_ref, state.mission_id, "quality_version_ref")
        _same_mission(trigger.campaign_ref, state.mission_id, "campaign_ref")
        return replace(state, triggers=_append(state.triggers, trigger, "trigger_id", "trigger_digest"))

    if event.event_type == R42_IMPACT_ASSESSMENT_RECORDED:
        payload = _payload(event, set(ImpactAssessment.__dataclass_fields__))
        assessment = ImpactAssessment.from_dict(payload)
        assessment = replace(assessment, created_seq=event.seq, created_at=event.created_at, correlation_id=event.correlation_id)
        if assessment.stream_owner_mission_id != state.mission_id:
            raise R42Error(R42_MISSION_INVALID, "assessment owner Mission differs from Event Mission")
        if event.entity_type != "IMPACT_ASSESSMENT" or event.entity_id != assessment.impact_assessment_id:
            raise R42Error(R42_EVENT_INVALID, "assessment event aggregate identity is invalid")
        for trigger_ref in assessment.trigger_refs:
            trigger = state.trigger(trigger_ref.object_id)
            if trigger is None or trigger.trigger_digest != trigger_ref.source_digest:
                raise R42Error(R42_REFERENCE_INVALID, "assessment trigger_refs must reference exact durable triggers")
            if trigger.stream_owner_mission_id != state.mission_id:
                raise R42Error(R42_MISSION_INVALID, "assessment contains a cross-Mission trigger")
        return replace(state, assessments=_append(state.assessments, assessment, "impact_assessment_id", "assessment_digest"))

    if event.event_type == R42_SELECTION_REVISION_LINKED:
        payload = _payload(event, set(SelectionRevisionLink.__dataclass_fields__))
        link = SelectionRevisionLink.from_dict(payload)
        link = replace(link, created_seq=event.seq, created_at=event.created_at, correlation_id=event.correlation_id)
        if event.entity_type != "SELECTION_REVISION_LINK" or event.entity_id != link.selection_link_id:
            raise R42Error(R42_EVENT_INVALID, "selection link event aggregate identity is invalid")
        assessment = state.assessment(link.impact_assessment_ref.object_id)
        if assessment is None or assessment.assessment_digest != link.impact_assessment_ref.source_digest:
            raise R42Error(R42_REFERENCE_INVALID, "selection link must reference an exact ImpactAssessment")
        if assessment.campaign_ref != link.campaign_ref:
            raise R42Error(R42_REFERENCE_INVALID, "selection link campaign differs from its assessment")
        _same_mission(link.impact_assessment_ref, state.mission_id, "impact_assessment_ref")
        return replace(state, selection_links=_append(state.selection_links, link, "selection_link_id", "link_digest"))

    if event.event_type == R42_R2_PLAN_REVISION_BRIDGE_REQUESTED:
        payload = _payload(event, {"plan_revision_intent", "bridge_receipt"})
        intent = PlanRevisionIntent.from_dict(payload["plan_revision_intent"])
        receipt_raw = dict(payload["bridge_receipt"])
        receipt = PlanRevisionBridgeReceipt.from_dict(_with_event_time(receipt_raw, event))
        if event.entity_type != "R2_PLAN_REVISION_BRIDGE" or event.entity_id != receipt.bridge_receipt_id:
            raise R42Error(R42_EVENT_INVALID, "bridge request event aggregate identity is invalid")
        if receipt.bridge_status.value != "R2_REQUESTED":
            raise R42Error(R42_STATE_TRANSITION_INVALID, "bridge request must start in R2_REQUESTED")
        if intent.plan_revision_intent_id != receipt.plan_revision_intent_ref.object_id:
            raise R42Error(R42_REFERENCE_INVALID, "bridge receipt must reference its exact PlanRevisionIntent")
        if intent.r4_intent_digest != receipt.plan_revision_intent_ref.source_digest:
            raise R42Error(R42_REFERENCE_INVALID, "bridge receipt PlanRevisionIntent digest mismatch")
        if intent.stream_owner_mission_id != receipt.stream_owner_mission_id or intent.campaign_ref != receipt.campaign_ref:
            raise R42Error(R42_REFERENCE_INVALID, "bridge intent and receipt owner/campaign references differ")
        if intent.impact_assessment_ref != receipt.impact_assessment_ref or intent.campaign_selection_revision_ref != receipt.selection_revision_ref:
            raise R42Error(R42_REFERENCE_INVALID, "bridge intent and receipt causal references differ")
        assessment = state.assessment(receipt.impact_assessment_ref.object_id)
        if assessment is None or assessment.assessment_digest != receipt.impact_assessment_ref.source_digest:
            raise R42Error(R42_REFERENCE_INVALID, "bridge receipt must reference an exact ImpactAssessment")
        link = next((item for item in state.selection_links if item.r4_1_selection_revision_ref.object_id == receipt.selection_revision_ref.object_id and item.impact_assessment_ref.object_id == assessment.impact_assessment_id), None)
        if link is None:
            raise R42Error(R42_REFERENCE_INVALID, "bridge receipt must reference a durable selection linkage")
        if link.r4_1_selection_revision_ref != receipt.selection_revision_ref:
            raise R42Error(R42_REFERENCE_INVALID, "bridge receipt selection reference is not the exact linked revision")
        if state.intent(intent.plan_revision_intent_id) is not None or state.bridge_receipt(receipt.bridge_receipt_id) is not None:
            raise R42Error(R42_IDENTITY_CONFLICT, "bridge request identity is already durable")
        return replace(state, plan_revision_intents=state.plan_revision_intents + (intent,), bridge_receipts=state.bridge_receipts + (receipt,))

    if event.event_type == R42_R2_PLAN_REVISION_BRIDGE_RESULT_RECORDED:
        payload = _payload(event, {"bridge_receipt"})
        receipt = PlanRevisionBridgeReceipt.from_dict(_with_event_time(payload["bridge_receipt"], event))
        if event.entity_type != "R2_PLAN_REVISION_BRIDGE" or event.entity_id != receipt.bridge_receipt_id:
            raise R42Error(R42_EVENT_INVALID, "bridge result event aggregate identity is invalid")
        previous = state.bridge_receipt(receipt.bridge_receipt_id)
        if previous is None:
            raise R42Error(R42_REFERENCE_INVALID, "bridge result requires a durable bridge request")
        if previous.bridge_status is not BridgeStatus.R2_REQUESTED:
            if previous.to_dict() == receipt.to_dict():
                raise R42Error("IDEMPOTENT_REPLAY", "bridge result is already durable")
            raise R42Error("R2_RESULT_CONFLICT", "bridge request already has a different result")
        if previous.planner_request_id != receipt.planner_request_id or previous.r2_planner_input_digest != receipt.r2_planner_input_digest:
            raise R42Error("R2_RESULT_CONFLICT", "planner request identity or input digest changed")
        for field in (
            "stream_owner_mission_id", "campaign_ref", "impact_assessment_ref", "selection_revision_ref",
            "plan_revision_intent_ref", "correlation_id",
        ):
            if getattr(previous, field) != getattr(receipt, field):
                raise R42Error(R42_REFERENCE_INVALID, f"bridge result changed immutable field: {field}")
        if receipt.bridge_status is BridgeStatus.R2_REQUESTED:
            raise R42Error(R42_STATE_TRANSITION_INVALID, "bridge result cannot remain R2_REQUESTED")
        updated = tuple(receipt if item.bridge_receipt_id == receipt.bridge_receipt_id else item for item in state.bridge_receipts)
        return replace(state, bridge_receipts=updated)

    raise R42Error(R42_EVENT_NOT_OWNED, f"unsupported R4.2 event: {event.event_type}")


class R42ReducerContribution:
    def reduce(self, state: R42State, event: EventEnvelope, core_state: RuntimeState) -> R42State:
        return reduce(state, event, core_state)


__all__ = ["R42ReducerContribution", "initial_state", "reduce"]
