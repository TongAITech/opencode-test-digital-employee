"""Signed preparation uses actual R1/planner/lease services, no SUT execution."""
import pytest
from rc6_runtime.truth import TruthRuntime
from rc6_runtime.authority import AuthorityError
from rc7_runtime.rc72_authority import RC72AuthorityRuntime
from rc7_runtime.rc72_n7_execution_planning import ExecutionPlanningService
from rc7_runtime.rc72_n7_execution_preparation import ExecutionPreparationService, ExecutionPreparationError
from rc7_runtime.rc72_data_resources import DataResourceConflict
from rc7_runtime.rc72_state_machine import RC72StateMachine
from rc7_runtime.rc72_domain import AutonomousMissionNode
from rc72_n2_test_support import BATCH, COMMIT, MISSION, RELEASE
from test_rc72_n6_executable_readiness import NOW
from test_rc72_n7_execution_admission import _ready

KEY = b'unit-test-scoped-runtime-key'


def _setup(tmp_path, monkeypatch):
    truth, _ = _ready(tmp_path, monkeypatch)
    plan = ExecutionPlanningService(truth, release_id=RELEASE, source_commit=COMMIT, now=NOW).plan(release_batch_id=BATCH)
    return truth, plan


def _service(truth, *, key=KEY, tools=None):
    return ExecutionPreparationService(truth, release_id=RELEASE, source_commit=COMMIT,
        authority=RC72AuthorityRuntime(key), tool_registry={'api_http': ['api_http']} if tools is None else tools, now=NOW)


def test_preparation_binds_real_signed_scoped_worker_and_data_without_running_tools(tmp_path, monkeypatch):
    truth, plan = _setup(tmp_path, monkeypatch)
    service = _service(truth)
    item = plan['items'][0]
    result = service.prepare(plan_id=plan['plan_id'], workitem_id=item['workitem_id'])
    binding = truth.query('rc72_workitem_attempt_binding', binding_id=result['binding_id'])[0]
    assert binding['mission_node_lineage_status'] == 'RESOLVED'
    assert binding['mission_node_type'] == 'N7_EXECUTION'
    assert binding['state'] == 'PREPARED'
    assert result['task_lease']['allowed_artifact_types'] == [] or result['task_lease']['allowed_artifact_types'] == ()
    assert result['task_lease']['scope_ref'] == 'task:%s/attempt:%s' % (item['workitem_id'], result['attempt_id'])
    assert len(result['data_lease_ids']) == 1
    service.authority.authorize_tool(result['worker_id'], result['task_lease']['lease_id'], 'api_http')
    with pytest.raises(AuthorityError, match='FORBIDDEN'):
        service.authority.authorize_tool(result['worker_id'], result['task_lease']['lease_id'], 'undeclared-db-write')
    assert truth.query('execution_attempt') == []
    assert truth.query('rc72_browser_lease') == []
    assert 'actual_result' not in result


def test_distinct_etus_get_distinct_worker_session_attempts(tmp_path, monkeypatch):
    truth, plan = _setup(tmp_path, monkeypatch)
    service = _service(truth)
    assert len(plan['items']) > 1
    rows = [service.prepare(plan_id=plan['plan_id'], workitem_id=item['workitem_id']) for item in plan['items']]
    assert len({row['worker_id'] for row in rows}) == len(rows)
    assert len({row['session_id'] for row in rows}) == len(rows)
    assert len({row['attempt_id'] for row in rows}) == len(rows)


def test_restart_revalidates_hmac_and_resumes_without_duplicate_lease(tmp_path, monkeypatch):
    truth, plan = _setup(tmp_path, monkeypatch)
    result = _service(truth).prepare(plan_id=plan['plan_id'], workitem_id=plan['items'][0]['workitem_id'])
    before = list(truth.store.iter_raw())
    replay = TruthRuntime(truth.store.path)
    assert _service(replay).prepare(plan_id=plan['plan_id'], workitem_id=plan['items'][0]['workitem_id']) == result
    assert list(replay.store.iter_raw()) == before
    with pytest.raises(AuthorityError, match='SIGNATURE_INVALID'):
        _service(replay, key=b'wrong-key-with-valid-length').assert_current(result['preparation_id'])
    assert list(replay.store.iter_raw()) == before


@pytest.mark.parametrize('tools', [{}, {'api_http': ['*']}])
def test_missing_or_wildcard_authority_is_rejected_before_any_preparation_write(tmp_path, monkeypatch, tools):
    truth, plan = _setup(tmp_path, monkeypatch)
    before = list(truth.store.iter_raw())
    with pytest.raises(ExecutionPreparationError):
        _service(truth, tools=tools).prepare(plan_id=plan['plan_id'], workitem_id=plan['items'][0]['workitem_id'])
    assert list(truth.store.iter_raw()) == before
    assert truth.query('rc72_worker_session') == []


