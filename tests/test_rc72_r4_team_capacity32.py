"""R4-07: 32-member plugin configuration and safe active-worker admissions.

Source engineering tests only: real DSH plugin roster verification remains a
separate Field gate; no fake DSH member or model invocation is created here.
"""
import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import ContractError
from rc7_runtime.control_plane import TaskScheduler
from rc7_runtime.rc72_captain_dispatch_fencing import CaptainDispatchFencer
from rc7_runtime.rc72_captain_scheduling import (
    CaptainFencedWorkItemScheduler, CaptainSchedulingError)
from rc7_runtime.rc72_worker_lifecycle import WorkerLifecycleService
from rc7_runtime.rc72_agentteams_capacity import (
    NANMICODER_PLUGIN, LEGACY_TEAM_PLUGIN, OFFICIAL_TEAM_PLUGIN,
    TeamCapacityPolicy, proposed_plugin_config,
    verify_installed_plugin_capacity)
from test_rc72_captain_scheduling import _ready_fixture, _admit


def test_r4_target_is_32_with_independent_active_limit():
    policy = TeamCapacityPolicy()
    assert policy.team_member_capacity == 32
    assert policy.max_active_workers == 4
    assert TeamCapacityPolicy(32, 2).max_active_workers == 2


@pytest.mark.parametrize("members,active", [(0, 1), (33, 4), (32, 0),
                                            (32, 33), (4, 5), (True, 2)])
def test_bad_capacity_fails_without_clamping(members, active):
    with pytest.raises(ContractError, match="R4_"):
        TeamCapacityPolicy(members, active)


def test_target_plugin_proposal_does_not_modify_observed_config():
    existing = {"maxMembers": 8, "memberMaxDepth": 0, "toolPolicies": {"review": {}}}
    patch = proposed_plugin_config(NANMICODER_PLUGIN, existing)
    assert patch == {"maxMembers": 32, "memberMaxDepth": 0,
                     "toolPolicies": {"review": {}}}
    assert existing["maxMembers"] == 8
    with pytest.raises(ContractError, match="NOT_QUALIFIED"):
        verify_installed_plugin_capacity(
            plugin_name=NANMICODER_PLUGIN, plugin_version="0.1.29",
            observed_config=existing)
    verified = verify_installed_plugin_capacity(
        plugin_name=NANMICODER_PLUGIN, plugin_version="0.1.29",
        observed_config=patch)
    assert verified["team_member_capacity"] == 32
    assert verified["max_active_workers"] == 4
    assert verified["field_verified"] is False and verified["bank_final"] is False


def test_other_plugin_has_distinct_field_and_official_rejects_obsolete_field():
    assert proposed_plugin_config(LEGACY_TEAM_PLUGIN, {"maxTeammates": 8}) == {
        "maxTeammates": 32}
    with pytest.raises(ContractError, match="SUBAGENT_RUNTIME"):
        proposed_plugin_config(OFFICIAL_TEAM_PLUGIN, {"maxMembers": 8})
    with pytest.raises(ContractError, match="UNKNOWN"):
        proposed_plugin_config("dsh-unknown", {})


def test_unverified_version_bool_config_and_fake_observation_are_rejected():
    for observed in ({}, {"maxMembers": True}, {"maxMembers": "32"},
                     {"maxMembers": 8}):
        with pytest.raises(ContractError, match="NOT_QUALIFIED"):
            verify_installed_plugin_capacity(
                plugin_name=NANMICODER_PLUGIN,
                plugin_version="0.1.29", observed_config=observed)
    with pytest.raises(ContractError, match="VERSION_REQUIRED"):
        verify_installed_plugin_capacity(
            plugin_name=NANMICODER_PLUGIN, plugin_version="",
            observed_config={"maxMembers": 32})


def _bounded(tmp_path, active=1):
    truth, fencer, captain, lifecycle, _ = _ready_fixture(tmp_path)
    bridge = CaptainFencedWorkItemScheduler(
        truth=truth, release_id="RC7.2", fencer=fencer,
        lifecycle=lifecycle, scheduler=TaskScheduler(truth, "RC7.2"),
        role_profiles={"test-executor": ["api", "tool:api"]},
        capacity_policy=TeamCapacityPolicy(32, active))
    return truth, captain, bridge


def test_one_active_worker_causes_next_workitem_to_queue_without_r1_write(tmp_path):
    truth, captain, bridge = _bounded(tmp_path)
    first = _admit(bridge, captain, "WI-1")
    before = list(truth.store.iter_raw())
    with pytest.raises(CaptainSchedulingError, match="ACTIVE_CAPACITY_REACHED"):
        _admit(bridge, captain, "WI-2")
    assert list(truth.store.iter_raw()) == before
    assert len(truth.query("rc72_worker_session", mission_id="M-1")) == 1
    assert truth.query("rc7_task", task_id="WI-2")[0]["state"] == "READY"
    assert first.worker_id == truth.query("rc7_task", task_id="WI-1")[0]["lease_owner"]


