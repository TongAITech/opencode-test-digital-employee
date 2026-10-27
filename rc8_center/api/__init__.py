"""Formal FastAPI adapter package for RC8 Center."""
from __future__ import annotations

from typing import Optional

from rc8_center.traceability_query import TraceabilityQueryService

from .artifact_read_routes import register_artifact_read_routes
from .claim_routes import register_claim_routes
from .defect_routes import register_defect_routes
from .delivery_routes import register_delivery_routes
from .executable_readiness_routes import register_executable_readiness_routes
from .execution_bundle_routes import register_execution_bundle_routes
from .failure_routes import register_failure_routes
from .fastapi_app import create_app as _create_app
from .n7_tool_routes import register_n7_tool_routes
from .prepared_attempt_routes import register_prepared_attempt_routes
from .revision_routes import register_revision_routes
from .runtime_sequence_routes import register_runtime_sequence_routes
from .test_round_routes import register_test_round_routes
from .traceability_routes import register_traceability_routes


def create_app(
    *,
    delivery_repository: Optional[object] = None,
    revision_repository: Optional[object] = None,
    test_round_repository: Optional[object] = None,
    traceability_repository: Optional[object] = None,
    traceability_query_service: Optional[object] = None,
    **kwargs,
):
    """Build the formal API with production-date, TestRounds and impact traceability."""
    app = _create_app(**kwargs)
    app.state.delivery_repository = delivery_repository
    postgres = kwargs.get("postgres")
    if revision_repository is None and postgres is not None:
        from rc8_center.infrastructure import PostgresRequirementRevisionRepository

        revision_repository = PostgresRequirementRevisionRepository(postgres)
    if traceability_repository is None and postgres is not None:
        from rc8_center.infrastructure import PostgresTraceabilityRepository

        traceability_repository = PostgresTraceabilityRepository(postgres)
    if traceability_query_service is None and traceability_repository is not None:
        traceability_query_service = TraceabilityQueryService(traceability_repository)

    app.state.revision_repository = revision_repository
    app.state.test_round_repository = test_round_repository
    app.state.traceability_repository = traceability_repository
    app.state.traceability_query_service = traceability_query_service

    register_delivery_routes(app)
    register_revision_routes(app)
    register_test_round_routes(app)
    register_claim_routes(app)
    register_failure_routes(app)
    register_defect_routes(app)
    register_runtime_sequence_routes(app)
    register_artifact_read_routes(app)
    register_traceability_routes(app)
    register_prepared_attempt_routes(app)
    register_executable_readiness_routes(app)
    register_execution_bundle_routes(app)
    register_n7_tool_routes(app)
    return app


__all__ = ["create_app"]
