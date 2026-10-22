from pathlib import Path

from rc8_center.__main__ import build_application
from rc8_center.coverage_repository import JsonFileCoverageRepository
from rc8_center.governance_event_projector import GovernanceEventProjector
from rc8_center.governance_repository import JsonFileGovernanceRepository
from rc8_center.json_repository import JsonFileArtifactRepository
from rc8_runtime import (
    ArtifactAvailability,
    CentralR1RuntimeLedger,
    RuntimeProducerKind,
    runtime_event,
)
from rc8_runtime.artifacts import ArtifactManifest
from rc8_runtime.governance import StageInstance, StageState


def _artifact(artifact_id, kind="evidence"):
    return ArtifactManifest(
        artifact_id=artifact_id,
        test_run_id="run-1",
        work_item_id="wi-1",
        node_id="node-1",
        kind=kind,
        producer_kind=RuntimeProducerKind.WORKER,
        producer_ref="worker:l1",
        file_name=artifact_id.lower() + ".json",
        sha256="0" * 64,
        size_bytes=1,
        availability=ArtifactAvailability.AVAILABLE,
        attempt_id="attempt-1",
    )


def _stage():
    return StageInstance(
        stage_instance_id="stage-l1-1",
        test_run_id="run-1",
        stage_type="APPLICABLE_LAYER_EXECUTION",
        scope_version="scope-v1",
        attempt_no=1,
        state=StageState.EXECUTING,
    )


def _projector(tmp_path):
    ledger = CentralR1RuntimeLedger(str(tmp_path / "r1.jsonl"))
    gov = JsonFileGovernanceRepository(str(tmp_path / "governance.json"))
    cov = JsonFileCoverageRepository(str(tmp_path / "coverage.json"))
    artifacts = JsonFileArtifactRepository(str(tmp_path / "artifacts.json"))
    gov.upsert_stage(_stage())
    return ledger, gov, cov, artifacts, GovernanceEventProjector(ledger, gov, cov, artifacts)


def _append(ledger, event_id, event_type, sequence, data, *, attempt_id="attempt-1"):
    event = runtime_event(
        event_id=event_id,
        test_run_id="run-1",
        work_item_id="wi-1",
        node_id="node-1",
        producer_kind=RuntimeProducerKind.WORKER,
        producer_ref="worker:l1",
        event_type=event_type,
        sequence=sequence,
        attempt_id=attempt_id,
        data=data,
    )
    ledger.append_runtime(event)


def test_r1_replay_projects_attempt_coverage_gap_sufficiency_and_release(tmp_path):
    ledger, gov, cov, artifacts, projector = _projector(tmp_path)
    for artifact_id in ("ART-JUNIT", "ART-JACOCO", "ART-GAP", "ART-EVAL", "ART-RELEASE"):
        artifacts.upsert(_artifact(artifact_id))

    _append(
        ledger,
        "ev-1",
        "ATTEMPT_STARTED",
        1,
        {"stage_instance_id": "stage-l1-1", "input_snapshot_ref": "git:abc", "started_at": 10},
    )
    _append(
        ledger,
        "ev-2",
        "ATTEMPT_COMPLETED",
        2,
        {
            "stage_instance_id": "stage-l1-1",
            "input_snapshot_ref": "git:abc",
            "started_at": 10,
            "finished_at": 20,
            "action_refs": ["action:unit-test"],
            "assertion_refs": ["assertion:unit-test"],
            "evidence_refs": ["ART-JUNIT"],
        },
    )
    _append(
        ledger,
        "ev-3",
        "COVERAGE_COLLECTED",
        3,
        {
            "stage_instance_id": "stage-l1-1",
            "observation_id": "coverage-1",
            "subject_ref": "layer:L1",
            "source_snapshot_ref": "git:abc",
            "source_tool": "jacoco",
            "artifact_refs": ["ART-JACOCO"],
            "metric": {
                "metric_id": "changed-branch-1",
                "dimension": "CHANGED_BRANCH",
                "covered": 8,
                "total": 10,
                "threshold": 0.9,
                "critical": True,
                "evidence_refs": ["ART-JACOCO"],
            },
        },
    )
    _append(
        ledger,
        "ev-4",
        "GAP_OPENED",
        4,
        {
            "gap_id": "gap-1",
            "source_stage_instance_id": "stage-l1-1",
            "gap_type": "COVERAGE_GAP",
            "severity": "P1",
            "description": "critical changed branch uncovered",
            "owner_stage": "TEST_DESIGN",
            "repair_strategy": "delta design",
            "evidence_refs": ["ART-GAP"],
            "invalidates": ["layer:L1:sufficiency", "mission:test-sufficient"],
        },
    )
    _append(
        ledger,
        "ev-5",
        "SUFFICIENCY_EVALUATED",
        5,
        {
            "evaluation_id": "eval-1",
            "scope": "MISSION",
            "subject_id": "run-1",
            "evaluator_id": "mission-evaluator",
            "policy_version": "policy-v1",
            "result": "INSUFFICIENT",
            "dimension_refs": ["coverage:changed-branch"],
            "evidence_refs": ["ART-EVAL"],
            "unsatisfied_requirement_refs": ["coverage:critical-changed-branch"],
            "unresolved_gap_ids": ["gap-1"],
            "explanation": "coverage gap remains open",
        },
        attempt_id=None,
    )
    _append(
        ledger,
        "ev-6",
        "RELEASE_DECISION_RECORDED",
        6,
        {
            "release_decision_id": "release-1",
            "decision": "HOLD",
            "mission_evaluation_ref": "eval-1",
            "evidence_refs": ["ART-RELEASE"],
            "blocking_defect_refs": [],
            "explanation": "mission insufficient",
        },
        attempt_id=None,
    )

    result = projector.replay()
    assert result["status"] == "REPLAY_COMPLETE"
    assert result["pending"] == 0
    assert gov.get_attempt("attempt-1").status.value == "COMPLETED"
    assert cov.get("coverage-1").source_snapshot_ref == "git:abc"
    assert gov.get_gap("gap-1").status.value == "OPEN"
    assert gov.get_evaluation("eval-1").result.value == "INSUFFICIENT"
    assert gov.get_release_decision("release-1").decision.value == "HOLD"
    assert gov.projection_receipt("ev-1")["status"] == "PROJECTED"
    assert gov.projection_receipt("ev-6")["status"] == "PROJECTED"

    # Exact ledger replay is idempotent and does not create another Attempt.
    again = projector.replay()
    assert again["projected"] == 0
    assert len(gov.list_attempts("run-1")) == 1


