"""C07 real R1 scheduling admission tests. No model/DSH/bank assertions."""
import multiprocessing

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.control_plane import TaskScheduler
from rc7_runtime.models import ContractError, TaskStatus
from rc7_runtime.rc72_captain_dispatch_fencing import CaptainDispatchFencer
from rc7_runtime.rc72_captain_scheduling import (
    CaptainFencedWorkItemScheduler, CaptainSchedulingError)
from rc7_runtime.rc72_worker_lifecycle import WorkerLifecycleService
from test_rc72_phase5_worker_lifecycle_contract import _runtime, _refs


def _ready_fixture(tmp_path):
    truth, _, lifecycle = _runtime(tmp_path)
    scheduler = TaskScheduler(truth, "RC7.2")
    # The test fixture has synthetic ETU-named inputs (not valid real
    # rc7_artifacts). Prepare an independent READY scheduler fixture with no
    # unresolved source refs; the ETU lineage is checked explicitly by bridge.
    for name in ("WI-1", "WI-2"):
        row = truth.query("rc7_task", task_id=name)[0]
        task = scheduler._task_from_row(row)
        task.state = TaskStatus.READY
        task.input_artifact_refs = []
        scheduler._persist_task(task, row["artifact_version"] + 1)
    fencer = CaptainDispatchFencer(truth, release_id="RC7.2")
    owner = fencer.acquire_initial(
        mission_id="M-1", team_id="TEAM-1", captain_session_id="CAP-A")
    bridge = CaptainFencedWorkItemScheduler(
        truth=truth, release_id="RC7.2", fencer=fencer,
        lifecycle=lifecycle, scheduler=scheduler,
        role_profiles={"test-executor": ["api", "tool:api"], "L3_EXECUTE": ["api", "tool:api"],
                       "quality-reviewer": ["filesystem"]})
    return truth, fencer, owner, lifecycle, bridge


def _admit(bridge, owner, task, *, role="test-executor"):
    return bridge.dispatch_etu(
        mission_id="M-1", team_id="TEAM-1",
        captain_session_id=owner["captain_session_id"],
        captain_lease_id=owner["lease_id"],
        role=role, etu_id=task.replace("WI-", "ETU-"),
        workitem_id=task, canonical_refs=_refs(task.replace("WI-", "ETU-")))


def test_two_distinct_fresh_workers_run_one_mission_without_shared_session(tmp_path):
    truth, _, owner, _, bridge = _ready_fixture(tmp_path)
    a = _admit(bridge, owner, "WI-1")
    b = _admit(bridge, owner, "WI-2")
    assert a.worker_id != b.worker_id and a.session_id != b.session_id
    assert a.captain_generation == b.captain_generation == 1
    assert a.state == b.state == "LEASED_AWAITING_SIGNED_AUTHORITY_AND_DSH"
    tasks = truth.query("rc7_task", mission_id="M-1")
    assert len([t for t in tasks if t["state"] == "LEASED"]) == 2
    assert {t["lease_owner"] for t in tasks} == {a.worker_id, b.worker_id}
    sessions = truth.query("rc72_worker_session", mission_id="M-1")
    assert len(sessions) == 2
    assert all("chat_history" not in s["context_bundle"] for s in sessions)
    assert all("captain_token" not in s["context_bundle"] for s in sessions)
    # Scheduling is not a DSH invocation or an accepted business result.
    assert not truth.query("execution_attempt", mission_id="M-1")


def test_wrong_captain_or_team_cannot_create_worker(tmp_path):
    truth, _, owner, _, bridge = _ready_fixture(tmp_path)
    kwargs = dict(mission_id="M-1", team_id="TEAM-1",
                  captain_session_id="CAP-B",
                  captain_lease_id=owner["lease_id"],
                  role="test-executor", etu_id="ETU-1", workitem_id="WI-1",
                  canonical_refs=_refs("ETU-1"))
    with pytest.raises(ContractError, match="CAPTAIN_DISPATCH_FENCED"):
        bridge.dispatch_etu(**kwargs)
    kwargs.update(captain_session_id="CAP-A", team_id="TEAM-OTHER")
    with pytest.raises(CaptainSchedulingError, match="TEAM_MISMATCH"):
        bridge.dispatch_etu(**kwargs)
    assert truth.query("rc72_worker_session", mission_id="M-1") == []


