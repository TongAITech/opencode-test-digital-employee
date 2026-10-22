"""Production-oriented RC8 Center application factory.

Formal runtime chain:
Node -> PostgreSQL identity/state + Redis active lease authorization
-> R1 Event Stream -> replayable projector -> PostgreSQL governance/coverage
projection -> evidence-gated Mission progression -> FastAPI -> Vue.

Artifact chain:
lease-authorized manifest -> resumable byte upload -> exact size/SHA-256 verify
-> atomic AVAILABLE publish -> R1 replay -> evidence-dependent projection.

Requirement truth chain:
RequirementMaster -> RequirementRevision -> ScopeRevision -> DeliveryScope ->
TestRound frozen revision snapshot -> Stage/WorkItem/Evidence lineage.
"""
from __future__ import annotations

from pathlib import Path

from rc8_runtime import CentralR1RuntimeLedger
from rc8_center.api import create_app
from rc8_center.artifacts import FileArtifactStore
from rc8_center.requirement_loop_progression import RequirementLoopProgressor
from rc8_center.formal_artifacts import FormalArtifactService
from rc8_center.formal_control import FormalCenterControlPlane
from rc8_center.formal_settings import CenterSettings
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
    RedisCoordination,
    build_engine,
)
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

    r1_path = Path(settings.r1_root) / "event-stream.jsonl"
    ledger = CentralR1RuntimeLedger(str(r1_path))
    projector = ScopeAwareGovernanceEventProjector(
        ledger,
        governance_repository,
        coverage_repository,
        artifact_repository,
    )
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
    recovery_coordinator = LeaseRecoveryCoordinator(
        control_repository,
        recovery_repository,
        redis_coordination,
        ledger,
    )
    artifact_store = FileArtifactStore(settings.artifact_root, artifact_repository)
    artifact_service = FormalArtifactService(
        artifact_store,
        formal_control,
        projector,
    )

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
