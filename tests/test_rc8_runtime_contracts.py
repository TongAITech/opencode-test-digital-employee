import pytest

from rc8_control.models import RC8ContractError
from rc8_control.runtime_contracts import (
    ArtifactAvailability,
    ArtifactManifest,
    RuntimeEventEnvelope,
)


def test_runtime_event_envelope_requires_source_r1_identity():
    envelope = RuntimeEventEnvelope(
        event_id="center-event-1",
        test_run_id="run-1",
        mission_id="mission-1",
        work_item_id="work-1",
        node_id="node-1",
        event_type="ASSERTION_PASS",
        subject_type="assertion",
        subject_id="assertion-1",
        source_r1_event_id="r1-event-1",
        source_r1_seq=8,
        idempotency_key="node-1:r1-event-1",
        refs=["ART-1"],
        data={"actual": "APPROVED"},
    )
    assert envelope.source_r1_seq == 8
    assert envelope.idempotency_key == "node-1:r1-event-1"


def test_runtime_event_source_sequence_must_be_positive():
    with pytest.raises(RC8ContractError, match="SOURCE_R1_SEQ_INVALID"):
        RuntimeEventEnvelope(
            event_id="center-event-1",
            test_run_id="run-1",
            mission_id="mission-1",
            work_item_id="work-1",
            node_id="node-1",
            event_type="STEP_STARTED",
            subject_type="step",
            subject_id="step-1",
            source_r1_event_id="r1-event-1",
            source_r1_seq=0,
            idempotency_key="key-1",
        )


def test_artifact_manifest_binds_assertion_evidence_to_full_execution_lineage():
    artifact = ArtifactManifest(
        artifact_id="ART-1",
        artifact_type="SCREENSHOT",
        test_run_id="run-1",
        mission_id="mission-1",
        work_item_id="work-1",
        node_id="node-1",
        producer_ref="browser-worker",
        file_name="step-4.png",
        size_bytes=100,
        sha256="a" * 64,
        availability=ArtifactAvailability.AVAILABLE,
        case_id="TC-1",
        attempt_id="ATT-2",
        step_id="STEP-4",
        assertion_id="AST-9",
    )
    assert artifact.is_available
    assert artifact.is_assertion_evidence


def test_assertion_artifact_cannot_skip_step_attempt_case_lineage():
    with pytest.raises(RC8ContractError, match="ASSERTION_ARTIFACT_REQUIRES_STEP_ID"):
        ArtifactManifest(
            artifact_id="ART-1",
            artifact_type="API_RESPONSE",
            test_run_id="run-1",
            mission_id="mission-1",
            work_item_id="work-1",
            node_id="node-1",
            producer_ref="api-worker",
            file_name="response.json",
            size_bytes=100,
            sha256="b" * 64,
            assertion_id="AST-1",
        )


def test_artifact_sha256_is_validated():
    with pytest.raises(RC8ContractError, match="ARTIFACT_SHA256_INVALID"):
        ArtifactManifest(
            artifact_id="ART-1",
            artifact_type="LOG",
            test_run_id="run-1",
            mission_id="mission-1",
            work_item_id="work-1",
            node_id="node-1",
            producer_ref="junit-worker",
            file_name="run.log",
            size_bytes=100,
            sha256="not-a-hash",
        )
