"""R3.6 Defect Hunter and evidence-backed RCA extension.

R3.6 is additive over the frozen R1 Event/Evidence lineage, R3.4 oracle/result
refs, R3.5 Page/Journey refs, and R3.E1 Knowledge retrieval. It does not own
legacy defect truth or a second Event/Evidence/Knowledge/Session store.
"""

from .contracts import (
    ANOMALY_RECORDED,
    ASSESS_DEFECT_TRUTH,
    ASSESS_FALSE_POSITIVE,
    CANDIDATE_CREATED,
    CHECKPOINT_RECORDED,
    COMMAND_TYPES,
    CREATE_DEFECT_CANDIDATE,
    CROSS_SOURCE_CORRELATED,
    DEFECT_TRUTH_ASSESSED,
    EVALUATE_REPRODUCIBILITY,
    EVIDENCE_ASSESSED,
    EVIDENCE_DEEPENING_REQUESTED,
    EVENT_TYPES,
    EXTENSION_ID,
    EXTENSION_VERSION,
    FAILURE_CLASSIFICATIONS,
    FALSE_POSITIVE_ASSESSED,
    RCA_RECORDED,
    RECORD_CROSS_SOURCE_CORRELATION,
    RECORD_EVIDENCE_ASSESSMENT,
    RECORD_INVESTIGATION_CHECKPOINT,
    RECORD_RCA,
    RECORD_TEST_ANOMALY,
    REPRODUCIBILITY_EVALUATED,
    REQUEST_EVIDENCE_DEEPENING,
    SEMANTIC_REUSE,
    SEMANTIC_REUSE_RECORDED,
    TestAnomaly,
    DefectCandidate,
    InvestigationWorkSetRequest,
    InvestigationWorkSetReceipt,
    EvidenceDeepeningReceipt,
    EvidenceAssessment,
    CrossSourceCorrelation,
    ReproducibilityAssessment,
    FalsePositiveAssessment,
    DefectAssessment,
    RCARecord,
    InvestigationCheckpoint,
    SemanticReuse,
    R36State,
)
from .errors import R36Error
from .extension import r3_6_extension
from .service import R36ApplicationService, R36OperationResult
from .workset import TypedRetrievalProvider, retrieve_workset

__all__ = [
    "ANOMALY_RECORDED", "ASSESS_DEFECT_TRUTH", "ASSESS_FALSE_POSITIVE", "CANDIDATE_CREATED",
    "CHECKPOINT_RECORDED", "COMMAND_TYPES", "CREATE_DEFECT_CANDIDATE", "CROSS_SOURCE_CORRELATED",
    "DEFECT_TRUTH_ASSESSED", "EVALUATE_REPRODUCIBILITY", "EVIDENCE_ASSESSED",
    "EVIDENCE_DEEPENING_REQUESTED", "EVENT_TYPES", "EXTENSION_ID", "EXTENSION_VERSION",
    "FAILURE_CLASSIFICATIONS", "FALSE_POSITIVE_ASSESSED", "RCA_RECORDED",
    "RECORD_CROSS_SOURCE_CORRELATION", "RECORD_EVIDENCE_ASSESSMENT",
    "RECORD_INVESTIGATION_CHECKPOINT", "RECORD_RCA", "RECORD_TEST_ANOMALY",
    "REPRODUCIBILITY_EVALUATED", "REQUEST_EVIDENCE_DEEPENING", "SEMANTIC_REUSE",
    "SEMANTIC_REUSE_RECORDED", "TestAnomaly", "DefectCandidate", "InvestigationWorkSetRequest",
    "InvestigationWorkSetReceipt", "EvidenceDeepeningReceipt", "EvidenceAssessment",
    "CrossSourceCorrelation", "ReproducibilityAssessment", "FalsePositiveAssessment",
    "DefectAssessment", "RCARecord", "InvestigationCheckpoint", "SemanticReuse", "R36State",
    "R36Error", "R36ApplicationService", "R36OperationResult", "TypedRetrievalProvider",
    "retrieve_workset", "r3_6_extension",
]
