"""R4.3 confirmed-defect fix-resolution lifecycle extension."""

from .contracts import *
from .errors import *
from .extension import r4_3_extension
from .r3_6_adapter import R36AssessmentAdmission, validate_r3_6_reference
from .service import R43ApplicationService, R43OperationResult, compose_r4_3_runtime
from .source_adapters import (
    adapt_typed_reference,
    normalize_legacy_source,
    normalize_manual_source,
    normalize_source_observation,
)

__all__ = [
    "R43ApplicationService", "R43OperationResult", "R43Error", "compose_r4_3_runtime", "r4_3_extension",
    "R36AssessmentAdmission", "validate_r3_6_reference", "adapt_typed_reference", "normalize_legacy_source",
    "normalize_manual_source", "normalize_source_observation",
]
__all__ += [name for name in globals() if not name.startswith("_") and name not in set(__all__)]
