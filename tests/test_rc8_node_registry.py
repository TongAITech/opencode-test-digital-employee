import pytest

from rc8_control.models import (
    CapabilityState,
    ExecutionNode,
    LeaseState,
    NodeStatus,
    RC8ContractError,
    RequirementDeliveryScope,
)
from rc8_control.node_registry import NodeRegistry, NodeRegistryError


def _node(node_id="node-a", package_version="rc8-dev", platform="windows-git-bash"):
    return ExecutionNode(
        node_id=node_id,
        display_name="办公电脑-A",
        platform=platform,
        architecture="x86_64",
        operator="tester-a",
        package_version=package_version,
    )


def _verify(registry, node_id, name, now=100):
    registry.report_capability(node_id, name, CapabilityState.REGISTERED, now=now)
    registry.report_capability(node_id, name, CapabilityState.EXECUTED, now=now)
    registry.report_capability(node_id, name, CapabilityState.ASSERTED, now=now)
    registry.report_capability(
        node_id,
        name,
        CapabilityState.EVIDENCE_PERSISTED,
        evidence_refs=["ART-%s" % name],
        now=now,
    )
    return registry.report_capability(
        node_id,
        name,
        CapabilityState.VERIFIED,
        evidence_refs=["ART-%s" % name],
        now=now,
    )


def test_requirement_delivery_scope_supports_multi_system_mapping():
    left = RequirementDeliveryScope(
        scope_id="scope-1",
        production_batch_id="prod-20261030",
        requirement_id="STBB19-401",
        system_version_id="BLOAN-PF1.3.0",
        application_id="cfg-data",
        sst_id="SST-001",
    )
    right = RequirementDeliveryScope(
        scope_id="scope-2",
        production_batch_id="prod-20261030",
        requirement_id="STBB19-401",
        system_version_id="RULE-PF2.4.0",
        application_id="rule-center",
        sst_id="SST-002",
    )
    assert left.requirement_id == right.requirement_id
    assert left.system_version_id != right.system_version_id


def test_verified_capability_requires_evidence():
    registry = NodeRegistry()
    registry.register(_node(), now=100)
    registry.report_capability("node-a", "CAN_BROWSER", CapabilityState.REGISTERED, now=100)
    registry.report_capability("node-a", "CAN_BROWSER", CapabilityState.EXECUTED, now=100)
    registry.report_capability("node-a", "CAN_BROWSER", CapabilityState.ASSERTED, now=100)
    registry.report_capability(
        "node-a",
        "CAN_BROWSER",
        CapabilityState.EVIDENCE_PERSISTED,
        evidence_refs=["ART-browser-proof"],
        now=100,
    )
    with pytest.raises(NodeRegistryError, match="VERIFIED_CAPABILITY_REQUIRES_EVIDENCE"):
        registry.report_capability("node-a", "CAN_BROWSER", CapabilityState.VERIFIED, now=100)


def test_scheduler_only_uses_reality_verified_capabilities():
    registry = NodeRegistry(offline_after_seconds=60)
    registry.register(_node("node-a"), now=100)
    registry.register(_node("node-b"), now=100)

    _verify(registry, "node-a", "CAN_BROWSER", now=100)
    registry.report_capability("node-b", "CAN_BROWSER", CapabilityState.REGISTERED, now=100)

    eligible = registry.eligible_nodes(["CAN_BROWSER"], now=120)
    assert [item.node_id for item in eligible] == ["node-a"]


def test_node_runtime_change_invalidates_old_verified_capabilities():
    registry = NodeRegistry(offline_after_seconds=300)
    registry.register(_node(package_version="rc8-dev-1"), now=100)
    _verify(registry, "node-a", "CAN_BROWSER", now=101)
    assert registry.get("node-a").has_verified_capabilities(["CAN_BROWSER"])

    registry.register(_node(package_version="rc8-dev-2"), now=120)
    assert not registry.get("node-a").has_verified_capabilities(["CAN_BROWSER"])
    assert registry.get("node-a").capabilities == {}


