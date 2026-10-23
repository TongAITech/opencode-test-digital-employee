"""Formal RC8 Center infrastructure adapters.

Domain/application code depends on repository/coordination behavior, not on
FastAPI/SQLAlchemy/redis-py details.
"""

from .postgres import Base, PostgresStore, build_engine
from .postgres_artifact import ArtifactMetadataRow, PostgresArtifactRepository
from .postgres_control import CapabilityRow, NodeRow, PostgresCenterRepository, StageWorkItemLinkRow, WorkItemRow
from .postgres_delivery import PostgresRequirementDeliveryRepository, ProductionBatchRow, RequirementDeliveryRow, RequirementDeliveryScopeRow, RequirementRow
from .postgres_governance import PostgresCoverageRepository, PostgresGovernanceRepository
from .postgres_provider_recovery import PostgresProviderRecoveryCheckpointRepository, ProviderRecoveryCheckpointRow, StoredRecoveryCheckpoint
from .postgres_recovery import PostgresRecoveryRepository, RecoveryIncidentRow
from .postgres_revision import DeliveryRevisionBindingRow, PostgresRequirementRevisionRepository, RequirementRevisionRow, ScopeRevisionRow
from .postgres_test_round import PostgresTestRoundRepository, TestRoundDeliveryRow, TestRoundRow
from .postgres_traceability import CodeSourceSnapshotRow, PostgresTraceabilityRepository, TraceEdgeRow, TraceEvidenceRow, TraceNodeRow, TraceabilityGraphRow
from .redis_coordination import RedisCoordination

__all__ = [
    "ArtifactMetadataRow", "Base", "CapabilityRow", "CodeSourceSnapshotRow", "DeliveryRevisionBindingRow", "NodeRow",
    "PostgresArtifactRepository", "PostgresCenterRepository", "PostgresCoverageRepository", "PostgresGovernanceRepository",
    "PostgresProviderRecoveryCheckpointRepository", "PostgresRecoveryRepository", "PostgresRequirementDeliveryRepository",
    "PostgresRequirementRevisionRepository", "PostgresStore", "PostgresTestRoundRepository", "PostgresTraceabilityRepository",
    "ProductionBatchRow", "ProviderRecoveryCheckpointRow", "RecoveryIncidentRow", "RedisCoordination", "RequirementDeliveryRow",
    "RequirementDeliveryScopeRow", "RequirementRevisionRow", "RequirementRow", "ScopeRevisionRow", "StageWorkItemLinkRow",
    "StoredRecoveryCheckpoint", "TestRoundDeliveryRow", "TestRoundRow", "TraceEdgeRow", "TraceEvidenceRow", "TraceNodeRow",
    "TraceabilityGraphRow", "WorkItemRow", "build_engine",
]
