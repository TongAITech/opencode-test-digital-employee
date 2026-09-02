from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from aitest_runtime.durable_core import ComposedRuntimeState, EventEnvelope, RuntimeState, canonical_sha256

from .contracts import (
    AUTH_REQUIRED,
    CONTEXT_CLOSED,
    CONTEXT_EXPIRED,
    CONTEXT_REVOKED,
    HUMAN_GATE_LINKED,
    RUNTIME_VERIFIED,
    RESUME_AUTHORIZED,
    SUTAuthContext,
    R3E2Error,
    R3E2State,
    VERIFICATION_PENDING,
    validate_transition,
)


def _payload(event: EventEnvelope) -> tuple[SUTAuthContext, dict[str, Any]]:
    payload = dict(event.payload)
    if set(payload) != {"context", "origin_lineage", "payload_digest"}:
        raise R3E2Error("R3_E2_EVENT_INVALID", f"{event.event_type} payload contains unknown or missing fields")
    expected = canonical_sha256({key: value for key, value in payload.items() if key != "payload_digest"})
    if payload.get("payload_digest") != expected:
        raise R3E2Error("R3_E2_PROVENANCE_INVALID", "event payload digest does not match immutable payload")
    origin = payload["origin_lineage"]
    if not isinstance(origin, Mapping) or origin.get("mission_id") != event.mission_id:
        raise R3E2Error("R3_E2_SCOPE_MISMATCH", "event origin lineage must identify the event Mission")
    return SUTAuthContext.from_dict(payload["context"]), dict(origin)


def initial_state(mission_id: str) -> R3E2State:
    return R3E2State(mission_id)


class R3E2ReducerContribution:
    def reduce(self, state: R3E2State, event: EventEnvelope, core_state: RuntimeState) -> R3E2State:
        if not isinstance(state, R3E2State):
            raise R3E2Error("EXTENSION_SCHEMA_MISMATCH", "invalid R3.E2 state")
        if event.mission_id != state.mission_id or core_state.mission_id != state.mission_id or core_state.seq != event.seq:
            raise R3E2Error("R3_E2_EVENT_INVALID", "R3.E2 event does not share the Core Mission sequence")
        context, origin = _payload(event)
        current = state.context_key(context.identity.key)
        if event.event_type == AUTH_REQUIRED:
            if current is not None:
                raise R3E2Error("R3_E2_CONTEXT_ID_CONFLICT", "AUTH_REQUIRED reintroduces an existing context")
            contexts = state.contexts + (context,)
        else:
            if current is None:
                raise R3E2Error("R3_E2_CONTEXT_NOT_FOUND", "event references a missing SUTAuthContext")
            if current.identity != context.identity or current.scope != context.scope:
                raise R3E2Error("R3_E2_CONTEXT_ID_CONFLICT", "event changes immutable context identity or scope")
            if event.event_type == RESUME_AUTHORIZED:
                if current.status != "AUTHENTICATED" or context.status != "AUTHENTICATED" or context.continuation_proof is None:
                    raise R3E2Error("R3_E2_CONTINUATION_INVALID", "resume authorization requires an authenticated context")
            else:
                validate_transition(current.status, context.status)
            contexts = tuple(context if item.identity.key == context.identity.key else item for item in state.contexts)
        history = state.transition_history + ({
            "event_type": event.event_type,
            "context_key": context.identity.key,
            "context": context.to_dict(),
            "status": context.status,
            "validation_status": context.validation_status,
            "origin_lineage": origin,
            "event_seq": event.seq,
            "record_digest": context.record_digest,
        },)
        return replace(state, contexts=contexts, transition_history=history)


class R3E2StateContribution:
    def initial_state(self, mission_id: str) -> R3E2State:
        return initial_state(mission_id)

    def encode(self, state: R3E2State) -> dict[str, Any]:
        return state.to_dict()

    def decode(self, value: Mapping[str, Any]) -> R3E2State:
        return R3E2State.from_dict(value)

    def hash(self, state: R3E2State) -> str:
        return canonical_sha256(self.encode(state))
