"""R3.7 explicit test sufficiency and rebuildable testing operations projections."""

from .contracts import (
    ARCHITECTURE_BASELINE_REF,
    COMMAND_TYPES,
    DECISION_SCOPE_KINDS,
    DECISION_STATES,
    EVIDENCE_CLASSES,
    EVIDENCE_CONFIDENCE_STATES,
    EVENT_TYPES,
    EXTENSION_ID,
    EXTENSION_VERSION,
    HARD_MAX_BYTES,
    HARD_MAX_HOPS,
    HARD_MAX_ITEMS,
    PROJECTION_TYPES,
    R37_EVALUATE_TEST_SUFFICIENCY,
    R37_SEMANTIC_REUSE,
    R37EvaluationInput,
    R37State,
    RemainingRiskItem,
    SemanticReuse,
    TestSufficiencyDecision,
    WorkSetReceipt,
    WorkSetRequest,
    EvidenceConfidence,
)
from .errors import R37Error
from .evaluator import EvaluationResult, evaluate_test_sufficiency, normalize_coverage
from .extension import r3_7_extension
from .projections import (
    ProjectionEnvelope,
    R37ProjectionContribution,
    build_operations_projection,
    coverage_center,
    defect_linkage,
    evidence_linkage,
    test_case_center,
    test_runs,
    testing_report,
)
from .service import R37ApplicationService, R37OperationResult
from .workset import TypedRetrievalProvider, retrieve_workset

__all__ = [
    "ARCHITECTURE_BASELINE_REF", "COMMAND_TYPES", "DECISION_SCOPE_KINDS", "DECISION_STATES", "EVIDENCE_CLASSES",
    "EVIDENCE_CONFIDENCE_STATES", "EVENT_TYPES", "EXTENSION_ID", "EXTENSION_VERSION", "HARD_MAX_BYTES", "HARD_MAX_HOPS",
    "HARD_MAX_ITEMS", "PROJECTION_TYPES", "R37_EVALUATE_TEST_SUFFICIENCY", "R37_SEMANTIC_REUSE", "R37EvaluationInput",
    "R37State", "RemainingRiskItem", "SemanticReuse", "TestSufficiencyDecision", "WorkSetReceipt", "WorkSetRequest",
    "EvidenceConfidence", "R37Error", "EvaluationResult", "evaluate_test_sufficiency", "normalize_coverage", "r3_7_extension",
    "ProjectionEnvelope", "R37ProjectionContribution", "build_operations_projection", "coverage_center", "defect_linkage",
    "evidence_linkage", "test_case_center", "test_runs", "testing_report", "R37ApplicationService", "R37OperationResult",
    "TypedRetrievalProvider", "retrieve_workset",
]
