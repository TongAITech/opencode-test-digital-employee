"""Production-oriented RC8 Center application factory.

Formal runtime chain:
Node -> PostgreSQL identity/state + Redis active lease authorization
-> R1 Event Stream -> replayable projector -> PostgreSQL governance/coverage
projection -> evidence-gated Mission progression -> FastAPI -> Vue.
"""
from __future__ import annotations

from pathlib import Path

from rc8_runtime import CentralR1RuntimeLedger
from rc8_center.api import create_app
from rc8_center.artifacts import FileArtifactStore
from rc8_center.case_inventory import CenterFrozenCaseInventoryResolver
from rc8_center.code_sufficiency import CenterCodeSufficiencyEvaluator
from rc8_center.defect_closure import CenterDefectClosureService
from rc8_center.executable_readiness import CenterExecutableReadinessService
from rc8_center.execution_admission import CenterN7ExecutionAdmissionGate
from rc8_center.failure_diagnosis import CenterFailureDiagnosisService
from rc8_center.fanout_progression import FanoutSafeRequirementLoopProgressor
from rc8_center.formal_artifacts import FormalArtifactService
from rc8_center.formal_control import FormalCenterControlPlane
from rc8_center.formal_settings import CenterSettings
from rc8_center.formal_trace_authority import FormalTraceRuntimeAuthority
from rc8_center.n7_execution_result import CenterN7CaseExecutionResultAuthority
from rc8_center.n7_execution_result_receipt import CenterN7CaseExecutionResultReceiptAuthority
from rc8_center.n7_formal_control import N7AdmissionAwareFormalCenterControlPlane
from rc8_center.n7_tool_invocation import CenterN7ToolInvocationAuthority
from rc8_center.prepared_attempt import CenterPreparedAttemptService
from rc8_center.r1_traceability_ingestion import R1BackedCenterTraceabilityIngestion
from rc8_center.runtime_invalidation import CenterRuntimeInvalidationCoordinator
from rc8_center.runtime_invalidation_projector import CenterRuntimeInvalidationProjector
from rc8_center.runtime_invalidation_recorder import CenterRuntimeInvalidationRecorder
from rc8_center.runtime_invalidation_service import CenterRuntimeInvalidationService
from rc8_center.runtime_mutation_producer import CenterRuntimeMutationProducer, RuntimeMutationAwareFormalCenterControlPlane
from rc8_center.scope_aware_governance_projector import ScopeAwareGovernanceEventProjector
from rc8_center.governance_projection import GovernanceProjectionService
from rc8_center.mission_service import CenterMissionService
from rc8_center.infrastructure import (
    PostgresArtifactRepository, PostgresCenterRepository, PostgresCoverageRepository,
    PostgresGovernanceRepository, PostgresRecoveryRepository, PostgresRequirementDeliveryRepository,
    PostgresRequirementRevisionRepository, PostgresStore, PostgresTestRoundRepository,
    PostgresTraceabilityRepository, RedisCoordination, build_engine,
)
from rc8_center.infrastructure.postgres_defect_closure import PostgresDefectClosureRepository
from rc8_center.infrastructure.postgres_executable_readiness import PostgresExecutableSpecRepository
from rc8_center.infrastructure.postgres_failure_diagnosis import PostgresFailureDiagnosisRepository
from rc8_center.infrastructure.postgres_prepared_attempt import PostgresPreparedAttemptRepository
from rc8_center.recovery_service import LeaseRecoveryCoordinator


def _require_complete_runtime_invalidation_replay(result) -> None:
    pending = int(getattr(result, "pending", 0) or (result.get("pending", 0) if isinstance(result, dict) else 0))
    errors = tuple(getattr(result, "errors", ()) or (result.get("errors", ()) if isinstance(result, dict) else ()))
    if pending or errors:
        detail = "; ".join(str(error) for error in errors[:5])
        raise RuntimeError("RC8 Center startup blocked: canonical runtime invalidation replay is incomplete (pending=%s, errors=%s)%s" % (pending, len(errors), (": " + detail) if detail else ""))


def _require_complete_runtime_mutation_replay(result) -> None:
    pending = int(getattr(result, "pending", 0) or (result.get("pending", 0) if isinstance(result, dict) else 0))
    errors = tuple(getattr(result, "errors", ()) or (result.get("errors", ()) if isinstance(result, dict) else ()))
    if pending or errors:
        detail = "; ".join(str(error) for error in errors[:5])
        raise RuntimeError("RC8 Center startup blocked: canonical runtime mutation replay is incomplete (pending=%s, errors=%s)%s" % (pending, len(errors), (": " + detail) if detail else ""))


