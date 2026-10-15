"""Parent-aware RC7 DSH Test Design evaluator.

This is the canonical RC7 DSH Test Design acceptance adapter. It composes the
independent reviewer / semantic closure evaluator with deterministic guards:
(1) the Designer cannot choose a small self-authored obligation denominator;
(2) a semantically covered case cannot PASS if it is unusable by downstream
Script/Preparation/Execution Runtime. Script and Execution workers must never
invent missing preconditions, data construction, cleanup, steps or oracles.
"""

from __future__ import annotations

import hashlib
from typing import Dict, List, Sequence

from rc6_runtime.preparation import CLEANUP_MODES, PRECONDITION_TYPES, STRATEGY_ORDER

from .closed_loop_control import ClosedLoopControlPlane
from .dsh_test_design_evaluator import (
    DshTestDesignEvaluation,
    DshTestDesignEvaluator as _BaseDshTestDesignEvaluator,
)
from .models import Evaluation, EvaluationResult, Gap, GapSeverity
from .test_design_loop import TestDesignLoopResult
from .test_obligation_inventory import (
    MandatoryObligationSource,
    ParentDerivedTestObligationInventory,
)


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


def _text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _preconditions_ready(value) -> bool:
    if not isinstance(value, list):
        return False
    seen = set()
    for item in value:
        if not isinstance(item, dict):
            return False
        pid = item.get("id")
        ptype = str(item.get("type") or "").upper()
        requirement = item.get("requirement")
        if not _text(pid) or pid in seen or ptype not in PRECONDITION_TYPES or not _text(requirement):
            return False
        seen.add(pid)
    return True


def _data_requirement_ready(item) -> bool:
    if not isinstance(item, dict) or not _text(item.get("id")):
        return False
    selectors = item.get("selectors")
    if not isinstance(selectors, dict) or not selectors:
        return False
    strategies = item.get("allowed_strategies")
    if not isinstance(strategies, list) or not strategies:
        return False
    normalized = [str(value).upper() for value in strategies]
    return all(value in STRATEGY_ORDER for value in normalized)


def _test_data_ready(value) -> bool:
    if not isinstance(value, dict):
        return False
    initial = value.get("initial_state")
    inputs = value.get("input_data")
    cleanup = value.get("cleanup_policy")
    if not isinstance(initial, list) or not isinstance(inputs, list):
        return False
    requirements = list(initial) + list(inputs)
    if any(not _data_requirement_ready(item) for item in requirements):
        return False
    ids = [item["id"] for item in requirements]
    if len(ids) != len(set(ids)):
        return False
    if not isinstance(cleanup, dict) or str(cleanup.get("mode") or "").upper() not in CLEANUP_MODES:
        return False
    return True


def _cleanup_consistent(case: Dict[str, object]) -> bool:
    top = case.get("cleanup_policy")
    test_data = case.get("test_data")
    if not isinstance(top, dict) or not isinstance(test_data, dict):
        return False
    nested = test_data.get("cleanup_policy")
    if not isinstance(nested, dict):
        return False
    left = dict(top)
    right = dict(nested)
    left["mode"] = str(left.get("mode") or "").upper()
    right["mode"] = str(right.get("mode") or "").upper()
    return left == right and left["mode"] in CLEANUP_MODES