def test_review_role_cannot_execute_etu_even_if_capability_profile_exists(tmp_path):
    truth, _, owner, _, bridge = _ready_fixture(tmp_path)
    with pytest.raises(CaptainSchedulingError, match="ROLE_CANNOT_EXECUTE_ETU"):
        bridge.dispatch_etu(
            mission_id="M-1", team_id="TEAM-1",
            captain_session_id="CAP-A", captain_lease_id=owner["lease_id"],
            role="quality-reviewer", etu_id="ETU-1", workitem_id="WI-1",
            canonical_refs=_refs("ETU-1"))
    assert truth.query("rc72_worker_session", mission_id="M-1") == []


def test_workitem_capability_not_present_in_role_profile_fails_before_worker(tmp_path):
    truth, fencer, owner, lifecycle, _ = _ready_fixture(tmp_path)
    bridge = CaptainFencedWorkItemScheduler(
        truth=truth, release_id="RC7.2", fencer=fencer,
        lifecycle=lifecycle, scheduler=TaskScheduler(truth, "RC7.2"),
        role_profiles={"test-executor": ["tool:api"]})
    with pytest.raises(CaptainSchedulingError, match="CAPABILITY_GAP"):
        _admit(bridge, owner, "WI-1")
    assert truth.query("rc72_worker_session", mission_id="M-1") == []


def test_etu_capability_not_present_in_role_profile_fails_before_worker(tmp_path):
    truth, fencer, owner, lifecycle, _ = _ready_fixture(tmp_path)
    bridge = CaptainFencedWorkItemScheduler(
        truth=truth, release_id="RC7.2", fencer=fencer,
        lifecycle=lifecycle, scheduler=TaskScheduler(truth, "RC7.2"),
        role_profiles={"test-executor": ["api"]})
    with pytest.raises(CaptainSchedulingError, match="ETU_CAPABILITY_GAP"):
        _admit(bridge, owner, "WI-1")
    assert truth.query("rc72_worker_session", mission_id="M-1") == []


def test_role_profile_never_accepts_full_access(tmp_path):
    truth, fencer, owner, lifecycle, _ = _ready_fixture(tmp_path)
    with pytest.raises(CaptainSchedulingError, match="FULL_ACCESS_FORBIDDEN"):
        CaptainFencedWorkItemScheduler(
            truth=truth, release_id="RC7.2", fencer=fencer,
            lifecycle=lifecycle, scheduler=TaskScheduler(truth, "RC7.2"),
            role_profiles={"test-executor": ["api", "FIELD_FULL_ACCESS"]})


def test_orphan_session_after_crash_blocks_duplicate_admission_after_cold_restart(tmp_path, monkeypatch):
    truth, _, owner, _, bridge = _ready_fixture(tmp_path)
    def crash(*args, **kwargs):
        raise KeyboardInterrupt("terminated between session allocation and WorkItem lease")
    monkeypatch.setattr(bridge.scheduler, "lease_task", crash)
    with pytest.raises(KeyboardInterrupt):
        _admit(bridge, owner, "WI-1")
    sessions = truth.query("rc72_worker_session", mission_id="M-1")
    assert len(sessions) == 1 and sessions[0]["state"] == "ACTIVE"
    assert truth.query("rc7_task", task_id="WI-1")[0]["state"] == "READY"
    replay = TruthRuntime(truth.store.path)
    fencer = CaptainDispatchFencer(replay, release_id="RC7.2")
    resumed = CaptainFencedWorkItemScheduler(
        truth=replay, release_id="RC7.2", fencer=fencer,
        lifecycle=WorkerLifecycleService(replay, release_id="RC7.2"),
        scheduler=TaskScheduler(replay, "RC7.2"),
        role_profiles={"test-executor": ["api", "tool:api"]})
    with pytest.raises(CaptainSchedulingError, match="PRIOR_SESSION_RECOVERY_REQUIRED"):
        _admit(resumed, owner, "WI-1")
    assert len(replay.query("rc72_worker_session", mission_id="M-1")) == 1


