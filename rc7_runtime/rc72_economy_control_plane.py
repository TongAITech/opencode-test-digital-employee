"""RC7.2 default economy-aware ClosedLoopControlPlane compatibility overlay.

RC7.2 keeps the proven RC7 control plane and replaces only its READY/lease
ordering view with the canonical cost-window adapter. The underlying Task store,
state machine, Gap planner and Mission completion authority remain unchanged.
Critical-path protection is computed only from durable Task dependencies.
"""
from __future__ import annotations

import importlib
from typing import Type

from rc6_runtime.truth import TruthRuntime

from .closed_loop_control import ClosedLoopControlPlane as _BaseClosedLoopControlPlane
from .rc72_critical_path import CanonicalCriticalPathResolver
from .rc72_schedule_semantics import WorkScheduleSemanticsService
from .rc72_scheduler_integration import attach_economy_scheduler


class RC72EconomyClosedLoopControlPlane(_BaseClosedLoopControlPlane):
    """ClosedLoopControlPlane with RC7.2 economy ordering installed by default."""

    def __init__(self, truth: TruthRuntime, release_id: str, mission_id: str) -> None:
        super().__init__(truth, release_id, mission_id)
        self.schedule_semantics = WorkScheduleSemanticsService(
            truth, release_id=release_id
        )
        self.critical_path = CanonicalCriticalPathResolver(
            truth,
            release_id=release_id,
            schedule_semantics=self.schedule_semantics,
        )
        self.economy_scheduler = attach_economy_scheduler(
            self,
            descriptor_resolver=self.critical_path.resolve,
        )


def install_rc72_economy_control_plane_default() -> Type[_BaseClosedLoopControlPlane]:
    """Install the additive RC7.2 control-plane overlay exactly once.

    RC7 already uses package-level compatibility installers for field fixes.
    Keeping this as an explicit idempotent overlay avoids copying or forking the
    mature ClosedLoopControlPlane implementation while ensuring all later direct
    imports from ``rc7_runtime.closed_loop_control`` receive the economy-aware
    subclass.
    """
    module = importlib.import_module("rc7_runtime.closed_loop_control")
    current = getattr(module, "ClosedLoopControlPlane")
    if current is RC72EconomyClosedLoopControlPlane:
        return RC72EconomyClosedLoopControlPlane
    if current is not _BaseClosedLoopControlPlane:
        raise RuntimeError("RC72_ECONOMY_CONTROL_PLANE_OVERLAY_CONFLICT")
    module.ClosedLoopControlPlane = RC72EconomyClosedLoopControlPlane
    return RC72EconomyClosedLoopControlPlane
