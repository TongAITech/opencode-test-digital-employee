from __future__ import annotations

from typing import Any, Mapping

from aitest_runtime.durable_core import ComposedRuntimeState, PendingEvent, canonical_sha256

from .contracts import (
    ARCHITECTURE_BASELINE_REF,
    EXTENSION_ID,
    R37_EVALUATE_TEST_SUFFICIENCY,
    R37_SEMANTIC_REUSE,
    REMAINING_RISK_RECORDED,
    SEMANTIC_REUSE_RECORDED,
    TEST_SUFFICIENCY_DECIDED,
    RemainingRiskItem,
    R37State,
    SemanticReuse,
)
from .errors import R37Error
from .evaluator import evaluate_test_sufficiency
from .contracts import R37EvaluationInput


def _request(command: Any) -> dict[str, Any]:
    payload = dict(command.payload)
    if set(payload) != {"request"} or not isinstance(payload.get("request"), Mapping):
        raise R37Error("R3_7_SCHEMA_INVALID", f"{command.type} payload must contain only request")
    request = dict(payload["request"])
    if request.get("mission_id") != command.mission_id:
        raise R37Error("R3_7_SCOPE_MISMATCH", "request mission_id must match command mission_id")
    origin = request.get("origin_lineage")
    if not isinstance(origin, Mapping) or origin.get("mission_id") != command.mission_id:
        raise R37Error("R3_7_SCOPE_MISMATCH", "origin_lineage must identify command Mission")
    if origin.get("architecture_baseline_ref", ARCHITECTURE_BASELINE_REF) != ARCHITECTURE_BASELINE_REF:
        raise R37Error("R3_7_SCOPE_MISMATCH", "R3.7 requires ArchitectureBaseline v5")
    return request


def _state(composed: ComposedRuntimeState) -> R37State:
    state = composed.extension_state(EXTENSION_ID)
    if not isinstance(state, R37State):
        raise R37Error("EXTENSION_SCHEMA_MISMATCH", "invalid R3.7 command state")
    return state


def _event(event_type: str, entity_type: str, entity_id: str, entity: Any, command: Any) -> PendingEvent:
    entity_body = entity.to_dict()
    origin = dict(entity_body.get("origin_lineage") or {})
    origin.setdefault("mission_id", command.mission_id)
    body = {"entity": entity_body, "origin_lineage": origin}
    payload = {**body, "payload_digest": canonical_sha256(body)}
    return PendingEvent(event_type, entity_type, entity_id, payload, session_id=command.session_id)


class R37CommandContribution:
    def handle(self, command: Any, composed: ComposedRuntimeState) -> list[PendingEvent]:
        state = _state(composed)
        request = _request(command)

        if command.type == R37_EVALUATE_TEST_SUFFICIENCY:
            raw_evaluation = request.get("evaluation") if isinstance(request.get("evaluation"), Mapping) else request
            evaluation = R37EvaluationInput.from_dict(raw_evaluation, mission_id=command.mission_id)
            result = evaluate_test_sufficiency(evaluation)
            if state.decision(result.decision.decision_id) is not None:
                raise R37Error("R3_7_SECOND_TRUTH_FORBIDDEN", f"decision already exists: {result.decision.decision_id}")
            events: list[PendingEvent] = []
            for risk in result.remaining_risks:
                if state.risk(risk.risk_item_id) is not None:
                    raise R37Error("R3_7_SECOND_TRUTH_FORBIDDEN", f"remaining risk already exists: {risk.risk_item_id}")
                events.append(_event(REMAINING_RISK_RECORDED, "R3_7_REMAINING_RISK", risk.risk_item_id, risk, command))
            events.append(_event(TEST_SUFFICIENCY_DECIDED, "R3_7_TEST_SUFFICIENCY_DECISION", result.decision.decision_id, result.decision, command))
            return events

        if command.type == R37_SEMANTIC_REUSE:
            raw = request.get("reuse")
            if not isinstance(raw, Mapping):
                raise R37Error("R3_7_SCHEMA_INVALID", "request.reuse must be an object")
            reuse = SemanticReuse.from_dict(raw)
            if state.reuse(reuse.reuse_id) is not None:
                raise R37Error("R3_7_SECOND_TRUTH_FORBIDDEN", f"reuse already exists: {reuse.reuse_id}")
            return [_event(SEMANTIC_REUSE_RECORDED, "R3_7_SEMANTIC_REUSE", reuse.reuse_id, reuse, command)]

        raise R37Error("R3_7_SCHEMA_INVALID", f"R3.7 command is not owned: {command.type}")
