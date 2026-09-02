"""R2.7 action routing over the existing frozen application boundaries."""

from __future__ import annotations

from collections.abc import Mapping
import inspect
from typing import Any

from aitest_runtime.r2_2 import MissionIntakeRequest
from aitest_runtime.r2_3 import PlannerInput
from aitest_runtime.r2_4 import TRANSITION_TASK

from .contracts import (
    CANCEL_TASK,
    COMMAND_ACTIONS,
    CONTINUE_MISSION,
    FORCE_ROTATE_SESSION,
    PAUSE_MISSION,
    RECORD_HUMAN_CONTINUATION,
    REQUEST_SESSION_ROTATION,
    RETRY_TASK,
    R2_7_ACTION_BOUNDARY_UNAVAILABLE,
    R2_7_ACTION_REQUEST_INVALID,
    R2_7_ACTION_UNSUPPORTED,
    R27Error,
    REVISE_GOAL,
    REVISE_PLAN,
    RuntimeOperationsActionRequest,
    SUBMIT_HUMAN_DECISION,
)


class RuntimeOperationsDependencies:
    """Caller-injected references to the real R2.2--R2.6 boundaries."""

    def __init__(
        self,
        runtime_service: Any,
        mission_intake: Any = None,
        planner: Any = None,
        session: Any = None,
        human_gate: Any = None,
        **aliases: Any,
    ) -> None:
        self.runtime_service = runtime_service
        self.mission_intake = mission_intake if mission_intake is not None else aliases.pop("mission_intake_orchestrator", None)
        self.planner = planner if planner is not None else aliases.pop("planner_orchestrator", None)
        self.session = session if session is not None else aliases.pop("session_orchestration_service", None)
        self.human_gate = human_gate if human_gate is not None else aliases.pop("human_gate_application_service", None)
        if aliases:
            raise R27Error(R2_7_ACTION_REQUEST_INVALID, f"unsupported RuntimeOperationsDependencies fields: {sorted(aliases)}")
        if runtime_service is None:
            raise R27Error(R2_7_ACTION_BOUNDARY_UNAVAILABLE, "RuntimeService is unavailable")
        self._verify_shared_runtime()

    @property
    def mission_intake_orchestrator(self) -> Any:
        return self.mission_intake

    @property
    def planner_orchestrator(self) -> Any:
        return self.planner

    @property
    def session_orchestration_service(self) -> Any:
        return self.session

    @property
    def human_gate_application_service(self) -> Any:
        return self.human_gate

    def _verify_shared_runtime(self) -> None:
        for name, service in (
            ("mission_intake", self.mission_intake),
            ("planner", self.planner),
            ("session", self.session),
            ("human_gate", self.human_gate),
        ):
            if service is None:
                continue
            service_runtime = getattr(service, "runtime_service", None)
            if service_runtime is None or service_runtime is not self.runtime_service:
                raise R27Error(
                    R2_7_ACTION_BOUNDARY_UNAVAILABLE,
                    f"{name} does not share the injected RuntimeService",
                )


