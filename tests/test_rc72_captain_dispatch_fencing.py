"""C07 Captain fencing: real R1/WorkerLifecycle contracts, no bank/DSH claims."""
import multiprocessing

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import ContractError
from rc7_runtime.rc72_captain_dispatch_fencing import CaptainDispatchFencer
from test_rc72_phase5_worker_lifecycle_contract import _runtime


def _competing_captain(path, index):
    """Fresh interpreter/process loads the same on-disk canonical R1."""
    truth = TruthRuntime(path)
    gate = CaptainDispatchFencer(truth, release_id="RC7.2")
    try:
        gate.acquire_initial(
            mission_id="M-1", team_id="TEAM-1",
            captain_session_id="CAPTAIN-%s" % index)
        return "WON"
    except ContractError:
        return "FENCED"


def test_single_captain_owner_survives_cold_replay(tmp_path):
    truth, _, lifecycle = _runtime(tmp_path)
    gate = CaptainDispatchFencer(truth, release_id="RC7.2")
    owner = gate.acquire_initial(
        mission_id="M-1", team_id="TEAM-1", captain_session_id="CAPTAIN-A")
    assert gate.assert_owner(
        mission_id="M-1", lease_id=owner["lease_id"],
        captain_session_id="CAPTAIN-A")["state"] == "ACTIVE"

    cold = TruthRuntime(truth.store.path)
    other = CaptainDispatchFencer(cold, release_id="RC7.2")
    with pytest.raises(ContractError, match="EXISTING_OWNER"):
        other.acquire_initial(
            mission_id="M-1", team_id="TEAM-1", captain_session_id="CAPTAIN-B")
    with pytest.raises(ContractError, match="FENCED"):
        other.assert_owner(
            mission_id="M-1", lease_id=owner["lease_id"],
            captain_session_id="CAPTAIN-B")
    assert other.assert_owner(
        mission_id="M-1", lease_id=owner["lease_id"],
        captain_session_id="CAPTAIN-A")["state"] == "ACTIVE"


def test_handoff_quiesces_old_captain_and_fences_old_generation(tmp_path):
    truth, _, lifecycle = _runtime(tmp_path)
    gate = CaptainDispatchFencer(truth, release_id="RC7.2")
    first = gate.acquire_initial(
        mission_id="M-1", team_id="TEAM-1", captain_session_id="CAPTAIN-A")
    checkpoint = gate.prepare_handoff(
        mission_id="M-1", lease_id=first["lease_id"],
        captain_session_id="CAPTAIN-A", team_id="TEAM-1",
        lifecycle=lifecycle, current_node_refs=["N7_EXECUTION"],
        latest_delivery_refs=[], latest_gate_refs=[],
        next_workitem_ids=["WI-1"])

    with pytest.raises(ContractError, match="NOT_ACTIVE"):
        gate.assert_owner(
            mission_id="M-1", lease_id=first["lease_id"],
            captain_session_id="CAPTAIN-A")

    restarted_truth = TruthRuntime(truth.store.path)
    restarted = CaptainDispatchFencer(restarted_truth, release_id="RC7.2")
    from rc7_runtime.rc72_worker_lifecycle import WorkerLifecycleService
    restarted_lifecycle = WorkerLifecycleService(restarted_truth, release_id="RC7.2",
                                                  policy=lifecycle.policy)
    successor = restarted.takeover(
        mission_id="M-1", team_id="TEAM-1",
        checkpoint_id=checkpoint.checkpoint_id,
        new_captain_session_id="CAPTAIN-B",
        lifecycle=restarted_lifecycle)
    assert successor["generation"] == 2
    assert successor["parent_lease_id"] == first["lease_id"]
    assert successor["captain_session_id"] == "CAPTAIN-B"
    assert restarted.assert_owner(
        mission_id="M-1", lease_id=successor["lease_id"],
        captain_session_id="CAPTAIN-B")["state"] == "ACTIVE"
    with pytest.raises(ContractError, match="FENCED"):
        gate.assert_owner(
            mission_id="M-1", lease_id=first["lease_id"],
            captain_session_id="CAPTAIN-A")
    with pytest.raises(ContractError, match="CHECKPOINT_REQUIRED"):
        restarted.takeover(
            mission_id="M-1", team_id="TEAM-1",
            checkpoint_id=checkpoint.checkpoint_id,
            new_captain_session_id="CAPTAIN-C", lifecycle=restarted_lifecycle)


