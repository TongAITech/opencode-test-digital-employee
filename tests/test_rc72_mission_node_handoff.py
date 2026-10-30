from pathlib import Path
import json
import subprocess

import pytest

from rc6_runtime.agent_runtime import AgentRuntimeError, DshHeadlessWorkerLauncher
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.models import Mission, Task
from rc7_runtime.rc72_authority import RC72AuthorityRuntime
from rc7_runtime.rc72_mission_node_assignment import install_rc72_mission_node_assignment_overlay
from rc7_runtime.rc72_mission_node_handoff import (
    MissionNodeHandoffError,
    N1DshHandoffService,
    install_rc72_mission_node_handoff_overlay,
    validate_rc72_mission_node_worker_attempt,
)
from rc7_runtime.rc72_truth import install_rc72_truth_overlay
from rc7_runtime.truth_overlay import install_rc7_truth_overlay


COMMIT = "3333333333333333333333333333333333333333"
OTHER_COMMIT = "4444444444444444444444444444444444444444"
RELEASE = "PAYMENT-R9.4.2"
MISSION = "MISSION-PAY-942"
BATCH = "RB-PAY-942"
NODE = "MN-N1-PAY-942"
WORKITEM = "WI-N1-PAY-942"
DISPATCH = "N1DISP-PAY-942"
ASSIGNMENT = "N1ASN-PAY-942"
WORKER = "RC72FW-PAY-942"
CAPS = ["reality_recon", "field_evidence"]


def _truth(tmp_path: Path) -> TruthRuntime:
    install_rc7_truth_overlay()
    install_rc72_truth_overlay()
    install_rc72_mission_node_assignment_overlay()
    install_rc72_mission_node_handoff_overlay()
    return TruthRuntime(tmp_path / "r1.jsonl")


def _seed(truth: TruthRuntime) -> None:
    truth.append_atomic(
        "RC72_RELEASE_BATCH_UPSERTED",
        {
            "release_batch_id": BATCH,
            "release_id": RELEASE,
            "mission_id": MISSION,
            "name": RELEASE,
            "planned_release_time": None,
            "version_ids": [RELEASE],
            "application_ids": ["APP-PAY"],
            "requirement_ids": ["REQ-PAY"],
            "state": "REGISTERED",
            "readiness": "READY",
            "created_at": 1,
            "updated_at": 1,
            "artifact_version": 1,
        },
    )
    truth.append_atomic(
        "RC72_MISSION_NODE_UPSERTED",
        {
            "mission_node_id": NODE,
            "release_id": RELEASE,
            "mission_id": MISSION,
            "node_type": "N1_REALITY",
            "scope_ref": "release-batch://%s" % BATCH,
            "state": "RUNNING",
            "active_delivery_version": None,
            "delivery_refs": [],
            "gate_refs": [],
            "open_gap_refs": [],
            "entered_at": 1,
            "exited_at": None,
            "blocked_reason": None,
            "revision": 1,
            "created_at": 1,
            "updated_at": 1,
            "artifact_version": 1,
        },
    )
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(mission_id=MISSION, release_id=RELEASE, goal="N1 reality recon"),
    )
    control.register_task(
        Task(
            task_id=WORKITEM,
            mission_id=MISSION,
            node="REALITY_RECON",
            task_type="RC72_NODE_WORK",
            objective="establish real release reality",
            required_capabilities=list(CAPS),
            acceptance_criteria=["candidate reality facts returned"],
            priority=0,
        )
    )
    leased = control.lease_next(worker_ref=WORKER, capabilities=CAPS)
    assert leased is not None and leased.task_id == WORKITEM

    truth.append_atomic(
        "RC72_MISSION_NODE_DISPATCH_UPSERTED",
        {
            "dispatch_id": DISPATCH,
            "release_id": RELEASE,
            "mission_id": MISSION,
            "release_batch_id": BATCH,
            "source_commit": COMMIT,
            "field_start_receipt_id": "START-PAY-942",
            "mission_node_id": NODE,
            "node_type": "N1_REALITY",
            "stage": "REALITY_RECON",
            "workitem_id": WORKITEM,
            "team_role": "REALITY_RECON_WORKER",
            "execution_substrate": "DSH_AGENT_TEAMS",
            "worker_policy": "FRESH_SESSION_REQUIRED",
            "required_capabilities": list(CAPS),
            "input_refs": [
                "release-batch://%s" % BATCH,
                "mission-node://%s" % NODE,
                "field-start://START-PAY-942",
            ],
            "status": "READY_FOR_ASSIGNMENT",
            "created_at": 2,
            "updated_at": 2,
            "artifact_version": 1,
        },
    )
    truth.append_atomic(
        "RC72_MISSION_NODE_WORKER_ASSIGNMENT_UPSERTED",
        {
            "assignment_id": ASSIGNMENT,
            "dispatch_id": DISPATCH,
            "release_id": RELEASE,
            "mission_id": MISSION,
            "release_batch_id": BATCH,
            "source_commit": COMMIT,
            "mission_node_id": NODE,
            "node_type": "N1_REALITY",
            "stage": "REALITY_RECON",
            "workitem_id": WORKITEM,
            "team_role": "REALITY_RECON_WORKER",
            "agent_id": "reality-recon",
            "execution_substrate": "DSH_AGENT_TEAMS",
            "worker_policy": "FRESH_SESSION_REQUIRED",
            "worker_instance_id": WORKER,
            "assignment_generation": 1,
            "required_capabilities": list(CAPS),
            "input_refs": [
                "release-batch://%s" % BATCH,
                "mission-node://%s" % NODE,
                "field-start://START-PAY-942",
            ],
            "task_state": "LEASED",
            "status": "LEASED_FOR_HANDOFF",
            "recovered_orphan_lease": False,
            "created_at": 3,
            "updated_at": 3,
            "artifact_version": 1,
        },
    )


