"""Parent-aware RC7 DSH Test Design evaluator.

This is the canonical RC7 DSH Test Design acceptance adapter. It composes the
independent reviewer / semantic closure evaluator with a deterministic parent
inventory guard so a Designer cannot obtain 100% coverage by choosing a small
self-authored obligation denominator.
"""

from __future__ import annotations

import hashlib
from typing import Dict, List, Sequence

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


class DshParentAwareTestDesignEvaluator(_BaseDshTestDesignEvaluator):
    """Add a parent-truth denominator guard to the proven DSH design evaluator."""

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

        evaluated = super().evaluate(control, task_id, artifact_id)
        guarded = self._apply_parent_guard(
            control,
            artifact_id=artifact_id,
            base=evaluated.loop_result,
            sources=sources,
            missing=missing,
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
    def _apply_parent_guard(
        control: ClosedLoopControlPlane,
        *,
        artifact_id: str,
        base: TestDesignLoopResult,
        sources: Sequence[MandatoryObligationSource],
        missing: Sequence[str],
    ) -> TestDesignLoopResult:
        dimensions = dict(base.evaluation.dimensions)
        dimensions["parent_obligation_source_total"] = len(sources)
        dimensions["parent_obligation_missing_total"] = len(missing)
        dimensions["missing_parent_obligation_sources"] = list(missing)
        dimensions["parent_obligation_coverage"] = "PASS" if not missing else "GAPS"

        if not missing:
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

        gaps = tuple(list(base.gaps) + extra_gaps)
        evaluation = Evaluation(
            evaluation_id=_stable_id(
                "EVAL-TD-PARENT",
                control.mission_id,
                artifact_id,
                base.evaluation.evaluation_id,
                ",".join(sorted(set(missing))),
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
