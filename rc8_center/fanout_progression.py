"""Fan-out-safe formal Mission progression.

N5/N6/N7 execution are materialized per frozen N4 case. The first completed
case cannot complete the whole Stage; downstream progression waits for every
durable linked case WorkItem to have a projected COMPLETED Attempt and AVAILABLE
evidence.
"""
from __future__ import annotations

import hashlib
from typing import List, Optional, Tuple

from rc8_runtime import WorkItemIdentity
from rc8_runtime.governance import StageState
from rc8_runtime.mission_graph import MissionStageType, SUFFICIENCY_STAGES

from .autonomous_progression import AutonomousProgressionError, ProgressionOutcome
from .case_inventory import CenterFrozenCaseInventoryResolver, FrozenCaseIdentity, FrozenCaseInventory
from .control_plane import WorkItemRecord, WorkItemState
from .requirement_loop_progression import RequirementLoopProgressor


_CASE_FANOUT_STAGE_TYPES = {
    MissionStageType.PRECONDITION_DATA_PREP.value,
    MissionStageType.EXECUTABLE_SPEC.value,
    MissionStageType.APPLICABLE_LAYER_EXECUTION.value,
}


def _case_work_item_id(stage, case: FrozenCaseIdentity, inventory: FrozenCaseInventory) -> str:
    raw = "\x1f".join((
        "case-work",
        stage.test_run_id,
        stage.stage_instance_id,
        stage.stage_type,
        case.case_id,
        case.case_revision_ref,
        inventory.artifact_sha256,
    ))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    readable = stage.stage_type.lower().replace("_", "-")
    return "work-%s-case-%s" % (readable[:42], digest)


