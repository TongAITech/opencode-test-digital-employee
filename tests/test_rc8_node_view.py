from rc8_center import CenterControlPlane
from rc8_center.node_view import NodeReadModel
from rc8_control.models import CapabilityState, ExecutionNode


def _qualify(center, node_id, capability, now=100):
    center.report_capability(node_id, capability, CapabilityState.REGISTERED, now=now)
    center.report_capability(node_id, capability, CapabilityState.EXECUTED, now=now)
    center.report_capability(node_id, capability, CapabilityState.ASSERTED, now=now)
    center.report_capability(
        node_id,
        capability,
        CapabilityState.EVIDENCE_PERSISTED,
        evidence_refs=["ART-%s" % capability],
        now=now,
    )
    center.report_capability(
        node_id,
        capability,
        CapabilityState.VERIFIED,
        evidence_refs=["ART-%s" % capability],
        now=now,
    )


def test_node_list_is_chinese_labeled_and_shows_current_work_item():
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
    center.lease_work_item("WORK-001", "NODE-01", ["CAN_BROWSER"], ttl_seconds=60, now=110)

    rows = NodeReadModel(center).list_nodes(now=120)
    assert rows == [
        {
            "node_id": "NODE-01",
            "display_name": "办公电脑-01",
            "operator": "测试人员甲",
            "platform": "windows-git-bash",
            "architecture": "x86_64",
            "package_version": "rc8-dev",
            "status": "RUNNING",
            "status_label": "执行中",
            "heartbeat_at": 100,
            "verified_capabilities": 1,
            "capability_total": 1,
            "current_work_item": "WORK-001",
        }
    ]


def test_node_detail_exposes_capability_evidence_and_lease_history():
    center = CenterControlPlane(offline_after_seconds=300)
    center.register_node(
        ExecutionNode(
            node_id="NODE-01",
            display_name="办公电脑-01",
            platform="linux-bash",
            architecture="aarch64",
            operator="测试人员甲",
            package_version="rc8-dev",
        ),
        now=100,
    )
    _qualify(center, "NODE-01", "CAN_CODEGRAPH", now=101)
    lease = center.lease_work_item("WORK-001", "NODE-01", ["CAN_CODEGRAPH"], ttl_seconds=60, now=110)

    detail = NodeReadModel(center).detail("NODE-01", now=120)
    assert detail["capabilities"][0]["state_label"] == "已验证"
    assert detail["capabilities"][0]["evidence_refs"] == ["ART-CAN_CODEGRAPH"]
    assert detail["leases"][0]["lease_id"] == lease.lease_id
    assert detail["leases"][0]["state"] == "ACTIVE"


def test_node_query_filters_without_dashboard_aggregation():
    center = CenterControlPlane(offline_after_seconds=300)
    center.register_node(
        ExecutionNode(
            node_id="NODE-WIN",
            display_name="办公电脑-Windows",
            platform="windows-git-bash",
            architecture="x86_64",
            operator="甲",
        ),
        now=100,
    )
    center.register_node(
        ExecutionNode(
            node_id="NODE-LINUX",
            display_name="办公电脑-信创Linux",
            platform="linux-bash",
            architecture="aarch64",
            operator="乙",
        ),
        now=100,
    )
    _qualify(center, "NODE-LINUX", "CAN_JUNIT", now=101)

    view = NodeReadModel(center)
    assert [row["node_id"] for row in view.list_nodes(query="linux", now=120)] == ["NODE-LINUX"]
    assert [row["node_id"] for row in view.list_nodes(capability="CAN_JUNIT", now=120)] == ["NODE-LINUX"]
