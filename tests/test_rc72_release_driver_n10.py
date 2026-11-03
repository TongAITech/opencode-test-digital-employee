"""Full original N4 source denominator, actual N1 read/N7 HTTP/N10 collection.

Initial domain/tool approvals are fixture protocol children; this is engineering
qualification, never bank Field or physical L1..L7 completion.
"""
import json,subprocess,sys,threading
from pathlib import Path
from http.server import ThreadingHTTPServer
import pytest
from rc72_n2_test_support import BATCH,COMMIT,MISSION,RELEASE
from rc72_formal_runner_support import _Handler as BusinessHandler,_profile,_qualify,LocalHTTPEnvironment
from test_rc72_libra_measurement import _Handler as CoverageHandler
from test_rc72_release_driver_n5 import _n5_driver
from test_rc72_expected_scope_input import CHILD
from rc7_runtime.rc72_authority import RC72AuthorityRuntime
from rc7_runtime.rc72_native_n1_launcher import NativeN1ReadDshLauncher
from rc7_runtime.rc72_native_n1_read_gate import N1ReadResource,TOOL
from rc7_runtime.rc72_n1_strict_pipeline import N1StrictPipelineService
from rc7_runtime.rc72_expected_scope_input import ExpectedScopeInputService
from rc7_runtime.rc72_canonical_design import CanonicalDesignService
from rc7_runtime.rc72_n7_execution_preparation import ExecutionPreparationService
from rc7_runtime.rc72_formal_runner import FormalN7RunnerAdapter
from rc7_runtime.rc72_n7_pipeline import N7PipelineService
from rc7_runtime.rc72_n9_accepted_scope import AcceptedScopeN9Service
from rc7_runtime.rc72_libra_measurement import NativeLibraMeasurementService
from rc7_runtime.rc72_native_coverage_intake import NativeCoverageGapIntakeService
from rc7_runtime.rc72_native_coverage_diagnosis import NativeCoveragePathDiagnosisService
from rc7_runtime.rc72_n10_control import NativeN10ControlService


