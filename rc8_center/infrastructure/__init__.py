"""Formal RC8 Center infrastructure adapters.

Domain/application code depends on repository/coordination behavior, not on
FastAPI/SQLAlchemy/redis-py details.
"""

from .postgres import Base, PostgresStore, build_engine
from .postgres_artifact import ArtifactMetadataRow, PostgresArtifactRepository
from .postgres_governance import PostgresCoverageRepository, PostgresGovernanceRepository
from .redis_coordination import RedisCoordination

__all__ = [
    "ArtifactMetadataRow",
    "Base",
    "PostgresArtifactRepository",
    "PostgresCoverageRepository",
    "PostgresGovernanceRepository",
    "PostgresStore",
    "RedisCoordination",
    "build_engine",
]
