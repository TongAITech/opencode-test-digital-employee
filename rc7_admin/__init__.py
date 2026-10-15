"""RC7 administration platform backed only by the durable R1 projection."""

from .projection import AdminProjection, AdminProjectionError
from .server import AdminApplication, create_server

__all__ = ["AdminApplication", "AdminProjection", "AdminProjectionError", "create_server"]
