"""RC7 Execution / Evidence / Diagnosis / Recovery closed-loop adapter.

A control-plane Task PASS means the execution work reached a trustworthy,
classified conclusion. It does NOT mean the product test passed. Therefore an
evidence-backed product TEST_RESULT=FAIL may still produce Evaluation=PASS and
a downstream PRODUCT_DEFECT Gap for the Defect node.

BLOCKED remains distinct from product FAIL. When diagnosis evidence exists,
BLOCKED is routed by its proven owner (AUTH/ENV/DATA/etc.) instead of being
collapsed into a generic failure bucket.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence, Tuple

from rc6_runtime.diagnosis import DiagnosisResult, RecoveryDecision
from rc6_runtime.execution import ExecutionRecord
from rc6_runtime.truth import TruthRuntime

from .models import Evaluation, EvaluationResult, Gap, GapSeverity, Task, TaskStatus
from .state_machine import transition_task
from .truth_overlay import append_entity


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


_FAILURE_ROUTE = {
    "SCRIPT": ("SCRIPT_DEFECT", "SCRIPT_READINESS", GapSeverity.HIGH),
    "SPEC": ("EXECUTION_CONTRACT_DEFECT", "SCRIPT_READINESS", GapSeverity.HIGH),
    "ORACLE": ("ORACLE_AMBIGUOUS", "TEST_DESIGN", GapSeverity.HIGH),
    "DATA": ("TEST_DATA_DEFECT", "SCRIPT_READINESS", GapSeverity.HIGH),
    "PRECONDITION": ("PRECONDITION_DEFECT", "SCRIPT_READINESS", GapSeverity.HIGH),
    "AUTH": ("AUTH_DEFECT", "RUNTIME", GapSeverity.HIGH),
    "ROUTE": ("API_ROUTE_DEFECT", "CODE_ANALYSIS", GapSeverity.HIGH),
    "TOOL": ("TOOL_DEFECT", "RUNTIME", GapSeverity.HIGH),
    "ENVIRONMENT": ("ENVIRONMENT_DEFECT", "RUNTIME", GapSeverity.HIGH),
    "DEPENDENCY": ("DEPENDENCY_DEFECT", "RUNTIME", GapSeverity.HIGH),
    "FLAKY": ("FLAKY_SUSPECTED", "EXECUTION", GapSeverity.HIGH),
    "TRANSIENT": ("TRANSIENT_FAILURE", "EXECUTION", GapSeverity.MEDIUM),
    "UNKNOWN": ("UNKNOWN_FAILURE", "RUNTIME", GapSeverity.BLOCKER),
}


@dataclass(frozen=True)
class ExecutionLoopResult:
    evaluation: Evaluation
    gaps: Tuple[Gap, ...]
    test_result: str
    conclusive: bool
    recovery_action: Optional[str]


class ExecutionClosedLoop:
    @staticmethod
    def _base_test_result(record: ExecutionRecord) -> str:
        status = str(record.status).upper()
        if status == "PASS":
            return "PASS"
        if status in {"BLOCKED", "SKIPPED", "NOT_RUN"}:
            return "BLOCKED"
        if status == "FAIL":
            if record.integrity_passed and record.assertion_passed is False:
                return "FAIL"
            return "INCONCLUSIVE"
        return "INCONCLUSIVE"

    def evaluate(
        self,
        *,
        mission_id: str,
        artifact_ref: str,
        record: ExecutionRecord,
        diagnosis: Optional[DiagnosisResult] = None,
        recovery: Optional[RecoveryDecision] = None,
        evaluator_ref: str = "rc6-execution-integrity-plus-diagnosis-gate",
    ) -> ExecutionLoopResult:
        test_result = self._base_test_result(record)
        gaps = []
        recovery_action = recovery.action if recovery is not None else None

        if diagnosis is not None and diagnosis.attempt_id != record.attempt_id:
            raise ValueError("DIAGNOSIS_ATTEMPT_MISMATCH")
        if recovery is not None and recovery.attempt_id != record.attempt_id:
            raise ValueError("RECOVERY_ATTEMPT_MISMATCH")

        if test_result == "PASS":
            evaluation_result = EvaluationResult.PASS
            conclusive = True
        elif test_result == "BLOCKED":
            if diagnosis is None:
                category, target, severity = "EXECUTION_BLOCKED", "RUNTIME", GapSeverity.HIGH
                description = record.reason or category
            else:
                failure_class = str(diagnosis.failure_class).upper()
                if failure_class == "PRODUCT":
                    raise ValueError("BLOCKED_EXECUTION_CANNOT_BE_PRODUCT_DEFECT")
                category, target, severity = _FAILURE_ROUTE.get(
                    failure_class,
                    ("UNKNOWN_FAILURE", "RUNTIME", GapSeverity.BLOCKER),
                )
                description = diagnosis.rationale
            gaps.append(
                self._gap(
                    mission_id,
                    record,
                    category=category,
                    target=target,
                    severity=severity,
                    description=description,
                    extra_evidence=diagnosis.evidence_refs if diagnosis is not None else (),
                )
            )
            # A diagnosed recoverable dependency is not a product test result;
            # it remains repairable. A terminal/manual recovery decision is a
            # durable BLOCKED conclusion rather than an infinite repair loop.
            if recovery is not None and recovery.terminal:
                evaluation_result = EvaluationResult.BLOCKED
                conclusive = True
            elif diagnosis is not None:
                evaluation_result = EvaluationResult.REPAIR_REQUIRED
                conclusive = False
            else:
                evaluation_result = EvaluationResult.BLOCKED
                conclusive = True
        else:
            if diagnosis is None:
                gaps.append(
                    self._gap(
                        mission_id,
                        record,
                        category="DIAGNOSIS_REQUIRED",
                        target="EXECUTION",
                        severity=GapSeverity.HIGH,
                        description="failure ownership is not yet classified",
                    )
                )
                evaluation_result = EvaluationResult.REPAIR_REQUIRED
                conclusive = False
            else:
                failure_class = str(diagnosis.failure_class).upper()
                if failure_class == "PRODUCT":
                    if test_result != "FAIL" or not record.integrity_passed:
                        raise ValueError("PRODUCT_FAILURE_REQUIRES_TRUSTED_ORACLE_FAIL")
                    if recovery is None or recovery.action != "PRODUCT_DEFECT" or not recovery.terminal:
                        raise ValueError("PRODUCT_FAILURE_REQUIRES_TERMINAL_DEFECT_DECISION")
                    gaps.append(
                        self._gap(
                            mission_id,
                            record,
                            category="PRODUCT_DEFECT",
                            target="DEFECT",
                            severity=GapSeverity.HIGH,
                            description=diagnosis.rationale,
                            extra_evidence=diagnosis.evidence_refs,
                        )
                    )
                    evaluation_result = EvaluationResult.PASS
                    conclusive = True
                else:
                    category, target, severity = _FAILURE_ROUTE.get(
                        failure_class,
                        ("UNKNOWN_FAILURE", "RUNTIME", GapSeverity.BLOCKER),
                    )
                    gaps.append(
                        self._gap(
                            mission_id,
                            record,
                            category=category,
                            target=target,
                            severity=severity,
                            description=diagnosis.rationale,
                            extra_evidence=diagnosis.evidence_refs,
                        )
                    )
                    if recovery is not None and recovery.terminal:
                        evaluation_result = EvaluationResult.BLOCKED
                        conclusive = True
                    else:
                        evaluation_result = EvaluationResult.REPAIR_REQUIRED
                        conclusive = False

        evidence_refs = list(record.evidence_refs)
        if diagnosis is not None:
            evidence_refs.extend(diagnosis.evidence_refs)
        evaluation = Evaluation(
            evaluation_id=_stable_id(
                "EVAL-EXEC",
                mission_id,
                record.attempt_id,
                test_result,
                evaluation_result.value,
                diagnosis.failure_class if diagnosis is not None else "NONE",
                recovery_action or "NONE",
            ),
            mission_id=mission_id,
            node="EXECUTION",
            artifact_refs=[artifact_ref],
            result=evaluation_result,
            evaluator_ref=evaluator_ref,
            dimensions={
                "test_result": test_result,
                "execution_status": record.status,
                "integrity_passed": record.integrity_passed,
                "assertion_passed": record.assertion_passed,
                "failure_class": diagnosis.failure_class if diagnosis is not None else None,
                "recovery_action": recovery_action,
                "conclusive": conclusive,
                "attempt_id": record.attempt_id,
            },
            gap_refs=[gap.gap_id for gap in gaps],
            evidence_refs=list(dict.fromkeys(evidence_refs)),
        )
        return ExecutionLoopResult(
            evaluation=evaluation,
            gaps=tuple(gaps),
            test_result=test_result,
            conclusive=conclusive,
            recovery_action=recovery_action,
        )

    @staticmethod
    def _gap(
        mission_id: str,
        record: ExecutionRecord,
        *,
        category: str,
        target: str,
        severity: GapSeverity,
        description: str,
        extra_evidence: Sequence[str] = (),
    ) -> Gap:
        evidence = list(dict.fromkeys(list(record.evidence_refs) + list(extra_evidence)))
        return Gap(
            gap_id=_stable_id("GAP-EXEC", mission_id, record.attempt_id, category),
            mission_id=mission_id,
            source_node="EXECUTION",
            category=category,
            severity=severity,
            target_node=target,
            description=description,
            subject_refs=[record.attempt_id, record.tc_id],
            evidence_refs=evidence,
            acceptance_criteria=["execution outcome is handled by owning node and reevaluated"],
        )

    @staticmethod
    def accept_candidate(task: Task, result: ExecutionLoopResult) -> Task:
        if task.state != TaskStatus.OUTPUT_PRODUCED:
            raise RuntimeError("EXECUTION_CANDIDATE_OUTPUT_REQUIRED")
        transition_task(task, TaskStatus.EVALUATING)
        if result.evaluation.result == EvaluationResult.PASS:
            return transition_task(task, TaskStatus.PASS, evaluation_id=result.evaluation.evaluation_id)
        if result.evaluation.result == EvaluationResult.BLOCKED:
            return transition_task(task, TaskStatus.BLOCKED, evaluation_id=result.evaluation.evaluation_id)
        return transition_task(
            task,
            TaskStatus.REPAIR_REQUIRED,
            evaluation_id=result.evaluation.evaluation_id,
        )

    @staticmethod
    def persist(
        truth: TruthRuntime,
        *,
        release_id: str,
        result: ExecutionLoopResult,
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
