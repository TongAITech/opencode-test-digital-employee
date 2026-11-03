"""Full product source chain and real HTTP/process N7, not bank Field proof."""
from http.server import ThreadingHTTPServer
import threading

from rc7_runtime.rc72_authority import RC72AuthorityRuntime
from rc7_runtime.rc72_canonical_design import CanonicalDesignService
from rc7_runtime.rc72_n7_execution_preparation import ExecutionPreparationService
from rc7_runtime.rc72_formal_runner import FormalN7RunnerAdapter
from rc7_runtime.rc72_n7_pipeline import N7PipelineService
from rc72_formal_runner_support import _Handler, _profile, _qualify, LocalHTTPEnvironment
from test_rc72_release_driver_n5 import _n5_driver
from rc72_n2_test_support import BATCH,COMMIT,RELEASE


def test_full_n1_to_n7_product_flow_uses_actual_process_http_cleanup_and_full_review(tmp_path,monkeypatch):
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
        assert truth.query('rc72_mission_node',node_type='N7_EXECUTION')[0]['state']=='READY'
        design=CanonicalDesignService(truth,release_id=RELEASE,source_commit=COMMIT).load(release_batch_id=BATCH)
        contracts=truth.query('rc72_n6_executable_contract')
        server.allowed_data_refs={r['data_ref'] for c in contracts for r in c['data_refs']}
        for case in design.cases:
            contract=next(c for c in contracts if c['case_id']==case['tc_id'])
            _qualify(tmp_path/'qualified'/case['tc_id'],case,contract)
        output=tmp_path/'actual-output'
        environment=LocalHTTPEnvironment(url,output)
        preparation=ExecutionPreparationService(truth,release_id=RELEASE,source_commit=COMMIT,
            authority=RC72AuthorityRuntime(b'product-real-execution-signing-key'),tool_registry={'api_http':['api_http']})
        runner=FormalN7RunnerAdapter(preparation,evidence_root=output,environment_adapter=environment,
            execution_env={'RC72_OUTPUT_ROOT':str(output)},timeout_seconds=30)
        driver.n7_pipeline=N7PipelineService(preparation,runner=runner,capture_root=tmp_path/'captured')
        result=driver.run(release_batch_id=BATCH)
        assert result['reason']=='NATIVE_PRODUCT_ROUTE_NOT_IMPLEMENTED'
        states={n['node_type']:n['state'] for n in result['nodes']}
        assert states['N7_EXECUTION']=='PASS' and states['N9_DEFECT']=='READY'
        assert result['mission_node_id']==next(n['mission_node_id'] for n in result['nodes'] if n['node_type']=='N9_DEFECT')
        assert states['N8_DIAGNOSIS_RECOVERY']=='NOT_STARTED'
        assert len(server.calls)==len(design.cases)
        assert len(truth.query('execution_attempt'))==len(design.cases)
        assert all(r['state']=='RELEASED' for r in truth.query('rc72_data_lease'))
        from rc7_runtime.rc72_obligation_execution_proof import AcceptedObligationExecutionProof
        before=truth.store.path.read_bytes()
        proof=AcceptedObligationExecutionProof(driver.n7_pipeline).audit(release_batch_id=BATCH)
        assert set(proof['verified_obligation_ids'])=={o.obligation_id for o in design.obligations}
        assert proof['case_count']==len(design.cases)
        assert len(proof['attempt_ids'])==len(design.cases)
        assert truth.store.path.read_bytes()==before and len(server.calls)==len(design.cases)
        count=len(calls)
        assert driver.run(release_batch_id=BATCH)==result
        assert truth.store.path.read_bytes()==before and len(calls)==count and len(server.calls)==len(design.cases)
        # The same full original scope may clear deterministic N9 only when
        # accepted proof and actual R1 intake contain no unresolved discrepancy.
        from rc7_runtime.rc72_n9_accepted_scope import AcceptedScopeN9Service
        driver.n9_pipeline=AcceptedScopeN9Service(driver.n7_pipeline)
        continued=driver.run(release_batch_id=BATCH)
        states={n['node_type']:n['state'] for n in continued['nodes']}
        assert states['N9_DEFECT']=='PASS' and states['N10_RELEASE_CONVERGENCE']=='READY'
        assert continued['reason']=='NATIVE_PRODUCT_ROUTE_NOT_IMPLEMENTED'
        assert continued['mission_node_id']==next(n['mission_node_id'] for n in continued['nodes'] if n['node_type']=='N10_RELEASE_CONVERGENCE')
        assert len(server.calls)==len(design.cases) and len(calls)==count
        assert len(truth.query('execution_attempt'))==len(design.cases)
        assert not truth.query('rc7_defect')
        # The inactive N8 branch must not prevent N9 from being reaudited
        # during accepted-prefix continuation.
        clearance=truth.query('rc72_n9_accepted_scope')[0]
        clearance.update(signature='0'*64,artifact_version=clearance['artifact_version']+1)
        truth.append_atomic('RC72_N9_ACCEPTED_SCOPE_UPSERTED',clearance)
        import pytest
        from rc7_runtime.models import ContractError
        before=truth.store.path.read_bytes()
        with pytest.raises(ContractError,match='N9_ACCEPTED_SCOPE_SIGNATURE_INVALID'):
            driver.run(release_batch_id=BATCH)
        assert truth.store.path.read_bytes()==before
        assert len(server.calls)==len(design.cases) and len(calls)==count
    finally:
        server.shutdown()
        server.server_close()
