"""RC8 durable Mission Graph semantics.

The graph is intentionally stricter than a workflow runner. Normal activity
stages may complete after evidence is ready; dedicated sufficiency stages can
unlock downstream work only through evidence-backed SufficiencyEvaluation.

`StageInstance.scope_version` is the canonical RequirementDeliveryScope snapshot
reference for this W-A contract (for example `scope:DS-123@v4`). Rework numbering
is isolated by `(stage_type, scope_version)` so multiple SST/application scopes
can run in one TestRun without contaminating one another.
"""
from __future__ import annotations

import time
from dataclasses import replace
from enum import Enum
from typing import Dict, List, Optional, Sequence, Set

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

# These edges exist specifically to repair an insufficient upstream result. They
# MUST NOT become ready from a green sufficiency gate, otherwise a successful
# stage would spuriously schedule repair work. Conversely, forward edges MUST
# NOT unlock from INSUFFICIENT.
_INSUFFICIENT_REWORK_EDGES = {
    (MissionStageType.REQUIREMENT_SUFFICIENCY, MissionStageType.REQUIREMENT_ANALYSIS),
    (MissionStageType.CODE_SUFFICIENCY, MissionStageType.CODE_ANALYSIS),
    (MissionStageType.CODE_SUFFICIENCY, MissionStageType.REQUIREMENT_ANALYSIS),
    (MissionStageType.DESIGN_SUFFICIENCY, MissionStageType.TEST_DESIGN),
    (MissionStageType.DESIGN_SUFFICIENCY, MissionStageType.CODE_ANALYSIS),
    (MissionStageType.DESIGN_SUFFICIENCY, MissionStageType.REQUIREMENT_ANALYSIS),
}

_CENTER_SUFFICIENCY_EVALUATOR_ID = "RC8_CENTER_SUFFICIENCY_LEDGER"
_CENTER_SUFFICIENCY_POLICY_PREFIX = "center-ledger:"
_CENTER_SUFFICIENCY_EVIDENCE_PREFIX = "ledger:"


def is_center_authoritative_sufficient_evaluation(evaluation: SufficiencyEvaluation) -> bool:
    """Return whether a green result is a Center-owned frozen-ledger decision.

    Negative outcomes can be reported by Workers because they never unlock
    forward progression. A positive outcome is privileged control-plane truth
    and must carry all three Center authority markers.
    """
    if not isinstance(evaluation, SufficiencyEvaluation):
        return False
    return (
        evaluation.result == SufficiencyResult.SUFFICIENT
        and evaluation.evaluator_id == _CENTER_SUFFICIENCY_EVALUATOR_ID
        and evaluation.policy_version.startswith(_CENTER_SUFFICIENCY_POLICY_PREFIX)
        and any(ref.startswith(_CENTER_SUFFICIENCY_EVIDENCE_PREFIX) for ref in evaluation.evidence_refs)
    )


