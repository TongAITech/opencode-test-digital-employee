"""Actual N1 MCP reads -> independent expected scope, before observed Cases."""
import json,subprocess,sys
from pathlib import Path
import pytest

import test_rc72_n1_completion as original
from test_rc72_n1_strict_pipeline import _candidate_with_binding
from rc7_runtime.rc72_n1_strict_pipeline import N1StrictPipelineService
from rc7_runtime.rc72_native_n1_launcher import NativeN1ReadDshLauncher
from rc7_runtime.rc72_native_n1_read_gate import N1ReadResource,TOOL
from rc7_runtime.rc72_authority import RC72AuthorityRuntime
from rc7_runtime.rc72_expected_scope_input import ExpectedScopeInputService
from rc7_runtime.rc72_release_scope import ReleaseScopeService


CHILD='''import json,os,subprocess,sys
context=json.loads(os.environ['PFC_RC72_TOOL_GATE_CONTEXT'])
values=[]
for i,ref in enumerate(json.loads(sys.argv[2])):
 message=dict(jsonrpc='2.0',id=i+1,method='tools/call',params=dict(name='read_scoped_reality_source',arguments=dict(source_ref=ref,mission_context=context)))
 child=subprocess.run([sys.executable,'-m','rc7_release.mcp_server_authorized'],cwd=sys.argv[1],input=json.dumps(message)+'\\n',text=True,capture_output=True,env=os.environ)
 response=json.loads(child.stdout)
 if 'error' in response:raise RuntimeError(response)
 values.append(json.loads(response['result']['content'][0]['text']))
candidate=json.loads(values[1]['text'])
candidate['facts']['expected_scope_input']=dict(source_ref=values[0]['source_ref'],sha256=values[0]['sha256'])
print(json.dumps(dict(type='session',session_id='session-native-expected-scope')))
for value in values:print(json.dumps(dict(type='tool_call',tool_name='mcp__pfc_aitest_rc7__read_scoped_reality_source')))
print(json.dumps(dict(type='final',text=json.dumps(candidate))))
'''


def _setup(tmp_path,mutate=None,raw_mutate=None,repeat_policy=False):
    truth=original._truth(tmp_path);original._seed(truth)
    batch=truth.query('rc72_release_batch')[0]
    policy=dict(schema='RC72_EXPECTED_RELEASE_SCOPE_V1',release_id=batch['release_id'],release_batch_id=original.BATCH,
        mission_id=original.MISSION,source_commit=original.COMMIT,application_ids=batch['application_ids'],version_ids=batch.get('version_ids',[]),
        requirement_ssts={r:['EXPECTED-SST-A','EXPECTED-SST-B'] for r in batch['requirement_ids']},
        required_levels_by_sst={s:['L1','L2','L3','L4','L5','L6','L7'] for s in ['EXPECTED-SST-A','EXPECTED-SST-B']},
        source_refs=['catalog://authoritative-release-scope/v1'])
    if mutate:mutate(policy)
    source=tmp_path/'expected.json';data=json.dumps(policy)
    source.write_text(raw_mutate(data) if raw_mutate else data,encoding='utf-8')
    candidate=tmp_path/'candidate.json';candidate.write_text(json.dumps(_candidate_with_binding()),encoding='utf-8')
    assignment=truth.query('rc72_mission_node_worker_assignment')[0]
    refs=[assignment['input_refs'][0],assignment['input_refs'][-1]]
    registered_refs=list(refs)
    if repeat_policy:refs.append(refs[0])
    script=tmp_path/'worker.py';script.write_text(CHILD,encoding='utf-8')
    patch=tmp_path/'patch.json';patch.write_text('{}')
    calls=[]
    def runner(command,**kwargs):
        calls.append(1)
        return subprocess.run([sys.executable,str(script),str(Path(__file__).resolve().parents[1]),json.dumps(refs)],**kwargs)
    launcher=NativeN1ReadDshLauncher(resources=[N1ReadResource(registered_refs[0],source),N1ReadResource(registered_refs[1],candidate)],
        dsh_bin=sys.executable,patch_path=str(patch),cwd=str(tmp_path),truth=truth,
        authority=RC72AuthorityRuntime(b'expected-policy-test-key'),coordinator_instance_id='controller',
        release_id=original.RELEASE,state_root=str(tmp_path/'state'),command_runner=runner)
    pipeline=N1StrictPipelineService(truth,source_commit=original.COMMIT,launcher=launcher,allowed_tools=[TOOL])
    return truth,pipeline,ExpectedScopeInputService(pipeline),calls,source


