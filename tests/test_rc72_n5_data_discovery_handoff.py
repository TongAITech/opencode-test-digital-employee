from pathlib import Path
import json
import subprocess

import pytest

from rc6_runtime.agent_runtime import AgentRuntimeError, DshHeadlessWorkerLauncher
from rc6_runtime.authority import AuthorityError
from rc7_runtime.rc72_authority import DATA_PREPARER, RC72AuthorityRuntime
from rc7_runtime.rc72_n5_data_discovery_assignment import N5DataDiscoveryAssignmentService
from rc7_runtime.rc72_n5_data_discovery_handoff import (
    N5DataDiscoveryDshHandoffService,
    N5DataDiscoveryHandoffError,
    validate_rc72_n5_data_discovery_attempt,
)

from rc72_n2_test_support import BATCH, COMMIT, MISSION, RELEASE
from test_rc72_n5_data_discovery_assignment import _dispatched


TOOL_DATA = "data-query"
TOOL_CONSTRUCT = "data-construct"


def _ready(tmp_path: Path, monkeypatch):
    truth, inventory, dispatched = _dispatched(tmp_path, monkeypatch)
    assigned = N5DataDiscoveryAssignmentService(
        truth,
        release_id=RELEASE,
        source_commit=COMMIT,
    ).assign_all(release_batch_id=BATCH)
    assert assigned["status"] == "ASSIGNED"
    return truth, inventory, dispatched, assigned


def _candidate(row, *, smuggle=False):
    value = {
        "status": "CANDIDATE",
        "release_batch_id": BATCH,
        "data_requirement_id": row["data_requirement_id"],
        "resolution_plan_id": row["resolution_plan_id"],
        "case_id": row["case_id"],
        "strategy": "DISCOVER_EXISTING",
        "observations": [
            {
                "kind": "REAL_TOOL_OBSERVATION",
                "summary": "a candidate satisfying the scoped case preconditions was observed",
            }
        ],
        "verification_plan": [
            "independently verify the candidate against the canonical DataRequirement before promotion"
        ],
        "unknowns": [],
        "gaps": [],
    }
    if smuggle:
        value["data_ref"] = "db://premature/canonical-data"
    return value


def _launcher(
    tmp_path: Path,
    truth,
    *,
    calls=None,
    fixed_session=None,
    tool_name=TOOL_DATA,
    smuggle=False,
):
    dsh = tmp_path / ("dsh-n5-data-%s" % id(calls))
    dsh.write_text("fixture executable placeholder", encoding="utf-8")
    patch = tmp_path / ("patch-n5-data-%s.json" % id(calls))
    patch.write_text("{}", encoding="utf-8")
    counter = calls if calls is not None else {"count": 0}

    def runner(command, **kwargs):
        counter["count"] += 1
        prompt = str(command[-1])
        assert "DATA_PREPARER" in prompt
        assert "one assigned DataRequirement" in prompt
        receipts = truth.query(
            "rc72_n5_data_discovery_assignment", release_batch_id=BATCH
        )
        matches = [
            row for row in receipts
            if str(row["data_requirement_id"]) in prompt
            and str(row["case_id"]) in prompt
        ]
        assert len(matches) == 1
        row = matches[0]
        session_id = fixed_session or "session-n5-data-%d" % counter["count"]
        events = [
            {"type": "session", "session_id": session_id},
            {"type": "tool_call", "tool_name": tool_name},
            {
                "type": "final",
                "text": json.dumps(_candidate(row, smuggle=smuggle), ensure_ascii=False),
            },
        ]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="\n".join(json.dumps(item, ensure_ascii=False) for item in events) + "\n",
            stderr="",
        )

    return DshHeadlessWorkerLauncher(
        dsh_bin=str(dsh),
        patch_path=str(patch),
        cwd=str(tmp_path),
        truth=truth,
        authority=RC72AuthorityRuntime(b"rc72-n5-data-handoff-test-key"),
        coordinator_instance_id="coordinator-n5-data",
        release_id=RELEASE,
        state_root=str(tmp_path / ("state-n5-data-%s" % id(calls))),
        command_runner=runner,
    )


def _first_assignment(truth):
    rows = sorted(
        truth.query("rc72_n5_data_discovery_assignment", release_batch_id=BATCH),
        key=lambda row: str(row["data_requirement_id"]),
    )
    assert rows
    return rows[0]


def test_data_preparer_is_zero_artifact_role_with_task_scoped_tools_only():
    authority = RC72AuthorityRuntime(b"rc72-data-preparer-authority-test-key")
    identity = authority.adopt_identity(
        worker_id="data-worker-1",
        role=DATA_PREPARER,
        phase="MISSION_NODE_EXECUTION",
        layer=None,
        generation=1,
        session_id="control-assignment://data-assignment-1",
    )
    lease = authority.issue_lease(
        identity.worker_id,
        "task:WI-N5-1",
        (),
        (TOOL_DATA,),
    )
    authority.authorize_tool(identity.worker_id, lease.lease_id, TOOL_DATA)
    with pytest.raises(AuthorityError, match="LEASE_TOOL_FORBIDDEN"):
        authority.authorize_tool(identity.worker_id, lease.lease_id, "unleased-shell")
    with pytest.raises(AuthorityError, match="LEASE_ARTIFACT_SCOPE_EXCEEDS_ROLE"):
        authority.issue_lease(
            identity.worker_id,
            "task:WI-N5-1",
            ("test_design",),
            (TOOL_DATA,),
        )


