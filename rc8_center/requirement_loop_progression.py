"""Requirement-analysis repair loop on top of evidence-gated Mission progression.

This module does not evaluate model output.  It consumes already projected
``SufficiencyEvaluation`` truth.  When a REQUIREMENT_SUFFICIENCY Stage is
INSUFFICIENT it appends a new REQUIREMENT_ANALYSIS/REQUIREMENT_SUFFICIENCY
attempt pair, preserves the old Stage/Evaluation/Gap facts, and moves the still
PENDING CODE_ANALYSIS gate to the latest sufficiency attempt.

The rework is bounded.  Hitting the attempt cap leaves the requirement gap open
and CODE_ANALYSIS blocked; it never fabricates sufficient truth.
"""
from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import List, Optional, Tuple

from rc8_runtime import WorkItemIdentity
from rc8_runtime.governance import StageInstance, StageState, SufficiencyEvaluation, SufficiencyResult
from rc8_runtime.mission_graph import MissionStageType, validate_edge

from .autonomous_progression import AutonomousMissionProgressor, ProgressionOutcome
from .control_plane import WorkItemRecord


REQUIREMENT_REPAIR_POLICY_VERSION = "rc8.requirement-repair.v1"
DEFAULT_MAX_REQUIREMENT_ANALYSIS_ATTEMPTS = 3


def _stable_stage_id(test_run_id: str, scope_version: str, stage_type: str, attempt_no: int) -> str:
    raw = "\x1f".join(("stage", test_run_id, scope_version, stage_type, "attempt:%s" % int(attempt_no)))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    readable = stage_type.lower().replace("_", "-")
    return "stage-%s-%s" % (readable[:48], digest)


