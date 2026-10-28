from pathlib import Path

import pytest

from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher, WorkerInvocation
from rc6_runtime.authority import AuthorityRuntime
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import Task
from rc7_runtime.rc72_domain import ExecutionTaskUnit, ReleaseBatch, TestObligation
from rc7_runtime.rc72_repository import CanonicalRC72Repository
from rc7_runtime.rc72_worker_lifecycle import WorkerLifecycleService
from rc7_runtime.truth_overlay import append_entity


def _setup(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    repo = CanonicalRC72Repository(truth, release_id="RC7.2")
    repo.persist(
        ReleaseBatch(
            release_batch_id="RB-1",
            mission_id="M-1",
            name="batch",
            application_ids=["cfg-center"],
            requirement_ids=["REQ-1"],
        )
    )
    repo.persist(
        TestObligation(
            obligation_id="TO-1",
            mission_id="M-1",
            release_batch_id="RB-1",
            requirement_id="REQ-1",
            sst_id="SST-1",
            application_id="cfg-center",
            business_scenario="guarantor creation",
            business_rule="required fields persist",
            risk_level="HIGH",
            test_level="L3",
            code_slice_refs=["Service#create"],
            oracle_refs=["HTTP", "DB"],
        )
    )
    repo.persist(
        ExecutionTaskUnit(
            etu_id="ETU-1",
            mission_id="M-1",
            release_batch_id="RB-1",
            obligation_id="TO-1",
            case_ids=["TC-1"],
            primary_goal="execute TC-1",
            primary_code_slice="Service#create",
            test_level="L3",
            primary_oracle="HTTP+DB",
            data_domain="guarantor",
            primary_tool_family="api",
            planning_snapshot_ref="PLAN-1",
            cohesion_score=1.0,
            cohesion_explanation="single high-risk case",
            required_capabilities=["tool:api"],
            estimated_duration_minutes=5,
            estimated_cost=1.0,
        )
    )
    append_entity(
        truth,
        Task(
            task_id="WI-1",
            mission_id="M-1",
            node="N7_EXECUTION",
            task_type="ETU_EXECUTION",
            objective="execute ETU-1",
            required_capabilities=["api"],
            input_artifact_refs=["ETU-1"],
            acceptance_criteria=["evidence persisted"],
        ),
        release_id="RC7.2",
    )
    service = WorkerLifecycleService(truth, release_id="RC7.2")
    lifecycle = service.assign_fresh_worker(
        mission_id="M-1",
        team_id="TEAM-1",
        role="test-executor",
        etu_id="ETU-1",
        workitem_id="WI-1",
        canonical_refs={
            "etu_refs": ["ETU-1"],
            "executable_contract_refs": ["EXEC-1"],
            "data_refs": ["DATA-1"],
            "evidence_refs": [],
            "gap_refs": [],
            "coverage_refs": ["COV-LATEST"],
            "lease_refs": [],
        },
    )
    authority = AuthorityRuntime(b"0123456789abcdef0123456789abcdef")
    launcher = DshHeadlessWorkerLauncher(
        dsh_bin="dsh",
        patch_path=str(tmp_path / "patch.yml"),
        cwd=str(tmp_path),
        truth=truth,
        authority=authority,
        coordinator_instance_id="CAPTAIN-1",
        release_id="RC7.2",
        state_root=str(tmp_path / "worker-state"),
    )
    assignment = launcher.assign(
        agent_id="test-executor",
        role="L3_EXECUTE",
        phase="EXECUTION",
        mission_id="M-1",
        attempt_id="ATT-1",
        scope="ETU-1",
        input_refs=["ETU-1", "EXEC-1", "DATA-1"],
        allowed_artifact_types=["execution_attempt", "evidence"],
        allowed_tools=["api"],
    )
    return truth, service, lifecycle, assignment


def test_signed_worker_assignment_is_bound_to_lifecycle_and_workitem_attempt(tmp_path: Path):
    truth, service, lifecycle, assignment = _setup(tmp_path)

    bound = service.bind_signed_runtime_assignment(
        lifecycle_session_id=lifecycle.session_id,
        assignment=assignment,
        case_id="TC-1",
    )

    assert bound.runtime_worker_id == assignment.worker_instance_id
    assert bound.task_lease_ref == assignment.lease.lease_id
    assert bound.attempt_id == "ATT-1"
    session = truth.query("rc72_worker_session", session_id=lifecycle.session_id)[0]
    assert session["runtime_worker_id"] == assignment.worker_instance_id
    assert session["task_lease_ref"] == assignment.lease.lease_id
    assert session["runtime_assignment_id"] == assignment.assignment_id
    binding = truth.query("rc72_workitem_attempt_binding", binding_id=bound.binding_id)[0]
    assert binding["state"] == "PREPARED"
    assert binding["worker_id"] == assignment.worker_instance_id
    assert binding["session_id"] == lifecycle.session_id
    assert binding["task_lease_ref"] == assignment.lease.lease_id


def test_real_dsh_session_identity_upgrades_binding_to_running(tmp_path: Path):
    truth, service, lifecycle, assignment = _setup(tmp_path)
    bound = service.bind_signed_runtime_assignment(
        lifecycle_session_id=lifecycle.session_id,
        assignment=assignment,
        case_id="TC-1",
    )
    invocation = WorkerInvocation(
        worker_instance_id=assignment.worker_instance_id,
        agent_id=assignment.agent_id,
        mission_id=assignment.mission_id,
        attempt_id=assignment.attempt_id,
        assignment_id=assignment.assignment_id,
        lease_id=assignment.lease.lease_id,
        parent_worker_id=assignment.parent_worker_id,
        scope=assignment.scope,
        input_refs=list(assignment.input_refs),
        started_at=1,
        dsh_session_id="DSH-SESSION-REAL-1",
    )

    running = service.record_dsh_session(
        lifecycle_session_id=lifecycle.session_id,
        invocation=invocation,
    )

    assert running.dsh_session_id == "DSH-SESSION-REAL-1"
    session = truth.query("rc72_worker_session", session_id=lifecycle.session_id)[0]
    assert session["dsh_session_id"] == "DSH-SESSION-REAL-1"
    binding = truth.query("rc72_workitem_attempt_binding", binding_id=bound.binding_id)[0]
    assert binding["state"] == "RUNNING"
    assert binding["session_id"] == "DSH-SESSION-REAL-1"
    assert binding["worker_id"] == assignment.worker_instance_id
    assert binding["task_lease_ref"] == assignment.lease.lease_id


def test_runtime_identity_mismatch_fails_closed(tmp_path: Path):
    _, service, lifecycle, assignment = _setup(tmp_path)
    service.bind_signed_runtime_assignment(
        lifecycle_session_id=lifecycle.session_id,
        assignment=assignment,
        case_id="TC-1",
    )
    bad = WorkerInvocation(
        worker_instance_id="WRONG-WORKER",
        agent_id=assignment.agent_id,
        mission_id=assignment.mission_id,
        attempt_id=assignment.attempt_id,
        assignment_id=assignment.assignment_id,
        lease_id=assignment.lease.lease_id,
        parent_worker_id=assignment.parent_worker_id,
        scope=assignment.scope,
        input_refs=list(assignment.input_refs),
        started_at=1,
        dsh_session_id="DSH-SESSION-X",
    )

    with pytest.raises(Exception, match="RUNTIME_WORKER_IDENTITY_MISMATCH"):
        service.record_dsh_session(
            lifecycle_session_id=lifecycle.session_id,
            invocation=bad,
        )


def test_runtime_binding_survives_r1_replay(tmp_path: Path):
    truth, service, lifecycle, assignment = _setup(tmp_path)
    bound = service.bind_signed_runtime_assignment(
        lifecycle_session_id=lifecycle.session_id,
        assignment=assignment,
        case_id="TC-1",
    )
    invocation = WorkerInvocation(
        worker_instance_id=assignment.worker_instance_id,
        agent_id=assignment.agent_id,
        mission_id=assignment.mission_id,
        attempt_id=assignment.attempt_id,
        assignment_id=assignment.assignment_id,
        lease_id=assignment.lease.lease_id,
        parent_worker_id=assignment.parent_worker_id,
        scope=assignment.scope,
        input_refs=list(assignment.input_refs),
        started_at=1,
        dsh_session_id="DSH-SESSION-REAL-1",
    )
    service.record_dsh_session(lifecycle_session_id=lifecycle.session_id, invocation=invocation)

    replayed = TruthRuntime(tmp_path / "r1.jsonl")
    assert replayed.query("rc72_worker_session", session_id=lifecycle.session_id)[0]["dsh_session_id"] == "DSH-SESSION-REAL-1"
    binding = replayed.query("rc72_workitem_attempt_binding", binding_id=bound.binding_id)[0]
    assert binding["state"] == "RUNNING"
    assert binding["session_id"] == "DSH-SESSION-REAL-1"