def test_n5_discovery_handoff_observes_fresh_real_dsh_without_promoting_data_truth(
    tmp_path: Path, monkeypatch
):
    truth, _inventory, _dispatched_result, _assigned = _ready(tmp_path, monkeypatch)
    receipt = _first_assignment(truth)
    calls = {"count": 0}
    service = N5DataDiscoveryDshHandoffService(
        truth,
        source_commit=COMMIT,
        launcher=_launcher(tmp_path, truth, calls=calls),
        allowed_tools=[TOOL_DATA, TOOL_CONSTRUCT],
    )

    result = service.handoff(
        release_batch_id=BATCH,
        data_requirement_id=receipt["data_requirement_id"],
    )

    assert result["status"] == "SESSION_OBSERVED"
    assert calls["count"] == 1
    assert result["worker_instance_id"] == receipt["worker_instance_id"]
    assert result["dsh_session_id"].startswith("session-n5-data-")
    assert result["attempt_state"] == "WORKER_COMPLETED_PENDING_RAW_ANCHOR"
    assert result["workitem_state"] == "LEASED"

    attempts = truth.query(
        "rc72_n5_data_discovery_attempt", attempt_id=result["attempt_id"]
    )
    assert len(attempts) == 1
    attempt = attempts[0]
    assert attempt["data_requirement_id"] == receipt["data_requirement_id"]
    assert attempt["resolution_plan_id"] == receipt["resolution_plan_id"]
    assert attempt["case_id"] == receipt["case_id"]
    assert attempt["source_case_sha256"] == receipt["source_case_sha256"]
    assert attempt["candidate_schema"] == "RC72_N5_DATA_DISCOVERY_CANDIDATE_V1"
    assert attempt["authorized_tools"] == [TOOL_DATA, TOOL_CONSTRUCT]
    assert attempt["observed_tool_calls"][0]["tool_name"] == TOOL_DATA
    assert any(ref.startswith("file://") for ref in attempt["runtime_evidence_refs"])
    assert attempt["input_refs"] == receipt["input_refs"]
    for forbidden in (
        "data_ref", "binding_id", "verification", "verified", "data_lease_id",
        "raw_evidence_sha256", "canonical_evidence_id", "node_pass", "n5_pass",
        "n6_ready", "field_verified", "bank_final",
    ):
        assert forbidden not in attempt

    task = truth.query("rc7_task", task_id=receipt["workitem_id"])[0]
    assert task["state"] == "LEASED"
    assert task["lease_owner"] == receipt["worker_instance_id"]
    assert truth.query(
        "rc72_n5_data_binding", data_requirement_id=receipt["data_requirement_id"]
    ) == []
    assert truth.query("rc72_data_lease") == []
    assert truth.query(
        "rc72_node_delivery", mission_id=MISSION, node_type="N5_TEST_DATA"
    ) == []
    assert truth.query(
        "rc72_node_gate", mission_id=MISSION, node_type="N5_TEST_DATA"
    ) == []
    n5 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N5_TEST_DATA"
    )[0]
    n6 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N6_EXECUTABLE_READINESS"
    )[0]
    assert n5["state"] == "RUNNING"
    assert n6["state"] == "NOT_STARTED"


def test_n5_discovery_handoff_replay_is_idempotent_without_second_dsh_session(
    tmp_path: Path, monkeypatch
):
    truth, _inventory, _dispatched_result, _assigned = _ready(tmp_path, monkeypatch)
    receipt = _first_assignment(truth)
    calls = {"count": 0}
    service = N5DataDiscoveryDshHandoffService(
        truth,
        source_commit=COMMIT,
        launcher=_launcher(tmp_path, truth, calls=calls),
        allowed_tools=[TOOL_DATA],
    )
    first = service.handoff(
        release_batch_id=BATCH,
        data_requirement_id=receipt["data_requirement_id"],
    )
    second = service.handoff(
        release_batch_id=BATCH,
        data_requirement_id=receipt["data_requirement_id"],
    )
    assert first["status"] == "SESSION_OBSERVED"
    assert second["status"] == "RESUMED"
    assert first["attempt_id"] == second["attempt_id"]
    assert first["dsh_session_id"] == second["dsh_session_id"]
    assert calls["count"] == 1


