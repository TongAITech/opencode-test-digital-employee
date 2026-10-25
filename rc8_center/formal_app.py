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
from rc8_center.executable_readiness import CenterExecutableReadinessService
from rc8_center.requirement_loop_progression import RequirementLoopProgressor
from rc8_center.formal_artifacts import FormalArtifactService
from rc8_center.formal_control import FormalCenterControlPlane
from rc8_center.formal_settings import CenterSettings
from rc8_center.formal_trace_authority import FormalTraceRuntimeAuthority
from rc8_center.prepared_attempt import CenterPreparedAttemptService
from rc8_center.r1_traceability_ingestion import R1BackedCenterTraceabilityIngestion
from rc8_center.runtime_invalidation import CenterRuntimeInvalidationCoordinator
from rc8_center.runtime_invalidation_projector import CenterRuntimeInvalidationProjector
from rc8_center.scope_aware_governance_projector import ScopeAwareGovernanceEventProjector
from rc8_center.governance_projection import GovernanceProjectionService
from rc8_center.mission_service import CenterMissionService
from rc8_center.infrastructure import (
    PostgresArtifactRepository,
    PostgresCenterRepository,
    PostgresCoverageRepository,
    PostgresGovernanceRepository,
    PostgresRecoveryRepository,
    PostgresRequirementDeliveryRepository,
    PostgresRequirementRevisionRepository,
    PostgresStore,
    PostgresTestRoundRepository,
    PostgresTraceabilityRepository,
    RedisCoordination,
    build_engine,
)
from rc8_center.infrastructure.postgres_executable_readiness import PostgresExecutableSpecRepository
from rc8_center.infrastructure.postgres_prepared_attempt import PostgresPreparedAttemptRepository
from rc8_center.recovery_service import LeaseRecoveryCoordinator


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

    r1_path = Path(settings.r1_root) / "event-stream.jsonl"
    ledger = CentralR1RuntimeLedger(str(r1_path))

    prepared_attempts = CenterPreparedAttemptService(prepared_attempt_repository)
    executable_readiness = CenterExecutableReadinessService(executable_spec_repository, prepared_attempts)
    runtime_invalidation_coordinator = CenterRuntimeInvalidationCoordinator(prepared_attempts, executable_readiness)
    runtime_invalidation_projector = CenterRuntimeInvalidationProjector(ledger, runtime_invalidation_coordinator)
    runtime_invalidation_replay_result = runtime_invalidation_projector.replay()

    projector = ScopeAwareGovernanceEventProjector(ledger, governance_repository, coverage_repository, artifact_repository)
    replay_result = projector.replay()
    projection = GovernanceProjectionService(governance_repository, coverage_repository)
    mission_service = CenterMissionService(governance_repository)
    mission_progressor = RequirementLoopProgressor(
        store=postgres,
        mission_service=mission_service,
        governance_repository=governance_repository,
        control_repository=control_repository,
        artifact_repository=artifact_repository,
    )
    formal_control = FormalCenterControlPlane(
        control_repository,
        redis_coordination,
        ledger,
        projector,
        progression=mission_progressor,
    )

    trace_runtime_authority = FormalTraceRuntimeAuthority(formal_control, governance_repository)
    traceability_ingestion = R1BackedCenterTraceabilityIngestion(
        traceability_repository,
        ledger=ledger,
        control_plane=trace_runtime_authority,
        attempt_snapshot_resolver=trace_runtime_authority.resolve_current_attempt,
    )
    # R1 is runtime truth. Repair any PostgreSQL TraceGraph projection that was
    # interrupted after canonical acceptance but before DB commit. This runs
    # before HTTP exposure and fails startup on malformed canonical evidence.
    trace_replay_result = traceability_ingestion.replay_canonical_runtime_observations()

    recovery_coordinator = LeaseRecoveryCoordinator(control_repository, recovery_repository, redis_coordination, ledger)
    artifact_store = FileArtifactStore(settings.artifact_root, artifact_repository)
    artifact_service = FormalArtifactService(artifact_store, formal_control, projector)

    app = create_app(
        settings=settings,
        postgres=postgres,
        redis_coordination=redis_coordination,
        governance_projection=projection,
        formal_control=formal_control,
        recovery_coordinator=recovery_coordinator,
        artifact_service=artifact_service,
        product_application=None,
        delivery_repository=delivery_repository,
        revision_repository=revision_repository,
        test_round_repository=test_round_repository,
    )
    app.state.r1_ledger = ledger
    app.state.runtime_invalidation_projector = runtime_invalidation_projector
    app.state.runtime_invalidation_replay_result = runtime_invalidation_replay_result
    app.state.runtime_invalidation_coordinator = runtime_invalidation_coordinator
    app.state.prepared_attempt_repository = prepared_attempt_repository
    app.state.executable_spec_repository = executable_spec_repository
    app.state.prepared_attempts = prepared_attempts
    app.state.executable_readiness = executable_readiness
    app.state.traceability_repository = traceability_repository
    app.state.trace_runtime_authority = trace_runtime_authority
    app.state.traceability_ingestion = traceability_ingestion
    app.state.trace_replay_result = trace_replay_result
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
    app.state.mission_service = mission_service
    app.state.mission_progressor = mission_progressor
    app.state.formal_control = formal_control
    app.state.recovery_coordinator = recovery_coordinator
    app.state.artifact_store = artifact_store
    app.state.artifact_service = artifact_service
    return app


app = build_app()
