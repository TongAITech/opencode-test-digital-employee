"""R3.1 requirement, coverage, and traceability intelligence extension."""

from .contracts import (
    ACCEPTED_SOURCE_KINDS,
    COVERAGE_GAP_KINDS,
    DERIVE_REQUIREMENT_COVERAGE,
    GAP_UNCOVERED,
    MAPPING_STATES,
    DerivationIdentity,
    DerivationRequest,
    R31Error,
    R31State,
)
from .extension import r3_1_extension
from .service import R31ApplicationService, R31OperationResult

__all__ = [
    "ACCEPTED_SOURCE_KINDS",
    "COVERAGE_GAP_KINDS",
    "DERIVE_REQUIREMENT_COVERAGE",
    "GAP_UNCOVERED",
    "MAPPING_STATES",
    "DerivationIdentity",
    "DerivationRequest",
    "R31ApplicationService",
    "R31Error",
    "R31OperationResult",
    "R31State",
    "r3_1_extension",
]