class DshParentAwareTestDesignEvaluator(_BaseDshTestDesignEvaluator):
    """Add parent-truth and downstream execution-contract guards."""

    def __init__(self, launcher, *, reviewer_allowed_tools=None) -> None:
        if reviewer_allowed_tools is None:
            super().__init__(launcher)
        else:
            super().__init__(launcher, reviewer_allowed_tools=reviewer_allowed_tools)
        self.parent_inventory = ParentDerivedTestObligationInventory()

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
        sources = self.parent_inventory.derive(
            control.truth,
            mission_id=control.mission_id,
            parent_artifact_refs=task.input_artifact_refs,
        )
        missing = self.parent_inventory.missing_reasons(
            sources,
            candidate.semantic_payload.get("obligations"),
        )
        case_reasons = self._execution_case_reasons(candidate.semantic_payload.get("cases"))

        evaluated = super().evaluate(control, task_id, artifact_id)
        guarded = self._apply_guards(
            control,
            artifact_id=artifact_id,
            base=evaluated.loop_result,
            sources=sources,
            missing=missing,
            case_reasons=case_reasons,
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
    def _execution_case_reasons(raw_cases) -> Sequence[str]:
        if not isinstance(raw_cases, list) or not raw_cases:
            return ("TEST_CASES_REQUIRED_FOR_EXECUTION",)
        reasons = []
        for index, case in enumerate(raw_cases):
            if not isinstance(case, dict):
                reasons.append("CASE[%d]:NOT_OBJECT" % index)
                continue
            tc_id = case.get("tc_id") if _text(case.get("tc_id")) else "CASE[%d]" % index
            test_data = case.get("test_data")
            data_count = 0
            if isinstance(test_data, dict):
                initial = test_data.get("initial_state", [])
                inputs = test_data.get("input_data", [])
                if isinstance(initial, list) and isinstance(inputs, list):
                    data_count = len(initial) + len(inputs)
            refs = case.get("test_data_refs")
            refs_ok = isinstance(refs, list) and all(_text(value) for value in refs)
            if data_count and refs_ok:
                refs_ok = bool(refs)
            checks = (
                (_text(case.get("requirement_id")), "REQUIREMENT_ID_REQUIRED"),
                (_preconditions_ready(case.get("preconditions")), "STRUCTURED_PRECONDITIONS_REQUIRED"),
                (_test_data_ready(test_data), "STRUCTURED_TEST_DATA_REQUIRED"),
                (_cleanup_consistent(case), "CLEANUP_POLICY_MUST_MATCH_TEST_DATA"),
                (isinstance(case.get("steps"), list) and bool(case.get("steps")), "STEPS_REQUIRED"),
                (_text(case.get("expected")), "EXPECTED_REQUIRED"),
                (
                    isinstance(case.get("evidence_requirements"), list)
                    and bool(case.get("evidence_requirements"))
                    and all(_text(value) for value in case.get("evidence_requirements", [])),
                    "EVIDENCE_REQUIREMENTS_REQUIRED",
                ),
                (refs_ok, "TEST_DATA_REFS_INVALID"),
                (
                    isinstance(case.get("oracle_refs"), list)
                    and bool(case.get("oracle_refs"))
                    and all(_text(value) for value in case.get("oracle_refs", [])),
                    "ORACLE_REFS_REQUIRED",
                ),
                (
                    _text(case.get("runner_type"))
                    and str(case.get("runner_type")).upper() in {"PYTEST", "JUNIT"},
                    "PYTEST_OR_JUNIT_RUNNER_REQUIRED",
                ),
            )
            for passed, code in checks:
                if not passed:
                    reasons.append("%s:%s" % (tc_id, code))
        return tuple(reasons)

    @staticmethod
    def _apply_guards(
        control: ClosedLoopControlPlane,
        *,
        artifact_id: str,
        base: TestDesignLoopResult,
        sources: Sequence[MandatoryObligationSource],
        missing: Sequence[str],
        case_reasons: Sequence[str],
    ) -> TestDesignLoopResult:
        dimensions = dict(base.evaluation.dimensions)
        dimensions["parent_obligation_source_total"] = len(sources)
        dimensions["parent_obligation_missing_total"] = len(missing)
        dimensions["missing_parent_obligation_sources"] = list(missing)
        dimensions["parent_obligation_coverage"] = "PASS" if not missing else "GAPS"
        dimensions["execution_contract_case_gap_total"] = len(case_reasons)
        dimensions["execution_contract_case_gaps"] = list(case_reasons)
        dimensions["execution_contract_ready"] = not case_reasons

        if not missing and not case_reasons:
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

        by_reason: Dict[str, MandatoryObligationSource] = {
            "SOURCE_OBLIGATION_MISSING:%s:%s" % (source.kind, source.source_id): source
            for source in sources
        }
        extra_gaps: List[Gap] = []
        for reason in sorted(set(missing)):
            source = by_reason.get(reason)
            subject_refs = [artifact_id]
            evidence_refs = list(base.evaluation.evidence_refs)
            if source is not None:
                subject_refs.extend([source.parent_artifact_id, source.source_id])
                rows = control.truth.query("rc7_artifact", artifact_id=source.parent_artifact_id)
                if rows:
                    refs = rows[0].get("evidence_refs", [])
                    if isinstance(refs, list):
                        evidence_refs.extend(str(ref) for ref in refs if isinstance(ref, str) and ref)
            extra_gaps.append(
                Gap(
                    gap_id=_stable_id("GAP-TD-PARENT", control.mission_id, artifact_id, reason),
                    mission_id=control.mission_id,
                    source_node="TEST_DESIGN",
                    category="TEST_DESIGN_SOURCE_OBLIGATION_GAP",
                    severity=GapSeverity.HIGH,
                    target_node="TEST_DESIGN",
                    description=reason,
                    subject_refs=list(dict.fromkeys(subject_refs)),
                    evidence_refs=list(dict.fromkeys(evidence_refs)),
                    acceptance_criteria=[
                        "every parent-derived requirement/code source is represented by a same-kind Test Obligation source_ref"
                    ],
                )
            )
        for reason in sorted(set(case_reasons)):
            extra_gaps.append(
                Gap(
                    gap_id=_stable_id("GAP-TD-EXEC", control.mission_id, artifact_id, reason),
                    mission_id=control.mission_id,
                    source_node="TEST_DESIGN",
                    category="TEST_CASE_DEFECT",
                    severity=GapSeverity.HIGH,
                    target_node="TEST_DESIGN",
                    description="EXECUTION_CONTRACT_CASE_GAP:%s" % reason,
                    subject_refs=[artifact_id, reason.split(":", 1)[0]],
                    evidence_refs=list(base.evaluation.evidence_refs),
                    acceptance_criteria=[
                        "TestCase carries structured preconditions, deterministic data construction, steps, expected/oracle refs, evidence requirements, one cleanup policy and PYTEST/JUNIT runner"
                    ],
                )
            )

        gaps = tuple(list(base.gaps) + extra_gaps)
        evaluation = Evaluation(
            evaluation_id=_stable_id(
                "EVAL-TD-GUARDED",
                control.mission_id,
                artifact_id,
                base.evaluation.evaluation_id,
                ",".join(sorted(set(list(missing) + list(case_reasons)))),
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
