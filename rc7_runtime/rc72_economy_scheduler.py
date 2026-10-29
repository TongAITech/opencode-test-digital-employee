"""RC7.2 mission-first scheduling policy for model-cost windows.

The selector consumes execution-only SemanticWorkDescriptors. It never changes
canonical Task/TestObligation scope. Its only job is to decide which READY work
should run now versus remain READY for a cheaper window.

Key safety rule: economy deferral must never idle a Mission when the only
runnable work is mandatory semantic work. In that case at least one semantic
item is promoted to RUN_NOW so the Mission continues to make progress.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from .rc72_context_economy import ExecutionMode, SemanticWorkDescriptor
from .rc72_model_economy import (
    BankCostWindow,
    MissionCriticality,
    SemanticCostClass,
    classify_bank_cost_window,
)


class EconomySchedulingError(ValueError):
    pass


@dataclass(frozen=True)
class EconomyReadyPlan:
    mission_id: str
    cost_window: BankCostWindow
    run_now_workitem_ids: Tuple[str, ...]
    deferred_workitem_ids: Tuple[str, ...]
    reasons: Mapping[str, str]

    @property
    def makes_progress(self) -> bool:
        return bool(self.run_now_workitem_ids)


class EconomyAwareReadySelector:
    """Prefer useful cheaper work without turning quota policy into a kill-switch."""

    def plan(
        self,
        items: Sequence[SemanticWorkDescriptor],
        *,
        when: Optional[datetime] = None,
    ) -> EconomyReadyPlan:
        if not items:
            raise EconomySchedulingError("READY_ITEMS_REQUIRED")
        mission_ids = {item.mission_id for item in items}
        if len(mission_ids) != 1:
            raise EconomySchedulingError("CROSS_MISSION_READY_SELECTION_FORBIDDEN")
        workitem_ids = [item.workitem_id for item in items]
        if len(workitem_ids) != len(set(workitem_ids)):
            raise EconomySchedulingError("DUPLICATE_READY_WORKITEM")

        window = classify_bank_cost_window(when)
        run_now: List[str] = []
        deferred: List[str] = []
        reasons: Dict[str, str] = {}

        # Cheap/unlimited windows do not defer work for economy reasons.
        cheap_or_unlimited = (
            not window.quota_limited or window.quota_cost_factor_millis < 1000
        )

        for item in items:
            if item.execution_mode == ExecutionMode.DETERMINISTIC:
                run_now.append(item.workitem_id)
                reasons[item.workitem_id] = "DETERMINISTIC_PROGRESS_NOW"
                continue
            if item.mission_criticality == MissionCriticality.BLOCKING:
                run_now.append(item.workitem_id)
                reasons[item.workitem_id] = "MISSION_CRITICAL_PATH_NOW"
                continue
            if cheap_or_unlimited:
                run_now.append(item.workitem_id)
                reasons[item.workitem_id] = "CHEAP_OR_UNLIMITED_WINDOW_NOW"
                continue
            if (
                item.mission_criticality == MissionCriticality.NON_BLOCKING
                and item.semantic_cost_class == SemanticCostClass.HIGH
            ):
                deferred.append(item.workitem_id)
                reasons[item.workitem_id] = "DAYTIME_HIGH_COST_NON_BLOCKING_DEFER_RECOMMENDED"
                continue
            run_now.append(item.workitem_id)
            reasons[item.workitem_id] = "NORMAL_READY_PROGRESS_NOW"

        # Economy may reorder work, but it may not stall the Mission. If every
        # READY item was a daytime high-cost/non-blocking semantic unit, promote
        # one item. Remaining siblings can still wait; the promoted item may
        # unlock deterministic/critical-path work on the next scheduling turn.
        if not run_now and deferred:
            promoted = deferred.pop(0)
            run_now.append(promoted)
            reasons[promoted] = "MISSION_PROGRESS_OVERRIDE_DEFER"

        return EconomyReadyPlan(
            mission_id=next(iter(mission_ids)),
            cost_window=window,
            run_now_workitem_ids=tuple(run_now),
            deferred_workitem_ids=tuple(deferred),
            reasons=reasons,
        )
