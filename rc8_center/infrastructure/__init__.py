"""Formal RC8 Center infrastructure adapters.

Domain/application code depends on repository/coordination behavior, not on
FastAPI/SQLAlchemy/redis-py details.
"""

from .postgres import Base, PostgresStore, build_engine
from .postgres_artifact import ArtifactMetadataRow, PostgresArtifactRepository
from .postgres_control import CapabilityRow, NodeRow, PostgresCenterRepository, WorkItemRow
from .postgres_governance import PostgresCoverageRepository, PostgresGovernanceRepository
from .postgres_recovery import PostgresRecoveryRepository, RecoveryIncidentRow
from .redis_coordination import RedisCoordination

__all__ = [
    "ArtifactMetadataRow",
    "Base",
    "CapabilityRow",
    "NodeRow",
    "PostgresArtifactRepository",
    "PostgresCenterRepository",
    "PostgresCoverageRepository",
    "PostgresGovernanceRepository",
    "PostgresRecoveryRepository",
    "PostgresStore",
    "RecoveryIncidentRow",
    "RedisCoordination",
    "WorkItemRow",
    "build_engine",
]
