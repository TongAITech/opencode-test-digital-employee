from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import Task
from rc7_runtime.rc72_data_resources import DataAccessMode, DataLeaseManager, DataResourceConflict
from rc7_runtime.rc72_domain import ExecutionTaskUnit, ReleaseBatch, TestObligation
from rc7_runtime.rc72_linkage import WorkItemAttemptBinding, WorkItemAttemptState
from rc7_runtime.rc72_repository import CanonicalRC72Repository
from rc7_runtime.truth_overlay import append_entity


def _persist_attempt(repo, truth, *, suffix, worker_id):
    etu_id = "ETU-%s" % suffix
    wi = "WI-%s" % suffix
    att = "ATT-%s" % suffix
    repo.persist(
        ExecutionTaskUnit(
            etu_id=etu_id,
            mission_id="M-1",
            release_batch_id="RB-1",
            obligation_id="TO-1",
            case_ids=["TC-%s" % suffix],
            primary_goal="data-bound execution %s" % suffix,
            primary_code_slice="Service#create",
            test_level="L3",
            primary_oracle="HTTP+DB",
            data_domain="subproject",
            primary_tool_family="api",
            planning_snapshot_ref="PLAN-1",
            cohesion_score=1.0,
            cohesion_explanation="same exact data domain",
            required_capabilities=["data:reserve"],
            estimated_duration_minutes=5,
            estimated_cost=1.0,
        )
    )
    append_entity(
        truth,
        Task(
            task_id=wi,
            mission_id="M-1",
            node="N7_EXECUTION",
            task_type="DATA_BOUND_EXECUTION",
            objective="execute with reserved data",
            required_capabilities=["data:reserve"],
            input_artifact_refs=[etu_id],
            acceptance_criteria=["data lease evidence persisted"],
        ),
        release_id="RC7.2",
    )
    repo.persist(
        WorkItemAttemptBinding(
            binding_id="BIND-%s" % suffix,
            mission_id="M-1",
            etu_id=etu_id,
            workitem_id=wi,
            case_id="TC-%s" % suffix,
            attempt_id=att,
            worker_id=worker_id,
            session_id="SESSION-%s" % suffix,
            task_lease_ref="TASKLEASE-%s" % suffix,
            state=WorkItemAttemptState.RUNNING,
        )
    )
    return wi, att, worker_id


