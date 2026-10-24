from __future__ import annotations

import hashlib
import json
from pathlib import Path

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.autonomous_n10_finalization import AutonomousN10FinalizationService
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.models import Artifact, Evidence, Mission, MissionStatus, Task, TaskStatus
from rc7_runtime.truth_overlay import append_entity


MISSION = "MISSION-N10-FINALIZATION"
RELEASE = "RC7.1-N10-FINALIZATION"
RUN = "RUN-N10-FINALIZATION"
TASK = "TASK-N10-FINALIZATION"


def _control(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(
            mission_id=MISSION,
            release_id=RELEASE,
            goal="prove final report replay and projection isolation",
            state=MissionStatus.CONVERGED,
            sufficiency_state="SUFFICIENT",
        ),
    )
    append_entity(
        truth,
        Task(
            task_id=TASK,
            mission_id=MISSION,
            node="MISSION_EVALUATION",
            task_type="N10_CONVERGENCE",
            objective="seed finalization producer",
            state=TaskStatus.PASS,
        ),
        release_id=RELEASE,
    )
    return truth, control


def _write_artifact(
    tmp_path: Path,
    control: ClosedLoopControlPlane,
    *,
    artifact_id: str,
    evidence_id: str,
    artifact_type: str,
    payload,
    parent_refs=(),
):
    path = tmp_path / (artifact_id + ".json")
    encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    path.write_bytes(encoded)
    digest = hashlib.sha256(encoded).hexdigest()
    evidence = Evidence(
        evidence_id=evidence_id,
        mission_id=MISSION,
        kind=artifact_type,
        source_ref="runtime://n10-finalization-test",
        content_ref="file://" + str(path),
        subject_refs=[artifact_id, RUN],
        content_hash="sha256:" + digest,
    )
    artifact = Artifact(
        artifact_id=artifact_id,
        mission_id=MISSION,
        artifact_type=artifact_type,
        producer_task_id=TASK,
        content_ref="file://" + str(path),
        parent_refs=list(parent_refs),
        evidence_refs=[evidence_id],
        content_hash="sha256:" + digest,
    )
    append_entity(control.truth, evidence, release_id=RELEASE)
    append_entity(control.truth, artifact, release_id=RELEASE)
    return artifact, evidence, digest


def _seed_final_report(tmp_path: Path, control: ClosedLoopControlPlane):
    common = {
        "mission_id": MISSION,
        "release_id": RELEASE,
        "node_deliveries": {"N1": {"status": "PASS"}},
        "layer_coverage": {"L1": {"covered": 1, "total": 1}},
        "quality_ledger": {"product_fail_count": 0},
        "defect_ledger": {"counts_by_state": {}},
        "evidence_completeness": {"all_current": True},
    }
    manifest, _, _ = _write_artifact(
        tmp_path,
        control,
        artifact_id="ART-MANIFEST-FINALIZATION",
        evidence_id="EVD-MANIFEST-FINALIZATION",
        artifact_type="MISSION_EVIDENCE_MANIFEST",
        payload=dict(common, run_id=RUN),
    )
    convergence, _, _ = _write_artifact(
        tmp_path,
        control,
        artifact_id="ART-CONVERGENCE-FINALIZATION",
        evidence_id="EVD-CONVERGENCE-FINALIZATION",
        artifact_type="MISSION_CONVERGENCE_RECEIPT",
        payload={
            "mission_id": MISSION,
            "release_id": RELEASE,
            "run_id": RUN,
            "mission_state": "CONVERGED",
            "manifest_artifact_id": manifest.artifact_id,
        },
        parent_refs=[manifest.artifact_id],
    )
    report_payload = dict(
        common,
        schema_version="RC7_1_FINAL_REPORT_V1",
        source="MISSION_EVIDENCE_MANIFEST_AND_R1",
        run_id=RUN,
        mission_state="CONVERGED",
        sufficiency_state="SUFFICIENT",
        quality_state="CONVERGED_CLEAN",
        release_recommendation="RECOMMENDED",
        business_release_decision="NOT_DECIDED_BY_TEST_SYSTEM",
        convergence_receipt_artifact_id=convergence.artifact_id,
        manifest_artifact_id=manifest.artifact_id,
        base_r1_report={"truth_digest": "stable-seeded-digest"},
    )
    report, report_evidence, digest = _write_artifact(
        tmp_path,
        control,
        artifact_id="ART-FINAL-REPORT-FINALIZATION",
        evidence_id="EVD-FINAL-REPORT-FINALIZATION",
        artifact_type="RC7_1_FINAL_REPORT",
        payload=report_payload,
        parent_refs=[convergence.artifact_id, manifest.artifact_id],
    )
    return manifest, convergence, report, report_evidence, digest


