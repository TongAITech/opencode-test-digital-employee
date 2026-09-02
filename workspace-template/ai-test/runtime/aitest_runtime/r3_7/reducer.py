from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from aitest_runtime.durable_core import ComposedRuntimeState, EventEnvelope, RuntimeState, canonical_sha256

from .contracts import (
    EXTENSION_ID,
    REMAINING_RISK_RECORDED,
    SEMANTIC_REUSE_RECORDED,
    TEST_SUFFICIENCY_DECIDED,
    R37State,
    RemainingRiskItem,
    SemanticReuse,
    TestSufficiencyDecision,
)
from .errors import R37Error


def _event_entity(event: EventEnvelope) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = dict(event.payload)
    if set(payload) != {"entity", "origin_lineage", "payload_digest"}:
        raise R37Error("R3_7_SCHEMA_INVALID", f"{event.event_type} payload contains unknown or missing fields")
    entity = payload.get("entity")
    origin = payload.get("origin_lineage")
    if not isinstance(entity, Mapping) or not isinstance(origin, Mapping):
        raise R37Error("R3_7_SCHEMA_INVALID", "R3.7 event entity and origin_lineage must be objects")
    if origin.get("mission_id") != event.mission_id:
        raise R37Error("R3_7_SCOPE_MISMATCH", "origin_lineage must identify the Event Mission")
    expected = canonical_sha256({"entity": dict(entity), "origin_lineage": dict(origin)})
    if payload.get("payload_digest") != expected:
        raise R37Error("R3_7_SCHEMA_INVALID", "immutable event payload digest does not match")
    return dict(entity), dict(origin)


def _append(values: tuple[Any, ...], value: Any, identity: str) -> tuple[Any, ...]:
    current = getattr(value, identity)
    if any(getattr(item, identity) == current for item in values):
        raise R37Error("R3_7_SECOND_TRUTH_FORBIDDEN", f"{identity} already exists: {current}")
    return values + (value,)


def initial_state(mission_id: str) -> R37State:
    return R37State(mission_id)


class R37ReducerContribution:
    def reduce(self, state: R37State, event: EventEnvelope, core_state: RuntimeState) -> R37State:
        if not isinstance(state, R37State):
            raise R37Error("EXTENSION_SCHEMA_MISMATCH", "invalid R3.7 state")
        if event.mission_id != state.mission_id or core_state.mission_id != state.mission_id or core_state.seq != event.seq:
            raise R37Error("R3_7_SCHEMA_INVALID", "R3.7 Event does not share Runtime Mission/sequence")

        if event.event_type == REMAINING_RISK_RECORDED:
            entity, _ = _event_entity(event)
            return replace(state, remaining_risks=_append(state.remaining_risks, RemainingRiskItem.from_dict(entity), "risk_item_id"))

        if event.event_type == TEST_SUFFICIENCY_DECIDED:
            entity, _ = _event_entity(event)
            decision = TestSufficiencyDecision.from_dict(entity)
            for risk_ref in decision.remaining_risk.get("item_refs", ()): 
                risk_id = risk_ref.get("ref_id") if isinstance(risk_ref, Mapping) else risk_ref
                if risk_id and state.risk(str(risk_id)) is None:
                    raise R37Error("R3_7_UPSTREAM_REF_MISSING", f"decision references missing remaining risk: {risk_id}")
            return replace(state, decisions=_append(state.decisions, decision, "decision_id"))

        if event.event_type == SEMANTIC_REUSE_RECORDED:
            entity, _ = _event_entity(event)
            reuse = SemanticReuse.from_dict(entity)
            if reuse.entity_kind == "TEST_SUFFICIENCY_DECISION" and state.decision(reuse.entity_id) is None:
                raise R37Error("R3_7_UPSTREAM_REF_MISSING", "semantic reuse references missing decision")
            return replace(state, reuses=_append(state.reuses, reuse, "reuse_id"))

        raise R37Error("R3_7_SCHEMA_INVALID", f"R3.7 event is not owned: {event.event_type}")


class R37StateContribution:
    def initial_state(self, mission_id: str) -> R37State:
        return initial_state(mission_id)

    def encode(self, state: R37State) -> dict[str, Any]:
        return state.to_dict()

    def decode(self, value: Mapping[str, Any]) -> R37State:
        return R37State.from_dict(value)

    def hash(self, state: R37State) -> str:
        return canonical_sha256(self.encode(state))
