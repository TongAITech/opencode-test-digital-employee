"""Independent runtimes/processes must not both own a mutable resource."""
import json
from pathlib import Path
import subprocess
import sys

import pytest
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.rc72_data_resources import DataLeaseManager, DataAccessMode
from test_rc72_phase7_data_lease_contract import _setup as data_setup, _acquire as acquire_data
from test_rc72_phase7_browser_lease_contract import _setup as browser_setup


_CHILD = '''import json,sys
import rc7_runtime
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.rc72_data_resources import DataLeaseManager,DataAccessMode
from rc7_runtime.rc72_browser_resources import BrowserPool,BrowserAccessMode
truth=TruthRuntime(sys.argv[1])
kind,wi,att,worker,mode=sys.argv[2:]
manager=DataLeaseManager(truth,release_id='RC7.2') if kind=='data' else BrowserPool(truth,release_id='RC7.2')
print('READY',flush=True)
sys.stdin.readline()
try:
    common=dict(mission_id='M-1',workitem_id=wi,attempt_id=att,worker_id=worker,ttl_seconds=300)
    if kind=='data':
        ref='data://dictionary/DICT-001' if mode=='READ' else 'data://subproject/SP-001'
        grant=manager.acquire(data_ref=ref,mode=DataAccessMode.SHARED_READ if mode=='READ' else DataAccessMode.EXCLUSIVE_WRITE,cleanup_policy='release reservation',**common)
    else:
        grant=manager.acquire(access_mode=BrowserAccessMode.WRITE,purpose='EXECUTION',**common)
    print(json.dumps(dict(state='ACQUIRED',lease=grant.__dict__)),flush=True)
except Exception as exc:
    print(json.dumps(dict(state='BLOCKED',error=str(exc))),flush=True)
'''


def _race(truth, kind, identities, mode='WRITE'):
    children = []
    try:
        for wi, attempt, worker in identities:
            child = subprocess.Popen([sys.executable, '-c', _CHILD, str(truth.store.path), kind, wi, attempt, worker, mode],
                cwd=str(Path(__file__).resolve().parents[1]), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True)
            children.append(child)
            assert child.stdout.readline().strip() == 'READY'
        for child in children:
            child.stdin.write('GO\n')
            child.stdin.flush()
        results = []
        for child in children:
            output, error = child.communicate(timeout=15)
            assert child.returncode == 0, error
            results.append(json.loads(output))
        return results
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.communicate()


@pytest.mark.parametrize('kind', ['data', 'browser'])
def test_two_real_processes_with_stale_projections_get_only_one_write_owner(tmp_path, kind):
    if kind == 'data':
        truth, _, a, b = data_setup(tmp_path)
        ids, bucket = (a, b), 'rc72_data_lease'
    else:
        truth, _, actors = browser_setup(tmp_path, instance_count=1)
        ids, bucket = (actors['L4'], actors['L5']), 'rc72_browser_lease'
    results = _race(truth, kind, ids)
    assert sorted(row['state'] for row in results) == ['ACQUIRED', 'BLOCKED']
    assert 'CONFLICT' in next(row['error'] for row in results if row['state'] == 'BLOCKED')
    cold = TruthRuntime(truth.store.path)
    assert len([row for row in cold.query(bucket) if row['state'] == 'ACTIVE']) == 1


def test_two_stale_readers_can_both_commit_with_unique_monotonic_journal_sequences(tmp_path):
    truth, _, a, b = data_setup(tmp_path)
    results = _race(truth, 'data', (a, b), mode='READ')
    assert any(row['state'] == 'ACQUIRED' for row in results)
    assert all(row['state'] == 'ACQUIRED' or 'LEDGER_BUSY' in row['error'] for row in results)
    # A busy concurrent contender may retry its reservation, never a business I/O.
    cold = TruthRuntime(truth.store.path)
    manager = DataLeaseManager(cold, release_id='RC7.2')
    for identity, result in zip((a, b), results):
        if result['state'] == 'BLOCKED':
            acquire_data(manager, identity, 'data://dictionary/DICT-001', DataAccessMode.SHARED_READ)
    cold.rebuild_projection()
    assert len(cold.query('rc72_data_lease')) == 2
    sequences = [row['seq'] for row in cold.store.iter_raw()]
    assert sequences == sorted(set(sequences))


def test_stale_manager_observes_new_external_owner_and_superseded_binding(tmp_path):
    truth, manager, a, b = data_setup(tmp_path)
    stale = DataLeaseManager(TruthRuntime(truth.store.path), release_id='RC7.2')
    acquired = acquire_data(manager, a, 'data://subproject/SP-001', DataAccessMode.EXCLUSIVE_WRITE)
    with pytest.raises(Exception, match='RESOURCE_CONFLICT'):
        acquire_data(stale, b, 'data://subproject/SP-001', DataAccessMode.EXCLUSIVE_WRITE)
    changed = TruthRuntime(truth.store.path)
    binding = changed.query('rc72_workitem_attempt_binding', workitem_id=a[0])[0]
    changed.append_atomic('RC72_WORKITEM_ATTEMPT_BINDING_UPSERTED', dict(binding, state='SUPERSEDED',
        artifact_version=binding['artifact_version'] + 1))
    with pytest.raises(Exception, match='ATTEMPT_NOT_ACTIVE'):
        manager.assert_usable(data_lease_id=acquired.data_lease_id, mission_id='M-1', workitem_id=a[0],
            attempt_id=a[1], worker_id=a[2], data_ref='data://subproject/SP-001')


