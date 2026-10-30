from pathlib import Path
import json
import subprocess

from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.models import Mission, Task
from rc7_runtime.rc72_authority import RC72AuthorityRuntime
from rc7_runtime.rc72_n1_completion import N1DeliveryGateService, N1GovernedHandoffService
from rc7_runtime.rc72_n1_revision import (
    N1RevisionDeliveryGateService,
    N1RevisionDispatchService,
    N1RevisionGovernedHandoffService,
    install_rc72_n1_revision_overlay,
)
from rc7_runtime.rc72_truth import install_rc72_truth_overlay
from rc7_runtime.truth_overlay import install_rc7_truth_overlay


COMMIT = "6666666666666666666666666666666666666666"
RELEASE = "CONFIG-X5.2.7"
MISSION = "MISSION-CONFIG-REV-527"
BATCH = "RB-CONFIG-REV-527"
NODE = "MN-N1-CONFIG-REV-527"
NODE2 = "MN-N2-CONFIG-REV-527"
WORKITEM = "WI-N1-CONFIG-REV-527"
DISPATCH = "N1DISP-CONFIG-REV-527"
ASSIGNMENT = "N1ASN-CONFIG-REV-527"
WORKER = "RC72FW-CONFIG-REV-527"
CAPS = ["reality_recon", "field_evidence"]


def _truth(tmp_path: Path) -> TruthRuntime:
    install_rc7_truth_overlay()
    install_rc72_truth_overlay()
    install_rc72_n1_revision_overlay()
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
    truth.append_atomic("RC72_MISSION_NODE_UPSERTED", _node_payload(NODE, "N1_REALITY", "RUNNING"))
    truth.append_atomic("RC72_MISSION_NODE_UPSERTED", _node_payload(NODE2, "N2_REQUIREMENT", "NOT_STARTED"))

    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(mission_id=MISSION, release_id=RELEASE, goal="N1 governed revision"),
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
            "field_start_receipt_id": "START-CONFIG-REV-527",
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
                "field-start://START-CONFIG-REV-527",
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
                "field-start://START-CONFIG-REV-527",
            ],
            "task_state": "LEASED",
            "status": "LEASED_FOR_HANDOFF",
            "recovered_orphan_lease": False,
            "created_at": 3,
            "updated_at": 3,
            "artifact_version": 1,
        },
    )


def _candidate(*, gaps=None, deployment=True):
    return {
        "status": "CANDIDATE",
        "facts": {
            "release_id": RELEASE,
            "release_batch_id": BATCH,
            "source_commit": COMMIT,
            "deployment_records": ([{"application_id": "APP-CONFIG", "environment": "FAT1", "deployment_id": "DEP-527"}] if deployment else []),
            "environment_checks": [{"name": "config-api", "status": "REACHABLE"}],
            "capability_checks": [{"name": "field-probe", "status": "AVAILABLE"}],
        },
        "unknowns": [],
        "gaps": list(gaps or []),
    }


def _launcher(tmp_path: Path, truth: TruthRuntime, candidate, *, session_id: str):
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
        authority=RC72AuthorityRuntime(b"rc72-n1-revision-test-key"),
        coordinator_instance_id="coordinator-n1-revision",
        release_id=RELEASE,
        state_root=str(tmp_path / "state"),
        command_runner=runner,
    )


def _initial_failed_gate(tmp_path: Path, truth: TruthRuntime):
    N1GovernedHandoffService(
        truth,
        source_commit=COMMIT,
        launcher=_launcher(
            tmp_path,
            truth,
            _candidate(gaps=["deployment readiness evidence incomplete"]),
            session_id="session-n1-initial-failed",
        ),
        allowed_tools=["field-probe"],
    ).handoff(release_batch_id=BATCH)
    return N1DeliveryGateService(truth, source_commit=COMMIT).complete(release_batch_id=BATCH)


