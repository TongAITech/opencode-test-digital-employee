"""RC8 durable Mission Graph semantics.

The graph is intentionally stricter than a workflow runner.  Normal activity
stages may complete, but downstream gates that depend on sufficiency stages are
released only by evidence-backed SufficiencyEvaluation records.
"""
from __future__ import annotations

from dataclasses import replace
from enum import Enum
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .contracts import RC8ContractError
from .governance import (
    InvalidationRecord,
    MissionRuntimeState,
    StageInstance,
    StageState,
    StatusScope,
    SufficiencyEvaluation,
    SufficiencyResult,
)


class MissionStageType(str, Enum):
    SCOPE_INTAKE = "SCOPE_INTAKE"
    REQUIREMENT_ANALYSIS = "REQUIREMENT_ANALYSIS"
    REQUIREMENT_SUFFICIENCY = "REQUIREMENT_SUFFICIENCY"
    CODE_ANALYSIS = "CODE_ANALYSIS"
    CODE_SUFFICIENCY = "CODE_SUFFICIENCY"
    RISK_TEST_MODEL = "RISK_TEST_MODEL"
    TEST_DESIGN = "TEST_DESIGN"
    DESIGN_SUFFICIENCY = "DESIGN_SUFFICIENCY"
    EXECUTABLE_SPEC = "EXECUTABLE_SPEC"
    PRECONDITION_DATA_PREP = "PRECONDITION_DATA_PREP"
    APPLICABLE_LAYER_EXECUTION = "APPLICABLE_LAYER_EXECUTION"
    FAILURE_COVERAGE_EVALUATION = "FAILURE_COVERAGE_EVALUATION"
    DELTA_REPAIR = "DELTA_REPAIR"
    TARGETED_REEXECUTION = "TARGETED_REEXECUTION"
    MISSION_SUFFICIENCY = "MISSION_SUFFICIENCY"
    REPORT_RELEASE = "REPORT_RELEASE"


SUFFICIENCY_STAGES = {
    MissionStageType.REQUIREMENT_SUFFICIENCY,
    MissionStageType.CODE_SUFFICIENCY,
    MissionStageType.DESIGN_SUFFICIENCY,
    MissionStageType.MISSION_SUFFICIENCY,
}


# Legal forward/rework edges.  Gap routing remains a separate policy in
# governance.py; these edges prevent arbitrary stage skipping.
_ALLOWED_EDGES = {
    (MissionStageType.SCOPE_INTAKE, MissionStageType.REQUIREMENT_ANALYSIS),
    (MissionStageType.REQUIREMENT_ANALYSIS, MissionStageType.REQUIREMENT_SUFFICIENCY),
    (MissionStageType.REQUIREMENT_SUFFICIENCY, MissionStageType.REQUIREMENT_ANALYSIS),
    (MissionStageType.REQUIREMENT_SUFFICIENCY, MissionStageType.CODE_ANALYSIS),
    (MissionStageType.CODE_ANALYSIS, MissionStageType.CODE_SUFFICIENCY),
    (MissionStageType.CODE_SUFFICIENCY, MissionStageType.CODE_ANALYSIS),
    (MissionStageType.CODE_SUFFICIENCY, MissionStageType.REQUIREMENT_ANALYSIS),
    (MissionStageType.CODE_SUFFICIENCY, MissionStageType.RISK_TEST_MODEL),
    (MissionStageType.RISK_TEST_MODEL, MissionStageType.TEST_DESIGN),
    (MissionStageType.TEST_DESIGN, MissionStageType.DESIGN_SUFFICIENCY),
    (MissionStageType.DESIGN_SUFFICIENCY, MissionStageType.TEST_DESIGN),
    (MissionStageType.DESIGN_SUFFICIENCY, MissionStageType.CODE_ANALYSIS),
    (MissionStageType.DESIGN_SUFFICIENCY, MissionStageType.REQUIREMENT_ANALYSIS),
    (MissionStageType.DESIGN_SUFFICIENCY, MissionStageType.EXECUTABLE_SPEC),
    (MissionStageType.EXECUTABLE_SPEC, MissionStageType.PRECONDITION_DATA_PREP),
    (MissionStageType.PRECONDITION_DATA_PREP, MissionStageType.APPLICABLE_LAYER_EXECUTION),
    (MissionStageType.APPLICABLE_LAYER_EXECUTION, MissionStageType.FAILURE_COVERAGE_EVALUATION),
    (MissionStageType.FAILURE_COVERAGE_EVALUATION, MissionStageType.DELTA_REPAIR),
    (MissionStageType.FAILURE_COVERAGE_EVALUATION, MissionStageType.MISSION_SUFFICIENCY),
    (MissionStageType.DELTA_REPAIR, MissionStageType.TARGETED_REEXECUTION),
    (MissionStageType.TARGETED_REEXECUTION, MissionStageType.FAILURE_COVERAGE_EVALUATION),
    (MissionStageType.MISSION_SUFFICIENCY, MissionStageType.REPORT_RELEASE),
}


