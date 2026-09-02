from __future__ import annotations

from typing import Mapping

from aitest_runtime.durable_core import RuntimeError, RuntimeService

from .builder import _ExecutionContextBuilder
from .contracts import BuildExecutionContextRequest, ExecutionContext
from .policy import ExecutionContextPolicyRegistry


class ExecutionContextApplicationService:
    def __init__(
        self,
        runtime_service: RuntimeService,
        policy_registry: ExecutionContextPolicyRegistry | None = None,
    ) -> None:
        if runtime_service is None:
            raise ValueError("runtime_service is required")
        self._runtime_service = runtime_service
        self._policy_registry = policy_registry or ExecutionContextPolicyRegistry()
        self._builder = _ExecutionContextBuilder()

    def build(self, request: BuildExecutionContextRequest) -> ExecutionContext:
        if isinstance(request, Mapping):
            request = BuildExecutionContextRequest.from_dict(request)
        if not isinstance(request, BuildExecutionContextRequest):
            raise RuntimeError("EXECUTION_CONTEXT_SCHEMA_INVALID", "request has an invalid type")
        if request.cursor.mission_id is not None and request.cursor.mission_id != request.mission_id:
            raise RuntimeError(
                "EVENT_CURSOR_MISSION_MISMATCH",
                "Event cursor is bound to another Mission",
                {"cursor_mission_id": request.cursor.mission_id, "request_mission_id": request.mission_id},
            )
        policy = self._policy_registry.get(request.policy_id, request.policy_version)
        head_seq = self._runtime_service.get_head_seq(request.mission_id)
        if request.cursor.through_seq > head_seq:
            raise RuntimeError(
                "EVENT_CURSOR_AHEAD",
                "Requested Event cursor is ahead of the Mission head",
                {"requested_seq": request.cursor.through_seq, "head_seq": head_seq},
            )
        replayed = self._runtime_service.replay_composed(
            request.mission_id,
            through_seq=request.cursor.through_seq,
        )
        if replayed.seq != request.cursor.through_seq:
            raise RuntimeError(
                "EVENT_CURSOR_MISMATCH",
                "Fixed-cursor composed replay did not reach the requested Event cursor",
                {"requested_seq": request.cursor.through_seq, "replayed_seq": replayed.seq},
            )
        return self._builder.build(request, replayed, policy)
