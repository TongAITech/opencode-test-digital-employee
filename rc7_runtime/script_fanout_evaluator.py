"""Case-fanout overlay for the existing deterministic Script evaluator.

Each worker invocation still builds one concrete frozen Case.  The overlay
records that Case's real SCRIPT_READY proof, then treats the accepted Test
Design Case inventory as a barrier.  Missing Cases become deterministic
SCRIPT_READINESS repair gaps; they can never be hidden by a PASS for the first
Case.
"""
from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import Mapping, Optional, Tuple

from .case_fanout_conformance import (
    check_script_barrier,
    contract_enabled,
    record_script_ready,
)
from .closed_loop_control import ClosedLoopControlPlane
from .dsh_script_evaluator import DshScriptReadinessEvaluation, DshScriptReadinessEvaluator
from .models import Evaluation, EvaluationResult, Gap, GapSeverity, TaskStatus
from .script_contract import CompiledScriptContract
from .script_readiness_loop import ScriptReadinessLoopResult
from .truth_overlay import append_entity


class ScriptFanoutEvaluatorError(RuntimeError):
    pass


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:24])


class DshCaseFanoutScriptEvaluator:
    def __init__(
        self,
        *,
        evidence_root: str,
        validation_timeout_seconds: int = 180,
    ) -> None:
        self.evidence_root = str(evidence_root)
        self.inner = DshScriptReadinessEvaluator(
            evidence_root=self.evidence_root,
            validation_timeout_seconds=validation_timeout_seconds,
        )

    def evaluate_and_apply(
        self,
        control: ClosedLoopControlPlane,
        task_id: str,
        artifact_id: str,
        *,
        contract: CompiledScriptContract,
        cwd: str,
        env: Optional[Mapping[str, str]] = None,
    ) -> DshScriptReadinessEvaluation:
        evaluated = self.inner.evaluate(
            control,
            task_id,
            artifact_id,
            contract=contract,
            cwd=cwd,
            env=env,
        )
        evaluation = evaluated.loop_result.evaluation
        task = control.scheduler.task(task_id)

        if not contract_enabled(control.truth, control.mission_id) or evaluation.result != EvaluationResult.PASS:
            control.accept_evaluation(task_id, evaluation=evaluation, gaps=evaluated.loop_result.gaps)
            return evaluated

        if evaluated.script is None or evaluated.validation is None or not evaluated.validation.ready:
            raise ScriptFanoutEvaluatorError("SCRIPT_FANOUT_PASS_REQUIRES_REAL_READY_SCRIPT")
        receipt_id = record_script_ready(
            control.truth,
            mission_id=control.mission_id,
            release_id=control.release_id,
            task_id=task_id,
            artifact_id=artifact_id,
            contract=contract,
            script=evaluated.script,
            validation=evaluated.validation,
            evidence_root=self.evidence_root,
        )

        # A repair task owns exactly one previously-opened Case delta. Passing
        # that Case resolves its source gap; the top-level task is reactivated
        # only after all sibling Case gaps have reached evidence-pending.
        if task.task_type == "REPAIR":
            control.accept_evaluation(task_id, evaluation=evaluation, gaps=evaluated.loop_result.gaps)
            return evaluated

        barrier = check_script_barrier(control.truth, control.mission_id)
        if barrier.status == "PASS":
            dimensions = dict(evaluation.dimensions)
            dimensions.update(
                {
                    "case_fanout_contract": "PASS",
                    "required_case_count": len(barrier.required_tc_ids),
                    "script_ready_case_count": len(barrier.ready_tc_ids),
                    "case_script_receipt_ids": list(barrier.receipt_ids),
                }
            )
            accepted = Evaluation(
                evaluation_id=evaluation.evaluation_id,
                mission_id=evaluation.mission_id,
                node=evaluation.node,
                artifact_refs=list(evaluation.artifact_refs),
                result=evaluation.result,
                evaluator_ref=evaluation.evaluator_ref,
                dimensions=dimensions,
                gap_refs=list(evaluation.gap_refs),
                evidence_refs=list(dict.fromkeys(list(evaluation.evidence_refs) + list(barrier.receipt_ids))),
            )
            result = ScriptReadinessLoopResult(
                evaluation=accepted,
                gaps=evaluated.loop_result.gaps,
                script_ready=True,
            )
            final = replace(evaluated, loop_result=result)
            control.accept_evaluation(task_id, evaluation=accepted, gaps=result.gaps)
            return final

        gaps = tuple(
            Gap(
                gap_id=_stable_id(
                    "GAP-CASE-SCRIPT",
                    control.mission_id,
                    barrier.design_artifact_id,
                    tc_id,
                ),
                mission_id=control.mission_id,
                source_node="SCRIPT_READINESS",
                category="SCRIPT_DEFECT",
                severity=GapSeverity.HIGH,
                target_node="SCRIPT_READINESS",
                description="Accepted Test Design Case has no durable SCRIPT_READY receipt: %s" % tc_id,
                subject_refs=[barrier.design_artifact_id, tc_id],
                evidence_refs=list(dict.fromkeys([receipt_id] + list(barrier.receipt_ids))),
                acceptance_criteria=[
                    "compile the frozen accepted Case %s from Test Design artifact %s" % (tc_id, barrier.design_artifact_id),
                    "persist real Script validation evidence and CASE_SCRIPT_READY receipt for %s" % tc_id,
                ],
            )
            for tc_id in barrier.missing_tc_ids
        )
        dimensions = dict(evaluation.dimensions)
        dimensions.update(
            {
                "case_fanout_contract": "INCOMPLETE",
                "required_case_count": len(barrier.required_tc_ids),
                "script_ready_case_count": len(barrier.ready_tc_ids),
                "missing_tc_ids": list(barrier.missing_tc_ids),
                "case_script_receipt_ids": list(barrier.receipt_ids),
            }
        )
        repair_evaluation = Evaluation(
            evaluation_id=_stable_id(
                "EVAL-CASE-SCRIPT-FANOUT",
                control.mission_id,
                artifact_id,
                ",".join(barrier.missing_tc_ids),
            ),
            mission_id=control.mission_id,
            node="SCRIPT_READINESS",
            artifact_refs=[artifact_id],
            result=EvaluationResult.REPAIR_REQUIRED,
            evaluator_ref="rc7-runtime-case-script-fanout-barrier",
            dimensions=dimensions,
            gap_refs=[gap.gap_id for gap in gaps],
            evidence_refs=list(dict.fromkeys(list(evaluation.evidence_refs) + [receipt_id] + list(barrier.receipt_ids))),
        )
        result = ScriptReadinessLoopResult(
            evaluation=repair_evaluation,
            gaps=gaps,
            script_ready=False,
        )
        final = replace(evaluated, loop_result=result)
        control.accept_evaluation(task_id, evaluation=repair_evaluation, gaps=gaps)
        self._bind_repair_tasks_to_design(control, gaps, barrier.design_artifact_id)
        return final

    @staticmethod
    def _bind_repair_tasks_to_design(
        control: ClosedLoopControlPlane,
        gaps: Tuple[Gap, ...],
        design_artifact_id: str,
    ) -> None:
        gap_ids = {gap.gap_id for gap in gaps}
        for row in control.truth.query("rc7_task", mission_id=control.mission_id):
            if row.get("task_type") != "REPAIR" or row.get("node") != "SCRIPT_READINESS":
                continue
            refs = set(row.get("gap_refs") or [])
            if not refs.intersection(gap_ids):
                continue
            task = control.scheduler.task(str(row["task_id"]))
            if design_artifact_id not in task.input_artifact_refs:
                task.input_artifact_refs.append(design_artifact_id)
                append_entity(
                    control.truth,
                    task,
                    release_id=control.release_id,
                    artifact_version=int(row["artifact_version"]) + 1,
                )
