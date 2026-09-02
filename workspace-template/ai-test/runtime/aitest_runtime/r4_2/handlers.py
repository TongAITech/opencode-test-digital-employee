from __future__ import annotations

from typing import Any, Mapping

from aitest_runtime.durable_core import ComposedRuntimeState, PendingEvent

from .contracts import (
    R4_2_LINK_SELECTION_REVISION,
    R4_2_RECORD_IMPACT_ASSESSMENT,
    R4_2_RECORD_R2_BRIDGE_RESULT,
    R4_2_RECORD_TRIGGER_RECEIPT,
    R4_2_REQUEST_R2_PLAN_REVISION_BRIDGE,
    R42_IMPACT_ASSESSMENT_RECORDED,
    R42_R2_PLAN_REVISION_BRIDGE_REQUESTED,
    R42_R2_PLAN_REVISION_BRIDGE_RESULT_RECORDED,
    R42_SELECTION_REVISION_LINKED,
    R42_TRIGGER_RECORDED,
    ContinuousTestTrigger,
    ImpactAssessment,
    PlanRevisionBridgeReceipt,
    PlanRevisionIntent,
    SelectionRevisionLink,
    command_id_for,
)
from .errors import R42Error, R42_COMMAND_INVALID, R42_MISSION_INVALID
from .reducer import _state


SUPPORTED_COMMANDS = frozenset(
    {
        R4_2_RECORD_TRIGGER_RECEIPT,
        R4_2_RECORD_IMPACT_ASSESSMENT,
        R4_2_LINK_SELECTION_REVISION,
        R4_2_REQUEST_R2_PLAN_REVISION_BRIDGE,
        R4_2_RECORD_R2_BRIDGE_RESULT,
    }
)


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise R42Error(R42_COMMAND_INVALID, f"{name} must be an object")
    return dict(value)


def _command_context(command: Any) -> None:
    if command.type not in SUPPORTED_COMMANDS:
        raise R42Error(R42_COMMAND_INVALID, f"unsupported R4.2 command: {command.type}")
    if command.session_id is not None:
        raise R42Error(R42_COMMAND_INVALID, "R4.2 commands require session_id=null")
    if not isinstance(command.idempotency_key, str) or not command.idempotency_key.strip():
        raise R42Error(R42_COMMAND_INVALID, "R4.2 commands require an idempotency_key")


def _entity_id(command_type: str, payload: Mapping[str, Any]) -> str:
    if command_type == R4_2_RECORD_TRIGGER_RECEIPT:
        return str(payload.get("trigger_id") or "")
    if command_type == R4_2_RECORD_IMPACT_ASSESSMENT:
        return str(payload.get("impact_assessment_id") or "")
    if command_type == R4_2_LINK_SELECTION_REVISION:
        return str(payload.get("selection_link_id") or "")
    if command_type in {R4_2_REQUEST_R2_PLAN_REVISION_BRIDGE, R4_2_RECORD_R2_BRIDGE_RESULT}:
        bridge = payload.get("bridge_receipt")
        return str(bridge.get("bridge_receipt_id") if isinstance(bridge, Mapping) else "")
    return ""


def _check_command_id(command: Any, entity_id: str) -> None:
    if not entity_id or command.command_id != command_id_for(command.type, entity_id):
        raise R42Error(R42_COMMAND_INVALID, "R4.2 command_id is not the canonical command identity")


def _check_owner(command: Any, owner: str) -> None:
    if owner != command.mission_id:
        raise R42Error(R42_MISSION_INVALID, "R4.2 aggregate owner Mission differs from command Mission")


