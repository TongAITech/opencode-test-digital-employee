import pytest

from rc8_control.runtime_contracts import ArtifactManifest, RuntimeEventEnvelope
from rc8_control.runtime_ingest import RuntimeIngestError, RuntimeIngestStore


def _event(data=None):
    return RuntimeEventEnvelope(
        event_id="event-1",
        test_run_id="run-1",
        mission_id="mission-1",
        work_item_id="work-1",
        node_id="node-1",
        event_type="API_RESPONSE",
        subject_type="step",
        subject_id="step-1",
        source_r1_event_id="r1-1",
        source_r1_seq=1,
        idempotency_key="node-1:r1-1",
        data=data or {"status": 200},
    )


def _artifact():
    return ArtifactManifest(
        artifact_id="ART-1",
        artifact_type="API_RESPONSE",
        test_run_id="run-1",
        mission_id="mission-1",
        work_item_id="work-1",
        node_id="node-1",
        producer_ref="api-worker",
        file_name="response.json",
        size_bytes=12,
        sha256="a" * 64,
        case_id="TC-1",
        attempt_id="ATT-1",
        step_id="STEP-1",
        assertion_id="AST-1",
    )


def test_event_ingest_is_idempotent_for_same_runtime_fact():
    store = RuntimeIngestStore()
    first = store.ingest_event(_event())
    second = store.ingest_event(_event())
    assert first == second
    assert store.event_count() == 1


def test_event_idempotency_conflict_is_rejected():
    store = RuntimeIngestStore()
    store.ingest_event(_event())
    with pytest.raises(RuntimeIngestError, match="IDEMPOTENCY_KEY_CONFLICT"):
        store.ingest_event(_event({"status": 500}))


def test_artifact_is_only_available_after_size_and_hash_verification():
    store = RuntimeIngestStore()
    store.declare_artifact(_artifact())
    store.begin_upload("ART-1")
    available = store.mark_available("ART-1", verified_size_bytes=12, verified_sha256="a" * 64)
    assert available.is_available


def test_artifact_hash_mismatch_cannot_become_available():
    store = RuntimeIngestStore()
    store.declare_artifact(_artifact())
    store.begin_upload("ART-1")
    with pytest.raises(RuntimeIngestError, match="ARTIFACT_HASH_MISMATCH"):
        store.mark_available("ART-1", verified_size_bytes=12, verified_sha256="b" * 64)


def test_failed_upload_can_retry_without_redeclaring_artifact():
    store = RuntimeIngestStore()
    store.declare_artifact(_artifact())
    store.begin_upload("ART-1")
    store.mark_upload_failed("ART-1")
    store.begin_upload("ART-1")
    available = store.mark_available("ART-1", verified_size_bytes=12, verified_sha256="a" * 64)
    assert available.is_available
