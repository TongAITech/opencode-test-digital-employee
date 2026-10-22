"""Evidence-gated autonomous Mission progression for RC8 formal Center.

This service bridges durable WorkItem completion back into the Mission Graph.
It never infers Stage PASS from a green WorkItem alone. A linked mission work
item can advance its Stage only after a projected COMPLETED Attempt exists and
all of that Attempt's evidence artifacts are AVAILABLE. Sufficiency stages also
require an R1-projected SufficiencyEvaluation before they can complete.

After a Stage is completed, dependency-ready downstream Stages are marked READY
and receive deterministic WorkItems. The operation is idempotent: deterministic
WorkItem identity plus Stage<->WorkItem lineage lets recovery reconcile a crash
between Stage completion and downstream work materialization.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from rc8_runtime import ArtifactAvailability, AttemptStatus, WorkItemIdentity
from rc8_runtime.governance import StageInstance, StageState
from rc8_runtime.mission_graph import MissionStageType, SUFFICIENCY_STAGES

from .control_plane import WorkItemRecord, WorkItemState
from .mission_service import CenterMissionService
from .repository_ports import ArtifactMetadataRepository, GovernanceRepository
from .infrastructure.postgres import PostgresStore
from .infrastructure.postgres_control import PostgresCenterRepository


class AutonomousProgressionError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProgressionOutcome:
    test_run_id: str
    source_work_item_id: str
    source_stage_instance_id: Optional[str]
    source_stage_state: Optional[str]
    newly_ready_stage_ids: Tuple[str, ...] = tuple()
    materialized_work_item_ids: Tuple[str, ...] = tuple()
    truth_note: str = "EVIDENCE_GATED_STAGE_PROGRESSION"


# Only capabilities already defined as product invariants are attached here.
# Unknown stages remain capability-neutral until their specialized worker slice
# is productized; inventing capability names would make scheduling look real
# while being impossible to satisfy. Java code analysis is the explicit RC8
# exception: it must not bypass CodeGraph.
_STAGE_REQUIRED_CAPABILITIES = {
    MissionStageType.CODE_ANALYSIS.value: ("codegraph",),
}


def _stable_work_item_id(stage: StageInstance) -> str:
    raw = "\x1f".join((
        "work",
        stage.test_run_id,
        stage.stage_instance_id,
        stage.stage_type,
        "attempt:1",
    ))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    readable = stage.stage_type.lower().replace("_", "-")
    return "work-%s-%s" % (readable[:48], digest)


def _artifact_id(ref: str) -> str:
    value = str(ref or "").strip()
    if not value:
        raise AutonomousProgressionError("MISSION_EVIDENCE_REF_REQUIRED")
    return value.split(":", 1)[1] if value.startswith("artifact:") else value


class AutonomousMissionProgressor:
    def __init__(
        self,
        *,
        store: PostgresStore,
        mission_service: CenterMissionService,
        governance_repository: GovernanceRepository,
        control_repository: PostgresCenterRepository,
        artifact_repository: ArtifactMetadataRepository,
    ) -> None:
        self.store = store
        self.mission_service = mission_service
        self.governance_repository = governance_repository
        self.control_repository = control_repository
        self.artifact_repository = artifact_repository

    def on_work_item_leased(self, work_item_id: str) -> Optional[StageInstance]:
        stage = self._linked_stage(work_item_id)
        if stage is None:
            return None
        if stage.state == StageState.READY:
            return self.mission_service.mark_leased(stage.test_run_id, stage.stage_instance_id)
        if stage.state in {
            StageState.LEASED,
            StageState.EXECUTING,
            StageState.EVIDENCE_PENDING,
            StageState.EVALUATING,
            StageState.SUFFICIENT,
            StageState.INSUFFICIENT,
            StageState.COMPLETED,
        }:
            return stage
        raise AutonomousProgressionError(
            "MISSION_STAGE_NOT_LEASEABLE:%s:%s" % (stage.stage_instance_id, stage.state.value)
        )

    def on_work_item_started(self, work_item_id: str) -> Optional[StageInstance]:
        stage = self._linked_stage(work_item_id)
        if stage is None:
            return None
        if stage.state == StageState.READY:
            stage = self.mission_service.mark_leased(stage.test_run_id, stage.stage_instance_id)
        if stage.state == StageState.LEASED:
            return self.mission_service.mark_executing(stage.test_run_id, stage.stage_instance_id)
        if stage.state in {
            StageState.EXECUTING,
            StageState.EVIDENCE_PENDING,
            StageState.EVALUATING,
            StageState.SUFFICIENT,
            StageState.INSUFFICIENT,
            StageState.COMPLETED,
        }:
            return stage
        raise AutonomousProgressionError(
            "MISSION_STAGE_NOT_STARTABLE:%s:%s" % (stage.stage_instance_id, stage.state.value)
        )

    def assert_work_item_completable(self, work_item_id: str) -> Tuple[str, ...]:
        """Fail closed before the durable WorkItem is marked terminal."""
        stage = self._linked_stage(work_item_id)
        if stage is None:
            # Legacy/non-production work remains compatible with the explicit
            # control-plane API. Autonomous production work always has lineage.
            return tuple()
        if stage.state == StageState.COMPLETED:
            return tuple(stage.output_refs)
        if stage.state not in {
            StageState.EXECUTING,
            StageState.EVIDENCE_PENDING,
            StageState.EVALUATING,
            StageState.SUFFICIENT,
            StageState.INSUFFICIENT,
        }:
            raise AutonomousProgressionError(
                "MISSION_STAGE_COMPLETION_STATE_INVALID:%s:%s"
                % (stage.stage_instance_id, stage.state.value)
            )

        evidence_refs = self._completed_attempt_evidence(work_item_id, stage)
        for ref in evidence_refs:
            manifest = self.artifact_repository.get(_artifact_id(ref))
            if manifest is None:
                raise AutonomousProgressionError("MISSION_COMPLETION_EVIDENCE_NOT_FOUND:%s" % ref)
            if manifest.availability != ArtifactAvailability.AVAILABLE:
                raise AutonomousProgressionError("MISSION_COMPLETION_EVIDENCE_NOT_AVAILABLE:%s" % ref)
            if manifest.test_run_id != stage.test_run_id:
                raise AutonomousProgressionError("MISSION_COMPLETION_EVIDENCE_TEST_RUN_MISMATCH:%s" % ref)
            if manifest.work_item_id != work_item_id:
                raise AutonomousProgressionError("MISSION_COMPLETION_EVIDENCE_WORK_ITEM_MISMATCH:%s" % ref)

        if stage.stage_type in {value.value for value in SUFFICIENCY_STAGES}:
            evaluations = [
                item
                for item in self.governance_repository.list_evaluations(stage.test_run_id)
                if item.subject_id == stage.stage_instance_id
            ]
            if not evaluations:
                raise AutonomousProgressionError("SUFFICIENCY_EVALUATION_NOT_PROJECTED")
        return evidence_refs

    def reconcile_completed_work_item(self, work_item_id: str) -> ProgressionOutcome:
        work = self.control_repository.get_work_item(work_item_id)
        if work is None:
            raise AutonomousProgressionError("WORK_ITEM_NOT_FOUND")
        if work.state != WorkItemState.COMPLETED:
            raise AutonomousProgressionError("WORK_ITEM_NOT_COMPLETED")
        stage = self._linked_stage(work_item_id)
        if stage is None:
            return ProgressionOutcome(
                test_run_id=work.identity.test_run_id,
                source_work_item_id=work_item_id,
                source_stage_instance_id=None,
                source_stage_state=None,
                truth_note="LEGACY_UNLINKED_WORK_ITEM_NO_MISSION_PROGRESSION",
            )

        evidence_refs = self.assert_work_item_completable(work_item_id)
        stage = self.governance_repository.get_stage(stage.stage_instance_id) or stage
        if stage.state != StageState.COMPLETED:
            if stage.state == StageState.EXECUTING:
                stage = self.mission_service.mark_evidence_pending(
                    stage.test_run_id, stage.stage_instance_id
                )
            if stage.stage_type in {value.value for value in SUFFICIENCY_STAGES}:
                if stage.state == StageState.EVIDENCE_PENDING:
                    stage = self.mission_service.begin_sufficiency_evaluation(
                        stage.test_run_id,
                        stage.stage_instance_id,
                        evidence_refs,
                    )
                if stage.state == StageState.EVALUATING:
                    stage = self.mission_service.reconcile_sufficiency(
                        stage.test_run_id, stage.stage_instance_id
                    )
                if stage.state in {StageState.SUFFICIENT, StageState.INSUFFICIENT}:
                    stage = self.mission_service.complete_sufficiency(
                        stage.test_run_id, stage.stage_instance_id
                    )
            else:
                if stage.state == StageState.EVIDENCE_PENDING:
                    stage = self.mission_service.complete_activity(
                        stage.test_run_id,
                        stage.stage_instance_id,
                        evidence_refs,
                    )

        newly_ready, materialized = self.materialize_ready_work(stage.test_run_id)
        latest = self.governance_repository.get_stage(stage.stage_instance_id) or stage
        return ProgressionOutcome(
            test_run_id=stage.test_run_id,
            source_work_item_id=work_item_id,
            source_stage_instance_id=stage.stage_instance_id,
            source_stage_state=latest.state.value,
            newly_ready_stage_ids=newly_ready,
            materialized_work_item_ids=materialized,
        )

    def reconcile_test_run(self, test_run_id: str) -> Tuple[ProgressionOutcome, ...]:
        """Crash-safe reconciliation for completed work whose Stage lagged."""
        outcomes: List[ProgressionOutcome] = []
        for work in self.control_repository.list_work_items():
            if work.identity.test_run_id != test_run_id or work.state != WorkItemState.COMPLETED:
                continue
            stage = self._linked_stage(work.identity.work_item_id)
            if stage is None or stage.state == StageState.COMPLETED:
                continue
            outcomes.append(self.reconcile_completed_work_item(work.identity.work_item_id))
        self.materialize_ready_work(test_run_id)
        return tuple(outcomes)

    def materialize_ready_work(self, test_run_id: str) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
        newly_ready: List[str] = []
        for stage_id in self.mission_service.ready_stage_ids(test_run_id):
            stage = self.mission_service.mark_ready(test_run_id, stage_id)
            newly_ready.append(stage.stage_instance_id)

        materialized: List[str] = []
        for stage in self.governance_repository.list_stages(test_run_id):
            if stage.state != StageState.READY:
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

    def _work_for_stage(self, stage: StageInstance) -> WorkItemRecord:
        run = self.store.get_test_run(stage.test_run_id)
        if run is None:
            raise AutonomousProgressionError("TEST_RUN_NOT_FOUND")
        test_round_id = str(run.test_round_id or "").strip()
        if not test_round_id:
            raise AutonomousProgressionError("MISSION_STAGE_REQUIRES_TEST_ROUND")
        identity = WorkItemIdentity(
            work_item_id=_stable_work_item_id(stage),
            test_run_id=stage.test_run_id,
            stage=stage.stage_type,
            scope_refs=[
                stage.scope_version,
                "stage-instance:%s" % stage.stage_instance_id,
                "test-round:%s" % test_round_id,
            ],
            required_capabilities=list(_STAGE_REQUIRED_CAPABILITIES.get(stage.stage_type, tuple())),
        )
        return WorkItemRecord(identity=identity, state=WorkItemState.READY)

    def _linked_stage(self, work_item_id: str) -> Optional[StageInstance]:
        link = self.control_repository.get_stage_link_for_work_item(work_item_id)
        if link is None:
            return None
        stage = self.governance_repository.get_stage(str(link.stage_instance_id))
        if stage is None:
            raise AutonomousProgressionError("MISSION_STAGE_NOT_FOUND")
        if stage.test_run_id != str(link.test_run_id):
            raise AutonomousProgressionError("STAGE_WORK_ITEM_TEST_RUN_MISMATCH")
        return stage

    def _completed_attempt_evidence(
        self,
        work_item_id: str,
        stage: StageInstance,
    ) -> Tuple[str, ...]:
        attempts = [
            item
            for item in self.governance_repository.list_attempts(stage.test_run_id)
            if item.work_item_id == work_item_id
            and item.stage_instance_id == stage.stage_instance_id
            and item.status == AttemptStatus.COMPLETED
        ]
        if not attempts:
            raise AutonomousProgressionError(
                "MISSION_WORK_ITEM_COMPLETION_REQUIRES_PROJECTED_COMPLETED_ATTEMPT"
            )
        refs: List[str] = []
        for attempt in attempts:
            refs.extend(attempt.evidence_refs)
        normalized = tuple(dict.fromkeys(str(ref).strip() for ref in refs if str(ref).strip()))
        if not normalized:
            raise AutonomousProgressionError("MISSION_WORK_ITEM_COMPLETION_REQUIRES_EVIDENCE")
        return normalized
