from copy import deepcopy

import pytest

from rc7_runtime.rc72_n1_strict_reality_gate import (
    N1StrictRealityGateError,
    N1StrictRealityGateService,
)

from test_rc72_n1_completion import (
    BATCH,
    COMMIT,
    MISSION,
    NODE,
    NODE2,
    _good_candidate,
    _handoff,
    _seed,
    _truth,
)
from test_rc72_n1_executable_binding import BINDING_KEY, _binding


def _candidate_with_binding(binding=None):
    candidate = deepcopy(_good_candidate())
    candidate["facts"]["executable_bindings"] = [
        deepcopy(_binding() if binding is None else binding)
    ]
    return candidate


def _prepare(tmp_path, candidate):
    truth = _truth(tmp_path)
    _seed(truth)
    _handoff(tmp_path, truth, candidate)
    return truth


def test_strict_n1_gate_passes_only_after_runtime_binding_pre_admission(tmp_path):
    truth = _prepare(tmp_path, _candidate_with_binding())

    result = N1StrictRealityGateService(
        truth, source_commit=COMMIT
    ).complete(release_batch_id=BATCH)

    assert result["gate"]["decision"] == "PASS"
    assert result["gate"]["n1_state"] == "PASS"
    assert result["gate"]["n2_state"] == "READY"
    assert result["binding_keys"] == [BINDING_KEY]
    assert len(result["executable_bindings"]) == 1
    row = result["executable_bindings"][0]
    assert row["binding_key"] == BINDING_KEY
    assert row["schema_version"] == "rc7.2-n1-executable-binding-v2"
    assert truth.query("rc72_n1_executable_binding", binding_id=row["binding_id"])


def test_strict_n1_gate_missing_bindings_fails_before_delivery_or_forward(tmp_path):
    truth = _prepare(tmp_path, deepcopy(_good_candidate()))

    with pytest.raises(
        N1StrictRealityGateError,
        match="EXECUTABLE_BINDINGS_REQUIRED",
    ):
        N1StrictRealityGateService(
            truth, source_commit=COMMIT
        ).complete(release_batch_id=BATCH)

    assert truth.query("rc72_node_delivery", mission_id=MISSION) == []
    assert truth.query("rc72_node_gate", mission_id=MISSION) == []
    assert truth.query("rc72_n1_executable_binding") == []
    assert truth.query("rc72_mission_node", mission_node_id=NODE)[0]["state"] == "RUNNING"
    assert truth.query("rc72_mission_node", mission_node_id=NODE2)[0]["state"] == "NOT_STARTED"


@pytest.mark.parametrize(
    "mutator",
    [
        lambda binding: binding["endpoint"].update({"verified": False}),
        lambda binding: binding["endpoint"].update({"url": "UNKNOWN"}),
        lambda binding: binding.update({"request_schema": "schema://must-stay-in-n3-n4"}),
        lambda binding: binding["tool_route"].update({"verified": False}),
        lambda binding: binding["capabilities"][0].update({"status": "UNKNOWN"}),
        lambda binding: binding["resources"][0].update({"status": "BLOCKED"}),
    ],
)
def test_strict_n1_gate_rejects_unready_guessed_or_cross_node_runtime_binding(
    tmp_path,
    mutator,
):
    binding = _binding()
    mutator(binding)
    truth = _prepare(tmp_path, _candidate_with_binding(binding))

    with pytest.raises(
        N1StrictRealityGateError,
        match="BINDING_INVALID",
    ):
        N1StrictRealityGateService(
            truth, source_commit=COMMIT
        ).complete(release_batch_id=BATCH)

    assert truth.query("rc72_node_delivery", mission_id=MISSION) == []
    assert truth.query("rc72_node_gate", mission_id=MISSION) == []
    assert truth.query("rc72_n1_executable_binding") == []
    assert truth.query("rc72_mission_node", mission_node_id=NODE2)[0]["state"] == "NOT_STARTED"


def test_strict_n1_gate_rejects_duplicate_binding_key_before_delivery(tmp_path):
    candidate = _candidate_with_binding()
    candidate["facts"]["executable_bindings"].append(deepcopy(_binding()))
    truth = _prepare(tmp_path, candidate)

    with pytest.raises(
        N1StrictRealityGateError,
        match="BINDING_KEY_DUPLICATE",
    ):
        N1StrictRealityGateService(
            truth, source_commit=COMMIT
        ).complete(release_batch_id=BATCH)

    assert truth.query("rc72_node_delivery", mission_id=MISSION) == []
    assert truth.query("rc72_node_gate", mission_id=MISSION) == []
