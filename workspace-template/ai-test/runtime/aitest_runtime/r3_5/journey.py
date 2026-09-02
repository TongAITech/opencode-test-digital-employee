from __future__ import annotations

from typing import Any, Mapping

from aitest_runtime.r3_e1 import KnowledgeScopeIdentity

from .contracts import (
    BusinessJourney,
    JourneyCheckpoint,
    JourneyStep,
    JourneyTransition,
    SourceRef,
)
from .errors import R35Error


def _scope(value: Any) -> KnowledgeScopeIdentity:
    if isinstance(value, KnowledgeScopeIdentity):
        return value
    if isinstance(value, Mapping):
        return KnowledgeScopeIdentity.from_dict(value)
    raise R35Error("R3_5_SCOPE_MISMATCH", "Journey scope must be KnowledgeScopeIdentity")


def define_journey(request: Mapping[str, Any] | BusinessJourney) -> BusinessJourney:
    if isinstance(request, BusinessJourney):
        return request
    if not isinstance(request, Mapping):
        raise R35Error("R3_5_SCHEMA_INVALID", "define_journey requires a mapping")
    raw = dict(request)
    journey_id = raw.get("journey_id")
    if not isinstance(journey_id, str) or not journey_id.strip():
        raise R35Error("R3_5_SCHEMA_INVALID", "journey_id is required")
    steps = tuple(item if isinstance(item, JourneyStep) else JourneyStep.from_dict({
        **dict(item),
        "journey_id": journey_id,
    }) for item in raw.get("steps") or ())
    transitions = tuple(str(item) for item in raw.get("ordered_transition_refs") or raw.get("transition_refs") or ())
    if not transitions:
        raise R35Error("R3_5_JOURNEY_ORDER_INVALID", "BusinessJourney requires ordered transition refs")
    journey = BusinessJourney(
        journey_id=journey_id,
        journey_version=raw.get("journey_version", 1),
        scope=_scope(raw["scope"]),
        business_start_state=raw.get("business_start_state") or raw.get("start_state"),
        steps=steps,
        ordered_transition_refs=transitions,
        business_end_state=raw.get("business_end_state") or raw.get("end_state"),
        participating_system_refs=tuple(raw.get("participating_system_refs") or raw.get("systems") or ()),
        page_graph_refs=tuple(raw.get("page_graph_refs") or ()),
        source_refs=tuple(raw.get("source_refs") or ()),
        knowledge_refs=tuple(raw.get("knowledge_refs") or ()),
        oracle_refs=tuple(raw.get("oracle_refs") or ()),
        lifecycle=raw.get("lifecycle", "SOURCE_MAPPED"),
    )
    return journey


def record_journey_transition(
    request: Mapping[str, Any] | JourneyTransition,
    *,
    journey: BusinessJourney,
) -> JourneyTransition:
    if isinstance(request, JourneyTransition):
        transition = request
    elif isinstance(request, Mapping):
        raw = dict(request)
        transition = JourneyTransition(
            transition_id=raw["transition_id"],
            journey_id=raw.get("journey_id", journey.journey_id),
            ordinal=raw["ordinal"],
            from_state=raw["from_state"],
            to_state=raw["to_state"],
            trigger_step_ref=raw["trigger_step_ref"],
            cross_system_boundary=raw.get("cross_system_boundary"),
            expected_data_refs=tuple(raw.get("expected_data_refs") or ()),
            expected_event_refs=tuple(raw.get("expected_event_refs") or ()),
            expected_log_refs=tuple(raw.get("expected_log_refs") or ()),
            oracle_refs=tuple(raw.get("oracle_refs") or ()),
            observed_evidence_refs=tuple(raw.get("observed_evidence_refs") or ()),
            status=raw.get("status", "OBSERVED"),
            observed_at=raw.get("observed_at"),
            source_refs=tuple(raw.get("source_refs") or ()),
        )
    else:
        raise R35Error("R3_5_SCHEMA_INVALID", "record_journey_transition requires a mapping")
    if transition.journey_id != journey.journey_id:
        raise R35Error("R3_5_SCOPE_MISMATCH", "transition belongs to another Journey")
    if transition.transition_id not in journey.ordered_transition_refs:
        raise R35Error("R3_5_JOURNEY_ORDER_INVALID", "transition is not part of ordered Journey")
    expected_ordinal = journey.ordered_transition_refs.index(transition.transition_id) + 1
    if transition.ordinal != expected_ordinal:
        raise R35Error("R3_5_JOURNEY_ORDER_INVALID", "transition ordinal does not match Journey ordering")
    step_ids = set(journey.ordered_step_refs)
    if transition.trigger_step_ref not in step_ids:
        raise R35Error("R3_5_JOURNEY_ORDER_INVALID", "transition trigger step is not part of Journey")
    if transition.status in {"OBSERVED", "VERIFIED"} and not transition.observed_evidence_refs:
        raise R35Error("R3_5_EVIDENCE_REF_REQUIRED", "observed transition requires actual evidence refs")
    return transition


def checkpoint_journey(request: Mapping[str, Any] | JourneyCheckpoint) -> JourneyCheckpoint:
    if isinstance(request, JourneyCheckpoint):
        return request
    if not isinstance(request, Mapping):
        raise R35Error("R3_5_SCHEMA_INVALID", "checkpoint_journey requires a mapping")
    return JourneyCheckpoint.from_dict(dict(request))


def update_journey_lifecycle(journey: BusinessJourney, lifecycle: str) -> BusinessJourney:
    allowed = {"DRAFT", "SOURCE_MAPPED", "EXECUTABLE", "IN_PROGRESS", "PASSED", "FAILED", "BLOCKED", "INCONCLUSIVE", "SUPERSEDED"}
    if lifecycle not in allowed:
        raise R35Error("R3_5_SCHEMA_INVALID", f"unsupported Journey lifecycle: {lifecycle}")
    body = journey.to_dict()
    body["lifecycle"] = lifecycle
    body.pop("journey_digest", None)
    return BusinessJourney.from_dict(body)