def test_freezes_original_expected_catalog_without_observed_case_denominator_or_second_worker(tmp_path):
    truth,pipeline,service,calls,source=_setup(tmp_path)
    before=truth.store.path.read_bytes()
    with pytest.raises(Exception,match='ACCEPTED_N1_REQUIRED'):service.freeze(release_batch_id=original.BATCH)
    assert not calls and truth.store.path.read_bytes()==before
    pipeline.complete(release_batch_id=original.BATCH)
    result=service.freeze(release_batch_id=original.BATCH)
    manifest=truth.query('rc72_release_scope_manifest')[0]
    assert set(manifest['required_levels_by_sst'])=={'EXPECTED-SST-A','EXPECTED-SST-B'}
    assert all(len(levels)==7 for levels in manifest['required_levels_by_sst'].values())
    assert not truth.query('rc72_test_obligation')
    assert len(calls)==1
    before=truth.store.path.read_bytes();source.unlink()
    assert service.freeze(release_batch_id=original.BATCH)==result
    assert truth.store.path.read_bytes()==before and len(calls)==1
    denominator=ReleaseScopeService(truth,release_id=original.RELEASE).evaluate_denominator(manifest_id=result['manifest_id'])
    assert denominator.denominator_complete is False and len(denominator.missing_ssts)==2


@pytest.mark.parametrize('change',['source','requirements','levels','application','version'])
def test_foreign_or_incomplete_catalog_cannot_freeze_scope(tmp_path,change):
    def mutate(policy):
        if change=='source':policy['source_commit']='0'*40
        elif change=='requirements':policy['requirement_ssts']={}
        elif change=='levels':policy['required_levels_by_sst']['EXPECTED-SST-A']=['L3','L3']
        elif change=='version':policy['version_ids']=['OTHER-VERSION']
        else:policy['application_ids']=['OTHER-APP']
    truth,pipeline,service,calls,source=_setup(tmp_path,mutate)
    pipeline.complete(release_batch_id=original.BATCH)
    before=truth.store.path.read_bytes()
    with pytest.raises(Exception,match='EXPECTED_SCOPE_'):service.freeze(release_batch_id=original.BATCH)
    assert truth.store.path.read_bytes()==before
    assert not truth.query('rc72_release_scope_manifest') and not truth.query('rc72_expected_scope_input')


def test_duplicate_json_key_is_not_silently_normalized_as_policy(tmp_path):
    truth,pipeline,service,calls,source=_setup(tmp_path,raw_mutate=lambda data:data.replace('{','{"schema":"forged",',1))
    pipeline.complete(release_batch_id=original.BATCH)
    before=truth.store.path.read_bytes()
    with pytest.raises(Exception,match='DUPLICATE_JSON_KEY'):service.freeze(release_batch_id=original.BATCH)
    assert truth.store.path.read_bytes()==before


