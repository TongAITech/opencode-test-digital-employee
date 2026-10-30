"""Independent N2 Requirement review with worker-declared uncertainty guard.

Canonical N2 candidate artifacts are reviewed by the inherited independent DSH
Requirement reviewer and deterministic RequirementClosedLoop. This adapter
adds one RC7.2 rule that the inherited semantic gate cannot infer by itself:
worker-declared unknowns/gaps and an unproven SST identity are unresolved truth
and therefore force REPAIR_REQUIRED even when the independent reviewer would
otherwise return PASS.

The service does not create NodeDelivery/NodeGate. It applies the resulting
Evaluation through ClosedLoopControlPlane so Gap routing, repair ownership and
Task state remain governed by the existing RC7 control plane.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Sequence, Tuple

from .candidate_payload import CandidatePayloadReader
from .closed_loop_control import ClosedLoopControlPlane
from .dsh_requirement_evaluator import DshRequirementEvaluation, DshRequirementEvaluator
from .models import Evaluation, EvaluationResult, Gap, GapSeverity


class N2RequirementReviewError(RuntimeError):
    pass


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


def _compact(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return str(value)


@dataclass(frozen=True)
class N2RequirementReviewResult:
    task_id: str
    artifact_id: str
    requirement_id: str
    reviewer_worker_id: str
    reviewer_session_id: str
    evaluation_id: str
    evaluation_result: str
    gap_ids: Tuple[str, ...]
    task_state: str
    worker_uncertainty_guard_triggered: bool


class N2RequirementReviewService:
    """Apply independent Requirement review without allowing uncertainty hiding."""

    def __init__(
        self,
        control: ClosedLoopControlPlane,
        evaluator: DshRequirementEvaluator,
    ) -> None:
        self.control = control
        self.evaluator = evaluator
        self.reader = CandidatePayloadReader()

    def _uncertainty_gaps(
        self,
        *,
        task_id: str,
        artifact_id: str,
        requirement_id: str,
        semantic: Dict[str, Any],
        evidence_refs: Sequence[str],
    ) -> Tuple[Gap, ...]:
        concerns: List[Tuple[str, GapSeverity, str]] = []
        sst_ids = semantic.get("sst_ids")
        if not isinstance(sst_ids, list) or not sst_ids:
            concerns.append((
                "SST_IDENTITY_NOT_PROVEN",
                GapSeverity.CRITICAL,
                "Requirement %s has no evidence-proven SST identity" % requirement_id,
            ))

        unknowns = semantic.get("candidate_unknowns", [])
        if not isinstance(unknowns, list):
            raise N2RequirementReviewError("RC72_N2_REVIEW_CANDIDATE_UNKNOWNS_INVALID")
        for index, unknown in enumerate(unknowns):
            concerns.append((
                "WORKER_DECLARED_UNKNOWN:%d" % index,
                GapSeverity.HIGH,
                "Worker-declared unresolved unknown: %s" % _compact(unknown),
            ))

        declared_gaps = semantic.get("candidate_gaps", [])
        if not isinstance(declared_gaps, list):
            raise N2RequirementReviewError("RC72_N2_REVIEW_CANDIDATE_GAPS_INVALID")
        for index, declared in enumerate(declared_gaps):
            concerns.append((
                "WORKER_DECLARED_GAP:%d" % index,
                GapSeverity.HIGH,
                "Worker-declared unresolved gap: %s" % _compact(declared),
            ))

        out: List[Gap] = []
        for reason_key, severity, description in concerns:
            gap_id = _stable_id(
                "GAP-N2-UNCERTAINTY",
                self.control.mission_id,
                task_id,
                artifact_id,
                reason_key,
                description,
            )
            out.append(Gap(
                gap_id=gap_id,
                mission_id=self.control.mission_id,
                source_node="REQUIREMENT_ANALYSIS",
                category="REQUIREMENT_AMBIGUITY",
                severity=severity,
                target_node="REQUIREMENT_ANALYSIS",
                description=description,
                subject_refs=[artifact_id, requirement_id, task_id],
                evidence_refs=list(dict.fromkeys(evidence_refs)),
                acceptance_criteria=[
                    "resolve %s with durable source evidence and rerun independent Requirement review"
                    % reason_key
                ],
            ))
        return tuple(out)

    def _guarded_evaluation(
        self,
        *,
        evaluated: DshRequirementEvaluation,
        extra_gaps: Sequence[Gap],
    ) -> Tuple[Evaluation, Tuple[Gap, ...]]:
        base = evaluated.loop_result.evaluation
        all_gaps = list(evaluated.loop_result.gaps)
        existing = {gap.gap_id for gap in all_gaps}
        for gap in extra_gaps:
            if gap.gap_id not in existing:
                all_gaps.append(gap)
                existing.add(gap.gap_id)
        if not extra_gaps:
            return base, tuple(all_gaps)

        reasons = list(base.dimensions.get("reasons", []))
        for gap in extra_gaps:
            marker = "RC72_WORKER_UNCERTAINTY:%s" % gap.gap_id
            if marker not in reasons:
                reasons.append(marker)
        dimensions = dict(base.dimensions)
        dimensions.update({
            "gate_status": "NOT_SUFFICIENT_CONTENT",
            "reasons": reasons,
            "rc72_worker_uncertainty_guard": "FAILED",
            "rc72_worker_uncertainty_gap_ids": [gap.gap_id for gap in extra_gaps],
        })
        evidence_refs = list(base.evidence_refs)
        for gap in extra_gaps:
            for ref in gap.evidence_refs:
                if ref not in evidence_refs:
                    evidence_refs.append(ref)
        evaluation = Evaluation(
            evaluation_id=_stable_id(
                "EVAL-N2-REQ",
                self.control.mission_id,
                evaluated.artifact_id,
                evaluated.reviewer_worker_id,
                "REPAIR_REQUIRED",
                ",".join(sorted(gap.gap_id for gap in all_gaps)),
            ),
            mission_id=self.control.mission_id,
            node="REQUIREMENT_ANALYSIS",
            artifact_refs=[evaluated.artifact_id],
            result=EvaluationResult.REPAIR_REQUIRED,
            evaluator_ref=base.evaluator_ref + "+rc7.2-worker-uncertainty-guard",
            dimensions=dimensions,
            gap_refs=[gap.gap_id for gap in all_gaps],
            evidence_refs=evidence_refs,
        )
        return evaluation, tuple(all_gaps)

    def review_and_apply(
        self,
        *,
        task_id: str,
        artifact_id: str,
    ) -> N2RequirementReviewResult:
        candidate = self.reader.load(
            self.control.truth,
            artifact_id,
            expected_mission_id=self.control.mission_id,
            expected_task_id=task_id,
        )
        semantic = dict(candidate.semantic_payload)
        requirement_id = semantic.get("requirement_id")
        if not isinstance(requirement_id, str) or not requirement_id.strip():
            raise N2RequirementReviewError("RC72_N2_REVIEW_REQUIREMENT_ID_REQUIRED")
        requirement_id = requirement_id.strip()

        evaluated = self.evaluator.evaluate(self.control, task_id, artifact_id)
        if evaluated.analysis.get("requirement_id") != requirement_id:
            raise N2RequirementReviewError("RC72_N2_REVIEW_EVALUATOR_REQUIREMENT_MISMATCH")
        artifact_rows = self.control.truth.query("rc7_artifact", artifact_id=artifact_id)
        if len(artifact_rows) != 1:
            raise N2RequirementReviewError("RC72_N2_REVIEW_ARTIFACT_NOT_UNIQUE")
        evidence_refs = list(artifact_rows[0].get("evidence_refs") or [])
        extra = self._uncertainty_gaps(
            task_id=task_id,
            artifact_id=artifact_id,
            requirement_id=requirement_id,
            semantic=semantic,
            evidence_refs=evidence_refs,
        )
        final_evaluation, final_gaps = self._guarded_evaluation(
            evaluated=evaluated,
            extra_gaps=extra,
        )
        task = self.control.accept_evaluation(
            task_id,
            evaluation=final_evaluation,
            gaps=final_gaps,
        )
        return N2RequirementReviewResult(
            task_id=task_id,
            artifact_id=artifact_id,
            requirement_id=requirement_id,
            reviewer_worker_id=evaluated.reviewer_worker_id,
            reviewer_session_id=evaluated.reviewer_session_id,
            evaluation_id=final_evaluation.evaluation_id,
            evaluation_result=final_evaluation.result.value,
            gap_ids=tuple(gap.gap_id for gap in final_gaps),
            task_state=task.state.value,
            worker_uncertainty_guard_triggered=bool(extra),
        )
