from pathlib import Path

import pytest

from rc7_runtime.rc72_n2_completion import N2DeliveryGateService
from rc7_runtime.rc72_n3_source_target_dispatch import (
    N3SourceTargetDispatchError,
    N3SourceTargetDispatchService,
    validate_rc72_n3_source_target_dispatch,
)

from rc72_n2_test_support import BATCH, COMMIT, MISSION
from test_rc72_n2_completion import _seed_reviewed_requirements


def _n2_pass(tmp_path: Path):
    truth, _ = _seed_reviewed_requirements(tmp_path)
    completed = N2DeliveryGateService(truth, source_commit=COMMIT).complete(
        release_batch_id=BATCH
    )
    assert completed["gate"]["decision"] == "PASS"
    assert completed["gate"]["n3_state"] == "READY"
    return truth


def test_n3_starts_with_per_application_source_target_discovery_not_code_analysis(tmp_path: Path):
    truth = _n2_pass(tmp_path)

    result = N3SourceTargetDispatchService(
        truth, source_commit=COMMIT
    ).dispatch(release_batch_id=BATCH)

    assert result["status"] == "DISPATCHED"
    assert result["node_state"] == "RUNNING"
    assert result["n4_state"] == "NOT_STARTED"
    assert len(result["dispatches"]) == 1
    dispatch = result["dispatches"][0]
    assert dispatch["application_id"] == "BLOAN"
    assert dispatch["stage"] == "SOURCE_TARGET_DISCOVERY"
    assert dispatch["required_capabilities"] == ["source_target_discovery"]
    assert dispatch["source_n1_artifact_refs"]
    assert dispatch["source_n1_evidence_refs"]
    assert dispatch["source_n2_artifact_refs"]
    assert dispatch["source_n2_evidence_refs"]
    for forbidden in (
        "repository", "repository_ref", "repo", "source_revision",
        "base_revision", "head_revision", "target_id",
    ):
        assert forbidden not in dispatch

    task = truth.query("rc7_task", task_id=dispatch["workitem_id"])[0]
    assert task["node"] == "SOURCE_TARGET_DISCOVERY"
    assert task["state"] == "READY"
    assert task["required_capabilities"] == ["source_target_discovery"]
    assert set(dispatch["source_n1_artifact_refs"]).issubset(
        set(task["input_artifact_refs"])
    )
    assert set(dispatch["source_n2_artifact_refs"]).issubset(
        set(task["input_artifact_refs"])
    )

    n3 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N3_CODE_ANALYSIS"
    )[0]
    n4 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N4_TEST_DESIGN"
    )[0]
    assert n3["state"] == "RUNNING"
    assert n4["state"] == "NOT_STARTED"
    assert truth.query("rc7_task", mission_id=MISSION, node="CODE_ANALYSIS") == []


def test_n3_source_dispatch_is_idempotent_and_does_not_mint_repo_truth(tmp_path: Path):
    truth = _n2_pass(tmp_path)
    service = N3SourceTargetDispatchService(truth, source_commit=COMMIT)

    first = service.dispatch(release_batch_id=BATCH)
    second = service.dispatch(release_batch_id=BATCH)

    assert first["status"] == "DISPATCHED"
    assert second["status"] == "RESUMED"
    assert first["dispatches"] == second["dispatches"]
    assert len(truth.query("rc72_n3_source_target_dispatch", release_batch_id=BATCH)) == 1
    assert len(truth.query("rc7_task", mission_id=MISSION, node="SOURCE_TARGET_DISCOVERY")) == 1


def test_n3_source_dispatch_contract_rejects_coordinator_invented_repository_or_revision(tmp_path: Path):
    truth = _n2_pass(tmp_path)
    result = N3SourceTargetDispatchService(
        truth, source_commit=COMMIT
    ).dispatch(release_batch_id=BATCH)
    row = truth.query(
        "rc72_n3_source_target_dispatch",
        dispatch_id=result["dispatches"][0]["dispatch_id"],
    )[0]

    tampered = dict(row)
    tampered["repository_ref"] = "guessed://cfg-service"
    with pytest.raises(Exception, match="PREMATURE_SOURCE_CLAIM_FORBIDDEN:repository_ref"):
        validate_rc72_n3_source_target_dispatch(tampered)

    tampered = dict(row)
    tampered["head_revision"] = "deadbeef"
    with pytest.raises(Exception, match="PREMATURE_SOURCE_CLAIM_FORBIDDEN:head_revision"):
        validate_rc72_n3_source_target_dispatch(tampered)


def test_n3_source_dispatch_cannot_start_when_n2_needs_revision(tmp_path: Path):
    truth, _ = _seed_reviewed_requirements(
        tmp_path, repair_requirement="STBB19-320"
    )
    completed = N2DeliveryGateService(truth, source_commit=COMMIT).complete(
        release_batch_id=BATCH
    )
    assert completed["gate"]["decision"] == "NEEDS_REVISION"

    with pytest.raises(N3SourceTargetDispatchError, match="N3_STATE_INVALID"):
        N3SourceTargetDispatchService(
            truth, source_commit=COMMIT
        ).dispatch(release_batch_id=BATCH)

    assert truth.query("rc72_n3_source_target_dispatch", release_batch_id=BATCH) == []
    assert truth.query("rc7_task", mission_id=MISSION, node="SOURCE_TARGET_DISCOVERY") == []