def test_projection_waits_for_available_artifact_then_replays(tmp_path):
    ledger, gov, cov, artifacts, projector = _projector(tmp_path)
    _append(
        ledger,
        "ev-cov",
        "COVERAGE_COLLECTED",
        1,
        {
            "stage_instance_id": "stage-l1-1",
            "observation_id": "coverage-1",
            "subject_ref": "layer:L1",
            "source_snapshot_ref": "git:abc",
            "source_tool": "jacoco",
            "artifact_refs": ["ART-JACOCO"],
            "metric": {
                "metric_id": "changed-line-1",
                "dimension": "CHANGED_LINE",
                "covered": 9,
                "total": 10,
                "threshold": 0.9,
                "evidence_refs": ["ART-JACOCO"],
            },
        },
    )
    first = projector.replay()
    assert first["pending"] == 1
    assert gov.projection_receipt("ev-cov")["status"] == "PENDING"
    assert cov.get("coverage-1") is None

    artifacts.upsert(_artifact("ART-JACOCO"))
    second = projector.replay()
    assert second["projected"] == 1
    assert gov.projection_receipt("ev-cov")["status"] == "PROJECTED"
    assert cov.get("coverage-1") is not None


def test_canonical_center_startup_replays_existing_r1_into_product_projection(tmp_path):
    state_dir = tmp_path / "center"
    state_dir.mkdir(parents=True)
    gov = JsonFileGovernanceRepository(str(state_dir / "governance-state.json"))
    gov.upsert_stage(_stage())
    artifacts = JsonFileArtifactRepository(str(state_dir / "artifact-metadata.json"))
    artifacts.upsert(_artifact("ART-JUNIT"))
    ledger = CentralR1RuntimeLedger(str(state_dir / "runtime-state" / "r1" / "event-stream.jsonl"))
    _append(
        ledger,
        "ev-startup",
        "ATTEMPT_COMPLETED",
        1,
        {
            "stage_instance_id": "stage-l1-1",
            "input_snapshot_ref": "git:abc",
            "started_at": 10,
            "finished_at": 20,
            "evidence_refs": ["ART-JUNIT"],
        },
    )

    application = build_application(str(state_dir))
    response = application.get("/api/v1/test-runs/run-1/governance")
    assert response["test_run"]["attempt_count"] == 1
    assert response["test_run"]["attempts"][0]["attempt_id"] == "attempt-1"
    assert response["test_run"]["latest_mission_sufficiency"] is None
    assert response["test_run"]["latest_release_decision"] is None
