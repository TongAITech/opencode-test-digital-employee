from pathlib import Path

import pytest
from rc7_runtime.models import ContractError
from rc7_runtime.rc72_formal_runner import FormalN7RunnerAdapter
from rc7_runtime.rc72_n7_tool_dispatch import SignedToolDispatchService
from rc7_runtime.rc72_n8_execution_diagnosis import ExecutionDiagnosisService
from rc72_formal_runner_support import formal_setup, LocalHTTPEnvironment


def _failure(tmp_path, monkeypatch, mode='data'):
    truth, plan, prep, server, url = formal_setup(tmp_path, monkeypatch)
    if mode == 'data':
        server.allowed_data_refs.clear()
    else:
        server.precondition_ready = False
    root = tmp_path / 'actual'
    env = LocalHTTPEnvironment(url, root)
    runner = FormalN7RunnerAdapter(prep, evidence_root=root, environment_adapter=env,
                                  execution_env={'RC72_OUTPUT_ROOT': str(root)}, timeout_seconds=30)
    p = prep.prepare(plan_id=plan['plan_id'], workitem_id=plan['items'][0]['workitem_id'])
    try:
        result = SignedToolDispatchService(prep, adapters={'api_http': runner}).dispatch(p['preparation_id'])
        assert result['state'] == 'FAILED'
        from rc7_runtime.rc72_n7_execution_evidence import ExecutionEvidenceService
        ExecutionEvidenceService(prep).record(p['preparation_id'])
        return truth, prep, server, p
    except BaseException:
        server.shutdown()
        server.server_close()
        raise


def test_actual_data_failure_independent_process_review_and_n5_back_edge(tmp_path, monkeypatch):
    truth, prep, server, p = _failure(tmp_path, monkeypatch)
    try:
        service = ExecutionDiagnosisService(prep, evidence_root=tmp_path / 'diagnosis')
        result = service.run(p['preparation_id'])
        assert result['state'] == 'REPAIR_REQUIRED'
        assert result['failure_class'] == 'TEST_DATA_GAP' and result['responsible_node'] == 'N5_TEST_DATA'
        receipt = truth.query('rc72_n8_process_diagnosis')[0]
        assert receipt['diagnostic_process']['pid'] != receipt['review_process']['pid']
        assert receipt['diagnosis_worker_id'] != receipt['reviewer_worker_id'] != p['worker_id']
        assert server.calls == []
        assert truth.query('execution_attempt')[0]['status'] == 'BLOCKED'
        assert truth.query('rc72_mission_node', node_type='N5_TEST_DATA')[0]['state'] == 'NEEDS_REVISION'
        before = list(truth.store.iter_raw())
        assert service.run(p['preparation_id']) == result
        assert list(truth.store.iter_raw()) == before
    finally:
        server.shutdown()
        server.server_close()


def test_unproven_precondition_cause_stays_unknown_without_gate_or_back_edge(tmp_path, monkeypatch):
    truth, prep, server, p = _failure(tmp_path, monkeypatch, 'precondition')
    try:
        service = ExecutionDiagnosisService(prep, evidence_root=tmp_path / 'diagnosis')
        result = service.run(p['preparation_id'])
        assert result['state'] == 'BLOCKED' and result['failure_class'] == 'UNKNOWN'
        assert truth.query('rc72_node_gate', node_type='N8_DIAGNOSIS_RECOVERY') == []
        assert truth.query('rc72_back_edge') == []
        before = list(truth.store.iter_raw())
        assert service.run(p['preparation_id']) == result
        assert list(truth.store.iter_raw()) == before
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize('tamper', ['bytes', 'signature'])
def test_failure_evidence_tampering_is_rejected_before_diagnostic_process(tmp_path, monkeypatch, tamper):
    truth, prep, server, p = _failure(tmp_path, monkeypatch)
    try:
        row = next(row for row in truth.query('rc7_evidence') if row['kind'] == 'N7_FORMAL_DATA_RECHECK')
        if tamper == 'bytes':
            Path(row['content_ref'][len('file://'):]).write_text('changed')
        else:
            row['check_success'] = True
            row['artifact_version'] += 1
            truth.append_atomic('RC7_EVIDENCE_UPSERTED', row)
        before = list(truth.store.iter_raw())
        with pytest.raises(ContractError, match='N8_LIVE_CHECK_'):
            ExecutionDiagnosisService(prep, evidence_root=tmp_path / 'diagnosis').run(p['preparation_id'])
        assert list(truth.store.iter_raw()) == before
        assert not (tmp_path / 'diagnosis').exists()
    finally:
        server.shutdown()
        server.server_close()


def test_saved_process_result_recovers_interrupted_acceptance_without_another_process(tmp_path, monkeypatch):
    truth, prep, server, p = _failure(tmp_path, monkeypatch)
    try:
        service = ExecutionDiagnosisService(prep, evidence_root=tmp_path / 'diagnosis')
        accept = service._accept
        def interrupt(*args):
            raise KeyboardInterrupt()
        monkeypatch.setattr(service, '_accept', interrupt)
        with pytest.raises(KeyboardInterrupt):
            service.run(p['preparation_id'])
        receipt = truth.query('rc72_n8_process_diagnosis')[0]
        monkeypatch.setattr(service, '_accept', accept)
        def no_process(*args):
            raise AssertionError('recorded diagnosis must not run again')
        monkeypatch.setattr(service, '_process', no_process)
        result = service.run(p['preparation_id'])
        assert result['state'] == 'REPAIR_REQUIRED'
        assert truth.query('rc72_n8_process_diagnosis')[0] == receipt
        from rc6_runtime.truth import TruthRuntime
        from test_rc72_n7_execution_preparation import _service
        replay = TruthRuntime(truth.store.path)
        resumed = ExecutionDiagnosisService(_service(replay), evidence_root=tmp_path / 'diagnosis')
        monkeypatch.setattr(resumed, '_process', no_process)
        before = list(replay.store.iter_raw())
        assert resumed.run(p['preparation_id']) == result
        assert list(replay.store.iter_raw()) == before
        assert server.calls == []
    finally:
        server.shutdown()
        server.server_close()


