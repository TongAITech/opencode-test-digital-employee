"""RC7.2 real N7 planner -> Captain-fenced scheduler -> signed preparation.

Tests run actual R1/TaskScheduler/authority/DataLease services, not a model or
SUT; an admitted preparation is *not* a completed DSH/Bank execution.
"""
from dataclasses import replace

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.control_plane import TaskScheduler
from rc7_runtime.models import ContractError
from rc7_runtime.rc72_captain_dispatch_fencing import CaptainDispatchFencer
from rc7_runtime.rc72_captain_scheduling import CaptainFencedWorkItemScheduler
from rc7_runtime.rc72_worker_lifecycle import WorkerLifecycleService

from test_rc72_n7_execution_preparation import _setup, _service
from rc72_n2_test_support import MISSION, RELEASE


def _fenced(tmp_path, monkeypatch):
    truth, plan = _setup(tmp_path, monkeypatch)
    item = plan["items"][0]
    etu = truth.query("rc72_etu", etu_id=item["etu_id"])[0]
    contract = truth.query("rc72_n6_executable_contract", contract_id=item["contract_id"])[0]
    task = truth.query("rc7_task", task_id=item["workitem_id"])[0]
    role = etu["test_level"] + "_EXECUTE"
    capabilities = sorted(set(task["required_capabilities"] + etu["required_capabilities"]))
    lifecycle = WorkerLifecycleService(truth, release_id=RELEASE)
    captain = CaptainDispatchFencer(truth, release_id=RELEASE)
    owner = captain.acquire_initial(
        mission_id=MISSION, team_id="TEAM-" + MISSION,
        captain_session_id="CAPTAIN-N7-A")
    scheduler = CaptainFencedWorkItemScheduler(
        truth=truth, release_id=RELEASE, fencer=captain,
        lifecycle=lifecycle, scheduler=TaskScheduler(truth, RELEASE),
        role_profiles={role: capabilities})
    dispatch = scheduler.dispatch_etu(
        mission_id=MISSION, team_id="TEAM-" + MISSION,
        captain_session_id="CAPTAIN-N7-A", captain_lease_id=owner["lease_id"],
        role=role, etu_id=item["etu_id"], workitem_id=item["workitem_id"],
        canonical_refs={
            "etu_refs": [item["etu_id"]],
            "executable_contract_refs": [item["contract_id"]],
            "data_refs": [r["data_ref"] for r in contract["data_refs"]],
        })
    return truth, plan, item, captain, lifecycle, owner, dispatch


def test_captain_fenced_admission_reuses_exact_worker_for_real_signed_n7_preparation(tmp_path, monkeypatch):
    truth, plan, item, _, _, owner, dispatch = _fenced(tmp_path, monkeypatch)
    before = truth.query("rc72_worker_session", mission_id=MISSION)
    assert len(before) == 1
    assert dispatch.worker_id == before[0]["worker_id"]
    assert dispatch.session_id == before[0]["session_id"]
    assert truth.query("rc7_task", task_id=item["workitem_id"])[0]["state"] == "LEASED"

    prep = _service(truth)
    prepared = prep.prepare(
        plan_id=plan["plan_id"], workitem_id=item["workitem_id"],
        fenced_admission=dispatch)
    assert prepared["worker_id"] == dispatch.worker_id
    assert prepared["session_id"] == dispatch.session_id
    assert prepared["attempt_id"] != dispatch.worker_id
    assert prepared["task_lease"]["scope_ref"] == (
        "task:%s/attempt:%s" % (item["workitem_id"], prepared["attempt_id"]))
    assert len(truth.query("rc72_worker_session", mission_id=MISSION)) == 1
    assert truth.query("rc7_task", task_id=item["workitem_id"])[0]["lease_owner"] == dispatch.worker_id
    assert truth.query("rc72_workitem_attempt_binding", attempt_id=prepared["attempt_id"])[0]["worker_id"] == dispatch.worker_id
    assert len(prepared["data_lease_ids"]) == 1
    prep.authority.authorize_tool(
        dispatch.worker_id, prepared["task_lease"]["lease_id"], "api_http")
    assert truth.query("execution_attempt") == []  # no fabricated SUT result


def test_cold_r1_fenced_worker_consumption_preserves_worker_identity(tmp_path, monkeypatch):
    truth, plan, item, _, _, _, dispatch = _fenced(tmp_path, monkeypatch)
    cold = TruthRuntime(truth.store.path)
    prepared = _service(cold).prepare(
        plan_id=plan["plan_id"], workitem_id=item["workitem_id"],
        fenced_admission=dispatch)
    assert prepared["worker_id"] == dispatch.worker_id
    assert prepared["session_id"] == dispatch.session_id
    assert len(cold.query("rc72_worker_session", mission_id=MISSION)) == 1
    assert cold.query("rc7_task", task_id=item["workitem_id"])[0]["state"] == "LEASED"


@pytest.mark.parametrize("change", [
    {"worker_id": "WRK-FORGED"},
    {"etu_id": "ETU-WRONG"},
    {"captain_generation": 42},
    {"role": "test-executor"},
])
def test_forged_or_stale_fenced_admission_refuses_signed_worker_authority(tmp_path, monkeypatch, change):
    truth, plan, item, _, _, _, dispatch = _fenced(tmp_path, monkeypatch)
    before = list(truth.store.iter_raw())
    fake = replace(dispatch, **change)
    with pytest.raises(ContractError, match="FENCED_"):
        _service(truth).prepare(
            plan_id=plan["plan_id"], workitem_id=item["workitem_id"],
            fenced_admission=fake)
    assert list(truth.store.iter_raw()) == before
    assert truth.query("rc72_n7_execution_preparation") == []


def test_quiesced_captain_cannot_issue_new_signed_n7_preparation(tmp_path, monkeypatch):
    truth, plan, item, captain, lifecycle, owner, dispatch = _fenced(tmp_path, monkeypatch)
    checkpoint = captain.prepare_handoff(
        mission_id=MISSION, team_id="TEAM-" + MISSION,
        lease_id=owner["lease_id"],
        captain_session_id=owner["captain_session_id"],
        lifecycle=lifecycle, current_node_refs=["N7_EXECUTION"],
        latest_delivery_refs=[], latest_gate_refs=[],
        next_workitem_ids=[item["workitem_id"]])
    assert checkpoint.checkpoint_id
    before = list(truth.store.iter_raw())
    with pytest.raises(ContractError, match="CAPTAIN_DISPATCH_NOT_ACTIVE"):
        _service(truth).prepare(
            plan_id=plan["plan_id"], workitem_id=item["workitem_id"],
            fenced_admission=dispatch)
    assert list(truth.store.iter_raw()) == before
    assert truth.query("rc72_n7_execution_preparation") == []