class RuntimeOperationsActionRouter:
    """Route only to existing CommandBus/application-service ports."""

    def __init__(self, dependencies: RuntimeOperationsDependencies) -> None:
        if not isinstance(dependencies, RuntimeOperationsDependencies):
            raise R27Error(R2_7_ACTION_BOUNDARY_UNAVAILABLE, "RuntimeOperationsDependencies is required")
        self._dependencies = dependencies

    @property
    def dependencies(self) -> RuntimeOperationsDependencies:
        return self._dependencies

    def dispatch(self, request: RuntimeOperationsActionRequest | Mapping[str, Any]) -> Any:
        action_request = RuntimeOperationsActionRequest.from_mapping(request)
        action = action_request.action
        if action in {RETRY_TASK, FORCE_ROTATE_SESSION}:
            raise R27Error(R2_7_ACTION_UNSUPPORTED, f"{action} is unsupported in R2.7 V1")
        if action in COMMAND_ACTIONS:
            return self._dispatch_command(action_request)
        if action == REVISE_GOAL:
            service = self._port(self._dependencies.mission_intake, "MissionIntakeOrchestrator", "intake")
            value = action_request.action_input()
            operation = value.get("operation")
            if operation is None:
                value["operation"] = "REVISE"
            elif str(operation).upper() != "REVISE":
                raise R27Error(R2_7_ACTION_REQUEST_INVALID, "REVISE_GOAL requires operation=REVISE")
            return service(MissionIntakeRequest.from_mapping(value))
        if action == REVISE_PLAN:
            service = self._port(self._dependencies.planner, "PlannerOrchestrator", "plan_or_revise")
            if not self._planner_supports_metadata(service):
                raise R27Error(
                    R2_7_ACTION_BOUNDARY_UNAVAILABLE,
                    "frozen PlannerOrchestrator does not natively accept idempotency_key and correlation_id",
                )
            value = action_request.action_input()
            metadata = {
                "idempotency_key": action_request.idempotency_key,
                "correlation_id": action_request.correlation_id,
            }
            planner_value = {
                key: item
                for key, item in value.items()
                if key not in {"idempotency_key", "correlation_id"}
            }
            # PlannerInput has no metadata fields; the caller-owned values are
            # passed unchanged as native method metadata below.
            try:
                return service(PlannerInput.from_mapping(planner_value), **metadata)
            except TypeError as exc:
                raise R27Error(
                    R2_7_ACTION_BOUNDARY_UNAVAILABLE,
                    "planner metadata parameters are not callable at the requested boundary",
                ) from exc
        if action == REQUEST_SESSION_ROTATION:
            service = self._port(self._dependencies.session, "SessionOrchestrationService", "rotate_session")
            value = action_request.action_input()
            if value.get("force") is True or str(value.get("rotation_mode", "")).upper() == "FORCE":
                raise R27Error(R2_7_ACTION_UNSUPPORTED, "forced session rotation is unsupported in R2.7 V1")
            return service(value)
        if action == SUBMIT_HUMAN_DECISION:
            service = self._port(self._dependencies.human_gate, "HumanGateApplicationService", "record_decision")
            return service(action_request.action_input())
        if action == RECORD_HUMAN_CONTINUATION:
            service = self._port(self._dependencies.human_gate, "HumanGateApplicationService", "record_continuation")
            return service(action_request.action_input())
        raise R27Error(R2_7_ACTION_UNSUPPORTED, f"unsupported Runtime Operations action: {action}")

    route = dispatch
    execute = dispatch
    apply = dispatch

    @staticmethod
    def _port(port: Any, name: str, method: str) -> Any:
        if port is None:
            raise R27Error(R2_7_ACTION_BOUNDARY_UNAVAILABLE, f"requested action boundary is unavailable: {name}")
        try:
            candidate = getattr(port, method, None)
        except Exception as exc:
            raise R27Error(
                R2_7_ACTION_BOUNDARY_UNAVAILABLE,
                f"requested action boundary is unavailable: {name}.{method}",
            ) from exc
        if not callable(candidate):
            raise R27Error(
                R2_7_ACTION_BOUNDARY_UNAVAILABLE,
                f"requested action boundary is unavailable: {name}.{method}",
            )
        return candidate

    @staticmethod
    def _planner_supports_metadata(method: Any) -> bool:
        try:
            parameters = inspect.signature(method).parameters
        except (TypeError, ValueError):
            return False
        for name in ("idempotency_key", "correlation_id"):
            parameter = parameters.get(name)
            if parameter is not None and parameter.kind == inspect.Parameter.POSITIONAL_ONLY:
                return False
        return (
            all(name in parameters for name in ("idempotency_key", "correlation_id"))
            or any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values())
        )

    def _dispatch_command(self, request: RuntimeOperationsActionRequest) -> Any:
        payload = dict(request.target)
        payload.update(request.payload)
        command_type = request.action
        if request.action == CANCEL_TASK:
            command_type = TRANSITION_TASK
            supplied_target = payload.get("target_state")
            if supplied_target is not None and str(supplied_target) != "CANCELLED":
                raise R27Error(R2_7_ACTION_REQUEST_INVALID, "CANCEL_TASK can only target CANCELLED")
            payload["target_state"] = "CANCELLED"
        command = {
            "command_id": request.command_id,
            "type": command_type,
            "mission_id": request.mission_id,
            "expected_seq": request.expected_seq,
            "actor": dict(request.actor or {}),
            "payload": payload,
            "idempotency_key": request.idempotency_key,
            "correlation_id": request.correlation_id,
            "schema_version": request.schema_version,
        }
        # The shared RuntimeService is the existing Mission CommandBus port.
        execute = self._port(self._dependencies.runtime_service, "RuntimeService", "execute")
        return execute(command)


RuntimeOperationsActionApplicationService = RuntimeOperationsActionRouter


__all__ = [
    "RuntimeOperationsActionApplicationService",
    "RuntimeOperationsActionRouter",
    "RuntimeOperationsActionRequest",
    "RuntimeOperationsDependencies",
]
