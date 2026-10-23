"""RC7 Test Design closed loop driven by explicit Test Obligations.

RC7.1 extends the obligation vocabulary with PRECONDITION and DEPENDENCY while
reusing the proven RC6 semantic closure primitive through deterministic
coverage-kind aliases. This keeps the RC6 contract stable but prevents those
Requirement facts from disappearing from the Test Design denominator.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from rc6_runtime.coverage import (
    CoverageContractError,
    CoverageSubjectRegistry,
    DeltaDesignPlanner,
    DesignClosureEvaluator,
)
from rc6_runtime.truth import TruthRuntime

from .models import Evaluation, EvaluationResult, Gap, GapSeverity, GapStatus, Task, TaskStatus
from .state_machine import transition_gap, transition_task
from .truth_overlay import append_entity


_KIND_GAP_CATEGORY = {
    "REQUIREMENT_ASSERTION": "UNCOVERED_REQUIREMENT",
    "BUSINESS_RULE": "UNCOVERED_BUSINESS_RULE",
    "PRECONDITION": "MISSING_PRECONDITION_CASE",
    "POSITIVE_PATH": "MISSING_POSITIVE_CASE",
    "NEGATIVE_PATH": "MISSING_NEGATIVE_CASE",
    "BOUNDARY": "UNCOVERED_BOUNDARY",
    "STATE_TRANSITION": "MISSING_STATE_TRANSITION",
    "ROLE_PERMISSION": "MISSING_PERMISSION_CASE",
    "DATA_CONDITION": "MISSING_DATA_VARIANT",
    "DEPENDENCY": "MISSING_DEPENDENCY_CASE",
    "CODE_IMPACT": "UNCOVERED_CODE_BRANCH",
    "SIDE_EFFECT": "MISSING_SIDE_EFFECT_CASE",
    "REGRESSION": "MISSING_REGRESSION_CASE",
    "HIGH_RISK_HYPOTHESIS": "UNCOVERED_RISK",
}

# RC6 CoverageSubjectRegistry owns the frozen semantic vocabulary. RC7.1 keeps
# that primitive unchanged and maps the two new source-level obligation kinds to
# semantically compatible RC6 categories for coverage calculation.
_COVERAGE_KIND_ALIASES = {
    "PRECONDITION": "DATA_CONDITION",
    "DEPENDENCY": "HIGH_RISK_HYPOTHESIS",
}

_RISK_SEVERITY = {
    "CRITICAL": GapSeverity.CRITICAL,
    "HIGH": GapSeverity.HIGH,
    "MEDIUM": GapSeverity.MEDIUM,
    "LOW": GapSeverity.LOW,
}


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


@dataclass(frozen=True)
class TestObligation:
    obligation_id: str
    kind: str
    layer: str
    risk: str
    evidence_refs: Tuple[str, ...]
    required: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.obligation_id, str) or not self.obligation_id.strip():
            raise ValueError("TEST_OBLIGATION_ID_REQUIRED")
        if not isinstance(self.evidence_refs, tuple) or not self.evidence_refs:
            raise ValueError("TEST_OBLIGATION_EVIDENCE_REQUIRED")

    def as_coverage_subject(self) -> Dict[str, Any]:
        kind = str(self.kind).upper()
        return {
            "subject_id": self.obligation_id,
            "kind": _COVERAGE_KIND_ALIASES.get(kind, kind),
            "layer": self.layer,
            "risk": self.risk,
            "required": self.required,
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True)
class TestDesignLoopResult:
    evaluation: Evaluation
    gaps: Tuple[Gap, ...]
    delta_requests: Tuple[Dict[str, Any], ...]
    semantic_coverage: float
    case_count: int


class TestDesignClosedLoop:
    def __init__(self) -> None:
        self._evaluator = DesignClosureEvaluator()
        self._delta = DeltaDesignPlanner()

    def evaluate(
        self,
        *,
        mission_id: str,
        artifact_ref: str,
        obligations: Iterable[TestObligation],
        cases: Iterable[Dict[str, Any]],
        evaluator_ref: str = "rc6-semantic-design-closure-evaluator",
    ) -> TestDesignLoopResult:
        obligation_list = list(obligations)
        case_list = list(cases)
        registry = CoverageSubjectRegistry([item.as_coverage_subject() for item in obligation_list])
        by_id = {item.obligation_id: item for item in obligation_list}

        try:
            closure = self._evaluator.evaluate(registry, case_list)
        except CoverageContractError as exc:
            gap = Gap(
                gap_id=_stable_id("GAP-TD", mission_id, artifact_ref, "SCHEMA", str(exc)),
                mission_id=mission_id,
                source_node="TEST_DESIGN",
                category="TEST_DESIGN_SCHEMA_INVALID",
                severity=GapSeverity.BLOCKER,
                target_node="TEST_DESIGN",
                description=str(exc),
                subject_refs=[artifact_ref],
                acceptance_criteria=["test design candidate satisfies semantic closure contract"],
            )
            evaluation = Evaluation(
                evaluation_id=_stable_id("EVAL-TD", mission_id, artifact_ref, "INVALID", str(exc)),
                mission_id=mission_id,
                node="TEST_DESIGN",
                artifact_refs=[artifact_ref],
                result=EvaluationResult.REPAIR_REQUIRED,
                evaluator_ref=evaluator_ref,
                dimensions={"gate_status": "INVALID_ARTIFACT_SCHEMA", "reason": str(exc)},
                gap_refs=[gap.gap_id],
            )
            return TestDesignLoopResult(evaluation, (gap,), (), 0.0, len(case_list))

        gaps: List[Gap] = []
        for obligation_id in closure.uncovered_subject_ids:
            obligation = by_id[obligation_id]
            category = _KIND_GAP_CATEGORY.get(obligation.kind.upper(), "UNCOVERED_TEST_OBLIGATION")
            gaps.append(
                Gap(
                    gap_id=_stable_id("GAP-TD", mission_id, obligation_id, category),
                    mission_id=mission_id,
                    source_node="TEST_DESIGN",
                    category=category,
                    severity=_RISK_SEVERITY.get(obligation.risk.upper(), GapSeverity.HIGH),
                    target_node="TEST_DESIGN",
                    description="UNCOVERED_TEST_OBLIGATION:%s" % obligation_id,
                    subject_refs=[artifact_ref, obligation_id],
                    evidence_refs=list(obligation.evidence_refs),
                    acceptance_criteria=["obligation %s has at least one valid case coverage link" % obligation_id],
                )
            )

        for tc_id in closure.oracle_gap_case_ids:
            gaps.append(
                Gap(
                    gap_id=_stable_id("GAP-TD", mission_id, tc_id, "ORACLE_INCOMPLETE"),
                    mission_id=mission_id,
                    source_node="TEST_DESIGN",
                    category="ORACLE_INCOMPLETE",
                    severity=GapSeverity.HIGH,
                    target_node="TEST_DESIGN",
                    description="ORACLE_INCOMPLETE:%s" % tc_id,
                    subject_refs=[artifact_ref, tc_id],
                    acceptance_criteria=["case %s satisfies layer/risk/action Oracle policy" % tc_id],
                )
            )

        for invalid_link in closure.metrics.get("invalid_coverage_links", []):
            gaps.append(
                Gap(
                    gap_id=_stable_id("GAP-TD", mission_id, str(invalid_link), "TRACEABILITY"),
                    mission_id=mission_id,
                    source_node="TEST_DESIGN",
                    category="TEST_DESIGN_TRACEABILITY_INVALID",
                    severity=GapSeverity.HIGH,
                    target_node="TEST_DESIGN",
                    description="INVALID_COVERAGE_LINK:%s" % invalid_link,
                    subject_refs=[artifact_ref, str(invalid_link)],
                    acceptance_criteria=["case coverage link resolves to a same-layer obligation with evidence"],
                )
            )

        delta_requests = tuple(
            {
                "layer": request.layer,
                "obligation_ids": list(request.subject_ids),
                "obligation_refs": list(request.subject_refs),
                "reason": request.reason,
            }
            for request in self._delta.plan(registry, closure)
        )
        result = EvaluationResult.PASS if closure.passed else EvaluationResult.REPAIR_REQUIRED
        evaluation = Evaluation(
            evaluation_id=_stable_id(
                "EVAL-TD",
                mission_id,
                artifact_ref,
                result.value,
                ",".join(sorted(gap.gap_id for gap in gaps)),
            ),
            mission_id=mission_id,
            node="TEST_DESIGN",
            artifact_refs=[artifact_ref],
            result=result,
            evaluator_ref=evaluator_ref,
            dimensions={
                "gate_status": closure.status,
                "metrics": closure.metrics,
                "uncovered_obligation_ids": list(closure.uncovered_subject_ids),
                "critical_high_gap_ids": list(closure.critical_high_gap_ids),
                "oracle_gap_case_ids": list(closure.oracle_gap_case_ids),
                "delta_requests": list(delta_requests),
            },
            gap_refs=[gap.gap_id for gap in gaps],
        )
        return TestDesignLoopResult(
            evaluation=evaluation,
            gaps=tuple(gaps),
            delta_requests=delta_requests,
            semantic_coverage=float(closure.metrics["semantic_coverage"]),
            case_count=int(closure.metrics["case_count"]),
        )

    @staticmethod
    def accept_candidate(task: Task, result: TestDesignLoopResult) -> Task:
        if task.state != TaskStatus.OUTPUT_PRODUCED:
            raise RuntimeError("TEST_DESIGN_CANDIDATE_OUTPUT_REQUIRED")
        transition_task(task, TaskStatus.EVALUATING)
        if result.evaluation.result == EvaluationResult.PASS:
            return transition_task(task, TaskStatus.PASS, evaluation_id=result.evaluation.evaluation_id)
        return transition_task(
            task,
            TaskStatus.REPAIR_REQUIRED,
            evaluation_id=result.evaluation.evaluation_id,
        )

    @staticmethod
    def resolve_repaired_gaps(prior_gaps: Sequence[Gap], result: TestDesignLoopResult) -> Tuple[Gap, ...]:
        current_gap_ids = {gap.gap_id for gap in result.gaps}
        resolved = []
        for gap in prior_gaps:
            if gap.gap_id in current_gap_ids:
                continue
            if gap.state != GapStatus.EVIDENCE_PENDING:
                raise RuntimeError("REPAIRED_GAP_MUST_BE_EVIDENCE_PENDING")
            transition_gap(
                gap,
                GapStatus.RESOLVED,
                resolution_evaluation_id=result.evaluation.evaluation_id,
            )
            resolved.append(gap)
        return tuple(resolved)

    @staticmethod
    def persist(
        truth: TruthRuntime,
        *,
        release_id: str,
        result: TestDesignLoopResult,
        evaluation_version: int = 1,
        gap_version: int = 1,
    ) -> Sequence[Any]:
        receipts = [
            append_entity(
                truth,
                result.evaluation,
                release_id=release_id,
                artifact_version=evaluation_version,
            )
        ]
        for gap in result.gaps:
            receipts.append(
                append_entity(truth, gap, release_id=release_id, artifact_version=gap_version)
            )
        return receipts

    @staticmethod
    def persist_gap_updates(
        truth: TruthRuntime,
        *,
        release_id: str,
        gaps: Sequence[Gap],
        artifact_version: int,
    ) -> Sequence[Any]:
        return [
            append_entity(
                truth,
                gap,
                release_id=release_id,
                artifact_version=artifact_version,
            )
            for gap in gaps
        ]