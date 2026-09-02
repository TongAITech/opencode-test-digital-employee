from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from aitest_runtime.durable_core import ActorRef, CommandResult, RuntimeService

from .contracts import ARCHITECTURE_BASELINE_REF, EXTENSION_ID, R37_EVALUATE_TEST_SUFFICIENCY, R37_SEMANTIC_REUSE, R37State
from .errors import R37Error
from .projections import ProjectionEnvelope, build_operations_projection
from .workset import TypedRetrievalProvider, retrieve_workset


@dataclass(frozen=True)
class R37OperationResult:
    command_result: CommandResult
    entity: Any | None = None
    remaining_risks: tuple[Any, ...] = ()

    @property
    def ok(self) -> bool:
        return self.command_result.ok

    @property
    def outcome(self) -> str:
        return self.command_result.outcome

    @property
    def error_code(self) -> str | None:
        return self.command_result.error_code

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command_result.to_dict(),
            "entity": self.entity.to_dict() if self.entity is not None else None,
            "remaining_risks": [item.to_dict() for item in self.remaining_risks],
        }


class R37ApplicationService:
    """Thin R3.7 application boundary over one shared RuntimeService."""

    def __init__(self, runtime: RuntimeService, *, actor: ActorRef | None = None) -> None:
        if runtime is None:
            raise R37Error("R3_7_SCHEMA_INVALID", "RuntimeService is required")
        try:
            runtime.extension_registry.manifest(EXTENSION_ID)
        except Exception as exc:
            raise R37Error("R3_7_EXTENSION_REQUIRED", "R3.7 requires its registered durable extension") from exc
        self.runtime = runtime
        self.actor = actor or ActorRef("SYSTEM", "r3.7")

    def state(self, mission_id: str) -> R37State:
        state = self.runtime.replay_composed(mission_id).extension_state(EXTENSION_ID)
        if not isinstance(state, R37State):
            raise R37Error("R3_7_STATE_INVALID", "R3.7 extension state is not registered")
        return state

    get_state = state

    @staticmethod
    def _request(raw: Mapping[str, Any], *, mission_id: str | None = None) -> dict[str, Any]:
        if not isinstance(raw, Mapping):
            raise R37Error("R3_7_SCHEMA_INVALID", "request must be an object")
        request = dict(raw)
        selected_mission = mission_id or request.get("mission_id")
        if not isinstance(selected_mission, str) or not selected_mission.strip():
            raise R37Error("R3_7_SCOPE_MISMATCH", "request.mission_id is required")
        request["mission_id"] = selected_mission
        idempotency_key = request.get("idempotency_key")
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise R37Error("R3_7_SCHEMA_INVALID", "request.idempotency_key is required")
        request["correlation_id"] = request.get("correlation_id") or f"corr:{idempotency_key}"
        origin = dict(request.get("origin_lineage") or {})
        origin["mission_id"] = selected_mission
        origin.setdefault("architecture_baseline_ref", ARCHITECTURE_BASELINE_REF)
        request["origin_lineage"] = origin
        if isinstance(request.get("evaluation"), Mapping):
            evaluation = dict(request["evaluation"])
            evaluation.setdefault("mission_id", selected_mission)
            evaluation.setdefault("origin_lineage", origin)
            request["evaluation"] = evaluation
        if isinstance(request.get("reuse"), Mapping):
            reuse = dict(request["reuse"])
            reuse.setdefault("origin_lineage", origin)
            request["reuse"] = reuse
        return request

    def _expected_seq(self, command_id: str, mission_id: str) -> int:
        for event in self.runtime.list_events(mission_id):
            if event.command_id == command_id:
                return event.seq - 1
        return self.runtime.get_head_seq(mission_id)

    def _execute(self, command_type: str, request: Mapping[str, Any]) -> R37OperationResult:
        prepared = self._request(request)
        mission_id = prepared["mission_id"]
        command_id = f"r3.7:{command_type}:{prepared['idempotency_key']}"
        result = self.runtime.execute({
            "command_id": command_id, "type": command_type, "mission_id": mission_id,
            "session_id": prepared.get("session_id"), "expected_seq": self._expected_seq(command_id, mission_id),
            "actor": self.actor.to_dict(), "payload": {"request": prepared},
            "idempotency_key": prepared["idempotency_key"], "correlation_id": prepared["correlation_id"], "schema_version": 1,
        })
        if not result.ok:
            return R37OperationResult(result)
        state = self.state(mission_id)
        if command_type == R37_EVALUATE_TEST_SUFFICIENCY:
            return R37OperationResult(result, state.decisions[-1] if state.decisions else None, state.remaining_risks)
        if command_type == R37_SEMANTIC_REUSE:
            return R37OperationResult(result, state.reuses[-1] if state.reuses else None)
        return R37OperationResult(result)

    def evaluate_test_sufficiency(self, request: Mapping[str, Any]) -> R37OperationResult:
        return self._execute(R37_EVALUATE_TEST_SUFFICIENCY, request)

    evaluate = evaluate_test_sufficiency
    evaluate_sufficiency = evaluate_test_sufficiency

    def record_semantic_reuse(self, request: Mapping[str, Any]) -> R37OperationResult:
        return self._execute(R37_SEMANTIC_REUSE, request)

    def operations_projection(
        self,
        mission_id: str,
        projection_type: str,
        *,
        scope: Mapping[str, Any],
        as_of_seq: int | None = None,
        observed_at: str = "engineering",
        freshness: str = "CURRENT",
        source_cursors: Mapping[str, Any] | None = None,
        source_payload: Mapping[str, Any] | None = None,
    ) -> ProjectionEnvelope:
        state = self.state(mission_id)
        return build_operations_projection(
            state, projection_type, scope=scope, as_of_seq=self.runtime.get_head_seq(mission_id) if as_of_seq is None else as_of_seq,
            observed_at=observed_at, freshness=freshness, source_cursors=source_cursors, source_payload=source_payload,
        )

    project_operations = operations_projection

    @staticmethod
    def retrieve_workset(request: Any, provider: TypedRetrievalProvider) -> Any:
        return retrieve_workset(request, provider)
