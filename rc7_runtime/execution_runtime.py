"""RC7 deterministic execution runtime composition.

A PASS Script is still not a test result. RC7 prepares the frozen TestCase,
executes its validated script through a real RunnerAdapter, independently
re-evaluates the observed actual_result with RuntimeOracleEvaluator, persists
execution/preparation/cleanup evidence into R1, and then delegates semantic
failure ownership/recovery routing to the inherited RC6 closure machinery.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from rc6_runtime.automation import RunnerAdapter, ScriptArtifact, ScriptValidation
from rc6_runtime.diagnosis import (
    AttemptHistory,
    DiagnosisResult,
    FailureContext,
    FailureSignature,
    RecoveryDecision,
    RecoveryEngine,
    history_entry_from_execution,
)
from rc6_runtime.execution import AttemptExecutor, ExecutionRecord, OracleAssertionResult, PreparedExecution
from rc6_runtime.preparation import PreparationRuntime, PreparationSpecParser, PreparedAttempt
from rc6_runtime.truth import TruthRuntime

from .execution_loop import ExecutionClosedLoop, ExecutionLoopResult
from .execution_oracle import RuntimeOracleEvaluator, RuntimeOracleResult
from .models import Evidence, Evaluation, EvaluationResult, Gap, GapSeverity
from .script_contract import CompiledScriptContract
from .truth_overlay import append_entity


class RC7ExecutionRuntimeError(RuntimeError):
    pass


@dataclass(frozen=True)
class RC7ExecutionRuntimeResult:
    record: ExecutionRecord
    oracle_result: Optional[RuntimeOracleResult]
    prepared_attempt: Optional[PreparedAttempt]
    cleanup_status: Optional[str]
    diagnosis: Optional[DiagnosisResult]
    recovery: Optional[RecoveryDecision]
    loop_result: ExecutionLoopResult


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


def _flatten_strings(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).lower()
    except (TypeError, ValueError):
        return str(value).lower()


class DeterministicFailureClassifier:
    """Evidence-first first-pass owner classifier before optional deep RCA."""

    @staticmethod
    def classify(record: ExecutionRecord, context: FailureContext) -> Tuple[str, str]:
        reason = str(record.reason or "").upper()
        actual_text = _flatten_strings(record.actual_result)
        logs = " ".join(context.runner_log_refs).lower()
        combined = reason.lower() + " " + actual_text + " " + logs

        if record.status == "BLOCKED_PREPARATION":
            if "data_preparation_failed" in combined or "data_verification_failed" in combined or "cleanup" in combined:
                return "DATA", "PREPARATION_DATA_FAILURE"
            if "auth" in combined:
                return "AUTH", "PREPARATION_AUTH_FAILURE"
            if "dependency" in combined:
                return "DEPENDENCY", "PREPARATION_DEPENDENCY_FAILURE"
            if "environment" in combined:
                return "ENVIRONMENT", "PREPARATION_ENVIRONMENT_FAILURE"
            return "PRECONDITION", "PREPARATION_PRECONDITION_FAILURE"

        if record.status == "INVALID_EVIDENCE":
            return "TOOL", "EXECUTION_EVIDENCE_INTEGRITY_FAILURE"

        # Deterministic ownership shortcuts for transport/runtime failures.
        if any(token in combined for token in ('"http_status": 401', '"http_status": 403', '"status_code": 401', '"status_code": 403')):
            return "AUTH", "HTTP_AUTH_FAILURE"
        if any(token in combined for token in ('"http_status": 404', '"http_status": 405', '"status_code": 404', '"status_code": 405')):
            return "ROUTE", "HTTP_ROUTE_FAILURE"
        if any(token in combined for token in ("connection refused", "connection reset", "dns", "name resolution", "network unreachable")):
            return "ENVIRONMENT", "NETWORK_ENVIRONMENT_FAILURE"
        if any(token in combined for token in ("dependency unavailable", "service unavailable", '"http_status": 503', '"status_code": 503')):
            return "DEPENDENCY", "DEPENDENCY_UNAVAILABLE"
        if any(token in combined for token in ("fixture", "syntaxerror", "importerror", "modulenotfounderror", "compilation failure")):
            return "SCRIPT", "SCRIPT_RUNTIME_FAILURE"

        if record.status == "FAIL" and record.assertion_passed is False:
            if context.product_ownership_proven():
                return "PRODUCT", "ASSERTION_FAILED_AFTER_COMPETING_OWNERS_EXCLUDED"
            return "UNKNOWN", "ASSERTION_FAILED_WITH_INCOMPLETE_OWNERSHIP_PROOF"
        return "UNKNOWN", "NO_DETERMINISTIC_OWNER"


class RC7ExecutionRuntime:
    def __init__(
        self,
        *,
        truth: TruthRuntime,
        release_id: str,
        mission_id: str,
        preparation_runtime: PreparationRuntime,
        runner_adapter: RunnerAdapter,
        execution_timeout_seconds: int = 300,
    ) -> None:
        self.truth = truth
        self.release_id = release_id
        self.mission_id = mission_id
        self.preparation_runtime = preparation_runtime
        self.runner_adapter = runner_adapter
        self.executor = AttemptExecutor(timeout_seconds=execution_timeout_seconds)
        self.oracle = RuntimeOracleEvaluator()
        self.loop = ExecutionClosedLoop()
        self.classifier = DeterministicFailureClassifier()

    def execute(
        self,
        *,
        artifact_ref: str,
        contract: CompiledScriptContract,
        script: ScriptArtifact,
        validation: ScriptValidation,
        attempt_id: str,
        worker_id: str,
        lease_id: str,
        target_id: str,
        cwd: str,
        env: Optional[Mapping[str, str]] = None,
    ) -> RC7ExecutionRuntimeResult:
        if validation.status != "SCRIPT_READY" or not validation.ready:
            raise RC7ExecutionRuntimeError("EXECUTION_REQUIRES_SCRIPT_READY")
        if validation.script_id != script.script_id:
            raise RC7ExecutionRuntimeError("EXECUTION_SCRIPT_VALIDATION_IDENTITY_MISMATCH")
        if script.spec_id != contract.spec.spec_id or script.tc_id != contract.spec.tc_id:
            raise RC7ExecutionRuntimeError("EXECUTION_SCRIPT_SPEC_IDENTITY_MISMATCH")
        self.oracle.validate(contract.frozen_case.get("oracle"))

        plan = PreparationSpecParser().parse(contract.frozen_case)
        prepared_attempt: Optional[PreparedAttempt] = None
        oracle_result: Optional[RuntimeOracleResult] = None
        cleanup_status: Optional[str] = None

        try:
            prepared_attempt = self.preparation_runtime.prepare(plan, attempt_id)
            prepared = PreparedExecution(
                attempt_id=attempt_id,
                tc_id=contract.spec.tc_id,
                case_version=contract.spec.case_version,
                target_id=target_id,
                layer=contract.spec.layer,
                worker_id=worker_id,
                lease_id=lease_id,
                preparation_passed=True,
                evidence_refs=tuple(prepared_attempt.evidence_refs),
                reason="PREPARATION_PASS",
            )
        except Exception as exc:
            prepared = PreparedExecution(
                attempt_id=attempt_id,
                tc_id=contract.spec.tc_id,
                case_version=contract.spec.case_version,
                target_id=target_id,
                layer=contract.spec.layer,
                worker_id=worker_id,
                lease_id=lease_id,
                preparation_passed=False,
                evidence_refs=(),
                reason="PREPARATION_FAILED:%s:%s" % (type(exc).__name__, exc),
            )

        def oracle_adapter(snapshot: Mapping[str, Any], actual: Mapping[str, Any]) -> OracleAssertionResult:
            nonlocal oracle_result
            oracle_result = self.oracle.evaluate(snapshot, actual)
            return OracleAssertionResult(
                assertion_ref=oracle_result.assertion_ref,
                passed=oracle_result.passed,
                evidence_refs=(),
            )

        record = self.executor.execute_with_runner(
            prepared=prepared,
            script=script,
            validation=validation,
            runner=self.runner_adapter,
            oracle_snapshot=contract.frozen_case["oracle"],
            oracle_evaluator=oracle_adapter,
            cwd=cwd,
            env=dict(env or {}),
        )
        record = self._canonicalize_record_evidence(record)

        if prepared_attempt is not None:
            try:
                cleanup = self.preparation_runtime.cleanup(plan, prepared_attempt)
                cleanup_status = cleanup.status
                cleanup_ids = self._persist_refs(
                    cleanup.evidence_refs,
                    kind="EXECUTION_CLEANUP_PROOF",
                    subject_refs=[attempt_id, contract.spec.tc_id],
                )
                record = replace(
                    record,
                    evidence_refs=tuple(dict.fromkeys(list(record.evidence_refs) + cleanup_ids)),
                )
            except Exception as exc:
                cleanup_status = "CLEANUP_FAILED:%s:%s" % (type(exc).__name__, exc)

        history = AttemptHistory()
        history.append(history_entry_from_execution(record))
        diagnosis: Optional[DiagnosisResult] = None
        recovery: Optional[RecoveryDecision] = None

        if record.status in {"PASS"}:
            result = self.loop.evaluate(
                mission_id=self.mission_id,
                artifact_ref=artifact_ref,
                record=record,
                evaluator_ref="rc7-runtime-execution-gate",
            )
        else:
            context = self._failure_context(
                record=record,
                contract=contract,
                validation=validation,
                prepared_attempt=prepared_attempt,
            )
            failure_class, rationale = self.classifier.classify(record, context)
            diagnosis = DiagnosisResult(
                diagnosis_id=_stable_id("DIAG-RC7", self.mission_id, attempt_id, failure_class, rationale),
                attempt_id=attempt_id,
                failure_class=failure_class,
                evidence_refs=record.evidence_refs,
                cat_required=False,
                cat_queried=False,
                rationale=rationale,
                classifier_ref="rc7-deterministic-first-owner-classifier",
                failure_signature=FailureSignature.from_context(context),
            )
            recovery = RecoveryEngine(history).decide(context, diagnosis)
            result = self.loop.evaluate(
                mission_id=self.mission_id,
                artifact_ref=artifact_ref,
                record=record,
                diagnosis=diagnosis,
                recovery=recovery,
                evaluator_ref="rc7-runtime-execution-gate",
            )

        if cleanup_status and cleanup_status != "CLEANUP_PASS":
            result = self._merge_cleanup_failure(
                artifact_ref=artifact_ref,
                record=record,
                base=result,
                cleanup_status=cleanup_status,
            )
        return RC7ExecutionRuntimeResult(
            record=record,
            oracle_result=oracle_result,
            prepared_attempt=prepared_attempt,
            cleanup_status=cleanup_status,
            diagnosis=diagnosis,
            recovery=recovery,
            loop_result=result,
        )

    def _canonicalize_record_evidence(self, record: ExecutionRecord) -> ExecutionRecord:
        ids = self._persist_refs(
            record.evidence_refs,
            kind="EXECUTION_RUNTIME_PROOF",
            subject_refs=[record.attempt_id, record.tc_id],
        )
        return replace(record, evidence_refs=tuple(ids))

    def _persist_refs(self, refs: Sequence[str], *, kind: str, subject_refs: Sequence[str]) -> List[str]:
        result = []
        for ref in refs:
            if not isinstance(ref, str) or not ref:
                continue
            digest = ""
            if ref.startswith("file://"):
                path = Path(ref[len("file://"):])
                if path.is_file():
                    digest = hashlib.sha256(path.read_bytes()).hexdigest()
            evidence_id = _stable_id("EVD-EXEC", self.mission_id, kind, ref, digest)
            if not self.truth.query("rc7_evidence", evidence_id=evidence_id):
                append_entity(
                    self.truth,
                    Evidence(
                        evidence_id=evidence_id,
                        mission_id=self.mission_id,
                        kind=kind,
                        source_ref="runtime://execution",
                        content_ref=ref,
                        subject_refs=list(subject_refs),
                        content_hash=("sha256:" + digest) if digest else None,
                    ),
                    release_id=self.release_id,
                    artifact_version=1,
                )
            result.append(evidence_id)
        return list(dict.fromkeys(result))

    @staticmethod
    def _failure_context(
        *,
        record: ExecutionRecord,
        contract: CompiledScriptContract,
        validation: ScriptValidation,
        prepared_attempt: Optional[PreparedAttempt],
    ) -> FailureContext:
        text = _flatten_strings(record.actual_result)
        http_auth_failure = any(token in text for token in ('"http_status": 401', '"http_status": 403', '"status_code": 401', '"status_code": 403'))
        http_route_failure = any(token in text for token in ('"http_status": 404', '"http_status": 405', '"status_code": 404', '"status_code": 405'))
        environment_failure = any(token in text for token in ("connection refused", "connection reset", "dns", "network unreachable"))
        dependency_failure = any(token in text for token in ("service unavailable", '"http_status": 503', '"status_code": 503'))
        prepared = prepared_attempt is not None and record.status != "BLOCKED_PREPARATION"
        runner_logs = []
        for step in validation.steps:
            runner_logs.extend([step.stdout_ref, step.stderr_ref])
        return FailureContext(
            attempt_id=record.attempt_id,
            tc_id=record.tc_id,
            case_version=record.case_version,
            target_id=record.target_id,
            layer=record.layer,
            execution_status=record.status,
            preparation_verified=prepared,
            real_action_executed=bool(record.tool_call_refs),
            assertion_failed=(record.assertion_passed is False),
            execution_evidence_refs=record.evidence_refs,
            runner_log_refs=tuple(ref for ref in runner_logs if isinstance(ref, str) and ref),
            case_oracle_verified=True,
            executable_spec_verified=True,
            script_validated=validation.ready,
            data_verified=prepared,
            auth_verified=prepared and not http_auth_failure,
            route_verified=prepared and not http_route_failure,
            tool_verified=record.integrity_passed,
            environment_verified=prepared and not environment_failure,
            dependency_verified=prepared and not dependency_failure,
        )

    def _merge_cleanup_failure(
        self,
        *,
        artifact_ref: str,
        record: ExecutionRecord,
        base: ExecutionLoopResult,
        cleanup_status: str,
    ) -> ExecutionLoopResult:
        gap = Gap(
            gap_id=_stable_id("GAP-EXEC-CLEANUP", self.mission_id, record.attempt_id, cleanup_status),
            mission_id=self.mission_id,
            source_node="EXECUTION",
            category="TEST_DATA_DEFECT",
            severity=GapSeverity.HIGH,
            target_node="SCRIPT_READINESS",
            description="EXECUTION_CLEANUP_NOT_PASS:%s" % cleanup_status,
            subject_refs=[artifact_ref, record.attempt_id, record.tc_id],
            evidence_refs=list(record.evidence_refs),
            acceptance_criteria=["test data cleanup executes and returns durable evidence"],
        )
        gaps = tuple(list(base.gaps) + [gap])
        dimensions = dict(base.evaluation.dimensions)
        dimensions["cleanup_status"] = cleanup_status
        evaluation = Evaluation(
            evaluation_id=_stable_id("EVAL-EXEC-CLEANUP", self.mission_id, record.attempt_id, cleanup_status),
            mission_id=self.mission_id,
            node="EXECUTION",
            artifact_refs=[artifact_ref],
            result=EvaluationResult.REPAIR_REQUIRED,
            evaluator_ref=base.evaluation.evaluator_ref,
            dimensions=dimensions,
            gap_refs=[item.gap_id for item in gaps],
            evidence_refs=list(record.evidence_refs),
        )
        return ExecutionLoopResult(
            evaluation=evaluation,
            gaps=gaps,
            test_result=base.test_result,
            conclusive=False,
        )
