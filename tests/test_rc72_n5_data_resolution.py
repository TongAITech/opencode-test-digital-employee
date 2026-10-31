from pathlib import Path

import pytest

from rc7_runtime.models import Evidence
from rc7_runtime.rc72_data_resources import DataLeaseManager
from rc7_runtime.rc72_n5_data_inventory import N5DataRequirementInventoryService
from rc7_runtime.rc72_n5_data_resolution import (
    N5DataResolutionError,
    N5DataResolutionService,
)
from rc7_runtime.truth_overlay import append_entity

from rc72_n2_test_support import BATCH, COMMIT, MISSION, RELEASE
from test_rc72_n5_data_inventory import _n5_ready


def _inventory(tmp_path: Path, monkeypatch):
    truth, scopes, completed = _n5_ready(tmp_path, monkeypatch)
    inventory = N5DataRequirementInventoryService(
        truth, source_commit=COMMIT
    ).materialize(release_batch_id=BATCH)
    assert inventory["node_state"] == "RUNNING"
    return truth, scopes, completed, inventory


def _evidence(truth, evidence_id: str, subject_refs):
    append_entity(
        truth,
        Evidence(
            evidence_id=evidence_id,
            mission_id=MISSION,
            kind="N5_DATA_VERIFICATION_PROOF",
            source_ref="tdsql://fat1/pcc",
            content_ref="query-proof://%s" % evidence_id,
            subject_refs=list(subject_refs),
        ),
        release_id=RELEASE,
    )


def _register_resource(
    truth,
    *,
    data_ref: str,
    verified: bool = True,
    mutable: bool = False,
):
    DataLeaseManager(truth, release_id=RELEASE).register_data_ref(
        data_ref=data_ref,
        data_domain="pcc-config",
        verified=verified,
        mutable=mutable,
        metadata_ref="db://fat1/pcc/%s" % data_ref.rsplit("/", 1)[-1],
    )


def _bind(service, requirement, data_ref: str, evidence_id: str):
    return service.bind_verified(
        data_requirement_id=requirement["data_requirement_id"],
        data_ref=data_ref,
        strategy="DISCOVER_EXISTING",
        source_or_constructor="tdsql://fat1/pcc/select-by-business-key",
        verification="row exists and satisfies exact Case precondition",
        verification_evidence_refs=[evidence_id],
        precondition_refs=["precondition://%s" % requirement["case_id"]],
        validity_window="mission-attempt-window",
        cleanup_policy="release reservation; no mutation cleanup required",
    )


def test_n5_resolver_never_guesses_data_ref_when_no_exact_binding_exists(
    tmp_path: Path, monkeypatch
):
    truth, _scopes, _completed, inventory = _inventory(tmp_path, monkeypatch)
    result = N5DataResolutionService(
        truth,
        release_id=RELEASE,
        source_commit=COMMIT,
    ).resolve_all(release_batch_id=BATCH)

    assert result["status"] == "RESOLVED_DETERMINISTICALLY"
    assert result["plan_count"] == inventory["data_requirement_count"]
    assert result["reuse_verified_count"] == 0
    assert result["discovery_required_count"] == inventory["data_requirement_count"]
    assert result["n5_state"] == "RUNNING"
    assert result["n6_state"] == "NOT_STARTED"
    assert all(row["status"] == "DISCOVERY_REQUIRED" for row in result["plans"])
    assert all(row["binding_id"] is None for row in result["plans"])
    assert all(row["data_ref"] is None for row in result["plans"])

    plans = truth.query("rc72_n5_data_resolution_plan", release_batch_id=BATCH)
    assert len(plans) == inventory["data_requirement_count"]
    assert {row["status"] for row in plans} == {"DISCOVERY_REQUIRED"}
    assert truth.query("rc72_n5_data_binding", release_batch_id=BATCH) == []
    assert truth.query("rc72_data_lease") == []
    assert truth.query(
        "rc72_node_delivery", mission_id=MISSION, node_type="N5_TEST_DATA"
    ) == []


