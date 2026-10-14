"""RC7 Case -> Execution Contract -> Script Readiness closed loop.

RC6 executable-spec fingerprints and deterministic ScriptValidator are reused.
RC7 deliberately invokes readiness validation with execute_target=False: compile,
discovery and dependency/fixture resolution determine SCRIPT_READY; the product
business assertion is evaluated later by the Execution node. A correct test that
finds a product defect must therefore remain SCRIPT_READY while TEST_RESULT=FAIL.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from rc6_runtime.automation import ScriptArtifact, ScriptValidation, ScriptValidator
from rc6_runtime.executable_spec import ExecutableSpecBuilder, ExecutableSpecError, ExecutableTestSpec
from rc6_runtime.truth import TruthRuntime

from .models import Evaluation, EvaluationResult, Gap, GapSeverity, GapStatus, Task, TaskStatus
from .state_machine import transition_gap, transition_task
from .truth_overlay import append_entity


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


@dataclass(frozen=True)
class ScriptReadinessLoopResult:
    evaluation: Evaluation
    gaps: Tuple[Gap, ...]
    script_ready: bool


class ScriptReadinessClosedLoop:
    def __init__(self, *, validation_timeout_seconds: int = 180) -> None:
        self._spec_builder = ExecutableSpecBuilder()
        self._validator = ScriptValidator(validation_timeout_seconds)

    def compile_execution_contract(
        self,
        *,
        case: Mapping[str, Any],
        target_requirements: Tuple[str, ...],
        test_data_refs: Tuple[str, ...],
        oracle_refs: Tuple[str, ...],
        cleanup_policy: Mapping[str, Any],
        runner_type: str,
        automation_mapping: Mapping[str, Any],
    ) -> ExecutableTestSpec:
        return self._spec_builder.build(
            case=case,
            target_requirements=target_requirements,
            test_data_refs=test_data_refs,
            oracle_refs=oracle_refs,
            cleanup_policy=cleanup_policy,
            runner_type=runner_type,
            automation_mapping=automation_mapping,
        )

    def validate_script(
        self,
        *,
        spec: ExecutableTestSpec,
        script: ScriptArtifact,
        cwd: str,
        env: Optional[Mapping[str, str]] = None,
    ) -> ScriptValidation:
        # Hard separation: do not execute the business assertion in the
        # readiness gate. Formal execution owns PASS/FAIL/BLOCKED/INCONCLUSIVE.
        return self._validator.validate(
            spec=spec,
            script=script,
            cwd=cwd,
            env=env,
            execute_target=False,
        )

    def evaluate(
        self,
        *,
        mission_id: str,
        artifact_ref: str,
        spec: ExecutableTestSpec,
        script: ScriptArtifact,
        validation: ScriptValidation,
        evaluator_ref: str = "rc6-deterministic-script-readiness-gate",
    ) -> ScriptReadinessLoopResult:
        gaps = []
        try:
            ExecutableSpecBuilder.verify_script_or_repair_binding(
                spec,
                case_fingerprint=script.case_fingerprint,
                oracle_fingerprint=script.oracle_fingerprint,
            )
            if script.spec_id != spec.spec_id or script.tc_id != spec.tc_id:
                raise ExecutableSpecError("SCRIPT_SPEC_IDENTITY_MISMATCH")
        except ExecutableSpecError as exc:
            gaps.append(
                Gap(
                    gap_id=_stable_id("GAP-SCRIPT", mission_id, script.script_id, str(exc)),
                    mission_id=mission_id,
                    source_node="SCRIPT_READINESS",
                    category="SCRIPT_BINDING_VIOLATION",
                    severity=GapSeverity.BLOCKER,
                    target_node="SCRIPT_READINESS",
                    description=str(exc),
                    subject_refs=[artifact_ref, spec.spec_id, script.script_id],
                    evidence_refs=list(script.builder_evidence_refs),
                    acceptance_criteria=["script preserves frozen Case and Oracle fingerprints"],
                )
            )

        if validation.script_id != script.script_id:
            gaps.append(
                Gap(
                    gap_id=_stable_id("GAP-SCRIPT", mission_id, script.script_id, "VALIDATION_IDENTITY"),
                    mission_id=mission_id,
                    source_node="SCRIPT_READINESS",
                    category="SCRIPT_VALIDATION_IDENTITY_MISMATCH",
                    severity=GapSeverity.BLOCKER,
                    target_node="SCRIPT_READINESS",
                    description="SCRIPT_VALIDATION_IDENTITY_MISMATCH",
                    subject_refs=[artifact_ref, script.script_id, validation.validation_id],
                    evidence_refs=list(validation.evidence_refs),
                    acceptance_criteria=["validation refers to the exact script revision"],
                )
            )
        elif not validation.ready:
            failed_steps = [step.name for step in validation.steps if not step.passed]
            gaps.append(
                Gap(
                    gap_id=_stable_id(
                        "GAP-SCRIPT",
                        mission_id,
                        script.script_id,
                        "VALIDATION",
                        ",".join(failed_steps),
                    ),
                    mission_id=mission_id,
                    source_node="SCRIPT_READINESS",
                    category="SCRIPT_VALIDATION_FAILED",
                    severity=GapSeverity.HIGH,
                    target_node="SCRIPT_READINESS",
                    description="SCRIPT_VALIDATION_FAILED:%s" % ",".join(failed_steps),
                    subject_refs=[artifact_ref, script.script_id, validation.validation_id],
                    evidence_refs=list(validation.evidence_refs),
                    acceptance_criteria=["compile/discovery/dependency readiness validation passes"],
                )
            )

        result = EvaluationResult.PASS if not gaps and validation.ready else EvaluationResult.REPAIR_REQUIRED
        evaluation = Evaluation(
            evaluation_id=_stable_id(
                "EVAL-SCRIPT",
                mission_id,
                script.script_id,
                validation.validation_id,
                result.value,
                ",".join(sorted(gap.gap_id for gap in gaps)),
            ),
            mission_id=mission_id,
            node="SCRIPT_READINESS",
            artifact_refs=[artifact_ref],
            result=result,
            evaluator_ref=evaluator_ref,
            dimensions={
                "gate_status": "SCRIPT_READY" if result == EvaluationResult.PASS else "SCRIPT_NOT_READY",
                "validation_status": validation.status,
                "validation_steps": [
                    {"name": step.name, "passed": step.passed, "exit_code": step.exit_code}
                    for step in validation.steps
                ],
                "business_assertion_executed": False,
                "case_fingerprint": spec.case_fingerprint,
                "oracle_fingerprint": spec.oracle_fingerprint,
            },
            gap_refs=[gap.gap_id for gap in gaps],
            evidence_refs=list(validation.evidence_refs) + list(script.builder_evidence_refs),
        )
        return ScriptReadinessLoopResult(
            evaluation=evaluation,
            gaps=tuple(gaps),
            script_ready=(result == EvaluationResult.PASS),
        )

    @staticmethod
    def accept_candidate(task: Task, result: ScriptReadinessLoopResult) -> Task:
        if task.state != TaskStatus.OUTPUT_PRODUCED:
            raise RuntimeError("SCRIPT_CANDIDATE_OUTPUT_REQUIRED")
        transition_task(task, TaskStatus.EVALUATING)
        if result.evaluation.result == EvaluationResult.PASS:
            return transition_task(task, TaskStatus.PASS, evaluation_id=result.evaluation.evaluation_id)
        return transition_task(
            task,
            TaskStatus.REPAIR_REQUIRED,
            evaluation_id=result.evaluation.evaluation_id,
        )

    @staticmethod
    def resolve_repaired_gaps(
        prior_gaps: Sequence[Gap],
        result: ScriptReadinessLoopResult,
    ) -> Tuple[Gap, ...]:
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
        result: ScriptReadinessLoopResult,
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