def test_failed_n1_gate_creates_fresh_revision_worker_and_new_governed_workitem(tmp_path: Path):
    truth = _truth(tmp_path)
    _seed(truth)
    failed = _initial_failed_gate(tmp_path, truth)
    assert failed["gate"]["decision"] == "NEEDS_REVISION"
    assert failed["gate"]["n1_state"] == "NEEDS_REVISION"
    assert failed["gate"]["n2_state"] == "NOT_STARTED"

    revision = N1RevisionDispatchService(truth, source_commit=COMMIT).plan_and_assign(
        release_batch_id=BATCH
    )
    assert revision["status"] == "ASSIGNED"
    assert revision["revision_generation"] == 2
    assert revision["workitem_id"] != WORKITEM
    assert revision["worker_instance_id"] != WORKER
    assert revision["workitem_state"] == "LEASED"
    assert revision["node_state"] == "RUNNING"

    previous_task = truth.query("rc7_task", task_id=WORKITEM)[0]
    revision_task = truth.query("rc7_task", task_id=revision["workitem_id"])[0]
    assert previous_task["state"] == "OUTPUT_PRODUCED"
    assert revision_task["state"] == "LEASED"
    assert revision_task["input_artifact_refs"] == [failed["delivery"]["artifact_id"]]


def test_revision_cycle_preserves_failed_history_and_passes_only_after_fresh_dsh_session(tmp_path: Path):
    truth = _truth(tmp_path)
    _seed(truth)
    failed = _initial_failed_gate(tmp_path, truth)
    revision = N1RevisionDispatchService(truth, source_commit=COMMIT).plan_and_assign(
        release_batch_id=BATCH
    )

    N1RevisionGovernedHandoffService(
        truth,
        source_commit=COMMIT,
        launcher=_launcher(
            tmp_path,
            truth,
            _candidate(),
            session_id="session-n1-revision-pass",
        ),
        allowed_tools=["field-probe"],
    ).handoff(release_batch_id=BATCH)
    result = N1RevisionDeliveryGateService(truth, source_commit=COMMIT).complete(
        release_batch_id=BATCH
    )

    assert result["delivery"]["delivery_version"] == 2
    assert result["gate"]["decision"] == "PASS"
    assert result["gate"]["n1_state"] == "PASS"
    assert result["gate"]["n2_state"] == "READY"
    assert result["gate"]["workitem_state"] == "PASS"

    attempts = truth.query("rc72_mission_node_worker_attempt", mission_id=MISSION)
    deliveries = truth.query("rc72_node_delivery", mission_id=MISSION)
    gates = truth.query("rc72_node_gate", mission_id=MISSION)
    anchors = truth.query("rc72_n1_dsh_evidence_anchor", mission_id=MISSION)
    receipts = truth.query("rc72_n1_revision_receipt", mission_id=MISSION)
    assert len(attempts) == 2
    assert len({row["worker_instance_id"] for row in attempts}) == 2
    assert len({row["dsh_session_id"] for row in attempts}) == 2
    assert len(deliveries) == 2
    assert sorted(row["version"] for row in deliveries) == [1, 2]
    assert len(gates) == 2
    assert [row["decision"] for row in gates].count("NEEDS_REVISION") == 1
    assert [row["decision"] for row in gates].count("PASS") == 1
    assert len(anchors) == 2
    assert len(receipts) == 1
    assert receipts[0]["failed_gate_id"] == failed["gate"]["gate_id"]
    assert truth.query("rc7_task", task_id=WORKITEM)[0]["state"] == "OUTPUT_PRODUCED"
    assert truth.query("rc7_task", task_id=revision["workitem_id"])[0]["state"] == "PASS"


def test_revision_plan_is_idempotent_and_never_reuses_failed_worker(tmp_path: Path):
    truth = _truth(tmp_path)
    _seed(truth)
    _initial_failed_gate(tmp_path, truth)
    service = N1RevisionDispatchService(truth, source_commit=COMMIT)

    first = service.plan_and_assign(release_batch_id=BATCH)
    second = service.plan_and_assign(release_batch_id=BATCH)

    assert first["status"] == "ASSIGNED"
    assert second["status"] == "RESUMED"
    assert first["revision_id"] == second["revision_id"]
    assert first["workitem_id"] == second["workitem_id"]
    assert first["worker_instance_id"] == second["worker_instance_id"]
    assert first["worker_instance_id"] != WORKER
    assert len(truth.query("rc72_n1_revision_receipt", mission_id=MISSION)) == 1
    assert len(truth.query("rc72_mission_node_worker_assignment", mission_id=MISSION)) == 2
