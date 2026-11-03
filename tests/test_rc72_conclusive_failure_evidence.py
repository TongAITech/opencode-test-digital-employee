"""A real successful process can yield a valid frozen business discrepancy."""
from pathlib import Path

import pytest
from rc7_runtime.models import ContractError
from rc7_runtime.rc72_formal_runner import FormalN7RunnerAdapter
from rc7_runtime.rc72_n7_pipeline import N7PipelineService
from rc7_runtime.rc72_n8_execution_diagnosis import ExecutionDiagnosisService
from rc72_formal_runner_support import formal_setup,LocalHTTPEnvironment
from rc72_n2_test_support import BATCH


def _failed_business(tmp_path,monkeypatch,*,fail=False):
    def approved_expectation(candidate):
        for case in candidate['cases']:
            for check in case['oracle']['checks']:
                if check['type']=='BUSINESS_RULE':
                    check['expected']='APPROVED_DIFFERENT_EXPECTATION'
    truth,plan,prep,server,url=formal_setup(tmp_path,monkeypatch,design_mutator=approved_expectation,fail=fail)
    output=tmp_path/'actual-output'
    runner=FormalN7RunnerAdapter(prep,evidence_root=output,environment_adapter=LocalHTTPEnvironment(url,output),
        execution_env={'RC72_OUTPUT_ROOT':str(output)},timeout_seconds=30)
    return truth,plan,prep,server,url,N7PipelineService(prep,runner=runner,capture_root=tmp_path/'capture')


def test_full_native_discrepancy_is_independently_diagnosed_for_n9_without_product_defect_or_replay(tmp_path,monkeypatch):
    truth,plan,prep,server,url,pipeline=_failed_business(tmp_path,monkeypatch)
    try:
        result=pipeline.complete(release_batch_id=BATCH)
        assert result['reason']=='N9_FAILURE_QUALIFICATION_REQUIRED'
        assert result['failure_class']=='VALID_TEST_FAILURE' and result['next_node']=='N9_DEFECT'
        assert len(server.calls)==1 and server.restored
        attempt=truth.query('execution_attempt')[0]
        assert attempt['status']=='BLOCKED' and attempt['assertion_passed'] is False
        states={r['node_type']:r['state'] for r in truth.query('rc72_mission_node')}
        assert states['N7_EXECUTION']=='NEEDS_REVISION' and states['N8_DIAGNOSIS_RECOVERY']=='PASS'
        assert states['N9_DEFECT']=='NEEDS_REVISION'
        receipt=truth.query('rc72_n8_process_diagnosis')[0]
        assert receipt['diagnostic_process']['pid']!=receipt['review_process']['pid']
        assert receipt['diagnosis_worker_id']!=receipt['reviewer_worker_id']!=attempt['worker_id']
        assert not truth.query('rc7_defect')
        assert not truth.query('rc72_node_gate',node_type='N7_EXECUTION')
        assert len(truth.query('rc72_n7_execution_plan')[0]['items'])==len(plan['items'])
        before=truth.store.path.read_bytes()
        assert pipeline.complete(release_batch_id=BATCH)==result
        assert truth.store.path.read_bytes()==before and len(server.calls)==1
        from rc6_runtime.truth import TruthRuntime
        from rc7_runtime.rc72_authority import RC72AuthorityRuntime
        from rc7_runtime.rc72_n7_execution_preparation import ExecutionPreparationService
        import rc7_runtime.rc72_n8_execution_diagnosis as diagnosis
        cold_truth=TruthRuntime(truth.store.path)
        cold_prep=ExecutionPreparationService(cold_truth,release_id=prep.release_id,source_commit=prep.source_commit,
            authority=RC72AuthorityRuntime(prep.authority._key),tool_registry=prep.tool_registry)
        cold_runner=FormalN7RunnerAdapter(cold_prep,evidence_root=pipeline.runner.root,
            environment_adapter=LocalHTTPEnvironment(url,pipeline.runner.root),
            execution_env={'RC72_OUTPUT_ROOT':str(pipeline.runner.root)},timeout_seconds=30)
        cold=N7PipelineService(cold_prep,runner=cold_runner,capture_root=pipeline.review.capture_root)
        def no_child(*args,**kwargs):
            raise AssertionError('accepted cold diagnosis must not spawn another business or diagnostic process')
        with monkeypatch.context() as patch:
            patch.setattr(diagnosis.subprocess,'Popen',no_child)
            assert cold.complete(release_batch_id=BATCH)==result
        assert cold_truth.store.path.read_bytes()==before and len(server.calls)==1
        assert not cold_prep.authority._leases
    finally:
        server.shutdown();server.server_close()


