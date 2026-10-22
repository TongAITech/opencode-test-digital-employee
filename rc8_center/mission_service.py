"""Center-owned Mission Graph control service.

Mission/Stage topology is durable control-domain state owned by Center. Runtime
facts (Attempt/Coverage/Gap/Sufficiency) arrive through R1 projection; this
service consumes those persisted facts to unlock, rework or invalidate stages.
Storage is behind the GovernanceRepository port.
"""
from __future__ import annotations

from dataclasses import replace
from typing import List, Optional, Sequence, Tuple

from rc8_runtime import RC8ContractError
from rc8_runtime.governance import StageInstance, StageState, StatusScope, SufficiencyResult
from rc8_runtime.mission_graph import MissionGraphRuntime, MissionStageType, SUFFICIENCY_STAGES

from .repository_ports import GovernanceRepository


class CenterMissionService:
    def __init__(self, repository: GovernanceRepository) -> None:
        self.repository = repository

    def _hydrate(self, test_run_id: str) -> MissionGraphRuntime:
        graph = MissionGraphRuntime(test_run_id)
        remaining = list(self.repository.list_stages(test_run_id))
        # Topological restore: persisted row ordering is not authoritative.
        while remaining:
            progress = False
            for stage in list(remaining):
                if all(pred in graph.runtime.stages for pred in stage.predecessor_ids):
                    graph.add_stage(stage)
                    remaining.remove(stage)
                    progress = True
            if not progress:
                unresolved = ",".join(sorted(stage.stage_instance_id for stage in remaining))
                raise RC8ContractError("MISSION_GRAPH_RESTORE_DEPENDENCY_CYCLE_OR_MISSING:%s" % unresolved)

        # Restore sufficiency proofs only for stages that have already consumed
        # them. EVALUATING stages consume newly projected evaluations explicitly
        # through reconcile_sufficiency().
        for evaluation in self.repository.list_evaluations(test_run_id):
            if evaluation.scope != StatusScope.STAGE:
                continue
            stage = graph.runtime.stages.get(evaluation.subject_id)
            if stage is None:
                continue
            if stage.state in {StageState.SUFFICIENT, StageState.INSUFFICIENT, StageState.COMPLETED}:
                graph.restore_evaluation(evaluation)
        return graph

    def register_stage(
        self,
        *,
        test_run_id: str,
        stage_instance_id: str,
        stage_type: MissionStageType,
        scope_version: str,
        attempt_no: int,
        predecessor_ids: Sequence[str] = (),
        input_refs: Sequence[str] = (),
        assigned_worker: Optional[str] = None,
        policy_version: Optional[str] = None,
    ) -> StageInstance:
        if self.repository.get_stage(stage_instance_id) is not None:
            raise RC8ContractError("STAGE_INSTANCE_ALREADY_EXISTS")
        graph = self._hydrate(test_run_id)
        stage = StageInstance(
            stage_instance_id=stage_instance_id,
            test_run_id=test_run_id,
            stage_type=stage_type.value,
            scope_version=scope_version,
            attempt_no=attempt_no,
            predecessor_ids=tuple(predecessor_ids),
            input_refs=tuple(input_refs),
            assigned_worker=assigned_worker,
            policy_version=policy_version,
        )
        graph.add_stage(stage)
        self.repository.upsert_stage(stage)
        return stage

    def mark_ready(self, test_run_id: str, stage_instance_id: str) -> StageInstance:
        graph = self._hydrate(test_run_id)
        updated = graph.mark_ready(stage_instance_id)
        self.repository.upsert_stage(updated)
        return updated

    def mark_leased(self, test_run_id: str, stage_instance_id: str) -> StageInstance:
        graph = self._hydrate(test_run_id)
        updated = graph.runtime.transition_stage(stage_instance_id, StageState.LEASED)
        self.repository.upsert_stage(updated)
        return updated

    def mark_executing(self, test_run_id: str, stage_instance_id: str) -> StageInstance:
        graph = self._hydrate(test_run_id)
        updated = graph.runtime.transition_stage(stage_instance_id, StageState.EXECUTING)
        self.repository.upsert_stage(updated)
        return updated

    def mark_evidence_pending(self, test_run_id: str, stage_instance_id: str) -> StageInstance:
        graph = self._hydrate(test_run_id)
        updated = graph.runtime.transition_stage(stage_instance_id, StageState.EVIDENCE_PENDING)
        self.repository.upsert_stage(updated)
        return updated

    def mark_failed_runtime(self, test_run_id: str, stage_instance_id: str) -> StageInstance:
        graph = self._hydrate(test_run_id)
        updated = graph.runtime.transition_stage(stage_instance_id, StageState.FAILED_RUNTIME)
        self.repository.upsert_stage(updated)
        return updated

    def mark_blocked(self, test_run_id: str, stage_instance_id: str) -> StageInstance:
        graph = self._hydrate(test_run_id)
        updated = graph.runtime.transition_stage(stage_instance_id, StageState.BLOCKED)
        self.repository.upsert_stage(updated)
        return updated

    def complete_activity(
        self,
        test_run_id: str,
        stage_instance_id: str,
        output_refs: Sequence[str],
    ) -> StageInstance:
        graph = self._hydrate(test_run_id)
        updated = graph.record_activity_completion(stage_instance_id, output_refs)
        self.repository.upsert_stage(updated)
        return updated

    def begin_sufficiency_evaluation(
        self,
        test_run_id: str,
        stage_instance_id: str,
        evidence_refs: Sequence[str],
    ) -> StageInstance:
        graph = self._hydrate(test_run_id)
        stage = graph.runtime.stages.get(stage_instance_id)
        if stage is None:
            raise RC8ContractError("STAGE_INSTANCE_NOT_FOUND")
        try:
            stage_type = MissionStageType(stage.stage_type)
        except ValueError as exc:
            raise RC8ContractError("MISSION_STAGE_TYPE_UNKNOWN:%s" % stage.stage_type) from exc
        if stage_type not in SUFFICIENCY_STAGES:
            raise RC8ContractError("MISSION_STAGE_IS_NOT_SUFFICIENCY_STAGE")
        if stage.state != StageState.EVIDENCE_PENDING:
            raise RC8ContractError("SUFFICIENCY_EVALUATION_REQUIRES_EVIDENCE_PENDING")
        refs = tuple(str(ref).strip() for ref in evidence_refs if isinstance(ref, str) and ref.strip())
        if not refs:
            raise RC8ContractError("SUFFICIENCY_EVALUATION_REQUIRES_EVIDENCE")
        stage = replace(stage, output_refs=tuple(dict.fromkeys(stage.output_refs + refs)))
        graph.runtime.stages[stage_instance_id] = stage
        updated = graph.runtime.transition_stage(stage_instance_id, StageState.EVALUATING)
        self.repository.upsert_stage(updated)
        return updated

    def reconcile_sufficiency(self, test_run_id: str, stage_instance_id: str) -> StageInstance:
        """Consume the latest R1-projected STAGE sufficiency result."""
        graph = self._hydrate(test_run_id)
        stage = graph.runtime.stages.get(stage_instance_id)
        if stage is None:
            raise RC8ContractError("STAGE_INSTANCE_NOT_FOUND")
        if stage.state != StageState.EVALUATING:
            raise RC8ContractError("MISSION_STAGE_MUST_BE_EVALUATING")
        evaluations = [
            item
            for item in self.repository.list_evaluations(test_run_id)
            if item.scope == StatusScope.STAGE and item.subject_id == stage_instance_id
        ]
        if not evaluations:
            raise RC8ContractError("SUFFICIENCY_EVALUATION_NOT_PROJECTED")
        evaluation = evaluations[-1]
        updated = graph.record_stage_sufficiency(stage_instance_id, evaluation)
        self.repository.upsert_stage(updated)
        return updated

    def complete_sufficiency(self, test_run_id: str, stage_instance_id: str) -> StageInstance:
        graph = self._hydrate(test_run_id)
        updated = graph.complete_sufficiency_stage(stage_instance_id)
        self.repository.upsert_stage(updated)
        return updated

    def invalidate(
        self,
        *,
        test_run_id: str,
        source_ref: str,
        stage_instance_ids: Sequence[str],
        reason: str,
        evidence_refs: Sequence[str],
        invalidation_id: str,
    ):
        graph = self._hydrate(test_run_id)
        record = graph.invalidate_from(
            source_ref,
            stage_instance_ids,
            reason=reason,
            evidence_refs=evidence_refs,
            invalidation_id=invalidation_id,
        )
        self.repository.append_invalidation(record)
        for stage_id in record.target_refs:
            self.repository.upsert_stage(graph.runtime.stages[stage_id])
        return record

    def ready_stage_ids(self, test_run_id: str) -> Tuple[str, ...]:
        graph = self._hydrate(test_run_id)
        result: List[str] = []
        for stage in graph.runtime.stages.values():
            if stage.state == StageState.PENDING and graph.can_mark_ready(stage.stage_instance_id):
                result.append(stage.stage_instance_id)
        return tuple(sorted(result))
