"""Final RC7 Test Design guards for executable Oracles and RC7.1 sufficiency."""

from __future__ import annotations

import hashlib
from typing import Dict, List, Sequence

from .closed_loop_control import ClosedLoopControlPlane
from .dsh_test_design_evaluator import DshTestDesignEvaluation
from .dsh_test_design_parent_evaluator import DshParentAwareTestDesignEvaluator
from .models import Evaluation, EvaluationResult, Gap, GapSeverity
from .oracle_runtime import DeterministicOracleError, DeterministicOracleRuntime
from .test_design_loop import TestDesignLoopResult
from .test_design_sufficiency_v2 import SufficiencyV2Result, TestDesignSufficiencyV2


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


class DshExecutionReadyTestDesignEvaluator(DshParentAwareTestDesignEvaluator):
    """Parent/case guards plus deterministic Oracle and sufficiency-v2 gates."""

    def evaluate(
        self,
        control: ClosedLoopControlPlane,
        task_id: str,
        artifact_id: str,
    ) -> DshTestDesignEvaluation:
        task = control.scheduler.task(task_id)
        candidate = self.reader.load(
            control.truth,
            artifact_id,
            expected_mission_id=control.mission_id,
            expected_task_id=task_id,
        )
        oracle_reasons = self._oracle_reasons(candidate.semantic_payload.get("cases"))
        evaluated = super().evaluate(control, task_id, artifact_id)
        guarded = self._apply_oracle_guard(
            control,
            artifact_id=artifact_id,
            base=evaluated.loop_result,
            reasons=oracle_reasons,
        )
        sufficiency = TestDesignSufficiencyV2().evaluate(
            obligations=evaluated.obligations,
            cases=evaluated.cases,
        )
        guarded = self._apply_sufficiency_v2_guard(
            control,
            artifact_id=artifact_id,
            base=guarded,
            result=sufficiency,
        )
        return DshTestDesignEvaluation(
            task_id=evaluated.task_id,
            artifact_id=evaluated.artifact_id,
            designer_worker_id=evaluated.designer_worker_id,
            reviewer_worker_id=evaluated.reviewer_worker_id,
            reviewer_session_id=evaluated.reviewer_session_id,
            reviewer_evidence_ids=evaluated.reviewer_evidence_ids,
            obligations=evaluated.obligations,
            cases=evaluated.cases,
            review=evaluated.review,
            loop_result=guarded,
        )

    @staticmethod
    def _oracle_reasons(raw_cases) -> Sequence[str]:
        if not isinstance(raw_cases, list):
            return ("TEST_CASES_REQUIRED_FOR_ORACLE",)
        reasons = []
        for index, case in enumerate(raw_cases):
            if not isinstance(case, dict):
                continue
            tc_id = case.get("tc_id") if isinstance(case.get("tc_id"), str) else "CASE[%d]" % index
            try:
                DeterministicOracleRuntime.validate_contract(case.get("oracle"))
            except DeterministicOracleError as exc:
                reasons.append("%s:DETERMINISTIC_ORACLE_INVALID:%s" % (tc_id, exc))
        return tuple(reasons)

    @staticmethod
    def _apply_oracle_guard(
        control: ClosedLoopControlPlane,
        *,
        artifact_id: str,
        base: TestDesignLoopResult,
        reasons: Sequence[str],
    ) -> TestDesignLoopResult:
        dimensions = dict(base.evaluation.dimensions)
        dimensions["deterministic_oracle_gap_total"] = len(reasons)
        dimensions["deterministic_oracle_gaps"] = list(reasons)
        dimensions["deterministic_oracle_ready"] = not reasons
        if not reasons:
            evaluation = Evaluation(
                evaluation_id=base.evaluation.evaluation_id,
                mission_id=base.evaluation.mission_id,
                node=base.evaluation.node,
                artifact_refs=list(base.evaluation.artifact_refs),
                result=base.evaluation.result,
                evaluator_ref=base.evaluation.evaluator_ref,
                dimensions=dimensions,
                gap_refs=list(base.evaluation.gap_refs),
                evidence_refs=list(base.evaluation.evidence_refs),
            )
            return TestDesignLoopResult(
                evaluation=evaluation,
                gaps=base.gaps,
                delta_requests=base.delta_requests,
                semantic_coverage=base.semantic_coverage,
                case_count=base.case_count,
            )

        extra: List[Gap] = []
        for reason in sorted(set(reasons)):
            tc_id = reason.split(":", 1)[0]
            extra.append(
                Gap(
                    gap_id=_stable_id("GAP-TD-ORACLE", control.mission_id, artifact_id, reason),
                    mission_id=control.mission_id,
                    source_node="TEST_DESIGN",
                    category="ORACLE_AMBIGUOUS",
                    severity=GapSeverity.HIGH,
                    target_node="TEST_DESIGN",
                    description=reason,
                    subject_refs=[artifact_id, tc_id],
                    evidence_refs=list(base.evaluation.evidence_refs),
                    acceptance_criteria=[
                        "every Oracle check binds actual_path + deterministic operator + expected before execution"
                    ],
                )
            )
        gaps = tuple(list(base.gaps) + extra)
        evaluation = Evaluation(
            evaluation_id=_stable_id(
                "EVAL-TD-ORACLE",
                control.mission_id,
                artifact_id,
                base.evaluation.evaluation_id,
                ",".join(sorted(set(reasons))),
            ),
            mission_id=control.mission_id,
            node="TEST_DESIGN",
            artifact_refs=[artifact_id],
            result=EvaluationResult.REPAIR_REQUIRED,
            evaluator_ref=base.evaluation.evaluator_ref,
            dimensions=dimensions,
            gap_refs=[gap.gap_id for gap in gaps],
            evidence_refs=list(base.evaluation.evidence_refs),
        )
        return TestDesignLoopResult(
            evaluation=evaluation,
            gaps=gaps,
            delta_requests=base.delta_requests,
            semantic_coverage=base.semantic_coverage,
            case_count=base.case_count,
        )

    @staticmethod
    def _sufficiency_gap_policy(reason: str):
        if reason.startswith("CRITICAL_OBLIGATION_DEPTH_INSUFFICIENT:"):
            return "CRITICAL_TEST_DEPTH_INSUFFICIENT", GapSeverity.CRITICAL
        if reason.startswith("CASE_DENSITY_INSUFFICIENT:"):
            return "TEST_CASE_DENSITY_INSUFFICIENT", GapSeverity.HIGH
        if reason.startswith("CASE_OBLIGATION_CONCENTRATION_HIGH:"):
            return "TEST_CASE_CONCENTRATION_HIGH", GapSeverity.HIGH
        if reason.startswith("KIND_DIVERSITY_INSUFFICIENT:"):
            return "TEST_CASE_KIND_DIVERSITY_INSUFFICIENT", GapSeverity.HIGH
        if reason.startswith("INTERACTION_COVERAGE_MISSING:"):
            return "TEST_INTERACTION_COVERAGE_MISSING", GapSeverity.HIGH
        return "TEST_DESIGN_SUFFICIENCY_V2_GAP", GapSeverity.HIGH

    @staticmethod
    def _reason_subject(reason: str) -> str:
        parts = reason.split(":")
        if reason.startswith("CRITICAL_OBLIGATION_DEPTH_INSUFFICIENT:") and len(parts) > 1:
            return parts[1]
        if reason.startswith("CASE_OBLIGATION_CONCENTRATION_HIGH:") and len(parts) > 1:
            return parts[1]
        if reason.startswith("INTERACTION_COVERAGE_MISSING:") and len(parts) > 1:
            return parts[1]
        return reason.split(":", 1)[0]

    @classmethod
    def _apply_sufficiency_v2_guard(
        cls,
        control: ClosedLoopControlPlane,
        *,
        artifact_id: str,
        base: TestDesignLoopResult,
        result: SufficiencyV2Result,
    ) -> TestDesignLoopResult:
        dimensions = dict(base.evaluation.dimensions)
        dimensions["test_design_sufficiency_v2"] = dict(result.metrics)
        dimensions["test_design_sufficiency_v2_reasons"] = list(result.reasons)
        dimensions["test_design_sufficiency_v2_ready"] = result.passed

        if result.passed:
            evaluation = Evaluation(
                evaluation_id=base.evaluation.evaluation_id,
                mission_id=base.evaluation.mission_id,
                node=base.evaluation.node,
                artifact_refs=list(base.evaluation.artifact_refs),
                result=base.evaluation.result,
                evaluator_ref=base.evaluation.evaluator_ref,
                dimensions=dimensions,
                gap_refs=list(base.evaluation.gap_refs),
                evidence_refs=list(base.evaluation.evidence_refs),
            )
            return TestDesignLoopResult(
                evaluation=evaluation,
                gaps=base.gaps,
                delta_requests=base.delta_requests,
                semantic_coverage=base.semantic_coverage,
                case_count=base.case_count,
            )

        extra: List[Gap] = []
        for reason in result.reasons:
            category, severity = cls._sufficiency_gap_policy(reason)
            subject = cls._reason_subject(reason)
            extra.append(
                Gap(
                    gap_id=_stable_id("GAP-TD-SUF2", control.mission_id, artifact_id, reason),
                    mission_id=control.mission_id,
                    source_node="TEST_DESIGN",
                    category=category,
                    severity=severity,
                    target_node="TEST_DESIGN",
                    description=reason,
                    subject_refs=[artifact_id, subject],
                    evidence_refs=list(base.evaluation.evidence_refs),
                    acceptance_criteria=[
                        "RC7.1 Test Design Sufficiency v2 no longer reports this depth/diversity/interaction gap"
                    ],
                )
            )

        gaps = tuple(list(base.gaps) + extra)
        merged_delta = list(base.delta_requests)
        for request in result.delta_requests:
            row = dict(request)
            if row not in merged_delta:
                merged_delta.append(row)
        evaluation = Evaluation(
            evaluation_id=_stable_id(
                "EVAL-TD-SUF2",
                control.mission_id,
                artifact_id,
                base.evaluation.evaluation_id,
                ",".join(result.reasons),
            ),
            mission_id=control.mission_id,
            node="TEST_DESIGN",
            artifact_refs=[artifact_id],
            result=EvaluationResult.REPAIR_REQUIRED,
            evaluator_ref=base.evaluation.evaluator_ref,
            dimensions=dimensions,
            gap_refs=[gap.gap_id for gap in gaps],
            evidence_refs=list(base.evaluation.evidence_refs),
        )
        return TestDesignLoopResult(
            evaluation=evaluation,
            gaps=gaps,
            delta_requests=tuple(merged_delta),
            semantic_coverage=base.semantic_coverage,
            case_count=base.case_count,
        )