def test_n5_resolver_reuses_only_exact_verified_evidence_backed_binding(
    tmp_path: Path, monkeypatch
):
    truth, _scopes, _completed, inventory = _inventory(tmp_path, monkeypatch)
    requirement = truth.query(
        "rc72_n5_data_requirement",
        data_requirement_id=inventory["data_requirement_ids"][0],
    )[0]
    data_ref = "data://fat1/pcc/config/verified-001"
    evidence_id = "EVD-N5-DATA-BINDING-001"
    _register_resource(truth, data_ref=data_ref, verified=True, mutable=False)
    _evidence(truth, evidence_id, [requirement["data_requirement_id"], data_ref])
    service = N5DataResolutionService(
        truth,
        release_id=RELEASE,
        source_commit=COMMIT,
    )
    bound = _bind(service, requirement, data_ref, evidence_id)
    assert bound["status"] == "BOUND_VERIFIED"
    assert bound["reservation_mode"] == "SHARED_READ"

    result = service.resolve_all(release_batch_id=BATCH)
    assert result["reuse_verified_count"] == 1
    assert result["discovery_required_count"] == inventory["data_requirement_count"] - 1
    reused = [row for row in result["plans"] if row["status"] == "REUSE_VERIFIED"]
    assert len(reused) == 1
    assert reused[0]["data_requirement_id"] == requirement["data_requirement_id"]
    assert reused[0]["binding_id"] == bound["binding_id"]
    assert reused[0]["data_ref"] == data_ref

    binding = truth.query("rc72_n5_data_binding", binding_id=bound["binding_id"])[0]
    assert binding["source_case_sha256"] == requirement["source_case_sha256"]
    assert binding["verification_evidence_refs"] == [evidence_id]
    assert binding["status"] == "VERIFIED"
    assert "reserved" not in binding
    assert "data_lease_id" not in binding
    assert truth.query("rc72_data_lease") == []
    n6 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N6_EXECUTABLE_READINESS"
    )[0]
    assert n6["state"] == "NOT_STARTED"


def test_n5_verified_binding_for_mutable_data_requires_future_exclusive_reservation(
    tmp_path: Path, monkeypatch
):
    truth, _scopes, _completed, inventory = _inventory(tmp_path, monkeypatch)
    requirement = truth.query(
        "rc72_n5_data_requirement",
        data_requirement_id=inventory["data_requirement_ids"][0],
    )[0]
    data_ref = "data://fat1/pcc/config/mutable-001"
    evidence_id = "EVD-N5-DATA-MUTABLE-001"
    _register_resource(truth, data_ref=data_ref, verified=True, mutable=True)
    _evidence(truth, evidence_id, [requirement["data_requirement_id"], data_ref])
    service = N5DataResolutionService(
        truth,
        release_id=RELEASE,
        source_commit=COMMIT,
    )
    bound = _bind(service, requirement, data_ref, evidence_id)

    assert bound["reservation_mode"] == "EXCLUSIVE_WRITE"
    binding = truth.query("rc72_n5_data_binding", binding_id=bound["binding_id"])[0]
    assert binding["reservation_mode"] == "EXCLUSIVE_WRITE"
    assert truth.query("rc72_data_lease") == []
    result = service.resolve_all(release_batch_id=BATCH)
    reused = [row for row in result["plans"] if row["status"] == "REUSE_VERIFIED"]
    assert len(reused) == 1
    assert reused[0]["data_ref"] == data_ref


def test_n5_resolver_fails_closed_when_multiple_verified_bindings_exist(
    tmp_path: Path, monkeypatch
):
    truth, _scopes, _completed, inventory = _inventory(tmp_path, monkeypatch)
    requirement = truth.query(
        "rc72_n5_data_requirement",
        data_requirement_id=inventory["data_requirement_ids"][0],
    )[0]
    service = N5DataResolutionService(
        truth,
        release_id=RELEASE,
        source_commit=COMMIT,
    )
    for index in (1, 2):
        data_ref = "data://fat1/pcc/config/ambiguous-%03d" % index
        evidence_id = "EVD-N5-DATA-AMBIGUOUS-%03d" % index
        _register_resource(truth, data_ref=data_ref, verified=True, mutable=False)
        _evidence(truth, evidence_id, [requirement["data_requirement_id"], data_ref])
        _bind(service, requirement, data_ref, evidence_id)

    with pytest.raises(
        N5DataResolutionError,
        match="AMBIGUOUS_VERIFIED_BINDINGS",
    ):
        service.resolve_all(release_batch_id=BATCH)

    assert truth.query("rc72_data_lease") == []
    n6 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N6_EXECUTABLE_READINESS"
    )[0]
    assert n6["state"] == "NOT_STARTED"


def test_n5_cannot_bind_unverified_data_resource(
    tmp_path: Path, monkeypatch
):
    truth, _scopes, _completed, inventory = _inventory(tmp_path, monkeypatch)
    requirement = truth.query(
        "rc72_n5_data_requirement",
        data_requirement_id=inventory["data_requirement_ids"][0],
    )[0]
    data_ref = "data://fat1/pcc/config/unverified-001"
    evidence_id = "EVD-N5-DATA-UNVERIFIED-001"
    _register_resource(truth, data_ref=data_ref, verified=False, mutable=False)
    _evidence(truth, evidence_id, [requirement["data_requirement_id"], data_ref])

    with pytest.raises(
        N5DataResolutionError,
        match="DATA_REF_NOT_VERIFIED",
    ):
        _bind(
            N5DataResolutionService(
                truth,
                release_id=RELEASE,
                source_commit=COMMIT,
            ),
            requirement,
            data_ref,
            evidence_id,
        )

    assert truth.query("rc72_n5_data_binding", release_batch_id=BATCH) == []
    assert truth.query("rc72_data_lease") == []