def test_missing_required_file_cannot_upgrade_a_business_discrepancy(tmp_path,monkeypatch):
    truth,plan,prep,server,url,pipeline=_failed_business(tmp_path,monkeypatch)
    cleanup=pipeline.cleanup.run
    def remove_file(preparation_id):
        result=cleanup(preparation_id)
        dispatch=truth.query('rc72_n7_tool_dispatch',preparation_id=preparation_id)[0]
        (pipeline.runner.root/dispatch['raw_result']['evidence'][0]['path']).unlink()
        return result
    monkeypatch.setattr(pipeline.cleanup,'run',remove_file)
    try:
        result=pipeline.complete(release_batch_id=BATCH)
        assert result['reason']=='N7_CONCLUSIVE_FAILURE_EVIDENCE_INCOMPLETE'
        assert not truth.query('rc72_node_gate',node_type='N8_DIAGNOSIS_RECOVERY')
        assert not truth.query('rc72_n8_process_diagnosis')
        assert len(server.calls)==1 and server.restored
    finally:
        server.shutdown();server.server_close()


def test_runner_process_failure_does_not_automatically_cleanup_or_replay(tmp_path,monkeypatch):
    truth,plan,prep,server,url,pipeline=_failed_business(tmp_path,monkeypatch,fail=True)
    try:
        result=pipeline.complete(release_batch_id=BATCH)
        assert result['reason']=='N7_EXECUTION_DIAGNOSIS_REQUIRED'
        assert len(server.calls)==1 and server.restored is False
        assert not truth.query('rc72_n7_cleanup_call')
        attempt=truth.query('execution_attempt')[0]
        assert attempt['status']=='BLOCKED' and attempt['reason']=='RUNNER_PROCESS_FAILED'
        assert all(r['state']=='ACTIVE' for r in truth.query('rc72_data_lease'))
        before=truth.store.path.read_bytes()
        assert pipeline.complete(release_batch_id=BATCH)==result
        assert truth.store.path.read_bytes()==before and len(server.calls)==1
    finally:
        server.shutdown();server.server_close()


def test_captured_failure_bytes_changed_before_diagnosis_are_rejected_without_gate(tmp_path,monkeypatch):
    truth,plan,prep,server,url,pipeline=_failed_business(tmp_path,monkeypatch)
    diagnose=pipeline.diagnosis.run
    def corrupt(preparation_id):
        admitted=pipeline.failure_evidence.audit(preparation_id)
        ref=admitted['proof']['captured_evidence'][0]['content_ref']
        Path(ref[len('file://'):]).write_bytes(b'changed captured bytes')
        return diagnose(preparation_id)
    monkeypatch.setattr(pipeline.diagnosis,'run',corrupt)
    try:
        with pytest.raises(ContractError,match='CAPTURE_BYTES_OR_SCOPE_CHANGED'):
            pipeline.complete(release_batch_id=BATCH)
        assert not truth.query('rc72_node_gate',node_type='N8_DIAGNOSIS_RECOVERY')
        assert not truth.query('rc72_n8_process_diagnosis')
        assert len(server.calls)==1 and server.restored
    finally:
        server.shutdown();server.server_close()


def test_independent_reviewer_rejects_forged_product_defect_then_cold_diagnosis_recovers_without_business_replay(tmp_path,monkeypatch):
    import sys
    import rc7_runtime.rc72_n8_execution_diagnosis as diagnosis
    truth,plan,prep,server,url,pipeline=_failed_business(tmp_path,monkeypatch)
    original=diagnosis.subprocess.Popen
    forged='''import json,sys
from pathlib import Path
x=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
print(json.dumps(dict(diagnosis_id=x['diagnosis_id'],input_sha256=x['input_sha256'],
failure_class='PRODUCT_DEFECT',confidence='forged claim',affected_refs=[x['facts']['case_id']],
rationale='unproven product causality',requested_remediation='invalid automatic defect')))
'''
    def process(command,**kwargs):
        if command[-1].endswith('/diagnosis.json') or command[-1].endswith('\\diagnosis.json'):
            return original([sys.executable,'-I','-c',forged,command[-1]],**kwargs)
        return original(command,**kwargs)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(diagnosis.subprocess,'Popen',process)
            with pytest.raises(ContractError,match='INDEPENDENT_REVIEW_REJECTED'):
                pipeline.complete(release_batch_id=BATCH)
        assert not truth.query('rc72_node_gate',node_type='N8_DIAGNOSIS_RECOVERY')
        assert not truth.query('rc7_defect') and len(server.calls)==1
        # A new diagnosis graph consumes the original actual failure/captures.
        pipeline.diagnosis=ExecutionDiagnosisService(prep,evidence_root=pipeline.review.capture_root/'diagnosis',
            failure_evidence=pipeline.failure_evidence)
        result=pipeline.complete(release_batch_id=BATCH)
        assert result['failure_class']=='VALID_TEST_FAILURE' and len(server.calls)==1
        assert not truth.query('rc7_defect')
    finally:
        server.shutdown();server.server_close()