def test_same_workitem_never_has_two_fresh_workers(tmp_path):
    truth, _, owner, _, bridge = _ready_fixture(tmp_path)
    first = _admit(bridge, owner, "WI-1")
    with pytest.raises(CaptainSchedulingError, match="WORKITEM_NOT_READY"):
        _admit(bridge, owner, "WI-1")
    assert len(truth.query("rc72_worker_session", mission_id="M-1")) == 1
    assert truth.query("rc7_task", task_id="WI-1")[0]["lease_owner"] == first.worker_id


def test_captain_handoff_controls_next_etu_without_replaying_old_work(tmp_path):
    truth, fencer, owner, lifecycle, bridge = _ready_fixture(tmp_path)
    first = _admit(bridge, owner, "WI-1")
    cp = fencer.prepare_handoff(
        mission_id="M-1", team_id="TEAM-1", captain_session_id="CAP-A",
        lease_id=owner["lease_id"], lifecycle=lifecycle,
        current_node_refs=["N7_EXECUTION"], latest_delivery_refs=[],
        latest_gate_refs=[], next_workitem_ids=["WI-2"])
    with pytest.raises(ContractError, match="NOT_ACTIVE"):
        _admit(bridge, owner, "WI-2")
    next_owner = fencer.takeover(
        mission_id="M-1", team_id="TEAM-1",
        checkpoint_id=cp.checkpoint_id,
        new_captain_session_id="CAP-B", lifecycle=lifecycle)
    second = _admit(bridge, next_owner, "WI-2")
    assert second.captain_generation == 2
    assert first.worker_id != second.worker_id
    assert truth.query("rc7_task", task_id="WI-1")[0]["lease_owner"] == first.worker_id
    assert len(truth.query("rc72_worker_session", mission_id="M-1")) == 2


def _competing_dispatch(path, owner, index):
    truth = TruthRuntime(path)
    bridge = CaptainFencedWorkItemScheduler(
        truth=truth, release_id="RC7.2",
        fencer=CaptainDispatchFencer(truth, release_id="RC7.2"),
        lifecycle=WorkerLifecycleService(truth, release_id="RC7.2"),
        scheduler=TaskScheduler(truth, "RC7.2"),
        role_profiles={"test-executor": ["api", "tool:api"]})
    try:
        _admit(bridge, owner, "WI-1")
        return "ADMITTED"
    except ContractError:
        return "FENCED"


def test_multiprocess_same_workitem_contention_cannot_duplicate_worker(tmp_path):
    truth, _, owner, _, _ = _ready_fixture(tmp_path)
    ctx = multiprocessing.get_context("spawn")
    with ctx.Pool(processes=2) as pool:
        outcomes = pool.starmap(_competing_dispatch, [
            (str(truth.store.path), owner, 1), (str(truth.store.path), owner, 2)])
    assert sorted(outcomes) == ["ADMITTED", "FENCED"]
    cold = TruthRuntime(truth.store.path)
    assert len(cold.query("rc72_worker_session", mission_id="M-1")) == 1
    assert cold.query("rc7_task", task_id="WI-1")[0]["state"] == "LEASED"



