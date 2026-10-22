"""RC8 formal Center app with autonomous claim-next routes enabled.

This is an additive construction entrypoint while the existing formal stack
continues regression verification. It reuses the same formal_app instance and
only attaches the claim-next API; no second persistence/lease truth is created.
"""
from rc8_center.api.claim_routes import register_claim_routes
from rc8_center.formal_app import app

register_claim_routes(app)

__all__ = ["app"]
