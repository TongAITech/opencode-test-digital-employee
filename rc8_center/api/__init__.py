"""Formal FastAPI adapter package for RC8 Center."""
from __future__ import annotations

from typing import Optional

from .delivery_routes import register_delivery_routes
from .fastapi_app import create_app as _create_app
from .test_round_routes import register_test_round_routes


def create_app(
    *,
    delivery_repository: Optional[object] = None,
    test_round_repository: Optional[object] = None,
    **kwargs,
):
    """Build the formal API and attach the production-date task model.

    ``ProductionBatch`` is the production date. ``TestRound`` is a testing
    round inside that same date; registering both route sets keeps these
    concepts explicit instead of encoding round history in opaque payloads.
    """
    app = _create_app(**kwargs)
    app.state.delivery_repository = delivery_repository
    app.state.test_round_repository = test_round_repository
    register_delivery_routes(app)
    register_test_round_routes(app)
    return app


__all__ = ["create_app"]