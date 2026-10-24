from __future__ import annotations

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.autonomous_node_adoption import AutonomousNodeAdoptionControl
from rc7_runtime.autonomous_reality_node import (
    AutonomousRealityNodeError,
    AutonomousRealityNodeService,
)
from rc7_runtime.bank_mission import start_or_resume
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.reality_recon import RuntimeRealityReconService


RELEASE = "RC7.1-WAVE-B-N1"
MISSION = "MISSION-RC7-1-N1"
RUN = "RUN-RC7-1-N1"


def _evidence_refs():
    return (
        "git://source/abc123",
        "runtime://bank-profile/protected",
        "runtime://dsh/headless",
        "runtime://agent-teams/bootstrap",
        "runtime://auth/foura-fresh",
        "runtime://browser/network-route-discovery",
        "runtime://execution/provider",
        "runtime://service/cfg-center",
        "runtime://service/cfg-data",
    )


def _facts():
    return {
        "release_id": RELEASE,
        "source_revision": "commit:abc123",
        "repository_ref": "repo://TongAITech/opencode-test-digital-employee",
        "runtime_profile": "BANK_PROTECTED",
        "environment_id": "engineering-fixture://pfc",
        "target_version": "BLOAN-PF1.2.0",
        "capabilities": {
            "dsh_headless": {
                "status": "VERIFIED",
                "evidence_ref": "runtime://dsh/headless",
            },
            "agent_teams_bootstrap": {
                "status": "VERIFIED",
                "evidence_ref": "runtime://agent-teams/bootstrap",
            },
            "fresh_auth": {
                "status": "VERIFIED",
                "evidence_ref": "runtime://auth/foura-fresh",
            },
            "browser_network_route_discovery": {
                "status": "VERIFIED",
                "evidence_ref": "runtime://browser/network-route-discovery",
            },
            "runtime_execution": {
                "status": "VERIFIED",
                "evidence_ref": "runtime://execution/provider",
            },
        },
        "required_services": {
            "cfg-center": {
                "status": "VERIFIED",
                "evidence_ref": "runtime://service/cfg-center",
            },
            "cfg-data": {
                "status": "VERIFIED",
                "evidence_ref": "runtime://service/cfg-data",
            },
        },
    }


def _setup(monkeypatch, tmp_path, mission_id=MISSION):
    monkeypatch.setenv("PFC_RC7_SOURCE_COMMIT", "c" * 40)
    r1 = tmp_path / "runtime-state" / "r1" / "event-stream.jsonl"
    started = start_or_resume(
        r1_path=str(r1),
        mission_id=mission_id,
        release_id=RELEASE,
        goal="prove autonomous N1 reality gate",
    )
    task_id = started["ready_tasks"][0]["task_id"]
    truth = TruthRuntime(r1)
    control = ClosedLoopControlPlane(truth, RELEASE, mission_id)
    return truth, control, task_id


def test_n1_requires_real_reality_snapshot_then_director_gate(monkeypatch, tmp_path) -> None:
    truth, control, task_id = _setup(monkeypatch, tmp_path)
    evidence_root = tmp_path / "evidence"
    snapshot = RuntimeRealityReconService(evidence_root=str(evidence_root)).reconcile(
        control,
        task_id,
        facts=_facts(),
        evidence_refs=_evidence_refs(),
    )
    assert snapshot.task_state == "PASS"

    service = AutonomousRealityNodeService(evidence_root=str(evidence_root))
    delivery = service.publish_ready(control, snapshot, run_id=RUN)
    assert delivery.iteration_count == 1

    terminal_before = [
        row
        for row in truth.query("rc7_control_event", mission_id=MISSION)
        if row.get("event_type_name") == "NODE_TERMINAL"
        and row.get("data", {}).get("node_id") == "N1"
    ]
    assert terminal_before == []

    adoption = AutonomousNodeAdoptionControl(
        truth,
        release_id=RELEASE,
        evidence_root=str(evidence_root),
    )
    decision = adoption.director_accept(
        mission_id=MISSION,
        run_id=RUN,
        node_id="N1",
        director_ref="director-runtime-authority",
    )
    assert decision.accepted is True
    terminal = truth.query("rc7_control_event", event_id=decision.terminal_event_id)
    assert len(terminal) == 1
    assert terminal[0]["data"]["node_id"] == "N1"
    assert terminal[0]["data"]["state"] == "PASS"


def test_legacy_reality_pass_cannot_impersonate_autonomous_n1(monkeypatch, tmp_path) -> None:
    _truth, control, task_id = _setup(monkeypatch, tmp_path, mission_id="MISSION-RC7-1-N1-LEGACY")
    evidence_root = tmp_path / "evidence"
    legacy_facts = {
        "release_id": RELEASE,
        "source_revision": "commit:abc123",
        "repository_ref": "repo://TongAITech/opencode-test-digital-employee",
        "runtime_profile": "BANK_PROTECTED",
    }
    snapshot = RuntimeRealityReconService(evidence_root=str(evidence_root)).reconcile(
        control,
        task_id,
        facts=legacy_facts,
        evidence_refs=("git://source/abc123", "runtime://bank-profile/protected"),
    )
    assert snapshot.task_state == "PASS"

    with pytest.raises(AutonomousRealityNodeError, match="N1_ENVIRONMENT_ID_REQUIRED"):
        AutonomousRealityNodeService(evidence_root=str(evidence_root)).publish_ready(
            control,
            snapshot,
            run_id="RUN-LEGACY",
        )


def test_n1_capability_claim_requires_snapshot_bound_durable_evidence(monkeypatch, tmp_path) -> None:
    _truth, control, task_id = _setup(monkeypatch, tmp_path, mission_id="MISSION-RC7-1-N1-EVIDENCE")
    evidence_root = tmp_path / "evidence"
    refs = tuple(ref for ref in _evidence_refs() if ref != "runtime://auth/foura-fresh")
    snapshot = RuntimeRealityReconService(evidence_root=str(evidence_root)).reconcile(
        control,
        task_id,
        facts=_facts(),
        evidence_refs=refs,
    )

    with pytest.raises(AutonomousRealityNodeError, match="N1_CAPABILITY_EVIDENCE_NOT_IN_SNAPSHOT:fresh_auth"):
        AutonomousRealityNodeService(evidence_root=str(evidence_root)).publish_ready(
            control,
            snapshot,
            run_id="RUN-EVIDENCE",
        )