def test_orphan_without_any_authority_or_business_effect_can_be_recovered_from_r1(tmp_path, monkeypatch):
    truth, _, owner, _, bridge = _ready_fixture(tmp_path)
    def crash(*args, **kwargs):
        raise KeyboardInterrupt("simulated pre-lease crash")
    monkeypatch.setattr(bridge.scheduler, "lease_task", crash)
    with pytest.raises(KeyboardInterrupt):
        _admit(bridge, owner, "WI-1")
    old = truth.query("rc72_worker_session", mission_id="M-1")[0]
    replay = TruthRuntime(truth.store.path)
    recovered = CaptainFencedWorkItemScheduler(
        truth=replay, release_id="RC7.2",
        fencer=CaptainDispatchFencer(replay, release_id="RC7.2"),
        lifecycle=WorkerLifecycleService(replay, release_id="RC7.2"),
        scheduler=TaskScheduler(replay, "RC7.2"),
        role_profiles={"test-executor": ["api", "tool:api"]})
    checkpoint = recovered.recover_unleased_orphan(
        mission_id="M-1", team_id="TEAM-1",
        captain_session_id="CAP-A", captain_lease_id=owner["lease_id"],
        workitem_id="WI-1", session_id=old["session_id"])
    assert checkpoint.session_id == old["session_id"]
    closed = replay.query("rc72_worker_session", session_id=old["session_id"])[0]
    assert closed["state"] == "CLOSED"
    assert closed["close_reason"] == "ORPHAN_BEFORE_WORKITEM_LEASE_VERIFIED"
    successor = _admit(recovered, owner, "WI-1")
    assert successor.session_id != old["session_id"]
    assert successor.worker_id != old["worker_id"]
    child = replay.query("rc72_worker_session", session_id=successor.session_id)[0]
    assert child["parent_session_id"] == old["session_id"]
    assert replay.query("rc7_task", task_id="WI-1")[0]["lease_owner"] == successor.worker_id


def test_orphan_with_any_runtime_assignment_cannot_be_silently_recovered(tmp_path, monkeypatch):
    truth, _, owner, lifecycle, bridge = _ready_fixture(tmp_path)
    def crash(*args, **kwargs):
        raise KeyboardInterrupt("simulated pre-lease crash")
    monkeypatch.setattr(bridge.scheduler, "lease_task", crash)
    with pytest.raises(KeyboardInterrupt):
        _admit(bridge, owner, "WI-1")
    session = truth.query("rc72_worker_session", mission_id="M-1")[0]
    # Represents an unconsumed launch/authority signal. No orphan release can
    # presume an external process did not perform business I/O.
    lifecycle._update_session(session, runtime_assignment_id="DSH-UNRESOLVED")
    with pytest.raises(CaptainSchedulingError, match="AUTHORITY_OR_DSH_OBSERVED"):
        bridge.recover_unleased_orphan(
            mission_id="M-1", team_id="TEAM-1",
            captain_session_id="CAP-A", captain_lease_id=owner["lease_id"],
            workitem_id="WI-1", session_id=session["session_id"])
    assert truth.query("rc72_worker_session", session_id=session["session_id"])[0]["state"] == "ACTIVE"