def _setup(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    repo = CanonicalRC72Repository(truth, release_id="RC7.2")
    repo.persist(
        ReleaseBatch(
            release_batch_id="RB-1",
            mission_id="M-1",
            name="batch",
            application_ids=["cfg-center"],
            requirement_ids=["REQ-1"],
        )
    )
    repo.persist(
        TestObligation(
            obligation_id="TO-1",
            mission_id="M-1",
            release_batch_id="RB-1",
            requirement_id="REQ-1",
            sst_id="SST-1",
            application_id="cfg-center",
            business_scenario="configure subproject",
            business_rule="subproject must be unconfigured before create",
            risk_level="HIGH",
            test_level="L3",
            code_slice_refs=["Service#create"],
            oracle_refs=["HTTP", "DB"],
        )
    )
    a = _persist_attempt(repo, truth, suffix="A", worker_id="WORKER-A")
    b = _persist_attempt(repo, truth, suffix="B", worker_id="WORKER-B")
    manager = DataLeaseManager(truth, release_id="RC7.2")
    manager.register_data_ref(
        data_ref="data://subproject/SP-001",
        data_domain="subproject",
        verified=True,
        mutable=True,
        metadata_ref="evidence://n5/SP-001",
    )
    manager.register_data_ref(
        data_ref="data://dictionary/DICT-001",
        data_domain="dictionary",
        verified=True,
        mutable=False,
        metadata_ref="evidence://n5/DICT-001",
    )
    return truth, manager, a, b


def _acquire(manager, ids, data_ref, mode, lease_id=None):
    wi, att, worker = ids
    return manager.acquire(
        data_lease_id=lease_id,
        data_ref=data_ref,
        mission_id="M-1",
        workitem_id=wi,
        attempt_id=att,
        worker_id=worker,
        mode=mode,
        ttl_seconds=300,
        cleanup_policy="release reservation",
    )


def test_mutable_data_requires_exact_exclusive_reservation(tmp_path: Path):
    truth, manager, a, _ = _setup(tmp_path)
    lease = _acquire(manager, a, "data://subproject/SP-001", DataAccessMode.EXCLUSIVE_WRITE)
    row = truth.query("rc72_data_lease", data_lease_id=lease.data_lease_id)[0]
    assert row["data_ref"] == "data://subproject/SP-001"
    assert row["mode"] == "EXCLUSIVE_WRITE"
    assert row["workitem_id"] == "WI-A"
    assert row["attempt_id"] == "ATT-A"
    assert row["worker_id"] == "WORKER-A"
    assert row["cleanup_policy"] == "release reservation"


def test_second_exclusive_owner_gets_conflict_and_no_silent_alternative_data(tmp_path: Path):
    truth, manager, a, b = _setup(tmp_path)
    first = _acquire(manager, a, "data://subproject/SP-001", DataAccessMode.EXCLUSIVE_WRITE)
    with pytest.raises(DataResourceConflict, match="DATA_RESOURCE_CONFLICT"):
        _acquire(manager, b, "data://subproject/SP-001", DataAccessMode.EXCLUSIVE_WRITE)
    active = [r for r in truth.query("rc72_data_lease", data_ref="data://subproject/SP-001") if r["state"] == "ACTIVE"]
    assert len(active) == 1
    assert active[0]["data_lease_id"] == first.data_lease_id
    # Runtime must not guess or substitute another DataRef on behalf of the executor.
    assert not truth.query("rc72_data_lease", workitem_id="WI-B")


def test_shared_reference_data_can_have_multiple_readers(tmp_path: Path):
    _, manager, a, b = _setup(tmp_path)
    first = _acquire(manager, a, "data://dictionary/DICT-001", DataAccessMode.SHARED_READ)
    second = _acquire(manager, b, "data://dictionary/DICT-001", DataAccessMode.SHARED_READ)
    assert first.data_lease_id != second.data_lease_id
    assert first.data_ref == second.data_ref


def test_exclusive_write_conflicts_with_active_shared_read(tmp_path: Path):
    _, manager, a, b = _setup(tmp_path)
    _acquire(manager, a, "data://dictionary/DICT-001", DataAccessMode.SHARED_READ)
    with pytest.raises(DataResourceConflict, match="DATA_RESOURCE_CONFLICT"):
        _acquire(manager, b, "data://dictionary/DICT-001", DataAccessMode.EXCLUSIVE_WRITE)


def test_unverified_data_ref_cannot_be_leased(tmp_path: Path):
    truth, manager, a, _ = _setup(tmp_path)
    manager.register_data_ref(
        data_ref="data://subproject/SP-UNKNOWN",
        data_domain="subproject",
        verified=False,
        mutable=True,
        metadata_ref="evidence://n5/pending",
    )
    with pytest.raises(Exception, match="DATA_REF_NOT_VERIFIED"):
        _acquire(manager, a, "data://subproject/SP-UNKNOWN", DataAccessMode.EXCLUSIVE_WRITE)
    assert not truth.query("rc72_data_lease", data_ref="data://subproject/SP-UNKNOWN")


def test_mutable_data_cannot_be_shared_read_for_execution(tmp_path: Path):
    _, manager, a, _ = _setup(tmp_path)
    with pytest.raises(Exception, match="MUTABLE_DATA_REQUIRES_EXCLUSIVE_WRITE"):
        _acquire(manager, a, "data://subproject/SP-001", DataAccessMode.SHARED_READ)


def test_lease_is_bound_to_attempt_worker_and_exact_data_ref(tmp_path: Path):
    _, manager, a, _ = _setup(tmp_path)
    lease = _acquire(manager, a, "data://subproject/SP-001", DataAccessMode.EXCLUSIVE_WRITE)
    assert manager.assert_usable(
        data_lease_id=lease.data_lease_id,
        mission_id="M-1",
        workitem_id="WI-A",
        attempt_id="ATT-A",
        worker_id="WORKER-A",
        data_ref="data://subproject/SP-001",
    )["state"] == "ACTIVE"
    with pytest.raises(Exception, match="DATA_LEASE_ATTEMPT_MISMATCH"):
        manager.assert_usable(
            data_lease_id=lease.data_lease_id,
            mission_id="M-1",
            workitem_id="WI-A",
            attempt_id="ATT-B",
            worker_id="WORKER-A",
            data_ref="data://subproject/SP-001",
        )
    with pytest.raises(Exception, match="DATA_LEASE_DATA_REF_MISMATCH"):
        manager.assert_usable(
            data_lease_id=lease.data_lease_id,
            mission_id="M-1",
            workitem_id="WI-A",
            attempt_id="ATT-A",
            worker_id="WORKER-A",
            data_ref="data://subproject/SP-OTHER",
        )


def test_release_runs_auditable_cleanup_and_allows_new_lease_not_transfer(tmp_path: Path):
    truth, manager, a, b = _setup(tmp_path)
    old = _acquire(manager, a, "data://subproject/SP-001", DataAccessMode.EXCLUSIVE_WRITE)
    manager.release(old.data_lease_id, cleanup_evidence_ref="evidence://cleanup/SP-001", reason="ETU complete")
    old_row = truth.query("rc72_data_lease", data_lease_id=old.data_lease_id)[0]
    assert old_row["state"] == "RELEASED"
    assert old_row["cleanup_evidence_ref"] == "evidence://cleanup/SP-001"
    new = _acquire(manager, b, "data://subproject/SP-001", DataAccessMode.EXCLUSIVE_WRITE)
    assert new.data_lease_id != old.data_lease_id


def test_expiry_fail_closed_and_resource_can_be_reacquired_with_new_lease(tmp_path: Path):
    _, manager, a, b = _setup(tmp_path)
    old = _acquire(manager, a, "data://subproject/SP-001", DataAccessMode.EXCLUSIVE_WRITE)
    row = manager.lease(old.data_lease_id)
    with pytest.raises(Exception, match="DATA_LEASE_EXPIRED"):
        manager.assert_usable(
            data_lease_id=old.data_lease_id,
            mission_id="M-1",
            workitem_id="WI-A",
            attempt_id="ATT-A",
            worker_id="WORKER-A",
            data_ref="data://subproject/SP-001",
            now=row["expires_at"] + 1,
        )
    new = manager.acquire(
        data_ref="data://subproject/SP-001",
        mission_id="M-1",
        workitem_id="WI-B",
        attempt_id="ATT-B",
        worker_id="WORKER-B",
        mode=DataAccessMode.EXCLUSIVE_WRITE,
        ttl_seconds=300,
        cleanup_policy="release reservation",
        now=row["expires_at"] + 1,
    )
    assert new.data_lease_id != old.data_lease_id


def test_data_resource_and_lease_truth_survive_r1_replay(tmp_path: Path):
    truth, manager, a, _ = _setup(tmp_path)
    lease = _acquire(manager, a, "data://subproject/SP-001", DataAccessMode.EXCLUSIVE_WRITE)
    replayed = TruthRuntime(tmp_path / "r1.jsonl")
    data = replayed.query("rc72_data_resource", data_ref="data://subproject/SP-001")[0]
    persisted = replayed.query("rc72_data_lease", data_lease_id=lease.data_lease_id)[0]
    assert data["verified"] is True
    assert data["mutable"] is True
    assert persisted["data_ref"] == data["data_ref"]
    assert persisted["attempt_id"] == "ATT-A"