def _dedupe(values) -> Tuple[str, ...]:
    result: List[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if normalized and normalized not in result:
            result.append(normalized)
    return tuple(result)


class RequirementLoopProgressor(AutonomousMissionProgressor):
    """Adds bounded requirement-analysis rework without weakening base gates."""

    def __init__(self, *args, max_requirement_analysis_attempts: int = DEFAULT_MAX_REQUIREMENT_ANALYSIS_ATTEMPTS, **kwargs):
        super().__init__(*args, **kwargs)
        if not isinstance(max_requirement_analysis_attempts, int) or max_requirement_analysis_attempts < 1:
            raise ValueError("REQUIREMENT_REPAIR_MAX_ATTEMPTS_INVALID")
        self.max_requirement_analysis_attempts = max_requirement_analysis_attempts

    def reconcile_completed_work_item(self, work_item_id: str) -> ProgressionOutcome:
        outcome = super().reconcile_completed_work_item(work_item_id)
        if not outcome.source_stage_instance_id:
            return outcome
        stage = self.governance_repository.get_stage(outcome.source_stage_instance_id)
        if stage is None or stage.stage_type != MissionStageType.REQUIREMENT_SUFFICIENCY.value:
            return outcome
        evaluation = self._latest_stage_evaluation(stage)
        if evaluation is None or evaluation.result != SufficiencyResult.INSUFFICIENT:
            return outcome

        created = self._ensure_requirement_rework(stage, evaluation)
        if not created:
            return replace(outcome, truth_note="REQUIREMENT_INSUFFICIENT_REPAIR_LIMIT_REACHED_CODE_ANALYSIS_BLOCKED")

        newly_ready, materialized = self.materialize_ready_work(stage.test_run_id)
        return replace(
            outcome,
            newly_ready_stage_ids=_dedupe(outcome.newly_ready_stage_ids + newly_ready),
            materialized_work_item_ids=_dedupe(outcome.materialized_work_item_ids + materialized),
            truth_note="REQUIREMENT_INSUFFICIENT_APPENDED_REPAIR_ATTEMPT",
        )

    def _ensure_requirement_rework(self, source: StageInstance, evaluation: SufficiencyEvaluation) -> bool:
        next_attempt = int(source.attempt_no) + 1
        if next_attempt > self.max_requirement_analysis_attempts:
            self._attach_gap_refs(source, evaluation)
            return False

        test_run_id = source.test_run_id
        scope_version = source.scope_version
        analysis_id = _stable_stage_id(
            test_run_id,
            scope_version,
            MissionStageType.REQUIREMENT_ANALYSIS.value,
            next_attempt,
        )
        sufficiency_id = _stable_stage_id(
            test_run_id,
            scope_version,
            MissionStageType.REQUIREMENT_SUFFICIENCY.value,
            next_attempt,
        )
        gap_refs = tuple("gap:%s" % value for value in evaluation.unresolved_gap_ids)
        repair_inputs = _dedupe(
            source.output_refs
            + gap_refs
            + (
                "evaluation:%s" % evaluation.evaluation_id,
                "repair-from-stage:%s" % source.stage_instance_id,
            )
        )

        analysis = self.governance_repository.get_stage(analysis_id)
        if analysis is None:
            analysis = self.mission_service.register_stage(
                test_run_id=test_run_id,
                stage_instance_id=analysis_id,
                stage_type=MissionStageType.REQUIREMENT_ANALYSIS,
                scope_version=scope_version,
                attempt_no=next_attempt,
                predecessor_ids=(source.stage_instance_id,),
                input_refs=repair_inputs,
                policy_version=REQUIREMENT_REPAIR_POLICY_VERSION,
            )

        sufficiency = self.governance_repository.get_stage(sufficiency_id)
        if sufficiency is None:
            sufficiency = self.mission_service.register_stage(
                test_run_id=test_run_id,
                stage_instance_id=sufficiency_id,
                stage_type=MissionStageType.REQUIREMENT_SUFFICIENCY,
                scope_version=scope_version,
                attempt_no=next_attempt,
                predecessor_ids=(analysis.stage_instance_id,),
                input_refs=_dedupe(repair_inputs + ("analysis-stage:%s" % analysis.stage_instance_id,)),
                policy_version=REQUIREMENT_REPAIR_POLICY_VERSION,
            )

        self._rewire_repair_graph(source, analysis, sufficiency, evaluation)
        self._attach_gap_refs(source, evaluation)
        return True

    def _rewire_repair_graph(
        self,
        previous_sufficiency: StageInstance,
        analysis: StageInstance,
        new_sufficiency: StageInstance,
        evaluation: SufficiencyEvaluation,
    ) -> None:
        """Persist both predecessor and successor sides of the dynamic repair path.

        Scheduler readiness is predecessor-based, but ``successor_ids`` is still
        durable product/debug topology and invalidation visibility.  Updating
        only predecessors would make the UI say ``sufficiency#1 -> code`` while
        runtime truth actually routes through analysis#2/sufficiency#2.
        """
        candidates = [
            stage
            for stage in self.governance_repository.list_stages(previous_sufficiency.test_run_id)
            if stage.stage_type == MissionStageType.CODE_ANALYSIS.value
            and stage.scope_version == previous_sufficiency.scope_version
        ]
        if not candidates:
            raise RuntimeError("REQUIREMENT_REPAIR_CODE_ANALYSIS_STAGE_NOT_FOUND")
        candidates.sort(key=lambda value: value.attempt_no)
        target = candidates[-1]
        if target.state != StageState.PENDING:
            if target.predecessor_ids != (new_sufficiency.stage_instance_id,):
                raise RuntimeError("REQUIREMENT_REPAIR_CANNOT_REWIRE_STARTED_CODE_ANALYSIS")
            return

        validate_edge(previous_sufficiency.stage_type, analysis.stage_type)
        validate_edge(analysis.stage_type, new_sufficiency.stage_type)
        validate_edge(new_sufficiency.stage_type, target.stage_type)

        source_current = self.governance_repository.get_stage(previous_sufficiency.stage_instance_id) or previous_sufficiency
        source_successors = tuple(
            value for value in source_current.successor_ids if value != target.stage_instance_id
        )
        source_updated = replace(
            source_current,
            successor_ids=_dedupe(source_successors + (analysis.stage_instance_id,)),
        )
        analysis_current = self.governance_repository.get_stage(analysis.stage_instance_id) or analysis
        analysis_updated = replace(
            analysis_current,
            successor_ids=_dedupe(analysis_current.successor_ids + (new_sufficiency.stage_instance_id,)),
        )
        sufficiency_current = self.governance_repository.get_stage(new_sufficiency.stage_instance_id) or new_sufficiency
        sufficiency_updated = replace(
            sufficiency_current,
            successor_ids=_dedupe(sufficiency_current.successor_ids + (target.stage_instance_id,)),
        )
        target_updated = replace(
            target,
            predecessor_ids=(new_sufficiency.stage_instance_id,),
            input_refs=_dedupe(
                target.input_refs
                + tuple("gap:%s" % value for value in evaluation.unresolved_gap_ids)
                + ("evaluation:%s" % evaluation.evaluation_id,)
            ),
        )
        self.governance_repository.upsert_stage(source_updated)
        self.governance_repository.upsert_stage(analysis_updated)
        self.governance_repository.upsert_stage(sufficiency_updated)
        self.governance_repository.upsert_stage(target_updated)

    def _attach_gap_refs(self, stage: StageInstance, evaluation: SufficiencyEvaluation) -> None:
        if not evaluation.unresolved_gap_ids:
            return
        current = self.governance_repository.get_stage(stage.stage_instance_id) or stage
        updated = replace(current, gap_refs=_dedupe(current.gap_refs + tuple(evaluation.unresolved_gap_ids)))
        self.governance_repository.upsert_stage(updated)

    def _latest_stage_evaluation(self, stage: StageInstance) -> Optional[SufficiencyEvaluation]:
        values = [
            value
            for value in self.governance_repository.list_evaluations(stage.test_run_id)
            if value.subject_id == stage.stage_instance_id
        ]
        if not values:
            return None
        values.sort(key=lambda value: (int(value.evaluated_at), value.evaluation_id))
        return values[-1]

    def _work_for_stage(self, stage: StageInstance) -> WorkItemRecord:
        """Carry repair gaps and predecessor Evidence into downstream work.

        Revision refs are still supplied by the base progressor from the frozen
        TestRun snapshot.  Adding Stage inputs/output refs makes repair work
        self-describing without switching RequirementRevision or ScopeRevision.
        """
        work = super()._work_for_stage(stage)
        refs: List[str] = list(work.identity.scope_refs)
        refs.extend(stage.input_refs)
        for predecessor_id in stage.predecessor_ids:
            predecessor = self.governance_repository.get_stage(predecessor_id)
            if predecessor is not None:
                refs.extend(predecessor.output_refs)
                refs.extend("gap:%s" % gap_id for gap_id in predecessor.gap_refs)
        identity = WorkItemIdentity(
            work_item_id=work.identity.work_item_id,
            test_run_id=work.identity.test_run_id,
            stage=work.identity.stage,
            scope_refs=list(_dedupe(refs)),
            required_capabilities=list(work.identity.required_capabilities),
        )
        return replace(work, identity=identity)
