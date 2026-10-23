"""RC7 code-analysis closed-loop adapter.

RC7.1 composes the existing evidence-backed Code gate with deterministic impact-
surface accountability so a real CodeGraph call cannot PASS while downstream
impact inventory is still shallow or silently missing.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Dict, List, Sequence, Tuple

from rc6_runtime.intelligence import CodeSufficiencyEvaluator
from rc6_runtime.truth import TruthRuntime

from .code_sufficiency_v2 import CodeSufficiencyV2
from .models import Evaluation, EvaluationResult, Gap, GapSeverity, GapStatus, Task, TaskStatus
from .state_machine import transition_gap, transition_task
from .truth_overlay import append_entity


_REASON_POLICY = {
    "CODE_INVALID_REQUIREMENT_IDS": ("REQUIREMENT_MAPPING_INVALID", GapSeverity.CRITICAL, "CODE_ANALYSIS"),
    "CODE_EVIDENCE_MISSING": ("CODE_EVIDENCE_MISSING", GapSeverity.CRITICAL, "CODE_ANALYSIS"),
    "CODE_CHANGESET_EMPTY": ("CHANGESET_MISSING", GapSeverity.CRITICAL, "CODE_ANALYSIS"),
    "CODE_SOURCE_REVISION_MISSING": ("SOURCE_REVISION_MISSING", GapSeverity.CRITICAL, "CODE_ANALYSIS"),
    "CODE_UNEXPLAINED_CHANGE": ("CHANGED_SYMBOL_UNANALYZED", GapSeverity.HIGH, "CODE_ANALYSIS"),
    "CODE_REVERSE_MAPPING_GAP": ("REQUIREMENT_MAPPING_MISSING", GapSeverity.HIGH, "CODE_ANALYSIS"),
    "CODEGRAPH_REAL_TOOL_EVIDENCE_MISSING": ("CODEGRAPH_INCOMPLETE", GapSeverity.HIGH, "CODE_ANALYSIS"),
    "GIT_REAL_TOOL_EVIDENCE_MISSING": ("GIT_EVIDENCE_MISSING", GapSeverity.CRITICAL, "CODE_ANALYSIS"),
    "REVIEW_INDEPENDENCE_FAIL": ("EVALUATOR_INDEPENDENCE_FAIL", GapSeverity.BLOCKER, "RUNTIME"),
    "REVIEW_MISSING": ("INDEPENDENT_EVALUATION_MISSING", GapSeverity.BLOCKER, "RUNTIME"),
    "REVIEW_EVIDENCE_MISSING": ("EVALUATION_EVIDENCE_MISSING", GapSeverity.CRITICAL, "CODE_ANALYSIS"),
    "REVIEW_OPEN_GAPS": ("CODE_REVIEW_GAP", GapSeverity.HIGH, "CODE_ANALYSIS"),
}


def _reason_policy(reason: str):
    if reason.startswith("CODE_IMPACT_SURFACE_INVALID:") or reason == "CODE_IMPACT_SURFACES_INVALID":
        return "CODE_IMPACT_SURFACE_INVALID", GapSeverity.HIGH, "CODE_ANALYSIS"
    if reason.startswith("CODE_IMPACT_EXCLUSION_INVALID:") or reason == "CODE_IMPACT_EXCLUSIONS_INVALID":
        return "CODE_IMPACT_EXCLUSION_INVALID", GapSeverity.HIGH, "CODE_ANALYSIS"
    if reason.startswith("CODE_IMPACT_DIMENSION_EXCLUSION_INVALID:") or reason == "CODE_IMPACT_DIMENSION_EXCLUSIONS_INVALID":
        return "CODE_IMPACT_EXCLUSION_INVALID", GapSeverity.HIGH, "CODE_ANALYSIS"
    if reason.startswith("CODE_IMPACT_SYMBOL_UNACCOUNTED:"):
        return "CODE_IMPACT_SURFACE_MISSING", GapSeverity.HIGH, "CODE_ANALYSIS"
    if reason.startswith("CODE_IMPACT_FILE_UNACCOUNTED:"):
        return "CODE_IMPACT_SURFACE_MISSING", GapSeverity.HIGH, "CODE_ANALYSIS"
    if reason.startswith("CODE_IMPACT_DIMENSION_UNACCOUNTED:"):
        return "CODE_IMPACT_DIMENSION_UNACCOUNTED", GapSeverity.HIGH, "CODE_ANALYSIS"
    if reason.startswith("CODE_IMPACT_DIMENSION_CONFLICT:"):
        return "CODE_IMPACT_DIMENSION_CONFLICT", GapSeverity.HIGH, "CODE_ANALYSIS"
    return _REASON_POLICY.get(
        reason,
        ("CODE_SUFFICIENCY_GAP", GapSeverity.HIGH, "CODE_ANALYSIS"),
    )


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


def _evidence_refs(analysis: Dict[str, Any], review: Dict[str, Any]) -> List[str]:
    refs: List[str] = []
    for source in (analysis.get("evidence_refs", []), review.get("evidence_refs", [])):
        if not isinstance(source, list):
            continue
        for ref in source:
            if isinstance(ref, str) and ref.strip() and ref.strip() not in refs:
                refs.append(ref.strip())
    for call in analysis.get("tool_calls", []):
        if isinstance(call, dict):
            ref = call.get("evidence_ref")
            if isinstance(ref, str) and ref.strip() and ref.strip() not in refs:
                refs.append(ref.strip())
    return refs


@dataclass(frozen=True)
class CodeLoopResult:
    evaluation: Evaluation
    gaps: Tuple[Gap, ...]
    gate_status: str
    gate_metrics: Dict[str, Any]


class CodeAnalysisClosedLoop:
    def __init__(self) -> None:
        self._gate = CodeSufficiencyEvaluator()
        self._v2 = CodeSufficiencyV2()

    def evaluate(
        self,
        *,
        mission_id: str,
        artifact_ref: str,
        target_id: str,
        analysis: Dict[str, Any],
        review: Dict[str, Any],
        evaluator_ref: str = "rc6-evidence-backed-code-sufficiency-gate+rc7.1-impact-surface-gate",
    ) -> CodeLoopResult:
        gate = self._gate.evaluate(analysis, review, target_id=target_id)
        v2 = self._v2.evaluate(
            analysis,
            force=analysis.get("sufficiency_v2_required") is True,
        )
        combined_reasons = list(dict.fromkeys(list(gate.reasons) + list(v2.reasons)))
        combined_metrics = dict(gate.metrics)
        combined_metrics["impact_sufficiency_v2"] = dict(v2.metrics)
        gate_status = "SUFFICIENT" if not combined_reasons else "NOT_SUFFICIENT_CONTENT"

        analysis_id = str(analysis.get("analysis_id") or "unknown-analysis")
        review_id = str(review.get("review_id") or review.get("id") or "missing-review")
        evidence_refs = _evidence_refs(analysis, review)

        gaps: List[Gap] = []
        for reason in combined_reasons:
            category, severity, target = _reason_policy(reason)
            gaps.append(
                Gap(
                    gap_id=_stable_id("GAP-CODE", mission_id, analysis_id, reason),
                    mission_id=mission_id,
                    source_node="CODE_ANALYSIS",
                    category=category,
                    severity=severity,
                    target_node=target,
                    description=reason,
                    subject_refs=[artifact_ref, analysis_id, target_id],
                    evidence_refs=list(evidence_refs),
                    acceptance_criteria=["independent code sufficiency gate no longer reports %s" % reason],
                )
            )

        result = EvaluationResult.PASS if not combined_reasons else EvaluationResult.REPAIR_REQUIRED
        evaluation = Evaluation(
            evaluation_id=_stable_id(
                "EVAL-CODE",
                mission_id,
                analysis_id,
                review_id,
                target_id,
                result.value,
                ",".join(sorted(combined_reasons)),
            ),
            mission_id=mission_id,
            node="CODE_ANALYSIS",
            artifact_refs=[artifact_ref],
            result=result,
            evaluator_ref=evaluator_ref,
            dimensions={
                "gate_status": gate_status,
                "metrics": combined_metrics,
                "reasons": list(combined_reasons),
                "target_id": target_id,
                "code_impact_sufficiency_v2_ready": v2.passed,
            },
            gap_refs=[gap.gap_id for gap in gaps],
            evidence_refs=evidence_refs,
        )
        return CodeLoopResult(
            evaluation=evaluation,
            gaps=tuple(gaps),
            gate_status=gate_status,
            gate_metrics=combined_metrics,
        )

    @staticmethod
    def accept_candidate(task: Task, result: CodeLoopResult) -> Task:
        if task.state != TaskStatus.OUTPUT_PRODUCED:
            raise RuntimeError("CODE_CANDIDATE_OUTPUT_REQUIRED")
        transition_task(task, TaskStatus.EVALUATING)
        if result.evaluation.result == EvaluationResult.PASS:
            return transition_task(task, TaskStatus.PASS, evaluation_id=result.evaluation.evaluation_id)
        return transition_task(
            task,
            TaskStatus.REPAIR_REQUIRED,
            evaluation_id=result.evaluation.evaluation_id,
        )

    @staticmethod
    def resolve_repaired_gaps(prior_gaps: Sequence[Gap], result: CodeLoopResult) -> Tuple[Gap, ...]:
        current_reasons = set(result.evaluation.dimensions.get("reasons", []))
        resolved = []
        for gap in prior_gaps:
            if gap.description in current_reasons:
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
        result: CodeLoopResult,
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