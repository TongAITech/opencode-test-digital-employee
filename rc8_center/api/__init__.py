"""Formal FastAPI adapter package for RC8 Center."""
from __future__ import annotations

from typing import Optional

from .claim_routes import register_claim_routes
from .delivery_routes import register_delivery_routes
from .fastapi_app import create_app as _create_app
from .revision_routes import register_revision_routes
from .test_round_routes import register_test_round_routes


def create_app(
    *,
    delivery_repository: Optional[object] = None,
    revision_repository: Optional[object] = None,
    test_round_repository: Optional[object] = None,
    **kwargs,
):
    """Build the formal API with production-date, revisions and TestRounds."""
    app = _create_app(**kwargs)
    app.state.delivery_repository = delivery_repository
    if revision_repository is None and kwargs.get("postgres") is not None:
        from rc8_center.infrastructure import PostgresRequirementRevisionRepository

        revision_repository = PostgresRequirementRevisionRepository(kwargs["postgres"])
    app.state.revision_repository = revision_repository
    app.state.test_round_repository = test_round_repository
    register_delivery_routes(app)
    register_revision_routes(app)
    register_test_round_routes(app)
    register_claim_routes(app)
    return app


__all__ = ["create_app"]