def test_existing_final_report_is_replayed_without_recounting_r1(tmp_path: Path, monkeypatch):
    truth, control = _control(tmp_path)
    manifest, convergence, report, report_evidence, digest = _seed_final_report(tmp_path, control)
    service = AutonomousN10FinalizationService(evidence_root=str(tmp_path / "n10"))

    # If idempotent replay is working this parent generator must never run.
    monkeypatch.setattr(
        "rc7_runtime.autonomous_n10_node.AutonomousN10Service.generate_final_report",
        lambda self, control, run_id: (_ for _ in ()).throw(AssertionError("must not regenerate")),
    )
    before_artifacts = len(truth.query("rc7_artifact", mission_id=MISSION))
    receipt = service.generate_final_report(control, run_id=RUN)
    after_artifacts = len(truth.query("rc7_artifact", mission_id=MISSION))

    assert receipt.artifact_id == report.artifact_id
    assert receipt.evidence_id == report_evidence.evidence_id
    assert receipt.manifest_artifact_id == manifest.artifact_id
    assert receipt.convergence_receipt_artifact_id == convergence.artifact_id
    assert receipt.report_sha256 == digest
    assert before_artifacts == after_artifacts


def test_projection_failure_is_durable_but_does_not_rewrite_mission_truth(tmp_path: Path):
    truth, control = _control(tmp_path)
    _, _, report, _, _ = _seed_final_report(tmp_path, control)
    service = AutonomousN10FinalizationService(evidence_root=str(tmp_path / "n10"))
    receipt = service.generate_final_report(control, run_id=RUN)

    result = service.sync_projection(
        control,
        report=receipt,
        projector_ref="backoffice-v1",
        projector=lambda _payload: (_ for _ in ()).throw(RuntimeError("backoffice unavailable")),
    )

    assert result.status == "FAILED"
    assert "backoffice unavailable" in str(result.reason)
    assert truth.query("rc7_mission", mission_id=MISSION)[0]["state"] == "CONVERGED"
    event = [
        row
        for row in truth.query("rc7_control_event", mission_id=MISSION)
        if row.get("event_type_name") == "REPORT_PROJECTION_FAILED"
    ]
    assert len(event) == 1
    assert event[0]["data"]["truth_effect"] == "PROJECTION_ONLY"
    projection_artifact = truth.query("rc7_artifact", artifact_id=result.artifact_id)[0]
    assert projection_artifact["artifact_type_name"] == "FINAL_REPORT_PROJECTION_RECEIPT"
    # Original final report remains immutable and unique.
    reports = [
        row for row in truth.query("rc7_artifact", mission_id=MISSION)
        if row.get("artifact_type_name") == "RC7_1_FINAL_REPORT"
    ]
    assert [row["artifact_id"] for row in reports] == [report.artifact_id]


def test_successful_projection_records_external_ref_without_becoming_truth_source(tmp_path: Path):
    truth, control = _control(tmp_path)
    _seed_final_report(tmp_path, control)
    service = AutonomousN10FinalizationService(evidence_root=str(tmp_path / "n10"))
    receipt = service.generate_final_report(control, run_id=RUN)

    result = service.sync_projection(
        control,
        report=receipt,
        projector_ref="backoffice-v1",
        projector=lambda _payload: {"projection_ref": "backoffice://report/123"},
    )

    assert result.status == "SYNCED"
    assert result.projection_ref == "backoffice://report/123"
    assert truth.query("rc7_mission", mission_id=MISSION)[0]["state"] == "CONVERGED"
    synced = [
        row
        for row in truth.query("rc7_control_event", mission_id=MISSION)
        if row.get("event_type_name") == "REPORT_PROJECTION_SYNCED"
    ]
    assert len(synced) == 1
    assert synced[0]["data"]["truth_effect"] == "PROJECTION_ONLY"
