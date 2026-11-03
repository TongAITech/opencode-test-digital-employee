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
        role_profiles={"test-executor": ["api"], "quality-reviewer": ["filesystem"]})
    return truth, fencer, owner, lifecycle, bridge


def _admit(bridge, owner, task):
    return bridge.dispatch_etu(
        mission_id="M-1", team_id="TEAM-1",
        captain_session_id=owner["captain_session_id"],
        captain_lease_id=owner["lease_id"],
        role="test-executor", etu_id=task.replace("WI-", "ETU-"),
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


def test_insufficient_role_capability_is_deterministic_gap_without_session(tmp_path):
    truth, _, owner, _, bridge = _ready_fixture(tmp_path)
    with pytest.raises(CaptainSchedulingError, match="CAPABILITY_GAP"):
        bridge.dispatch_etu(
            mission_id="M-1", team_id="TEAM-1",
            captain_session_id="CAP-A", captain_lease_id=owner["lease_id"],
            role="quality-reviewer", etu_id="ETU-1", workitem_id="WI-1",
            canonical_refs=_refs("ETU-1"))
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
        role_profiles={"test-executor": ["api"]})
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
        role_profiles={"test-executor": ["api"]})
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
        role_profiles={"test-executor": ["api"]})
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
