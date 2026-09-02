"""R3.2 change-impact and independent coverage reconciliation extension."""

from .contracts import (
    CHANGE_IMPACT_DERIVED,
    COMMAND_TYPES,
    CODE_INTELLIGENCE_STATUSES,
    COMPARE_MODES,
    DERIVE_CHANGE_IMPACT_RECONCILIATION,
    EVENT_TYPES,
    IMPACT_RESOLUTIONS,
    RECONCILIATION_CREATED,
    RECONCILIATION_REUSED,
    ChangeImpactDerivation,
    ChangeImpactIdentity,
    ChangeImpactObligation,
    ChangeImpactRequest,
    ChangedFileFact,
    ChangedSymbolFact,
    CodeIntelligenceEnvelope,
    CompareIdentity,
    ImpactEdge,
    ImpactedSurface,
    R31Reference,
    R32Error,
    R32State,
    ReconciliationItem,
    ReconciliationSnapshot,
    RepositoryCompareRequest,
)
from .engine import (
    build_derivation,
    derive_change_obligations,
    r31_provenance_bundle_digest,
    reconcile,
    validate_r31_reference,
)
from .extension import r3_2_extension
from .providers import CodeIntelligenceProvider, GitCodeIntelligenceProvider, MappingCodeIntelligenceProvider
from .service import R32ApplicationService, R32OperationResult, request_from_mapping

__all__ = [
    "CHANGE_IMPACT_DERIVED", "COMMAND_TYPES", "CODE_INTELLIGENCE_STATUSES", "COMPARE_MODES",
    "DERIVE_CHANGE_IMPACT_RECONCILIATION", "EVENT_TYPES", "IMPACT_RESOLUTIONS", "RECONCILIATION_CREATED", "RECONCILIATION_REUSED",
    "ChangeImpactDerivation", "ChangeImpactIdentity", "ChangeImpactObligation", "ChangeImpactRequest",
    "ChangedFileFact", "ChangedSymbolFact", "CodeIntelligenceEnvelope", "CompareIdentity", "ImpactEdge", "ImpactedSurface",
    "R31Reference", "R32Error", "R32State", "ReconciliationItem", "ReconciliationSnapshot", "RepositoryCompareRequest",
    "build_derivation", "derive_change_obligations", "r31_provenance_bundle_digest", "reconcile", "validate_r31_reference",
    "r3_2_extension", "CodeIntelligenceProvider", "GitCodeIntelligenceProvider", "MappingCodeIntelligenceProvider",
    "R32ApplicationService", "R32OperationResult", "request_from_mapping",
]
