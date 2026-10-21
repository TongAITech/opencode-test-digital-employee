from rc8_center import CenterControlPlane
from rc8_control.models import CapabilityState, ExecutionNode, NodeStatus
from rc8_control.runtime_contracts import ArtifactManifest, RuntimeEventEnvelope
from rc8_node import NodeAgent


def _qualify(agent, capability, evidence_ref, now=100):
    agent.report_capability(capability, CapabilityState.REGISTERED, now=now)
    agent.report_capability(capability, CapabilityState.EXECUTED, now=now)
    agent.report_capability(capability, CapabilityState.ASSERTED, now=now)
    agent.report_capability(
        capability,
        CapabilityState.EVIDENCE_PERSISTED,
        evidence_refs=[evidence_ref],
        now=now,
    )
    agent.report_capability(
        capability,
        CapabilityState.VERIFIED,
        evidence_refs=[evidence_ref],
        now=now,
    )


def test_single_node_can_register_qualify_lease_publish_and_upload_evidence():
    center = CenterControlPlane(offline_after_seconds=120)
    node = ExecutionNode(
        node_id="NODE-WIN-01",
        display_name="办公电脑-01",
        platform="windows-git-bash",
        architecture="x86_64",
        operator="tester-01",
        package_version="rc8-dev",
    )
    agent = NodeAgent(node=node, center=center)

    registered = agent.connect(now=100)
    assert registered.status == NodeStatus.ONLINE

    _qualify(agent, "CAN_JUNIT", "ART-CAP-JUNIT", now=101)
    lease = agent.lease_work_item(
        work_item_id="WORK-001",
        required_capabilities=["CAN_JUNIT"],
        ttl_seconds=60,
        now=110,
    )
    assert lease.node_id == "NODE-WIN-01"
    assert center.nodes.get("NODE-WIN-01").status == NodeStatus.RUNNING

    event = RuntimeEventEnvelope(
        event_id="EVT-CENTER-001",
        test_run_id="RUN-001",
        mission_id="MISSION-001",
        work_item_id="WORK-001",
        node_id="NODE-WIN-01",
        event_type="ASSERTION_PASS",
        subject_type="assertion",
        subject_id="AST-001",
        source_r1_event_id="R1-EVT-001",
        source_r1_seq=1,
        idempotency_key="NODE-WIN-01:R1-EVT-001",
        refs=["ART-EVID-001"],
        data={"expected": "APPROVED", "actual": "APPROVED"},
    )
    agent.publish_event(event)
    agent.publish_event(event)
    assert center.runtime.event_count() == 1

    evidence = ArtifactManifest(
        artifact_id="ART-EVID-001",
        artifact_type="JUNIT_RESULT",
        test_run_id="RUN-001",
        mission_id="MISSION-001",
        work_item_id="WORK-001",
        node_id="NODE-WIN-01",
        producer_ref="rc7-junit-worker",
        file_name="surefire.xml",
        size_bytes=42,
        sha256="c" * 64,
        case_id="TC-001",
        attempt_id="ATT-001",
        step_id="STEP-001",
        assertion_id="AST-001",
    )
    agent.declare_artifact(evidence)
    agent.begin_artifact_upload("ART-EVID-001")
    available = agent.complete_artifact_upload(
        artifact_id="ART-EVID-001",
        verified_size_bytes=42,
        verified_sha256="c" * 64,
    )
    assert available.is_available
    assert available.is_assertion_evidence

    agent.release_lease("WORK-001")
    assert center.nodes.get("NODE-WIN-01").status == NodeStatus.IDLE
