from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any, Mapping

from aitest_runtime.durable_core import EventEnvelope, RuntimeError, RuntimeState

from .contracts import (
    APPLIED,
    CANCELLED,
    CONTINUATION_PENDING,
    EVENT_TYPES,
    EXPIRED,
    GATE_KINDS,
    HUMAN_GATE_CANCELLED,
    HUMAN_GATE_CONTINUATION_RECORDED,
    HUMAN_GATE_DECISION_RECORDED,
    HUMAN_GATE_ESCALATED,
    HUMAN_GATE_EXPIRED,
    HUMAN_GATE_OPENED,
    NOT_REQUIRED,
    OUTCOMES,
    ROUTES,
    PENDING,
    RESOLVED,
    R26Error,
    HumanGateRecord,
    HumanGateState,
    _allowed_routes,
    _digest,
    _mapping,
    _non_negative,
    _optional_text,
    _positive,
    _provenance,
    _text,
    _timestamp,
    policy_digest,
    replace_gate,
    validate_payload,
)


def _payload(event: EventEnvelope, required: set[str]) -> dict[str, Any]:
    if event.event_type not in EVENT_TYPES:
        raise R26Error("R2_6_EVENT_INVALID", f"unsupported R2.6 event: {event.event_type}")
    if event.entity_type != "HUMAN_GATE" or event.mission_id != event.payload.get("mission_id", event.mission_id):
        raise R26Error("R2_6_EVENT_INVALID", "Human Gate event identity is invalid")
    value = dict(event.payload)
    if set(value) != required:
        raise R26Error("R2_6_EVENT_INVALID", f"{event.event_type} payload contains unknown or missing fields")
    if value.get("gate_id") != event.entity_id:
        raise R26Error("R2_6_EVENT_INVALID", "Human Gate event entity identity mismatch")
    return value


def _created_by(event: EventEnvelope) -> dict[str, str]:
    return {"type": event.initiator_type, "id": event.initiator_id}


