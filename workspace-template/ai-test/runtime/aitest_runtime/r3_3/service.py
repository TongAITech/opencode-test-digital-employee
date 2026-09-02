from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from aitest_runtime.durable_core import ActorRef, CommandResult, RuntimeError, RuntimeService

from .contracts import (
    CREATE_TEST_STRATEGY,
    DESIGN_CASE_BATCH,
    BatchDesignRequest,
    R33State,
    StandardTestCase,
    StrategyRequest,
    TestStrategy,
    AutomationMapping,
    CaseBatch,
)
from .extension import r3_3_extension


@dataclass(frozen=True)
class R33OperationResult:
    command_result: CommandResult
    strategy: TestStrategy | None = None
    batch: CaseBatch | None = None
    standard_cases: tuple[StandardTestCase, ...] = ()
    automation_mappings: tuple[AutomationMapping, ...] = ()

    @property
    def ok(self) -> bool:
        return self.command_result.ok

    @property
    def outcome(self) -> str:
        return self.command_result.outcome

    @property
    def error_code(self) -> str | None:
        return self.command_result.error_code


class R33ApplicationService:
    """R3.3 application boundary over the shared R1 RuntimeService."""

    def __init__(self, runtime: RuntimeService, *, actor: ActorRef | None = None) -> None:
        if runtime is None:
            raise ValueError("runtime is required")
        runtime.extension_registry.manifest("r3_3_test_strategy_standard_case_design")
        self.runtime = runtime
        self.actor = actor or ActorRef("SYSTEM", "r3.3")

    def state(self, mission_id: str) -> R33State:
        value = self.runtime.replay_composed(mission_id).extension_state("r3_3_test_strategy_standard_case_design")
        if not isinstance(value, R33State):
            raise RuntimeError("R3_3_STATE_INVALID", "R3.3 extension state is not registered")
        return value

    get_state = state

    def create_strategy(self, request: StrategyRequest) -> R33OperationResult:
        if not isinstance(request, StrategyRequest):
            raise TypeError("request must be a StrategyRequest")
        command_id = f"r3.3:{request.idempotency_key}:create_strategy"
        result = self.runtime.execute({
            "command_id": command_id,
            "type": CREATE_TEST_STRATEGY,
            "mission_id": request.mission_id,
            "session_id": None,
            "expected_seq": self._expected_seq(command_id, request.mission_id),
            "actor": self.actor.to_dict(),
            "payload": {"request": request.to_payload()},
            "idempotency_key": request.idempotency_key,
            "correlation_id": request.correlation_id,
            "schema_version": 1,
        })
        if not result.ok:
            return R33OperationResult(result)
        state = self.state(request.mission_id)
        strategy = next((item for item in state.strategies if item.idempotency_key == request.idempotency_key), None)
        if strategy is None and state.reuses:
            strategy = state.strategy_by_id(state.reuses[-1].strategy_version_id)
        return R33OperationResult(result, strategy=strategy)

    def design_case_batch(self, request: BatchDesignRequest) -> R33OperationResult:
        if not isinstance(request, BatchDesignRequest):
            raise TypeError("request must be a BatchDesignRequest")
        command_id = f"r3.3:{request.idempotency_key}:design_case_batch"
        mission_id = self._strategy_mission(request.strategy_version_id)
        result = self.runtime.execute({
            "command_id": command_id,
            "type": DESIGN_CASE_BATCH,
            "mission_id": mission_id,
            "session_id": request.designer_session_ref,
            "expected_seq": self._expected_seq(command_id, mission_id),
            "actor": self.actor.to_dict(),
            "payload": {"request": request.to_payload()},
            "idempotency_key": request.idempotency_key,
            "correlation_id": request.correlation_id,
            "schema_version": 1,
        })
        if not result.ok:
            return R33OperationResult(result)
        state = self.state(mission_id)
        batch = state.batch(request.batch_id) if request.batch_id else None
        if batch is None:
            batches = [item for item in state.batches if item.strategy_version_id == request.strategy_version_id]
            batch = batches[-1] if batches else None
        strategy = state.strategy_by_id(request.strategy_version_id)
        case_ids = set(batch.standard_case_version_refs) if batch else set()
        cases = tuple(item for item in state.standard_cases if item.case_version_id in case_ids)
        mappings = tuple(item for item in state.automation_mappings if item.mapping_id in set(batch.automation_mapping_refs)) if batch else ()
        return R33OperationResult(result, strategy=strategy, batch=batch, standard_cases=cases, automation_mappings=mappings)

    def _strategy_mission(self, strategy_version_id: str) -> str:
        for mission_id in self._candidate_missions():
            try:
                state = self.state(mission_id)
            except Exception:
                continue
            strategy = state.strategy_by_id(strategy_version_id)
            if strategy is not None:
                return strategy.mission_id
        raise RuntimeError("R3_3_STRATEGY_NOT_FOUND", f"strategy_version_id is not registered: {strategy_version_id}")

    def _expected_seq(self, command_id: str, mission_id: str) -> int:
        from aitest_runtime.durable_core.schema import connect
        conn = connect(self.runtime.db_path)
        try:
            row = conn.execute("SELECT expected_seq FROM commands WHERE command_id=?", (command_id,)).fetchone()
            return int(row["expected_seq"]) if row is not None else self.runtime.get_head_seq(mission_id)
        finally:
            conn.close()

    def _candidate_missions(self) -> tuple[str, ...]:
        # The runtime core has no cross-mission query API. R3.3 callers normally
        # retain the mission identity from StrategyRequest; this fallback only
        # supports a single active mission without creating new truth.
        import sqlite3
        from aitest_runtime.durable_core.schema import connect
        conn = connect(self.runtime.db_path)
        try:
            rows = conn.execute("SELECT mission_id FROM mission_projection ORDER BY mission_id").fetchall()
            return tuple(str(row["mission_id"]) for row in rows)
        finally:
            conn.close()


def request_from_mapping(value: Mapping[str, Any]) -> StrategyRequest:
    return StrategyRequest.from_payload(value, correlation_id=value.get("correlation_id") or value.get("idempotency_key"))


def batch_request_from_mapping(value: Mapping[str, Any]) -> BatchDesignRequest:
    return BatchDesignRequest.from_payload(value, correlation_id=value.get("correlation_id") or value.get("idempotency_key"))
