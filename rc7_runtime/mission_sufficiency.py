"""RC7 Mission Test Sufficiency / residual-risk / report gate.

Workflow completion is not Mission completion.  This evaluator consumes an
explicit evidence snapshot and applies deterministic hard gates.  Release
recommendation is deliberately separate from technical test sufficiency, and a
final report projection is legal only after Mission CONVERGED.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence, Tuple

from .models import Evaluation, EvaluationResult, Gap, GapSeverity, Mission, MissionStatus
from .state_machine import (
    ConvergenceInput,
    decide_convergence,
    transition_mission,
)


class MissionSufficiencyError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResidualRisk:
    risk_id: str
    severity: str
    description: str
    evidence_refs: Tuple[str, ...]
    disposition: str = "PENDING"
    acceptance_ref: str = ""

    def __post_init__(self) -> None:
        if not self.risk_id or not self.description or not self.evidence_refs:
            raise MissionSufficiencyError("RESIDUAL_RISK_ID_DESCRIPTION_EVIDENCE_REQUIRED")
        if self.severity.upper() not in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}:
            raise MissionSufficiencyError("RESIDUAL_RISK_SEVERITY_INVALID")
        if self.disposition.upper() not in {"PENDING", "ACCEPTED", "DEFERRED", "MONITOR"}:
            raise MissionSufficiencyError("RESIDUAL_RISK_DISPOSITION_INVALID")
        if self.disposition.upper() in {"ACCEPTED", "DEFERRED", "MONITOR"} and not self.acceptance_ref:
            raise MissionSufficiencyError("RESIDUAL_RISK_DISPOSITION_REQUIRES_REFERENCE")


@dataclass(frozen=True)
class MissionEvidenceSnapshot:
    mission_id: str
    release_id: str
    snapshot_ref: str
    evidence_refs: Tuple[str, ...]

    critical_requirements_total: int = 0
    critical_requirements_verified: int = 0
    unverified_requirement_refs: Tuple[str, ...] = ()

    critical_obligations_total: int = 0
    critical_obligations_verified: int = 0
    unverified_obligation_refs: Tuple[str, ...] = ()

    critical_branches_total: int = 0
    critical_branches_verified: int = 0
    unverified_branch_refs: Tuple[str, ...] = ()

    critical_executions_total: int = 0
    critical_executions_conclusive: int = 0
    inconclusive_execution_refs: Tuple[str, ...] = ()

    open_critical_defect_refs: Tuple[str, ...] = ()
    open_high_defect_refs: Tuple[str, ...] = ()
    pending_defect_verification_refs: Tuple[str, ...] = ()
    open_blocker_gap_refs: Tuple[str, ...] = ()
    open_critical_gap_refs: Tuple[str, ...] = ()
    external_blocker_refs: Tuple[str, ...] = ()
    residual_risks: Tuple[ResidualRisk, ...] = ()

    def __post_init__(self) -> None:
        if not self.mission_id or not self.release_id or not self.snapshot_ref or not self.evidence_refs:
            raise MissionSufficiencyError("MISSION_SNAPSHOT_ID_RELEASE_REF_EVIDENCE_REQUIRED")
        pairs = (
            ("critical_requirements", self.critical_requirements_total, self.critical_requirements_verified, self.unverified_requirement_refs),
            ("critical_obligations", self.critical_obligations_total, self.critical_obligations_verified, self.unverified_obligation_refs),
            ("critical_branches", self.critical_branches_total, self.critical_branches_verified, self.unverified_branch_refs),
            ("critical_executions", self.critical_executions_total, self.critical_executions_conclusive, self.inconclusive_execution_refs),
        )
        for name, total, verified, refs in pairs:
            if not isinstance(total, int) or not isinstance(verified, int) or total < 0 or verified < 0 or verified > total:
                raise MissionSufficiencyError("MISSION_%s_COUNTER_INVALID" % name.upper())
            if len(refs) != total - verified:
                raise MissionSufficiencyError("MISSION_%s_MISSING_REF_COUNT_MISMATCH" % name.upper())


@dataclass(frozen=True)
class MissionSufficiencyResult:
    evaluation: Evaluation
    gaps: Tuple[Gap, ...]
    sufficiency_state: str
    release_recommendation: str
    report_ready: bool


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


class MissionSufficiencyClosedLoop:
    def evaluate(
        self,
        snapshot: MissionEvidenceSnapshot,
        *,
        evaluator_ref: str = "rc7-deterministic-mission-sufficiency-gate",
    ) -> MissionSufficiencyResult:
        gaps: List[Gap] = []

        for ref in snapshot.unverified_requirement_refs:
            gaps.append(self._gap(snapshot, "CRITICAL_REQUIREMENT_NOT_VERIFIED", "EXECUTION", GapSeverity.CRITICAL, ref))
        for ref in snapshot.unverified_obligation_refs:
            gaps.append(self._gap(snapshot, "CRITICAL_OBLIGATION_NOT_VERIFIED", "EXECUTION", GapSeverity.CRITICAL, ref))
        for ref in snapshot.unverified_branch_refs:
            gaps.append(self._gap(snapshot, "CRITICAL_BRANCH_UNVERIFIED", "EXECUTION", GapSeverity.CRITICAL, ref))
        for ref in snapshot.inconclusive_execution_refs:
            gaps.append(self._gap(snapshot, "INCONCLUSIVE_RESULT_GAP", "EXECUTION", GapSeverity.CRITICAL, ref))
        for ref in snapshot.open_critical_defect_refs:
            gaps.append(self._gap(snapshot, "OPEN_CRITICAL_DEFECT", "DEFECT", GapSeverity.CRITICAL, ref))
        for ref in snapshot.open_high_defect_refs:
            gaps.append(self._gap(snapshot, "OPEN_HIGH_DEFECT", "DEFECT", GapSeverity.HIGH, ref))
        for ref in snapshot.pending_defect_verification_refs:
            gaps.append(self._gap(snapshot, "DEFECT_VERIFICATION_PENDING", "DEFECT", GapSeverity.HIGH, ref))
        for ref in snapshot.open_blocker_gap_refs:
            gaps.append(self._gap(snapshot, "MISSION_BLOCKING_GAP", "RUNTIME", GapSeverity.BLOCKER, ref))
        for ref in snapshot.open_critical_gap_refs:
            gaps.append(self._gap(snapshot, "MISSION_BLOCKING_GAP", "RUNTIME", GapSeverity.CRITICAL, ref))

        external_blocker_gaps = [
            self._gap(snapshot, "MISSION_BLOCKING_GAP", "RUNTIME", GapSeverity.BLOCKER, ref)
            for ref in snapshot.external_blocker_refs
        ]
        gaps.extend(external_blocker_gaps)

        pending_risk_gaps = []
        for risk in snapshot.residual_risks:
            if risk.disposition.upper() == "PENDING":
                severity = GapSeverity.CRITICAL if risk.severity.upper() == "CRITICAL" else GapSeverity.HIGH
                pending_risk_gaps.append(
                    Gap(
                        gap_id=_stable_id("GAP-MISSION", snapshot.mission_id, risk.risk_id, "RISK_ACCEPTANCE"),
                        mission_id=snapshot.mission_id,
                        source_node="MISSION_EVALUATION",
                        category="RESIDUAL_RISK_REQUIRES_ACCEPTANCE",
                        severity=severity,
                        target_node="HUMAN_GATE",
                        description=risk.description,
                        subject_refs=[risk.risk_id, snapshot.snapshot_ref],
                        evidence_refs=list(risk.evidence_refs),
                        acceptance_criteria=["residual risk has explicit disposition and acceptance reference"],
                    )
                )
        gaps.extend(pending_risk_gaps)

        non_external_non_risk = [
            gap for gap in gaps
            if gap not in external_blocker_gaps and gap not in pending_risk_gaps
        ]
        if non_external_non_risk:
            result = EvaluationResult.REPAIR_REQUIRED
            sufficiency = "NOT_SUFFICIENT"
            recommendation = "NOT_RECOMMENDED"
        elif external_blocker_gaps:
            result = EvaluationResult.BLOCKED
            sufficiency = "BLOCKED"
            recommendation = "BLOCKED"
        elif pending_risk_gaps:
            result = EvaluationResult.HUMAN_REQUIRED
            sufficiency = "RISK_ACCEPTANCE_REQUIRED"
            recommendation = "RISK_ACCEPTANCE_REQUIRED"
        else:
            result = EvaluationResult.PASS
            if snapshot.residual_risks:
                sufficiency = "SUFFICIENT_WITH_RESIDUAL_RISK"
                recommendation = "CONDITIONAL"
            else:
                sufficiency = "SUFFICIENT"
                recommendation = "RECOMMENDED"

        metrics = {
            "critical_requirement_verified": self._ratio(snapshot.critical_requirements_verified, snapshot.critical_requirements_total),
            "critical_obligation_verified": self._ratio(snapshot.critical_obligations_verified, snapshot.critical_obligations_total),
            "critical_branch_verified": self._ratio(snapshot.critical_branches_verified, snapshot.critical_branches_total),
            "critical_execution_conclusive": self._ratio(snapshot.critical_executions_conclusive, snapshot.critical_executions_total),
            "open_critical_defects": len(snapshot.open_critical_defect_refs),
            "open_high_defects": len(snapshot.open_high_defect_refs),
            "pending_defect_verifications": len(snapshot.pending_defect_verification_refs),
            "open_blocker_gaps": len(snapshot.open_blocker_gap_refs) + len(snapshot.external_blocker_refs),
            "open_critical_gaps": len(snapshot.open_critical_gap_refs),
            "residual_risks": len(snapshot.residual_risks),
            "residual_risks_pending_acceptance": len(pending_risk_gaps),
        }
        evaluation = Evaluation(
            evaluation_id=_stable_id(
                "EVAL-MISSION",
                snapshot.mission_id,
                snapshot.snapshot_ref,
                result.value,
                sufficiency,
                ",".join(sorted(gap.gap_id for gap in gaps)),
            ),
            mission_id=snapshot.mission_id,
            node="MISSION_EVALUATION",
            artifact_refs=[snapshot.snapshot_ref],
            result=result,
            evaluator_ref=evaluator_ref,
            dimensions={
                "sufficiency_state": sufficiency,
                "release_recommendation": recommendation,
                "metrics": metrics,
                "report_ready": result == EvaluationResult.PASS,
            },
            gap_refs=[gap.gap_id for gap in gaps],
            evidence_refs=list(snapshot.evidence_refs),
        )
        return MissionSufficiencyResult(
            evaluation=evaluation,
            gaps=tuple(gaps),
            sufficiency_state=sufficiency,
            release_recommendation=recommendation,
            report_ready=(result == EvaluationResult.PASS),
        )

    def apply_to_mission(
        self,
        mission: Mission,
        snapshot: MissionEvidenceSnapshot,
        result: MissionSufficiencyResult,
    ) -> Mission:
        if mission.mission_id != snapshot.mission_id:
            raise MissionSufficiencyError("MISSION_SNAPSHOT_ID_MISMATCH")
        if mission.state != MissionStatus.EVALUATING:
            raise MissionSufficiencyError("MISSION_MUST_BE_EVALUATING")
        mission.latest_evaluation_id = result.evaluation.evaluation_id
        mission.open_gap_ids = [gap.gap_id for gap in result.gaps]
        mission.residual_risk_ids = [risk.risk_id for risk in snapshot.residual_risks]

        if result.evaluation.result == EvaluationResult.PASS:
            convergence = decide_convergence(
                ConvergenceInput(
                    mission_sufficiency_result=EvaluationResult.PASS,
                    open_critical_gaps=0,
                    open_blocking_gaps=0,
                    pending_defect_verifications=0,
                    residual_risks_pending_acceptance=0,
                )
            )
            transition_mission(
                mission,
                MissionStatus.CONVERGED,
                convergence=convergence,
                evaluation_id=result.evaluation.evaluation_id,
            )
            mission.sufficiency_state = result.sufficiency_state
            return mission
        if result.evaluation.result == EvaluationResult.HUMAN_REQUIRED:
            mission.sufficiency_state = result.sufficiency_state
            return transition_mission(mission, MissionStatus.WAITING_HUMAN)
        if result.evaluation.result == EvaluationResult.BLOCKED:
            mission.sufficiency_state = result.sufficiency_state
            return transition_mission(mission, MissionStatus.BLOCKED)
        mission.sufficiency_state = result.sufficiency_state
        return transition_mission(mission, MissionStatus.REPAIRING)

    @staticmethod
    def build_final_report_projection(
        mission: Mission,
        snapshot: MissionEvidenceSnapshot,
        result: MissionSufficiencyResult,
    ) -> Dict[str, Any]:
        if mission.state != MissionStatus.CONVERGED or not result.report_ready:
            raise MissionSufficiencyError("FINAL_REPORT_REQUIRES_CONVERGED_MISSION")
        return {
            "mission_id": mission.mission_id,
            "release_id": snapshot.release_id,
            "source": "R1_EVENT_STREAM_PROJECTION",
            "mission_evaluation_id": result.evaluation.evaluation_id,
            "test_sufficiency": result.sufficiency_state,
            "release_recommendation": result.release_recommendation,
            "metrics": result.evaluation.dimensions["metrics"],
            "residual_risks": [
                {
                    "risk_id": risk.risk_id,
                    "severity": risk.severity,
                    "description": risk.description,
                    "disposition": risk.disposition,
                    "acceptance_ref": risk.acceptance_ref,
                    "evidence_refs": list(risk.evidence_refs),
                }
                for risk in snapshot.residual_risks
            ],
        }

    @staticmethod
    def _ratio(value: int, total: int) -> float:
        return 1.0 if total == 0 else float(value) / float(total)

    @staticmethod
    def _gap(
        snapshot: MissionEvidenceSnapshot,
        category: str,
        target: str,
        severity: GapSeverity,
        subject_ref: str,
    ) -> Gap:
        return Gap(
            gap_id=_stable_id("GAP-MISSION", snapshot.mission_id, category, subject_ref),
            mission_id=snapshot.mission_id,
            source_node="MISSION_EVALUATION",
            category=category,
            severity=severity,
            target_node=target,
            description="%s:%s" % (category, subject_ref),
            subject_refs=[subject_ref, snapshot.snapshot_ref],
            evidence_refs=list(snapshot.evidence_refs),
            acceptance_criteria=["mission hard gate no longer reports %s" % category],
        )
