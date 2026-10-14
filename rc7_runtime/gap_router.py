"""Deterministic cross-node Gap routing for RC7.

Known failure/gap categories cannot be silently rerouted by a worker. Unknown
categories remain extensible but are explicitly marked as requiring policy
review instead of being treated as fully-governed routes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

from .models import Gap


class GapRoutingError(RuntimeError):
    pass


ROUTE_POLICY: Dict[str, Tuple[str, ...]] = {
    "MISSING_BOUNDARY": ("REQUIREMENT_ANALYSIS",),
    "TRACEABILITY_MISSING": ("REQUIREMENT_ANALYSIS",),
    "UNTRACEABLE_FACT": ("REQUIREMENT_ANALYSIS",),
    "UNTESTABLE_REQUIREMENT": ("REQUIREMENT_ANALYSIS",),
    "EVIDENCE_MISSING": ("REQUIREMENT_ANALYSIS",),
    "REQUIREMENT_REVIEW_GAP": ("REQUIREMENT_ANALYSIS",),
    "REQUIREMENT_AMBIGUITY": ("REQUIREMENT_ANALYSIS",),
    "EVALUATOR_INDEPENDENCE_FAIL": ("RUNTIME",),
    "INDEPENDENT_EVALUATION_MISSING": ("RUNTIME",),
    "API_ROUTE_DEFECT": ("CODE_ANALYSIS",),
    "CODE_ANALYSIS_DEFECT": ("CODE_ANALYSIS",),
    "RUNTIME_DISCOVERED_CODE_PATH": ("CODE_ANALYSIS",),
    "REQUIREMENT_MAPPING_INVALID": ("CODE_ANALYSIS",),
    "CODE_EVIDENCE_MISSING": ("CODE_ANALYSIS",),
    "CHANGESET_MISSING": ("CODE_ANALYSIS",),
    "SOURCE_REVISION_MISSING": ("CODE_ANALYSIS",),
    "CHANGED_SYMBOL_UNANALYZED": ("CODE_ANALYSIS",),
    "REQUIREMENT_MAPPING_MISSING": ("CODE_ANALYSIS",),
    "CODEGRAPH_INCOMPLETE": ("CODE_ANALYSIS",),
    "GIT_EVIDENCE_MISSING": ("CODE_ANALYSIS",),
    "CODE_REVIEW_GAP": ("CODE_ANALYSIS",),
    "TEST_DESIGN_SCHEMA_INVALID": ("TEST_DESIGN",),
    "TEST_DESIGN_TRACEABILITY_INVALID": ("TEST_DESIGN",),
    "UNCOVERED_REQUIREMENT": ("TEST_DESIGN",),
    "UNCOVERED_BUSINESS_RULE": ("TEST_DESIGN",),
    "MISSING_POSITIVE_CASE": ("TEST_DESIGN",),
    "MISSING_NEGATIVE_CASE": ("TEST_DESIGN",),
    "UNCOVERED_BOUNDARY": ("TEST_DESIGN",),
    "MISSING_STATE_TRANSITION": ("TEST_DESIGN",),
    "MISSING_PERMISSION_CASE": ("TEST_DESIGN",),
    "MISSING_DATA_VARIANT": ("TEST_DESIGN",),
    "UNCOVERED_CODE_BRANCH": ("TEST_DESIGN",),
    "MISSING_SIDE_EFFECT_CASE": ("TEST_DESIGN",),
    "MISSING_REGRESSION_CASE": ("TEST_DESIGN",),
    "UNCOVERED_RISK": ("TEST_DESIGN",),
    "UNCOVERED_TEST_OBLIGATION": ("TEST_DESIGN",),
    "ORACLE_INCOMPLETE": ("TEST_DESIGN",),
    "TEST_CASE_DEFECT": ("TEST_DESIGN",),
    "ORACLE_AMBIGUOUS": ("TEST_DESIGN", "REQUIREMENT_ANALYSIS"),
    "SCRIPT_DEFECT": ("SCRIPT_READINESS",),
    "ASSERTION_IMPLEMENTATION_DEFECT": ("SCRIPT_READINESS",),
    "LOCATOR_DEFECT": ("SCRIPT_READINESS",),
    "TEST_DATA_DEFECT": ("SCRIPT_READINESS",),
    "PRECONDITION_DEFECT": ("SCRIPT_READINESS",),
    "AUTH_DEFECT": ("RUNTIME",),
    "ENVIRONMENT_DEFECT": ("RUNTIME",),
    "DEPENDENCY_DEFECT": ("RUNTIME",),
    "PRODUCT_DEFECT": ("DEFECT",),
    "DEFECT_VERIFICATION_PENDING": ("DEFECT",),
    "CRITICAL_OBLIGATION_NOT_VERIFIED": ("EXECUTION",),
    "INCONCLUSIVE_RESULT_GAP": ("EXECUTION",),
}


@dataclass(frozen=True)
class GapRouteDecision:
    gap_id: str
    target_node: str
    policy: str
    requires_policy_review: bool = False


class GapRouter:
    def route(self, gap: Gap) -> GapRouteDecision:
        allowed = ROUTE_POLICY.get(gap.category)
        if allowed is None:
            return GapRouteDecision(
                gap_id=gap.gap_id,
                target_node=gap.target_node,
                policy="DECLARED_FALLBACK",
                requires_policy_review=True,
            )
        if gap.target_node not in allowed:
            raise GapRoutingError(
                "GAP_TARGET_POLICY_VIOLATION:%s:%s->%s" % (
                    gap.category,
                    gap.target_node,
                    ",".join(allowed),
                )
            )
        return GapRouteDecision(
            gap_id=gap.gap_id,
            target_node=gap.target_node,
            policy="DETERMINISTIC",
            requires_policy_review=False,
        )
