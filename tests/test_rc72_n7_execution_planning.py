"""Planning integration, with external worker/tool I/O supplied by fixtures."""
import pytest
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.rc72_n7_execution_planning import ExecutionPlanningService, ExecutionPlanningError
from rc7_runtime.rc72_state_machine import RC72StateMachine
from rc7_runtime.rc72_domain import AutonomousMissionNode
from rc72_n2_test_support import BATCH, COMMIT, MISSION, RELEASE
from test_rc72_n6_executable_readiness import NOW
from test_rc72_n7_execution_admission import _ready


def _service(truth):
    return ExecutionPlanningService(truth, release_id=RELEASE, source_commit=COMMIT, now=NOW)


def test_admitted_cases_create_real_persisted_decomposition_and_ready_tasks(tmp_path, monkeypatch):
    truth, ids = _ready(tmp_path, monkeypatch)
    result = _service(truth).plan(release_batch_id=BATCH)
    assert result['status'] == 'PLANNED'
    assert {item['contract_id'] for item in result['items']} == set(ids)
    snapshot = truth.query('rc72_decomposition_snapshot', snapshot_id=result['snapshot_id'])[0]
    assert snapshot['current_node'] == 'N7_EXECUTION'
    assert set(snapshot['case_ids']) == {item['case_id'] for item in result['items']}
    for item in result['items']:
        task = truth.query('rc7_task', task_id=item['workitem_id'])[0]
        etu = truth.query('rc72_etu', etu_id=item['etu_id'])[0]
        assert task['state'] == 'READY'
        assert task['task_type'] == 'RC72_CASE_EXECUTION'
        assert item['case_id'] in etu['case_ids']
        assert etu['planning_snapshot_ref'] == result['snapshot_id']
        obligation = truth.query('rc72_test_obligation', obligation_id=etu['obligation_id'])[0]
        assert obligation['release_batch_id'] == BATCH
        assert obligation['mission_id'] == MISSION
        assert 'same_sst=' + obligation['sst_id'] in etu['cohesion_explanation']
    assert truth.query('rc72_worker_session') == []
    assert truth.query('rc72_data_lease') == []
    assert truth.query('rc72_workitem_attempt_binding') == []
    assert truth.query('execution_attempt') == []


def test_replay_resumes_same_etus_tasks_admissions_without_duplicate_work(tmp_path, monkeypatch):
    truth, _ = _ready(tmp_path, monkeypatch)
    first = _service(truth).plan(release_batch_id=BATCH)
    before = list(truth.store.iter_raw())
    replay = TruthRuntime(truth.store.path)
    assert _service(replay).plan(release_batch_id=BATCH) == first
    assert list(replay.store.iter_raw()) == before


def test_stale_upstream_blocks_planning_before_any_task_or_etu_write(tmp_path, monkeypatch):
    truth, _ = _ready(tmp_path, monkeypatch)
    runtime = RC72StateMachine(truth, release_id=RELEASE)
    node = runtime.node_by_type(MISSION, AutonomousMissionNode.N5_TEST_DATA)
    runtime.mark_stale(node['mission_node_id'], reason='data changed')
    before = list(truth.store.iter_raw())
    with pytest.raises(ValueError, match='UPSTREAM_NOT_PASS'):
        _service(truth).plan(release_batch_id=BATCH)
    assert list(truth.store.iter_raw()) == before
    assert truth.query('rc72_etu') == []


def test_plan_cannot_be_reused_after_source_changes(tmp_path, monkeypatch):
    truth, _ = _ready(tmp_path, monkeypatch)
    first = _service(truth).plan(release_batch_id=BATCH)
    before = list(truth.store.iter_raw())
    with pytest.raises(ExecutionPlanningError, match='SOURCE_MISMATCH'):
        ExecutionPlanningService(truth, release_id=RELEASE, source_commit='2'*40, now=NOW).assert_current(first['plan_id'])
    assert list(truth.store.iter_raw()) == before
