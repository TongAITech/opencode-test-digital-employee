"""Recoverable R2.2 Mission Intake orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from aitest_runtime.durable_core import CommandResult, RuntimeError as DurableRuntimeError
from aitest_runtime.durable_core import RuntimeService
from aitest_runtime.r2_1 import IdempotencyConflict as R2_1IdempotencyConflict
from aitest_runtime.r2_1 import RuntimeFactsResolver, resolve_runtime_facts

from .contracts import (
    IdempotencyConflict,
    MissionIntakeError,
    MissionIntakeRequest,
    OP_CREATE,
    OP_REVISE,
)
from .normalizer import build_goal_definition, build_resolution_request, normalize_request


def _error(code: str, message: str, details: Mapping[str, Any] | None = None) -> MissionIntakeError:
    return MissionIntakeError(code, message, details)


@dataclass(frozen=True)
class MissionIntakeResult:
    outcome: str
    operation: str
    intake_id: str
    normalized_digest: str
    mission_id: str
    goal_id: str
    command_results: tuple[CommandResult, ...]
    mission: Mapping[str, Any]
    goal: Mapping[str, Any]
    resolution: Mapping[str, Any]
    replayed: bool = False

    @property
    def ok(self) -> bool:
        return self.outcome in {"APPLIED", "DUPLICATE"}

    @property
    def command_ids(self) -> tuple[str, ...]:
        return tuple(item.command_id for item in self.command_results)

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "status": self.outcome,
            "operation": self.operation,
            "intake_id": self.intake_id,
            "normalized_digest": self.normalized_digest,
            "mission_id": self.mission_id,
            "goal_id": self.goal_id,
            "command_results": [item.to_dict() for item in self.command_results],
            "commands": [item.to_dict() for item in self.command_results],
            "command_ids": list(self.command_ids),
            "mission": dict(self.mission),
            "goal": dict(self.goal),
            "resolution": dict(self.resolution),
            "replayed": self.replayed,
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)


def _mission_id(request: MissionIntakeRequest) -> str:
    return request.mission_id or f"r2.2:mission:{request.intake_id}"


def _goal_id(request: MissionIntakeRequest, mission: Any | None = None) -> str:
    if request.goal_id:
        return request.goal_id
    if mission is not None and getattr(mission, "active_goal_id", None):
        return str(mission.active_goal_id)
    return f"r2.2:goal:{request.intake_id}"


def _command_id(intake_id: str, command_type: str) -> str:
    return f"r2.2:{intake_id}:{command_type}"


def _state_dict(state: Any) -> dict[str, Any]:
    return state.to_dict() if hasattr(state, "to_dict") else dict(state)


def _mission_attributes(mission: Any) -> dict[str, Any]:
    raw = getattr(mission, "attributes", {}) or {}
    return dict(raw) if isinstance(raw, Mapping) else {}


def _marker(value: Mapping[str, Any]) -> tuple[str | None, str | None]:
    return (
        str(value.get("intake_id")) if value.get("intake_id") is not None else None,
        str(value.get("normalized_digest")) if value.get("normalized_digest") is not None else None,
    )


def _goal_history(runtime_service: RuntimeService, mission_id: str) -> list[tuple[str, str | None, str | None, int]]:
    history: list[tuple[str, str | None, str | None, int]] = []
    for event in runtime_service.list_events(mission_id):
        if event.event_type not in {"goal.created", "goal.revised"}:
            continue
        definition = event.payload.get("definition")
        if not isinstance(definition, Mapping):
            continue
        intake_id, digest = _marker(definition)
        if intake_id is not None:
            history.append((event.event_type, intake_id, digest, event.seq))
    return history


def _command_or_raise(result: CommandResult) -> CommandResult:
    if result.ok:
        return result
    if result.error is None:
        raise _error("COMMAND_REJECTED", f"durable command was rejected: {result.command_id}")
    raise MissionIntakeError(result.error.code, result.error.message, result.error.details)


class MissionIntakeOrchestrator:
    """Application boundary for the frozen R2.2 intake flow."""

    def __init__(
        self,
        runtime_service: RuntimeService,
        resolver: RuntimeFactsResolver | None = None,
    ) -> None:
        if runtime_service is None:
            raise ValueError("runtime_service is required")
        self._runtime_service = runtime_service
        self._resolver = resolver or RuntimeFactsResolver()

    @property
    def runtime_service(self) -> RuntimeService:
        return self._runtime_service

    def intake(
        self,
        value: Mapping[str, Any] | MissionIntakeRequest,
        *,
        facts: list[dict[str, Any]] | None = None,
        capabilities: list[dict[str, Any]] | None = None,
        source_precedence: Any = None,
        resolution: Mapping[str, Any] | None = None,
    ) -> MissionIntakeResult:
        # This is deliberately the first operation: malformed requests and
        # raw secrets cannot reach R2.1 or the durable RuntimeService.
        if facts is not None or capabilities is not None or source_precedence is not None:
            raw = value.to_mapping(include_digest=False) if isinstance(value, MissionIntakeRequest) else dict(value)
            if facts is not None:
                raw["facts"] = facts
            if capabilities is not None:
                raw["capabilities"] = capabilities
            if source_precedence is not None:
                raw["source_precedence"] = source_precedence
            raw.pop("normalized_digest", None)
            request = normalize_request(raw)
        else:
            request = normalize_request(value)
        mission_id = _mission_id(request)
        current = self._runtime_service.replay(mission_id)

        if request.operation == OP_CREATE:
            return self._create(request, current, facts, capabilities, source_precedence, resolution)
        return self._revise(request, current, facts, capabilities, source_precedence, resolution)

    execute = intake
    submit = intake
    orchestrate = intake
    run = intake

    def _resolve(
        self,
        request: MissionIntakeRequest,
        *,
        facts: list[dict[str, Any]] | None,
        capabilities: list[dict[str, Any]] | None,
        source_precedence: Any,
        resolution: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        if resolution is not None:
            if not isinstance(resolution, Mapping):
                raise _error("resolution must be an object")
            return dict(resolution)

        raw = build_resolution_request(request)
        direct = raw.get("resolution")
        if isinstance(direct, Mapping) and "status" in direct:
            return dict(direct)
        if facts is not None:
            raw["facts"] = facts
        if capabilities is not None:
            raw["capabilities"] = capabilities
        if source_precedence is not None:
            raw["source_precedence"] = source_precedence
        try:
            return self._resolver.resolve(raw)
        except R2_1IdempotencyConflict:
            raise
        except DurableRuntimeError:
            # R2.1 request-level failures that survive R2.2's structural
            # boundary are represented as INVALID scope resolution, so the
            # Goal remains durable and carries the reason.
            return {
                "resolution_id": raw.get("resolution_id"),
                "request_digest": raw.get("request_digest"),
                "snapshot_id": None,
                "fact_set_digest": None,
                "status": "INVALID",
                "reason_code": "R2_1_RESOLUTION_INVALID",
                "source_refs": [],
                "valid_until": raw.get("valid_until"),
            }

    def _check_create_identity(self, request: MissionIntakeRequest, current: Any) -> None:
        mission = current.mission
        if mission is None:
            return
        owner_id, owner_digest = _marker(_mission_attributes(mission))
        if owner_id is None or owner_digest is None:
            raise _error("MISSION_IDENTITY_CONFLICT", "Mission identity is not an R2.2 intake")
        if owner_id != request.intake_id or owner_digest != request.normalized_digest:
            raise IdempotencyConflict(request.intake_id)

    def _create(
        self,
        request: MissionIntakeRequest,
        current: Any,
        facts: list[dict[str, Any]] | None,
        capabilities: list[dict[str, Any]] | None,
        source_precedence: Any,
        supplied_resolution: Mapping[str, Any] | None,
    ) -> MissionIntakeResult:
        self._check_create_identity(request, current)
        existing_goal = None
        if current.mission is not None:
            existing_goal = current.goal(_goal_id(request, current.mission))

        command_results: list[CommandResult] = []
        replayed = current.mission is not None and existing_goal is not None
        if current.mission is None:
            mission_command = {
                "command_id": _command_id(request.intake_id, "CREATE_MISSION"),
                "type": "CREATE_MISSION",
                "mission_id": _mission_id(request),
                "expected_seq": 0,
                "actor": dict(request.actor),
                "payload": {
                    "contract_version": request.schema_version,
                    "intake_id": request.intake_id,
                    "normalized_digest": request.normalized_digest,
                    "title": str(request.goal.get("title") or request.goal.get("intent") or request.intake_id),
                    "mission_type": "TEST",
                },
                "correlation_id": request.intake_id,
                "schema_version": 1,
            }
            command_results.append(_command_or_raise(self._runtime_service.execute(mission_command)))
            current = self._runtime_service.replay(_mission_id(request))
            replayed = False
            existing_goal = current.goal(_goal_id(request, current.mission)) if current.mission else None

        resolution_result = self._resolve(
            request,
            facts=facts,
            capabilities=capabilities,
            source_precedence=source_precedence,
            resolution=supplied_resolution,
        )
        definition = build_goal_definition(request, resolution_result, source_precedence=source_precedence)
        goal_id = _goal_id(request, current.mission)

        if existing_goal is None:
            goal_command = {
                "command_id": _command_id(request.intake_id, "CREATE_GOAL"),
                "type": "CREATE_GOAL",
                "mission_id": _mission_id(request),
                "expected_seq": self._runtime_service.get_head_seq(_mission_id(request)),
                "actor": dict(request.actor),
                "payload": {"goal_id": goal_id, "goal": definition},
                "correlation_id": request.intake_id,
                "schema_version": 1,
            }
            command_results.append(_command_or_raise(self._runtime_service.execute(goal_command)))
            replayed = False
        else:
            # Re-submit completed command identities. RuntimeService returns
            # their durable results without appending another Event.
            if replayed:
                mission_command = {
                    "command_id": _command_id(request.intake_id, "CREATE_MISSION"),
                    "type": "CREATE_MISSION",
                    "mission_id": _mission_id(request),
                    "expected_seq": 0,
                    "actor": dict(request.actor),
                    "payload": {
                        "contract_version": request.schema_version,
                        "intake_id": request.intake_id,
                        "normalized_digest": request.normalized_digest,
                        "title": str(request.goal.get("title") or request.goal.get("intent") or request.intake_id),
                        "mission_type": "TEST",
                    },
                    "correlation_id": request.intake_id,
                    "schema_version": 1,
                }
                goal_command = {
                    "command_id": _command_id(request.intake_id, "CREATE_GOAL"),
                    "type": "CREATE_GOAL",
                    "mission_id": _mission_id(request),
                    "expected_seq": 1,
                    "actor": dict(request.actor),
                    "payload": {"goal_id": goal_id, "goal": definition},
                    "correlation_id": request.intake_id,
                    "schema_version": 1,
                }
                command_results.extend(
                    [
                        _command_or_raise(self._runtime_service.execute(mission_command)),
                        _command_or_raise(self._runtime_service.execute(goal_command)),
                    ]
                )

        return self._result(request, resolution_result, command_results, replayed)

    def _revise(
        self,
        request: MissionIntakeRequest,
        current: Any,
        facts: list[dict[str, Any]] | None,
        capabilities: list[dict[str, Any]] | None,
        source_precedence: Any,
        supplied_resolution: Mapping[str, Any] | None,
    ) -> MissionIntakeResult:
        if current.mission is None:
            raise _error("MISSION_NOT_FOUND", "Mission not found")
        mission_id = _mission_id(request)
        goal_id = _goal_id(request, current.mission)
        goal = current.goal(goal_id)
        if goal is None:
            raise _error("GOAL_NOT_FOUND", "Goal not found")

        for _, history_intake, history_digest, _ in _goal_history(self._runtime_service, mission_id):
            if history_intake == request.intake_id and history_digest != request.normalized_digest:
                raise IdempotencyConflict(request.intake_id)

        existing_intake, existing_digest = _marker(goal.definition)
        if existing_intake == request.intake_id:
            if existing_digest != request.normalized_digest:
                raise IdempotencyConflict(request.intake_id)
            if goal.revision == int(request.base_revision) + 1:
                resolution_result = self._resolve(
                    request,
                    facts=facts,
                    capabilities=capabilities,
                    source_precedence=source_precedence,
                    resolution=supplied_resolution,
                )
                definition = build_goal_definition(request, resolution_result, source_precedence=source_precedence)
                command = {
                    "command_id": _command_id(request.intake_id, "REVISE_GOAL"),
                    "type": "REVISE_GOAL",
                    "mission_id": mission_id,
                    "expected_seq": self._runtime_service.get_head_seq(mission_id) - 1,
                    "actor": dict(request.actor),
                    "payload": {
                        "goal_id": goal_id,
                        "base_revision": request.base_revision,
                        "goal": definition,
                    },
                    "correlation_id": request.intake_id,
                    "schema_version": 1,
                }
                result = _command_or_raise(self._runtime_service.execute(command))
                return self._result(request, resolution_result, [result], True)
        if goal.revision != request.base_revision:
            raise _error(
                "GOAL_REVISION_MISMATCH",
                f"expected Goal revision {goal.revision}, received {request.base_revision}",
            )

        resolution_result = self._resolve(
            request,
            facts=facts,
            capabilities=capabilities,
            source_precedence=source_precedence,
            resolution=supplied_resolution,
        )
        definition = build_goal_definition(request, resolution_result, source_precedence=source_precedence)
        command = {
            "command_id": _command_id(request.intake_id, "REVISE_GOAL"),
            "type": "REVISE_GOAL",
            "mission_id": mission_id,
            "expected_seq": self._runtime_service.get_head_seq(mission_id),
            "actor": dict(request.actor),
            "payload": {
                "goal_id": goal_id,
                "base_revision": request.base_revision,
                "goal": definition,
            },
            "correlation_id": request.intake_id,
            "schema_version": 1,
        }
        result = _command_or_raise(self._runtime_service.execute(command))
        return self._result(request, resolution_result, [result], False)

    def _result(
        self,
        request: MissionIntakeRequest,
        resolution: Mapping[str, Any],
        command_results: list[CommandResult],
        replayed: bool,
    ) -> MissionIntakeResult:
        mission_id = _mission_id(request)
        state = self._runtime_service.get_state(mission_id)
        goal_id = _goal_id(request, state.mission)
        goal = state.goal(goal_id)
        if goal is None:
            raise _error("RUNTIME_INVARIANT_VIOLATION", "durable Goal is missing after intake")
        return MissionIntakeResult(
            outcome="DUPLICATE" if replayed else "APPLIED",
            operation=request.operation,
            intake_id=request.intake_id,
            normalized_digest=request.normalized_digest or "",
            mission_id=mission_id,
            goal_id=goal_id,
            command_results=tuple(command_results),
            mission=state.mission.to_dict() if state.mission else {},
            goal=goal.to_dict(),
            resolution=dict(resolution),
            replayed=replayed,
        )


def orchestrate_mission_intake(
    runtime_service: RuntimeService,
    request: Mapping[str, Any] | MissionIntakeRequest,
    *,
    resolver: RuntimeFactsResolver | None = None,
    facts: list[dict[str, Any]] | None = None,
    capabilities: list[dict[str, Any]] | None = None,
    source_precedence: Any = None,
    resolution: Mapping[str, Any] | None = None,
) -> MissionIntakeResult:
    return MissionIntakeOrchestrator(runtime_service, resolver).intake(
        request,
        facts=facts,
        capabilities=capabilities,
        source_precedence=source_precedence,
        resolution=resolution,
    )


intake_mission = orchestrate_mission_intake
handle_mission_intake = orchestrate_mission_intake
MissionIntakeService = MissionIntakeOrchestrator
MissionIntakeApplicationService = MissionIntakeOrchestrator


__all__ = [
    "MissionIntakeResult",
    "MissionIntakeOrchestrator",
    "orchestrate_mission_intake",
    "intake_mission",
    "handle_mission_intake",
    "MissionIntakeService",
    "MissionIntakeApplicationService",
]
