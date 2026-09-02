from __future__ import annotations

from typing import Any, Mapping

from aitest_runtime.durable_core import ComposedRuntimeState, PendingEvent

from .contracts import (
    CASE_BATCH_DESIGNED,
    CREATE_TEST_STRATEGY,
    DESIGN_CASE_BATCH,
    DESIGN_REUSED,
    STRATEGY_CREATED,
    BatchDesignRequest,
    R33Error,
    R33State,
    StrategyRequest,
)
from .engine import build_strategy, design_case_batch


def _state(composed: ComposedRuntimeState) -> R33State:
    value = composed.extension_state("r3_3_test_strategy_standard_case_design")
    if not isinstance(value, R33State):
        raise R33Error("EXTENSION_SCHEMA_MISMATCH", "invalid R3.3 extension state")
    return value


def _payload(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise R33Error("R3_3_SCHEMA_INVALID", f"{name} must be an object")
    return dict(value)


def handle(command: Any, composed: ComposedRuntimeState) -> list[PendingEvent]:
    state = _state(composed)
    if command.type == CREATE_TEST_STRATEGY:
        payload = _payload(command.payload, "command.payload")
        if set(payload) != {"request"}:
            raise R33Error("R3_3_SCHEMA_INVALID", "R3.3 strategy command must contain request only")
        request = StrategyRequest.from_payload(payload["request"], command_mission_id=command.mission_id, correlation_id=command.correlation_id)
        if command.idempotency_key != request.idempotency_key:
            raise R33Error("R3_3_IDEMPOTENCY_KEY_MISMATCH", "command idempotency key must match strategy request")
        r31_state = composed.extension_state("r3_1_requirement_coverage_traceability")
        r32_state = composed.extension_state("r3_2_change_impact_reconciliation")
        strategy, points = build_strategy(request, r31_state, r32_state)
        existing = state.strategy(strategy.strategy_fingerprint)
        if existing is not None:
            return [
                PendingEvent(
                    DESIGN_REUSED,
                    "R3_3_DESIGN",
                    f"r3.3:reuse:{command.command_id}",
                    {
                        "strategy_version_id": existing.strategy_version_id,
                        "strategy_fingerprint": existing.strategy_fingerprint,
                        "batch_id": None,
                        "idempotency_key": request.idempotency_key,
                    },
                    session_id=command.session_id,
                )
            ]
        return [
            PendingEvent(
                STRATEGY_CREATED,
                "R3_3_STRATEGY",
                strategy.strategy_id,
                {"strategy": strategy.to_dict(), "test_points": [item.to_dict() for item in points]},
                session_id=command.session_id,
            )
        ]
    if command.type == DESIGN_CASE_BATCH:
        payload = _payload(command.payload, "command.payload")
        if set(payload) != {"request"}:
            raise R33Error("R3_3_SCHEMA_INVALID", "R3.3 batch command must contain request only")
        request = BatchDesignRequest.from_payload(payload["request"], command_mission_id=command.mission_id, correlation_id=command.correlation_id)
        if command.idempotency_key != request.idempotency_key:
            raise R33Error("R3_3_IDEMPOTENCY_KEY_MISMATCH", "command idempotency key must match batch request")
        strategy = state.strategy_by_id(request.strategy_version_id)
        if strategy is None:
            raise R33Error("R3_3_STRATEGY_NOT_FOUND", "strategy_version_id is not registered")
        if request.batch_id is not None and state.batch(request.batch_id) is not None:
            batch = state.batch(request.batch_id)
            if batch is not None and batch.strategy_version_id == strategy.strategy_version_id:
                return [
                    PendingEvent(
                        DESIGN_REUSED,
                        "R3_3_DESIGN",
                        f"r3.3:reuse:{command.command_id}",
                        {
                            "strategy_version_id": strategy.strategy_version_id,
                            "strategy_fingerprint": strategy.strategy_fingerprint,
                            "batch_id": batch.batch_id,
                            "idempotency_key": request.idempotency_key,
                        },
                        session_id=command.session_id,
                    )
                ]
        points = state.points_for(strategy.strategy_version_id)
        batch, cases, mappings, updated_strategy = design_case_batch(
            strategy, points, request, existing_cases=tuple(
                item for item in state.standard_cases if item.strategy_version_id == strategy.strategy_version_id
            ),
        )
        return [
            PendingEvent(
                CASE_BATCH_DESIGNED,
                "R3_3_BATCH",
                batch.batch_id,
                {
                    "strategy": updated_strategy.to_dict(),
                    "batch": batch.to_dict(),
                    "standard_cases": [item.to_dict() for item in cases],
                    "automation_mappings": [item.to_dict() for item in mappings],
                },
                session_id=command.session_id,
            )
        ]
    raise R33Error("R3_3_UNSUPPORTED_COMMAND", f"unsupported R3.3 command: {command.type}")


class R33CommandContribution:
    def handle(self, command: Any, composed: ComposedRuntimeState) -> list[PendingEvent]:
        return handle(command, composed)

