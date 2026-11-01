from pathlib import Path

import pytest

from rc7_runtime.rc72_n5_completion import (
    N5CompletionError,
    N5DeliveryGateService,
)

from rc72_n2_test_support import BATCH, COMMIT, MISSION, RELEASE
from test_rc72_n5_data_discovery_dispatch import (
    _bind_requirement,
    _resolved_inventory,
)
from test_rc72_n5_data_resolution import _bind, _evidence, _register_resource


def _service(truth):
    return N5DeliveryGateService(
        truth,
        release_id=RELEASE,
        source_commit=COMMIT,
    )


def _all_reused(tmp_path: Path, monkeypatch):
    truth, _scopes, _completed, inventory, resolver, _resolution = _resolved_inventory(
        tmp_path, monkeypatch
    )
    for index, data_requirement_id in enumerate(inventory["data_requirement_ids"]):
        _bind_requirement(
            truth,
            resolver,
            data_requirement_id,
            "completion-reuse-%03d" % index,
        )
    return truth, inventory, resolver


def test_n5_completion_releases_n6_only_after_full_verified_binding_denominator(
    tmp_path: Path, monkeypatch
):
    truth, inventory, _resolver = _all_reused(tmp_path, monkeypatch)

    result = _service(truth).complete(release_batch_id=BATCH)

    assert result["delivery"]["status"] == "DELIVERY_ADMITTED"
    assert result["delivery"]["data_requirement_count"] == inventory["data_requirement_count"]
    assert result["delivery"]["verified_binding_count"] == inventory["data_requirement_count"]
    assert result["gate"]["status"] == "GATE_APPLIED"
    assert result["gate"]["decision"] == "PASS"
    assert result["gate"]["failed"] == []
    assert result["gate"]["n5_state"] == "PASS"
    assert result["gate"]["n6_state"] == "READY"

    delivery = truth.query(
        "rc72_node_delivery", delivery_id=result["delivery"]["delivery_id"]
    )[0]
    bindings = truth.query("rc72_n5_data_binding", release_batch_id=BATCH)
    assert set(delivery["artifact_refs"]) == {row["binding_id"] for row in bindings}
    assert len(delivery["artifact_refs"]) == inventory["data_requirement_count"]
    assert delivery["known_gaps"] == []
    assert delivery["sufficiency_score"] == 1.0
    assert delivery["evidence_refs"]

    gate = truth.query("rc72_node_gate", gate_id=result["gate"]["gate_id"])[0]
    assert gate["decision"] == "PASS"
    assert gate["failed"] == []
    assert set(gate["evidence_refs"]) == set(delivery["evidence_refs"])

    # N5 completion proves exact verified bindings only. Consumer-specific
    # reservation begins only after N6 creates a concrete Attempt binding.
    assert truth.query("rc72_data_lease") == []
    assert truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N5_TEST_DATA"
    )[0]["state"] == "PASS"
    assert truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N6_EXECUTABLE_READINESS"
    )[0]["state"] == "READY"


def test_n5_completion_replay_is_idempotent_and_does_not_create_data_leases(
    tmp_path: Path, monkeypatch
):
    truth, inventory, _resolver = _all_reused(tmp_path, monkeypatch)
    service = _service(truth)
    first = service.complete(release_batch_id=BATCH)
    second = service.complete(release_batch_id=BATCH)

    assert first["gate"]["decision"] == "PASS"
    assert second["delivery"]["status"] == "RESUMED"
    assert second["gate"]["status"] == "RESUMED"
    assert second["gate"]["decision"] == "PASS"
    assert second["gate"]["n5_state"] == "PASS"
    assert second["gate"]["n6_state"] == "READY"
    assert len(
        truth.query("rc72_node_delivery", mission_id=MISSION, node_type="N5_TEST_DATA")
    ) == 1
    assert len(
        truth.query("rc72_node_gate", mission_id=MISSION, node_type="N5_TEST_DATA")
    ) == 1
    assert len(
        truth.query("rc72_n5_data_binding", release_batch_id=BATCH)
    ) == inventory["data_requirement_count"]
    assert truth.query("rc72_data_lease") == []


def test_n5_completion_refuses_partial_discovery_without_fabricating_delivery(
    tmp_path: Path, monkeypatch
):
    truth, _scopes, _completed, inventory, _resolver, resolution = _resolved_inventory(
        tmp_path, monkeypatch
    )
    assert resolution["discovery_required_count"] == inventory["data_requirement_count"]

    with pytest.raises(
        N5CompletionError,
        match="FINALIZATION_INCOMPLETE",
    ):
        _service(truth).complete(release_batch_id=BATCH)

    assert truth.query(
        "rc72_node_delivery", mission_id=MISSION, node_type="N5_TEST_DATA"
    ) == []
    assert truth.query(
        "rc72_node_gate", mission_id=MISSION, node_type="N5_TEST_DATA"
    ) == []
    assert truth.query("rc72_data_lease") == []
    assert truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N5_TEST_DATA"
    )[0]["state"] == "RUNNING"
    assert truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N6_EXECUTABLE_READINESS"
    )[0]["state"] == "NOT_STARTED"