def test_full_original_source_driver_enters_actual_n10_without_erasing_missing_levels(tmp_path,monkeypatch,record_property):
    import test_rc72_release_driver as source
    business=ThreadingHTTPServer(('127.0.0.1',0),BusinessHandler)
    business.calls,business.restored,business.allowed_data_refs,business.precondition_ready=[],True,set(),True
    coverage=ThreadingHTTPServer(('127.0.0.1',0),CoverageHandler)
    coverage.calls,coverage.app=[], 'BLOAN'
    def all_covered(row):
        for unit in row['units']:unit['covered']=True
    coverage.mutate=all_covered
    for server in (business,coverage):threading.Thread(target=server.serve_forever,daemon=True).start()
    url='http://127.0.0.1:%d'%business.server_address[1]
    original=source._binding
    def binding():
        value=original();value['endpoint']['url']=url+'/config/query'
        profile=_profile(url,value['environment']);value['environment'].update(target_profile=profile,deployed_release_id=RELEASE)
        value['authoritative_sources'] += [f['source_ref'] for f in profile['facts']]
        return value
    monkeypatch.setattr(source,'_binding',binding)
    try:
        truth,driver,calls=_n5_driver(tmp_path,materialized=True,runner_root=tmp_path/'qualified')
        batch=truth.query('rc72_release_batch')[0]
        policy=dict(schema='RC72_EXPECTED_RELEASE_SCOPE_V2',release_id=RELEASE,release_batch_id=BATCH,mission_id=MISSION,source_commit=COMMIT,
            application_ids=batch['application_ids'],version_ids=batch['version_ids'],
            requirement_ssts={r:['SST-'+r] for r in batch['requirement_ids']},
            required_levels_by_sst={'SST-'+r:['L1','L2','L3','L4','L5','L6','L7'] for r in batch['requirement_ids']},
            source_refs=['catalog://original-full-source-policy/v1'],coverage_targets={app:dict(metric='LINE',base_revision='base-a',
                target_revision='target-b',target_ratio=.9,report_url='http://127.0.0.1:%d/report'%coverage.server_address[1],
                auth_mode='ANONYMOUS',source_ref='catalog://original-coverage-policy/v1') for app in batch['application_ids']})
        policy_file=tmp_path/'original-full-policy.json';policy_file.write_text(json.dumps(policy))
        candidate=source._good_candidate()
        candidate['facts'].update(release_id=RELEASE,release_batch_id=BATCH,source_commit=COMMIT)
        candidate['facts']['deployment_records'][0]['application_id']='BLOAN'
        runtime=source._binding();runtime.update(release_id=RELEASE,mission_id=MISSION,release_batch_id=BATCH,source_commit=COMMIT)
        runtime['tool_route']['family']='API';candidate['facts']['executable_bindings']=[runtime]
        candidate_file=tmp_path/'n1-full-candidate.json';candidate_file.write_text(json.dumps(candidate))
        child=tmp_path/'n1-native-full.py';child.write_text(CHILD.replace('import json,os,subprocess,sys','import json,os,subprocess,sys\nfrom pathlib import Path')
            .replace("candidate=json.loads(values[1]['text'])","candidate=json.loads(Path(sys.argv[3]).read_text())"))
        patch=tmp_path/'native-n1-patch.json';patch.write_text('{}');native_calls=[]
        def run(command,**kwargs):
            native_calls.append(1)
            return subprocess.run([sys.executable,str(child),str(Path(__file__).resolve().parents[1]),
                json.dumps(['release-batch://'+BATCH]),str(candidate_file)],**kwargs)
        launcher=NativeN1ReadDshLauncher(resources=[N1ReadResource('release-batch://'+BATCH,policy_file)],
            dsh_bin=sys.executable,patch_path=str(patch),cwd=str(tmp_path),truth=truth,
            authority=RC72AuthorityRuntime(b'full-n10-original-policy-key'),coordinator_instance_id='full-n10-controller',
            release_id=RELEASE,state_root=str(tmp_path/'n1-native-state'),command_runner=run)
        driver.n1_launcher=launcher;driver.n1_tools=(TOOL,)
        driver.expected_scope=ExpectedScopeInputService(N1StrictPipelineService(truth,source_commit=COMMIT,launcher=launcher,allowed_tools=[TOOL]))
        staged=driver.run(release_batch_id=BATCH)
        assert staged['reason']=='NATIVE_PRODUCT_ROUTE_NOT_IMPLEMENTED'
        assert truth.query('rc72_mission_node',node_type='N7_EXECUTION')[0]['state']=='READY'
        design=CanonicalDesignService(truth,release_id=RELEASE,source_commit=COMMIT).load(release_batch_id=BATCH)
        contracts=truth.query('rc72_n6_executable_contract')
        business.allowed_data_refs={r['data_ref'] for c in contracts for r in c['data_refs']}
        for case in design.cases:
            contract=next(c for c in contracts if c['case_id']==case['tc_id'])
            _qualify(tmp_path/'qualified'/case['tc_id'],case,contract)
        output=tmp_path/'actual-output';environment=LocalHTTPEnvironment(url,output)
        preparation=ExecutionPreparationService(truth,release_id=RELEASE,source_commit=COMMIT,
            authority=RC72AuthorityRuntime(b'full-n10-real-execution-key'),tool_registry={'api_http':['api_http']})
        driver.n7_pipeline=N7PipelineService(preparation,runner=FormalN7RunnerAdapter(preparation,evidence_root=output,
            environment_adapter=environment,execution_env={'RC72_OUTPUT_ROOT':str(output)},timeout_seconds=30),capture_root=tmp_path/'n7-captured')
        driver.n9_pipeline=AcceptedScopeN9Service(driver.n7_pipeline)
        measurement=NativeLibraMeasurementService(driver.expected_scope,driver.n9_pipeline,capture_root=tmp_path/'libra-captured')
        intake=NativeCoverageGapIntakeService(measurement)
        diagnosis=NativeCoveragePathDiagnosisService(intake,evidence_root=tmp_path/'coverage-diagnosis')
        driver.n10_pipeline=NativeN10ControlService(driver.expected_scope,driver.n9_pipeline,measurement,intake,diagnosis)
        result=driver.run(release_batch_id=BATCH)
        assert result['reason']=='N10_RELEASE_NOT_CONVERGED' and result['convergence_result']=='NOT_CONVERGED'
        assert len(design.cases)==28 and len(business.calls)==len(design.cases)
        assert len(truth.query('execution_attempt'))==len(design.cases) and len(coverage.calls)==1 and native_calls==[1]
        assert any(b.startswith('scope:missing-level:') for b in result['blockers'])
        assert all(len(levels)==7 for levels in truth.query('rc72_release_scope_manifest')[0]['required_levels_by_sst'].values())
        assert truth.query('rc72_mission_node',node_type='N10_RELEASE_CONVERGENCE')[0]['state']=='RUNNING'
        assert not truth.query('rc72_node_gate',node_type='N10_RELEASE_CONVERGENCE') and not truth.query('rc7_defect')
        count=len(calls)
        again=driver.run(release_batch_id=BATCH)
        assert again['reason']=='N10_RELEASE_NOT_CONVERGED' and len(calls)==count and native_calls==[1]
        assert len(business.calls)==len(design.cases) and len(coverage.calls)==1
        driver.n10_pipeline=None
        before=truth.store.path.read_bytes()
        with pytest.raises(Exception,match='NATIVE_N10_PROVIDER_REQUIRED'):driver.run(release_batch_id=BATCH)
        assert truth.store.path.read_bytes()==before
        record_property('original_case_count',len(design.cases));record_property('original_obligation_count',len(design.obligations))
        record_property('actual_business_calls',len(business.calls));record_property('actual_coverage_reads',len(coverage.calls))
        record_property('original_required_levels_preserved',7)
    finally:
        for server in (business,coverage):server.shutdown();server.server_close()
