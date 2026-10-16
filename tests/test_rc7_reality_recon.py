from __future__ import annotations

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.bank_mission import start_or_resume
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.reality_recon import RuntimeRealityReconError, RuntimeRealityReconService


def _facts(release_id: str):
    return {
        "release_id": release_id,
        "source_revision": "commit:abc123",
        "repository_ref": "repo://TongAITech/opencode-test-digital-employee",
        "runtime_profile": "BANK_PROTECTED",
    }


def test_runtime_reality_recon_is_durable_and_releases_requirement_producer(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PFC_RC7_SOURCE_COMMIT", "a" * 40)
    r1 = tmp_path / "runtime-state" / "r1" / "event-stream.jsonl"
    started = start_or_resume(
        r1_path=str(r1),
        mission_id="MISSION-REALITY-1",
        release_id="REL-REALITY",
        goal="prove runtime-owned reality before analysis",
    )
    task_id = started["ready_tasks"][0]["task_id"]
    assert started["ready_tasks"][0]["node"] == "REALITY_RECON"

    truth = TruthRuntime(r1)
    control = ClosedLoopControlPlane(truth, "REL-REALITY", "MISSION-REALITY-1")
    service = RuntimeRealityReconService(evidence_root=str(tmp_path / "evidence"))
    snapshot = service.reconcile(
        control,
        task_id,
        facts=_facts("REL-REALITY"),
        evidence_refs=(
            "git://source/abc123",
            "runtime://bank-profile/protected",
        ),
    )

    assert snapshot.task_state == "PASS"
    assert snapshot.content_hash.startswith("sha256:")
    assert len(snapshot.evidence_ids) == 3
    assert control.scheduler.task(task_id).state.value == "PASS"
    ready_nodes = [task.node for task in control.scheduler.ready_tasks("MISSION-REALITY-1")]
    assert ready_nodes == ["REQUIREMENT_ANALYSIS"]

    artifacts = truth.query("rc7_artifact", artifact_id=snapshot.artifact_id)
    assert len(artifacts) == 1
    assert artifacts[0]["content_hash"] == snapshot.content_hash
    assert artifacts[0]["artifact_type_name"] == "BANK_REALITY_SNAPSHOT"
    assert len(truth.query("rc7_evaluation", mission_id="MISSION-REALITY-1")) == 1

    # Process/session recreation must reuse the exact R1/file truth and create
    # no duplicate Artifact/Evaluation rows.
    replayed = TruthRuntime(r1)
    recovered = ClosedLoopControlPlane(replayed, "REL-REALITY", "MISSION-REALITY-1")
    replay = service.reconcile(
        recovered,
        task_id,
        facts=_facts("REL-REALITY"),
        evidence_refs=(
            "git://source/abc123",
            "runtime://bank-profile/protected",
        ),
    )
    assert replay == snapshot
    assert len(replayed.query("rc7_artifact", artifact_id=snapshot.artifact_id)) == 1
    assert len(replayed.query("rc7_evaluation", mission_id="MISSION-REALITY-1")) == 1


def test_runtime_reality_recon_rejects_release_drift(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PFC_RC7_SOURCE_COMMIT", "b" * 40)
    r1 = tmp_path / "runtime-state" / "r1" / "event-stream.jsonl"
    started = start_or_resume(
        r1_path=str(r1),
        mission_id="MISSION-REALITY-2",
        release_id="REL-A",
        goal="fail closed on mismatched reality",
    )
    control = ClosedLoopControlPlane(TruthRuntime(r1), "REL-A", "MISSION-REALITY-2")
    service = RuntimeRealityReconService(evidence_root=str(tmp_path / "evidence"))

    try:
        service.reconcile(
            control,
            started["ready_tasks"][0]["task_id"],
            facts=_facts("REL-B"),
            evidence_refs=("git://source/abc123",),
        )
    except RuntimeRealityReconError as exc:
        assert str(exc) == "REALITY_RELEASE_MISMATCH"
    else:
        raise AssertionError("release drift must fail closed")
