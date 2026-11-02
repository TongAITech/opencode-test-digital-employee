"""Apply a signed re-execution decision after verified member drain.

These projections grant no old execution rights and launch no business tools.
A fresh preparation must acquire its own scoped lease and preserve parentage.
"""
from dataclasses import fields

from rc6_runtime.authority import TaskLease, WorkerIdentity
from .models import ContractError, TaskStatus
from .state_machine import transition_task
from .rc72_linkage import WorkItemAttemptBinding, WorkItemAttemptState
from .rc72_ledger_lock import ledger_lock
from .rc72_n7_execution_admission import _hash

_REEXECUTE = 'REEXECUTE_AFTER_VERIFIED_DRAIN'


def _decision(planning, row, member):
    from .rc72_n8_retry_truth import verify_record
    verify_record(planning.authority, row)
    matches = [d for d in row.get('member_decisions', []) if d['preparation_id'] == member['preparation_id']]
    persisted = planning._one('rc72_n8_retry_reconciliation', reconciliation_id=row['reconciliation_id'])
    verify_record(planning.authority, persisted)
    # Compare canonical durable JSON, including version. A warm signed nested
    # lease can contain tuples; journal replay represents those arrays as lists.
    if (_hash(persisted) != _hash(row)
            or row['state'] != 'READY' or member not in row.get('members', []) or len(matches) != 1
            or matches[0]['disposition'] != _REEXECUTE):
        raise ContractError('N8_MEMBER_SIGNED_REEXECUTION_DECISION_REQUIRED')
    return matches[0]


def _same(left, right, ignored):
    return {k: v for k, v in left.items() if k not in ignored} == {k: v for k, v in right.items() if k not in ignored}


def verify_member_projection(planning, row, member, *, partial=False):
    """Read-only exact transition/child ownership check, without authority restore."""
    decision = _decision(planning, row, member)
    old, task0, binding0 = (member[key] for key in ('original_preparation', 'original_task', 'original_binding'))
    p = planning._one('rc72_n7_execution_preparation', preparation_id=old['preparation_id'])
    drained = dict(old, status='DRAINED', artifact_version=old['artifact_version'] + 1)
    interrupted = dict(old, status='INTERRUPTED', artifact_version=old['artifact_version'] + 2)
    if p != interrupted and (not partial or p != drained):
        raise ContractError('N8_MEMBER_DISPOSITION_PREPARATION_CHANGED')
    binding = planning._one('rc72_workitem_attempt_binding', binding_id=old['binding_id'])
    expected_binding = dict(binding0, state='SUPERSEDED', artifact_version=binding0['artifact_version'] + 1)
    if binding != expected_binding and (not partial or binding != binding0):
        raise ContractError('N8_MEMBER_DISPOSITION_BINDING_CHANGED')
    session = planning._one('rc72_worker_session', session_id=old['session_id'])
    from .rc72_n7_member_drain import _REASON as checkpoint_reason
    if (session['state'] != 'CLOSED' or session['worker_id'] != old['worker_id']
            or session['workitem_id'] != old['workitem_id'] or session.get('close_reason') != checkpoint_reason):
        raise ContractError('N8_MEMBER_DISPOSITION_SESSION_CHANGED')
    task = planning._one('rc7_task', task_id=old['workitem_id'])
    ready = dict(task0, state='READY', lease_owner=None, artifact_version=task0['artifact_version'] + 2)
    if _same(task, ready, {'updated_at'}):
        return
    if partial:
        stale = dict(task0, state='STALE', lease_owner=None, artifact_version=task0['artifact_version'] + 1)
        if task == task0 or _same(task, stale, {'updated_at'}):
            return
    # Once the plan was published a newly signed child may own the same Task.
    # Authenticate that actual child, not arbitrary RUNNING/PASS metadata.
    children = planning.truth.query('rc72_n7_execution_preparation', plan_id=row['plan']['plan_id'],
                                    workitem_id=old['workitem_id'], status='PREPARED')
    if len(children) != 1:
        raise ContractError('N8_MEMBER_DISPOSITION_FRESH_CHILD_REQUIRED')
    child = children[0]
    bound = planning._one('rc72_workitem_attempt_binding', binding_id=child['binding_id'])
    lease_data = dict(child['task_lease'])
    for key in ('allowed_tools', 'allowed_artifact_types'):
        lease_data[key] = tuple(lease_data[key])
    lease = TaskLease(**lease_data)
    identity = WorkerIdentity(**child['worker_identity'])
    planning.authority.validate_historical_lease(identity, lease)
    item = next(i for i in row['plan']['items'] if i['workitem_id'] == old['workitem_id'])
    if (any(child[key] != old[key] for key in ('mission_id', 'release_batch_id', 'release_id', 'source_commit', 'case_id', 'etu_id'))
            or any(child[key] != item[key] for key in ('contract_id', 'admission_id'))
            or child['contract_id'] != decision['current_contract_id']
            or child['attempt_generation'] != old['attempt_generation'] + 1
            or child['attempt_id'] == old['attempt_id'] or child['worker_id'] == old['worker_id']
            or child['session_id'] == old['session_id'] or bound.get('parent_attempt_id') != old['attempt_id']
            or any(bound.get(key) != child[key] for key in ('workitem_id', 'attempt_id', 'worker_id', 'session_id', 'case_id', 'etu_id'))
            or bound.get('state') not in {'PREPARED', 'RUNNING', 'EVIDENCE_READY', 'COMPLETED'}
            or bound.get('mission_id') != old['mission_id'] or bound.get('task_lease_ref') != lease.lease_id or lease.worker_id != child['worker_id']
            or identity.worker_id != child['worker_id'] or identity.session_id != child['session_id']
            or lease.scope_ref != 'task:%s/attempt:%s' % (old['workitem_id'], child['attempt_id'])
            or lease.allowed_artifact_types or lease.allowed_tools != tuple(old['task_lease']['allowed_tools'])
            or identity.phase != 'N7_EXECUTION' or identity.role != old['worker_identity']['role']
            or identity.layer != old['worker_identity']['layer'] or identity.generation != child['attempt_generation'] - 1
            or task.get('lease_owner') != child['worker_id']
            or task['state'] not in {'LEASED', 'RUNNING', 'OUTPUT_PRODUCED', 'EVALUATING', 'PASS'}
            or not _same(task, task0, {'state', 'artifact_version', 'updated_at', 'lease_owner', 'output_artifact_refs', 'evaluation_id'})):
        raise ContractError('N8_MEMBER_DISPOSITION_CHILD_SCOPE_CHANGED')


