from copy import deepcopy

import pytest

from rc7_runtime.rc72_n6_completion import N6CompletionError, N6DeliveryGateService
from rc7_runtime.rc72_n6_executable_readiness import N6ExecutableReadinessCompiler

from rc72_n2_test_support import BATCH, COMMIT, MISSION, RELEASE, REQUIREMENTS
from test_rc72_n5_completion import _all_reused, _service as _n5_service
from test_rc72_n6_executable_readiness import NOW, _binding, _case, _data_ref


def _contract():
    case = deepcopy(_case())
    case.update(
        {
            "release_batch_id": BATCH,
            "mission_id": MISSION,
            "requirement_id": REQUIREMENTS[0],
        }
    )
    data_ref = deepcopy(_data_ref())
    data_ref.update(
        {
            "release_batch_id": BATCH,
            "mission_id": MISSION,
            "requirement_id": REQUIREMENTS[0],
            "case_id": case["case_id"],
        }
    )
    return N6ExecutableReadinessCompiler().compile(
        case,
        [data_ref],
        _binding(),
        now=NOW,
    )


def _ready_truth(tmp_path, monkeypatch):
    truth, _inventory, _resolver = _all_reused(tmp_path, monkeypatch)
    result = _n5_service(truth).complete(release_batch_id=BATCH)
    assert result["gate"]["decision"] == "PASS"
    assert result["gate"]["n6_state"] == "READY"
    return truth


def _service(truth):
    return N6DeliveryGateService(
        truth,
        release_id=RELEASE,
        source_commit=COMMIT,
    )


def test_n6_completion_persists_contract_gates_and_releases_n7(tmp_path, monkeypatch):
    truth = _ready_truth(tmp_path, monkeypatch)

    result = _service(truth).complete(
        release_batch_id=BATCH,
        contracts=[_contract()],
    )

    assert result["delivery"]["status"] == "DELIVERY_ADMITTED"
    assert result["delivery"]["contract_count"] == 1
    assert result["gate"]["status"] == "GATE_APPLIED"
    assert result["gate"]["decision"] == "PASS"
    assert result["gate"]["failed"] == []
    assert result["gate"]["n6_state"] == "PASS"
    assert result["gate"]["n7_state"] == "READY"

    contract_id = result["delivery"]["contract_ids"][0]
    stored = truth.query("rc72_n6_executable_contract", contract_id=contract_id)
    assert len(stored) == 1
    assert stored[0]["case_id"] == "case-limit-001"
    assert stored[0]["contract_sha256"] == _contract().contract_sha256
    assert "data_lease_id" not in stored[0]
    assert truth.query("rc72_data_lease") == []

    delivery = truth.query(
        "rc72_node_delivery", delivery_id=result["delivery"]["delivery_id"]
    )[0]
    assert delivery["artifact_refs"] == [contract_id]
    assert delivery["sufficiency_score"] == 1.0
    assert delivery["known_gaps"] == []

    gate = truth.query("rc72_node_gate", gate_id=result["gate"]["gate_id"])[0]
    assert gate["reviewer_worker_id"] == "rc72-runtime-n6-gate"
    assert gate["reviewer_session_id"] == "runtime://rc72/n6-gate/v1"
    assert gate["decision"] == "PASS"
    assert "N6_NO_PREMATURE_DATA_LEASE" in gate["passed"]


def test_n6_completion_replay_is_idempotent(tmp_path, monkeypatch):
    truth = _ready_truth(tmp_path, monkeypatch)
    service = _service(truth)
    contract = _contract()

    first = service.complete(release_batch_id=BATCH, contracts=[contract])
    second = service.complete(release_batch_id=BATCH, contracts=[contract])

    assert first["gate"]["decision"] == "PASS"
    assert second["delivery"]["status"] == "RESUMED"
    assert second["gate"]["status"] == "RESUMED"
    assert second["gate"]["decision"] == "PASS"
    assert second["gate"]["n6_state"] == "PASS"
    assert second["gate"]["n7_state"] == "READY"
    assert len(truth.query("rc72_n6_executable_contract", mission_id=MISSION)) == 1
    assert len(
        truth.query("rc72_node_delivery", mission_id=MISSION, node_type="N6_EXECUTABLE_READINESS")
    ) == 1
    assert len(
        truth.query("rc72_node_gate", mission_id=MISSION, node_type="N6_EXECUTABLE_READINESS")
    ) == 1
    assert truth.query("rc72_data_lease") == []


def test_n6_gate_detects_r1_contract_tamper_and_keeps_n7_locked(tmp_path, monkeypatch):
    truth = _ready_truth(tmp_path, monkeypatch)
    service = _service(truth)
    admitted = service.admit_delivery(
        release_batch_id=BATCH,
        contracts=[_contract()],
    )
    assert admitted["node_state"] == "REVIEW_PENDING"

    contract_id = admitted["contract_ids"][0]
    row = truth.query("rc72_n6_executable_contract", contract_id=contract_id)[0]
    payload = dict(row)
    payload.pop("artifact_type", None)
    payload["artifact_version"] = int(row.get("artifact_version") or 1) + 1
    payload["endpoint"] = dict(payload["endpoint"])
    payload["endpoint"]["url"] = "http://tampered.invalid/api"
    truth.append_atomic("rc72.n6.executable_contract_compiled", payload)

    result = service.apply_gate(release_batch_id=BATCH)

    assert result["decision"] == "NEEDS_REVISION"
    assert "N6_EXECUTABLE_CONTRACT_DIGEST_VALID" in result["failed"]
    assert result["n6_state"] == "NEEDS_REVISION"
    assert result["n7_state"] == "NOT_STARTED"
    assert truth.query("rc72_data_lease") == []


def test_n6_refuses_to_run_before_n5_pass(tmp_path, monkeypatch):
    truth, _inventory, _resolver = _all_reused(tmp_path, monkeypatch)

    with pytest.raises(N6CompletionError, match="PARENT_N5_NOT_PASS"):
        _service(truth).complete(
            release_batch_id=BATCH,
            contracts=[_contract()],
        )

    assert truth.query("rc72_n6_executable_contract") == []
    assert truth.query(
        "rc72_node_delivery", mission_id=MISSION, node_type="N6_EXECUTABLE_READINESS"
    ) == []
    assert truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N7_EXECUTION"
    )[0]["state"] == "NOT_STARTED"


def test_n6_rejects_contract_mission_lineage_mismatch(tmp_path, monkeypatch):
    truth = _ready_truth(tmp_path, monkeypatch)
    bad = _contract()
    object.__setattr__(bad, "mission_id", "MISSION-WRONG")

    with pytest.raises(N6CompletionError, match="CONTRACT_MISSION_MISMATCH"):
        _service(truth).complete(release_batch_id=BATCH, contracts=[bad])

    assert truth.query("rc72_n6_executable_contract") == []
    assert truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N7_EXECUTION"
    )[0]["state"] == "NOT_STARTED"
