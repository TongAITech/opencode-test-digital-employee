"""Formal FastAPI adapter package for RC8 Center."""
from __future__ import annotations

from typing import Optional

from .claim_routes import register_claim_routes
from .delivery_routes import register_delivery_routes
from .fastapi_app import create_app as _create_app
from .test_round_routes import register_test_round_routes


def create_app(
    *,
    delivery_repository: Optional[object] = None,
    test_round_repository: Optional[object] = None,
    **kwargs,
):
    """Build the formal API with production-date, TestRound and claim-next entry.

    ``ProductionBatch`` is the production date. ``TestRound`` is a testing
    round inside that same date. Autonomous claim-next is part of the formal
    Center product surface, not a separate experimental app, so the Docker
    entrypoint and Reality-CI exercise the same routing contract.
    """
    app = _create_app(**kwargs)
    app.state.delivery_repository = delivery_repository
    app.state.test_round_repository = test_round_repository
    register_delivery_routes(app)
    register_test_round_routes(app)
    register_claim_routes(app)
    return app


__all__ = ["create_app"]
