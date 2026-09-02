"""R2.6 Human Gate and Continuation additive runtime extension."""

from .boundary import ALLOW, BLOCK, ROUTE_REVISION, WAIT, HumanGateBoundaryDecision, evaluate_human_gate_boundary, run_r2_4_if_allowed
from .composition import compose_extensions, compose_r2_6_runtime
from .contracts import *
from .extension import human_gate_extension, r2_6_extension
from .service import HumanGateApplicationService, HumanGateService, R26ApplicationService, R26OperationResult

__all__ = [
    "ALLOW", "BLOCK", "ROUTE_REVISION", "WAIT", "HumanGateBoundaryDecision", "evaluate_human_gate_boundary", "run_r2_4_if_allowed",
    "compose_extensions", "compose_r2_6_runtime", "human_gate_extension", "r2_6_extension",
    "HumanGateApplicationService", "HumanGateService", "R26ApplicationService", "R26OperationResult",
]