def _stage_type(value: str) -> MissionStageType:
    try:
        return MissionStageType(value)
    except ValueError as exc:
        raise RC8ContractError("MISSION_STAGE_TYPE_UNKNOWN:%s" % value) from exc


def validate_edge(source_type: str, target_type: str) -> None:
    source = _stage_type(source_type)
    target = _stage_type(target_type)
    if (source, target) not in _ALLOWED_EDGES:
        raise RC8ContractError("MISSION_STAGE_EDGE_FORBIDDEN:%s->%s" % (source.value, target.value))


class MissionGraphRuntime:
    """Mission dependency/sufficiency/invalidation aggregate.

    Persistence is intentionally external.  Center repositories store the
    records; this class defines which state transitions are legal.
    """

    def __init__(self, test_run_id: str) -> None:
        self.runtime = MissionRuntimeState(test_run_id)
        self._successors: Dict[str, Set[str]] = {}
        self._stage_evaluations: Dict[str, str] = {}

    @property
    def test_run_id(self) -> str:
        return self.runtime.test_run_id

    def add_stage(self, stage: StageInstance) -> None:
        stage_type = _stage_type(stage.stage_type)
        if not stage.predecessor_ids and self.runtime.stages:
            # Only intake may start a populated mission without a predecessor.
            if stage_type != MissionStageType.SCOPE_INTAKE:
                raise RC8ContractError("MISSION_STAGE_PREDECESSOR_REQUIRED")
        if not stage.predecessor_ids and not self.runtime.stages and stage_type != MissionStageType.SCOPE_INTAKE:
            raise RC8ContractError("MISSION_FIRST_STAGE_MUST_BE_SCOPE_INTAKE")

        for predecessor_id in stage.predecessor_ids:
            predecessor = self.runtime.stages.get(predecessor_id)
            if predecessor is None:
                raise RC8ContractError("MISSION_PREDECESSOR_NOT_FOUND:%s" % predecessor_id)
            validate_edge(predecessor.stage_type, stage.stage_type)

        # Rework creates a new StageInstance with increasing attempt_no.
        same_type = [item for item in self.runtime.stages.values() if item.stage_type == stage.stage_type]
        if same_type:
            highest = max(item.attempt_no for item in same_type)
            if stage.attempt_no <= highest:
                raise RC8ContractError("MISSION_STAGE_REWORK_REQUIRES_NEW_ATTEMPT_NO")

        self.runtime.add_stage(stage)
        self._successors.setdefault(stage.stage_instance_id, set())
        for predecessor_id in stage.predecessor_ids:
            self._successors.setdefault(predecessor_id, set()).add(stage.stage_instance_id)

    def _predecessor_ready(self, predecessor: StageInstance) -> bool:
        predecessor_type = _stage_type(predecessor.stage_type)
        if predecessor.state in {StageState.INVALIDATED, StageState.SUPERSEDED}:
            return False
        if predecessor_type in SUFFICIENCY_STAGES:
            evaluation_id = self._stage_evaluations.get(predecessor.stage_instance_id)
            if not evaluation_id:
                return False
            evaluation = self.runtime.evaluations[evaluation_id]
            return evaluation.result == SufficiencyResult.SUFFICIENT and predecessor.state in {
                StageState.SUFFICIENT,
                StageState.COMPLETED,
            }
        return predecessor.state == StageState.COMPLETED

    def can_mark_ready(self, stage_instance_id: str) -> bool:
        stage = self.runtime.stages.get(stage_instance_id)
        if stage is None:
            raise RC8ContractError("STAGE_INSTANCE_NOT_FOUND")
        if stage.state != StageState.PENDING:
            return False
        if not stage.predecessor_ids:
            return _stage_type(stage.stage_type) == MissionStageType.SCOPE_INTAKE
        return all(self._predecessor_ready(self.runtime.stages[pred]) for pred in stage.predecessor_ids)

    def mark_ready(self, stage_instance_id: str) -> StageInstance:
        if not self.can_mark_ready(stage_instance_id):
            raise RC8ContractError("MISSION_STAGE_DEPENDENCIES_NOT_SATISFIED")
        return self.runtime.transition_stage(stage_instance_id, StageState.READY)

    def record_stage_sufficiency(self, stage_instance_id: str, evaluation: SufficiencyEvaluation) -> StageInstance:
        stage = self.runtime.stages.get(stage_instance_id)
        if stage is None:
            raise RC8ContractError("STAGE_INSTANCE_NOT_FOUND")
        if _stage_type(stage.stage_type) not in SUFFICIENCY_STAGES:
            raise RC8ContractError("MISSION_STAGE_IS_NOT_SUFFICIENCY_STAGE")
        if evaluation.scope != StatusScope.STAGE:
            raise RC8ContractError("MISSION_STAGE_EVALUATION_SCOPE_REQUIRED")
        if evaluation.subject_id != stage_instance_id:
            raise RC8ContractError("MISSION_STAGE_EVALUATION_SUBJECT_MISMATCH")
        if stage.state != StageState.EVALUATING:
            raise RC8ContractError("MISSION_STAGE_MUST_BE_EVALUATING")

        self.runtime.record_evaluation(evaluation)
        self._stage_evaluations[stage_instance_id] = evaluation.evaluation_id
        target = {
            SufficiencyResult.SUFFICIENT: StageState.SUFFICIENT,
            SufficiencyResult.INSUFFICIENT: StageState.INSUFFICIENT,
            SufficiencyResult.BASELINE_ONLY: StageState.INSUFFICIENT,
            SufficiencyResult.BLOCKED: StageState.BLOCKED,
        }[evaluation.result]
        if target in {StageState.SUFFICIENT, StageState.INSUFFICIENT}:
            return self.runtime.transition_stage(stage_instance_id, target, evaluator_id=evaluation.evaluator_id)
        return self.runtime.transition_stage(stage_instance_id, target)

    def complete_stage(self, stage_instance_id: str) -> StageInstance:
        stage = self.runtime.stages.get(stage_instance_id)
        if stage is None:
            raise RC8ContractError("STAGE_INSTANCE_NOT_FOUND")
        if stage.state not in {StageState.SUFFICIENT, StageState.INSUFFICIENT}:
            raise RC8ContractError("MISSION_STAGE_COMPLETION_REQUIRES_EVALUATION_RESULT")
        return self.runtime.transition_stage(stage_instance_id, StageState.COMPLETED)

    def invalidate_from(
        self,
        source_ref: str,
        stage_instance_ids: Sequence[str],
        *,
        reason: str,
        evidence_refs: Sequence[str],
        invalidation_id: str,
    ) -> InvalidationRecord:
        targets: Set[str] = set()
        queue: List[str] = list(stage_instance_ids)
        while queue:
            stage_id = queue.pop(0)
            if stage_id in targets:
                continue
            if stage_id not in self.runtime.stages:
                raise RC8ContractError("INVALIDATION_STAGE_NOT_FOUND:%s" % stage_id)
            targets.add(stage_id)
            queue.extend(sorted(self._successors.get(stage_id, set())))

        record = InvalidationRecord(
            invalidation_id=invalidation_id,
            test_run_id=self.test_run_id,
            source_ref=source_ref,
            target_refs=tuple(sorted(targets)),
            reason=reason,
            evidence_refs=tuple(evidence_refs),
        )
        self.runtime.add_invalidation(record)

        for stage_id in sorted(targets):
            stage = self.runtime.stages[stage_id]
            if stage.state == StageState.SUPERSEDED:
                continue
            if stage.state != StageState.INVALIDATED:
                # Hydrated/current proof can be invalidated without deleting it.
                updated = replace(
                    stage,
                    state=StageState.INVALIDATED,
                    invalidation_refs=tuple(list(stage.invalidation_refs) + [invalidation_id]),
                )
                self.runtime.stages[stage_id] = updated
        return record

    def latest_stage(self, stage_type: MissionStageType) -> Optional[StageInstance]:
        items = [stage for stage in self.runtime.stages.values() if stage.stage_type == stage_type.value]
        if not items:
            return None
        return sorted(items, key=lambda item: item.attempt_no)[-1]

    def stage_evaluation(self, stage_instance_id: str) -> Optional[SufficiencyEvaluation]:
        evaluation_id = self._stage_evaluations.get(stage_instance_id)
        if not evaluation_id:
            return None
        return self.runtime.evaluations[evaluation_id]