def test_cold_restart_does_not_erase_capacity_or_replay_workitem(tmp_path):
    truth, captain, bridge = _bounded(tmp_path)
    _admit(bridge, captain, "WI-1")
    cold = TruthRuntime(truth.store.path)
    fresh = CaptainFencedWorkItemScheduler(
        truth=cold, release_id="RC7.2",
        fencer=CaptainDispatchFencer(cold, release_id="RC7.2"),
        lifecycle=WorkerLifecycleService(cold, release_id="RC7.2"),
        scheduler=TaskScheduler(cold, "RC7.2"),
        role_profiles={"test-executor": ["api", "tool:api"]},
        capacity_policy=TeamCapacityPolicy(32, 1))
    before = list(cold.store.iter_raw())
    with pytest.raises(CaptainSchedulingError, match="ACTIVE_CAPACITY_REACHED"):
        _admit(fresh, captain, "WI-2")
    assert list(cold.store.iter_raw()) == before


def test_two_active_slots_allow_two_distinct_workers(tmp_path):
    truth, captain, bridge = _bounded(tmp_path, 2)
    first = _admit(bridge, captain, "WI-1")
    second = _admit(bridge, captain, "WI-2")
    assert first.worker_id != second.worker_id
    assert len(truth.query("rc72_worker_session", mission_id="M-1")) == 2


def _r4_batch_inputs():
    from test_rc72_phase5_worker_lifecycle_contract import _refs
    return [
        {"workitem_id": "WI-1", "etu_id": "ETU-1",
         "role": "test-executor", "canonical_refs": _refs("ETU-1")},
        {"workitem_id": "WI-2", "etu_id": "ETU-2",
         "role": "test-executor", "canonical_refs": _refs("ETU-2")},
    ]


def test_batch_fills_active_capacity_in_priority_order_and_preserves_ready_queue(tmp_path):
    truth, captain, bridge = _bounded(tmp_path, 1)
    arguments = dict(mission_id="M-1", team_id="TEAM-1",
                     captain_session_id=captain["captain_session_id"],
                     captain_lease_id=captain["lease_id"],
                     workitems=_r4_batch_inputs())
    original_ready = [item.task_id for item in bridge.scheduler.ready_tasks("M-1")]
    assert set(original_ready) == {"WI-1", "WI-2"}
    first = bridge.dispatch_ready_batch(**arguments)
    assert [a.workitem_id for a in first.admitted] == original_ready[:1]
    assert first.queued_workitem_ids == tuple(original_ready[1:])
    assert truth.query("rc7_task", task_id=original_ready[1])[0]["state"] == "READY"
    before = list(truth.store.iter_raw())
    # Cold/warm repeated planning cannot write a second Worker or duplicate I/O.
    only_queued = dict(arguments, workitems=[
        item for item in arguments["workitems"]
        if item["workitem_id"] in first.queued_workitem_ids])
    second = bridge.dispatch_ready_batch(**only_queued)
    assert second.admitted == () and second.queued_workitem_ids == tuple(original_ready[1:])
    assert list(truth.store.iter_raw()) == before


def test_invalid_batch_rejected_before_first_r1_write(tmp_path):
    truth, captain, bridge = _bounded(tmp_path, 2)
    before = list(truth.store.iter_raw())
    inputs = _r4_batch_inputs()
    base = dict(mission_id="M-1", team_id="TEAM-1",
                captain_session_id=captain["captain_session_id"],
                captain_lease_id=captain["lease_id"])
    for items, reason in (([inputs[0], inputs[0]], "DUPLICATE"),
                          ([dict(inputs[0], extra="untrusted")], "ITEM_INVALID"),
                          ([], "SIZE_INVALID"),
                          ([dict(inputs[0], workitem_id="NOT-READY")],
                           "WORKITEM_NOT_READY")):
        with pytest.raises(CaptainSchedulingError, match=reason):
            bridge.dispatch_ready_batch(workitems=items, **base)
    assert list(truth.store.iter_raw()) == before


def test_two_slot_batch_admits_two_signed_r1_worker_sessions(tmp_path):
    truth, captain, bridge = _bounded(tmp_path, 2)
    batch = bridge.dispatch_ready_batch(
        mission_id="M-1", team_id="TEAM-1",
        captain_session_id=captain["captain_session_id"],
        captain_lease_id=captain["lease_id"],
        workitems=_r4_batch_inputs())
    assert len(batch.admitted) == 2 and batch.queued_workitem_ids == ()
    assert len({a.session_id for a in batch.admitted}) == 2
    assert len(truth.query("rc72_worker_session", mission_id="M-1")) == 2
    assert not truth.query("execution_attempt", mission_id="M-1")