class FanoutSafeRequirementLoopProgressor(RequirementLoopProgressor):
    """Case-fanout materialization plus all-linked-work Stage completion gate."""

    def __init__(self, *args, case_inventory_resolver: Optional[CenterFrozenCaseInventoryResolver] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.case_inventory_resolver = case_inventory_resolver

    def materialize_ready_work(self, test_run_id: str) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
        if self.case_inventory_resolver is None:
            return super().materialize_ready_work(test_run_id)

        newly_ready: List[str] = []
        for stage_id in self.mission_service.ready_stage_ids(test_run_id):
            stage = self.mission_service.mark_ready(test_run_id, stage_id)
            newly_ready.append(stage.stage_instance_id)

        materialized: List[str] = []
        for stage in self.governance_repository.list_stages(test_run_id):
            if stage.state != StageState.READY:
                continue
            if stage.stage_type in _CASE_FANOUT_STAGE_TYPES:
                materialized.extend(self._materialize_case_work(stage))
                continue
            links = self.control_repository.list_work_item_links_for_stage(stage.stage_instance_id)
            if links:
                continue
            work = self._work_for_stage(stage)
            self.control_repository.upsert_work_item(work)
            self.control_repository.link_work_item_to_stage(
                work_item_id=work.identity.work_item_id,
                stage_instance_id=stage.stage_instance_id,
                test_run_id=stage.test_run_id,
            )
            materialized.append(work.identity.work_item_id)
        return tuple(sorted(newly_ready)), tuple(sorted(materialized))

    def _materialize_case_work(self, stage) -> Tuple[str, ...]:
        if self.case_inventory_resolver is None:
            raise AutonomousProgressionError("CASE_FANOUT_INVENTORY_RESOLVER_REQUIRED")
        inventory = self.case_inventory_resolver.resolve(
            test_run_id=stage.test_run_id,
            scope_version=stage.scope_version,
        )
        expected = {
            _case_work_item_id(stage, case, inventory): self._work_for_case(stage, case, inventory)
            for case in inventory.cases
        }
        links = self.control_repository.list_work_item_links_for_stage(stage.stage_instance_id)
        linked_ids = {str(link.work_item_id) for link in links}
        unexpected = sorted(linked_ids.difference(expected))
        if unexpected:
            raise AutonomousProgressionError(
                "CASE_FANOUT_EXISTING_WORK_NOT_IN_FROZEN_INVENTORY:%s" % ",".join(unexpected)
            )

        materialized: List[str] = []
        for work_id, work in expected.items():
            current = self.control_repository.get_work_item(work_id)
            if current is not None and current.identity != work.identity:
                raise AutonomousProgressionError("CASE_FANOUT_WORK_IDENTITY_CONFLICT:%s" % work_id)
            if current is None:
                self.control_repository.upsert_work_item(work)
                materialized.append(work_id)
            link = self.control_repository.get_stage_link_for_work_item(work_id)
            if link is None:
                self.control_repository.link_work_item_to_stage(
                    work_item_id=work_id,
                    stage_instance_id=stage.stage_instance_id,
                    test_run_id=stage.test_run_id,
                )
            elif link.stage_instance_id != stage.stage_instance_id or link.test_run_id != stage.test_run_id:
                raise AutonomousProgressionError("CASE_FANOUT_WORK_STAGE_LINK_CONFLICT:%s" % work_id)
        return tuple(sorted(materialized))

    def _work_for_case(self, stage, case: FrozenCaseIdentity, inventory: FrozenCaseInventory) -> WorkItemRecord:
        base = self._work_for_stage(stage)
        scope_refs = list(base.identity.scope_refs)
        scope_refs.extend((
            "case:%s" % case.case_id,
            case.case_revision_ref,
            inventory.artifact_ref,
            inventory.fingerprint_ref,
        ))
        identity = WorkItemIdentity(
            work_item_id=_case_work_item_id(stage, case, inventory),
            test_run_id=stage.test_run_id,
            stage=stage.stage_type,
            scope_refs=list(dict.fromkeys(scope_refs)),
            required_capabilities=base.identity.required_capabilities,
        )
        return WorkItemRecord(identity=identity, state=WorkItemState.READY)

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
            raise AutonomousProgressionError("SUFFICIENCY_STAGE_FANOUT_REQUIRES_DETERMINISTIC_AGGREGATOR")

        linked_work = self._linked_work_for_stage(stage.test_run_id, links)
        self.assert_work_item_completable(work_item_id)
        incomplete = tuple(item.identity.work_item_id for item in linked_work if item.state != WorkItemState.COMPLETED)
        if incomplete:
            latest = self.governance_repository.get_stage(stage.stage_instance_id) or stage
            return ProgressionOutcome(
                test_run_id=stage.test_run_id,
                source_work_item_id=work_item_id,
                source_stage_instance_id=stage.stage_instance_id,
                source_stage_state=latest.state.value,
                truth_note="STAGE_COMPLETION_DEFERRED_UNTIL_ALL_LINKED_WORK_ITEMS_COMPLETE:" + ",".join(sorted(incomplete)),
            )

        evidence_refs = self._aggregate_completed_work_evidence(linked_work, stage)
        latest = self.governance_repository.get_stage(stage.stage_instance_id) or stage
        if latest.state == StageState.EXECUTING:
            latest = self.mission_service.mark_evidence_pending(latest.test_run_id, latest.stage_instance_id)
        if latest.state == StageState.EVIDENCE_PENDING:
            latest = self.mission_service.complete_activity(latest.test_run_id, latest.stage_instance_id, evidence_refs)
        elif latest.state != StageState.COMPLETED:
            raise AutonomousProgressionError(
                "MISSION_STAGE_FANOUT_COMPLETION_STATE_INVALID:%s:%s" % (latest.stage_instance_id, latest.state.value)
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
                raise AutonomousProgressionError("STAGE_LINKED_WORK_ITEM_NOT_FOUND:%s" % link.work_item_id)
            if work.identity.test_run_id != test_run_id:
                raise AutonomousProgressionError("STAGE_WORK_ITEM_TEST_RUN_MISMATCH")
            values.append(work)
        return tuple(values)

    def _aggregate_completed_work_evidence(self, works, stage) -> Tuple[str, ...]:
        refs: List[str] = []
        for work in works:
            work_id = work.identity.work_item_id
            if work.state != WorkItemState.COMPLETED:
                raise AutonomousProgressionError("STAGE_LINKED_WORK_ITEM_NOT_COMPLETED:%s" % work_id)
            current = self._completed_attempt_evidence(work_id, stage)
            self._require_available_evidence(work_id, stage, current, "MISSION_COMPLETION")
            refs.extend(current)
        normalized = tuple(dict.fromkeys(refs))
        if not normalized:
            raise AutonomousProgressionError("MISSION_STAGE_COMPLETION_REQUIRES_AGGREGATED_EVIDENCE")
        return normalized
