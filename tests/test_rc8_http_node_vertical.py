import json
import threading
from urllib.request import urlopen

from rc8_center import CenterControlPlane
from rc8_control.models import CapabilityState, ExecutionNode
from rc8_control.runtime_contracts import ArtifactManifest, RuntimeEventEnvelope
from rc8_node import NodeAgent
from rc8_node.http_client import HttpCenterClient
from rc8_product import ProductApplication
from rc8_product.server import create_server


def _get_json(url):
    with urlopen(url, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def test_real_http_node_protocol_updates_same_product_control_plane():
    center = CenterControlPlane(offline_after_seconds=300)
    server = create_server(ProductApplication(center), host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = "http://127.0.0.1:%s" % server.server_address[1]

    try:
        node = ExecutionNode(
            node_id="NODE-NET-01",
            display_name="办公电脑-网络纵向切片",
            platform="windows-git-bash",
            architecture="x86_64",
            operator="测试人员甲",
            package_version="rc8-dev",
        )
        agent = NodeAgent(node=node, center=HttpCenterClient(base))
        agent.connect()

        for state in (
            CapabilityState.REGISTERED,
            CapabilityState.EXECUTED,
            CapabilityState.ASSERTED,
        ):
            agent.report_capability("CAN_JUNIT", state)
        agent.report_capability(
            "CAN_JUNIT",
            CapabilityState.EVIDENCE_PERSISTED,
            evidence_refs=["ART-CAP-JUNIT"],
        )
        agent.report_capability(
            "CAN_JUNIT",
            CapabilityState.VERIFIED,
            evidence_refs=["ART-CAP-JUNIT"],
        )

        lease = agent.lease_work_item("WORK-NET-01", ["CAN_JUNIT"], ttl_seconds=60)
        assert lease.node_id == "NODE-NET-01"

        event = RuntimeEventEnvelope(
            event_id="EVENT-NET-01",
            test_run_id="RUN-NET-01",
            mission_id="MISSION-NET-01",
            work_item_id="WORK-NET-01",
            node_id="NODE-NET-01",
            event_type="ASSERTION_PASS",
            subject_type="assertion",
            subject_id="AST-NET-01",
            source_r1_event_id="R1-NET-01",
            source_r1_seq=1,
            idempotency_key="NODE-NET-01:R1-NET-01",
            refs=["ART-NET-01"],
            data={"expected": "PASS", "actual": "PASS"},
        )
        agent.publish_event(event)
        agent.publish_event(event)
        assert center.runtime.event_count() == 1

        artifact = ArtifactManifest(
            artifact_id="ART-NET-01",
            artifact_type="JUNIT_RESULT",
            test_run_id="RUN-NET-01",
            mission_id="MISSION-NET-01",
            work_item_id="WORK-NET-01",
            node_id="NODE-NET-01",
            producer_ref="rc7-junit-worker",
            file_name="surefire.xml",
            size_bytes=42,
            sha256="d" * 64,
            case_id="TC-NET-01",
            attempt_id="ATT-NET-01",
            step_id="STEP-NET-01",
            assertion_id="AST-NET-01",
        )
        agent.declare_artifact(artifact)
        agent.begin_artifact_upload("ART-NET-01")
        result = agent.complete_artifact_upload("ART-NET-01", 42, "d" * 64)
        assert result.is_available

        product = _get_json(base + "/api/nodes?q=%E7%BD%91%E7%BB%9C%E7%BA%B5%E5%90%91%E5%88%87%E7%89%87")
        assert product["total"] == 1
        assert product["items"][0]["current_work_item"] == "WORK-NET-01"
        assert product["items"][0]["verified_capabilities"] == 1
        assert product["items"][0]["status_label"] == "执行中"

        agent.release_lease("WORK-NET-01")
        product = _get_json(base + "/api/nodes/NODE-NET-01")
        assert product["status_label"] == "空闲"
        assert product["capabilities"][0]["evidence_refs"] == ["ART-CAP-JUNIT"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