def test_crash_during_handoff_fails_closed_without_dispatch(tmp_path, monkeypatch):
    truth, _, lifecycle = _runtime(tmp_path)
    gate = CaptainDispatchFencer(truth, release_id="RC7.2")
    first = gate.acquire_initial(
        mission_id="M-1", team_id="TEAM-1", captain_session_id="CAPTAIN-A")

    def crash(**_kwargs):
        raise KeyboardInterrupt("simulated process exit before checkpoint persisted")

    monkeypatch.setattr(lifecycle, "create_captain_handoff", crash)
    with pytest.raises(KeyboardInterrupt):
        gate.prepare_handoff(
            mission_id="M-1", lease_id=first["lease_id"],
            captain_session_id="CAPTAIN-A", team_id="TEAM-1",
            lifecycle=lifecycle, current_node_refs=["N7_EXECUTION"],
            latest_delivery_refs=[], latest_gate_refs=[],
            next_workitem_ids=["WI-1"])
    cold = CaptainDispatchFencer(TruthRuntime(truth.store.path), release_id="RC7.2")
    with pytest.raises(ContractError, match="NOT_ACTIVE"):
        cold.assert_owner(
            mission_id="M-1", lease_id=first["lease_id"],
            captain_session_id="CAPTAIN-A")
    with pytest.raises(ContractError, match="EXISTING_OWNER_REQUIRES_HANDOFF"):
        cold.acquire_initial(
            mission_id="M-1", team_id="TEAM-1", captain_session_id="CAPTAIN-C")


def test_expired_owner_cannot_renew_or_grant_replacement_without_handoff(tmp_path, monkeypatch):
    import rc7_runtime.rc72_captain_dispatch_fencing as fencing
    truth, _, _ = _runtime(tmp_path)
    gate = CaptainDispatchFencer(truth, release_id="RC7.2")
    owner = gate.acquire_initial(
        mission_id="M-1", team_id="TEAM-1",
        captain_session_id="CAPTAIN-A", ttl_seconds=10)
    monkeypatch.setattr(fencing, "_now", lambda: owner["expires_at"] + 1)
    with pytest.raises(ContractError, match="LEASE_EXPIRED"):
        gate.assert_owner(mission_id="M-1", lease_id=owner["lease_id"],
                          captain_session_id="CAPTAIN-A")
    with pytest.raises(ContractError, match="NOT_ACTIVE"):
        gate.heartbeat(mission_id="M-1", lease_id=owner["lease_id"],
                       captain_session_id="CAPTAIN-A")
    with pytest.raises(ContractError, match="EXISTING_OWNER_REQUIRES_HANDOFF"):
        gate.acquire_initial(
            mission_id="M-1", team_id="TEAM-1", captain_session_id="CAPTAIN-B")


def test_different_os_processes_cannot_acquire_two_captains(tmp_path):
    truth, _, _ = _runtime(tmp_path)
    ctx = multiprocessing.get_context("spawn")
    with ctx.Pool(processes=3) as pool:
        results = pool.starmap(
            _competing_captain, [(str(truth.store.path), idx) for idx in range(3)])
    assert results.count("WON") == 1
    assert results.count("FENCED") == 2
    cold = CaptainDispatchFencer(TruthRuntime(truth.store.path), release_id="RC7.2")
    owners = cold._rows("M-1")
    assert len(owners) == 1 and owners[0]["state"] == "ACTIVE"