def test_same_runtime_reconnect_preserves_verified_capabilities():
    registry = NodeRegistry(offline_after_seconds=300)
    registry.register(_node(package_version="rc8-dev-1"), now=100)
    _verify(registry, "node-a", "CAN_BROWSER", now=101)

    registry.register(_node(package_version="rc8-dev-1"), now=120)
    assert registry.get("node-a").has_verified_capabilities(["CAN_BROWSER"])


def test_offline_node_cannot_receive_new_lease():
    registry = NodeRegistry(offline_after_seconds=30)
    registry.register(_node(), now=100)
    _verify(registry, "node-a", "CAN_JUNIT", now=100)

    registry.refresh_liveness(now=131)
    assert registry.get("node-a").status == NodeStatus.OFFLINE
    with pytest.raises(NodeRegistryError, match="NODE_NOT_LEASE_ELIGIBLE"):
        registry.lease_work_item("work-1", "node-a", ["CAN_JUNIT"], ttl_seconds=30, now=131)


def test_work_item_has_only_one_active_lease():
    registry = NodeRegistry(offline_after_seconds=300)
    registry.register(_node("node-a"), now=100)
    registry.register(_node("node-b"), now=100)
    _verify(registry, "node-a", "CAN_DB", now=100)
    _verify(registry, "node-b", "CAN_DB", now=100)

    first = registry.lease_work_item("work-1", "node-a", ["CAN_DB"], ttl_seconds=60, now=110)
    assert first.state == LeaseState.ACTIVE

    with pytest.raises(NodeRegistryError, match="WORK_ITEM_ALREADY_LEASED"):
        registry.lease_work_item("work-1", "node-b", ["CAN_DB"], ttl_seconds=60, now=111)


def test_expired_lease_does_not_authorize_automatic_replay_but_can_be_released_for_reassignment():
    registry = NodeRegistry(offline_after_seconds=300)
    registry.register(_node("node-a"), now=100)
    registry.register(_node("node-b"), now=100)
    _verify(registry, "node-a", "CAN_BROWSER", now=100)
    _verify(registry, "node-b", "CAN_BROWSER", now=100)

    old = registry.lease_work_item("work-1", "node-a", ["CAN_BROWSER"], ttl_seconds=10, now=110)
    assert registry.lease_for("work-1", now=121) is None
    assert old.state == LeaseState.EXPIRED

    # Reassignment is technically possible after expiry, but a higher recovery
    # controller must inspect R1 side-effect truth before dispatching a replay.
    new = registry.lease_work_item("work-1", "node-b", ["CAN_BROWSER"], ttl_seconds=10, now=122)
    assert new.node_id == "node-b"


def test_release_returns_running_node_to_idle():
    registry = NodeRegistry(offline_after_seconds=300)
    registry.register(_node(), now=100)
    _verify(registry, "node-a", "CAN_CODEGRAPH", now=100)
    registry.lease_work_item("work-1", "node-a", ["CAN_CODEGRAPH"], ttl_seconds=60, now=110)
    assert registry.get("node-a").status == NodeStatus.RUNNING

    registry.release_lease("work-1", "node-a")
    assert registry.get("node-a").status == NodeStatus.IDLE


def test_direct_verified_transition_is_forbidden():
    registry = NodeRegistry()
    registry.register(_node(), now=100)
    with pytest.raises(NodeRegistryError, match="CAPABILITY_TRANSITION_FORBIDDEN"):
        registry.report_capability(
            "node-a",
            "CAN_4A_LOGIN",
            CapabilityState.VERIFIED,
            evidence_refs=["ART-proof"],
            now=100,
        )


def test_empty_scope_identity_is_rejected():
    with pytest.raises(RC8ContractError, match="SST_ID_REQUIRED"):
        RequirementDeliveryScope(
            scope_id="scope-1",
            production_batch_id="prod-1",
            requirement_id="req-1",
            system_version_id="ver-1",
            application_id="app-1",
            sst_id="",
        )
