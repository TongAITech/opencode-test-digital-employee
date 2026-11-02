"""Whole-member preflight and cold partial mixed-disposition recovery."""
from pathlib import Path
import pytest
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import ContractError
from rc7_runtime.rc72_n8_execution_diagnosis import ExecutionDiagnosisService
from rc7_runtime.rc72_n8_retry_continuation import DataRepairContinuationService
from rc72_multi_member_support import mixed_member_repair
from test_rc72_n7_member_drain import _close
from test_rc72_n7_execution_preparation import _service


def _peer_state(prep, peer):
    return {kind: prep._one(kind, **{key: peer[value]}) for kind, key, value in (
        ('rc7_task', 'task_id', 'workitem_id'), ('rc72_n7_execution_preparation', 'preparation_id', 'preparation_id'),
        ('rc72_workitem_attempt_binding', 'binding_id', 'binding_id'))}


def test_bad_later_peer_blocks_every_earlier_member_projection(tmp_path, monkeypatch):
    import rc7_runtime.rc72_n8_member_disposition as module
    truth, prep, server, old_plan, peers, failed, diagnosis = mixed_member_repair(tmp_path, monkeypatch)
    try:
        before = [_peer_state(prep, peer) for peer in peers]
        repairs = list(server.repair_calls)
        apply = module.apply_member_dispositions
        def change_last_peer(controller, row):
            assert row['member_decisions'][0]['disposition'] == 'REEXECUTE_AFTER_VERIFIED_DRAIN'
            last = row['members'][1]['captured_evidence'][0]
            Path(last['content_ref'][len('file://'):]).write_bytes(b'changed after decision')
            return apply(controller, row)
        monkeypatch.setattr(module, 'apply_member_dispositions', change_last_peer)
        with pytest.raises(ContractError, match='REUSE_CAPTURE_BYTES_CHANGED'):
            DataRepairContinuationService(diagnosis).reconcile(failed['preparation_id'])
        row = truth.query('rc72_n8_retry_reconciliation')[0]
        assert row['state'] == 'READY' and len(row['members']) == 2
        assert not truth.query('rc72_n7_execution_plan', plan_id=row['plan']['plan_id'])
        assert [_peer_state(prep, peer) for peer in peers] == before
        assert len(server.calls) == 2 and server.repair_calls == repairs
        assert len(truth.query('execution_attempt')) == 3
    finally:
        _close(server)


@pytest.mark.parametrize('corrupt_after_crash', [False, True])
def test_partial_first_member_recovers_only_after_rechecking_the_other_peer(tmp_path, monkeypatch, corrupt_after_crash):
    truth, prep, server, old_plan, peers, failed, diagnosis = mixed_member_repair(tmp_path, monkeypatch)
    try:
        second_before = _peer_state(prep, peers[1])
        repairs = list(server.repair_calls)
        append, hits = truth.append_atomic, []
        def crash(kind, payload, **kwargs):
            result = append(kind, payload, **kwargs)
            if kind == 'RC72_WORKITEM_ATTEMPT_BINDING_UPSERTED' and payload['binding_id'] == peers[0]['binding_id'] and not hits:
                hits.append(True)
                raise KeyboardInterrupt()
            return result
        monkeypatch.setattr(truth, 'append_atomic', crash)
        with pytest.raises(KeyboardInterrupt):
            DataRepairContinuationService(diagnosis).reconcile(failed['preparation_id'])
        first_partial = _peer_state(prep, peers[0])
        assert first_partial['rc72_workitem_attempt_binding']['state'] == 'SUPERSEDED'
        assert first_partial['rc7_task']['state'] == 'RUNNING'
        row = truth.query('rc72_n8_retry_reconciliation')[0]
        if corrupt_after_crash:
            capture = row['members'][1]['captured_evidence'][0]
            Path(capture['content_ref'][len('file://'):]).write_bytes(b'changed while controller was absent')
        cold = _service(TruthRuntime(truth.store.path))
        service = DataRepairContinuationService(ExecutionDiagnosisService(cold, evidence_root=tmp_path / 'multiple-diagnosis'))
        if corrupt_after_crash:
            before = cold.truth.store.path.read_bytes()
            with pytest.raises(ContractError, match='REUSE_CAPTURE_BYTES_CHANGED'):
                service.reconcile(failed['preparation_id'])
            assert cold.truth.store.path.read_bytes() == before
            assert _peer_state(cold, peers[0]) == first_partial
            assert not cold.truth.query('rc72_n7_execution_plan', plan_id=row['plan']['plan_id'])
        else:
            plan = service.reconcile(failed['preparation_id'])
            assert cold._one('rc7_task', task_id=peers[0]['workitem_id'])['state'] == 'READY'
            assert cold._one('rc72_n7_execution_preparation', preparation_id=peers[0]['preparation_id'])['status'] == 'INTERRUPTED'
            before = cold.truth.store.path.read_bytes()
            assert service.reconcile(failed['preparation_id']) == plan
            assert cold.truth.store.path.read_bytes() == before and not cold.authority._leases
            child = cold.prepare(plan_id=plan['plan_id'], workitem_id=peers[0]['workitem_id'])
            assert cold._one('rc72_workitem_attempt_binding', binding_id=child['binding_id'])['parent_attempt_id'] == peers[0]['attempt_id']
        assert _peer_state(cold, peers[1]) == second_before
        assert len(server.calls) == 2 and server.repair_calls == repairs
        assert len(cold.truth.query('execution_attempt')) == 3
    finally:
        _close(server)
