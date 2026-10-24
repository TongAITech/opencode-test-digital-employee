from __future__ import annotations

import pytest

from rc7_runtime import Gap, GapSeverity
from rc7_runtime.gap_router import GapRouter, GapRoutingError


def _gap(category: str, target: str) -> Gap:
    return Gap(
        gap_id="GAP-" + category,
        mission_id="MISSION-1",
        source_node="EXECUTION",
        category=category,
        severity=GapSeverity.HIGH,
        target_node=target,
        description=category,
    )


def test_known_gap_uses_deterministic_route() -> None:
    decision = GapRouter().route(_gap("API_ROUTE_DEFECT", "CODE_ANALYSIS"))
    assert decision.target_node == "CODE_ANALYSIS"
    assert decision.policy == "DETERMINISTIC"
    assert decision.requires_policy_review is False


@pytest.mark.parametrize("category", ["TEST_DATA_DEFECT", "PRECONDITION_DEFECT", "AUTH_DEFECT"])
def test_preparation_owned_gaps_route_to_runtime_not_script_readiness(category: str) -> None:
    decision = GapRouter().route(_gap(category, "RUNTIME"))
    assert decision.target_node == "RUNTIME"
    assert decision.policy == "DETERMINISTIC"
    with pytest.raises(GapRoutingError, match="GAP_TARGET_POLICY_VIOLATION"):
        GapRouter().route(_gap(category, "SCRIPT_READINESS"))


def test_worker_cannot_reroute_known_gap_to_wrong_node() -> None:
    with pytest.raises(GapRoutingError, match="GAP_TARGET_POLICY_VIOLATION"):
        GapRouter().route(_gap("PRODUCT_DEFECT", "SCRIPT_READINESS"))


def test_unknown_gap_is_not_silently_treated_as_governed() -> None:
    decision = GapRouter().route(_gap("NEW_FUTURE_GAP", "TEST_DESIGN"))
    assert decision.target_node == "TEST_DESIGN"
    assert decision.policy == "DECLARED_FALLBACK"
    assert decision.requires_policy_review is True