def _launcher(
    tmp_path: Path,
    truth: TruthRuntime,
    *,
    session_id: str = "session-n1-fresh",
    tool_name: str = "field-probe",
    calls=None,
) -> DshHeadlessWorkerLauncher:
    dsh = tmp_path / "dsh"
    dsh.write_text("fixture executable placeholder", encoding="utf-8")
    patch = tmp_path / "patch.json"
    patch.write_text("{}", encoding="utf-8")
    counter = calls if calls is not None else {"count": 0}

    def runner(command, **kwargs):
        counter["count"] += 1
        events = [
            {"type": "session", "session_id": session_id},
            {"type": "tool_call", "tool_name": tool_name},
            {
                "type": "final",
                "text": json.dumps(
                    {"status": "CANDIDATE", "facts": [], "unknowns": [], "gaps": []}
                ),
            },
        ]
        stdout = "\n".join(json.dumps(event) for event in events) + "\n"
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    return DshHeadlessWorkerLauncher(
        dsh_bin=str(dsh),
        patch_path=str(patch),
        cwd=str(tmp_path),
        truth=truth,
        authority=RC72AuthorityRuntime(b"rc72-handoff-test-signing-key"),
        coordinator_instance_id="coordinator-n1",
        release_id=RELEASE,
        state_root=str(tmp_path / "state"),
        command_runner=runner,
    )


def test_n1_handoff_reuses_exact_agentteams_worker_and_admits_attempt_only_after_session(tmp_path: Path):
    truth = _truth(tmp_path)
    _seed(truth)
    launcher = _launcher(tmp_path, truth)

    result = N1DshHandoffService(
        truth, source_commit=COMMIT, launcher=launcher, allowed_tools=["field-probe"]
    ).handoff(release_batch_id=BATCH)

    assert result["status"] == "SESSION_OBSERVED"
    assert result["worker_instance_id"] == WORKER
    assert result["dsh_session_id"] == "session-n1-fresh"
    assert result["attempt_state"] == "WORKER_COMPLETED_PENDING_DELIVERY"
    assert result["workitem_state"] == "LEASED"

    rows = truth.query("rc72_mission_node_worker_attempt", attempt_id=result["attempt_id"])
    assert len(rows) == 1
    attempt = rows[0]
    assert attempt["worker_instance_id"] == WORKER
    assert attempt["handoff_status"] == "DSH_SESSION_OBSERVED"
    assert attempt["process_outcome"] == "SUCCEEDED"
    assert attempt["observed_tool_calls"][0]["tool_name"] == "field-probe"
    task = truth.query("rc7_task", task_id=WORKITEM)[0]
    assert task["state"] == "LEASED"
    assert task["lease_owner"] == WORKER
    assert truth.query("rc72_node_delivery", mission_id=MISSION) == []
    assert truth.query("rc72_node_gate", mission_id=MISSION) == []


