"""Signed affected-member transition recovery after actual N5 physical repair."""
import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import ContractError
from rc7_runtime.rc72_n8_execution_diagnosis import ExecutionDiagnosisService
from rc7_runtime.rc72_n8_retry_continuation import DataRepairContinuationService
from rc7_runtime.rc72_n8_member_disposition import assert_disposed_member
from test_rc72_n8_member_reuse import _repaired
from test_rc72_n7_member_drain import _close
from test_rc72_n7_execution_preparation import _service


@pytest.mark.parametrize('stage', ['signed_decision', 'binding', 'stale_task', 'ready_task', 'preparation', 'published_plan'])
def test_each_affected_member_projection_resumes_cold_without_repeating_business_or_repair(tmp_path, monkeypatch, stage):
    truth, prep, server, completed, failed, diagnosis, drain = _repaired(tmp_path, monkeypatch, repair_completed=True)
    try:
        histories = truth.query('execution_attempt')
        repaired_refs = list(server.repair_calls)
        append, hits = truth.append_atomic, []
        def crash(kind, payload, **kwargs):
            result = append(kind, payload, **kwargs)
            selected = (
                stage == 'signed_decision' and kind == 'RC72_N8_RETRY_RECONCILIATION_UPSERTED' and payload['state'] == 'READY'
                or stage == 'binding' and kind == 'RC72_WORKITEM_ATTEMPT_BINDING_UPSERTED' and payload['binding_id'] == completed['binding_id']
                or stage in {'stale_task', 'ready_task'} and kind == 'RC7_TASK_UPSERTED' and payload['task_id'] == completed['workitem_id']
                    and payload['state'] == ('STALE' if stage == 'stale_task' else 'READY')
                or stage == 'preparation' and kind == 'RC72_N7_EXECUTION_PREPARATION_UPSERTED' and payload['preparation_id'] == completed['preparation_id']
                or stage == 'published_plan' and kind == 'RC72_N7_EXECUTION_PLAN_UPSERTED')
            if selected and not hits:
                hits.append(True)
                raise KeyboardInterrupt()
            return result
        monkeypatch.setattr(truth, 'append_atomic', crash)
        with pytest.raises(KeyboardInterrupt):
            DataRepairContinuationService(diagnosis).reconcile(failed['preparation_id'])
        assert hits
        cold = _service(TruthRuntime(truth.store.path))
        with pytest.raises(ContractError, match='SUSPENDED_BY_MEMBER_CHECKPOINT'):
            cold.assert_current(completed['preparation_id'])
        service = DataRepairContinuationService(ExecutionDiagnosisService(cold, evidence_root=tmp_path / 'diagnosis'))
        plan = service.reconcile(failed['preparation_id'])
        row = cold.truth.query('rc72_n8_retry_reconciliation')[0]
        assert row['member_decisions'][0]['disposition'] == 'REEXECUTE_AFTER_VERIFIED_DRAIN'
        assert_disposed_member(cold, row, row['members'][0])
        assert cold._one('rc7_task', task_id=completed['workitem_id'])['state'] == 'READY'
        assert cold._one('rc7_task', task_id=completed['workitem_id'])['lease_owner'] is None
        assert cold._one('rc72_workitem_attempt_binding', binding_id=completed['binding_id'])['state'] == 'SUPERSEDED'
        assert cold.truth.query('execution_attempt') == histories
        assert server.repair_calls == repaired_refs and len(server.calls) == 1
        assert not cold.authority._leases
        before = cold.truth.store.path.read_bytes()
        assert service.reconcile(failed['preparation_id']) == plan
        assert cold.truth.store.path.read_bytes() == before
        child = cold.prepare(plan_id=plan['plan_id'], workitem_id=completed['workitem_id'])
        assert child['attempt_id'] != completed['attempt_id'] and child['worker_id'] != completed['worker_id']
        assert cold._one('rc72_workitem_attempt_binding', binding_id=child['binding_id'])['parent_attempt_id'] == completed['attempt_id']
        assert len(server.calls) == 1
    finally:
        _close(server)


