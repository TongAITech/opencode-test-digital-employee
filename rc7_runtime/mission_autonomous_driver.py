"""Bounded fail-closed autonomous driver for one durable RC7 Mission.

The driver is a coordinator, never a testing authority.  It does not perform
Requirement/Code/Test work, synthesize Evaluations, or declare sufficiency.
Instead it reads canonical R1 state and invokes the already-governed authority
for exactly one next action:

* READY work -> MissionStageDispatcher (Runtime handler or DSH producer)
* OUTPUT_PRODUCED -> independent evaluator supplied for that node/task type
* active leased/running work -> optional session/recovery authority
* no active work -> independent Mission convergence authority
* CONVERGED -> optional post-convergence report authority

Every non-report action must change durable Mission/Task/Gap control truth.  A
handler that merely returns a success-looking value without R1 progress fails
closed.  No second driver state store exists; process recreation simply reads
R1 again and continues the same Mission.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple

from .closed_loop_control import ClosedLoopControlPlane
from .mission_conformance import MissionConformanceChecker
from .mission_stage_dispatch import MissionStageDispatcher
from .models import GapStatus, MissionStatus, Task, TaskStatus


class MissionAutonomousDriverError(RuntimeError):
    pass


@dataclass(frozen=True)
class MissionDriveBoundary:
    status: str
    mission_id: str
    step_count: int = 0
    task_id: Optional[str] = None
    node: Optional[str] = None
    action: Optional[str] = None
    reason: Optional[str] = None

    def as_dict(self) -> Dict[str, object]:
        return {
            "status": self.status,
            "mission_id": self.mission_id,
            "step_count": self.step_count,
            "task_id": self.task_id,
            "node": self.node,
            "action": self.action,
            "reason": self.reason,
        }


class MissionAutonomousDriver:
    """Drive one Mission until a durable boundary is reached.

    Evaluator lookup is exact-task-type first (``NODE:TASK_TYPE``), then node,
    then task type.  This lets defect/recovery work use a specialized authority
    without weakening canonical-node evaluator ownership.
    """

    _HUMAN_TASK_STATES = {TaskStatus.HUMAN_REQUIRED}
    _BLOCKED_TASK_STATES = {TaskStatus.BLOCKED, TaskStatus.FAILED, TaskStatus.STALE}
    _ACTIVE_TASK_STATES = {TaskStatus.LEASED, TaskStatus.RUNNING, TaskStatus.EVALUATING}
    _NONTERMINAL_TASK_STATES = {
        TaskStatus.REGISTERED,
        TaskStatus.READY,
        TaskStatus.LEASED,
        TaskStatus.RUNNING,
        TaskStatus.OUTPUT_PRODUCED,
        TaskStatus.EVALUATING,
        TaskStatus.REPAIR_REQUIRED,
        TaskStatus.BLOCKED,
        TaskStatus.HUMAN_REQUIRED,
        TaskStatus.FAILED,
        TaskStatus.STALE,
    }

    def __init__(
        self,
        control: ClosedLoopControlPlane,
        dispatcher: MissionStageDispatcher,
        *,
        output_evaluators: Optional[Mapping[str, Callable[[Task], Any]]] = None,
        active_task_handler: Optional[Callable[[Task], Any]] = None,
        convergence_handler: Optional[Callable[[], Any]] = None,
        final_report_handler: Optional[Callable[[], Any]] = None,
    ) -> None:
        if dispatcher.control is not control:
            raise MissionAutonomousDriverError("DRIVER_DISPATCHER_CONTROL_MISMATCH")
        self.control = control
        self.dispatcher = dispatcher
        self.output_evaluators = dict(output_evaluators or {})
        self.active_task_handler = active_task_handler
        self.convergence_handler = convergence_handler
        self.final_report_handler = final_report_handler

    def drive(self, *, max_steps: int = 100) -> MissionDriveBoundary:
        if not isinstance(max_steps, int) or max_steps < 1:
            raise MissionAutonomousDriverError("DRIVE_MAX_STEPS_MUST_BE_POSITIVE")
        progressed = 0
        while progressed < max_steps:
            boundary = self.step()
            if boundary.status != "PROGRESSED":
                return replace(boundary, step_count=progressed)
            progressed += 1
        return MissionDriveBoundary(
            status="BUDGET_EXHAUSTED",
            mission_id=self.control.mission_id,
            step_count=progressed,
            action="RESUME_FROM_R1",
            reason="DRIVE_STEP_BUDGET_EXHAUSTED",
        )

    def step(self) -> MissionDriveBoundary:
        conformance = MissionConformanceChecker(self.control.truth).check(self.control.mission_id)
        if conformance.status != "PASS":
            raise MissionAutonomousDriverError(
                "MISSION_CONFORMANCE_REQUIRED_BEFORE_AUTONOMY:%s"
                % ",".join(conformance.violations)
            )

        mission = self._mission_row()
        mission_state = MissionStatus(str(mission["state"]))
        if mission_state in {MissionStatus.CONVERGED, MissionStatus.CLOSED}:
            action = "MISSION_ALREADY_%s" % mission_state.value
            if mission_state == MissionStatus.CONVERGED and self.final_report_handler is not None:
                self.final_report_handler()
                action = "POST_CONVERGENCE_REPORT"
            return MissionDriveBoundary(
                status=mission_state.value,
                mission_id=self.control.mission_id,
                action=action,
            )

        # Registered tasks become READY only through the deterministic scheduler.
        self.control.refresh_ready()
        tasks = self._tasks()

        produced = [task for task in tasks if task.state == TaskStatus.OUTPUT_PRODUCED]
        if produced:
            task = produced[0]
            evaluator = self._output_evaluator(task)
            if evaluator is None:
                raise MissionAutonomousDriverError(
                    "OUTPUT_EVALUATOR_REQUIRED:%s:%s:%s"
                    % (task.task_id, task.node, task.task_type)
                )
            self._invoke_progressing(
                lambda: evaluator(task),
                reason="OUTPUT_EVALUATOR_NO_DURABLE_PROGRESS:%s" % task.task_id,
            )
            return self._progressed(task, "INDEPENDENT_EVALUATION")

        ready = [task for task in tasks if task.state == TaskStatus.READY]
        if ready:
            expected = ready[0]
            route = self.dispatcher.next_route()
            if route is None:
                raise MissionAutonomousDriverError("READY_TASK_ROUTE_MISSING:%s" % expected.task_id)
            if route.task_id != expected.task_id:
                raise MissionAutonomousDriverError(
                    "READY_TASK_ROUTE_ORDER_MISMATCH:%s:%s" % (expected.task_id, route.task_id)
                )
            self._invoke_progressing(
                self.dispatcher.dispatch_next,
                reason="DISPATCH_NO_DURABLE_PROGRESS:%s" % expected.task_id,
            )
            return self._progressed(expected, route.action)

        # Runnable work always has priority over stop boundaries.  Once no work
        # is runnable, Human/Blocked truth becomes an explicit durable boundary.
        human_tasks = [task for task in tasks if task.state in self._HUMAN_TASK_STATES]
        human_gaps = self._gaps_in({GapStatus.HUMAN_REQUIRED})
        if human_tasks or human_gaps or mission_state == MissionStatus.WAITING_HUMAN:
            task = human_tasks[0] if human_tasks else None
            return MissionDriveBoundary(
                status="HUMAN_REQUIRED",
                mission_id=self.control.mission_id,
                task_id=task.task_id if task else None,
                node=task.node if task else None,
                action="WAIT_FOR_HUMAN_GATE",
                reason="DURABLE_HUMAN_BOUNDARY",
            )

        blocked_tasks = [task for task in tasks if task.state in self._BLOCKED_TASK_STATES]
        blocked_gaps = self._gaps_in({GapStatus.BLOCKED})
        if blocked_tasks or blocked_gaps or mission_state == MissionStatus.BLOCKED:
            task = blocked_tasks[0] if blocked_tasks else None
            return MissionDriveBoundary(
                status="BLOCKED",
                mission_id=self.control.mission_id,
                task_id=task.task_id if task else None,
                node=task.node if task else None,
                action="REPAIR_OR_FIELD_BINDING_REQUIRED",
                reason="DURABLE_BLOCKED_BOUNDARY",
            )

        active = [task for task in tasks if task.state in self._ACTIVE_TASK_STATES]
        if active:
            task = active[0]
            if self.active_task_handler is None:
                return MissionDriveBoundary(
                    status="ACTIVE_TASK_PENDING",
                    mission_id=self.control.mission_id,
                    task_id=task.task_id,
                    node=task.node,
                    action="SESSION_RECOVERY_OR_WORKER_COMPLETION_REQUIRED",
                    reason="ACTIVE_TASK_HAS_NO_TAKEOVER_AUTHORITY",
                )
            self._invoke_progressing(
                lambda: self.active_task_handler(task),
                reason="ACTIVE_TASK_HANDLER_NO_DURABLE_PROGRESS:%s" % task.task_id,
            )
            return self._progressed(task, "ACTIVE_TASK_RECOVERY")

        repair_required = [task for task in tasks if task.state == TaskStatus.REPAIR_REQUIRED]
        if repair_required:
            task = repair_required[0]
            return MissionDriveBoundary(
                status="BLOCKED",
                mission_id=self.control.mission_id,
                task_id=task.task_id,
                node=task.node,
                action="REPAIR_TASK_REQUIRED",
                reason="SOURCE_REPAIR_REQUIRED_WITHOUT_RUNNABLE_REPAIR",
            )

        registered = [task for task in tasks if task.state == TaskStatus.REGISTERED]
        if registered:
            task = registered[0]
            return MissionDriveBoundary(
                status="BLOCKED",
                mission_id=self.control.mission_id,
                task_id=task.task_id,
                node=task.node,
                action="DEPENDENCY_OR_INPUT_RECONCILIATION_REQUIRED",
                reason="REGISTERED_TASK_NOT_READY",
            )

        nonterminal = [task for task in tasks if task.state in self._NONTERMINAL_TASK_STATES]
        if nonterminal:
            task = nonterminal[0]
            raise MissionAutonomousDriverError(
                "UNHANDLED_NONTERMINAL_TASK_STATE:%s:%s" % (task.task_id, task.state.value)
            )

        if self.convergence_handler is None:
            return MissionDriveBoundary(
                status="CONVERGENCE_REQUIRED",
                mission_id=self.control.mission_id,
                action="INDEPENDENT_MISSION_EVALUATION_REQUIRED",
                reason="NO_ACTIVE_WORK_REMAINS",
            )
        self._invoke_progressing(
            self.convergence_handler,
            reason="CONVERGENCE_HANDLER_NO_DURABLE_PROGRESS",
        )
        return MissionDriveBoundary(
            status="PROGRESSED",
            mission_id=self.control.mission_id,
            action="INDEPENDENT_MISSION_CONVERGENCE",
        )

    def _output_evaluator(self, task: Task) -> Optional[Callable[[Task], Any]]:
        for key in (
            "%s:%s" % (task.node, task.task_type),
            task.node,
            task.task_type,
        ):
            evaluator = self.output_evaluators.get(key)
            if evaluator is not None:
                return evaluator
        return None

    def _mission_row(self) -> Mapping[str, object]:
        rows = self.control.truth.query("rc7_mission", mission_id=self.control.mission_id)
        if len(rows) != 1:
            raise MissionAutonomousDriverError("DRIVER_REQUIRES_EXACTLY_ONE_MISSION")
        return rows[0]

    def _tasks(self) -> Sequence[Task]:
        rows = self.control.truth.query("rc7_task", mission_id=self.control.mission_id)
        tasks = [self.control.scheduler.task(str(row["task_id"])) for row in rows]
        return tuple(sorted(tasks, key=lambda item: (item.priority, item.created_at, item.task_id)))

    def _gaps_in(self, states: set[GapStatus]) -> Tuple[Mapping[str, object], ...]:
        allowed = {state.value for state in states}
        rows = [
            row for row in self.control.truth.query("rc7_gap", mission_id=self.control.mission_id)
            if str(row.get("state") or "") in allowed
        ]
        return tuple(sorted(rows, key=lambda row: str(row.get("gap_id") or "")))

    def _fingerprint(self) -> str:
        payload = {
            "mission": self.control.truth.query("rc7_mission", mission_id=self.control.mission_id),
            "tasks": self.control.truth.query("rc7_task", mission_id=self.control.mission_id),
            "gaps": self.control.truth.query("rc7_gap", mission_id=self.control.mission_id),
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _invoke_progressing(self, callback: Callable[[], Any], *, reason: str) -> Any:
        before = self._fingerprint()
        result = callback()
        after = self._fingerprint()
        if before == after:
            raise MissionAutonomousDriverError(reason)
        return result

    def _progressed(self, task: Task, action: str) -> MissionDriveBoundary:
        return MissionDriveBoundary(
            status="PROGRESSED",
            mission_id=self.control.mission_id,
            task_id=task.task_id,
            node=task.node,
            action=action,
        )
