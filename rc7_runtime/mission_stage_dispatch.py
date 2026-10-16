"""Owner-aware dispatcher for durable RC7 Mission stages.

The dispatcher is deliberately thin. It never performs Requirement/Code/Test
work itself. It only reads the durable graph contract, selects the highest
priority READY task, and delegates that task to the owner defined by Mission
Graph v2. Runtime-owned work must never fall through to DSH workers; producer
work must never be executed by the coordinator/Director.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional

from .closed_loop_control import ClosedLoopControlPlane
from .mission_conformance import MissionConformanceChecker
from .mission_graph import MissionTaskGraphCompiler
from .models import Task


class MissionStageDispatchError(RuntimeError):
    pass


@dataclass(frozen=True)
class MissionStageRoute:
    task_id: str
    node: str
    graph_version: str
    owner: str
    action: str


class MissionStageDispatcher:
    """Route one READY canonical task to its actual execution authority."""

    def __init__(
        self,
        control: ClosedLoopControlPlane,
        *,
        runtime_handlers: Optional[Mapping[str, Callable[[Task], Any]]] = None,
        producer_runner: Optional[Callable[[], Any]] = None,
    ) -> None:
        self.control = control
        self.runtime_handlers = dict(runtime_handlers or {})
        self.producer_runner = producer_runner

    def next_route(self) -> Optional[MissionStageRoute]:
        conformance = MissionConformanceChecker(self.control.truth).check(self.control.mission_id)
        if conformance.status != "PASS":
            raise MissionStageDispatchError(
                "MISSION_CONFORMANCE_REQUIRED_BEFORE_DISPATCH:%s"
                % ",".join(conformance.violations)
            )
        ready = self.control.scheduler.ready_tasks(self.control.mission_id)
        if not ready:
            return None
        task = ready[0]
        compiler = MissionTaskGraphCompiler(conformance.graph_version)
        if task.node not in compiler.NODE_ORDER:
            raise MissionStageDispatchError("READY_NONCANONICAL_TASK_FORBIDDEN:%s" % task.node)
        owner = compiler.task_owner(task.node)
        if owner == compiler.OWNER_RUNTIME:
            action = "RUNTIME_HANDLER"
        elif owner == compiler.OWNER_PRODUCER:
            action = "PRODUCER_WORKER"
        else:
            raise MissionStageDispatchError("READY_TASK_OWNER_NOT_EXECUTABLE:%s:%s" % (task.node, owner))
        return MissionStageRoute(
            task_id=task.task_id,
            node=task.node,
            graph_version=compiler.graph_version,
            owner=owner,
            action=action,
        )

    def dispatch_next(self) -> Any:
        route = self.next_route()
        if route is None:
            return None
        task = self.control.scheduler.task(route.task_id)
        if route.action == "RUNTIME_HANDLER":
            handler = self.runtime_handlers.get(route.node)
            if handler is None:
                raise MissionStageDispatchError("RUNTIME_HANDLER_REQUIRED:%s" % route.node)
            return handler(task)
        if route.action == "PRODUCER_WORKER":
            if self.producer_runner is None:
                raise MissionStageDispatchError("PRODUCER_RUNNER_REQUIRED:%s" % route.node)
            return self.producer_runner()
        raise MissionStageDispatchError("MISSION_STAGE_ROUTE_ACTION_UNSUPPORTED:%s" % route.action)
