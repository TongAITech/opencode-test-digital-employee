"""R4.2 continuous trigger, impact, and R2 revision bridge extension."""

from .contracts import *
from .errors import *
from .extension import r4_2_extension
from .service import R42ApplicationService, R42ContinuationResult, R42OperationResult, compose_r4_2_runtime
from .source_adapters import SourceObservation, adapt_typed_reference, normalize_manual_source, normalize_source_observation

__all__ = [
    "R42ApplicationService", "R42ContinuationResult", "R42Error", "R42OperationResult", "SourceObservation",
    "adapt_typed_reference", "compose_r4_2_runtime", "normalize_manual_source", "normalize_source_observation", "r4_2_extension",
]
__all__ += [name for name in globals() if not name.startswith("_") and name not in set(__all__)]
