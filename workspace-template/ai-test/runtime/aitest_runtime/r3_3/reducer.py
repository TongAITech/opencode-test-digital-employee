from __future__ import annotations

from dataclasses import replace
from typing import Any

from aitest_runtime.durable_core import EventEnvelope, RuntimeState

from .contracts import (
    CASE_BATCH_DESIGNED,
    DESIGN_REUSED,
    STRATEGY_CREATED,
    AutomationMapping,
    CaseBatch,
    R33Error,
    R33ReuseReference,
    R33State,
    StandardTestCase,
    TestPoint,
    TestStrategy,
)


def _payload(event: EventEnvelope, required: set[str]) -> dict[str, Any]:
    payload = dict(event.payload)
    if set(payload) != required:
        raise R33Error("R3_3_EVENT_INVALID", f"{event.event_type} payload contains unknown or missing fields")
    return payload


class R33ReducerContribution:
    def reduce(self, state: R33State, event: EventEnvelope, core_state: RuntimeState) -> R33State:
        if not isinstance(state, R33State):
            raise R33Error("EXTENSION_SCHEMA_MISMATCH", "invalid R3.3 state")
        if event.mission_id != state.mission_id or core_state.mission_id != state.mission_id:
            raise R33Error("R3_3_EVENT_INVALID", "R3.3 Event Mission identity mismatch")
        if core_state.seq != event.seq:
            raise R33Error("R3_3_EVENT_INVALID", "R3.3 Event does not share the Core sequence")
        if event.event_type == STRATEGY_CREATED:
            payload = _payload(event, {"strategy", "test_points"})
            strategy = TestStrategy.from_dict(payload["strategy"])
            if strategy.mission_id != event.mission_id:
                raise R33Error("R3_3_EVENT_INVALID", "strategy Mission identity mismatch")
            points = tuple(TestPoint.from_dict(item) for item in payload["test_points"])
            if any(item.strategy_version_id != strategy.strategy_version_id for item in points):
                raise R33Error("R3_3_EVENT_INVALID", "TestPoint strategy identity mismatch")
            if state.strategy(strategy.strategy_fingerprint) is not None:
                raise R33Error("R3_3_EVENT_INVALID", "strategy fingerprint is not immutable")
            if any(item.strategy_version_id == strategy.strategy_version_id for item in state.strategies):
                raise R33Error("R3_3_EVENT_INVALID", "strategy version identity is not immutable")
            if any(item.point_id in {point.point_id for point in state.test_points} for item in points):
                raise R33Error("R3_3_EVENT_INVALID", "TestPoint identity is not immutable")
            return replace(state, strategies=state.strategies + (strategy,), test_points=state.test_points + points)
        if event.event_type == CASE_BATCH_DESIGNED:
            payload = _payload(event, {"strategy", "batch", "standard_cases", "automation_mappings"})
            updated_strategy = TestStrategy.from_dict(payload["strategy"])
            batch = CaseBatch.from_dict(payload["batch"])
            cases = tuple(StandardTestCase.from_dict(item) for item in payload["standard_cases"])
            mappings = tuple(AutomationMapping.from_dict(item) for item in payload["automation_mappings"])
            current_strategy = state.strategy_by_id(updated_strategy.strategy_version_id)
            if current_strategy is None:
                raise R33Error("R3_3_EVENT_INVALID", "case batch references a missing strategy")
            if current_strategy.strategy_fingerprint != updated_strategy.strategy_fingerprint:
                raise R33Error("R3_3_EVENT_INVALID", "case batch changes strategy identity")
            if batch.strategy_version_id != updated_strategy.strategy_version_id or batch.batch_id != event.entity_id:
                raise R33Error("R3_3_EVENT_INVALID", "case batch identity mismatch")
            if state.batch(batch.batch_id) is not None:
                raise R33Error("R3_3_EVENT_INVALID", "case batch identity is not immutable")
            known_points = {item.point_id for item in state.test_points if item.strategy_version_id == batch.strategy_version_id}
            if not set(batch.test_point_refs).issubset(known_points):
                raise R33Error("R3_3_EVENT_INVALID", "case batch references an unknown TestPoint")
            if any(item.strategy_version_id != batch.strategy_version_id or item.batch_id != batch.batch_id for item in cases):
                raise R33Error("R3_3_EVENT_INVALID", "StandardTestCase batch identity mismatch")
            known_case_ids = {item.case_version_id for item in state.standard_cases}
            if any(item.case_version_id in known_case_ids for item in cases):
                raise R33Error("R3_3_EVENT_INVALID", "StandardTestCase version identity is not immutable")
            known_mapping_ids = {item.mapping_id for item in state.automation_mappings}
            if any(item.mapping_id in known_mapping_ids for item in mappings):
                raise R33Error("R3_3_EVENT_INVALID", "AutomationMapping identity is not immutable")
            case_ids = {item.case_version_id for item in cases}
            if any(item.case_version_id not in case_ids for item in mappings):
                raise R33Error("R3_3_EVENT_INVALID", "AutomationMapping cannot create a StandardTestCase")
            strategy = replace(
                current_strategy,
                standard_case_count=len(state.standard_cases) + len(cases),
                automation_mapping_count=len(state.automation_mappings) + len(mappings),
                automation_method_count=len({
                    method for item in state.automation_mappings for method in item.automation_method_refs
                } | {
                    method for item in mappings for method in item.automation_method_refs
                }),
                strategy_status=updated_strategy.strategy_status,
            )
            return replace(
                state,
                strategies=tuple(strategy if item.strategy_version_id == strategy.strategy_version_id else item for item in state.strategies),
                batches=state.batches + (batch,),
                standard_cases=state.standard_cases + cases,
                automation_mappings=state.automation_mappings + mappings,
            )
        if event.event_type == DESIGN_REUSED:
            payload = _payload(event, {"strategy_version_id", "strategy_fingerprint", "batch_id", "idempotency_key"})
            strategy = state.strategy_by_id(payload["strategy_version_id"])
            if strategy is None or strategy.strategy_fingerprint != payload["strategy_fingerprint"]:
                raise R33Error("R3_3_EVENT_INVALID", "reuse references a missing or mismatched strategy")
            reuse = R33ReuseReference(
                reuse_id=event.entity_id, strategy_version_id=payload["strategy_version_id"],
                strategy_fingerprint=payload["strategy_fingerprint"], idempotency_key=payload["idempotency_key"],
                batch_id=payload["batch_id"], created_seq=event.seq, created_at=event.created_at,
                correlation_id=event.correlation_id,
            )
            if any(item.reuse_id == reuse.reuse_id for item in state.reuses):
                raise R33Error("R3_3_EVENT_INVALID", "reuse identity is not immutable")
            return replace(state, reuses=state.reuses + (reuse,))
        raise R33Error("R3_3_EVENT_NOT_OWNED", f"unsupported R3.3 event: {event.event_type}")

