"""Canonical autonomous-loop gap routing.

The router encodes ownership only. It never performs the repair itself.
"""
from __future__ import annotations

from dataclasses import dataclass

from .autonomous_contract import CanonicalNode


class AutonomousGapRoutingError(ValueError):
    pass


@dataclass(frozen=True)
class GapRouteDecision:
    owner: CanonicalNode
    reason: str


_FAILURE_ROUTES = {
    "SCRIPT": CanonicalNode.N6,
    "SPEC": CanonicalNode.N4,
    "DESIGN": CanonicalNode.N4,
    "ORACLE": CanonicalNode.N4,
    "DATA": CanonicalNode.N5,
    "PRECONDITION": CanonicalNode.N5,
    "AUTH": CanonicalNode.N5,
    "TOOL": CanonicalNode.N1,
    "ENVIRONMENT": CanonicalNode.N1,
    "DEPENDENCY": CanonicalNode.N1,
    "TRANSIENT": CanonicalNode.N7,
    "FLAKY": CanonicalNode.N7,
    "PRODUCT": CanonicalNode.N9,
    "PRODUCT_DEFECT": CanonicalNode.N9,
    "UNKNOWN": CanonicalNode.N8,
}


def route_failure_class(failure_class: str, *, route_scope: str = "SOURCE") -> GapRouteDecision:
    value = str(failure_class or "").strip().upper()
    scope = str(route_scope or "SOURCE").strip().upper()
    if value == "ROUTE":
        if scope == "BINDING":
            return GapRouteDecision(CanonicalNode.N6, "stale executable route binding")
        return GapRouteDecision(CanonicalNode.N3, "route source truth requires code/network discovery")
    owner = _FAILURE_ROUTES.get(value)
    if owner is None:
        raise AutonomousGapRoutingError("UNMAPPED_FAILURE_CLASS:%s" % value)
    return GapRouteDecision(owner, "canonical failure ownership")


def route_gap_category(category: str) -> GapRouteDecision:
    value = str(category or "").strip().upper()
    if not value:
        raise AutonomousGapRoutingError("GAP_CATEGORY_REQUIRED")
    if value.startswith("REQUIREMENT_"):
        return GapRouteDecision(CanonicalNode.N2, "requirement/source denominator gap")
    if value.startswith("CODE_") or value.startswith("GRAPH_"):
        return GapRouteDecision(CanonicalNode.N3, "code impact/graph gap")
    if value.startswith("TEST_DESIGN_") or value.startswith("ORACLE_"):
        return GapRouteDecision(CanonicalNode.N4, "test design/oracle gap")
    if value.startswith("DATA_") or value.startswith("PRECONDITION_") or value.startswith("AUTH_"):
        return GapRouteDecision(CanonicalNode.N5, "preparation/data/auth gap")
    if value.startswith("SCRIPT_") or value.startswith("BINDING_") or value.startswith("FIXTURE_"):
        return GapRouteDecision(CanonicalNode.N6, "script implementation gap")
    if value.startswith("COVERAGE_") or value.startswith("EXECUTION_"):
        return GapRouteDecision(CanonicalNode.N7, "coverage/execution gap")
    if value.startswith("DIAGNOSIS_") or value.startswith("FAILURE_"):
        return GapRouteDecision(CanonicalNode.N8, "failure diagnosis gap")
    if value.startswith("DEFECT_") or value == "PRODUCT_DEFECT":
        return GapRouteDecision(CanonicalNode.N9, "defect qualification/disposition gap")
    if value.startswith("MISSION_") or value.startswith("TRACEABILITY_") or value.startswith("EVIDENCE_"):
        return GapRouteDecision(CanonicalNode.N10, "global convergence gap; N10 must route onward when owner is known")
    raise AutonomousGapRoutingError("UNMAPPED_GAP_CATEGORY:%s" % value)