def test_real_release_controller_freezes_policy_before_n2_and_rejects_changed_policy_history(tmp_path):
    import test_rc72_release_driver as product
    truth,driver,upstream_calls=product._driver(tmp_path)
    batch=truth.query('rc72_release_batch')[0]
    policy=dict(schema='RC72_EXPECTED_RELEASE_SCOPE_V1',release_id=batch['release_id'],release_batch_id=product.BATCH,
        mission_id=product.MISSION,source_commit=product.COMMIT,application_ids=batch['application_ids'],version_ids=batch.get('version_ids',[]),
        requirement_ssts={r:['SST-'+r] for r in batch['requirement_ids']},
        required_levels_by_sst={'SST-'+r:['L1','L2','L3','L4','L5','L6','L7'] for r in batch['requirement_ids']},
        source_refs=['catalog://original-expected-release/v1'])
    source=tmp_path/'policy.json';source.write_text(json.dumps(policy),encoding='utf-8')
    candidate=product._good_candidate()
    candidate['facts'].update(release_id=product.RELEASE,release_batch_id=product.BATCH,source_commit=product.COMMIT)
    candidate['facts']['deployment_records'][0]['application_id']='BLOAN'
    binding=product._binding();binding.update(release_id=product.RELEASE,mission_id=product.MISSION,
                                            release_batch_id=product.BATCH,source_commit=product.COMMIT)
    candidate['facts']['executable_bindings']=[binding]
    fixture=tmp_path/'candidate.json';fixture.write_text(json.dumps(candidate),encoding='utf-8')
    script=tmp_path/'native-policy-worker.py'
    # Upstream semantic facts remain an explicit engineering fixture. The
    # policy is read through the real production MCP and live native parent.
    script.write_text(CHILD.replace('import json,os,subprocess,sys','import json,os,subprocess,sys\nfrom pathlib import Path')
        .replace("candidate=json.loads(values[1]['text'])","candidate=json.loads(Path(sys.argv[3]).read_text())"),encoding='utf-8')
    count=[]
    def runner(command,**kwargs):
        assert 'RC72_EXPECTED_RELEASE_SCOPE_V1' in command[-1]
        assert 'facts.expected_scope_input' in command[-1]
        count.append(1)
        return subprocess.run([sys.executable,str(script),str(Path(__file__).resolve().parents[1]),
            json.dumps(['release-batch://'+product.BATCH]),str(fixture)],**kwargs)
    driver.n1_launcher=NativeN1ReadDshLauncher(resources=[N1ReadResource('release-batch://'+product.BATCH,source)],
        dsh_bin=sys.executable,patch_path=str(tmp_path/'patch.json'),cwd=str(tmp_path),truth=truth,
        authority=RC72AuthorityRuntime(b'controller-expected-policy-key'),coordinator_instance_id='controller',
        release_id=product.RELEASE,state_root=str(tmp_path/'native-state'),command_runner=runner)
    driver.n1_tools=(TOOL,)
    driver.expected_scope=ExpectedScopeInputService(N1StrictPipelineService(truth,source_commit=product.COMMIT,
        launcher=driver.n1_launcher,allowed_tools=[TOOL]))
    original_n2_runner=driver.n2_launcher.command_runner
    def n2_runner(command,**kwargs):
        assert len(truth.query('rc72_release_scope_manifest'))==1
        assert len(truth.query('rc72_expected_scope_input'))==1
        return original_n2_runner(command,**kwargs)
    driver.n2_launcher.command_runner=n2_runner
    result=driver.run(release_batch_id=product.BATCH)
    assert next(n for n in result['nodes'] if n['node_type']=='N2_REQUIREMENT')['state']=='PASS'
    before=truth.store.path.read_bytes()
    assert driver.run(release_batch_id=product.BATCH)==result
    assert truth.store.path.read_bytes()==before and len(count)==1
    row=truth.query('rc72_release_scope_manifest')[0]
    row['required_levels_by_sst'][next(iter(row['required_levels_by_sst']))]=['L3']
    row['artifact_version']+=1;truth.append_atomic('RC72_RELEASE_SCOPE_MANIFEST_UPSERTED',row)
    before=truth.store.path.read_bytes()
    with pytest.raises(Exception,match='FROZEN_MANIFEST_CHANGED'):driver.run(release_batch_id=product.BATCH)
    assert truth.store.path.read_bytes()==before and len(count)==1
    driver.expected_scope=None
    with pytest.raises(Exception,match='EXPECTED_SCOPE_PROVIDER_REQUIRED'):
        driver.run(release_batch_id=product.BATCH)
    assert truth.store.path.read_bytes()==before and len(count)==1


