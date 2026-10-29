"""RC7.2 economy-aware TaskScheduler integration.

Driver, Dispatcher and DSH bridge already share ``control.scheduler`` as the
canonical READY/lease ordering boundary. This adapter wraps the existing
TaskScheduler so every consumer observes the same mission-first economy order.
It does not create a second Task state store and does not modify persisted Task
priority/dependency truth.

Only execution order changes:
- deterministic and mission-critical work can move ahead of daytime high-cost,
  non-blocking semantic work;
- when only deferred semantic work remains, the selector promotes at least one
  item so the Mission cannot stall merely to save quota;
- lease order uses the exact same ordered READY view as Driver/Dispatcher.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Iterable, Optional, Sequence, Tuple

from .models import Task, TaskStatus
from .rc72_context_economy import SemanticWorkDescriptor
from .rc72_economy_scheduler import EconomyAwareReadySelector, EconomyReadyPlan
from .state_machine import transition_task


class EconomySchedulerIntegrationError(RuntimeError):
    pass


DescriptorResolver = Callable[[Task], SemanticWorkDescriptor]
Clock = Callable[[], datetime]


class EconomyAwareTaskSchedulerAdapter:
    """Single ordering view shared by driver, dispatcher, leasing and gap planner."""

    def __init__(
        self,
        delegate: Any,
        *,
        descriptor_resolver: DescriptorResolver,
        selector: Optional[EconomyAwareReadySelector] = None,
        clock: Optional[Clock] = None,
    ) -> None:
        if descriptor_resolver is None:
            raise EconomySchedulerIntegrationError("DESCRIPTOR_RESOLVER_REQUIRED")
        self.delegate = delegate
        self.descriptor_resolver = descriptor_resolver
        self.selector = selector or EconomyAwareReadySelector()
        self.clock = clock
        self.last_plan: Optional[EconomyReadyPlan] = None

    def __getattr__(self, name: str) -> Any:
        return getattr(self.delegate, name)

    def _plan(self, mission_id: str, tasks: Sequence[Task]) -> Optional[EconomyReadyPlan]:
        if not tasks:
            self.last_plan = None
            return None
        descriptors = []
        for task in tasks:
            descriptor = self.descriptor_resolver(task)
            if not isinstance(descriptor, SemanticWorkDescriptor):
                raise EconomySchedulerIntegrationError(
                    "SEMANTIC_WORK_DESCRIPTOR_REQUIRED:%s" % task.task_id
                )
            if descriptor.workitem_id != task.task_id:
                raise EconomySchedulerIntegrationError(
                    "DESCRIPTOR_WORKITEM_MISMATCH:%s:%s"
                    % (task.task_id, descriptor.workitem_id)
                )
            if descriptor.mission_id != mission_id:
                raise EconomySchedulerIntegrationError(
                    "DESCRIPTOR_MISSION_MISMATCH:%s:%s"
                    % (task.task_id, descriptor.mission_id)
                )
            descriptors.append(descriptor)
        when = self.clock() if self.clock is not None else None
        self.last_plan = self.selector.plan(descriptors, when=when)
        return self.last_plan

    def ready_tasks(self, mission_id: str) -> Tuple[Task, ...]:
        canonical = tuple(self.delegate.ready_tasks(mission_id))
        plan = self._plan(mission_id, canonical)
        if plan is None:
            return ()
        by_id = {task.task_id: task for task in canonical}
        ordered_ids = (*plan.run_now_workitem_ids, *plan.deferred_workitem_ids)
        if set(ordered_ids) != set(by_id):
            raise EconomySchedulerIntegrationError("ECONOMY_READY_PLAN_TASK_SET_MISMATCH")
        return tuple(by_id[task_id] for task_id in ordered_ids)

    def lease_next(
        self,
        mission_id: str,
        *,
        worker_ref: str,
        capabilities: Iterable[str],
    ) -> Optional[Task]:
        """Lease exactly from the same ordered READY view seen by Driver/Dispatcher."""
        capability_set = set(capabilities)
        for task in self.ready_tasks(mission_id):
            if not set(task.required_capabilities).issubset(capability_set):
                continue
            row = self.delegate._row(task.task_id)
            if row is None or row["state"] != TaskStatus.READY.value:
                continue
            transition_task(task, TaskStatus.LEASED, lease_owner=worker_ref)
            self.delegate._persist_task(task, int(row["artifact_version"]) + 1)
            return task
        return None


def attach_economy_scheduler(
    control: Any,
    *,
    descriptor_resolver: DescriptorResolver,
    selector: Optional[EconomyAwareReadySelector] = None,
    clock: Optional[Clock] = None,
) -> EconomyAwareTaskSchedulerAdapter:
    """Attach one economy ordering boundary to an existing ClosedLoopControlPlane.

    The GapRepairPlanner shares the same adapter so dynamic repair registration
    and lookups do not drift onto a second scheduler object.
    """
    current = getattr(control, "scheduler", None)
    if current is None:
        raise EconomySchedulerIntegrationError("CONTROL_SCHEDULER_REQUIRED")
    if isinstance(current, EconomyAwareTaskSchedulerAdapter):
        raise EconomySchedulerIntegrationError("ECONOMY_SCHEDULER_ALREADY_ATTACHED")
    adapter = EconomyAwareTaskSchedulerAdapter(
        current,
        descriptor_resolver=descriptor_resolver,
        selector=selector,
        clock=clock,
    )
    control.scheduler = adapter
    gap_planner = getattr(control, "gap_planner", None)
    if gap_planner is not None:
        gap_planner.scheduler = adapter
    return adapter
