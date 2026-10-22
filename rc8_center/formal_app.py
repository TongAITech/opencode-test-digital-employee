"""Production-oriented RC8 Center application factory.

Formal runtime chain:
Node -> PostgreSQL identity/state + Redis active lease authorization
-> R1 Event Stream -> replayable projector -> PostgreSQL governance/coverage
projection -> FastAPI -> Vue.

Lost Redis lease is not blind-replayed: the recovery coordinator records a
durable incident and requires either a provably safe reset or an explicit
evidence-backed recovery decision.
"""
from __future__ import annotations

from pathlib import Path

from rc8_runtime import CentralR1RuntimeLedger
from rc8_center.api import create_app
from rc8_center.formal_control import FormalCenterControlPlane
from rc8_center.formal_settings import CenterSettings
from rc8_center.governance_event_projector import GovernanceEventProjector
from rc8_center.governance_projection import GovernanceProjectionService
from rc8_center.infrastructure import (
    PostgresArtifactRepository,
    PostgresCenterRepository,
    PostgresCoverageRepository,
    PostgresGovernanceRepository,
    PostgresRecoveryRepository,
    PostgresStore,
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

    r1_path = Path(settings.r1_root) / "event-stream.jsonl"
    ledger = CentralR1RuntimeLedger(str(r1_path))
    projector = GovernanceEventProjector(ledger, governance_repository, coverage_repository, artifact_repository)
    replay_result = projector.replay()
    projection = GovernanceProjectionService(governance_repository, coverage_repository)
    formal_control = FormalCenterControlPlane(
        control_repository,
        redis_coordination,
        ledger,
        projector,
    )
    recovery_coordinator = LeaseRecoveryCoordinator(
        control_repository,
        recovery_repository,
        redis_coordination,
        ledger,
    )

    app = create_app(
        settings=settings,
        postgres=postgres,
        redis_coordination=redis_coordination,
        governance_projection=projection,
        formal_control=formal_control,
        recovery_coordinator=recovery_coordinator,
        product_application=None,
    )
    app.state.r1_ledger = ledger
    app.state.governance_projector = projector
    app.state.governance_replay_result = replay_result
    app.state.governance_repository = governance_repository
    app.state.coverage_repository = coverage_repository
    app.state.artifact_repository = artifact_repository
    app.state.control_repository = control_repository
    app.state.recovery_repository = recovery_repository
    app.state.formal_control = formal_control
    app.state.recovery_coordinator = recovery_coordinator
    return app


app = build_app()
