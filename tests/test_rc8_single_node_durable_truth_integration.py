from __future__ import annotations

import tempfile

from sqlalchemy import create_engine

from rc8_center.infrastructure.postgres import AttemptRow, Base, PostgresStore
from rc8_center.infrastructure.postgres_artifact import ArtifactMetadataRow
from rc8_center.infrastructure.postgres_control import WorkItemRow
from rc8_center.single_node_truth_reader import ProductionCenterR1TruthReader
from rc8_node.single_node_full_loop_proof import FROZEN_N1_N10_STAGES, SingleNodeFullLoopProof
from rc8_node.single_node_truth import SingleNodeCenterTruthVerifier
from rc8_runtime import RuntimeProducerKind
from rc8_runtime.r1_runtime import CentralR1RuntimeLedger, runtime_event


def test_frozen_denominator_is_verified_through_production_durable_truth_boundaries():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    store = PostgresStore(engine)
    temp = tempfile.NamedTemporaryFile(prefix="rc8-r1-integration-", suffix=".jsonl", delete=False)
    temp.close()
    ledger = CentralR1RuntimeLedger(temp.name)

    work_item_ids = []
    lease_ids = []
    stage_instance_ids = []
    attempt_ids = []
    evidence_refs = []
    with store.session() as session:
        for index, stage in enumerate(FROZEN_N1_N10_STAGES, start=1):
            work_item_id = "wi-%02d" % index
            lease_id = "lease-%02d" % index
            stage_instance_id = "stage-%02d" % index
            attempt_id = lease_id
            artifact_id = "art-%02d" % index
            work_item_ids.append(work_item_id)
            lease_ids.append(lease_id)
            stage_instance_ids.append(stage_instance_id)
            attempt_ids.append(attempt_id)
            evidence_refs.append("artifact:%s" % artifact_id)
            session.add(WorkItemRow(
                work_item_id=work_item_id, test_run_id="run-integration", stage=stage, scope_refs=[],
                required_capabilities=[], state="COMPLETED", lease_id=None,
                lease_owner_node_id=None, lease_expires_at=None,
            ))
            session.add(AttemptRow(
                attempt_id=attempt_id, test_run_id="run-integration", stage_instance_id=stage_instance_id,
                work_item_id=work_item_id, producer_node_id="node-1", producer_ref="worker-%02d" % index,
                input_snapshot_ref="snapshot:integration", status="COMPLETED", case_id=None,
                action_refs=[], assertion_refs=[], evidence_refs=["artifact:%s" % artifact_id], coverage_refs=[],
                gap_refs=[], defect_refs=[], failure_ownership=None, started_at=index, finished_at=index + 1, payload={},
            ))
            session.add(ArtifactMetadataRow(
                artifact_id=artifact_id, test_run_id="run-integration", work_item_id=work_item_id, node_id="node-1",
                kind="STAGE_EVIDENCE", producer_kind=RuntimeProducerKind.NODE_AGENT.value,
                producer_ref="worker-%02d" % index, file_name="%s.json" % stage.lower(), sha256=("%064x" % index),
                size_bytes=2, availability="AVAILABLE", case_id=None, attempt_id=attempt_id, step_id=None,
                refs=[], metadata_json={}, created_at=index + 1,
            ))

    for index, (work_item_id, attempt_id) in enumerate(zip(work_item_ids, attempt_ids), start=1):
        ledger.append_runtime(runtime_event(
            event_id="evt-%02d" % index, test_run_id="run-integration", work_item_id=work_item_id,
            node_id="node-1", producer_kind=RuntimeProducerKind.NODE_AGENT,
            producer_ref="worker-%02d" % index, event_type="ATTEMPT_COMPLETED", sequence=index,
            attempt_id=attempt_id, occurred_at=index + 1,
        ))

    observed = SingleNodeFullLoopProof(
        test_run_id="run-integration", stages=FROZEN_N1_N10_STAGES,
        work_item_ids=tuple(work_item_ids), lease_ids=tuple(lease_ids),
        stage_instance_ids=tuple(stage_instance_ids), attempt_ids=tuple(attempt_ids),
        evidence_refs=tuple(evidence_refs),
    )
    truth = SingleNodeCenterTruthVerifier(
        truth_reader=ProductionCenterR1TruthReader(store=store, r1_ledger=ledger)
    ).verify(observed)

    assert truth.status == "CENTER_R1_EVIDENCE_VERIFIED_NOT_AUTHORIZED"
    assert truth.verified_work_items == tuple(work_item_ids)
    assert truth.verified_attempts == tuple(attempt_ids)
    assert truth.verified_artifacts == tuple("art-%02d" % i for i in range(1, 16))
    assert truth.verified_r1_events == tuple("evt-%02d" % i for i in range(1, 16))
    assert truth.bank_reality_verified is False
    assert truth.release_status == "HOLD"
