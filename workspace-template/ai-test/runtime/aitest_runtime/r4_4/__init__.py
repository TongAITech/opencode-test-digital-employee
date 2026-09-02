"""R4.4 post-fix validation and targeted regression closure extension."""

from .contracts import *
from .errors import *
from .execution_bridge import BridgeResult, R44ExecutionBridge
from .extension import r4_4_extension
from .reducer import R44ReducerContribution, R44State
from .service import R44ApplicationService, R44OperationResult, compose_r4_4_runtime, make_binding, make_cycle, make_intent, make_workset

__all__ = [
    "R44ApplicationService", "R44OperationResult", "R44ExecutionBridge", "BridgeResult", "R44State",
    "R44ReducerContribution", "R44Error", "r4_4_extension", "compose_r4_4_runtime", "make_cycle",
    "make_workset", "make_binding", "make_intent",
]
__all__ += [name for name in globals() if not name.startswith("_") and name not in set(__all__)]