def build_app():
    settings = CenterSettings()
    postgres = PostgresStore(build_engine(settings.database_url))
    redis_coordination = RedisCoordination.from_url(settings.redis_url)
    governance_repository = PostgresGovernanceRepository(postgres)
    coverage_repository = PostgresCoverageRepository(postgres)
    artifact_repository = PostgresArtifactRepository(postgres)
    control_repository = PostgresCenterRepository(postgres)
    recovery_repository = PostgresRecoveryRepository(postgres)
    delivery_repository = PostgresRequirementDeliveryRepository(postgres)
    revision_repository = PostgresRequirementRevisionRepository(postgres)
    test_round_repository = PostgresTestRoundRepository(postgres)
    prepared_attempt_repository = PostgresPreparedAttemptRepository(postgres)
    executable_spec_repository = PostgresExecutableSpecRepository(postgres)
    traceability_repository = PostgresTraceabilityRepository(postgres)
    failure_diagnosis_repository = PostgresFailureDiagnosisRepository(postgres)
    defect_closure_repository = PostgresDefectClosureRepository(postgres)
    failure_diagnosis_service = CenterFailureDiagnosisService(failure_diagnosis_repository)
    defect_closure_service = CenterDefectClosureService(defect_closure_repository, failure_diagnosis_repository)

    ledger = CentralR1RuntimeLedger(str(Path(settings.r1_root) / "event-stream.jsonl"))
    prepared_attempts = CenterPreparedAttemptService(prepared_attempt_repository)
    executable_readiness = CenterExecutableReadinessService(executable_spec_repository, prepared_attempts)
    runtime_invalidation_coordinator = CenterRuntimeInvalidationCoordinator(prepared_attempts, executable_readiness)
    runtime_invalidation_projector = CenterRuntimeInvalidationProjector(ledger, runtime_invalidation_coordinator)
    runtime_invalidation_replay_result = runtime_invalidation_projector.replay()
    _require_complete_runtime_invalidation_replay(runtime_invalidation_replay_result)
    runtime_invalidation_recorder = CenterRuntimeInvalidationRecorder(ledger)
    runtime_invalidation_service = CenterRuntimeInvalidationService(recorder=runtime_invalidation_recorder, projector=runtime_invalidation_projector, prepared_attempts=prepared_attempts)
    runtime_mutation_producer = CenterRuntimeMutationProducer(ledger=ledger, invalidation_service=runtime_invalidation_service, executable_readiness=executable_readiness)
    runtime_mutation_replay_result = runtime_mutation_producer.replay()
    _require_complete_runtime_mutation_replay(runtime_mutation_replay_result)

    projector = ScopeAwareGovernanceEventProjector(ledger, governance_repository, coverage_repository, artifact_repository)
    replay_result = projector.replay()
    projection = GovernanceProjectionService(governance_repository, coverage_repository)
    artifact_store = FileArtifactStore(settings.artifact_root, artifact_repository)
    case_inventory_resolver = CenterFrozenCaseInventoryResolver(
        governance_repository=governance_repository,
        control_repository=control_repository,
        artifact_repository=artifact_repository,
        artifact_store=artifact_store,
    )
    mission_service = CenterMissionService(governance_repository, traceability_repository=traceability_repository)
    mission_progressor = FanoutSafeRequirementLoopProgressor(
        store=postgres, mission_service=mission_service, governance_repository=governance_repository,
        control_repository=control_repository, artifact_repository=artifact_repository,
        case_inventory_resolver=case_inventory_resolver,
    )
    formal_control_core = FormalCenterControlPlane(control_repository, redis_coordination, ledger, projector, progression=mission_progressor)
    runtime_formal_control = RuntimeMutationAwareFormalCenterControlPlane(formal_control_core, runtime_mutation_producer)
    n7_execution_admission = CenterN7ExecutionAdmissionGate(
        governance_repository=governance_repository,
        case_inventory_resolver=case_inventory_resolver,
        prepared_attempts=prepared_attempts,
        executable_readiness=executable_readiness,
        artifact_store=artifact_store,
    )
    n7_case_execution_result_authority = CenterN7CaseExecutionResultAuthority(
        runtime_ledger=ledger,
        executable_readiness=executable_readiness,
        artifact_repository=artifact_repository,
    )
    n7_case_execution_result_receipt_authority = CenterN7CaseExecutionResultReceiptAuthority(ledger)
    n7_tool_invocation_authority = CenterN7ToolInvocationAuthority(
        redis_coordination,
        executable_readiness,
    )
    formal_control = N7AdmissionAwareFormalCenterControlPlane(
        runtime_formal_control,
        n7_execution_admission,
        n7_case_execution_result_authority,
        n7_tool_invocation_authority,
        n7_case_execution_result_receipt_authority,
    )
    trace_runtime_authority = FormalTraceRuntimeAuthority(formal_control, governance_repository)
    traceability_ingestion = R1BackedCenterTraceabilityIngestion(traceability_repository, ledger=ledger, control_plane=trace_runtime_authority, attempt_snapshot_resolver=trace_runtime_authority.resolve_current_attempt)
    trace_replay_result = traceability_ingestion.replay_canonical_runtime_observations()
    code_sufficiency_evaluator = CenterCodeSufficiencyEvaluator(traceability_repository)
    recovery_coordinator = LeaseRecoveryCoordinator(control_repository, recovery_repository, redis_coordination, ledger)
    artifact_service = FormalArtifactService(artifact_store, formal_control, projector)

    app = create_app(settings=settings, postgres=postgres, redis_coordination=redis_coordination, governance_projection=projection, formal_control=formal_control, recovery_coordinator=recovery_coordinator, artifact_service=artifact_service, product_application=None, delivery_repository=delivery_repository, revision_repository=revision_repository, test_round_repository=test_round_repository)
    app.state.r1_ledger = ledger
    app.state.runtime_invalidation_projector = runtime_invalidation_projector
    app.state.runtime_invalidation_replay_result = runtime_invalidation_replay_result
    app.state.runtime_invalidation_coordinator = runtime_invalidation_coordinator
    app.state.runtime_invalidation_recorder = runtime_invalidation_recorder
    app.state.runtime_invalidation_service = runtime_invalidation_service
    app.state.runtime_mutation_producer = runtime_mutation_producer
    app.state.runtime_mutation_replay_result = runtime_mutation_replay_result
    app.state.prepared_attempt_repository = prepared_attempt_repository
    app.state.executable_spec_repository = executable_spec_repository
    app.state.prepared_attempts = prepared_attempts
    app.state.executable_readiness = executable_readiness
    app.state.n7_execution_admission = n7_execution_admission
    app.state.n7_case_execution_result_authority = n7_case_execution_result_authority
    app.state.n7_case_execution_result_receipt_authority = n7_case_execution_result_receipt_authority
    app.state.n7_tool_invocation_authority = n7_tool_invocation_authority
    app.state.traceability_repository = traceability_repository
    app.state.trace_runtime_authority = trace_runtime_authority
    app.state.traceability_ingestion = traceability_ingestion
    app.state.trace_replay_result = trace_replay_result
    app.state.code_sufficiency_evaluator = code_sufficiency_evaluator
    app.state.governance_projector = projector
    app.state.governance_replay_result = replay_result
    app.state.governance_repository = governance_repository
    app.state.coverage_repository = coverage_repository
    app.state.artifact_repository = artifact_repository
    app.state.control_repository = control_repository
    app.state.recovery_repository = recovery_repository
    app.state.delivery_repository = delivery_repository
    app.state.revision_repository = revision_repository
    app.state.test_round_repository = test_round_repository
    app.state.failure_diagnosis_repository = failure_diagnosis_repository
    app.state.failure_diagnosis_service = failure_diagnosis_service
    app.state.defect_closure_repository = defect_closure_repository
    app.state.defect_closure_service = defect_closure_service
    app.state.mission_service = mission_service
    app.state.mission_progressor = mission_progressor
    app.state.formal_control_core = formal_control_core
    app.state.runtime_formal_control = runtime_formal_control
    app.state.formal_control = formal_control
    app.state.recovery_coordinator = recovery_coordinator
    app.state.artifact_store = artifact_store
    app.state.case_inventory_resolver = case_inventory_resolver
    app.state.artifact_service = artifact_service
    return app


app = build_app()