def test_process_death_releases_lock_without_deleting_its_file_or_stealing_a_live_owner(tmp_path):
    truth, manager, a, b = data_setup(tmp_path)
    code = '''import sys
import rc7_runtime
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.rc72_ledger_lock import ledger_lock
with ledger_lock(TruthRuntime(sys.argv[1])):
    print('LOCKED',flush=True)
    sys.stdin.readline()
'''
    child = subprocess.Popen([sys.executable, '-c', code, str(truth.store.path)],
        cwd=str(Path(__file__).resolve().parents[1]), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == 'LOCKED'
        with pytest.raises(Exception, match='LEDGER_BUSY'):
            acquire_data(manager, a, 'data://subproject/SP-001', DataAccessMode.EXCLUSIVE_WRITE)
    finally:
        child.kill()
        child.communicate(timeout=10)
    from rc7_runtime.rc72_ledger_lock import ledger_lock_path
    assert ledger_lock_path(truth).exists()
    acquired = acquire_data(manager, a, 'data://subproject/SP-001', DataAccessMode.EXCLUSIVE_WRITE)
    with pytest.raises(Exception, match='RESOURCE_CONFLICT'):
        acquire_data(manager, b, 'data://subproject/SP-001', DataAccessMode.EXCLUSIVE_WRITE)
    assert manager.lease(acquired.data_lease_id)['state'] == 'ACTIVE'


def _second_mission(truth):
    from dataclasses import fields
    from rc7_runtime.models import Task
    from rc7_runtime.rc72_domain import ReleaseBatch, TestObligation, ExecutionTaskUnit
    from rc7_runtime.rc72_linkage import WorkItemAttemptBinding, WorkItemAttemptState
    from rc7_runtime.rc72_repository import CanonicalRC72Repository
    from rc7_runtime.truth_overlay import append_entity
    repo = CanonicalRC72Repository(truth, release_id='RC7.2')
    obligation = truth.query('rc72_test_obligation')[0]
    repo.persist(ReleaseBatch(release_batch_id='RB-SECOND', mission_id='M-SECOND', name='second independent mission',
        application_ids=[obligation['application_id']], requirement_ids=[obligation['requirement_id']]))
    values = {field.name: obligation[field.name] for field in fields(TestObligation) if field.name in obligation}
    values.update(obligation_id='TO-SECOND', mission_id='M-SECOND', release_batch_id='RB-SECOND')
    repo.persist(TestObligation(**values))
    etu = truth.query('rc72_etu')[0]
    values = {field.name: etu[field.name] for field in fields(ExecutionTaskUnit) if field.name in etu}
    values.update(etu_id='ETU-SECOND', mission_id='M-SECOND', release_batch_id='RB-SECOND',
        obligation_id='TO-SECOND', case_ids=['TC-SECOND'])
    repo.persist(ExecutionTaskUnit(**values))
    append_entity(truth, Task(task_id='WI-SECOND', mission_id='M-SECOND', node='N7_EXECUTION',
        task_type='SECOND_MISSION_EXECUTION', objective='same physical resource in a different mission',
        required_capabilities=['resource:write'], input_artifact_refs=['ETU-SECOND'],
        acceptance_criteria=['no resource substitution']), release_id='RC7.2')
    repo.persist(WorkItemAttemptBinding(binding_id='BIND-SECOND', mission_id='M-SECOND', etu_id='ETU-SECOND',
        workitem_id='WI-SECOND', case_id='TC-SECOND', attempt_id='ATT-SECOND', worker_id='WORKER-SECOND',
        session_id='SESSION-SECOND', task_lease_ref='TASKLEASE-SECOND', state=WorkItemAttemptState.RUNNING))


@pytest.mark.parametrize('kind', ['data', 'browser'])
def test_write_ownership_is_global_across_independent_missions(tmp_path, kind):
    if kind == 'data':
        truth, manager, a, _ = data_setup(tmp_path)
        acquire_data(manager, a, 'data://subproject/SP-001', DataAccessMode.EXCLUSIVE_WRITE)
    else:
        from rc7_runtime.rc72_browser_resources import BrowserAccessMode
        truth, manager, actors = browser_setup(tmp_path, instance_count=1)
        wi, attempt, worker = actors['L4']
        manager.acquire(mission_id='M-1', workitem_id=wi, attempt_id=attempt, worker_id=worker,
            access_mode=BrowserAccessMode.WRITE, purpose='EXECUTION', ttl_seconds=300)
    _second_mission(truth)
    common = dict(mission_id='M-SECOND', workitem_id='WI-SECOND', attempt_id='ATT-SECOND',
                  worker_id='WORKER-SECOND', ttl_seconds=300)
    with pytest.raises(Exception, match='RESOURCE_CONFLICT'):
        if kind == 'data':
            manager.acquire(data_ref='data://subproject/SP-001', mode=DataAccessMode.EXCLUSIVE_WRITE,
                cleanup_policy='release reservation', **common)
        else:
            manager.acquire(access_mode=BrowserAccessMode.WRITE, purpose='EXECUTION', **common)
