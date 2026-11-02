from __future__ import annotations

import tempfile
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine

from rc8_center.infrastructure.postgres import Base, PostgresStore
from rc8_center.infrastructure.postgres_artifact import ArtifactMetadataRow
from rc8_center.single_node_truth_reader import ProductionCenterR1TruthReader, ProductionTruthReaderError
from rc8_node.single_node_integration_proof import SingleNodeDurableIntegrationProofRunner
from rc8_runtime import RuntimeProducerKind
from rc8_runtime.r1_runtime import CentralR1RuntimeLedger


def _reader():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    store = PostgresStore(engine)
    temp = tempfile.NamedTemporaryFile(prefix="rc8-r1-artifact-preflight-", suffix=".jsonl", delete=False)
    temp.close()
    return store, ProductionCenterR1TruthReader(
        store=store,
        r1_ledger=CentralR1RuntimeLedger(temp.name),
    )


def _add_artifact(store, *, artifact_id: str, test_run_id: str, attempt_id: str = "lease-1"):
    with store.session() as session:
        session.add(ArtifactMetadataRow(
            artifact_id=artifact_id,
            test_run_id=test_run_id,
            work_item_id="wi-1",
            node_id="node-1",
            kind="STAGE_EVIDENCE",
            producer_kind=RuntimeProducerKind.WORKER.value,
            producer_ref="worker-1",
            file_name="evidence.json",
            sha256="1" * 64,
            size_bytes=2,
            availability="AVAILABLE",
            case_id=None,
            attempt_id=attempt_id,
            step_id=None,
            refs=[],
            metadata_json={},
            created_at=1,
        ))


def test_clean_test_run_has_no_preseeded_artifact_truth():
    _store, reader = _reader()
    reader.assert_no_artifacts_for_test_run("run-clean")


def test_preseeded_worker_artifact_fails_production_causality_preflight():
    store, reader = _reader()
    _add_artifact(store, artifact_id="artifact-preseeded", test_run_id="run-dirty")

    with pytest.raises(
        ProductionTruthReaderError,
        match="PRODUCTION_CAUSALITY_PREFLIGHT_ARTIFACT_ALREADY_EXISTS:artifact-preseeded",
    ):
        reader.assert_no_artifacts_for_test_run("run-dirty")


def test_artifact_preflight_requires_test_run_identity():
    _store, reader = _reader()
    with pytest.raises(ProductionTruthReaderError, match="TEST_RUN_ID_REQUIRED"):
        reader.assert_no_artifacts_for_test_run("   ")


def test_complete_worker_artifact_set_matches_observed_traversal():
    store, reader = _reader()
    _add_artifact(store, artifact_id="art-1", test_run_id="run-match", attempt_id="lease-1")
    _add_artifact(store, artifact_id="art-2", test_run_id="run-match", attempt_id="lease-2")

    assert reader.worker_artifact_refs_for_test_run("run-match") == ("artifact:art-1", "artifact:art-2")
    reader.assert_worker_artifact_refs_match_observed_evidence(
        test_run_id="run-match",
        observed_evidence_refs=("artifact:art-2", "artifact:art-1"),
    )


def test_unexpected_worker_artifact_fails_complete_artifact_denominator():
    store, reader = _reader()
    _add_artifact(store, artifact_id="art-expected", test_run_id="run-extra", attempt_id="lease-1")
    _add_artifact(store, artifact_id="art-unexpected", test_run_id="run-extra", attempt_id="lease-extra")

    with pytest.raises(
        ProductionTruthReaderError,
        match=r"PRODUCTION_CAUSALITY_ARTIFACT_SET_MISMATCH:run-extra:missing=-:unexpected=artifact:art-unexpected",
    ):
        reader.assert_worker_artifact_refs_match_observed_evidence(
            test_run_id="run-extra",
            observed_evidence_refs=("artifact:art-expected",),
        )


def test_missing_worker_artifact_fails_complete_artifact_denominator():
    store, reader = _reader()
    _add_artifact(store, artifact_id="art-present", test_run_id="run-missing")

    with pytest.raises(
        ProductionTruthReaderError,
        match=r"PRODUCTION_CAUSALITY_ARTIFACT_SET_MISMATCH:run-missing:missing=artifact:art-missing:unexpected=-",
    ):
        reader.assert_worker_artifact_refs_match_observed_evidence(
            test_run_id="run-missing",
            observed_evidence_refs=("artifact:art-present", "artifact:art-missing"),
        )


def test_composed_production_runner_binds_complete_artifact_set_before_truth_promotion():
    calls = []

    class Truth:
        def assert_no_attempts_for_test_run(self, _test_run_id): pass
        def assert_no_r1_attempt_lifecycle_for_test_run(self, _test_run_id): pass
        def assert_attempt_ids_match_observed_leases(self, **_kwargs): pass
        def assert_r1_attempt_lifecycle_matches_observed_leases(self, **_kwargs): pass
        def assert_worker_artifact_refs_match_observed_evidence(self, *, test_run_id, observed_evidence_refs):
            calls.append((test_run_id, tuple(observed_evidence_refs)))

    observed = SimpleNamespace(
        work_item_ids=("wi-1",), attempt_ids=("lease-1",), lease_ids=("lease-1",),
        evidence_refs=("artifact:art-1",),
    )
    durable = SimpleNamespace(
        verified_work_items=("wi-1",), verified_attempts=("lease-1",),
        verified_production_node_id="node-1", verified_r1_start_events=("evt-start-1",),
        verified_r1_events=("evt-complete-1",), bank_reality_verified=False, release_status="HOLD",
    )
    runner = SingleNodeDurableIntegrationProofRunner.__new__(SingleNodeDurableIntegrationProofRunner)
    runner._production_components_verified = True
    runner.expected_node_id = "node-1"
    runner.truth_reader = Truth()
    runner.observer = SimpleNamespace(run=lambda **_kwargs: observed)
    runner.verifier = SimpleNamespace(verify=lambda _observed: durable)

    proof = runner.run(test_run_id="run-1")

    assert calls == [("run-1", ("artifact:art-1",))]
    assert proof.production_causality_verified is False
    assert proof.release_status == "HOLD"
