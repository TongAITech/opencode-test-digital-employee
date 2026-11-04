"""C04/C07 formal N7 failed Case -> signed N8 -> Captain-fenced N9 analyst.

These tests exercise actual local HTTP and process evidence, but do not claim
DSH AgentTeams, product Defect confirmation, a fix or bank Field results.
"""
import pytest

from rc7_runtime.control_plane import TaskScheduler
from rc7_runtime.models import ContractError
from rc7_runtime.rc72_captain_dispatch_fencing import CaptainDispatchFencer
from rc7_runtime.rc72_captain_scheduling import CaptainFencedWorkItemScheduler
from rc7_runtime.rc72_n7_pipeline import N7PipelineService
from rc7_runtime.rc72_worker_lifecycle import WorkerLifecycleService
from rc72_n2_test_support import BATCH
from test_rc72_conclusive_failure_evidence import _failed_business


def _setup_fenced_business_failure(tmp_path, monkeypatch, *, n9_caps=('defect_analysis',)):
    truth, plan, prep, server, url, legacy = _failed_business(tmp_path, monkeypatch)
    team = 'TEAM-N9-PROFESSIONAL'
    captain = 'CAPTAIN-N9-PROFESSIONAL'
    fencer = CaptainDispatchFencer(truth, release_id=prep.release_id)
    owner = fencer.acquire_initial(
        mission_id=plan['mission_id'], team_id=team,
        captain_session_id=captain)
    roles = {}
    for item in plan['items']:
        etu = truth.query('rc72_etu', etu_id=item['etu_id'])[0]
        task = truth.query('rc7_task', task_id=item['workitem_id'])[0]
        role = etu['test_level'] + '_EXECUTE'
        roles.setdefault(role, set()).update(
            list(etu['required_capabilities']) + list(task['required_capabilities']))
    roles['N9_QUALIFY'] = set(n9_caps)
    scheduler = CaptainFencedWorkItemScheduler(
        truth=truth, release_id=prep.release_id,
        fencer=fencer,
        lifecycle=WorkerLifecycleService(truth, release_id=prep.release_id),
        scheduler=TaskScheduler(truth, prep.release_id),
        role_profiles={role: sorted(caps) for role, caps in roles.items()})
    pipeline = N7PipelineService(
        prep, runner=legacy.runner, capture_root=legacy.review.capture_root,
        captain_scheduler=scheduler, captain_session_id=captain,
        captain_lease_id=owner['lease_id'], team_id=team)
    return truth, plan, prep, server, pipeline, owner


def test_original_signed_n8_failure_admits_independent_captain_n9_without_business_replay(
        tmp_path, monkeypatch):
    truth, plan, prep, server, pipeline, owner = _setup_fenced_business_failure(
        tmp_path, monkeypatch)
    try:
        result = pipeline.complete(release_batch_id=BATCH)
        assert result['status'] == 'HOLD'
        assert result['failure_class'] == 'VALID_TEST_FAILURE'
        assert result['next_node'] == 'N9_DEFECT'
        assert result['defect_confirmed'] is False
        assert result['reproduction_completed'] is False
        assert result['qualification_admission_reason'] == (
            'N9_CAPTAIN_QUALIFICATION_AWAITS_SIGNED_DSH')
        assert len(server.calls) == 1
        wid = result['qualification_workitem_id']
        task = truth.query('rc7_task', task_id=wid)[0]
        assert task['task_type'] == 'N9_DISCREPANCY_QUALIFICATION'
        assert task['state'] == 'LEASED'
        assert task['lease_owner'] == result['qualification_worker_id']
        admission = truth.query(
            'rc72_captain_etu_admission',
            admission_id=result['qualification_admission_id'])[0]
        assert admission['role'] == 'N9_QUALIFY'
        assert admission['team_id'] == owner['team_id']
        assert admission['captain_generation'] == owner['generation']
        assert admission['worker_id'] == task['lease_owner']
        assert admission['workitem_id'] != plan['items'][0]['workitem_id']
        session = truth.query('rc72_worker_session', session_id=admission['session_id'])[0]
        assert session['role'] == 'N9_QUALIFY'
        assert session['workitem_id'] == wid
        assert session['runtime_attempt_id'] is None
        assert session['dsh_session_id'] is None
        assert not truth.query('rc7_defect')
        assert not truth.query('rc7_task', task_type='DEFECT_REPRODUCTION')
        assert not truth.query('rc72_node_gate', node_type='N9_DEFECT')
        before = truth.store.path.read_bytes()
        second = pipeline.complete(release_batch_id=BATCH)
        assert second['qualification_admission_id'] == admission['admission_id']
        assert second['qualification_worker_id'] == admission['worker_id']
        assert second['qualification_admission_reason'] == (
            'N9_CAPTAIN_ALREADY_ADMITTED_NO_REPLAY')
        assert truth.store.path.read_bytes() == before
        assert len(server.calls) == 1
    finally:
        server.shutdown()
        server.server_close()


def test_n9_analyst_cannot_inherit_n7_business_tool_capability(
        tmp_path, monkeypatch):
    truth, plan, prep, server, pipeline, owner = _setup_fenced_business_failure(
        tmp_path, monkeypatch, n9_caps=('defect_analysis', 'api_http'))
    try:
        with pytest.raises(ContractError, match='N9_CAPTAIN_ANALYSIS_ONLY_PROFILE_REQUIRED'):
            pipeline.complete(release_batch_id=BATCH)
        assert len(server.calls) == 1
        assert not truth.query('rc72_captain_etu_admission', role='N9_QUALIFY')
        assert not truth.query('rc72_worker_session', role='N9_QUALIFY')
        assert not truth.query('rc7_defect')
        assert not truth.query('rc7_task', task_type='DEFECT_REPRODUCTION')
        assert not truth.query('rc72_node_gate', node_type='N9_DEFECT')
    finally:
        server.shutdown()
        server.server_close()


def test_n9_qualification_cannot_bypass_n7_executors_role_admission(
        tmp_path, monkeypatch):
    truth, plan, prep, server, pipeline, owner = _setup_fenced_business_failure(
        tmp_path, monkeypatch)
    try:
        with pytest.raises(ContractError, match='CAPTAIN_SCHEDULER_ROLE_CANNOT_EXECUTE_ETU'):
            pipeline.captain_scheduler.dispatch_etu(
                mission_id=plan['mission_id'],
                team_id=owner['team_id'],
                captain_session_id=owner['captain_session_id'],
                captain_lease_id=owner['lease_id'],
                role='N9_QUALIFY',
                etu_id=plan['items'][0]['etu_id'],
                workitem_id=plan['items'][0]['workitem_id'],
                canonical_refs={'etu_refs': [plan['items'][0]['etu_id']]})
        assert len(server.calls) == 0
        assert not truth.query('rc72_worker_session', role='N9_QUALIFY')
    finally:
        server.shutdown()
        server.server_close()
