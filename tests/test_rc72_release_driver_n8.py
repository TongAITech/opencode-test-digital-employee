"""Formal ReleaseBatch.run N7 failed HTTP -> non-bypass N8 -> N5 repair boundary.

Uses the real product entry, signed N7 tool dispatch, local HTTP precondition
failure, isolated N8 processes and fenced physical cleanup. No fake PASS,
case substitution, old Attempt replay or invented N5 verification.
"""
from http.server import ThreadingHTTPServer
import threading

from rc7_runtime.rc72_authority import RC72AuthorityRuntime
from rc7_runtime.rc72_canonical_design import CanonicalDesignService
from rc7_runtime.rc72_formal_runner import FormalN7RunnerAdapter
from rc7_runtime.rc72_n7_execution_preparation import ExecutionPreparationService
from rc7_runtime.rc72_n7_pipeline import N7PipelineService
from rc7_runtime.rc72_n8_product_recovery import NativeN8ProductRecoveryService
from rc72_formal_runner_support import _Handler, _profile, _qualify, LocalHTTPEnvironment
from test_rc72_release_driver_n5 import _n5_driver
from rc72_n2_test_support import BATCH, COMMIT, RELEASE


def test_release_driver_non_bypass_n8_uses_real_n7_failed_http_and_immutable_attempt(tmp_path,monkeypatch):
    import test_rc72_release_driver as n1_source
    server=ThreadingHTTPServer(('127.0.0.1',0),_Handler)
    server.calls,server.restored,server.allowed_data_refs,server.precondition_ready=[],True,set(),True
    threading.Thread(target=server.serve_forever,daemon=True).start()
    url='http://127.0.0.1:%d'%server.server_address[1]
    original=n1_source._binding

    def binding():
        value=original()
        value['endpoint']['url']=url+'/config/query'
        profile=_profile(url,value['environment'])
        value['environment'].update(target_profile=profile,deployed_release_id=RELEASE)
        value['authoritative_sources'] += [f['source_ref'] for f in profile['facts']]
        return value

    monkeypatch.setattr(n1_source,'_binding',binding)
    try:
        truth,driver,calls=_n5_driver(tmp_path,materialized=True,runner_root=tmp_path/'qualified')
        staged=driver.run(release_batch_id=BATCH)
        assert staged['reason']=='NATIVE_PRODUCT_ROUTE_NOT_IMPLEMENTED'
        design=CanonicalDesignService(truth,release_id=RELEASE,source_commit=COMMIT).load(release_batch_id=BATCH)
        contracts=truth.query('rc72_n6_executable_contract')
        server.allowed_data_refs={r['data_ref'] for c in contracts for r in c['data_refs']}
        for case in design.cases:
            contract=next(c for c in contracts if c['case_id']==case['tc_id'])
            _qualify(tmp_path/'qualified'/case['tc_id'],case,contract)
        # The physical target loses exact DataRefs only after source N1..N6
        # admission; this is an actual changed precondition, not a fake Error.
        server.allowed_data_refs.clear()
        root=tmp_path/'native-runner'
        prep=ExecutionPreparationService(truth,release_id=RELEASE,source_commit=COMMIT,
            authority=RC72AuthorityRuntime(b'product-failed-n8-authority-key'),
            tool_registry={'api_http':['api_http']})
        environment=LocalHTTPEnvironment(url,root)
        runner=FormalN7RunnerAdapter(prep,evidence_root=root,
            environment_adapter=environment,
            execution_env={'RC72_OUTPUT_ROOT':str(root)},timeout_seconds=30)
        driver.n7_pipeline=N7PipelineService(prep,runner=runner,
            capture_root=tmp_path/'captured')
        driver.n8_pipeline=NativeN8ProductRecoveryService(driver.n7_pipeline)
        result=driver.run(release_batch_id=BATCH)
        assert result['status']=='HOLD' and result['reason']=='N8_VERIFIED_N5_REPAIR_REQUIRED'
        assert result['failure_class']=='TEST_DATA_GAP' and result['affected_data_refs']
        assert result['field_verified'] is result['bank_final'] is False
        n8=truth.query('rc72_mission_node',node_type='N8_DIAGNOSIS_RECOVERY')[0]
        assert n8['state']=='PASS' and n8['gate_refs']
        assert truth.query('rc72_mission_node',node_type='N5_TEST_DATA')[0]['state']=='RUNNING'
        assert truth.query('rc72_mission_node',node_type='N7_EXECUTION')[0]['state']=='NOT_STARTED'
        original_attempts=truth.query('execution_attempt')
        assert len(original_attempts)==1 and original_attempts[0]['status']=='BLOCKED'
        assert truth.query('rc72_n8_repair_boundary')[0]['state']=='REPAIR_OPEN'
        assert all(lease['state']=='RELEASED' for lease in truth.query('rc72_data_lease'))
        assert not truth.query('rc72_diagnosis_repair')
        assert not truth.query('rc7_defect')
        assert not server.calls
        before=truth.store.path.read_bytes()
        before_n1_to_n5=len(calls)
        assert driver.run(release_batch_id=BATCH)==result
        assert truth.store.path.read_bytes()==before
        assert len(calls)==before_n1_to_n5 and server.calls==[]
        assert truth.query('execution_attempt')==original_attempts
    finally:
        server.shutdown();server.server_close()
