from __future__ import annotations

import tempfile

import pytest
from sqlalchemy import create_engine

from rc8_center.infrastructure.postgres import Base, PostgresStore
from rc8_center.infrastructure.postgres_artifact import ArtifactMetadataRow
from rc8_center.single_node_truth_reader import ProductionCenterR1TruthReader, ProductionTruthReaderError
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


def test_clean_test_run_has_no_preseeded_artifact_truth():
    _store, reader = _reader()
    reader.assert_no_artifacts_for_test_run("run-clean")


def test_preseeded_worker_artifact_fails_production_causality_preflight():
    store, reader = _reader()
    with store.session() as session:
        session.add(ArtifactMetadataRow(
            artifact_id="artifact-preseeded",
            test_run_id="run-dirty",
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
            attempt_id="lease-1",
            step_id=None,
            refs=[],
            metadata_json={},
            created_at=1,
        ))

    with pytest.raises(
        ProductionTruthReaderError,
        match="PRODUCTION_CAUSALITY_PREFLIGHT_ARTIFACT_ALREADY_EXISTS:artifact-preseeded",
    ):
        reader.assert_no_artifacts_for_test_run("run-dirty")


def test_artifact_preflight_requires_test_run_identity():
    _store, reader = _reader()
    with pytest.raises(ProductionTruthReaderError, match="TEST_RUN_ID_REQUIRED"):
        reader.assert_no_artifacts_for_test_run("   ")