def assert_member_projections(planning, row, *, partial=False):
    for decision in row.get('member_decisions', []):
        if decision['disposition'] == _REEXECUTE:
            member = next(m for m in row['members'] if m['preparation_id'] == decision['preparation_id'])
            verify_member_projection(planning, row, member, partial=partial)


def assert_disposed_member(preparation, row, member, *, partial=False):
    from .rc72_n7_member_drain import ExecutionMemberDrainService
    from .rc72_n7_evidence_review import ExecutionEvidenceReviewService
    review = ExecutionEvidenceReviewService(preparation, adapter_output_root=member['adapter_output_root'],
                                           capture_root=member['capture_root'])
    ExecutionMemberDrainService(review)._audit(member, terminal=not partial, disposition=row)
    return member


def apply_member_dispositions(preparation, row):
    from .rc72_n8_member_reuse import member_reuse_decisions
    from .rc72_n7_member_drain import assert_drained_member
    from .closed_loop_control import ClosedLoopControlPlane
    with ledger_lock(preparation.truth, busy='N8_MEMBER_DISPOSITION_LEDGER_BUSY'):
        if member_reuse_decisions(preparation.planning, row, row['plan']) != row.get('member_decisions', []):
            raise ContractError('N8_MEMBER_DISPOSITION_DECISION_CHANGED')
        # Preflight the entire decision denominator before any resumed mutation.
        for member in row.get('members', []):
            decision = next(d for d in row['member_decisions'] if d['preparation_id'] == member['preparation_id'])
            if decision['disposition'] == _REEXECUTE:
                assert_disposed_member(preparation, row, member, partial=True)
            else:
                assert_drained_member(preparation, member['preparation_id'])
        for member in row.get('members', []):
            decision = next(d for d in row['member_decisions'] if d['preparation_id'] == member['preparation_id'])
            if decision['disposition'] != _REEXECUTE:
                continue
            old = member['original_preparation']
            preparation.authority.revoke_worker_lease(old['task_lease']['lease_id'])
            binding = preparation._one('rc72_workitem_attempt_binding', binding_id=old['binding_id'])
            if binding['state'] != 'SUPERSEDED':
                entity = WorkItemAttemptBinding(**{f.name: binding[f.name] for f in fields(WorkItemAttemptBinding) if f.name in binding})
                entity.state = WorkItemAttemptState.SUPERSEDED
                preparation.lifecycle.repository.persist(entity, artifact_version=binding['artifact_version'] + 1)
            control = ClosedLoopControlPlane(preparation.truth, row['release_id'], row['mission_id'])
            for target in (TaskStatus.STALE, TaskStatus.READY):
                task = preparation._one('rc7_task', task_id=old['workitem_id'])
                if task['state'] == 'READY' or target == TaskStatus.STALE and task['state'] == 'STALE':
                    continue
                entity = control.scheduler.task(task['task_id'])
                transition_task(entity, target)
                control.scheduler._persist_task(entity, task['artifact_version'] + 1)
            p = preparation._one('rc72_n7_execution_preparation', preparation_id=old['preparation_id'])
            if p['status'] != 'INTERRUPTED':
                preparation.truth.append_atomic('RC72_N7_EXECUTION_PREPARATION_UPSERTED',
                    dict(p, status='INTERRUPTED', artifact_version=p['artifact_version'] + 1))
            assert_disposed_member(preparation, row, member)
