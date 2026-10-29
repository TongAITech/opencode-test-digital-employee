from __future__ import annotations

import tempfile

import pytest
from sqlalchemy import create_engine

from rc8_center.infrastructure.postgres import AttemptRow, Base, PostgresStore
from rc8_center.infrastructure.postgres_artifact import ArtifactMetadataRow
from rc8_center.infrastructure.postgres_control import WorkItemRow
from rc8_center.single_node_truth_reader import ProductionCenterR1TruthReader, ProductionTruthReaderError
from rc8_runtime import RuntimeProducerKind
from rc8_runtime.r1_runtime import CentralR1RuntimeLedger, runtime_event


def _reader():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    store = PostgresStore(engine)
    temp = tempfile.NamedTemporaryFile(prefix="rc8-r1-", suffix=".jsonl", delete=False)
    temp.close()
    ledger = CentralR1RuntimeLedger(temp.name)
    return store, ledger, ProductionCenterR1TruthReader(store=store, r1_ledger=ledger)


def _seed(store, ledger):
    with store.session() as session:
        session.add(WorkItemRow(
            work_item_id="wi-1", test_run_id="run-1", stage="SCOPE_INTAKE", scope_refs=[],
            required_capabilities=[], state="COMPLETED", lease_id=None,
            lease_owner_node_id=None, lease_expires_at=None,
        ))
        session.add(AttemptRow(
            attempt_id="att-1", test_run_id="run-1", stage_instance_id="stage-1",
            work_item_id="wi-1", producer_node_id="node-1", producer_ref="worker-1",
            input_snapshot_ref="snapshot:1", status="COMPLETED", case_id=None,
            action_refs=[], assertion_refs=[], evidence_refs=["artifact:art-1"], coverage_refs=[],
            gap_refs=[], defect_refs=[], failure_ownership=None, started_at=1, finished_at=2, payload={},
        ))
        session.add(ArtifactMetadataRow(
            artifact_id="art-1", test_run_id="run-1", work_item_id="wi-1", node_id="node-1",
            kind="SCOPE_EVIDENCE", producer_kind=RuntimeProducerKind.NODE_AGENT.value, producer_ref="worker-1",
            file_name="scope.json", sha256="a" * 64, size_bytes=2, availability="AVAILABLE", case_id=None,
            attempt_id="att-1", step_id=None, refs=[], metadata_json={}, created_at=2,
        ))
    ledger.append_runtime(runtime_event(
        event_id="evt-1", test_run_id="run-1", work_item_id="wi-1", node_id="node-1",
        producer_kind=RuntimeProducerKind.NODE_AGENT, producer_ref="worker-1",
        event_type="ATTEMPT_COMPLETED", sequence=1, attempt_id="att-1", occurred_at=2,
    ))


def test_reader_returns_only_durable_production_truth():
    store, ledger, reader = _reader()
    _seed(store, ledger)

    assert reader.get_work_item("wi-1") == {
        "work_item_id": "wi-1", "test_run_id": "run-1", "stage": "SCOPE_INTAKE", "status": "COMPLETED"
    }
    assert reader.get_attempt("att-1")["work_item_id"] == "wi-1"
    assert reader.get_artifact("art-1") == {
        "artifact_id": "art-1", "test_run_id": "run-1", "work_item_id": "wi-1",
        "attempt_id": "att-1", "status": "COMPLETED",
    }
    event = reader.find_r1_attempt_completed(test_run_id="run-1", work_item_id="wi-1", attempt_id="att-1")
    assert event["event_id"] == "evt-1"
    assert event["event_type"] == "ATTEMPT_COMPLETED"


def test_reader_fails_closed_on_duplicate_terminal_r1_truth():
    store, ledger, reader = _reader()
    _seed(store, ledger)
    ledger.append_runtime(runtime_event(
        event_id="evt-2", test_run_id="run-1", work_item_id="wi-1", node_id="node-1",
        producer_kind=RuntimeProducerKind.NODE_AGENT, producer_ref="worker-1",
        event_type="ATTEMPT_COMPLETED", sequence=2, attempt_id="att-1", occurred_at=3,
    ))

    with pytest.raises(ProductionTruthReaderError, match="R1_ATTEMPT_COMPLETED_NOT_UNIQUE"):
        reader.find_r1_attempt_completed(test_run_id="run-1", work_item_id="wi-1", attempt_id="att-1")


def test_reader_never_falls_back_when_truth_is_missing():
    _store, _ledger, reader = _reader()
    assert reader.get_work_item("missing") is None
    assert reader.get_attempt("missing") is None
    assert reader.get_artifact("missing") is None
    assert reader.find_r1_attempt_completed(test_run_id="run-x", work_item_id="wi-x", attempt_id="att-x") is None