def test_repeated_handoff_resumes_same_attempt_without_second_dsh_launch(tmp_path: Path):
    truth = _truth(tmp_path)
    _seed(truth)
    calls = {"count": 0}
    launcher = _launcher(tmp_path, truth, calls=calls)
    service = N1DshHandoffService(
        truth, source_commit=COMMIT, launcher=launcher, allowed_tools=["field-probe"]
    )

    first = service.handoff(release_batch_id=BATCH)
    second = service.handoff(release_batch_id=BATCH)

    assert first["status"] == "SESSION_OBSERVED"
    assert second["status"] == "RESUMED"
    assert first["attempt_id"] == second["attempt_id"]
    assert first["dsh_session_id"] == second["dsh_session_id"]
    assert calls["count"] == 1
    assert len(truth.query("rc72_mission_node_worker_attempt", mission_id=MISSION)) == 1


def test_dsh_tool_outside_authority_lease_cannot_be_admitted_as_attempt(tmp_path: Path):
    truth = _truth(tmp_path)
    _seed(truth)
    launcher = _launcher(tmp_path, truth, tool_name="unapproved-shell")

    with pytest.raises(MissionNodeHandoffError, match="UNAUTHORIZED_TOOL"):
        N1DshHandoffService(
            truth, source_commit=COMMIT, launcher=launcher, allowed_tools=["field-probe"]
        ).handoff(release_batch_id=BATCH)

    assert truth.query("rc72_mission_node_worker_attempt", mission_id=MISSION) == []


def test_missing_fresh_dsh_session_fails_before_attempt_truth(tmp_path: Path):
    truth = _truth(tmp_path)
    _seed(truth)
    launcher = _launcher(tmp_path, truth, session_id="not-a-session")

    with pytest.raises(AgentRuntimeError, match="DSH_SESSION_ID_MISSING"):
        N1DshHandoffService(
            truth, source_commit=COMMIT, launcher=launcher, allowed_tools=["field-probe"]
        ).handoff(release_batch_id=BATCH)

    assert truth.query("rc72_mission_node_worker_attempt", mission_id=MISSION) == []


def test_stale_source_commit_cannot_launch_dsh(tmp_path: Path):
    truth = _truth(tmp_path)
    _seed(truth)
    calls = {"count": 0}
    launcher = _launcher(tmp_path, truth, calls=calls)

    with pytest.raises(MissionNodeHandoffError, match="EXACT_ASSIGNMENT_REQUIRED:0"):
        N1DshHandoffService(
            truth, source_commit=OTHER_COMMIT, launcher=launcher, allowed_tools=["field-probe"]
        ).handoff(release_batch_id=BATCH)

    assert calls["count"] == 0
    assert truth.query("agent_runtime_event", mission_id=MISSION) == []


def test_rc72_authority_adoption_is_idempotent_and_conflicting_identity_fails_closed():
    authority = RC72AuthorityRuntime(b"rc72-authority-adoption-test-key")
    first = authority.adopt_identity(
        worker_id=WORKER,
        role="REALITY_RECON_WORKER",
        phase="MISSION_NODE_EXECUTION",
        layer=None,
        generation=1,
        session_id="control-assignment://%s" % ASSIGNMENT,
    )
    second = authority.adopt_identity(
        worker_id=WORKER,
        role="REALITY_RECON_WORKER",
        phase="MISSION_NODE_EXECUTION",
        layer=None,
        generation=1,
        session_id="control-assignment://%s" % ASSIGNMENT,
    )
    assert first == second

    with pytest.raises(Exception, match="WORKER_IDENTITY_CONFLICT"):
        authority.adopt_identity(
            worker_id=WORKER,
            role="REALITY_RECON_WORKER",
            phase="MISSION_NODE_EXECUTION",
            layer=None,
            generation=2,
            session_id="control-assignment://other",
        )


def test_attempt_contract_rejects_node_gate_or_pass_smuggling(tmp_path: Path):
    truth = _truth(tmp_path)
    _seed(truth)
    launcher = _launcher(tmp_path, truth)
    result = N1DshHandoffService(
        truth, source_commit=COMMIT, launcher=launcher, allowed_tools=["field-probe"]
    ).handoff(release_batch_id=BATCH)
    attempt = dict(
        truth.query("rc72_mission_node_worker_attempt", attempt_id=result["attempt_id"])[0]
    )
    attempt["node_gate"] = "PASS"

    with pytest.raises(Exception, match="BUSINESS_CLAIM_FORBIDDEN:node_gate"):
        validate_rc72_mission_node_worker_attempt(attempt)