def test_independent_review_rejects_changed_diagnostic_conclusion(tmp_path, monkeypatch):
    truth, prep, server, p = _failure(tmp_path, monkeypatch)
    try:
        service = ExecutionDiagnosisService(prep, evidence_root=tmp_path / 'diagnosis')
        process = service._process
        def forged(request, path):
            result, proof = process(request, path)
            if request.get('mode') != 'REVIEW':
                result['failure_class'] = 'PRODUCT_DEFECT'
            return result, proof
        monkeypatch.setattr(service, '_process', forged)
        with pytest.raises(ContractError, match='N8_INDEPENDENT_REVIEW_REJECTED'):
            service.run(p['preparation_id'])
        assert truth.query('rc72_n8_process_diagnosis') == []
        assert truth.query('rc72_node_gate', node_type='N8_DIAGNOSIS_RECOVERY') == []
        assert truth.query('rc7_defect') == []
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize('event', ['RC72_NODE_GATE_UPSERTED', 'RC7_GAP_UPSERTED',
    'RC72_BACK_EDGE_UPSERTED', 'RC72_NODE_TRANSITION_UPSERTED', 'RC72_DIAGNOSIS_OUTCOME_UPSERTED'])
def test_partial_gate_and_back_edge_writes_resume_without_duplicate_gap_or_route(tmp_path, monkeypatch, event):
    truth, prep, server, p = _failure(tmp_path, monkeypatch)
    try:
        service = ExecutionDiagnosisService(prep, evidence_root=tmp_path / 'diagnosis')
        append = truth.append_atomic
        interrupted = []
        def crash(kind, payload, **kwargs):
            result = append(kind, payload, **kwargs)
            if kind == event and not interrupted and (kind != 'RC72_NODE_TRANSITION_UPSERTED' or payload['kind'] == 'BACK_EDGE'):
                interrupted.append(True)
                raise KeyboardInterrupt()
            return result
        monkeypatch.setattr(truth, 'append_atomic', crash)
        with pytest.raises(KeyboardInterrupt):
            service.run(p['preparation_id'])
        monkeypatch.setattr(truth, 'append_atomic', append)
        def no_process(*args):
            raise AssertionError('accepted process evidence must be reused')
        monkeypatch.setattr(service, '_process', no_process)
        result = service.run(p['preparation_id'])
        assert result['state'] == 'REPAIR_REQUIRED'
        assert len(truth.query('rc7_gap', category='TEST_DATA_GAP')) == 1
        assert len(truth.query('rc72_back_edge')) == 1
        assert len(truth.query('rc72_node_transition', kind='BACK_EDGE')) == 1
        before = list(truth.store.iter_raw())
        assert service.run(p['preparation_id']) == result
        assert list(truth.store.iter_raw()) == before
        assert server.calls == []
    finally:
        server.shutdown()
        server.server_close()


def test_live_data_restoration_cannot_reuse_old_gate_as_accepted_repair(tmp_path, monkeypatch):
    truth, prep, server, p = _failure(tmp_path, monkeypatch)
    try:
        service = ExecutionDiagnosisService(prep, evidence_root=tmp_path / 'diagnosis')
        service.run(p['preparation_id'])
        receipt = truth.query('rc72_n8_process_diagnosis')[0]
        failed_refs = receipt['result']['affected_refs']
        server.allowed_data_refs.update(failed_refs)
        admission = truth.query('rc72_n7_execution_admission', admission_id=p['admission_id'])[0]
        old_n5 = next(row['delivery_id'] for row in admission['upstream_refs'] if row['node_type'] == 'N5_TEST_DATA')
        before = list(truth.store.iter_raw())
        with pytest.raises(ContractError, match='N8_NEW_ACCEPTED_N5_REPAIR_REQUIRED'):
            service.record_accepted_repair(p['preparation_id'], repair_delivery_id=old_n5,
                                          changed_refs=failed_refs, reason='live data appeared again')
        assert list(truth.store.iter_raw()) == before
        assert truth.query('rc72_diagnosis_repair') == []
        assert truth.query('rc72_diagnosis_recovery') == []
        assert truth.query('execution_attempt')[0]['status'] == 'BLOCKED'
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize('tamper', ['receipt', 'process_bytes'])
def test_saved_n8_process_proof_cannot_be_changed_during_replay(tmp_path, monkeypatch, tamper):
    truth, prep, server, p = _failure(tmp_path, monkeypatch)
    try:
        service = ExecutionDiagnosisService(prep, evidence_root=tmp_path / 'diagnosis')
        service.run(p['preparation_id'])
        row = truth.query('rc72_n8_process_diagnosis')[0]
        if tamper == 'receipt':
            row['result']['failure_class'] = 'PRODUCT_DEFECT'
            row['artifact_version'] += 1
            truth.append_atomic('RC72_N8_PROCESS_DIAGNOSIS_UPSERTED', row)
        else:
            Path(row['review_process']['stdout_ref'][len('file://'):]).write_text('{"accepted":true}')
        before = list(truth.store.iter_raw())
        with pytest.raises(ContractError, match='N8_PROCESS_'):
            service.run(p['preparation_id'])
        assert list(truth.store.iter_raw()) == before
        assert truth.query('rc7_defect') == []
    finally:
        server.shutdown()
        server.server_close()