def test_partial_manifest_write_resumes_same_signed_original_input(tmp_path,monkeypatch):
    truth,pipeline,service,calls,source=_setup(tmp_path)
    pipeline.complete(release_batch_id=original.BATCH)
    append=truth.append_atomic
    def stop(event,row,**kwargs):
        if event=='RC72_RELEASE_SCOPE_MANIFEST_UPSERTED':raise KeyboardInterrupt()
        return append(event,row,**kwargs)
    monkeypatch.setattr(truth,'append_atomic',stop)
    with pytest.raises(KeyboardInterrupt):service.freeze(release_batch_id=original.BATCH)
    assert len(truth.query('rc72_expected_scope_input'))==1
    assert not truth.query('rc72_release_scope_manifest')
    monkeypatch.setattr(truth,'append_atomic',append)
    service.freeze(release_batch_id=original.BATCH)
    assert len(truth.query('rc72_expected_scope_input'))==len(truth.query('rc72_release_scope_manifest'))==1
    assert len(calls)==1


def test_identical_repeated_original_reads_are_all_bound_without_duplicate_manifest(tmp_path):
    truth,pipeline,service,calls,source=_setup(tmp_path,repeat_policy=True)
    pipeline.complete(release_batch_id=original.BATCH)
    service.freeze(release_batch_id=original.BATCH)
    receipt=truth.query('rc72_expected_scope_input')[0]
    assert len(receipt['native_call_refs'])==2
    assert len(truth.query('rc72_release_scope_manifest'))==1 and len(calls)==1


def test_changed_catalog_between_actual_n1_reads_is_not_arbitrarily_selected(tmp_path,monkeypatch):
    from rc7_runtime.rc72_native_n1_read_gate import NativeN1ReadGate
    truth,pipeline,service,calls,source=_setup(tmp_path,repeat_policy=True)
    original_invoke=NativeN1ReadGate.invoke
    changed=[]
    def invoke(gate,request_id,tool,arguments):
        result=original_invoke(gate,request_id,tool,arguments)
        if arguments.get('source_ref')=='release-batch://'+original.BATCH and not changed:
            changed.append(1)
            payload=json.loads(source.read_text())
            payload['required_levels_by_sst']['EXPECTED-SST-A']=['L3']
            source.write_text(json.dumps(payload))
        return result
    monkeypatch.setattr(NativeN1ReadGate,'invoke',invoke)
    pipeline.complete(release_batch_id=original.BATCH)
    before=truth.store.path.read_bytes()
    with pytest.raises(Exception,match='ORIGINAL_INPUT_CHANGED_DURING_N1'):
        service.freeze(release_batch_id=original.BATCH)
    assert truth.store.path.read_bytes()==before
    assert not truth.query('rc72_expected_scope_input') and not truth.query('rc72_release_scope_manifest')


