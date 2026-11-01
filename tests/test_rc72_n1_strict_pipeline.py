from copy import deepcopy

import pytest

from rc7_runtime.rc72_n1_strict_pipeline import (
    N1StrictDshHandoffService,
    N1StrictPipelineService,
)
from rc7_runtime.rc72_n1_strict_reality_gate import N1StrictRealityGateError

from test_rc72_n1_completion import (
    BATCH,
    COMMIT,
    MISSION,
    NODE,
    NODE2,
    _good_candidate,
    _launcher,
    _seed,
    _truth,
)
from test_rc72_n1_executable_binding import BINDING_KEY, _binding


def _candidate_with_binding():
    candidate = deepcopy(_good_candidate())
    candidate["facts"]["executable_bindings"] = [deepcopy(_binding())]
    return candidate


def _pipeline(tmp_path, truth, candidate):
    return N1StrictPipelineService(
        truth,
        source_commit=COMMIT,
        launcher=_launcher(tmp_path, truth, candidate),
        allowed_tools=["field-probe"],
    )


def test_strict_n1_worker_prompt_requires_runtime_owned_bindings(tmp_path):
    truth = _truth(tmp_path)
    _seed(truth)
    assignment = truth.query("rc72_mission_node_worker_assignment")[0]
    service = N1StrictDshHandoffService(
        truth,
        source_commit=COMMIT,
        launcher=_launcher(tmp_path, truth, _candidate_with_binding()),
        allowed_tools=["field-probe"],
    )

    prompt = service._prompt(assignment)

    assert "facts.executable_bindings MUST be a non-empty list" in prompt
    assert "Never guess" in prompt
    assert "endpoint{verified=true" in prompt
    assert "tool_route{verified=true" in prompt
    assert "capabilities[{name,status=READY,source_ref}]" in prompt
    assert "resources[{name,status=READY,source_ref}]" in prompt
    assert "N1 MUST NOT emit request" in prompt
    assert "request_schema" in prompt
    assert "schema_ref" in prompt
    assert "cleanup" in prompt
    assert '"source_commit": "' + COMMIT + '"' in prompt


def test_strict_n1_pipeline_closes_handoff_anchor_gate_and_binding(tmp_path):
    truth = _truth(tmp_path)
    _seed(truth)

    result = _pipeline(
        tmp_path, truth, _candidate_with_binding()
    ).complete(release_batch_id=BATCH)

    assert result["handoff"]["dsh_session_id"].startswith("session-")
    assert result["handoff"]["raw_output_sha256"].startswith("sha256:")
    completion = result["completion"]
    assert completion["gate"]["decision"] == "PASS"
    assert completion["gate"]["n1_state"] == "PASS"
    assert completion["gate"]["n2_state"] == "READY"
    assert completion["binding_keys"] == [BINDING_KEY]
    assert len(completion["executable_bindings"]) == 1
    assert result["field_verified"] is False
    assert result["bank_final"] is False
    assert len(truth.query("rc72_n1_dsh_evidence_anchor", mission_id=MISSION)) == 1
    assert len(truth.query("rc72_node_delivery", mission_id=MISSION)) == 1
    assert len(truth.query("rc72_node_gate", mission_id=MISSION)) == 1
    assert len(truth.query("rc72_n1_executable_binding", mission_id=MISSION)) == 1


def test_strict_n1_pipeline_missing_runtime_binding_stops_before_delivery(tmp_path):
    truth = _truth(tmp_path)
    _seed(truth)

    with pytest.raises(
        N1StrictRealityGateError,
        match="EXECUTABLE_BINDINGS_REQUIRED",
    ):
        _pipeline(
            tmp_path, truth, deepcopy(_good_candidate())
        ).complete(release_batch_id=BATCH)

    # The actual worker session and its immutable evidence remain available for
    # diagnosis, but no business delivery/gate or N2 forward is admitted.
    assert len(truth.query("rc72_mission_node_worker_attempt", mission_id=MISSION)) == 1
    assert len(truth.query("rc72_n1_dsh_evidence_anchor", mission_id=MISSION)) == 1
    assert truth.query("rc72_node_delivery", mission_id=MISSION) == []
    assert truth.query("rc72_node_gate", mission_id=MISSION) == []
    assert truth.query("rc72_n1_executable_binding", mission_id=MISSION) == []
    assert truth.query("rc72_mission_node", mission_node_id=NODE)[0]["state"] == "RUNNING"
    assert truth.query("rc72_mission_node", mission_node_id=NODE2)[0]["state"] == "NOT_STARTED"


def test_strict_n1_pipeline_replay_does_not_launch_second_worker_session(tmp_path):
    truth = _truth(tmp_path)
    _seed(truth)
    service = _pipeline(tmp_path, truth, _candidate_with_binding())

    first = service.complete(release_batch_id=BATCH)
    second = service.complete(release_batch_id=BATCH)

    assert first["completion"]["gate"]["decision"] == "PASS"
    assert second["handoff"]["status"] == "RESUMED_FROM_CANONICAL_N1"
    assert second["completion"]["gate"]["decision"] == "PASS"
    assert len(truth.query("rc72_mission_node_worker_attempt", mission_id=MISSION)) == 1
    assert len(truth.query("rc72_n1_dsh_evidence_anchor", mission_id=MISSION)) == 1
    assert len(truth.query("rc72_node_delivery", mission_id=MISSION)) == 1
    assert len(truth.query("rc72_node_gate", mission_id=MISSION)) == 1
    assert len(truth.query("rc72_n1_executable_binding", mission_id=MISSION)) == 1