def test_resource_conflict_rolls_back_task_and_closes_worker_without_execution(tmp_path, monkeypatch):
    truth, plan = _setup(tmp_path, monkeypatch)
    service = _service(truth)
    def conflict(**kwargs):
        raise DataResourceConflict('RESOURCE_CONFLICT:fixture')
    monkeypatch.setattr(service.data, 'acquire', conflict)
    with pytest.raises(DataResourceConflict):
        service.prepare(plan_id=plan['plan_id'], workitem_id=plan['items'][0]['workitem_id'])
    task = truth.query('rc7_task', task_id=plan['items'][0]['workitem_id'])[0]
    assert task['state'] == 'READY' and task['lease_owner'] is None
    assert {row['state'] for row in truth.query('rc72_worker_session')} == {'CLOSED'}
    assert {row['state'] for row in truth.query('rc72_workitem_attempt_binding')} == {'SUPERSEDED'}
    assert truth.query('execution_attempt') == []
    assert truth.query('rc72_n7_execution_preparation') == []
    assert service.authority._leases == {}


def test_stale_upstream_stops_preparation_before_worker_or_lease_creation(tmp_path, monkeypatch):
    truth, plan = _setup(tmp_path, monkeypatch)
    runtime = RC72StateMachine(truth, release_id=RELEASE)
    node = runtime.node_by_type(MISSION, AutonomousMissionNode.N6_EXECUTABLE_READINESS)
    runtime.mark_stale(node['mission_node_id'], reason='recompiled contract needed')
    before = list(truth.store.iter_raw())
    with pytest.raises(ValueError, match='UPSTREAM_NOT_PASS'):
        _service(truth).prepare(plan_id=plan['plan_id'], workitem_id=plan['items'][0]['workitem_id'])
    assert list(truth.store.iter_raw()) == before


def test_unstarted_takeover_preserves_work_and_uses_new_session_and_attempt(tmp_path, monkeypatch):
    truth, plan = _setup(tmp_path, monkeypatch)
    service = _service(truth)
    task_id = plan['items'][0]['workitem_id']
    first = service.prepare(plan_id=plan['plan_id'], workitem_id=task_id)
    closed = service.release_unstarted(first['preparation_id'], reason='captain handoff before execution')
    assert closed['status'] == 'INTERRUPTED'
    assert {row['state'] for row in truth.query('rc72_data_lease')} == {'RELEASED'}
    second = service.prepare(plan_id=plan['plan_id'], workitem_id=task_id)
    assert second['session_id'] != first['session_id']
    assert second['worker_id'] != first['worker_id']
    assert second['attempt_id'] != first['attempt_id']
    assert second['attempt_generation'] == first['attempt_generation'] + 1
    binding = truth.query('rc72_workitem_attempt_binding', binding_id=second['binding_id'])[0]
    assert binding['parent_attempt_id'] == first['attempt_id']
    assert truth.query('execution_attempt') == []
    assert len(truth.query('rc7_task', task_id=task_id)) == 1
    with pytest.raises(AuthorityError):
        service.authority.authorize_tool(first['worker_id'], first['task_lease']['lease_id'], 'api_http')


def test_unstarted_release_cannot_claim_cleanup_after_execution_begins(tmp_path, monkeypatch):
    from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
    truth, plan = _setup(tmp_path, monkeypatch)
    service = _service(truth)
    first = service.prepare(plan_id=plan['plan_id'], workitem_id=plan['items'][0]['workitem_id'])
    ClosedLoopControlPlane(truth, RELEASE, MISSION).start(first['workitem_id'], worker_ref=first['worker_id'])
    before = list(truth.store.iter_raw())
    with pytest.raises(ExecutionPreparationError, match='UNSTARTED_OWNED'):
        service.release_unstarted(first['preparation_id'], reason='cannot fake cleanup')
    assert list(truth.store.iter_raw()) == before
    assert {row['state'] for row in truth.query('rc72_data_lease')} == {'ACTIVE'}


def test_n6_recompile_resumes_original_timestamp_while_n7_holds_its_own_leases(tmp_path, monkeypatch):
    from datetime import timedelta
    from rc7_runtime.rc72_canonical_executable import CanonicalExecutableService
    truth, plan = _setup(tmp_path, monkeypatch)
    service = _service(truth)
    prepared = service.prepare(plan_id=plan['plan_id'], workitem_id=plan['items'][0]['workitem_id'])
    contract = truth.query('rc72_n6_executable_contract', contract_id=prepared['contract_id'])[0]
    before = list(truth.store.iter_raw())
    result = CanonicalExecutableService(truth, release_id=RELEASE, source_commit=COMMIT,
        now=NOW + timedelta(seconds=1)).compile_batch(release_batch_id=BATCH)
    assert result['gate']['decision'] == 'PASS'
    assert list(truth.store.iter_raw()) == before
    assert truth.query('rc72_n6_executable_contract', contract_id=prepared['contract_id'])[0]['compiled_at'] == contract['compiled_at']
    assert {row['state'] for row in truth.query('rc72_data_lease')} == {'ACTIVE'}