@pytest.mark.parametrize('change', ['old_preparation', 'old_binding', 'ready_owner'])
def test_changed_projection_cannot_authorize_fresh_member_before_signed_lineage_is_restored(tmp_path, monkeypatch, change):
    truth, prep, server, completed, failed, diagnosis, drain = _repaired(tmp_path, monkeypatch, repair_completed=True)
    try:
        plan = DataRepairContinuationService(diagnosis).reconcile(failed['preparation_id'])
        if change == 'old_preparation':
            p = prep._one('rc72_n7_execution_preparation', preparation_id=completed['preparation_id'])
            p.update(status='DRAINED', artifact_version=p['artifact_version'] + 1)
            truth.append_atomic('RC72_N7_EXECUTION_PREPARATION_UPSERTED', p)
        elif change == 'old_binding':
            binding = prep._one('rc72_workitem_attempt_binding', binding_id=completed['binding_id'])
            binding.update(state='EVIDENCE_READY', artifact_version=binding['artifact_version'] + 1)
            truth.append_atomic('RC72_WORKITEM_ATTEMPT_BINDING_UPSERTED', binding)
        else:
            task = prep._one('rc7_task', task_id=completed['workitem_id'])
            task.update(lease_owner='UNRELATED-WORKER', artifact_version=task['artifact_version'] + 1)
            truth.append_atomic('RC7_TASK_UPSERTED', task)
        before = truth.store.path.read_bytes()
        with pytest.raises(ContractError, match='ORIGINAL_PREPARATION_CHANGED|DISPOSITION_(PREPARATION_CHANGED|BINDING_CHANGED|FRESH_CHILD_REQUIRED)'):
            prep.prepare(plan_id=plan['plan_id'], workitem_id=completed['workitem_id'])
        assert truth.store.path.read_bytes() == before
        assert len(server.calls) == 1 and len(truth.query('execution_attempt')) == 2
        assert not truth.query('rc72_n7_execution_preparation', plan_id=plan['plan_id'])
    finally:
        _close(server)


@pytest.mark.parametrize('change', ['parent_attempt', 'task_owner'])
def test_fresh_child_must_keep_signed_parent_and_actual_task_owner_before_dispatch(tmp_path, monkeypatch, change):
    from rc7_runtime.rc72_n7_tool_dispatch import SignedToolDispatchService
    truth, prep, server, completed, failed, diagnosis, drain = _repaired(tmp_path, monkeypatch, repair_completed=True)
    try:
        plan = DataRepairContinuationService(diagnosis).reconcile(failed['preparation_id'])
        child = prep.prepare(plan_id=plan['plan_id'], workitem_id=completed['workitem_id'])
        if change == 'parent_attempt':
            binding = prep._one('rc72_workitem_attempt_binding', binding_id=child['binding_id'])
            binding.update(parent_attempt_id=failed['attempt_id'], artifact_version=binding['artifact_version'] + 1)
            truth.append_atomic('RC72_WORKITEM_ATTEMPT_BINDING_UPSERTED', binding)
        else:
            task = prep._one('rc7_task', task_id=child['workitem_id'])
            task.update(lease_owner=completed['worker_id'], artifact_version=task['artifact_version'] + 1)
            truth.append_atomic('RC7_TASK_UPSERTED', task)
        calls = []
        before = truth.store.path.read_bytes()
        with pytest.raises(ContractError, match='DISPOSITION_CHILD_SCOPE_CHANGED'):
            SignedToolDispatchService(prep, adapters={'api_http': lambda **kwargs: calls.append(kwargs)}).dispatch(child['preparation_id'])
        assert truth.store.path.read_bytes() == before
        assert not calls and len(server.calls) == 1
        assert not truth.query('rc72_n7_tool_dispatch', preparation_id=child['preparation_id'])
        assert len(truth.query('execution_attempt')) == 2
    finally:
        _close(server)


def test_reopened_old_session_blocks_the_entire_transition_before_any_member_projection(tmp_path, monkeypatch):
    import rc7_runtime.rc72_n8_member_disposition as module
    truth, prep, server, completed, failed, diagnosis, drain = _repaired(tmp_path, monkeypatch, repair_completed=True)
    try:
        apply = module.apply_member_dispositions
        def changed_session(controller, row):
            session = prep._one('rc72_worker_session', session_id=completed['session_id'])
            session.update(state='ACTIVE', artifact_version=session['artifact_version'] + 1)
            truth.append_atomic('RC72_WORKER_SESSION_UPSERTED', session)
            return apply(controller, row)
        monkeypatch.setattr(module, 'apply_member_dispositions', changed_session)
        with pytest.raises(ContractError, match='DISPOSITION_SESSION_CHANGED'):
            DataRepairContinuationService(diagnosis).reconcile(failed['preparation_id'])
        row = truth.query('rc72_n8_retry_reconciliation')[0]
        assert row['state'] == 'READY'
        assert not truth.query('rc72_n7_execution_plan', plan_id=row['plan']['plan_id'])
        assert prep._one('rc72_workitem_attempt_binding', binding_id=completed['binding_id'])['state'] == 'EVIDENCE_READY'
        assert prep._one('rc7_task', task_id=completed['workitem_id'])['state'] == 'RUNNING'
        assert prep._one('rc72_n7_execution_preparation', preparation_id=completed['preparation_id'])['status'] == 'DRAINED'
        assert len(server.calls) == 1 and len(truth.query('execution_attempt')) == 2
    finally:
        _close(server)