def test_n5_discovery_handoff_rejects_unapproved_tool_and_admits_no_attempt(
    tmp_path: Path, monkeypatch
):
    truth, _inventory, _dispatched_result, _assigned = _ready(tmp_path, monkeypatch)
    receipt = _first_assignment(truth)
    service = N5DataDiscoveryDshHandoffService(
        truth,
        source_commit=COMMIT,
        launcher=_launcher(tmp_path, truth, tool_name="unapproved-shell"),
        allowed_tools=[TOOL_DATA],
    )
    with pytest.raises(N5DataDiscoveryHandoffError, match="UNAUTHORIZED_TOOL"):
        service.handoff(
            release_batch_id=BATCH,
            data_requirement_id=receipt["data_requirement_id"],
        )
    assert truth.query("rc72_n5_data_discovery_attempt", mission_id=MISSION) == []
    n6 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N6_EXECUTABLE_READINESS"
    )[0]
    assert n6["state"] == "NOT_STARTED"


def test_n5_discovery_handoff_rejects_reused_dsh_session_across_workitems(
    tmp_path: Path, monkeypatch
):
    truth, _inventory, _dispatched_result, _assigned = _ready(tmp_path, monkeypatch)
    receipts = sorted(
        truth.query("rc72_n5_data_discovery_assignment", release_batch_id=BATCH),
        key=lambda row: str(row["data_requirement_id"]),
    )
    assert len(receipts) >= 2
    fixed = "session-n5-data-reused"
    first_service = N5DataDiscoveryDshHandoffService(
        truth,
        source_commit=COMMIT,
        launcher=_launcher(tmp_path, truth, fixed_session=fixed),
        allowed_tools=[TOOL_DATA],
    )
    first_service.handoff(
        release_batch_id=BATCH,
        data_requirement_id=receipts[0]["data_requirement_id"],
    )
    second_service = N5DataDiscoveryDshHandoffService(
        truth,
        source_commit=COMMIT,
        launcher=_launcher(tmp_path, truth, fixed_session=fixed),
        allowed_tools=[TOOL_DATA],
    )
    with pytest.raises(N5DataDiscoveryHandoffError, match="DSH_SESSION_REUSED"):
        second_service.handoff(
            release_batch_id=BATCH,
            data_requirement_id=receipts[1]["data_requirement_id"],
        )
    assert len(truth.query("rc72_n5_data_discovery_attempt", mission_id=MISSION)) == 1


def test_n5_discovery_candidate_cannot_smuggle_data_ref_into_attempt_truth(
    tmp_path: Path, monkeypatch
):
    truth, _inventory, _dispatched_result, _assigned = _ready(tmp_path, monkeypatch)
    receipt = _first_assignment(truth)
    service = N5DataDiscoveryDshHandoffService(
        truth,
        source_commit=COMMIT,
        launcher=_launcher(tmp_path, truth, smuggle=True),
        allowed_tools=[TOOL_DATA],
    )
    with pytest.raises(
        N5DataDiscoveryHandoffError,
        match="CANDIDATE_TOP_LEVEL_CONTRACT_INVALID",
    ):
        service.handoff(
            release_batch_id=BATCH,
            data_requirement_id=receipt["data_requirement_id"],
        )
    assert truth.query("rc72_n5_data_discovery_attempt", mission_id=MISSION) == []
    assert truth.query("rc72_data_lease") == []


def test_n5_attempt_contract_rejects_post_handoff_acceptance_claims(
    tmp_path: Path, monkeypatch
):
    truth, _inventory, _dispatched_result, _assigned = _ready(tmp_path, monkeypatch)
    receipt = _first_assignment(truth)
    result = N5DataDiscoveryDshHandoffService(
        truth,
        source_commit=COMMIT,
        launcher=_launcher(tmp_path, truth),
        allowed_tools=[TOOL_DATA],
    ).handoff(
        release_batch_id=BATCH,
        data_requirement_id=receipt["data_requirement_id"],
    )
    attempt = truth.query(
        "rc72_n5_data_discovery_attempt", attempt_id=result["attempt_id"]
    )[0]
    for field, value in (
        ("data_ref", "db://fake"),
        ("data_lease_id", "LEASE-FAKE"),
        ("raw_evidence_sha256", "sha256:fake"),
        ("node_pass", True),
        ("n6_ready", True),
        ("field_verified", True),
        ("bank_final", True),
    ):
        tampered = dict(attempt)
        tampered[field] = value
        with pytest.raises(Exception, match="BUSINESS_CLAIM_FORBIDDEN"):
            validate_rc72_n5_data_discovery_attempt(tampered)


def test_n5_discovery_handoff_source_commit_is_exact_not_best_effort(
    tmp_path: Path, monkeypatch
):
    truth, _inventory, _dispatched_result, _assigned = _ready(tmp_path, monkeypatch)
    receipt = _first_assignment(truth)
    service = N5DataDiscoveryDshHandoffService(
        truth,
        source_commit="stale-source-commit",
        launcher=_launcher(tmp_path, truth),
        allowed_tools=[TOOL_DATA],
    )
    with pytest.raises(
        N5DataDiscoveryHandoffError,
        match="EXACT_ASSIGNMENT_REQUIRED",
    ):
        service.handoff(
            release_batch_id=BATCH,
            data_requirement_id=receipt["data_requirement_id"],
        )
    assert truth.query("rc72_n5_data_discovery_attempt", mission_id=MISSION) == []