def test_n5_completion_fails_closed_on_ambiguous_verified_bindings(
    tmp_path: Path, monkeypatch
):
    truth, _scopes, _completed, inventory, resolver, _resolution = _resolved_inventory(
        tmp_path, monkeypatch
    )
    first_id = inventory["data_requirement_ids"][0]
    first_requirement = truth.query(
        "rc72_n5_data_requirement", data_requirement_id=first_id
    )[0]
    for suffix in ("ambiguous-a", "ambiguous-b"):
        data_ref = "data://fat1/pcc/config/%s" % suffix
        evidence_id = "EVD-N5-COMPLETION-%s" % suffix
        _register_resource(truth, data_ref=data_ref, verified=True, mutable=False)
        _evidence(truth, evidence_id, [first_id, data_ref])
        _bind(resolver, first_requirement, data_ref, evidence_id)
    for index, data_requirement_id in enumerate(inventory["data_requirement_ids"][1:]):
        _bind_requirement(
            truth,
            resolver,
            data_requirement_id,
            "completion-other-%03d" % index,
        )

    with pytest.raises(
        N5CompletionError,
        match="RESOLUTION_INVALID:.*AMBIGUOUS_VERIFIED_BINDINGS",
    ):
        _service(truth).complete(release_batch_id=BATCH)

    assert truth.query(
        "rc72_node_delivery", mission_id=MISSION, node_type="N5_TEST_DATA"
    ) == []
    assert truth.query(
        "rc72_node_gate", mission_id=MISSION, node_type="N5_TEST_DATA"
    ) == []
    assert truth.query("rc72_data_lease") == []
    assert truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N6_EXECUTABLE_READINESS"
    )[0]["state"] == "NOT_STARTED"


def test_n5_gate_fails_revision_if_verified_resource_truth_changes_after_delivery(
    tmp_path: Path, monkeypatch
):
    truth, _inventory, _resolver = _all_reused(tmp_path, monkeypatch)
    service = _service(truth)
    delivery_result = service.admit_delivery(release_batch_id=BATCH)
    assert delivery_result["node_state"] == "REVIEW_PENDING"

    delivery = truth.query(
        "rc72_node_delivery", delivery_id=delivery_result["delivery_id"]
    )[0]
    binding = truth.query(
        "rc72_n5_data_binding", binding_id=delivery["artifact_refs"][0]
    )[0]
    resource = truth.query("rc72_data_resource", data_ref=binding["data_ref"])[0]
    payload = dict(resource)
    payload.pop("artifact_type", None)
    payload["artifact_version"] = int(resource.get("artifact_version") or 1) + 1
    payload["verified"] = False
    truth.append_atomic("RC72_DATA_RESOURCE_UPSERTED", payload)

    result = service.apply_gate(release_batch_id=BATCH)
    assert result["decision"] == "NEEDS_REVISION"
    assert "N5_VERIFIED_DATA_RESOURCE" in result["failed"]
    assert result["n5_state"] == "NEEDS_REVISION"
    assert result["n6_state"] == "NOT_STARTED"
    assert truth.query("rc72_data_lease") == []


def test_n5_mutable_binding_can_pass_gate_without_premature_exclusive_lease(
    tmp_path: Path, monkeypatch
):
    truth, _scopes, _completed, inventory, resolver, _resolution = _resolved_inventory(
        tmp_path, monkeypatch
    )
    first_id = inventory["data_requirement_ids"][0]
    first_requirement = truth.query(
        "rc72_n5_data_requirement", data_requirement_id=first_id
    )[0]
    data_ref = "data://fat1/pcc/config/mutable-ready"
    evidence_id = "EVD-N5-COMPLETION-MUTABLE"
    _register_resource(truth, data_ref=data_ref, verified=True, mutable=True)
    _evidence(truth, evidence_id, [first_id, data_ref])
    mutable_binding = _bind(resolver, first_requirement, data_ref, evidence_id)
    assert mutable_binding["reservation_mode"] == "EXCLUSIVE_WRITE"
    for index, data_requirement_id in enumerate(inventory["data_requirement_ids"][1:]):
        _bind_requirement(
            truth,
            resolver,
            data_requirement_id,
            "completion-read-%03d" % index,
        )

    result = _service(truth).complete(release_batch_id=BATCH)
    assert result["gate"]["decision"] == "PASS"
    assert "N5_RESERVATION_MODE_CONSISTENT" in result["gate"]["passed"]
    assert "N5_NO_PREMATURE_DATA_LEASE_DEPENDENCY" in result["gate"]["passed"]
    assert truth.query("rc72_data_lease") == []
    assert truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N6_EXECUTABLE_READINESS"
    )[0]["state"] == "READY"
