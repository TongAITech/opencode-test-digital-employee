import pytest

from rc8_center import CenterControlPlane
from rc8_control.models import CapabilityState, ExecutionNode
from rc8_product import ProductApplication, ProductError


def _qualify(center, node_id, capability, now=100):
    for state in (
        CapabilityState.REGISTERED,
        CapabilityState.EXECUTED,
        CapabilityState.ASSERTED,
    ):
        center.report_capability(node_id, capability, state, now=now)
    center.report_capability(
        node_id,
        capability,
        CapabilityState.EVIDENCE_PERSISTED,
        evidence_refs=["ART-proof"],
        now=now,
    )
    center.report_capability(
        node_id,
        capability,
        CapabilityState.VERIFIED,
        evidence_refs=["ART-proof"],
        now=now,
    )


def test_product_node_api_reads_same_control_plane_state():
    center = CenterControlPlane(offline_after_seconds=300)
    center.register_node(
        ExecutionNode(
            node_id="NODE-01",
            display_name="办公电脑-01",
            platform="windows-git-bash",
            architecture="x86_64",
            operator="测试人员甲",
            package_version="rc8-dev",
        ),
        now=100,
    )
    _qualify(center, "NODE-01", "CAN_BROWSER", now=101)
    center.lease_work_item("WORK-01", "NODE-01", ["CAN_BROWSER"], ttl_seconds=60, now=110)

    app = ProductApplication(center)
    listing = app.list_nodes({"q": "办公电脑"}, now=120)
    assert listing["total"] == 1
    assert listing["items"][0]["current_work_item"] == "WORK-01"
    assert listing["items"][0]["status_label"] == "执行中"

    detail = app.node_detail("NODE-01", now=120)
    assert detail["capabilities"][0]["state_label"] == "已验证"
    assert detail["capabilities"][0]["evidence_refs"] == ["ART-proof"]


def test_product_unknown_node_returns_domain_error():
    app = ProductApplication(CenterControlPlane())
    with pytest.raises(ProductError, match="NODE_NOT_REGISTERED"):
        app.node_detail("missing-node")


def test_product_health_declares_r1_runtime_truth():
    app = ProductApplication(CenterControlPlane())
    assert app.health() == {
        "status": "UP",
        "product": "RC8",
        "runtime_truth": "R1_EVENT_STREAM",
    }