def handle(command: Any, composed: ComposedRuntimeState) -> list[PendingEvent]:
    _command_context(command)
    state = _state(composed)
    payload = _mapping(command.payload, "payload")
    entity_id = _entity_id(command.type, payload)
    _check_command_id(command, entity_id)

    if command.type == R4_2_RECORD_TRIGGER_RECEIPT:
        trigger = ContinuousTestTrigger.from_dict(payload)
        _check_owner(command, trigger.stream_owner_mission_id)
        return [PendingEvent(R42_TRIGGER_RECORDED, "CONTINUOUS_TEST_TRIGGER", trigger.trigger_id, trigger.to_dict(), None)]

    if command.type == R4_2_RECORD_IMPACT_ASSESSMENT:
        assessment = ImpactAssessment.from_dict(payload)
        _check_owner(command, assessment.stream_owner_mission_id)
        return [PendingEvent(R42_IMPACT_ASSESSMENT_RECORDED, "IMPACT_ASSESSMENT", assessment.impact_assessment_id, assessment.to_dict(), None)]

    if command.type == R4_2_LINK_SELECTION_REVISION:
        link = SelectionRevisionLink.from_dict(payload)
        # The link has no owner field; its ImpactAssessment is the owner anchor.
        assessment = state.assessment(link.impact_assessment_ref.object_id)
        if assessment is None:
            raise R42Error("NOT_FOUND", "ImpactAssessment is not durable")
        _check_owner(command, assessment.stream_owner_mission_id)
        return [PendingEvent(R42_SELECTION_REVISION_LINKED, "SELECTION_REVISION_LINK", link.selection_link_id, link.to_dict(), None)]

    if command.type == R4_2_REQUEST_R2_PLAN_REVISION_BRIDGE:
        intent_raw = _mapping(payload.get("plan_revision_intent"), "plan_revision_intent")
        receipt_raw = _mapping(payload.get("bridge_receipt"), "bridge_receipt")
        if set(payload) != {"plan_revision_intent", "bridge_receipt"}:
            raise R42Error(R42_COMMAND_INVALID, "bridge request payload contains unknown or missing fields")
        intent = PlanRevisionIntent.from_dict(intent_raw)
        receipt = PlanRevisionBridgeReceipt.from_dict(receipt_raw)
        if receipt.bridge_status.value != "R2_REQUESTED":
            raise R42Error(R42_COMMAND_INVALID, "bridge request receipt must be R2_REQUESTED")
        if receipt.plan_revision_intent_ref.object_id != intent.plan_revision_intent_id:
            raise R42Error(R42_COMMAND_INVALID, "bridge request receipt does not reference its intent")
        _check_owner(command, intent.stream_owner_mission_id)
        return [PendingEvent(
            R42_R2_PLAN_REVISION_BRIDGE_REQUESTED,
            "R2_PLAN_REVISION_BRIDGE",
            receipt.bridge_receipt_id,
            {"plan_revision_intent": intent.to_dict(), "bridge_receipt": receipt.to_dict()},
            None,
        )]

    if command.type == R4_2_RECORD_R2_BRIDGE_RESULT:
        if set(payload) != {"bridge_receipt"}:
            raise R42Error(R42_COMMAND_INVALID, "bridge result payload contains unknown or missing fields")
        receipt = PlanRevisionBridgeReceipt.from_dict(_mapping(payload["bridge_receipt"], "bridge_receipt"))
        previous = state.bridge_receipt(receipt.bridge_receipt_id)
        if previous is None:
            raise R42Error("NOT_FOUND", "bridge request is not durable")
        _check_owner(command, previous.stream_owner_mission_id)
        return [PendingEvent(
            R42_R2_PLAN_REVISION_BRIDGE_RESULT_RECORDED,
            "R2_PLAN_REVISION_BRIDGE",
            receipt.bridge_receipt_id,
            {"bridge_receipt": receipt.to_dict()},
            None,
        )]

    raise R42Error(R42_COMMAND_INVALID, f"unsupported R4.2 command: {command.type}")


class R42CommandContribution:
    def handle(self, command: Any, composed: ComposedRuntimeState) -> list[PendingEvent]:
        return handle(command, composed)


__all__ = ["R42CommandContribution", "SUPPORTED_COMMANDS", "handle"]

