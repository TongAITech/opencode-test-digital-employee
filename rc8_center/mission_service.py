"""Center-owned Mission Graph control service.

Mission/Stage topology is durable control-domain state owned by Center. Runtime
facts (Attempt/Coverage/Gap/Sufficiency) arrive through R1 projection. Worker
sufficiency facts are candidates; a forward-unlocking SUFFICIENT result must be
recomputed by a Center-owned frozen denominator.
"""
from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import List, Optional, Sequence, Tuple

from rc8_runtime import RC8ContractError
from rc8_runtime.governance import CoverageDimension, StageInstance, StageState, StatusScope, SufficiencyEvaluation, SufficiencyResult
from rc8_runtime.mission_graph import MissionGraphRuntime, MissionStageType, SUFFICIENCY_STAGES
from rc8_runtime.sufficiency import DimensionAssessment, DimensionState, FrozenSufficiencyLedger, RequiredDimension, evaluate_frozen_ledger

from .code_sufficiency import CenterCodeSufficiencyEvaluator
from .repository_ports import GovernanceRepository


_REQUIREMENT_DIMENSION_IDS = (
    "dimension:requirement-source-assertions",
    "dimension:requirement-atomic-statements",
    "dimension:requirement-traceability",
    "dimension:requirement-evidence",
    "dimension:requirement-normal-path",
    "dimension:requirement-open-question",
)
_CENTER_REQUIREMENT_POLICY = "rc8.requirement-sufficiency-center.v1"
_CENTER_EVALUATOR_ID = "RC8_CENTER_SUFFICIENCY_LEDGER"
_N8_ROUTE_CONTROLLED_STAGE_TYPES = frozenset(
    {
        MissionStageType.DELTA_REPAIR,
        MissionStageType.TARGETED_REEXECUTION,
    }
)


def _center_authoritative(evaluation: SufficiencyEvaluation) -> bool:
    return evaluation.policy_version.startswith("center-ledger:") and evaluation.evaluator_id == _CENTER_EVALUATOR_ID and any(ref.startswith("ledger:") for ref in evaluation.evidence_refs)


