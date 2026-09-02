"""Explicit caller-injected R2.7 composition; HTTP/UI wiring stays open."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .actions import RuntimeOperationsActionRouter, RuntimeOperationsDependencies
from .contracts import CONTROL_PLANE_HTTP_INTEGRATION_GAP
from .queries import RuntimeOperationsQueryService


@dataclass(frozen=True)
class RuntimeOperationsComposition:
    query_service: RuntimeOperationsQueryService
    action_router: RuntimeOperationsActionRouter
    http_integration: str = CONTROL_PLANE_HTTP_INTEGRATION_GAP

    @property
    def runtime_service(self) -> Any:
        return self.query_service.runtime_service


def compose_runtime_operations(
    runtime_service: Any,
    *,
    mission_intake: Any = None,
    planner: Any = None,
    session: Any = None,
    human_gate: Any = None,
    dependencies: RuntimeOperationsDependencies | None = None,
    current_observation_source: Any = None,
    derived_timeline_source: Any = None,
) -> RuntimeOperationsComposition:
    """Compose R2.7 around caller-owned service instances.

    No default HTTP/UI registration or service construction occurs here.
    """

    deps = dependencies or RuntimeOperationsDependencies(
        runtime_service,
        mission_intake=mission_intake,
        planner=planner,
        session=session,
        human_gate=human_gate,
    )
    if deps.runtime_service is not runtime_service:
        raise ValueError("RuntimeOperationsDependencies must use the supplied RuntimeService")
    return RuntimeOperationsComposition(
        query_service=RuntimeOperationsQueryService(
            runtime_service,
            current_observation_source=current_observation_source,
            derived_timeline_source=derived_timeline_source,
        ),
        action_router=RuntimeOperationsActionRouter(deps),
    )


build_runtime_operations = compose_runtime_operations
compose_r2_7_runtime_operations = compose_runtime_operations


__all__ = [
    "CONTROL_PLANE_HTTP_INTEGRATION_GAP",
    "RuntimeOperationsComposition",
    "build_runtime_operations",
    "compose_r2_7_runtime_operations",
    "compose_runtime_operations",
]
