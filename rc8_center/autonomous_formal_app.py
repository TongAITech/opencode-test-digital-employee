"""Compatibility alias for the formal RC8 Center application.

Autonomous claim-next is now part of ``rc8_center.formal_app`` itself so Docker,
CI and office Nodes use one product entrypoint and one persistence/lease truth.
This module remains only for callers that already reference the historical
specialized module path.
"""
from rc8_center.formal_app import app

__all__ = ["app"]