def test_orphan_recovery_rejects_wrong_captain_without_mutating_r1(tmp_path, monkeypatch):
    truth, _, owner, _, bridge = _ready_fixture(tmp_path)
    monkeypatch.setattr(bridge.scheduler, "lease_task",
                        lambda *a, **kw: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        _admit(bridge, owner, "WI-1")
    session = truth.query("rc72_worker_session", mission_id="M-1")[0]
    before = truth.store.path.read_bytes()
    with pytest.raises(ContractError, match="FENCED"):
        bridge.recover_unleased_orphan(
            mission_id="M-1", team_id="TEAM-1",
            captain_session_id="CAP-OTHER", captain_lease_id=owner["lease_id"],
            workitem_id="WI-1", session_id=session["session_id"])
    assert truth.store.path.read_bytes() == before



def _seed_n7_plan(truth, *, bound_etu="ETU-1", create_snapshot=True):
    from rc7_runtime.rc72_n7_execution_planning import install_rc72_n7_execution_planning_overlay
    from rc7_runtime.rc72_decomposition_truth import install_rc72_decomposition_truth_overlay

    install_rc72_n7_execution_planning_overlay()
    install_rc72_decomposition_truth_overlay()
    if create_snapshot:
        truth.append_atomic("RC72_DECOMPOSITION_SNAPSHOT_UPSERTED", {
            "snapshot_id": "PLAN-1", "mission_id": "M-1",
            "release_id": "RC7.2", "release_batch_id": "RB-1",
            "current_node": "N7_EXECUTION", "config_version": "test",
            "obligation_ids": ["TO-1"], "case_ids": ["TC-1", "TC-2"],
            "completed_case_ids": [], "etu_ids": ["ETU-1", "ETU-2"],
            "planning_cases": [], "coverage_gaps": [], "execution_history": [],
            "planning_signals": [], "coverage_routes": [],
            "priority_weights": {}, "obligation_priorities": {},
            "priority_explanations": {}, "replan_reasons": {},
            "created_at": 1, "artifact_version": 1,
        })
    truth.append_atomic("RC72_N7_EXECUTION_PLAN_UPSERTED", {
        "plan_id": "N7PLAN-TEST", "release_id": "RC7.2",
        "source_commit": "0" * 40, "release_batch_id": "RB-1",
        "mission_id": "M-1", "snapshot_id": "PLAN-1",
        "input_digest": "hash-of-reviewed-inputs", "status": "PLANNED",
        "items": [{
            "case_id": "TC-1", "contract_id": "N6-C1",
            "admission_id": "N7-ADMIT-1", "etu_id": bound_etu,
            "workitem_id": "WI-1", "input_artifact_refs": [],
        }],
        "artifact_version": 1,
    })


def _mark_n7_case_task(truth):
    scheduler = TaskScheduler(truth, "RC7.2")
    row = truth.query("rc7_task", task_id="WI-1")[0]
    task = scheduler._task_from_row(row)
    task.task_type = "RC72_CASE_EXECUTION"
    scheduler._persist_task(task, row["artifact_version"] + 1)


def test_formal_n7_rejects_generic_executor_role_before_creating_worker(tmp_path):
    truth, _, owner, _, bridge = _ready_fixture(tmp_path)
    _mark_n7_case_task(truth)
    _seed_n7_plan(truth)
    with pytest.raises(CaptainSchedulingError, match="N7_ROLE_SCOPE_MISMATCH"):
        _admit(bridge, owner, "WI-1", role="test-executor")
    assert truth.query("rc72_worker_session", mission_id="M-1") == []
    assert truth.query("rc72_captain_etu_admission", mission_id="M-1") == []


def test_n7_case_workitem_requires_canonical_planning_lineage(tmp_path):
    truth, _, owner, _, bridge = _ready_fixture(tmp_path)
    _mark_n7_case_task(truth)
    with pytest.raises(CaptainSchedulingError, match="N7_PLAN_ITEM_NOT_UNIQUE"):
        _admit(bridge, owner, "WI-1", role="L3_EXECUTE")
    assert truth.query("rc72_worker_session", mission_id="M-1") == []


def test_n7_case_cannot_dispatch_using_wrong_etu_from_same_mission(tmp_path):
    truth, _, owner, _, bridge = _ready_fixture(tmp_path)
    _mark_n7_case_task(truth)
    _seed_n7_plan(truth, bound_etu="ETU-2")
    with pytest.raises(CaptainSchedulingError, match="N7_CANONICAL_LINEAGE_MISMATCH"):
        _admit(bridge, owner, "WI-1", role="L3_EXECUTE")
    assert truth.query("rc7_task", task_id="WI-1")[0]["state"] == "READY"
    assert truth.query("rc72_worker_session", mission_id="M-1") == []


def test_n7_case_plan_snapshot_must_exist_before_worker_is_allocated(tmp_path):
    truth, _, owner, _, bridge = _ready_fixture(tmp_path)
    _mark_n7_case_task(truth)
    _seed_n7_plan(truth, create_snapshot=False)
    with pytest.raises(CaptainSchedulingError, match="N7_SNAPSHOT_NOT_VERIFIED"):
        _admit(bridge, owner, "WI-1", role="L3_EXECUTE")
    assert truth.query("rc72_worker_session", mission_id="M-1") == []


def test_n7_case_canonical_plan_and_snapshot_allow_fresh_worker(tmp_path):
    truth, _, owner, _, bridge = _ready_fixture(tmp_path)
    _mark_n7_case_task(truth)
    _seed_n7_plan(truth)
    admitted = _admit(bridge, owner, "WI-1", role="L3_EXECUTE")
    assert admitted.state == "LEASED_AWAITING_SIGNED_AUTHORITY_AND_DSH"
    assert len(truth.query("rc72_worker_session", mission_id="M-1")) == 1
    assert truth.query("rc7_task", task_id="WI-1")[0]["lease_owner"] == admitted.worker_id



def test_cross_mission_artifact_cannot_be_an_etu_dispatch_input(tmp_path):
    from rc7_runtime.models import Artifact
    from rc7_runtime.truth_overlay import append_entity

    truth, _, owner, _, bridge = _ready_fixture(tmp_path)
    append_entity(truth, Artifact(
        artifact_id="FOREIGN-INPUT", mission_id="M-OTHER",
        artifact_type="source-ref", producer_task_id="WI-OTHER",
        content_ref="file://untrusted-other-mission"),
        release_id="RC7.2")
    scheduler = TaskScheduler(truth, "RC7.2")
    row = truth.query("rc7_task", task_id="WI-1")[0]
    task = scheduler._task_from_row(row)
    task.input_artifact_refs = ["FOREIGN-INPUT"]
    scheduler._persist_task(task, row["artifact_version"] + 1)
    with pytest.raises(CaptainSchedulingError, match="INPUT_MISSION_MISMATCH"):
        _admit(bridge, owner, "WI-1")
    assert truth.query("rc72_worker_session", mission_id="M-1") == []



def test_raw_r1_capability_event_blocks_orphan_recovery_even_without_tool_call(tmp_path, monkeypatch):
    from rc7_runtime.rc72_capability_broker import install_rc72_capability_overlay

    truth, _, owner, _, bridge = _ready_fixture(tmp_path)
    monkeypatch.setattr(bridge.scheduler, "lease_task",
                        lambda *a, **kw: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        _admit(bridge, owner, "WI-1")
    session = truth.query("rc72_worker_session", mission_id="M-1")[0]
    install_rc72_capability_overlay()
    truth.append_atomic("RC72_CAPABILITY_REQUEST_UPSERTED", {
        "request_id": "CAP-UNKNOWN-1", "release_id": "RC7.2",
        "mission_id": "M-1", "workitem_id": "WI-1",
        "attempt_id": "A-UNKNOWN", "worker_id": session["worker_id"],
        "parent_task_lease_id": "TL-UNKNOWN",
        "requested_capability": "db-write", "reason": "unknown external authority",
        "state": "REQUESTED", "created_at": 1, "artifact_version": 1,
    })
    cold = TruthRuntime(truth.store.path)
    bridge = CaptainFencedWorkItemScheduler(
        truth=cold, release_id="RC7.2",
        fencer=CaptainDispatchFencer(cold, release_id="RC7.2"),
        lifecycle=WorkerLifecycleService(cold, release_id="RC7.2"),
        scheduler=TaskScheduler(cold, "RC7.2"),
        role_profiles={"test-executor": ["api", "tool:api"]})
    with pytest.raises(CaptainSchedulingError, match="R1_PROVENANCE_UNKNOWN"):
        bridge.recover_unleased_orphan(
            mission_id="M-1", team_id="TEAM-1",
            captain_session_id="CAP-A", captain_lease_id=owner["lease_id"],
            workitem_id="WI-1", session_id=session["session_id"])
    assert cold.query("rc72_worker_session", session_id=session["session_id"])[0]["state"] == "ACTIVE"



def test_stale_dependency_rejects_ready_task_before_worker_allocation(tmp_path):
    truth, _, owner, _, bridge = _ready_fixture(tmp_path)
    scheduler = TaskScheduler(truth, "RC7.2")
    row = truth.query("rc7_task", task_id="WI-1")[0]
    task = scheduler._task_from_row(row)
    task.dependency_task_ids = ["WI-2"]
    scheduler._persist_task(task, row["artifact_version"] + 1)
    with pytest.raises(CaptainSchedulingError, match="DEPENDENCY_NOT_PASS"):
        _admit(bridge, owner, "WI-1")
    assert truth.query("rc72_worker_session", mission_id="M-1") == []


def test_stale_etu_blocks_ready_workitem_even_when_role_has_all_capabilities(tmp_path):
    truth, _, owner, _, bridge = _ready_fixture(tmp_path)
    etu = dict(truth.query("rc72_etu", etu_id="ETU-1")[0])
    etu.pop("artifact_type", None)
    etu["artifact_version"] += 1
    etu["state"] = "STALE"
    truth.append_atomic("RC72_ETU_UPSERTED", etu)
    with pytest.raises(CaptainSchedulingError, match="ETU_NOT_EXECUTABLE"):
        _admit(bridge, owner, "WI-1")
    assert truth.query("rc72_worker_session", mission_id="M-1") == []



def test_two_consecutive_prelease_process_crashes_can_recover_as_linear_fresh_worker_chain(tmp_path, monkeypatch):
    truth, _, owner, _, bridge = _ready_fixture(tmp_path)
    original_lease = bridge.scheduler.lease_task
    def fail_before_task_lease(*args, **kwargs):
        raise KeyboardInterrupt("process crash before any TaskLease")
    monkeypatch.setattr(bridge.scheduler, "lease_task", fail_before_task_lease)
    old_sessions = []
    for generation in range(2):
        with pytest.raises(KeyboardInterrupt):
            _admit(bridge, owner, "WI-1")
        current = [s for s in truth.query("rc72_worker_session", mission_id="M-1")
                   if s["state"] == "ACTIVE"]
        assert len(current) == 1
        old_sessions.append(current[0])
        checkpoint = bridge.recover_unleased_orphan(
            mission_id="M-1", team_id="TEAM-1",
            captain_session_id="CAP-A", captain_lease_id=owner["lease_id"],
            workitem_id="WI-1", session_id=current[0]["session_id"])
        assert checkpoint.session_id == current[0]["session_id"]
        assert truth.query("rc7_task", task_id="WI-1")[0]["state"] == "READY"
    monkeypatch.setattr(bridge.scheduler, "lease_task", original_lease)
    admitted = _admit(bridge, owner, "WI-1")
    chain = {s["session_id"]: s for s in truth.query("rc72_worker_session", mission_id="M-1")}
    assert len(chain) == 3
    assert admitted.session_id not in {s["session_id"] for s in old_sessions}
    assert chain[admitted.session_id]["parent_session_id"] == old_sessions[1]["session_id"]
    assert chain[old_sessions[1]["session_id"]]["parent_session_id"] == old_sessions[0]["session_id"]
    assert chain[old_sessions[0]["session_id"]]["parent_session_id"] is None
    assert len([s for s in chain.values() if s["state"] == "ACTIVE"]) == 1


def test_recovered_prelease_worker_cannot_change_professional_role(tmp_path, monkeypatch):
    truth, fencer, owner, lifecycle, bridge = _ready_fixture(tmp_path)
    monkeypatch.setattr(bridge.scheduler, "lease_task",
                        lambda *a, **kw: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        _admit(bridge, owner, "WI-1")
    session = truth.query("rc72_worker_session", mission_id="M-1")[0]
    bridge.recover_unleased_orphan(
        mission_id="M-1", team_id="TEAM-1",
        captain_session_id="CAP-A", captain_lease_id=owner["lease_id"],
        workitem_id="WI-1", session_id=session["session_id"])
    altered = CaptainFencedWorkItemScheduler(
        truth=truth, release_id="RC7.2", fencer=fencer,
        lifecycle=lifecycle, scheduler=TaskScheduler(truth, "RC7.2"),
        role_profiles={
            "test-executor": ["api", "tool:api"],
            "performance-executor": ["api", "tool:api"],
        })
    with pytest.raises(CaptainSchedulingError, match="RECOVERY_SCOPE_DRIFT"):
        altered.dispatch_etu(
            mission_id="M-1", team_id="TEAM-1",
            captain_session_id="CAP-A", captain_lease_id=owner["lease_id"],
            role="performance-executor", etu_id="ETU-1", workitem_id="WI-1",
            canonical_refs=_refs("ETU-1"))
    assert truth.query("rc7_task", task_id="WI-1")[0]["state"] == "READY"
    assert len(truth.query("rc72_worker_session", mission_id="M-1")) == 1
