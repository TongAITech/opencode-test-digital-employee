"""Fan-out-safe formal Mission progression.

The baseline progressor historically materialized one WorkItem per Stage. RC8
case-scoped N5/N6/N7 work needs several WorkItems to share one Stage without the
first completed case falsely completing the whole Stage.

This adapter changes only Stage completion aggregation. Each WorkItem still
requires its own projected COMPLETED Attempt and AVAILABLE evidence. Downstream
work is unlocked only after every durable WorkItem linked to the Stage is
COMPLETED and all of their evidence has been revalidated.
"""
from __future__ import annotations

from typing import List, Tuple

from rc8_runtime.governance import StageState
from rc8_runtime.mission_graph import SUFFICIENCY_STAGES

from .autonomous_progression import AutonomousProgressionError, ProgressionOutcome
from .control_plane import WorkItemRecord, WorkItemState
from .requirement_loop_progression import RequirementLoopProgressor


class FanoutSafeRequirementLoopProgressor(RequirementLoopProgressor):
    """Prevent one completed fan-out WorkItem from completing its whole Stage."""

    def reconcile_completed_work_item(self, work_item_id: str) -> ProgressionOutcome:
        work = self.control_repository.get_work_item(work_item_id)
        if work is None:
            raise AutonomousProgressionError("WORK_ITEM_NOT_FOUND")
        if work.state != WorkItemState.COMPLETED:
            raise AutonomousProgressionError("WORK_ITEM_NOT_COMPLETED")

        stage = self._linked_stage(work_item_id)
        if stage is None:
            return super().reconcile_completed_work_item(work_item_id)

        links = self.control_repository.list_work_item_links_for_stage(stage.stage_instance_id)
        if len(links) <= 1 or stage.state == StageState.COMPLETED:
            return super().reconcile_completed_work_item(work_item_id)

        if stage.stage_type in {value.value for value in SUFFICIENCY_STAGES}:
            raise AutonomousProgressionError(
                "SUFFICIENCY_STAGE_FANOUT_REQUIRES_DETERMINISTIC_AGGREGATOR"
            )

        linked_work = self._linked_work_for_stage(stage.test_run_id, links)
        # The just-completed WorkItem must independently satisfy the existing
        # Attempt/evidence gate even while sibling work is still running.
        self.assert_work_item_completable(work_item_id)

        incomplete = tuple(
            item.identity.work_item_id
            for item in linked_work
            if item.state != WorkItemState.COMPLETED
        )
        if incomplete:
            latest = self.governance_repository.get_stage(stage.stage_instance_id) or stage
            return ProgressionOutcome(
                test_run_id=stage.test_run_id,
                source_work_item_id=work_item_id,
                source_stage_instance_id=stage.stage_instance_id,
                source_stage_state=latest.state.value,
                truth_note=(
                    "STAGE_COMPLETION_DEFERRED_UNTIL_ALL_LINKED_WORK_ITEMS_COMPLETE:"
                    + ",".join(sorted(incomplete))
                ),
            )

        evidence_refs = self._aggregate_completed_work_evidence(linked_work, stage)
        latest = self.governance_repository.get_stage(stage.stage_instance_id) or stage
        if latest.state == StageState.EXECUTING:
            latest = self.mission_service.mark_evidence_pending(
                latest.test_run_id,
                latest.stage_instance_id,
            )
        if latest.state == StageState.EVIDENCE_PENDING:
            latest = self.mission_service.complete_activity(
                latest.test_run_id,
                latest.stage_instance_id,
                evidence_refs,
            )
        elif latest.state != StageState.COMPLETED:
            raise AutonomousProgressionError(
                "MISSION_STAGE_FANOUT_COMPLETION_STATE_INVALID:%s:%s"
                % (latest.stage_instance_id, latest.state.value)
            )

        newly_ready, materialized = self.materialize_ready_work(stage.test_run_id)
        latest = self.governance_repository.get_stage(stage.stage_instance_id) or latest
        return ProgressionOutcome(
            test_run_id=stage.test_run_id,
            source_work_item_id=work_item_id,
            source_stage_instance_id=stage.stage_instance_id,
            source_stage_state=latest.state.value,
            newly_ready_stage_ids=newly_ready,
            materialized_work_item_ids=materialized,
            truth_note="ALL_LINKED_WORK_ITEMS_COMPLETED_WITH_AVAILABLE_EVIDENCE",
        )

    def _linked_work_for_stage(self, test_run_id: str, links) -> Tuple[WorkItemRecord, ...]:
        values: List[WorkItemRecord] = []
        for link in links:
            if str(link.test_run_id) != str(test_run_id):
                raise AutonomousProgressionError("STAGE_WORK_ITEM_TEST_RUN_MISMATCH")
            work = self.control_repository.get_work_item(str(link.work_item_id))
            if work is None:
                raise AutonomousProgressionError(
                    "STAGE_LINKED_WORK_ITEM_NOT_FOUND:%s" % link.work_item_id
                )
            if work.identity.test_run_id != test_run_id:
                raise AutonomousProgressionError("STAGE_WORK_ITEM_TEST_RUN_MISMATCH")
            values.append(work)
        return tuple(values)

    def _aggregate_completed_work_evidence(self, works, stage) -> Tuple[str, ...]:
        refs: List[str] = []
        for work in works:
            work_id = work.identity.work_item_id
            if work.state != WorkItemState.COMPLETED:
                raise AutonomousProgressionError(
                    "STAGE_LINKED_WORK_ITEM_NOT_COMPLETED:%s" % work_id
                )
            current = self._completed_attempt_evidence(work_id, stage)
            self._require_available_evidence(
                work_id,
                stage,
                current,
                "MISSION_COMPLETION",
            )
            refs.extend(current)
        normalized = tuple(dict.fromkeys(refs))
        if not normalized:
            raise AutonomousProgressionError(
                "MISSION_STAGE_COMPLETION_REQUIRES_AGGREGATED_EVIDENCE"
            )
        return normalized
