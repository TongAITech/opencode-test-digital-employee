"""Adopt existing RC8 N2/N3/N4 stages into N1-N10 delivery contracts.

This adapter deliberately reuses the existing durable MissionStage graph and
Center sufficiency decisions. It does not create a second Requirement, Code or
Test Design state machine. A MissionNode delivery can be assembled only from
the latest stage attempt for the same run/scope, a current N1 RealitySnapshot
binding, and Center-authoritative green sufficiency evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

from rc8_runtime.governance import StageInstance, StageState, SufficiencyEvaluation, SufficiencyResult
from rc8_runtime.mission_graph import MissionStageType, is_center_authoritative_sufficient_evaluation
from rc8_runtime.mission_nodes import MissionNodeInstance, MissionNodeState, MissionNodeType, NodeDeliveryPackage

from .control_plane import CenterControlError
from .reality_snapshot import MissionNodeRealityBinding, RealitySnapshotRepository
from .repository_ports import GovernanceRepository


_REQUIRED_STAGES: Dict[MissionNodeType, Tuple[MissionStageType, ...]] = {
    MissionNodeType.N2_REQUIREMENT_ANALYSIS: (
        MissionStageType.REQUIREMENT_ANALYSIS,
        MissionStageType.REQUIREMENT_SUFFICIENCY,
    ),
    MissionNodeType.N3_CODE_ANALYSIS: (
        MissionStageType.CODE_ANALYSIS,
        MissionStageType.CODE_SUFFICIENCY,
    ),
    MissionNodeType.N4_TEST_DESIGN: (
        MissionStageType.RISK_TEST_MODEL,
        MissionStageType.TEST_DESIGN,
        MissionStageType.DESIGN_SUFFICIENCY,
    ),
}

_SUFFICIENCY_STAGE_TYPES = {
    MissionStageType.REQUIREMENT_SUFFICIENCY,
    MissionStageType.CODE_SUFFICIENCY,
    MissionStageType.DESIGN_SUFFICIENCY,
}


@dataclass(frozen=True)
class MissionNodeAdoptionDelivery:
    package: NodeDeliveryPackage
    reality_binding: MissionNodeRealityBinding
    stage_instance_ids: Tuple[str, ...]
    sufficiency_evaluation_ids: Tuple[str, ...]


class CenterMissionNodeAdoptionService:
    """Center-side adapter from legacy durable Stage truth to N2-N4 delivery."""

    def __init__(
        self,
        governance_repository: GovernanceRepository,
        reality_repository: RealitySnapshotRepository,
    ) -> None:
        self.governance_repository = governance_repository
        self.reality_repository = reality_repository

    def build_delivery(
        self,
        *,
        node: MissionNodeInstance,
        reality_binding: MissionNodeRealityBinding,
        package_id: str,
        attempt_ref: str,
    ) -> MissionNodeAdoptionDelivery:
        self._validate_node(node)
        self._validate_reality(node, reality_binding)
        package_id = self._required(package_id, "package_id")
        attempt_ref = self._required(attempt_ref, "attempt_ref")

        required = _REQUIRED_STAGES[node.node_type]
        stages = self._latest_required_stages(node, required)
        evaluations = self._authoritative_sufficiency(node, stages)

        evidence_refs: List[str] = []
        output_refs: List[str] = [
            "reality-snapshot:%s" % reality_binding.reality_snapshot_id,
            "reality-binding:%s" % reality_binding.binding_id,
        ]
        for stage in stages:
            output_refs.append("stage:%s" % stage.stage_instance_id)
            output_refs.extend(stage.output_refs)
            # Activity stage completion requires output evidence in the existing
            # MissionGraph. Preserve those refs as delivery evidence.
            if MissionStageType(stage.stage_type) not in _SUFFICIENCY_STAGE_TYPES:
                evidence_refs.extend(stage.output_refs)
        for evaluation in evaluations:
            output_refs.append("sufficiency:%s" % evaluation.evaluation_id)
            output_refs.extend(evaluation.dimension_refs)
            evidence_refs.extend(evaluation.evidence_refs)

        evidence_refs = list(dict.fromkeys(ref for ref in evidence_refs if ref))
        output_refs = list(dict.fromkeys(ref for ref in output_refs if ref))
        if not evidence_refs:
            raise CenterControlError("MISSION_NODE_ADOPTION_REQUIRES_EVIDENCE")

        package = NodeDeliveryPackage(
            package_id=package_id,
            test_run_id=node.test_run_id,
            mission_node_id=node.mission_node_id,
            attempt_ref=attempt_ref,
            evidence_refs=tuple(evidence_refs),
            output_refs=tuple(output_refs),
        )
        return MissionNodeAdoptionDelivery(
            package=package,
            reality_binding=reality_binding,
            stage_instance_ids=tuple(stage.stage_instance_id for stage in stages),
            sufficiency_evaluation_ids=tuple(value.evaluation_id for value in evaluations),
        )

    def _validate_node(self, node: MissionNodeInstance) -> None:
        if not isinstance(node, MissionNodeInstance):
            raise CenterControlError("MISSION_NODE_INSTANCE_REQUIRED")
        if node.node_type not in _REQUIRED_STAGES:
            raise CenterControlError("MISSION_NODE_ADOPTION_UNSUPPORTED:%s" % node.node_type.value)
        if node.state != MissionNodeState.IN_PROGRESS:
            raise CenterControlError("MISSION_NODE_ADOPTION_REQUIRES_IN_PROGRESS")

    def _validate_reality(self, node: MissionNodeInstance, binding: MissionNodeRealityBinding) -> None:
        if not isinstance(binding, MissionNodeRealityBinding):
            raise CenterControlError("MISSION_NODE_REALITY_BINDING_REQUIRED")
        if binding.test_run_id != node.test_run_id:
            raise CenterControlError("MISSION_NODE_REALITY_TEST_RUN_MISMATCH")
        if binding.mission_node_id != node.mission_node_id or binding.mission_node_type != node.node_type:
            raise CenterControlError("MISSION_NODE_REALITY_SUBJECT_MISMATCH")
        latest = self.reality_repository.latest_reality_snapshot(node.test_run_id, node.scope_version)
        if latest is None:
            raise CenterControlError("MISSION_NODE_CURRENT_REALITY_REQUIRED")
        if not latest.ready:
            raise CenterControlError("MISSION_NODE_CURRENT_REALITY_BLOCKED")
        if latest.snapshot_id != binding.reality_snapshot_id or latest.fingerprint != binding.reality_fingerprint:
            raise CenterControlError("MISSION_NODE_STALE_REALITY_BINDING")

    def _latest_required_stages(
        self,
        node: MissionNodeInstance,
        required: Sequence[MissionStageType],
    ) -> Tuple[StageInstance, ...]:
        all_stages = [
            stage
            for stage in self.governance_repository.list_stages(node.test_run_id)
            if stage.scope_version == node.scope_version
        ]
        result: List[StageInstance] = []
        for stage_type in required:
            candidates = [stage for stage in all_stages if stage.stage_type == stage_type.value]
            if not candidates:
                raise CenterControlError("MISSION_NODE_REQUIRED_STAGE_MISSING:%s" % stage_type.value)
            latest = sorted(candidates, key=lambda stage: stage.attempt_no)[-1]
            if latest.state != StageState.COMPLETED:
                raise CenterControlError(
                    "MISSION_NODE_LATEST_STAGE_NOT_COMPLETED:%s:%s" % (stage_type.value, latest.state.value)
                )
            if stage_type not in _SUFFICIENCY_STAGE_TYPES and not latest.output_refs:
                raise CenterControlError("MISSION_NODE_ACTIVITY_STAGE_EVIDENCE_MISSING:%s" % stage_type.value)
            result.append(latest)
        return tuple(result)

    def _authoritative_sufficiency(
        self,
        node: MissionNodeInstance,
        stages: Sequence[StageInstance],
    ) -> Tuple[SufficiencyEvaluation, ...]:
        evaluations = self.governance_repository.list_evaluations(node.test_run_id)
        result: List[SufficiencyEvaluation] = []
        for stage in stages:
            stage_type = MissionStageType(stage.stage_type)
            if stage_type not in _SUFFICIENCY_STAGE_TYPES:
                continue
            candidates = [value for value in evaluations if value.subject_id == stage.stage_instance_id]
            if not candidates:
                raise CenterControlError("MISSION_NODE_SUFFICIENCY_EVALUATION_MISSING:%s" % stage_type.value)
            latest = sorted(candidates, key=lambda value: value.evaluated_at)[-1]
            if latest.result != SufficiencyResult.SUFFICIENT:
                raise CenterControlError("MISSION_NODE_SUFFICIENCY_NOT_GREEN:%s" % stage_type.value)
            if not is_center_authoritative_sufficient_evaluation(latest):
                raise CenterControlError("MISSION_NODE_SUFFICIENCY_NOT_CENTER_AUTHORITATIVE:%s" % stage_type.value)
            result.append(latest)
        return tuple(result)

    @staticmethod
    def _required(value: str, name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise CenterControlError("%s_REQUIRED" % name.upper())
        return value.strip()
