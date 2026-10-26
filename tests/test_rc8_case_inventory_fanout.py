from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from sqlalchemy import create_engine

from rc8_center.artifacts import FileArtifactStore
from rc8_center.case_inventory import CASE_INVENTORY_KIND, CASE_INVENTORY_SCHEMA, CenterFrozenCaseInventoryResolver, FrozenCaseInventoryError
from rc8_center.control_plane import CenterControlError, WorkItemRecord, WorkItemState
from rc8_center.fanout_progression import FanoutSafeRequirementLoopProgressor
from rc8_center.infrastructure import Base, PostgresArtifactRepository, PostgresCenterRepository, PostgresGovernanceRepository, PostgresStore
from rc8_center.mission_service import CenterMissionService
from rc8_center.runtime_mutation_producer import _case_id_from_scope_refs
from rc8_runtime import ArtifactAvailability, AttemptRecord, AttemptStatus, RuntimeProducerKind, WorkItemIdentity
from rc8_runtime.artifacts import ArtifactManifest
from rc8_runtime.governance import StageInstance, StageState
from rc8_runtime.mission_graph import MissionStageType


def _setup(cases):
    tmp = TemporaryDirectory()
    engine = create_engine("sqlite+pysqlite:///%s/case-fanout.db" % tmp.name, future=True)
    Base.metadata.create_all(engine)
    store = PostgresStore(engine)
    store.create_test_run("TR-CASE", test_round_id="ROUND-CASE", payload={}, now=100)
    governance = PostgresGovernanceRepository(store)
    control = PostgresCenterRepository(store)
    artifacts = PostgresArtifactRepository(store)
    artifact_store = FileArtifactStore(str(Path(tmp.name) / "artifacts"), artifacts)
    mission = CenterMissionService(governance)
    scope = "delivery-scope:SCOPE-CASE"
    design_stage = StageInstance(stage_instance_id="stage-design", test_run_id="TR-CASE", stage_type=MissionStageType.TEST_DESIGN.value, scope_version=scope, attempt_no=1, state=StageState.COMPLETED, output_refs=("artifact:CASE-INVENTORY",))
    n5_stage = StageInstance(stage_instance_id="stage-n5", test_run_id="TR-CASE", stage_type=MissionStageType.PRECONDITION_DATA_PREP.value, scope_version=scope, attempt_no=1, state=StageState.READY)
    governance.upsert_stage(design_stage)
    governance.upsert_stage(n5_stage)
    design_work = WorkItemRecord(identity=WorkItemIdentity(work_item_id="work-design", test_run_id="TR-CASE", stage=MissionStageType.TEST_DESIGN.value, scope_refs=(scope, "stage-instance:stage-design", "test-round:ROUND-CASE"), required_capabilities=()), state=WorkItemState.COMPLETED)
    control.upsert_work_item(design_work)
    control.link_work_item_to_stage(work_item_id="work-design", stage_instance_id="stage-design", test_run_id="TR-CASE", created_at=101)
    payload = {"schema_version": CASE_INVENTORY_SCHEMA, "test_run_id": "TR-CASE", "stage_instance_id": "stage-design", "scope_version": scope, "cases": cases}
    content = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    digest = hashlib.sha256(content).hexdigest()
    manifest = ArtifactManifest(artifact_id="CASE-INVENTORY", test_run_id="TR-CASE", work_item_id="work-design", node_id="NODE-DESIGN", kind=CASE_INVENTORY_KIND, producer_kind=RuntimeProducerKind.WORKER, producer_ref="worker:test-design", file_name="case-inventory.json", sha256=digest, size_bytes=len(content), availability=ArtifactAvailability.PENDING_UPLOAD, attempt_id="ATT-DESIGN", metadata={"schema_version": CASE_INVENTORY_SCHEMA}, created_at=102)
    artifact_store.begin(manifest)
    artifact_store.upload_chunk("CASE-INVENTORY", offset=0, data=content)
    artifact_store.complete("CASE-INVENTORY")
    governance.upsert_attempt(AttemptRecord(attempt_id="ATT-DESIGN", test_run_id="TR-CASE", stage_instance_id="stage-design", work_item_id="work-design", producer_node_id="NODE-DESIGN", producer_ref="worker:test-design", input_snapshot_ref=scope, status=AttemptStatus.COMPLETED, evidence_refs=("artifact:CASE-INVENTORY",), started_at=101, finished_at=102))
    resolver = CenterFrozenCaseInventoryResolver(governance_repository=governance, control_repository=control, artifact_repository=artifacts, artifact_store=artifact_store)
    progressor = FanoutSafeRequirementLoopProgressor(store=store, mission_service=mission, governance_repository=governance, control_repository=control, artifact_repository=artifacts, case_inventory_resolver=resolver)
    return tmp, control, resolver, progressor, n5_stage


def test_n5_materializes_deterministic_work_per_frozen_n4_case() -> None:
    cases = [
        {"case_id": "CASE-02", "case_revision_ref": "case-revision:CASE-02:r3"},
        {"case_id": "CASE-01", "case_revision_ref": "case-revision:CASE-01:r7"},
    ]
    tmp, control, resolver, progressor, n5_stage = _setup(cases)
    try:
        inventory = resolver.resolve(test_run_id="TR-CASE", scope_version=n5_stage.scope_version)
        assert [case.case_id for case in inventory.cases] == ["CASE-01", "CASE-02"]
        _ready, materialized = progressor.materialize_ready_work("TR-CASE")
        assert len(materialized) == 2
        links = control.list_work_item_links_for_stage("stage-n5")
        assert len(links) == 2
        case_refs = set()
        for link in links:
            work = control.get_work_item(link.work_item_id)
            assert work is not None
            assert work.identity.stage == MissionStageType.PRECONDITION_DATA_PREP.value
            assert inventory.artifact_ref in work.identity.scope_refs
            assert inventory.fingerprint_ref in work.identity.scope_refs
            case_refs.add(next(ref for ref in work.identity.scope_refs if ref.startswith("case:")))
        assert case_refs == {"case:CASE-01", "case:CASE-02"}
        _ready2, materialized2 = progressor.materialize_ready_work("TR-CASE")
        assert materialized2 == tuple()
        assert len(control.list_work_item_links_for_stage("stage-n5")) == 2
    finally:
        tmp.cleanup()


def test_duplicate_case_identity_fails_closed_before_materialization() -> None:
    cases = [
        {"case_id": "CASE-01", "case_revision_ref": "case-revision:CASE-01:r1"},
        {"case_id": "CASE-01", "case_revision_ref": "case-revision:CASE-01:r2"},
    ]
    tmp, control, _resolver, progressor, _n5_stage = _setup(cases)
    try:
        with pytest.raises(FrozenCaseInventoryError, match="DUPLICATE_CASE_ID"):
            progressor.materialize_ready_work("TR-CASE")
        assert control.list_work_item_links_for_stage("stage-n5") == []
    finally:
        tmp.cleanup()


def test_case_scope_identity_is_single_and_unambiguous() -> None:
    assert _case_id_from_scope_refs(("delivery-scope:S1", "case:CASE-01")) == "CASE-01"
    assert _case_id_from_scope_refs(("delivery-scope:S1",)) is None
    with pytest.raises(CenterControlError, match="WORK_ITEM_CASE_SCOPE_AMBIGUOUS"):
        _case_id_from_scope_refs(("case:CASE-01", "case:CASE-02"))