class R26ReducerContribution:
    def reduce(self, state: HumanGateState, event: EventEnvelope, core_state: RuntimeState) -> HumanGateState:
        if not isinstance(state, HumanGateState):
            raise R26Error("EXTENSION_SCHEMA_MISMATCH", "invalid R2.6 state")
        if event.mission_id != state.mission_id or core_state.mission_id != state.mission_id or core_state.seq != event.seq:
            raise R26Error("R2_6_EVENT_INVALID", "R2.6 event does not share the canonical Mission sequence")
        if event.event_type == HUMAN_GATE_OPENED:
            required = {
                "gate_id", "mission_id", "plan_id", "plan_revision_id", "task_id", "root_attempt_id",
                "origin_attempt_id", "origin_session_id", "gate_kind", "request_payload_mode", "request_payload",
                "request_digest", "response_schema", "expires_at", "expiry_policy", "decision_policy_id",
                "decision_policy_version", "decision_policy_digest", "allowed_outcomes", "allowed_routes_by_outcome",
                "request_provenance", "status", "gate_revision", "continuation_revision", "continuation_state",
            }
            payload = _payload(event, required)
            if state.current_cycle(payload["mission_id"], payload["task_id"], payload["root_attempt_id"]) is not None:
                raise R26Error("R2_6_ACTIVE_GATE_CONFLICT", "opened event would create multiple blocking Gate cycles")
            if state.gate(payload["gate_id"]) is not None or payload["status"] != PENDING or payload["gate_revision"] != 1 or payload["continuation_revision"] != 0 or payload["continuation_state"] != NOT_REQUIRED:
                raise R26Error("R2_6_EVENT_INVALID", "opened event does not create the initial PENDING state")
            if payload["gate_kind"] not in GATE_KINDS:
                raise R26Error("R2_6_EVENT_INVALID", "opened event has an invalid Gate kind")
            validate_payload(payload["request_payload_mode"], payload["request_payload"], payload["request_digest"], "request")
            _provenance(payload["request_provenance"], "request_provenance")
            allowed_outcomes = tuple(_text(item, "allowed_outcomes") for item in payload["allowed_outcomes"])
            routes = _allowed_routes(payload["allowed_routes_by_outcome"])
            expected_policy = policy_digest(payload["decision_policy_id"], payload["decision_policy_version"], allowed_outcomes, routes)
            if _digest(payload["decision_policy_digest"], "decision_policy_digest") != expected_policy:
                raise R26Error("R2_6_EVENT_INVALID", "opened policy digest mismatch")
            record = HumanGateRecord(
                gate_id=payload["gate_id"], mission_id=payload["mission_id"], plan_id=_text(payload["plan_id"], "plan_id"),
                plan_revision_id=_text(payload["plan_revision_id"], "plan_revision_id"), task_id=_text(payload["task_id"], "task_id"),
                root_attempt_id=_text(payload["root_attempt_id"], "root_attempt_id"), origin_attempt_id=_text(payload["origin_attempt_id"], "origin_attempt_id"),
                origin_session_id=_text(payload["origin_session_id"], "origin_session_id"), gate_kind=_text(payload["gate_kind"], "gate_kind"),
                status=PENDING, request_payload_mode=payload["request_payload_mode"], request_payload=payload["request_payload"],
                request_digest=payload["request_digest"], response_schema=_mapping(payload["response_schema"], "response_schema"),
                expires_at=_timestamp(payload["expires_at"], "expires_at"), expiry_policy=_text(payload["expiry_policy"], "expiry_policy"),
                decision_policy_id=_text(payload["decision_policy_id"], "decision_policy_id"), decision_policy_version=_positive(payload["decision_policy_version"], "decision_policy_version"),
                decision_policy_digest=payload["decision_policy_digest"], allowed_outcomes=allowed_outcomes,
                allowed_routes_by_outcome=routes, gate_revision=1, continuation_revision=0, continuation_state=NOT_REQUIRED,
                created_seq=event.seq, created_at=event.created_at, created_by=_created_by(event),
            )
            return replace(state, gates=state.gates + (record,))
        gate = state.gate(event.entity_id)
        if gate is None:
            raise R26Error("R2_6_EVENT_INVALID", "R2.6 event references an unknown Gate")
        if event.event_type == HUMAN_GATE_DECISION_RECORDED:
            required = {
                "gate_id", "expected_gate_revision", "expected_continuation_revision", "decision_id", "outcome", "route",
                "decision_payload_mode", "decision_payload", "decision_digest", "decision_provenance", "gate_revision",
                "continuation_revision", "continuation_state",
            }
            payload = _payload(event, required)
            if gate.status != PENDING or gate.decision_id is not None:
                raise R26Error("R2_6_EVENT_INVALID", "decision event violates Gate lifecycle")
            if payload["expected_gate_revision"] != gate.gate_revision or payload["gate_revision"] != gate.gate_revision + 1:
                raise R26Error("R2_6_EVENT_INVALID", "decision Gate revision is not contiguous")
            validate_payload(payload["decision_payload_mode"], payload["decision_payload"], payload["decision_digest"], "decision")
            route = _text(payload["route"], "route")
            outcome = _text(payload["outcome"], "outcome")
            if outcome not in OUTCOMES or route not in ROUTES or outcome not in gate.allowed_outcomes or route not in gate.allowed_routes_by_outcome[outcome]:
                raise R26Error("R2_6_DECISION_POLICY_VIOLATION", "decision event violates the immutable policy snapshot")
            expected_continuation = gate.continuation_revision + (1 if route in {"RESUME_EXECUTION", "GOAL_REVISION", "PLAN_REVISION"} else 0)
            if payload["expected_continuation_revision"] != gate.continuation_revision or payload["continuation_revision"] != expected_continuation:
                raise R26Error("R2_6_EVENT_INVALID", "decision Continuation revision is not contiguous")
            if payload["continuation_state"] not in {NOT_REQUIRED, CONTINUATION_PENDING}:
                raise R26Error("R2_6_EVENT_INVALID", "decision Continuation state is invalid")
            changed = replace(
                gate, status=RESOLVED, gate_revision=payload["gate_revision"], continuation_revision=payload["continuation_revision"],
                continuation_state=payload["continuation_state"], continuation_route=route, decision_id=_text(payload["decision_id"], "decision_id"),
                decision_outcome=outcome, decision_payload_mode=payload["decision_payload_mode"],
                decision_payload=payload["decision_payload"], decision_digest=payload["decision_digest"], decision_provenance=_provenance(payload["decision_provenance"], "decision_provenance"),
            )
            return replace_gate(state, changed)
        if event.event_type == HUMAN_GATE_ESCALATED:
            required = {"gate_id", "expected_gate_revision", "escalation_id", "reason", "target_reference", "escalation_provenance", "gate_revision"}
            payload = _payload(event, required)
            if gate.status != PENDING or payload["expected_gate_revision"] != gate.gate_revision or payload["gate_revision"] != gate.gate_revision + 1:
                raise R26Error("R2_6_EVENT_INVALID", "escalation event violates Gate lifecycle or revision")
            _text(payload["escalation_id"], "escalation_id")
            _text(payload["reason"], "reason")
            _mapping(payload["target_reference"], "target_reference")
            _provenance(payload["escalation_provenance"], "escalation_provenance")
            return replace_gate(state, replace(gate, gate_revision=payload["gate_revision"]))
        if event.event_type == HUMAN_GATE_CANCELLED:
            required = {"gate_id", "expected_gate_revision", "reason", "cancellation_provenance", "gate_revision"}
            payload = _payload(event, required)
            if gate.status != PENDING or payload["expected_gate_revision"] != gate.gate_revision or payload["gate_revision"] != gate.gate_revision + 1:
                raise R26Error("R2_6_EVENT_INVALID", "cancel event violates Gate lifecycle or revision")
            _text(payload["reason"], "reason")
            _provenance(payload["cancellation_provenance"], "cancellation_provenance")
            return replace_gate(state, replace(gate, status=CANCELLED, gate_revision=payload["gate_revision"]))
        if event.event_type == HUMAN_GATE_EXPIRED:
            required = {"gate_id", "expected_gate_revision", "observed_at", "expiry_provenance", "gate_revision"}
            payload = _payload(event, required)
            if gate.status != PENDING or payload["expected_gate_revision"] != gate.gate_revision or payload["gate_revision"] != gate.gate_revision + 1:
                raise R26Error("R2_6_EVENT_INVALID", "expire event violates Gate lifecycle or revision")
            observed_at = _timestamp(payload["observed_at"], "observed_at")
            if observed_at is None or gate.expires_at is None or gate.expiry_policy == "NONE" or datetime.fromisoformat(observed_at.replace("Z", "+00:00")) < datetime.fromisoformat(gate.expires_at.replace("Z", "+00:00")):
                raise R26Error("R2_6_EXPIRY_NOT_REACHED", "expire event is before the immutable expiry boundary")
            expiry_provenance = _provenance(payload["expiry_provenance"], "expiry_provenance")
            if expiry_provenance["observed_at"] != observed_at:
                raise R26Error("R2_6_EVENT_INVALID", "expiry provenance does not bind observed_at")
            return replace_gate(state, replace(gate, status=EXPIRED, gate_revision=payload["gate_revision"]))
        if event.event_type == HUMAN_GATE_CONTINUATION_RECORDED:
            required = {"gate_id", "expected_gate_revision", "expected_continuation_revision", "route", "canonical_reference", "source_seq", "source_digest", "continuation_provenance", "gate_revision", "continuation_revision", "continuation_state"}
            payload = _payload(event, required)
            if gate.status != RESOLVED or gate.continuation_state != CONTINUATION_PENDING or payload["route"] != gate.continuation_route:
                raise R26Error("R2_6_EVENT_INVALID", "continuation event violates Gate lifecycle")
            if payload["expected_gate_revision"] != gate.gate_revision or payload["gate_revision"] != gate.gate_revision + 1:
                raise R26Error("R2_6_EVENT_INVALID", "continuation Gate revision is not contiguous")
            if payload["expected_continuation_revision"] != gate.continuation_revision or payload["continuation_revision"] != gate.continuation_revision + 1 or payload["continuation_state"] != APPLIED:
                raise R26Error("R2_6_EVENT_INVALID", "continuation revision is not contiguous")
            if payload["route"] not in {"RESUME_EXECUTION", "GOAL_REVISION", "PLAN_REVISION"}:
                raise R26Error("R2_6_CONTINUATION_SOURCE_CONFLICT", "continuation event has an invalid Route")
            _mapping(payload["canonical_reference"], "canonical_reference")
            _positive(payload["source_seq"], "source_seq")
            _digest(payload["source_digest"], "source_digest")
            _provenance(payload["continuation_provenance"], "continuation_provenance")
            changed = replace(gate, gate_revision=payload["gate_revision"], continuation_revision=payload["continuation_revision"], continuation_state=APPLIED, continuation_reference=_mapping(payload["canonical_reference"], "canonical_reference"))
            return replace_gate(state, changed)
        raise R26Error("R2_6_EVENT_INVALID", f"unsupported R2.6 event: {event.event_type}")
