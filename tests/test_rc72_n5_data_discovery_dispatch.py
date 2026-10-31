from pathlib import Path

from rc7_runtime.rc72_n5_data_discovery_dispatch import (
    N5DataDiscoveryDispatchService,
)
from rc7_runtime.rc72_n5_data_inventory import N5DataRequirementInventoryService
from rc7_runtime.rc72_n5_data_resolution import N5DataResolutionService

from rc72_n2_test_support import BATCH, COMMIT, MISSION, RELEASE
from test_rc72_n5_data_inventory import _n5_ready
from test_rc72_n5_data_resolution import _bind, _evidence, _register_resource


def _resolved_inventory(tmp_path: Path, monkeypatch):
    truth, scopes, completed = _n5_ready(tmp_path, monkeypatch)
    inventory = N5DataRequirementInventoryService(
        truth, source_commit=COMMIT
    ).materialize(release_batch_id=BATCH)
    resolver = N5DataResolutionService(
        truth,
        release_id=RELEASE,
        source_commit=COMMIT,
    )
    resolution = resolver.resolve_all(release_batch_id=BATCH)
    return truth, scopes, completed, inventory, resolver, resolution


def _bind_requirement(truth, resolver, data_requirement_id: str, suffix: str):
    requirement = truth.query(
        "rc72_n5_data_requirement", data_requirement_id=data_requirement_id
    )[0]
    data_ref = "data://fat1/pcc/config/%s" % suffix
    evidence_id = "EVD-N5-DISCOVERY-DISPATCH-%s" % suffix
    _register_resource(truth, data_ref=data_ref, verified=True, mutable=False)
    _evidence(truth, evidence_id, [data_requirement_id, data_ref])
    return _bind(resolver, requirement, data_ref, evidence_id)


def test_n5_dispatches_one_small_workitem_per_discovery_required_requirement(
    tmp_path: Path, monkeypatch
):
    truth, _scopes, _completed, inventory, _resolver, resolution = _resolved_inventory(
        tmp_path, monkeypatch
    )
    assert resolution["discovery_required_count"] == inventory["data_requirement_count"]

    result = N5DataDiscoveryDispatchService(
        truth,
        release_id=RELEASE,
        source_commit=COMMIT,
    ).dispatch(release_batch_id=BATCH)

    assert result["status"] == "DISPATCHED"
    assert result["dispatch_count"] == inventory["data_requirement_count"]
    assert set(result["data_requirement_ids"]) == set(
        inventory["data_requirement_ids"]
    )
    assert result["team_role"] == "DATA_PREPARER"
    assert result["execution_substrate"] == "DSH_AGENT_TEAMS"
    assert result["worker_policy"] == "FRESH_SESSION_REQUIRED"
    assert result["n5_state"] == "RUNNING"
    assert result["n6_state"] == "NOT_STARTED"

    receipts = truth.query(
        "rc72_n5_data_discovery_dispatch", release_batch_id=BATCH
    )
    assert len(receipts) == inventory["data_requirement_count"]
    assert len({row["workitem_id"] for row in receipts}) == len(receipts)
    assert len({row["data_requirement_id"] for row in receipts}) == len(receipts)
    for row in receipts:
        assert row["status"] == "READY_FOR_ASSIGNMENT"
        assert row["required_capabilities"] == ["test_data"]
        assert row["parent_artifact_refs"]
        assert row["dependency_workitem_refs"]
        assert row["case_preconditions"]
        assert row["case_code_trace"]
        assert "data_ref" not in row
        assert "worker_instance_id" not in row
        assert "dsh_session_id" not in row
        assert "attempt_id" not in row
        task = truth.query("rc7_task", task_id=row["workitem_id"])[0]
        assert task["node"] == "TEST_DATA"
        assert task["state"] == "READY"
        assert task["required_capabilities"] == ["test_data"]
        assert task["input_artifact_refs"] == row["parent_artifact_refs"]
        assert task["dependency_task_ids"] == row["dependency_workitem_refs"]
        assert task.get("lease_owner") in {None, ""}

    assert truth.query("rc72_data_lease") == []
    assert truth.query(
        "rc72_node_delivery", mission_id=MISSION, node_type="N5_TEST_DATA"
    ) == []
    assert truth.query(
        "rc72_node_gate", mission_id=MISSION, node_type="N5_TEST_DATA"
    ) == []


