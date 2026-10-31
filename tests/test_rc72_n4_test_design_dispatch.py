from pathlib import Path

import pytest

from rc7_runtime.rc72_n3_completion import N3DeliveryGateService
from rc7_runtime.rc72_n4_parent_truth import N4ParentTruthService
from rc7_runtime.rc72_n4_test_design_dispatch import (
    N4TestDesignDispatchError,
    N4TestDesignDispatchService,
)

from rc72_n2_test_support import BATCH, COMMIT, MISSION
from test_rc72_n3_completion import _review_gate_ready


def _n4_ready(tmp_path: Path, monkeypatch):
    truth, _row, _promoted, _reviewed = _review_gate_ready(tmp_path, monkeypatch)
    n3 = N3DeliveryGateService(truth, source_commit=COMMIT).complete(
        release_batch_id=BATCH
    )
    assert n3["gate"]["decision"] == "PASS"
    assert n3["gate"]["n4_state"] == "READY"
    snapshot = N4ParentTruthService(truth).resolve(release_batch_id=BATCH)
    return truth, snapshot


def test_n4_dispatch_is_forbidden_before_formal_n3_pass(tmp_path: Path, monkeypatch):
    truth, _row, _promoted, _reviewed = _review_gate_ready(tmp_path, monkeypatch)
    with pytest.raises(Exception, match="N4_NOT_ADMITTED"):
        N4TestDesignDispatchService(truth, source_commit=COMMIT).dispatch(
            release_batch_id=BATCH
        )
    assert truth.query("rc72_n4_test_design_dispatch", release_batch_id=BATCH) == []
    assert truth.query(
        "rc7_task", mission_id=MISSION, node="TEST_DESIGN"
    ) == []


def test_n4_dispatch_fans_out_exact_requirement_sst_scopes_and_locks_n5(
    tmp_path: Path, monkeypatch
):
    truth, snapshot = _n4_ready(tmp_path, monkeypatch)
    result = N4TestDesignDispatchService(
        truth, source_commit=COMMIT
    ).dispatch(release_batch_id=BATCH)

    expected_scopes = sorted(
        (requirement_id, sst_id)
        for requirement_id, sst_ids in snapshot["requirement_sst_map"].items()
        for sst_id in sst_ids
    )
    actual_scopes = sorted(
        (row["requirement_id"], row["sst_id"])
        for row in result["design_scopes"]
    )
    assert actual_scopes == expected_scopes
    assert len(result["workitem_ids"]) == len(expected_scopes)
    assert len(result["workitem_ids"]) == len(set(result["workitem_ids"]))
    assert len(result["dispatch_ids"]) == len(expected_scopes)
    assert result["node_state"] == "RUNNING"
    assert result["execution_substrate"] == "DSH_AGENT_TEAMS"
    assert result["worker_policy"] == "FRESH_SESSION_REQUIRED"
    assert result["parent_snapshot_id"] == snapshot["snapshot_id"]

    receipts = truth.query("rc72_n4_test_design_dispatch", release_batch_id=BATCH)
    assert len(receipts) == len(expected_scopes)
    by_scope = {(row["requirement_id"], row["sst_id"]): row for row in receipts}
    assert set(by_scope) == set(expected_scopes)

    for scope in expected_scopes:
        requirement_id, _sst_id = scope
        receipt = by_scope[scope]
        task = truth.query("rc7_task", task_id=receipt["workitem_id"])[0]
        assert task["state"] == "READY"
        assert task["node"] == "TEST_DESIGN"
        assert task["task_type"] == "RC72_NODE_WORK"
        assert set(task["input_artifact_refs"]) == set(receipt["parent_artifact_refs"])
        assert set(task["dependency_task_ids"]) == set(receipt["dependency_workitem_refs"])
        assert len(task["input_artifact_refs"]) >= 2
        assert task["required_capabilities"] == ["test_design", "codegraph"]
        assert "TBD" in " ".join(task["acceptance_criteria"])
        assert "L1-L7" in " ".join(task["acceptance_criteria"])

        parent_types = {
            truth.query("rc7_artifact", artifact_id=artifact_id)[0]["artifact_type_name"]
            for artifact_id in receipt["parent_artifact_refs"]
        }
        assert "REQUIREMENT_ANALYSIS_OUTPUT" in parent_types
        assert "CODE_ANALYSIS_CANDIDATE" in parent_types
        for dependency_id in receipt["dependency_workitem_refs"]:
            dependency = truth.query("rc7_task", task_id=dependency_id)[0]
            assert dependency["state"] == "PASS"
        assert receipt["parent_obligation_source_refs"]
        assert all(
            ref.rsplit(":", 1)[-1] in set(receipt["parent_artifact_refs"])
            for ref in receipt["parent_obligation_source_refs"]
        )
        assert "worker_instance_id" not in receipt
        assert "dsh_session_id" not in receipt
        assert "test_cases" not in receipt
        assert "obligations" not in receipt

        requirement_artifacts = [
            artifact_id
            for artifact_id in receipt["parent_artifact_refs"]
            if truth.query("rc7_artifact", artifact_id=artifact_id)[0]["artifact_type_name"]
            == "REQUIREMENT_ANALYSIS_OUTPUT"
        ]
        assert len(requirement_artifacts) == 1
        payload_path = truth.query(
            "rc7_artifact", artifact_id=requirement_artifacts[0]
        )[0]["content_ref"]
        assert payload_path.startswith("file://")
        # The exact Requirement identity is also independently anchored in the
        # dispatch receipt, so multiple SSTs cannot collapse into one batch task.
        assert receipt["requirement_id"] == requirement_id

    n4 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N4_TEST_DESIGN"
    )[0]
    n5 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N5_TEST_DATA"
    )[0]
    assert n4["state"] == "RUNNING"
    assert n5["state"] == "NOT_STARTED"
    assert truth.query(
        "rc72_node_delivery", mission_id=MISSION, node_type="N4_TEST_DESIGN"
    ) == []
    assert truth.query(
        "rc72_node_gate", mission_id=MISSION, node_type="N4_TEST_DESIGN"
    ) == []


def test_n4_dispatch_replay_is_idempotent_and_cannot_duplicate_design_scope(
    tmp_path: Path, monkeypatch
):
    truth, snapshot = _n4_ready(tmp_path, monkeypatch)
    service = N4TestDesignDispatchService(truth, source_commit=COMMIT)
    first = service.dispatch(release_batch_id=BATCH)
    second = service.dispatch(release_batch_id=BATCH)

    assert first["status"] == "DISPATCHED"
    assert second["status"] == "RESUMED"
    assert second["dispatch_ids"] == first["dispatch_ids"]
    assert second["workitem_ids"] == first["workitem_ids"]
    assert second["design_scopes"] == first["design_scopes"]
    assert second["parent_snapshot_id"] == snapshot["snapshot_id"]
    assert len(
        truth.query("rc72_n4_test_design_dispatch", release_batch_id=BATCH)
    ) == len(first["dispatch_ids"])
    assert len(
        truth.query("rc7_task", mission_id=MISSION, node="TEST_DESIGN")
    ) == len(first["workitem_ids"])