class CenterMissionService:
    def __init__(self, repository: GovernanceRepository, traceability_repository=None) -> None:
        self.repository = repository
        self.traceability_repository = traceability_repository

    def _hydrate(self, test_run_id: str) -> MissionGraphRuntime:
        graph = MissionGraphRuntime(test_run_id)
        remaining = list(self.repository.list_stages(test_run_id))
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

        for evaluation in self.repository.list_evaluations(test_run_id):
            if evaluation.scope != StatusScope.STAGE:
                continue
            stage = graph.runtime.stages.get(evaluation.subject_id)
            if stage is None:
                continue
            if evaluation.result == SufficiencyResult.SUFFICIENT and not _center_authoritative(evaluation):
                continue
            if stage.state in {StageState.SUFFICIENT, StageState.INSUFFICIENT, StageState.COMPLETED}:
                graph.restore_evaluation(evaluation)
        return graph

    def register_stage(self, *, test_run_id: str, stage_instance_id: str, stage_type: MissionStageType, scope_version: str, attempt_no: int, predecessor_ids: Sequence[str] = (), input_refs: Sequence[str] = (), assigned_worker: Optional[str] = None, policy_version: Optional[str] = None) -> StageInstance:
        # Recovery routing is N8 control-plane authority.  Keeping these stage
        # types in MissionGraph preserves durable graph compatibility, but the
        # generic registration surface must never let a caller choose its own
        # repair/re-execution route.  N8 authorizes targeted successor work via
        # evidence-backed RepairWorkOrder/RepairReceipt instead.
        if stage_type in _N8_ROUTE_CONTROLLED_STAGE_TYPES:
            raise RC8ContractError("N8_ROUTE_AUTHORITY_REQUIRED:%s" % stage_type.value)
        if self.repository.get_stage(stage_instance_id) is not None:
            raise RC8ContractError("STAGE_INSTANCE_ALREADY_EXISTS")
        graph = self._hydrate(test_run_id)
        stage = StageInstance(stage_instance_id=stage_instance_id, test_run_id=test_run_id, stage_type=stage_type.value, scope_version=scope_version, attempt_no=attempt_no, predecessor_ids=tuple(predecessor_ids), input_refs=tuple(input_refs), assigned_worker=assigned_worker, policy_version=policy_version)
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

    def complete_activity(self, test_run_id: str, stage_instance_id: str, output_refs: Sequence[str]) -> StageInstance:
        graph = self._hydrate(test_run_id)
        updated = graph.record_activity_completion(stage_instance_id, output_refs)
        self.repository.upsert_stage(updated)
        return updated

    def begin_sufficiency_evaluation(self, test_run_id: str, stage_instance_id: str, evidence_refs: Sequence[str]) -> StageInstance:
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
        graph = self._hydrate(test_run_id)
        stage = graph.runtime.stages.get(stage_instance_id)
        if stage is None:
            raise RC8ContractError("STAGE_INSTANCE_NOT_FOUND")
        if stage.state != StageState.EVALUATING:
            raise RC8ContractError("MISSION_STAGE_MUST_BE_EVALUATING")
        evaluations = [item for item in self.repository.list_evaluations(test_run_id) if item.scope == StatusScope.STAGE and item.subject_id == stage_instance_id]
        if not evaluations:
            raise RC8ContractError("SUFFICIENCY_EVALUATION_NOT_PROJECTED")

        authoritative = [item for item in evaluations if _center_authoritative(item)]
        if authoritative:
            evaluation = authoritative[-1]
        else:
            candidate = evaluations[-1]
            if candidate.result == SufficiencyResult.SUFFICIENT:
                evaluation = self._recompute_worker_green(stage, candidate)
                self.repository.append_evaluation(evaluation)
            else:
                evaluation = candidate

        updated = graph.record_stage_sufficiency(stage_instance_id, evaluation)
        self.repository.upsert_stage(updated)
        return updated

    def _recompute_worker_green(self, stage: StageInstance, candidate: SufficiencyEvaluation) -> SufficiencyEvaluation:
        stage_type = MissionStageType(stage.stage_type)
        if stage_type == MissionStageType.CODE_SUFFICIENCY:
            if self.traceability_repository is None:
                raise RC8ContractError("CENTER_CODE_SUFFICIENCY_TRACEABILITY_REPOSITORY_REQUIRED")
            graph_refs = tuple(dict.fromkeys(ref.split(":", 1)[1] for ref in stage.input_refs + stage.output_refs if isinstance(ref, str) and ref.startswith("trace-graph:") and ref.split(":", 1)[1]))
            if len(graph_refs) != 1:
                raise RC8ContractError("CENTER_CODE_SUFFICIENCY_REQUIRES_SINGLE_TRACE_GRAPH")
            result = CenterCodeSufficiencyEvaluator(self.traceability_repository).evaluate(
                test_run_id=stage.test_run_id,
                stage_instance_id=stage.stage_instance_id,
                graph_id=graph_refs[0],
                active_gap_ids=candidate.unresolved_gap_ids,
                worker_claimed_sufficient=True,
            )
            # Center code evaluator is the only authority allowed to turn a
            # Worker CODE_SUFFICIENCY green into forward-unlocking SUFFICIENT.
            return replace(result.evaluation, evaluated_at=max(result.evaluation.evaluated_at, candidate.evaluated_at + 1))
        if stage_type != MissionStageType.REQUIREMENT_SUFFICIENCY:
            raise RC8ContractError("CENTER_SUFFICIENCY_LEDGER_BUILDER_REQUIRED:%s" % stage_type.value)

        source_refs = tuple(dict.fromkeys(stage.input_refs + stage.output_refs))
        if not source_refs:
            source_refs = ("stage-scope:%s" % stage.scope_version,)
        digest_input = "\x1f".join((stage.test_run_id, stage.stage_instance_id, _CENTER_REQUIREMENT_POLICY) + source_refs + _REQUIREMENT_DIMENSION_IDS)
        ledger_id = "ledger-req-%s" % hashlib.sha256(digest_input.encode("utf-8")).hexdigest()[:32]
        required = tuple(RequiredDimension(dimension_id=dimension_id, dimension=CoverageDimension.REQUIREMENT, source_ref=source_refs[0]) for dimension_id in _REQUIREMENT_DIMENSION_IDS)
        ledger = FrozenSufficiencyLedger(ledger_id=ledger_id, test_run_id=stage.test_run_id, subject_id=stage.stage_instance_id, policy_version=_CENTER_REQUIREMENT_POLICY, source_refs=source_refs, required_dimensions=required)

        declared = set(candidate.dimension_refs)
        satisfied = set(candidate.satisfied_requirement_refs)
        unsatisfied = set(candidate.unsatisfied_requirement_refs)
        assessments = []
        for item in required:
            dimension_id = item.dimension_id
            if dimension_id not in declared:
                assessments.append(DimensionAssessment(dimension_id=dimension_id, state=DimensionState.UNKNOWN, reason="worker omitted frozen required dimension"))
            elif dimension_id in satisfied and dimension_id not in unsatisfied:
                assessments.append(DimensionAssessment(dimension_id=dimension_id, state=DimensionState.SATISFIED, evidence_refs=candidate.evidence_refs, reason="worker candidate satisfied; Center denominator preserved"))
            elif dimension_id in unsatisfied:
                assessments.append(DimensionAssessment(dimension_id=dimension_id, state=DimensionState.UNSATISFIED, evidence_refs=candidate.evidence_refs, reason="worker candidate reported unsatisfied"))
            else:
                assessments.append(DimensionAssessment(dimension_id=dimension_id, state=DimensionState.UNKNOWN, evidence_refs=candidate.evidence_refs, reason="candidate has no unambiguous state for frozen dimension"))

        decision = evaluate_frozen_ledger(ledger, assessments, evaluator_id=_CENTER_EVALUATOR_ID, active_gap_ids=candidate.unresolved_gap_ids, worker_claimed_sufficient=True)
        evaluation = decision.to_evaluation("center-%s" % candidate.evaluation_id)
        return replace(evaluation, evaluated_at=max(evaluation.evaluated_at, candidate.evaluated_at + 1))

    def complete_sufficiency(self, test_run_id: str, stage_instance_id: str) -> StageInstance:
        graph = self._hydrate(test_run_id)
        updated = graph.complete_sufficiency_stage(stage_instance_id)
        self.repository.upsert_stage(updated)
        return updated

    def invalidate(self, *, test_run_id: str, source_ref: str, stage_instance_ids: Sequence[str], reason: str, evidence_refs: Sequence[str], invalidation_id: str):
        graph = self._hydrate(test_run_id)
        record = graph.invalidate_from(source_ref, stage_instance_ids, reason=reason, evidence_refs=evidence_refs, invalidation_id=invalidation_id)
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
