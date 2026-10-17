"""Owner-aware dispatcher for durable RC7 Mission stages.

The dispatcher is deliberately thin. It never performs Requirement/Code/Test
work itself. It only reads durable R1 truth, selects the highest-priority READY
task, and delegates it to a governed execution authority.

Only the exact compiled canonical Task identities inherit Mission Graph owner
semantics. A dynamic task cannot borrow a canonical node name to bypass Gap
governance. Dynamic repair/defect work is admitted only through an explicit
(node, task_type) policy and must reference existing governed Gaps in the same
Mission and target node.
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
    """Route one READY task to its actual execution authority."""

    # Dynamic producer tasks are deliberately separate from canonical graph
    # tasks. They need governed Gap refs before a DSH worker may own them.
    _DYNAMIC_PRODUCER_TASKS = {
        ("RUNTIME", "REPAIR"),
        ("DEFECT", "REPAIR"),
        ("DEFECT", "QUALIFY_DEFECT"),
    }
    # Per-Case execution fan-out is Runtime-owned. A dynamic EXECUTION/REPAIR
    # is valid only when created from an EXECUTION-targeted governed Gap (for
    # example EXECUTION_CASE_PENDING). It must never fall through to DSH.
    _DYNAMIC_RUNTIME_TASKS = {
        ("EXECUTION", "REPAIR"),
    }

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
        owner = self._task_owner(task, compiler)
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

    def _task_owner(self, task: Task, compiler: MissionTaskGraphCompiler) -> str:
        canonical = compiler.compile(self.control.mission_id)
        canonical_by_id = {item.task_id: item for item in canonical.tasks}
        expected = canonical_by_id.get(task.task_id)
        if expected is not None:
            if task.node != expected.node:
                raise MissionStageDispatchError(
                    "CANONICAL_TASK_NODE_IDENTITY_MISMATCH:%s:%s:%s"
                    % (task.task_id, task.node, expected.node)
                )
            return compiler.task_owner(expected.node)

        key = (task.node, task.task_type)
        if key in self._DYNAMIC_RUNTIME_TASKS:
            self._require_governed_gap_refs(task)
            return compiler.OWNER_RUNTIME
        if key in self._DYNAMIC_PRODUCER_TASKS:
            self._require_governed_gap_refs(task)
            return compiler.OWNER_PRODUCER
        raise MissionStageDispatchError(
            "READY_NONCANONICAL_TASK_FORBIDDEN:%s:%s" % (task.node, task.task_type)
        )

    def _require_governed_gap_refs(self, task: Task) -> None:
        if not task.gap_refs:
            raise MissionStageDispatchError("DYNAMIC_TASK_GOVERNED_GAP_REQUIRED:%s" % task.task_id)
        for gap_id in task.gap_refs:
            rows = self.control.truth.query("rc7_gap", gap_id=gap_id)
            if len(rows) != 1:
                raise MissionStageDispatchError(
                    "DYNAMIC_TASK_GOVERNED_GAP_NOT_UNIQUE:%s:%s" % (task.task_id, gap_id)
                )
            if str(rows[0].get("mission_id") or "") != self.control.mission_id:
                raise MissionStageDispatchError(
                    "DYNAMIC_TASK_GOVERNED_GAP_MISSION_MISMATCH:%s:%s" % (task.task_id, gap_id)
                )
            if str(rows[0].get("target_node") or "") != task.node:
                raise MissionStageDispatchError(
                    "DYNAMIC_TASK_GOVERNED_GAP_TARGET_MISMATCH:%s:%s" % (task.task_id, gap_id)
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