def test_cold_controller_replay_needs_neither_original_file_nor_worker_authority(tmp_path):
    truth,pipeline,service,calls,source=_setup(tmp_path)
    pipeline.complete(release_batch_id=original.BATCH)
    service.freeze(release_batch_id=original.BATCH);source.unlink()
    before=truth.store.path.read_bytes()
    script='''import sys
from pathlib import Path
from rc6_runtime.truth import TruthRuntime
from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc7_runtime.rc72_authority import RC72AuthorityRuntime
from rc7_runtime.rc72_n1_strict_pipeline import N1StrictPipelineService
from rc7_runtime.rc72_expected_scope_input import ExpectedScopeInputService
root=Path(sys.argv[1]);truth=TruthRuntime(root/'r1.jsonl')
authority=RC72AuthorityRuntime(b'expected-policy-test-key')
def never(*a,**k):raise AssertionError('scope replay launched worker')
launcher=DshHeadlessWorkerLauncher(dsh_bin=sys.executable,patch_path=str(root/'patch.json'),cwd=str(root),truth=truth,authority=authority,coordinator_instance_id='controller',release_id=sys.argv[2],state_root=str(root/'cold'),command_runner=never)
pipeline=N1StrictPipelineService(truth,source_commit=sys.argv[3],launcher=launcher,allowed_tools=['mcp__pfc_aitest_rc7__read_scoped_reality_source'])
ExpectedScopeInputService(pipeline).freeze(release_batch_id=sys.argv[4])
assert not authority._leases
'''
    result=subprocess.run([sys.executable,'-c',script,str(tmp_path),original.RELEASE,original.COMMIT,original.BATCH],
        cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
    assert truth.store.path.read_bytes()==before


def test_validly_signed_receipt_cannot_replace_the_actual_captured_scope(tmp_path):
    from rc7_runtime.rc72_n7_execution_admission import _hash
    truth,pipeline,service,calls,source=_setup(tmp_path)
    pipeline.complete(release_batch_id=original.BATCH);service.freeze(release_batch_id=original.BATCH)
    row=truth.query('rc72_expected_scope_input')[0]
    row['manifest']['required_levels_by_sst']['EXPECTED-SST-A']=['L3']
    row['manifest_sha256']=_hash(row['manifest'])
    raw={k:v for k,v in row.items() if k not in {'signature','artifact_type','artifact_version'}}
    row.update(signature=service.authority._sign(raw),artifact_version=row['artifact_version']+1)
    truth.append_atomic('RC72_EXPECTED_SCOPE_INPUT_UPSERTED',row)
    before=truth.store.path.read_bytes()
    with pytest.raises(Exception,match='INPUT_RECEIPT_CHANGED'):service.freeze(release_batch_id=original.BATCH)
    assert truth.store.path.read_bytes()==before and len(calls)==1


@pytest.mark.parametrize('field,value,error',[
    ('target_ratio',True,'TARGET_RATIO_INVALID'),
    ('target_ratio',0,'TARGET_RATIO_INVALID'),
    ('target_ratio',1.01,'TARGET_RATIO_INVALID'),
    ('report_url','https://user:password@example.invalid/report','FIXED_REPORT_URL_REQUIRED'),
    ('report_url','https://example.invalid/report#unbound','FIXED_REPORT_URL_REQUIRED'),
    ('target_revision','base-a','DISTINCT_REVISIONS_REQUIRED'),
    ('auth_mode','IMPLICIT','TARGET_MODE_INVALID'),
])
def test_v2_original_coverage_policy_rejects_ambiguous_targets(tmp_path,field,value,error):
    from rc7_runtime.rc72_expected_scope_input import parse_expected_scope
    truth=original._truth(tmp_path);original._seed(truth)
    batch=truth.query('rc72_release_batch')[0]
    target=dict(metric='LINE',base_revision='base-a',target_revision='target-b',target_ratio=.9,
        report_url='https://example.invalid/report',auth_mode='WORKER_HEADER',source_ref='catalog://coverage/v1')
    target[field]=value
    policy=dict(schema='RC72_EXPECTED_RELEASE_SCOPE_V2',release_id=batch['release_id'],release_batch_id=original.BATCH,
        mission_id=original.MISSION,source_commit=original.COMMIT,application_ids=batch['application_ids'],version_ids=batch.get('version_ids',[]),
        requirement_ssts={r:['SST-'+r] for r in batch['requirement_ids']},
        required_levels_by_sst={'SST-'+r:['L1','L2','L3','L4','L5','L6','L7'] for r in batch['requirement_ids']},
        source_refs=['catalog://original/v1'],coverage_targets={app:target for app in batch['application_ids']})
    with pytest.raises(Exception,match=error):parse_expected_scope(json.dumps(policy),batch,original.COMMIT)
