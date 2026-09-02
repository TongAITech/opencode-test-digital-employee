"""R3.3 Test Strategy, Layer Selection and Standard Case Design extension."""

from .contracts import (
    CASE_BATCH_DESIGNED,
    COMMAND_TYPES,
    CREATE_TEST_STRATEGY,
    DESIGN_CASE_BATCH,
    DESIGN_REUSED,
    EVENT_TYPES,
    LAYER_DECISIONS,
    LAYER_IDS,
    MAPPING_RELATIONS,
    MAPPING_STATES,
    RISK_BANDS,
    RISK_DIMENSIONS,
    STRATEGY_CREATED,
    AutomationMapping,
    BatchDesignRequest,
    CaseBatch,
    LayerDecision,
    R32Reference,
    R33Error,
    R33State,
    RiskVector,
    StandardTestCase,
    StrategyRequest,
    TestPoint,
    TestStrategy,
)
from .engine import build_risk_vector, build_strategy, design_case_batch, validate_source_references
from .extension import r3_3_extension
from .service import R33ApplicationService, R33OperationResult, batch_request_from_mapping, request_from_mapping

__all__ = [
    "CASE_BATCH_DESIGNED", "COMMAND_TYPES", "CREATE_TEST_STRATEGY", "DESIGN_CASE_BATCH",
    "DESIGN_REUSED", "EVENT_TYPES", "LAYER_DECISIONS", "LAYER_IDS", "MAPPING_RELATIONS",
    "MAPPING_STATES", "RISK_BANDS", "RISK_DIMENSIONS", "STRATEGY_CREATED",
    "AutomationMapping", "BatchDesignRequest", "CaseBatch", "LayerDecision", "R32Reference",
    "R33Error", "R33State", "RiskVector", "StandardTestCase", "StrategyRequest", "TestPoint",
    "TestStrategy", "build_risk_vector", "build_strategy", "design_case_batch",
    "validate_source_references", "r3_3_extension", "R33ApplicationService", "R33OperationResult",
    "batch_request_from_mapping", "request_from_mapping",
]

