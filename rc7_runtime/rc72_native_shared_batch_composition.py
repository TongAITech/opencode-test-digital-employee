"""C10 native execution+evaluator batch composition for the actual Mission host.

Both independent DSH launchers are prevalidated before installing either
instance-local model meter. No A-owned factory/state machine changes. The host
provides real authorities, approved scopes, real leases and tool capabilities.
"""
from __future__ import annotations

from dataclasses import dataclass

from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
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


@dataclass(frozen=True)
class NativeBatchServices:
    execution: NativeSharedExecutionBatch
    evaluator: NativeSharedEvaluatorBatch


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
                review=review,
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
