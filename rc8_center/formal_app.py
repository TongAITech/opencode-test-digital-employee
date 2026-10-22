"""Production-oriented RC8 Center application factory.

Formal chain:
R1 Event Stream -> replayable projector -> PostgreSQL governance/coverage
projection -> FastAPI -> Vue.

Node runtime-event ingestion is not exposed here until the formal PostgreSQL
WorkItem repository + Redis lease authorization path is complete; this prevents
bypassing ownership just to make the API look finished.
"""
from __future__ import annotations

from pathlib import Path

from rc8_runtime import CentralR1RuntimeLedger
from rc8_center.api import create_app
from rc8_center.formal_settings import CenterSettings
from rc8_center.governance_event_projector import GovernanceEventProjector
from rc8_center.governance_projection import GovernanceProjectionService
from rc8_center.infrastructure import (
    PostgresArtifactRepository,
    PostgresCoverageRepository,
    PostgresGovernanceRepository,
    PostgresStore,
    RedisCoordination,
    build_engine,
)


def build_app():
    settings = CenterSettings()
    postgres = PostgresStore(build_engine(settings.database_url))
    redis_coordination = RedisCoordination.from_url(settings.redis_url)
    governance_repository = PostgresGovernanceRepository(postgres)
    coverage_repository = PostgresCoverageRepository(postgres)
    artifact_repository = PostgresArtifactRepository(postgres)

    r1_path = Path(settings.r1_root) / "event-stream.jsonl"
    ledger = CentralR1RuntimeLedger(str(r1_path))
    projector = GovernanceEventProjector(
        ledger,
        governance_repository,
        coverage_repository,
        artifact_repository,
    )
    replay_result = projector.replay()
    projection = GovernanceProjectionService(governance_repository, coverage_repository)

    app = create_app(
        settings=settings,
        postgres=postgres,
        redis_coordination=redis_coordination,
        governance_projection=projection,
        product_application=None,
    )
    app.state.r1_ledger = ledger
    app.state.governance_projector = projector
    app.state.governance_replay_result = replay_result
    app.state.governance_repository = governance_repository
    app.state.coverage_repository = coverage_repository
    app.state.artifact_repository = artifact_repository
    return app


app = build_app()