@pytest.mark.parametrize('stage',['capture','failure-proof','diagnosis-receipt'])
def test_native_failure_fsync_interruption_resumes_cold_without_business_replay(tmp_path,monkeypatch,stage):
    from rc6_runtime.truth import TruthRuntime
    from rc7_runtime.rc72_authority import RC72AuthorityRuntime
    from rc7_runtime.rc72_n7_execution_preparation import ExecutionPreparationService
    from rc7_runtime.rc72_conclusive_failure_evidence import KIND
    import rc7_runtime.rc72_n8_execution_diagnosis as diagnosis
    truth,plan,prep,server,url,pipeline=_failed_business(tmp_path,monkeypatch)
    append=truth.append_atomic
    def interrupt(event,payload):
        result=append(event,payload)
        match=(stage=='capture' and event=='EVIDENCE_UPSERTED' and payload.get('kind')=='N7_REQUIRED_EVIDENCE_FILE'
               or stage=='failure-proof' and event=='RC7_EVIDENCE_UPSERTED' and payload.get('kind')==KIND
               or stage=='diagnosis-receipt' and event=='RC72_N8_PROCESS_DIAGNOSIS_UPSERTED')
        if match:
            raise KeyboardInterrupt('interrupted after actual fsync')
        return result
    monkeypatch.setattr(truth,'append_atomic',interrupt)
    try:
        with pytest.raises(KeyboardInterrupt):
            pipeline.complete(release_batch_id=BATCH)
        assert len(server.calls)==1 and server.restored
        cold_truth=TruthRuntime(truth.store.path)
        cold_prep=ExecutionPreparationService(cold_truth,release_id=prep.release_id,source_commit=prep.source_commit,
            authority=RC72AuthorityRuntime(prep.authority._key),tool_registry=prep.tool_registry)
        runner=FormalN7RunnerAdapter(cold_prep,evidence_root=pipeline.runner.root,
            environment_adapter=LocalHTTPEnvironment(url,pipeline.runner.root),
            execution_env={'RC72_OUTPUT_ROOT':str(pipeline.runner.root)},timeout_seconds=30)
        cold=N7PipelineService(cold_prep,runner=runner,capture_root=pipeline.review.capture_root)
        def no_child(*args,**kwargs):
            raise AssertionError('persisted accepted diagnosis must not run another process')
        with monkeypatch.context() as patch:
            if stage=='diagnosis-receipt':
                patch.setattr(diagnosis.subprocess,'Popen',no_child)
            result=cold.complete(release_batch_id=BATCH)
        assert result['failure_class']=='VALID_TEST_FAILURE' and len(server.calls)==1
        assert len(cold_truth.query('rc7_evidence',kind=KIND))==1
        assert not cold_prep.authority._leases
    finally:
        server.shutdown();server.server_close()


def test_rehashed_failure_file_and_canonical_pointers_cannot_forge_runtime_signature(tmp_path,monkeypatch):
    import json,hashlib
    truth,plan,prep,server,url,pipeline=_failed_business(tmp_path,monkeypatch)
    diagnose=pipeline.diagnosis.run
    def forged(preparation_id):
        admitted=pipeline.failure_evidence.audit(preparation_id)
        proof=admitted['proof']
        proof['signature']='0'*64
        data=json.dumps(proof,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()
        digest=hashlib.sha256(data).hexdigest()
        path=pipeline.review.capture_root/(digest+'.json')
        path.write_bytes(data)
        row=truth.query('rc7_evidence',evidence_id=admitted['evidence_id'])[0]
        row.update(content_ref='file://'+str(path),content_hash=digest,artifact_version=row['artifact_version']+1)
        truth.append_atomic('RC7_EVIDENCE_UPSERTED',row)
        canonical=truth.query('evidence',id=admitted['evidence_id'])[0]
        canonical.update(ref=row['content_ref'],artifact_version=canonical['artifact_version']+1)
        truth.append_atomic('EVIDENCE_UPSERTED',canonical)
        return diagnose(preparation_id)
    monkeypatch.setattr(pipeline.diagnosis,'run',forged)
    try:
        with pytest.raises(ContractError,match='PROOF_SIGNATURE_INVALID'):
            pipeline.complete(release_batch_id=BATCH)
        assert not truth.query('rc72_node_gate',node_type='N8_DIAGNOSIS_RECOVERY')
        assert not truth.query('rc72_n8_process_diagnosis')
        assert len(server.calls)==1
    finally:
        server.shutdown();server.server_close()