def _require_center_authority_for_green(evaluation: SufficiencyEvaluation) -> None:
    if evaluation.result == SufficiencyResult.SUFFICIENT and not is_center_authoritative_sufficient_evaluation(evaluation):
        raise RC8ContractError("MISSION_SUFFICIENT_REQUIRES_CENTER_LEDGER_AUTHORITY")


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
    """Mission dependency/sufficiency/invalidation aggregate."""

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
            if stage_type != MissionStageType.SCOPE_INTAKE:
                raise RC8ContractError("MISSION_STAGE_PREDECESSOR_REQUIRED")
        if not stage.predecessor_ids and not self.runtime.stages and stage_type != MissionStageType.SCOPE_INTAKE:
            raise RC8ContractError("MISSION_FIRST_STAGE_MUST_BE_SCOPE_INTAKE")

        for predecessor_id in stage.predecessor_ids:
            predecessor = self.runtime.stages.get(predecessor_id)
            if predecessor is None:
                raise RC8ContractError("MISSION_PREDECESSOR_NOT_FOUND:%s" % predecessor_id)
            validate_edge(predecessor.stage_type, stage.stage_type)

        same_scope_type = [
            item
            for item in self.runtime.stages.values()
            if item.stage_type == stage.stage_type and item.scope_version == stage.scope_version
        ]
        if same_scope_type:
            highest = max(item.attempt_no for item in same_scope_type)
            if stage.attempt_no <= highest:
                raise RC8ContractError("MISSION_STAGE_REWORK_REQUIRES_NEW_ATTEMPT_NO")

        self.runtime.add_stage(stage)
        self._successors.setdefault(stage.stage_instance_id, set())
        for predecessor_id in stage.predecessor_ids:
            self._successors.setdefault(predecessor_id, set()).add(stage.stage_instance_id)

    def restore_evaluation(self, evaluation: SufficiencyEvaluation) -> None:
        if evaluation.scope != StatusScope.STAGE:
            return
        stage = self.runtime.stages.get(evaluation.subject_id)
        if stage is None:
            raise RC8ContractError("RESTORE_EVALUATION_STAGE_NOT_FOUND")
        if _stage_type(stage.stage_type) not in SUFFICIENCY_STAGES:
            raise RC8ContractError("RESTORE_EVALUATION_TARGET_NOT_SUFFICIENCY_STAGE")
        _require_center_authority_for_green(evaluation)
        self.runtime.record_evaluation(evaluation)
        self._stage_evaluations[evaluation.subject_id] = evaluation.evaluation_id

    def _predecessor_ready(self, predecessor: StageInstance, target: StageInstance) -> bool:
        predecessor_type = _stage_type(predecessor.stage_type)
        target_type = _stage_type(target.stage_type)
        if predecessor.state in {StageState.INVALIDATED, StageState.SUPERSEDED}:
            return False
        if predecessor_type in SUFFICIENCY_STAGES:
            evaluation_id = self._stage_evaluations.get(predecessor.stage_instance_id)
            if not evaluation_id:
                return False
            evaluation = self.runtime.evaluations[evaluation_id]
            edge = (predecessor_type, target_type)
            if edge in _INSUFFICIENT_REWORK_EDGES:
                return evaluation.result == SufficiencyResult.INSUFFICIENT and predecessor.state in {
                    StageState.INSUFFICIENT,
                    StageState.COMPLETED,
                }
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
        return all(self._predecessor_ready(self.runtime.stages[pred], stage) for pred in stage.predecessor_ids)

    def mark_ready(self, stage_instance_id: str) -> StageInstance:
        if not self.can_mark_ready(stage_instance_id):
            raise RC8ContractError("MISSION_STAGE_DEPENDENCIES_NOT_SATISFIED")
        return self.runtime.transition_stage(stage_instance_id, StageState.READY)

    def record_activity_completion(self, stage_instance_id: str, output_refs: Sequence[str]) -> StageInstance:
        stage = self.runtime.stages.get(stage_instance_id)
        if stage is None:
            raise RC8ContractError("STAGE_INSTANCE_NOT_FOUND")
        if _stage_type(stage.stage_type) in SUFFICIENCY_STAGES:
            raise RC8ContractError("SUFFICIENCY_STAGE_REQUIRES_EVALUATION")
        if stage.state != StageState.EVIDENCE_PENDING:
            raise RC8ContractError("ACTIVITY_COMPLETION_REQUIRES_EVIDENCE_PENDING")
        refs = tuple(str(item).strip() for item in output_refs if isinstance(item, str) and item.strip())
        if not refs:
            raise RC8ContractError("ACTIVITY_COMPLETION_REQUIRES_OUTPUT_EVIDENCE")
        updated = replace(
            stage,
            state=StageState.COMPLETED,
            output_refs=tuple(dict.fromkeys(stage.output_refs + refs)),
            finished_at=int(time.time()),
        )
        self.runtime.stages[stage_instance_id] = updated
        return updated

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

        _require_center_authority_for_green(evaluation)
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

    def complete_sufficiency_stage(self, stage_instance_id: str) -> StageInstance:
        stage = self.runtime.stages.get(stage_instance_id)
        if stage is None:
            raise RC8ContractError("STAGE_INSTANCE_NOT_FOUND")
        if _stage_type(stage.stage_type) not in SUFFICIENCY_STAGES:
            raise RC8ContractError("ACTIVITY_STAGE_USES_ACTIVITY_COMPLETION")
        if stage.state not in {StageState.SUFFICIENT, StageState.INSUFFICIENT}:
            raise RC8ContractError("MISSION_STAGE_COMPLETION_REQUIRES_EVALUATION_RESULT")
        return self.runtime.transition_stage(stage_instance_id, StageState.COMPLETED)

    def complete_stage(self, stage_instance_id: str) -> StageInstance:
        return self.complete_sufficiency_stage(stage_instance_id)

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
                updated = replace(
                    stage,
                    state=StageState.INVALIDATED,
                    invalidation_refs=tuple(list(stage.invalidation_refs) + [invalidation_id]),
                    finished_at=stage.finished_at or int(time.time()),
                )
                self.runtime.stages[stage_id] = updated
        return record

    def latest_stage(self, stage_type: MissionStageType, scope_version: Optional[str] = None) -> Optional[StageInstance]:
        items = [stage for stage in self.runtime.stages.values() if stage.stage_type == stage_type.value]
        if scope_version is not None:
            items = [stage for stage in items if stage.scope_version == scope_version]
        if not items:
            return None
        return sorted(items, key=lambda item: item.attempt_no)[-1]

    def stage_evaluation(self, stage_instance_id: str) -> Optional[SufficiencyEvaluation]:
        evaluation_id = self._stage_evaluations.get(stage_instance_id)
        if not evaluation_id:
            return None
        return self.runtime.evaluations[evaluation_id]
