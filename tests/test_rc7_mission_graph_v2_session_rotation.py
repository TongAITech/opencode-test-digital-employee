from __future__ import annotations

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.bank_mission import start_or_resume
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.mission_conformance import MissionConformanceChecker
from rc7_runtime.mission_stage_dispatch import MissionStageDispatcher
from rc7_runtime.reality_recon import RuntimeRealityReconService


def test_bank_graph_v2_active_producer_rotates_a_to_b_to_c_without_task_recreation(monkeypatch, tmp_path) -> None:
    source_commit = "7" * 40
    monkeypatch.setenv("PFC_RC7_SOURCE_COMMIT", source_commit)
    r1 = tmp_path / "runtime-state" / "r1" / "event-stream.jsonl"
    mission_id = "MISSION-V2-A-B-C"
    release_id = "REL-V2-A-B-C"
    goal = "prove durable graph-v2 session rotation"

    started = start_or_resume(
        r1_path=str(r1),
        mission_id=mission_id,
        release_id=release_id,
        goal=goal,
    )
    assert started["graph_version"] == "v2"
    assert [item["node"] for item in started["ready_tasks"]] == ["REALITY_RECON"]

    truth_a = TruthRuntime(r1)
    control_a = ClosedLoopControlPlane(truth_a, release_id, mission_id)
    reality_task_id = started["ready_tasks"][0]["task_id"]
    snapshot = RuntimeRealityReconService(evidence_root=str(tmp_path / "evidence")).reconcile(
        control_a,
        reality_task_id,
        facts={
            "release_id": release_id,
            "source_revision": "git:%s" % source_commit,
            "repository_ref": "repo://TongAITech/opencode-test-digital-employee",
            "runtime_profile": "BANK_PROTECTED",
        },
        evidence_refs=("git://%s" % source_commit, "runtime://bank-profile/protected"),
    )
    assert snapshot.task_state == "PASS"

    route = MissionStageDispatcher(control_a).next_route()
    assert route is not None
    assert route.node == "REQUIREMENT_ANALYSIS"
    assert route.owner == "PRODUCER_WORKER"
    producer = control_a.scheduler.task(route.task_id)
    leased = control_a.lease_next(worker_ref="SESSION-A", capabilities=producer.required_capabilities)
    assert leased is not None
    assert leased.task_id == route.task_id
    assert leased.lease_owner == "SESSION-A"
    control_a.start(route.task_id, worker_ref="SESSION-A")

    handoff_ab = control_a.sessions.prepare(
        mission_id=mission_id,
        task_id=route.task_id,
        predecessor_session_ref="SESSION-A",
        artifact_refs=(snapshot.artifact_id,),
    )
    control_a.sessions.activate(handoff_ab.handoff_id, "SESSION-B")

    # Reconstruct the runtime exactly as a successor process/session would.
    truth_b = TruthRuntime(r1)
    control_b = ClosedLoopControlPlane(truth_b, release_id, mission_id)
    envelope_b = control_b.sessions.resume_envelope(handoff_ab.handoff_id)
    assert envelope_b["active_session_ref"] == "SESSION-B"
    assert envelope_b["task_id"] == route.task_id
    assert envelope_b["task_state"] == "RUNNING"
    assert envelope_b["artifact_refs"] == [snapshot.artifact_id]
    assert "conversation" not in envelope_b
    assert "transcript" not in envelope_b
    assert MissionConformanceChecker(truth_b).check(mission_id).status == "PASS"

    handoff_bc = control_b.sessions.prepare(
        mission_id=mission_id,
        task_id=route.task_id,
        predecessor_session_ref="SESSION-B",
        artifact_refs=tuple(envelope_b["artifact_refs"]),
        gap_refs=tuple(envelope_b["gap_refs"]),
    )
    control_b.sessions.activate(handoff_bc.handoff_id, "SESSION-C")

    truth_c = TruthRuntime(r1)
    control_c = ClosedLoopControlPlane(truth_c, release_id, mission_id)
    envelope_c = control_c.sessions.resume_envelope(handoff_bc.handoff_id)
    assert envelope_c["active_session_ref"] == "SESSION-C"
    assert envelope_c["generation"] == 2
    assert envelope_c["task_id"] == route.task_id
    assert envelope_c["task_state"] == "RUNNING"
    assert "conversation" not in envelope_c
    assert "transcript" not in envelope_c
    assert MissionConformanceChecker(truth_c).check(mission_id).status == "PASS"

    # Bank entrypoint must resume the same persisted graph/task inventory after
    # two session rotations; it may not silently recreate or upgrade the DAG.
    resumed = start_or_resume(
        r1_path=str(r1),
        mission_id=mission_id,
        release_id=release_id,
        goal=goal,
    )
    assert resumed["status"] == "RESUMED"
    assert resumed["graph_version"] == "v2"
    task_rows = truth_c.query("rc7_task", mission_id=mission_id)
    assert len(task_rows) == started["task_count"] == 6
    active = [row for row in task_rows if row["task_id"] == route.task_id]
    assert len(active) == 1
    assert active[0]["state"] == "RUNNING"
    assert active[0]["lease_owner"] == "SESSION-C"
