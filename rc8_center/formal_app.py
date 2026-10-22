"""Production-oriented RC8 Center application factory.

This module wires formal infrastructure only. Existing domain/application
services stay independently testable and are progressively injected here as
W-A/W-B product slices migrate off the W1 stdlib adapter.
"""
from __future__ import annotations

from rc8_center.api import create_app
from rc8_center.formal_settings import CenterSettings
from rc8_center.infrastructure import PostgresStore, RedisCoordination, build_engine


def build_app():
    settings = CenterSettings()
    postgres = PostgresStore(build_engine(settings.database_url))
    redis_coordination = RedisCoordination.from_url(settings.redis_url)
    return create_app(
        settings=settings,
        postgres=postgres,
        redis_coordination=redis_coordination,
        product_application=None,
    )


app = build_app()
