"""RC7 requirement-analysis closed-loop adapter.

The semantic sufficiency predicate is inherited from the proven RC6 independent
requirement gate. RC7 adds canonical Evaluation/Gap objects and deterministic
Task acceptance semantics around that predicate.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Dict, List, Sequence, Tuple

from rc6_runtime.agent_runtime import IndependentRequirementSufficiencyGate
from rc6_runtime.truth import TruthRuntime

from .models import (
    Evaluation,
    EvaluationResult,
    Gap,
    GapSeverity,
    GapStatus,
    Task,
    TaskStatus,
)
from .state_machine import transition_gap, transition_task
from .truth_overlay import append_entity


_REASON_POLICY = {
    "REQ_BOUNDARY_RULE_MISSING": ("MISSING_BOUNDARY", GapSeverity.CRITICAL, "REQUIREMENT_ANALYSIS"),
    "REQ_TRACEABILITY_GAP": ("TRACEABILITY_MISSING", GapSeverity.HIGH, "REQUIREMENT_ANALYSIS"),
    "REQ_UNSUPPORTED_ASSERTION": ("UNTRACEABLE_FACT", GapSeverity.CRITICAL, "REQUIREMENT_ANALYSIS"),
    "REQ_TESTABILITY_GAP": ("UNTESTABLE_REQUIREMENT", GapSeverity.HIGH, "REQUIREMENT_ANALYSIS"),
    "REQ_INVALID_TRACE_LINK": ("TRACEABILITY_MISSING", GapSeverity.HIGH, "REQUIREMENT_ANALYSIS"),
    "REQ_EVIDENCE_MISSING": ("EVIDENCE_MISSING", GapSeverity.CRITICAL, "REQUIREMENT_ANALYSIS"),
    "REVIEW_INDEPENDENCE_FAIL": ("EVALUATOR_INDEPENDENCE_FAIL", GapSeverity.BLOCKER, "RUNTIME"),
    "REVIEW_MISSING": ("INDEPENDENT_EVALUATION_MISSING", GapSeverity.BLOCKER, "RUNTIME"),
    "REVIEW_EVIDENCE_MISSING": ("EVALUATION_EVIDENCE_MISSING", GapSeverity.CRITICAL, "REQUIREMENT_ANALYSIS"),
    "REVIEW_OPEN_GAPS": ("REQUIREMENT_REVIEW_GAP", GapSeverity.HIGH, "REQUIREMENT_ANALYSIS"),
}


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


def _evidence_refs(analysis: Dict[str, Any], review: Dict[str, Any]) -> List[str]:
    refs = []
    for source in (analysis.get("evidence_refs", []), review.get("evidence_refs", [])):
        if isinstance(source, list):
            for ref in source:
                if isinstance(ref, str) and ref.strip() and ref not in refs:
                    refs.append(ref.strip())
    return refs


@dataclass(frozen=True)
class RequirementLoopResult:
    evaluation: Evaluation
    gaps: Tuple[Gap, ...]
    gate_status: str
    gate_metrics: Dict[str, Any]


class RequirementClosedLoop:
    def __init__(self) -> None:
        self._gate = IndependentRequirementSufficiencyGate()

    def evaluate(
        self,
        *,
        mission_id: str,
        artifact_ref: str,
        analysis: Dict[str, Any],
        review: Dict[str, Any],
        evaluator_ref: str = "rc6-independent-requirement-sufficiency-gate",
    ) -> RequirementLoopResult:
        gate = self._gate.evaluate(analysis, review)
        analysis_id = str(analysis.get("analysis_id") or "unknown-analysis")
        review_id = str(review.get("review_id") or review.get("id") or "missing-review")
        evidence_refs = _evidence_refs(analysis, review)

        gaps: List[Gap] = []
        for reason in gate.reasons:
            category, severity, target = _REASON_POLICY.get(
                reason,
                ("REQUIREMENT_SUFFICIENCY_GAP", GapSeverity.HIGH, "REQUIREMENT_ANALYSIS"),
            )
            gaps.append(
                Gap(
                    gap_id=_stable_id("GAP-REQ", mission_id, analysis_id, reason),
                    mission_id=mission_id,
                    source_node="REQUIREMENT_ANALYSIS",
                    category=category,
                    severity=severity,
                    target_node=target,
                    description=reason,
                    subject_refs=[artifact_ref, analysis_id],
                    evidence_refs=list(evidence_refs),
                    acceptance_criteria=["independent requirement sufficiency gate no longer reports %s" % reason],
                )
            )

        result = EvaluationResult.PASS if gate.passed else EvaluationResult.REPAIR_REQUIRED
        evaluation = Evaluation(
            evaluation_id=_stable_id(
                "EVAL-REQ",
                mission_id,
                analysis_id,
                review_id,
                result.value,
                ",".join(sorted(gate.reasons)),
            ),
            mission_id=mission_id,
            node="REQUIREMENT_ANALYSIS",
            artifact_refs=[artifact_ref],
            result=result,
            evaluator_ref=evaluator_ref,
            dimensions={
                "gate_status": gate.status,
                "metrics": gate.metrics,
                "reasons": list(gate.reasons),
            },
            gap_refs=[gap.gap_id for gap in gaps],
            evidence_refs=evidence_refs,
        )
        return RequirementLoopResult(
            evaluation=evaluation,
            gaps=tuple(gaps),
            gate_status=gate.status,
            gate_metrics=dict(gate.metrics),
        )

    @staticmethod
    def accept_candidate(task: Task, result: RequirementLoopResult) -> Task:
        """Move candidate output through evaluator-owned acceptance semantics."""
        if task.state != TaskStatus.OUTPUT_PRODUCED:
            raise RuntimeError("REQUIREMENT_CANDIDATE_OUTPUT_REQUIRED")
        transition_task(task, TaskStatus.EVALUATING)
        if result.evaluation.result == EvaluationResult.PASS:
            return transition_task(
                task,
                TaskStatus.PASS,
                evaluation_id=result.evaluation.evaluation_id,
            )
        return transition_task(
            task,
            TaskStatus.REPAIR_REQUIRED,
            evaluation_id=result.evaluation.evaluation_id,
        )

    @staticmethod
    def resolve_repaired_gaps(
        prior_gaps: Sequence[Gap],
        result: RequirementLoopResult,
    ) -> Tuple[Gap, ...]:
        """Resolve only gaps whose reason disappeared in a new evaluation.

        Repair output alone can never close a gap.  The repair controller must
        first move a gap to EVIDENCE_PENDING; this method then requires the new
        independent evaluation as the resolution authority.
        """
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
        result: RequirementLoopResult,
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
                append_entity(
                    truth,
                    gap,
                    release_id=release_id,
                    artifact_version=gap_version,
                )
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
