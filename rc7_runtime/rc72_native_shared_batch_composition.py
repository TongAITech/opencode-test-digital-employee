"""C10 native execution+evaluator batch composition for the actual Mission host.

Both independent DSH launchers are prevalidated before installing either
instance-local model meter. No A-owned factory/state machine changes. The host
provides real authorities, approved scopes, real leases and tool capabilities.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping

from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc6_runtime.authority import AuthorityRuntime
from rc6_runtime.truth import TruthRuntime

from .rc72_model_economy import TokenEconomyService
from .rc72_model_usage import TokenUsageAuditService
from .rc72_production_economy_wiring import (
    ProductionEconomyBindingError, bind_production_model_economy,
)
from .rc72_native_shared_batch import (
    NativeSharedExecutionBatch, canonical_batch_metadata_resolver,
)
from .rc72_native_shared_batch_review import NativeSharedEvaluatorBatch
from .rc72_native_batch_formal_n7 import NativeBatchFormalN7Reconciler


@dataclass(frozen=True)
class NativeBatchServices:
    execution: NativeSharedExecutionBatch
    evaluator: NativeSharedEvaluatorBatch

    def drive_formal_n7(
        self, *, batch, attempt_ids_by_workitem: Mapping[str, str],
        execution_assignment: Any,
        approved_reviewer_assignment_factory: Callable[[Dict[str, Any]], Any],
        pipeline, release_batch_id: str,
    ) -> Dict[str, Any]:
        """One real producer + one independent reviewer; then A's full N7.

        Never create reviewer authorization locally: a host-side, approved
        factory receives the actual producer candidate with raw evidence and
        must return a new independently scoped WorkerAssignment. No model
        response can become business PASS; only pipeline.complete and its
        accepted full N7 obligation audit can reconcile members.
        """
        if not callable(approved_reviewer_assignment_factory):
            raise ProductionEconomyBindingError(
                "NATIVE_BATCH_APPROVED_REVIEWER_ASSIGNMENT_FACTORY_REQUIRED"
            )
        if pipeline.truth is not self.execution.truth:
            raise ProductionEconomyBindingError("NATIVE_BATCH_FORMAL_LEDGER_MISMATCH")
        if pipeline.release_id != self.execution.release_id:
            raise ProductionEconomyBindingError("NATIVE_BATCH_FORMAL_RELEASE_MISMATCH")
        candidate = self.execution.dispatch(
            batch,
            attempt_ids_by_workitem=attempt_ids_by_workitem,
            assignment=execution_assignment,
        )
        reviewer_assignment = approved_reviewer_assignment_factory(dict(candidate))
        reviewed = self.evaluator.review(
            candidate_id=candidate["candidate_id"],
            assignment=reviewer_assignment,
        )
        # The business runner operates on original formal Case/ETU/Attempt
        # contracts, not model-generated candidate steps. It may stay HOLD.
        formal = pipeline.complete(release_batch_id=release_batch_id)
        if formal.get("state") != "N7_PASS":
            return {
                "status": "HOLD",
                "reason": "NATIVE_BATCH_FORMAL_N7_NOT_ACCEPTED",
                "batch_receipt_id": candidate["batch_receipt_id"],
                "candidate_id": candidate["candidate_id"],
                "review_id": reviewed["review_id"],
                "formal_n7_state": formal.get("state", formal.get("status", "UNKNOWN")),
            }
        reconciled = self.reconcile_accepted_n7(
            pipeline,
            release_batch_id=release_batch_id,
            batch_receipt_id=candidate["batch_receipt_id"],
            candidate_id=candidate["candidate_id"],
            review_id=reviewed["review_id"],
        )
        return {
            "status": "N7_BATCH_RESULTS_RECONCILED",
            "batch_receipt_id": reconciled["batch_receipt_id"],
            "member_count": reconciled["member_count"],
            "candidate_id": candidate["candidate_id"],
            "review_id": reviewed["review_id"],
            "formal_n7_state": "N7_PASS",
            "bank_final": False,
        }

    def reconcile_accepted_n7(
        self, pipeline, *, release_batch_id: str,
        batch_receipt_id: str, candidate_id: str, review_id: str,
    ):
        """No model verdict becomes N7 PASS: require formal full-N7 proof."""
        if pipeline.truth is not self.execution.truth:
            raise ProductionEconomyBindingError("NATIVE_BATCH_FORMAL_LEDGER_MISMATCH")
        if pipeline.release_id != self.execution.release_id:
            raise ProductionEconomyBindingError("NATIVE_BATCH_FORMAL_RELEASE_MISMATCH")
        return NativeBatchFormalN7Reconciler(pipeline).reconcile(
            release_batch_id=release_batch_id,
            batch_receipt_id=batch_receipt_id,
            candidate_id=candidate_id,
            review_id=review_id,
        )


def compose_native_batch_services(
    truth: TruthRuntime, *,
    release_id: str, mission_id: str,
    execution_launcher: DshHeadlessWorkerLauncher,
    evaluator_launcher: DshHeadlessWorkerLauncher,
    economy: TokenEconomyService,
    usage_audit: TokenUsageAuditService,
) -> NativeBatchServices:
    """Bind the two actual native DSH model-call boundaries before dispatch."""
    if not isinstance(mission_id, str) or not mission_id.strip():
        raise ProductionEconomyBindingError("NATIVE_BATCH_MISSION_REQUIRED")
    if not isinstance(release_id, str) or not release_id.strip():
        raise ProductionEconomyBindingError("NATIVE_BATCH_RELEASE_REQUIRED")
    if execution_launcher is evaluator_launcher:
        raise ProductionEconomyBindingError("NATIVE_BATCH_INDEPENDENT_LAUNCHERS_REQUIRED")
    if not isinstance(economy, TokenEconomyService) or not isinstance(usage_audit, TokenUsageAuditService):
        raise ProductionEconomyBindingError("NATIVE_BATCH_REAL_R1_USAGE_SERVICES_REQUIRED")
    if (
        economy.truth is not truth or usage_audit.truth is not truth
        or economy.release_id != release_id or usage_audit.release_id != release_id
    ):
        raise ProductionEconomyBindingError("NATIVE_BATCH_R1_RELEASE_MISMATCH")
    for role, launcher in (("execution", execution_launcher), ("evaluator", evaluator_launcher)):
        if (
            not isinstance(launcher, DshHeadlessWorkerLauncher)
            or launcher.truth is not truth
            or launcher.release_id != release_id
            or not isinstance(getattr(launcher, "authority", None), AuthorityRuntime)
            or not callable(getattr(launcher, "command_runner", None))
            or not callable(getattr(launcher, "execute", None))
            or not callable(getattr(launcher, "_persist_raw_worker_output", None))
            or getattr(launcher, "_rc72_production_economy_bound", False)
        ):
            raise ProductionEconomyBindingError("NATIVE_BATCH_LAUNCHER_INVALID:%s" % role)

    for launcher, review in ((execution_launcher, False), (evaluator_launcher, True)):
        bind_production_model_economy(
            launcher, economy=economy, usage_audit=usage_audit,
            metadata_resolver=canonical_batch_metadata_resolver(
                truth, release_id=release_id, mission_id=mission_id,
                launcher=launcher, review=review,
            ),
        )
    return NativeBatchServices(
        execution=NativeSharedExecutionBatch(
            truth, release_id=release_id, launcher=execution_launcher,
        ),
        evaluator=NativeSharedEvaluatorBatch(
            truth, release_id=release_id, launcher=evaluator_launcher,
        ),
    )
