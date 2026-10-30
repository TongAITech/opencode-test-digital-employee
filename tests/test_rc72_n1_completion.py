from pathlib import Path
import json
import subprocess

import pytest

from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.models import Mission, Task
from rc7_runtime.rc72_authority import RC72AuthorityRuntime
from rc7_runtime.rc72_mission_node_assignment import install_rc72_mission_node_assignment_overlay
from rc7_runtime.rc72_mission_node_handoff import install_rc72_mission_node_handoff_overlay
from rc7_runtime.rc72_n1_completion import (
    N1CompletionError,
    N1DeliveryGateService,
    N1GovernedHandoffService,
)
from rc7_runtime.rc72_truth import install_rc72_truth_overlay
from rc7_runtime.truth_overlay import install_rc7_truth_overlay


COMMIT = "5555555555555555555555555555555555555555"
RELEASE = "CONFIG-X5.2.7"
MISSION = "MISSION-CONFIG-527"
BATCH = "RB-CONFIG-527"
NODE = "MN-N1-CONFIG-527"
NODE2 = "MN-N2-CONFIG-527"
WORKITEM = "WI-N1-CONFIG-527"
DISPATCH = "N1DISP-CONFIG-527"
ASSIGNMENT = "N1ASN-CONFIG-527"
WORKER = "RC72FW-CONFIG-527"
CAPS = ["reality_recon", "field_evidence"]


def _truth(tmp_path: Path) -> TruthRuntime:
    install_rc7_truth_overlay()
    install_rc72_truth_overlay()
    install_rc72_mission_node_assignment_overlay()
    install_rc72_mission_node_handoff_overlay()
    return TruthRuntime(tmp_path / "r1.jsonl")


def _node_payload(node_id: str, node_type: str, state: str):
    return {
        "mission_node_id": node_id,
        "release_id": RELEASE,
        "mission_id": MISSION,
        "node_type": node_type,
        "scope_ref": "release-batch://%s" % BATCH,
        "state": state,
        "active_delivery_version": None,
        "delivery_refs": [],
        "gate_refs": [],
        "open_gap_refs": [],
        "entered_at": 1 if state != "NOT_STARTED" else None,
        "exited_at": None,
        "blocked_reason": None,
        "revision": 1,
        "created_at": 1,
        "updated_at": 1,
        "artifact_version": 1,
    }


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
            "application_ids": ["APP-CONFIG"],
            "requirement_ids": ["REQ-CONFIG"],
            "state": "REGISTERED",
            "readiness": "READY",
            "created_at": 1,
            "updated_at": 1,
            "artifact_version": 1,
        },
    )
    truth.append_atomic(
        "RC72_MISSION_NODE_UPSERTED",
        _node_payload(NODE, "N1_REALITY", "RUNNING"),
    )
    truth.append_atomic(
        "RC72_MISSION_NODE_UPSERTED",
        _node_payload(NODE2, "N2_REQUIREMENT", "NOT_STARTED"),
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
            "field_start_receipt_id": "START-CONFIG-527",
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
                "field-start://START-CONFIG-527",
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
                "field-start://START-CONFIG-527",
            ],
            "task_state": "LEASED",
            "status": "LEASED_FOR_HANDOFF",
            "recovered_orphan_lease": False,
            "created_at": 3,
            "updated_at": 3,
            "artifact_version": 1,
        },
    )


def _good_candidate():
    return {
        "status": "CANDIDATE",
        "facts": {
            "release_id": RELEASE,
            "release_batch_id": BATCH,
            "source_commit": COMMIT,
            "deployment_records": [
                {"application_id": "APP-CONFIG", "environment": "FAT1", "deployment_id": "DEP-527"}
            ],
            "environment_checks": [
                {"name": "config-api", "status": "REACHABLE"}
            ],
            "capability_checks": [
                {"name": "field-probe", "status": "AVAILABLE"}
            ],
        },
        "unknowns": [],
        "gaps": [],
    }


def _launcher(
    tmp_path: Path,
    truth: TruthRuntime,
    candidate,
    *,
    session_id: str = "session-n1-completion",
):
    dsh = tmp_path / "dsh"
    dsh.write_text("fixture executable placeholder", encoding="utf-8")
    patch = tmp_path / "patch.json"
    patch.write_text("{}", encoding="utf-8")

    def runner(command, **kwargs):
        events = [
            {"type": "session", "session_id": session_id},
            {"type": "tool_call", "tool_name": "field-probe"},
            {"type": "final", "text": json.dumps(candidate)},
        ]
        stdout = "\n".join(json.dumps(event) for event in events) + "\n"
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    return DshHeadlessWorkerLauncher(
        dsh_bin=str(dsh),
        patch_path=str(patch),
        cwd=str(tmp_path),
        truth=truth,
        authority=RC72AuthorityRuntime(b"rc72-n1-completion-test-key"),
        coordinator_instance_id="coordinator-n1-completion",
        release_id=RELEASE,
        state_root=str(tmp_path / "state"),
        command_runner=runner,
    )


def _handoff(tmp_path: Path, truth: TruthRuntime, candidate):
    launcher = _launcher(tmp_path, truth, candidate)
    return N1GovernedHandoffService(
        truth,
        source_commit=COMMIT,
        launcher=launcher,
        allowed_tools=["field-probe"],
    ).handoff(release_batch_id=BATCH)


