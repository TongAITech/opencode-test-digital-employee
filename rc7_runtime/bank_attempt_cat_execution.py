"""Bank execution hardening: current-Attempt CAT provenance.

This adapter keeps the frozen ClosedLoopRuntimeExecutionService behavior but
adds two trust-boundary guarantees for the bank Autopilot path:

1. the terminal ExecutionRecord is written to canonical R1 before diagnosis;
2. required CAT is executed by AttemptCatQueryService and immediately replayed
   from immutable R1 evidence before DiagnosisRuntime may consume its signals.

Missing CAT qualification/provider/correlation remains a diagnosis evidence gap;
there is no local or Agent-authored fallback.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from rc6_runtime.diagnosis import CorrelationScope, DiagnosisContractError

from .attempt_cat import AttemptCatError, AttemptCatQueryService
from .case_runtime import CaseRuntimeError
from .execution_diagnosis import ExecutionDiagnosisCoordinator
from .runtime_execution import RuntimeExecutionError
from .runtime_execution_control import ClosedLoopRuntimeExecutionService


class BankAttemptCatRuntimeExecutionService(ClosedLoopRuntimeExecutionService):
    """Closed-loop execution with R1-first Attempt and trusted CAT diagnosis."""

    @staticmethod
    def _correlation_payload(scope: CorrelationScope) -> Dict[str, Any]:
        return {
            "applications": list(scope.applications),
            "window_start": scope.window_start,
            "window_end": scope.window_end,
            **scope.identifiers(),
        }

    @classmethod
    def _failure_context_payload(cls, scope: CorrelationScope, context: object) -> Dict[str, Any]:
        return {
            "attempt_id": str(getattr(context, "attempt_id", "") or ""),
            "target_id": str(getattr(context, "target_id", "") or ""),
            "layer": str(getattr(context, "layer", "") or "").upper(),
            "real_action_executed": bool(getattr(context, "real_action_executed", False)),
            "remote_integration": bool(getattr(context, "remote_integration", False)),
            "business_action_state": str(getattr(context, "business_action_state", "UNKNOWN") or "UNKNOWN").upper(),
            "correlation": cls._correlation_payload(scope),
        }

    @staticmethod
    def _execution_attempt_payload(bundle, record) -> Dict[str, Any]:
        return {
            "attempt_id": record.attempt_id,
            "release_id": bundle.spec.release_id,
            "artifact_version": 1,
            "requirement_id": bundle.spec.requirement_id,
            "tc_id": record.tc_id,
            "case_version": record.case_version,
            "target_id": record.target_id,
            "layer": record.layer,
            "status": record.status,
            "actual_result": record.actual_result,
            "tool_call_refs": list(record.tool_call_refs or ()),
            "evidence_refs": list(record.evidence_refs or ()),
        }

    def _record_current_attempt(self, control, bundle, record) -> None:
        """Persist exactly one immutable current Attempt before any diagnosis."""
        payload = self._execution_attempt_payload(bundle, record)
        rows = control.truth.query("execution_attempt", attempt_id=record.attempt_id)
        if rows:
            if len(rows) != 1:
                raise RuntimeExecutionError("EXECUTION_ATTEMPT_R1_NOT_UNIQUE:%s" % record.attempt_id)
            current = rows[0]
            for field, expected in payload.items():
                if field == "artifact_version":
                    continue
                if current.get(field) != expected:
                    raise RuntimeExecutionError("EXECUTION_ATTEMPT_R1_CONFLICT:%s:%s" % (record.attempt_id, field))
            return
        try:
            control.truth.append_atomic("EXECUTION_ATTEMPT_UPSERTED", payload)
        except Exception as exc:
            raise RuntimeExecutionError("EXECUTION_ATTEMPT_R1_PERSISTENCE_FAILED:%s" % exc) from exc

    def _persistable_output(self, control, *, task_id, bundle, raw_record):
        output = super()._persistable_output(control, task_id=task_id, bundle=bundle, raw_record=raw_record)
        self._record_current_attempt(control, bundle, output[0])
        return output

    def _trusted_cat_query(self, control, *, task_id: str, runtime_worker_id: str):
        service = AttemptCatQueryService(control.truth, self.state_root)

        def query(scope: CorrelationScope, context: object) -> Dict[str, Any]:
            failure_context = self._failure_context_payload(scope, context)
            try:
                result = service.query(
                    mission_id=control.mission_id,
                    task_id=task_id,
                    worker_id=runtime_worker_id,
                    attempt_id=failure_context["attempt_id"],
                    target_id=failure_context["target_id"],
                    correlation=failure_context["correlation"],
                    failure_context=failure_context,
                )
                verified = service.require_for_failure_context(
                    mission_id=control.mission_id,
                    task_id=task_id,
                    worker_id=runtime_worker_id,
                    failure_context=failure_context,
                )
            except (AttemptCatError, CaseRuntimeError) as exc:
                raise DiagnosisContractError("CAT_CURRENT_ATTEMPT_EVIDENCE_GAP:%s" % exc) from exc
            if verified is None:
                raise DiagnosisContractError("CAT_CURRENT_ATTEMPT_EVIDENCE_GAP:POLICY_NOT_REQUIRED")
            if verified["cat_query_evidence_id"] != result["evidence_id"]:
                raise DiagnosisContractError("CAT_CURRENT_ATTEMPT_EVIDENCE_REPLAY_MISMATCH")
            return {
                "tool_call_ref": verified["tool_call_ref"],
                "evidence_ref": verified["cat_query_evidence_id"],
                "signals": dict(verified.get("signals") or {}),
            }

        return query

    def execute_active_task(
        self,
        control,
        task_id: str,
        *,
        bundle,
        prepared,
        active,
        authority,
        tool_broker,
        oracle_evaluator,
        cwd: str,
        env: Optional[Mapping[str, str]] = None,
        diagnosis=None,
        recovery=None,
        diagnosis_coordinator: Optional[ExecutionDiagnosisCoordinator] = None,
        diagnosis_trust=None,
    ):
        if diagnosis_coordinator is None:
            diagnosis_coordinator = ExecutionDiagnosisCoordinator(
                authority=authority,
                tool_broker=tool_broker,
                evidence_root=str(self.evidence_root),
                cat_query=self._trusted_cat_query(
                    control,
                    task_id=task_id,
                    runtime_worker_id=active.runtime_worker_id,
                ),
            )
        return super().execute_active_task(
            control,
            task_id,
            bundle=bundle,
            prepared=prepared,
            active=active,
            authority=authority,
            tool_broker=tool_broker,
            oracle_evaluator=oracle_evaluator,
            cwd=cwd,
            env=env,
            diagnosis=diagnosis,
            recovery=recovery,
            diagnosis_coordinator=diagnosis_coordinator,
            diagnosis_trust=diagnosis_trust,
        )
