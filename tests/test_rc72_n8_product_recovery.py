"""Actual N7 local HTTP failure -> independent N8 -> signed N5 compensation.

These are source-level tests using a real local SUT and real subprocess
diagnosis/cleanup. No fake Case PASS, DataRef or field qualification is issued.
"""
import pytest

from rc7_runtime.models import ContractError
from rc7_runtime.rc72_formal_runner import FormalN7RunnerAdapter
from rc7_runtime.rc72_n7_pipeline import N7PipelineService
from rc7_runtime.rc72_n8_product_recovery import NativeN8ProductRecoveryService
from rc72_formal_runner_support import LocalHTTPEnvironment
from test_rc72_n8_execution_diagnosis import _failure


def _product(tmp_path,monkeypatch,*,mode='data'):
    truth,prep,server,p=_failure(tmp_path,monkeypatch,mode)
    root=tmp_path/'n8-product-native'
    url='http://127.0.0.1:%d'%server.server_address[1]
    runner=FormalN7RunnerAdapter(prep,evidence_root=root/'runner',
        environment_adapter=LocalHTTPEnvironment(url,root/'cleanup'))
    pipeline=N7PipelineService(prep,runner=runner,capture_root=root/'evidence')
    return truth,p,server,NativeN8ProductRecoveryService(pipeline)


def test_n8_product_accepts_actual_failed_n7_then_opens_verified_n5_repair_only(tmp_path,monkeypatch):
    truth,p,server,service=_product(tmp_path,monkeypatch)
    try:
        old=truth.query('execution_attempt',attempt_id=p['attempt_id'])[0]
        result=service.complete(release_batch_id=p['release_batch_id'])
        assert result['status']=='HOLD' and result['reason']=='N8_VERIFIED_N5_REPAIR_REQUIRED'
        assert result['failure_class']=='TEST_DATA_GAP'
        assert result['affected_data_refs']
        assert result['field_verified'] is result['bank_final'] is False
        assert truth.query('rc72_mission_node',node_type='N8_DIAGNOSIS_RECOVERY')[0]['state']=='PASS'
        assert truth.query('rc72_mission_node',node_type='N5_TEST_DATA')[0]['state']=='RUNNING'
        assert truth.query('rc72_mission_node',node_type='N7_EXECUTION')[0]['state']=='NOT_STARTED'
        assert truth.query('rc72_n8_repair_boundary')[0]['state']=='REPAIR_OPEN'
        assert truth.query('execution_attempt',attempt_id=p['attempt_id'])[0]==old
        assert not truth.query('rc72_diagnosis_repair')
        assert not truth.query('rc7_defect')
        assert server.calls==[]
        before=truth.store.path.read_bytes()
        repeat=service.complete(release_batch_id=p['release_batch_id'])
        assert repeat==result and truth.store.path.read_bytes()==before
        assert server.calls==[] and not truth.query('rc72_diagnosis_recovery')
    finally:
        server.shutdown();server.server_close()


def test_n8_product_unknown_causality_has_no_gate_compensation_or_business_replay(tmp_path,monkeypatch):
    truth,p,server,service=_product(tmp_path,monkeypatch,mode='precondition')
    try:
        result=service.complete(release_batch_id=p['release_batch_id'])
        assert result['status']=='HOLD' and result['reason']=='N8_UNKNOWN_CAUSE_NO_AUTO_PASS'
        assert result['failure_class']=='UNKNOWN'
        assert truth.query('rc72_mission_node',node_type='N8_DIAGNOSIS_RECOVERY')[0]['state']=='BLOCKED'
        assert not truth.query('rc72_n8_repair_boundary')
        assert not truth.query('rc72_node_gate',node_type='N8_DIAGNOSIS_RECOVERY')
        assert not truth.query('rc7_defect')
        assert server.calls==[]
        before=truth.store.path.read_bytes()
        assert service.complete(release_batch_id=p['release_batch_id'])==result
        assert truth.store.path.read_bytes()==before and server.calls==[]
    finally:
        server.shutdown();server.server_close()


def test_n8_product_rejects_edited_r1_failure_edge_before_cleanup(tmp_path,monkeypatch):
    truth,p,server,service=_product(tmp_path,monkeypatch)
    try:
        # Independently perform only the N8 signed diagnosis; never invoke
        # compensation before checking the persisted original transition.
        service.diagnosis.run(p['preparation_id'])
        edge=truth.query('rc72_node_transition',kind='DIAGNOSIS')[0]
        truth.append_atomic('RC72_NODE_TRANSITION_UPSERTED',dict(edge,
            evidence_refs=['foreign-evidence-proof'],
            artifact_version=edge['artifact_version']+1))
        before=truth.store.path.read_bytes()
        with pytest.raises(ContractError,match='N8_PRODUCT_ORIGINAL_FAILURE_EVIDENCE_CHANGED'):
            service.complete(release_batch_id=p['release_batch_id'])
        assert truth.store.path.read_bytes()==before
        assert not truth.query('rc72_n8_repair_boundary')
        assert server.calls==[]
    finally:
        server.shutdown();server.server_close()