def test_n1_candidate_is_promoted_from_hashed_raw_dsh_evidence_and_pass_gate_releases_n2(tmp_path: Path):
    truth = _truth(tmp_path)
    _seed(truth)
    handoff = _handoff(tmp_path, truth, _good_candidate())
    assert handoff["raw_output_sha256"].startswith("sha256:")

    result = N1DeliveryGateService(truth, source_commit=COMMIT).complete(
        release_batch_id=BATCH
    )

    assert result["delivery"]["status"] == "DELIVERY_ADMITTED"
    assert result["gate"]["decision"] == "PASS"
    assert result["gate"]["n1_state"] == "PASS"
    assert result["gate"]["n2_state"] == "READY"
    assert result["gate"]["workitem_state"] == "PASS"
    assert result["gate"]["field_verified"] is False
    assert result["gate"]["bank_final"] is False

    deliveries = truth.query("rc72_node_delivery", mission_id=MISSION)
    gates = truth.query("rc72_node_gate", mission_id=MISSION)
    artifacts = truth.query("rc7_artifact", mission_id=MISSION)
    evidence = truth.query("rc7_evidence", mission_id=MISSION)
    anchors = truth.query("rc72_n1_dsh_evidence_anchor", mission_id=MISSION)
    assert len(deliveries) == 1
    assert len(gates) == 1
    assert len(anchors) == 1
    assert gates[0]["reviewer_worker_id"] == "rc72-runtime-n1-gate"
    assert gates[0]["reviewer_worker_id"] != WORKER
    assert len(artifacts) == 1
    assert artifacts[0]["content_hash"].startswith("sha256:")
    assert len(evidence) == 1
    assert evidence[0]["content_hash"] == artifacts[0]["content_hash"]
    assert anchors[0]["raw_output_sha256"] == artifacts[0]["content_hash"]


def test_n1_gap_candidate_fails_closed_and_does_not_release_n2(tmp_path: Path):
    truth = _truth(tmp_path)
    _seed(truth)
    candidate = _good_candidate()
    candidate["gaps"] = ["FAT1 deployment health endpoint unavailable"]
    _handoff(tmp_path, truth, candidate)

    result = N1DeliveryGateService(truth, source_commit=COMMIT).complete(
        release_batch_id=BATCH
    )

    assert result["gate"]["decision"] == "NEEDS_REVISION"
    assert "N1_GAPS_EMPTY" in result["gate"]["failed"]
    assert result["gate"]["n1_state"] == "NEEDS_REVISION"
    assert result["gate"]["n2_state"] == "NOT_STARTED"
    assert result["gate"]["workitem_state"] == "OUTPUT_PRODUCED"
    assert truth.query("rc7_evaluation", mission_id=MISSION) == []


def test_n1_incomplete_facts_cannot_become_pass_even_when_worker_process_passed(tmp_path: Path):
    truth = _truth(tmp_path)
    _seed(truth)
    candidate = _good_candidate()
    candidate["facts"]["deployment_records"] = []
    _handoff(tmp_path, truth, candidate)

    result = N1DeliveryGateService(truth, source_commit=COMMIT).complete(
        release_batch_id=BATCH
    )

    assert result["gate"]["decision"] == "NEEDS_REVISION"
    assert "N1_DEPLOYMENT_RECORDS_REQUIRED" in result["gate"]["failed"]
    assert truth.query("rc72_mission_node", mission_node_id=NODE2)[0]["state"] == "NOT_STARTED"


def test_n1_raw_dsh_evidence_tamper_after_anchor_is_rejected_before_delivery(tmp_path: Path):
    truth = _truth(tmp_path)
    _seed(truth)
    handoff = _handoff(tmp_path, truth, _good_candidate())
    attempt = truth.query(
        "rc72_mission_node_worker_attempt", attempt_id=handoff["attempt_id"]
    )[0]
    raw_ref = next(
        ref for ref in attempt["runtime_evidence_refs"] if ref.startswith("file://")
    )
    raw_path = Path(raw_ref[len("file://"):])
    raw_path.write_text(
        raw_path.read_text(encoding="utf-8") + json.dumps({"type": "final", "text": json.dumps(_good_candidate())}) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(N1CompletionError, match="RAW_DSH_EVIDENCE_HASH_MISMATCH"):
        N1DeliveryGateService(truth, source_commit=COMMIT).admit_delivery(
            release_batch_id=BATCH
        )

    assert truth.query("rc72_node_delivery", mission_id=MISSION) == []
    assert truth.query("rc72_node_gate", mission_id=MISSION) == []


def test_n1_completion_is_idempotent_after_pass_and_does_not_duplicate_gate_or_forward(tmp_path: Path):
    truth = _truth(tmp_path)
    _seed(truth)
    _handoff(tmp_path, truth, _good_candidate())
    service = N1DeliveryGateService(truth, source_commit=COMMIT)

    first = service.complete(release_batch_id=BATCH)
    second = service.complete(release_batch_id=BATCH)

    assert first["gate"]["decision"] == "PASS"
    assert second["delivery"]["status"] == "RESUMED"
    assert second["gate"]["status"] == "RESUMED"
    assert second["gate"]["decision"] == "PASS"
    assert len(truth.query("rc72_node_delivery", mission_id=MISSION)) == 1
    assert len(truth.query("rc72_node_gate", mission_id=MISSION)) == 1