def test_n5_dispatch_skips_exact_reuse_verified_requirements(
    tmp_path: Path, monkeypatch
):
    truth, _scopes, _completed, inventory, resolver, _resolution = _resolved_inventory(
        tmp_path, monkeypatch
    )
    reused_id = inventory["data_requirement_ids"][0]
    _bind_requirement(truth, resolver, reused_id, "reuse-one")
    resolution = resolver.resolve_all(release_batch_id=BATCH)
    assert resolution["reuse_verified_count"] == 1

    result = N5DataDiscoveryDispatchService(
        truth,
        release_id=RELEASE,
        source_commit=COMMIT,
    ).dispatch(release_batch_id=BATCH)

    assert result["status"] == "DISPATCHED"
    assert result["dispatch_count"] == inventory["data_requirement_count"] - 1
    assert reused_id not in result["data_requirement_ids"]
    receipts = truth.query(
        "rc72_n5_data_discovery_dispatch", release_batch_id=BATCH
    )
    assert all(row["data_requirement_id"] != reused_id for row in receipts)
    assert truth.query("rc72_data_lease") == []


def test_n5_dispatch_is_idempotent_without_duplicate_workitems(
    tmp_path: Path, monkeypatch
):
    truth, _scopes, _completed, inventory, _resolver, _resolution = _resolved_inventory(
        tmp_path, monkeypatch
    )
    service = N5DataDiscoveryDispatchService(
        truth,
        release_id=RELEASE,
        source_commit=COMMIT,
    )
    first = service.dispatch(release_batch_id=BATCH)
    second = service.dispatch(release_batch_id=BATCH)

    assert first["status"] == "DISPATCHED"
    assert second["status"] == "RESUMED"
    assert second["dispatch_ids"] == first["dispatch_ids"]
    assert second["workitem_ids"] == first["workitem_ids"]
    assert len(
        truth.query("rc72_n5_data_discovery_dispatch", release_batch_id=BATCH)
    ) == inventory["data_requirement_count"]
    for workitem_id in first["workitem_ids"]:
        assert len(truth.query("rc7_task", task_id=workitem_id)) == 1


def test_n5_dispatch_creates_no_dummy_worker_when_all_requirements_reuse_verified(
    tmp_path: Path, monkeypatch
):
    truth, _scopes, _completed, inventory, resolver, _resolution = _resolved_inventory(
        tmp_path, monkeypatch
    )
    for index, data_requirement_id in enumerate(inventory["data_requirement_ids"]):
        _bind_requirement(
            truth,
            resolver,
            data_requirement_id,
            "reuse-all-%03d" % index,
        )
    resolution = resolver.resolve_all(release_batch_id=BATCH)
    assert resolution["reuse_verified_count"] == inventory["data_requirement_count"]
    assert resolution["discovery_required_count"] == 0

    result = N5DataDiscoveryDispatchService(
        truth,
        release_id=RELEASE,
        source_commit=COMMIT,
    ).dispatch(release_batch_id=BATCH)

    assert result["status"] == "NO_DISCOVERY_REQUIRED"
    assert result["dispatch_count"] == 0
    assert result["dispatch_ids"] == []
    assert result["workitem_ids"] == []
    assert truth.query(
        "rc72_n5_data_discovery_dispatch", release_batch_id=BATCH
    ) == []
    assert truth.query(
        "rc7_task", mission_id=MISSION, node="TEST_DATA"
    ) == []
    assert truth.query("rc72_data_lease") == []
    n5 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N5_TEST_DATA"
    )[0]
    n6 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N6_EXECUTABLE_READINESS"
    )[0]
    assert n5["state"] == "RUNNING"
    assert n6["state"] == "NOT_STARTED"
