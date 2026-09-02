from __future__ import annotations

from typing import Any, Mapping

from aitest_runtime.durable_core import ComposedRuntimeState, PendingEvent, RuntimeState, canonical_sha256

from .contracts import (
    BUILD_PAGE_GRAPH,
    CHECKPOINT_JOURNEY,
    CHECKPOINT_RECORDED,
    DEFINE_JOURNEY,
    JOURNEY_RECORDED,
    PAGE_GRAPH_RECORDED,
    RECORD_TRANSITION,
    RECORD_VERIFICATION,
    TRANSITION_RECORDED,
    VERIFICATION_RECORDED,
    EXTENSION_ID,
    BusinessJourney,
    JourneyCheckpoint,
    JourneyTransition,
    JourneyVerification,
    PageGraph,
    R35State,
)
from .errors import R35Error


def _payload(command: Any, entity_key: str) -> tuple[dict[str, Any], Any]:
    raw = dict(command.payload)
    required = {entity_key, "origin_lineage", "payload_digest"}
    if set(raw) != required:
        raise R35Error("R3_5_SCHEMA_INVALID", f"{command.type} payload contains unknown or missing fields")
    expected = canonical_sha256({key: value for key, value in raw.items() if key != "payload_digest"})
    if raw.get("payload_digest") != expected:
        raise R35Error("R3_5_SCHEMA_INVALID", "command payload digest does not match immutable payload")
    origin = raw.get("origin_lineage")
    if not isinstance(origin, Mapping) or origin.get("mission_id") != command.mission_id:
        raise R35Error("R3_5_SCOPE_MISMATCH", "origin_lineage must identify the command Mission")
    return raw, raw[entity_key]


def _event(event_type: str, entity_type: str, entity_id: str, payload: Mapping[str, Any], command: Any) -> list[PendingEvent]:
    return [PendingEvent(event_type, entity_type, entity_id, dict(payload), session_id=command.session_id)]


class R35CommandContribution:
    def handle(self, command: Any, composed: ComposedRuntimeState) -> list[PendingEvent]:
        state = composed.extension_state(EXTENSION_ID)
        if not isinstance(state, R35State):
            raise R35Error("EXTENSION_SCHEMA_MISMATCH", "invalid R3.5 command state")
        if command.type == BUILD_PAGE_GRAPH:
            raw, value = _payload(command, "graph")
            graph = PageGraph.from_dict(value)
            if state.page_graph(graph.graph_id, graph.graph_version) is not None:
                raise R35Error("R3_5_SECOND_TRUTH_FORBIDDEN", f"PageGraph identity already exists: {graph.graph_id}:v{graph.graph_version}")
            return _event(PAGE_GRAPH_RECORDED, "PAGE_GRAPH", f"{graph.graph_id}:v{graph.graph_version}", raw, command)
        if command.type == DEFINE_JOURNEY:
            raw, value = _payload(command, "journey")
            journey = BusinessJourney.from_dict(value)
            if state.journey(journey.journey_id, journey.journey_version) is not None:
                raise R35Error("R3_5_SECOND_TRUTH_FORBIDDEN", f"Journey identity already exists: {journey.journey_id}:v{journey.journey_version}")
            return _event(JOURNEY_RECORDED, "BUSINESS_JOURNEY", f"{journey.journey_id}:v{journey.journey_version}", raw, command)
        if command.type == RECORD_TRANSITION:
            raw, value = _payload(command, "transition")
            transition = JourneyTransition.from_dict(value)
            journey = state.journey(transition.journey_id)
            if journey is None:
                raise R35Error("R3_5_JOURNEY_ORDER_INVALID", "transition references a missing Journey")
            if transition.transition_id not in journey.ordered_transition_refs:
                raise R35Error("R3_5_JOURNEY_ORDER_INVALID", "transition is not part of the ordered Journey")
            if transition.ordinal != journey.ordered_transition_refs.index(transition.transition_id) + 1:
                raise R35Error("R3_5_JOURNEY_ORDER_INVALID", "transition ordinal does not match Journey ordering")
            if transition.trigger_step_ref not in journey.ordered_step_refs:
                raise R35Error("R3_5_JOURNEY_ORDER_INVALID", "transition trigger step is not part of the Journey")
            if transition.status in {"OBSERVED", "VERIFIED"} and not transition.observed_evidence_refs:
                raise R35Error("R3_5_EVIDENCE_REF_REQUIRED", "observed transition requires actual evidence refs")
            if state.transition(transition.transition_id) is not None:
                raise R35Error("R3_5_SECOND_TRUTH_FORBIDDEN", f"transition identity already exists: {transition.transition_id}")
            return _event(TRANSITION_RECORDED, "JOURNEY_TRANSITION", transition.transition_id, raw, command)
        if command.type == CHECKPOINT_JOURNEY:
            raw, value = _payload(command, "checkpoint")
            checkpoint = JourneyCheckpoint.from_dict(value)
            if state.journey(checkpoint.journey_id, checkpoint.journey_version) is None:
                raise R35Error("R3_5_JOURNEY_ORDER_INVALID", "checkpoint references a missing Journey")
            if state.checkpoint(checkpoint.checkpoint_id) is not None:
                raise R35Error("R3_5_SECOND_TRUTH_FORBIDDEN", f"checkpoint identity already exists: {checkpoint.checkpoint_id}")
            return _event(CHECKPOINT_RECORDED, "JOURNEY_CHECKPOINT", checkpoint.checkpoint_id, raw, command)
        if command.type == RECORD_VERIFICATION:
            raw, value = _payload(command, "verification")
            verification = JourneyVerification.from_dict(value)
            journey = state.journey(verification.journey_id, verification.journey_version)
            if journey is None:
                raise R35Error("R3_5_JOURNEY_ORDER_INVALID", "verification references a missing Journey")
            if state.verification(verification.verification_id) is not None:
                raise R35Error("R3_5_SECOND_TRUTH_FORBIDDEN", f"verification identity already exists: {verification.verification_id}")
            return _event(VERIFICATION_RECORDED, "JOURNEY_VERIFICATION", verification.verification_id, raw, command)
        raise R35Error("R3_5_SCHEMA_INVALID", f"R3.5 command is not owned: {command.type}")