def test_lease_expires_on_exact_ttl_boundary_not_after_one_extra_second(tmp_path, monkeypatch):
    import rc7_runtime.rc72_captain_dispatch_fencing as fencing

    truth, _, _ = _runtime(tmp_path)
    gate = CaptainDispatchFencer(truth, release_id="RC7.2")
    owner = gate.acquire_initial(
        mission_id="M-1", team_id="TEAM-1",
        captain_session_id="CAPTAIN-A", ttl_seconds=10)
    monkeypatch.setattr(fencing, "_now", lambda: owner["expires_at"])
    with pytest.raises(ContractError, match="LEASE_EXPIRED"):
        gate.assert_owner(
            mission_id="M-1", lease_id=owner["lease_id"],
            captain_session_id="CAPTAIN-A")
    cold = CaptainDispatchFencer(TruthRuntime(truth.store.path), release_id="RC7.2")
    assert cold._latest("M-1")["state"] == "EXPIRED"
    with pytest.raises(ContractError, match="NOT_ACTIVE"):
        cold.assert_owner(
            mission_id="M-1", lease_id=owner["lease_id"],
            captain_session_id="CAPTAIN-A")



@pytest.mark.parametrize("state", ["LEASED", "RUNNING", "OUTPUT_PRODUCED"])
def test_first_captain_must_not_adopt_legacy_worker_with_active_uncheckpointed_work(
        tmp_path, state):
    from rc7_runtime.control_plane import TaskScheduler
    from rc7_runtime.models import TaskStatus

    truth, _, _ = _runtime(tmp_path)
    scheduler = TaskScheduler(truth, "RC7.2")
    original = truth.query("rc7_task", task_id="WI-1")[0]
    task = scheduler._task_from_row(original)
    task.state = TaskStatus(state)
    task.lease_owner = "LEGACY-WORKER-UNFENCED"
    scheduler._persist_task(task, original["artifact_version"] + 1)

    before = list(truth.store.iter_raw())
    with pytest.raises(
            ContractError,
            match="CAPTAIN_BOOTSTRAP_UNGOVERNED_ACTIVE_WORK_RECONCILIATION_REQUIRED"):
        CaptainDispatchFencer(truth, release_id="RC7.2").acquire_initial(
            mission_id="M-1", team_id="TEAM-1",
            captain_session_id="CAPTAIN-NEW")
    assert list(truth.store.iter_raw()) == before
    assert truth.query("rc72_captain_dispatch_lease", mission_id="M-1") == []



def test_historical_signed_preflight_failed_requires_independent_hmac_file_proof(
        tmp_path, monkeypatch):
    """A row's boolean is never enough to permit Captain handoff."""
    from test_rc72_n8_execution_diagnosis import _failure

    truth, preparation, server, prepared = _failure(
        tmp_path, monkeypatch, mode="data")
    try:
        call = truth.query("rc72_n7_tool_dispatch",
                           attempt_id=prepared["attempt_id"])[0]
        assert call["state"] == "FAILED"
        trusted = CaptainDispatchFencer(
            truth, release_id="RC7.2", authority=preparation.authority)
        unbound = CaptainDispatchFencer(truth, release_id="RC7.2")
        assert trusted._certified_safe_tool_failure(call) is True
        assert unbound._certified_safe_tool_failure(call) is False
        forged = dict(call, no_effect_evidence_refs=["N7CHECK-FAKE"])
        assert trusted._certified_safe_tool_failure(forged) is False
        mismatched = dict(call, worker_id="WORKER-IMPOSTER")
        assert trusted._certified_safe_tool_failure(mismatched) is False
        original_events = list(truth.store.iter_raw())
        seen_effect = dict(
            event_type="RC72_N7_HTTP_CALL_UPSERTED",
            payload={"attempt_id": prepared["attempt_id"]})
        monkeypatch.setattr(
            truth.store, "iter_raw",
            lambda: iter(original_events + [seen_effect]))
        assert trusted._certified_safe_tool_failure(call) is False
    finally:
        server.shutdown()
        server.server_close()
