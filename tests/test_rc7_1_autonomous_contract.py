from __future__ import annotations

import json
from pathlib import Path

import pytest

from rc7_runtime.autonomous_contract import (
    AutonomousContractError,
    CANONICAL_LAYER_IDS,
    CANONICAL_NODE_IDS,
    CoverageDenominatorSnapshot,
    LayerCoverageContract,
    NodeDeliveryPackage,
    canonical_coverage_targets,
    canonical_execution_profile_specs,
    require_layer,
)
from rc7_runtime.autonomous_events import AutonomousEvent, require_autonomous_event
from rc7_runtime.autonomous_gap_router import route_failure_class, route_gap_category


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_ROOT = ROOT / "contracts" / "autonomous_loop"


def _json(name: str):
    return json.loads((CONTRACT_ROOT / name).read_text(encoding="utf-8"))


def test_canonical_node_and_layer_registry_is_frozen() -> None:
    assert CANONICAL_NODE_IDS == tuple("N%d" % value for value in range(1, 11))
    assert CANONICAL_LAYER_IDS == ("L1", "L2", "L3", "L4", "L5", "L6", "L7")

    specs = canonical_execution_profile_specs()
    assert specs["L5"]["action_kind"] == "CROSS_SYSTEM_E2E"
    assert specs["L5"]["required_tools"] == ("e2e-orchestrator",)
    assert specs["L6"]["action_kind"] == "PERFORMANCE"
    assert specs["L6"]["required_tools"] == ("k6",)
    assert specs["L7"]["action_kind"] == "SECURITY"
    assert specs["L7"]["required_tools"] == ("zap",)


def test_machine_contract_registry_matches_runtime_registry() -> None:
    node_rows = _json("canonical_nodes.json")
    layer_rows = _json("canonical_layers.json")
    assert tuple(row["id"] for row in node_rows) == CANONICAL_NODE_IDS
    assert tuple(row["id"] for row in layer_rows) == CANONICAL_LAYER_IDS
    assert tuple(row["name"] for row in layer_rows) == tuple(
        canonical_execution_profile_specs()[layer]["action_kind"] for layer in CANONICAL_LAYER_IDS
    )
    assert _json("coverage_contracts.json") == canonical_coverage_targets()
    assert set(_json("r1_events.json")) == {event.value for event in AutonomousEvent}


def test_contract_manifest_preserves_reality_boundary() -> None:
    manifest = _json("contract_manifest.json")
    assert manifest["contract_id"] == "RC-AUTONOMOUS-TEST-LOOP"
    assert manifest["contract_version"] == "1.0.0"
    assert manifest["reality_status"]["controlled_engineering"] == "PASS"
    assert manifest["reality_status"]["bank_field_reality"] == "NOT_VERIFIED"


def test_old_rc7_1_layer_aliases_are_not_canonical_layers() -> None:
    for value in ("API_CONTRACT", "CAPABILITY_EXECUTION", "CROSS_LAYER_E2E"):
        with pytest.raises(AutonomousContractError):
            require_layer(value)


def test_denominator_is_versioned_nonempty_and_evidence_backed() -> None:
    item = CoverageDenominatorSnapshot(
        mission_id="mission-1",
        layer="L1",
        source_revision="git:abc",
        target_id="PFC",
        denominator_version="1",
        denominator_hash="sha256:abc",
        obligation_ids=("line:1", "branch:2:T", "branch:2:F"),
        evidence_refs=("evd-git", "evd-codegraph"),
    )
    assert item.layer == "L1"

    with pytest.raises(AutonomousContractError, match="COVERAGE_DENOMINATOR_EMPTY"):
        CoverageDenominatorSnapshot(
            mission_id="mission-1",
            layer="L1",
            source_revision="git:abc",
            target_id="PFC",
            denominator_version="1",
            denominator_hash="sha256:abc",
            obligation_ids=(),
            evidence_refs=("evd",),
        )


def test_layer_contract_rejects_target_drift() -> None:
    with pytest.raises(AutonomousContractError, match="LAYER_COVERAGE_TARGET_DRIFT"):
        LayerCoverageContract(
            layer="L1",
            metric_targets={"line_coverage": 0.8, "logic_coverage": 1.0},
            measurement_provider="jacoco",
            evidence_contract="current runtime proof",
            gap_routing_policy="canonical",
            stop_policy="all targets met",
        )


def test_agent_delivery_cannot_self_declare_pass() -> None:
    with pytest.raises(AutonomousContractError, match="AGENT_DELIVERY_CANNOT_SELF_DECLARE_PASS"):
        NodeDeliveryPackage(
            mission_id="m1",
            run_id="r1",
            node_id="N2",
            input_version="v1",
            iteration_count=1,
            artifact_refs=("art-1",),
            evidence_refs=("evd-1",),
            unresolved_gap_ids=(),
            blocked_item_ids=(),
            terminal_status="PASS",
            r1_refs=("event-1",),
        )


def test_gap_router_corrects_data_precondition_auth_ownership() -> None:
    assert route_failure_class("DATA").owner.value == "N5"
    assert route_failure_class("PRECONDITION").owner.value == "N5"
    assert route_failure_class("AUTH").owner.value == "N5"
    assert route_failure_class("SCRIPT").owner.value == "N6"
    assert route_failure_class("PRODUCT").owner.value == "N9"
    assert route_failure_class("UNKNOWN").owner.value == "N8"
    assert route_failure_class("ROUTE", route_scope="SOURCE").owner.value == "N3"
    assert route_failure_class("ROUTE", route_scope="BINDING").owner.value == "N6"
    assert route_gap_category("DATA_PREPARATION_STALE").owner.value == "N5"


def test_r1_event_registry_is_strict() -> None:
    assert require_autonomous_event("COVERAGE_TARGET_REACHED") is AutonomousEvent.COVERAGE_TARGET_REACHED
    with pytest.raises(ValueError, match="NON_CANONICAL_AUTONOMOUS_EVENT"):
        require_autonomous_event("MODEL_SAYS_DONE")
