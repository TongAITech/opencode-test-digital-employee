"""Formal FastAPI adapter package for RC8 Center."""
from __future__ import annotations

from typing import Optional

from .delivery_routes import register_delivery_routes
from .fastapi_app import create_app as _create_app


def create_app(*, delivery_repository: Optional[object] = None, **kwargs):
    """Build the formal API and attach the production-batch task model.

    Keeping this wrapper outside ``fastapi_app`` avoids coupling the existing
    runtime/lease/artifact adapter to product task organization while still
    making the routes part of the formal Center application.
    """
    app = _create_app(**kwargs)
    app.state.delivery_repository = delivery_repository
    register_delivery_routes(app)
    return app


__all__ = ["create_app"]