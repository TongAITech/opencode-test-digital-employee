from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from aitest_runtime.durable_core import ComposedRuntimeState, EventEnvelope, RuntimeState, canonical_sha256

from .contracts import (
    CHECKPOINT_RECORDED,
    EXTENSION_ID,
    JOURNEY_RECORDED,
    PAGE_GRAPH_RECORDED,
    RECORD_TRANSITION,
    TRANSITION_RECORDED,
    VERIFICATION_RECORDED,
    BusinessJourney,
    JourneyCheckpoint,
    JourneyTransition,
    JourneyVerification,
    PageGraph,
    R35State,
)
from .errors import R35Error


def _payload(event: EventEnvelope, required: set[str]) -> dict[str, Any]:
    payload = dict(event.payload)
    if set(payload) != required:
        raise R35Error("R3_5_SCHEMA_INVALID", f"{event.event_type} payload contains unknown or missing fields")
    expected = canonical_sha256({key: value for key, value in payload.items() if key != "payload_digest"})
    if payload.get("payload_digest") != expected:
        raise R35Error("R3_5_SCHEMA_INVALID", "event payload digest does not match immutable payload")
    origin = payload.get("origin_lineage")
    if not isinstance(origin, Mapping) or origin.get("mission_id") != event.mission_id:
        raise R35Error("R3_5_SCOPE_MISMATCH", "origin_lineage must identify the Event Mission")
    return payload


def _append(values: tuple[Any, ...], value: Any, identity: str) -> tuple[Any, ...]:
    current = getattr(value, identity)
    if any(getattr(item, identity) == current for item in values):
        raise R35Error("R3_5_SECOND_TRUTH_FORBIDDEN", f"{identity} already exists: {current}")
    return values + (value,)


def _append_versioned(values: tuple[Any, ...], value: Any, identity: str, version_identity: str) -> tuple[Any, ...]:
    current = (getattr(value, identity), getattr(value, version_identity))
    if any((getattr(item, identity), getattr(item, version_identity)) == current for item in values):
        raise R35Error("R3_5_SECOND_TRUTH_FORBIDDEN", f"{identity}/version already exists: {current[0]}:v{current[1]}")
    return values + (value,)


def initial_state(mission_id: str) -> R35State:
    return R35State(mission_id)


class R35ReducerContribution:
    def reduce(self, state: R35State, event: EventEnvelope, core_state: RuntimeState) -> R35State:
        if not isinstance(state, R35State):
            raise R35Error("EXTENSION_SCHEMA_MISMATCH", "invalid R3.5 state")
        if event.mission_id != state.mission_id or core_state.mission_id != state.mission_id or core_state.seq != event.seq:
            raise R35Error("R3_5_SCHEMA_INVALID", "R3.5 Event does not share the Runtime Mission/sequence")
        if event.event_type == PAGE_GRAPH_RECORDED:
            payload = _payload(event, {"graph", "origin_lineage", "payload_digest"})
            return replace(state, page_graphs=_append_versioned(state.page_graphs, PageGraph.from_dict(payload["graph"]), "graph_id", "graph_version"))
        if event.event_type == JOURNEY_RECORDED:
            payload = _payload(event, {"journey", "origin_lineage", "payload_digest"})
            return replace(state, journeys=_append_versioned(state.journeys, BusinessJourney.from_dict(payload["journey"]), "journey_id", "journey_version"))
        if event.event_type == TRANSITION_RECORDED:
            payload = _payload(event, {"transition", "origin_lineage", "payload_digest"})
            transition = JourneyTransition.from_dict(payload["transition"])
            journey = state.journey(transition.journey_id)
            if journey is None:
                raise R35Error("R3_5_JOURNEY_ORDER_INVALID", "transition references a missing Journey")
            return replace(state, transitions=_append(state.transitions, transition, "transition_id"))
        if event.event_type == CHECKPOINT_RECORDED:
            payload = _payload(event, {"checkpoint", "origin_lineage", "payload_digest"})
            checkpoint = JourneyCheckpoint.from_dict(payload["checkpoint"])
            if state.journey(checkpoint.journey_id, checkpoint.journey_version) is None:
                raise R35Error("R3_5_JOURNEY_ORDER_INVALID", "checkpoint references a missing Journey")
            return replace(state, checkpoints=_append(state.checkpoints, checkpoint, "checkpoint_id"))
        if event.event_type == VERIFICATION_RECORDED:
            payload = _payload(event, {"verification", "origin_lineage", "payload_digest"})
            verification = JourneyVerification.from_dict(payload["verification"])
            journey = state.journey(verification.journey_id, verification.journey_version)
            if journey is None:
                raise R35Error("R3_5_JOURNEY_ORDER_INVALID", "verification references a missing Journey")
            return replace(state, verifications=_append(state.verifications, verification, "verification_id"))
        raise R35Error("R3_5_SCHEMA_INVALID", f"R3.5 event is not owned: {event.event_type}")


class R35StateContribution:
    def initial_state(self, mission_id: str) -> R35State:
        return initial_state(mission_id)

    def encode(self, state: R35State) -> dict[str, Any]:
        return state.to_dict()

    def decode(self, value: Mapping[str, Any]) -> R35State:
        return R35State.from_dict(value)

    def hash(self, state: R35State) -> str:
        return canonical_sha256(self.encode(state))
