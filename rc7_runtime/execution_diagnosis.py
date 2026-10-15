"""Runtime-owned failure diagnosis and recovery coordination for RC7 execution.

The formal execution runner owns process/result truth.  This module consumes
that immutable truth and reuses the proven RC6 evidence-first DiagnosisRuntime
and RecoveryEngine.  It never upgrades an assertion failure to PRODUCT merely
because an assertion failed; PRODUCT is legal only after all competing
ownership classes are positively excluded by Runtime-owned trust facts.

When mandatory evidence (for example bounded CAT correlation for L3/L5) is not
available, diagnosis fails closed and the caller keeps DIAGNOSIS_REQUIRED open.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

from rc6_runtime.capability import ToolCapabilityBroker
from rc6_runtime.diagnosis import (
    AttemptHistory,
    CATPolicy,
    CorrelationScope,
    DiagnosisContractError,
    DiagnosisResult,
    DiagnosisRuntime,
    FailureContext,
    RecoveryDecision,
    RecoveryEngine,
    history_entry_from_execution,
)
from rc6_runtime.execution import ExecutionRecord
from rc6_runtime.preparation import PreparedAttempt

from .authority import RC7AuthorityRuntime
from .execution_recovery import ExecutionRecoveryPlanner, RecoveryWorkPlan
from .oracle_runtime import DeterministicOracleRuntime
from .runtime_execution import VerifiedScriptExecutionBundle


@dataclass(frozen=True)
class ExecutionTrustFacts:
    """Facts that may only be supplied by Runtime-owned probes/evidence."""

    auth_verified: bool = False
    route_verified: bool = False
    tool_verified: bool = False
    environment_verified: bool = False
    dependency_verified: bool = False
    remote_integration: bool = False
    correlation: Optional[CorrelationScope] = None
    exception_type: Optional[str] = None
    root_stack_frame: Optional[str] = None
    http_status: Optional[int] = None
    business_error_code: Optional[str] = None
    route: Optional[str] = None
    assertion_identity: Optional[str] = None
    runner_log_refs: Tuple[str, ...] = ()


@dataclass(frozen=True)
class DiagnosisClosure:
    context: FailureContext
    diagnosis: Optional[DiagnosisResult]
    recovery: Optional[RecoveryDecision]
    work_plan: Optional[RecoveryWorkPlan]
    unavailable_reason: Optional[str]
    diagnostic_worker_id: Optional[str]
    diagnostic_lease_id: Optional[str]
    evidence_ref: Optional[str] = None
    evidence_sha256: Optional[str] = None

    @property
    def complete(self) -> bool:
        return (
            self.diagnosis is not None
            and self.recovery is not None
            and self.work_plan is not None
            and self.unavailable_reason is None
        )


class ExecutionDiagnosisCoordinator:
    """Build evidence context, diagnose, and decide recovery without model self-attestation."""

    def __init__(
        self,
        *,
        authority: RC7AuthorityRuntime,
        tool_broker: ToolCapabilityBroker,
        evidence_root: str,
        classifier: Optional[Callable[[FailureContext, Dict[str, Any]], Dict[str, Any]]] = None,
        cat_query: Optional[Callable[[CorrelationScope, FailureContext], Dict[str, Any]]] = None,
        evidence_collectors: Optional[Mapping[str, Callable[[FailureContext], Dict[str, Any]]]] = None,
        rca_resolver: Optional[Callable[[FailureContext, Dict[str, Any], str], Dict[str, Any]]] = None,
        history: Optional[AttemptHistory] = None,
        max_transient_retries: int = 2,
    ) -> None:
        self.authority = authority
        self.tool_broker = tool_broker
        self.evidence_root = Path(evidence_root).resolve()
        self.classifier = classifier or self._default_classifier
        self.cat_query = cat_query
        self.evidence_collectors = dict(evidence_collectors or {})
        self.rca_resolver = rca_resolver
        self.history = history or AttemptHistory()
        self.max_transient_retries = int(max_transient_retries)
        if self.max_transient_retries < 0:
            raise ValueError("max_transient_retries must be >= 0")

    @staticmethod
    def _default_classifier(context: FailureContext, signals: Dict[str, Any]) -> Dict[str, Any]:
        del signals
        exception = str(context.exception_type or "").lower().replace("_", "").replace("-", "")
        reason_parts = []
        if context.http_status in {401, 403} or "auth" in exception:
            failure_class = "AUTH"
            reason_parts.append("AUTH_FAILURE_SIGNAL")
        elif context.http_status == 404 or "routenotfound" in exception or "endpointnotfound" in exception:
            failure_class = "ROUTE"
            reason_parts.append("ROUTE_FAILURE_SIGNAL")
        elif context.http_status in {408, 425, 429, 502, 503, 504}:
            failure_class = "TRANSIENT"
            reason_parts.append("HTTP_TRANSIENT_STATUS")
        elif any(token in exception for token in ("importerror", "modulenotfound", "syntaxerror")):
            failure_class = "SCRIPT"
            reason_parts.append("SCRIPT_LOAD_EXCEPTION")
        elif "precondition" in exception:
            failure_class = "PRECONDITION"
            reason_parts.append("PRECONDITION_FAILURE_SIGNAL")
        elif any(token in exception for token in ("databinding", "testdata", "dataunavailable")):
            failure_class = "DATA"
            reason_parts.append("DATA_FAILURE_SIGNAL")
        elif "dependency" in exception:
            failure_class = "DEPENDENCY"
            reason_parts.append("DEPENDENCY_FAILURE_SIGNAL")
        elif "environment" in exception:
            failure_class = "ENVIRONMENT"
            reason_parts.append("ENVIRONMENT_FAILURE_SIGNAL")
        elif "tool" in exception:
            failure_class = "TOOL"
            reason_parts.append("TOOL_FAILURE_SIGNAL")
        elif any(token in exception for token in ("timeout", "connectionerror", "connectionreset")):
            failure_class = "TRANSIENT"
            reason_parts.append("TRANSPORT_EXCEPTION")
        elif context.assertion_failed and context.product_ownership_proven():
            failure_class = "PRODUCT"
            reason_parts.append("ASSERTION_FAIL_WITH_ALL_COMPETING_OWNERSHIP_EXCLUDED")
        else:
            failure_class = "UNKNOWN"
            reason_parts.append("OWNERSHIP_NOT_PROVEN")
        return {
            "failure_class": failure_class,
            "classifier_ref": "rc7-runtime-deterministic-failure-classifier/v2",
            "rationale": ",".join(reason_parts),
            "evidence_refs": [],
        }

    @staticmethod
    def _http_facts(record: ExecutionRecord) -> Tuple[Optional[int], Optional[str]]:
        actual = record.actual_result
        if not isinstance(actual, dict):
            return None, None
        http = actual.get("_http")
        if not isinstance(http, dict):
            return None, None
        status = http.get("status_code")
        target = http.get("target_url")
        return (int(status) if isinstance(status, int) else None, target if isinstance(target, str) else None)

    @staticmethod
    def _real_action_executed(record: ExecutionRecord) -> bool:
        refs = tuple(str(ref) for ref in (record.tool_call_refs or ()) if isinstance(ref, str) and ref)
        if str(record.layer).upper() == "L3":
            return any(ref.startswith("api-runtime://APIREC-") for ref in refs)
        non_business_prefixes = (
            "process://",
            "runner-process://",
            "stdout://",
            "stderr://",
            "validation-manifest://",
        )
        return any(not ref.startswith(non_business_prefixes) for ref in refs)

    def build_context(
        self,
        *,
        record: ExecutionRecord,
        bundle: VerifiedScriptExecutionBundle,
        prepared: PreparedAttempt,
        trust: Optional[ExecutionTrustFacts] = None,
    ) -> FailureContext:
        trust = trust or ExecutionTrustFacts()
        http_status, route = self._http_facts(record)
        oracle_verified = False
        try:
            DeterministicOracleRuntime.validate_contract(prepared.oracle_snapshot)
            oracle_verified = True
        except Exception:
            oracle_verified = False
        return FailureContext(
            attempt_id=record.attempt_id,
            tc_id=record.tc_id,
            case_version=record.case_version,
            target_id=record.target_id,
            layer=record.layer,
            execution_status=record.status,
            preparation_verified=prepared.status == "PREPARED",
            real_action_executed=self._real_action_executed(record),
            assertion_failed=record.assertion_passed is False,
            execution_evidence_refs=tuple(record.evidence_refs),
            correlation=trust.correlation,
            remote_integration=trust.remote_integration,
            case_oracle_verified=oracle_verified,
            executable_spec_verified=True,
            script_validated=bool(bundle.validation.ready),
            data_verified=prepared.status == "PREPARED",
            auth_verified=trust.auth_verified,
            route_verified=trust.route_verified,
            tool_verified=trust.tool_verified,
            environment_verified=trust.environment_verified,
            dependency_verified=trust.dependency_verified,
            exception_type=(trust.exception_type if trust.exception_type is not None else record.reason),
            root_stack_frame=trust.root_stack_frame,
            http_status=trust.http_status if trust.http_status is not None else http_status,
            business_error_code=trust.business_error_code,
            route=trust.route if trust.route is not None else route,
            assertion_identity=(
                trust.assertion_identity
                if trust.assertion_identity is not None
                else (record.assertion_ref if isinstance(record.assertion_ref, str) else None)
            ),
            runner_log_refs=tuple(trust.runner_log_refs),
        )

    def diagnose(
        self,
        *,
        record: ExecutionRecord,
        bundle: VerifiedScriptExecutionBundle,
        prepared: PreparedAttempt,
        trust: Optional[ExecutionTrustFacts] = None,
    ) -> DiagnosisClosure:
        context = self.build_context(record=record, bundle=bundle, prepared=prepared, trust=trust)
        if str(record.status).upper() == "PASS":
            return self._finish(context, None, None, None, "PASS_DOES_NOT_REQUIRE_FAILURE_DIAGNOSIS", None, None)

        cat_required = CATPolicy().required(context)
        tools = ["cat"] if cat_required else []
        worker = self.authority.issue_identity(
            "FAILURE_DIAGNOSTIC", "DIAGNOSIS", None, 0, "rc7-runtime-diagnosis"
        )
        lease = self.authority.issue_lease(
            worker.worker_id,
            "attempt:%s" % record.attempt_id,
            ["failure_diagnosis", "recovery_decision", "evidence"],
            tools,
            ttl_seconds=300,
        )
        if cat_required:
            try:
                self.tool_broker.bind_worker("cat", worker.worker_id, visible=True, permitted=True)
            except Exception:
                pass

        runtime = DiagnosisRuntime(
            authority=self.authority,
            tool_broker=self.tool_broker,
            classifier=self.classifier,
            evidence_collectors=self.evidence_collectors,
            cat_query=self.cat_query,
            rca_resolver=self.rca_resolver,
        )
        try:
            diagnosis = runtime.diagnose(
                context=context,
                worker_id=worker.worker_id,
                lease_id=lease.lease_id,
            )
            if self.history.get(record.attempt_id) is None:
                self.history.append(history_entry_from_execution(record))
            recovery = RecoveryEngine(
                self.history,
                max_transient_retries=self.max_transient_retries,
            ).decide(context, diagnosis)
            work_plan = ExecutionRecoveryPlanner().compile(recovery)
            return self._finish(
                context,
                diagnosis,
                recovery,
                work_plan,
                None,
                worker.worker_id,
                lease.lease_id,
            )
        except (DiagnosisContractError, RuntimeError) as exc:
            return self._finish(
                context,
                None,
                None,
                None,
                str(exc),
                worker.worker_id,
                lease.lease_id,
            )

    def _finish(
        self,
        context: FailureContext,
        diagnosis: Optional[DiagnosisResult],
        recovery: Optional[RecoveryDecision],
        work_plan: Optional[RecoveryWorkPlan],
        unavailable_reason: Optional[str],
        worker_id: Optional[str],
        lease_id: Optional[str],
    ) -> DiagnosisClosure:
        folder = self.evidence_root / "diagnosis"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (context.attempt_id + ".json")
        payload = {
            "context": asdict(context),
            "diagnosis": asdict(diagnosis) if diagnosis is not None else None,
            "recovery": asdict(recovery) if recovery is not None else None,
            "work_plan": asdict(work_plan) if work_plan is not None else None,
            "unavailable_reason": unavailable_reason,
            "diagnostic_worker_id": worker_id,
            "diagnostic_lease_id": lease_id,
        }
        encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n").encode("utf-8")
        path.write_bytes(encoded)
        digest = hashlib.sha256(encoded).hexdigest()
        return DiagnosisClosure(
            context=context,
            diagnosis=diagnosis,
            recovery=recovery,
            work_plan=work_plan,
            unavailable_reason=unavailable_reason,
            diagnostic_worker_id=worker_id,
            diagnostic_lease_id=lease_id,
            evidence_ref="file://" + str(path),
            evidence_sha256=digest,
        )
