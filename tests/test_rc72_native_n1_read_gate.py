"""Actual child MCP process -> live parent scoped read, not bank qualification."""
import json
import subprocess
import sys
from pathlib import Path

import pytest
from test_rc72_mission_node_handoff import _truth, _seed, COMMIT, RELEASE, BATCH, MISSION, WORKITEM
from rc7_runtime.rc72_authority import RC72AuthorityRuntime
from rc7_runtime.rc72_mission_node_handoff import N1DshHandoffService
from rc7_runtime.rc72_native_n1_launcher import NativeN1ReadDshLauncher
from rc7_runtime.rc72_native_n1_read_gate import N1ReadResource, TOOL


CHILD = '''import json,os,subprocess,sys
mode=sys.argv[2]
context=json.loads(os.environ['PFC_RC72_TOOL_GATE_CONTEXT'])
args=dict(source_ref='release-batch://RB-PAY-942',mission_context=context)
if mode=='outside':args['source_ref']='file:///etc/passwd'
if mode=='spoof':context['worker_id']='other-worker'
if mode=='path':args['path']='/etc/passwd'
message=dict(jsonrpc='2.0',id=1,method='tools/call',params=dict(name='read_scoped_reality_source',arguments=args))
if mode!='fake':
    result=subprocess.run([sys.executable,'-m','rc7_release.mcp_server_authorized'],cwd=sys.argv[1],input=json.dumps(message)+'\\n',text=True,capture_output=True,env=os.environ)
    response=json.loads(result.stdout.strip())
    if 'error' in response:raise RuntimeError(response)
    if mode=='duplicate':
        again=subprocess.run([sys.executable,'-m','rc7_release.mcp_server_authorized'],cwd=sys.argv[1],input=json.dumps(message)+'\\n',text=True,capture_output=True,env=os.environ)
        assert json.loads(again.stdout)==response
    text=json.loads(response['result']['content'][0]['text'])['text']
else:text='invented'
print(json.dumps(dict(type='session',session_id='session-native-n1')))
print(json.dumps(dict(type='tool_call',tool_name='mcp__pfc_aitest_rc7__read_scoped_reality_source')))
print(json.dumps(dict(type='final',text=json.dumps(dict(status='CANDIDATE',facts=[dict(observed=text)],unknowns=[],gaps=[])))))
'''


def _service(tmp_path, mode='normal', before=None):
    truth=_truth(tmp_path);_seed(truth)
    source=tmp_path/'original.json';source.write_text('{"actual":"observed"}',encoding='utf-8')
    script=tmp_path/'child.py';script.write_text(CHILD,encoding='utf-8')
    patch=tmp_path/'patch.json';patch.write_text('{}')
    count=[]
    def runner(command,**kwargs):
        count.append(command)
        if before:before(launcher)
        return subprocess.run([sys.executable,str(script),str(Path(__file__).resolve().parents[1]),mode],**kwargs)
    launcher=NativeN1ReadDshLauncher(resources=[N1ReadResource('release-batch://'+BATCH,source)],
        dsh_bin=sys.executable,patch_path=str(patch),cwd=str(tmp_path),truth=truth,
        authority=RC72AuthorityRuntime(b'native-n1-test-signing-key'),coordinator_instance_id='coordinator',
        release_id=RELEASE,state_root=str(tmp_path/'state'),command_runner=runner)
    service=N1DshHandoffService(truth,source_commit=COMMIT,launcher=launcher,allowed_tools=[TOOL])
    return service,truth,count,source


def test_actual_mcp_read_and_no_repeat_or_source_re_read_on_resume(tmp_path):
    service,truth,count,source=_service(tmp_path)
    first=service.handoff(release_batch_id=BATCH)
    assert first['status']=='SESSION_OBSERVED'
    calls=truth.query('rc72_n1_native_read',kind='CALL')
    assert len(calls)==1 and calls[0]['state']=='RETURNED'
    assert json.loads(calls[0]['result']['text'])=={'actual':'observed'}
    source.write_text('changed after observation')
    assert service.handoff(release_batch_id=BATCH)['status']=='RESUMED'
    assert len(count)==1
    assert len(truth.query('rc7_task',task_id=WORKITEM))==1
    assert not truth.query('rc72_node_gate',mission_id=MISSION)
    capture=Path(calls[0]['result']['content_ref'][7:]);capture.write_text('tampered')
    with pytest.raises(Exception,match='CAPTURE_CHANGED'):
        service.handoff(release_batch_id=BATCH)
    assert len(count)==1


@pytest.mark.parametrize('mode',['outside','spoof','path','fake'])
def test_forged_or_outside_scope_calls_cannot_establish_attempt(tmp_path,mode):
    service,truth,count,source=_service(tmp_path,mode)
    with pytest.raises(Exception):service.handoff(release_batch_id=BATCH)
    assert not truth.query('rc72_mission_node_worker_attempt',mission_id=MISSION)
    assert not truth.query('rc72_n1_native_read',kind='CALL')
    assert not list((tmp_path/'state').rglob('*.source'))


def test_revoked_live_worker_prevents_actual_read(tmp_path):
    def revoke(launcher):
        gate=launcher._native_gate
        launcher.authority.revoke_worker_lease(gate.assignment.lease.lease_id)
    service,truth,count,source=_service(tmp_path,before=revoke)
    with pytest.raises(Exception):service.handoff(release_batch_id=BATCH)
    assert not truth.query('rc72_n1_native_read',kind='CALL')
    assert not truth.query('rc72_mission_node_worker_attempt',mission_id=MISSION)


def test_lost_authority_after_read_retains_unknown_capture_without_attempt(tmp_path,monkeypatch):
    from rc7_runtime.rc72_native_n1_read_gate import NativeN1ReadGate
    original=NativeN1ReadGate._actor
    seen=[]
    def actor(gate):
        seen.append(1)
        # open, call before reading, call after physical read/capture.
        if len(seen)==3:gate.authority.revoke_worker_lease(gate.assignment.lease.lease_id)
        return original(gate)
    monkeypatch.setattr(NativeN1ReadGate,'_actor',actor)
    service,truth,count,source=_service(tmp_path)
    with pytest.raises(Exception):service.handoff(release_batch_id=BATCH)
    records=truth.query('rc72_n1_native_read',kind='CALL')
    assert len(records)==1 and records[0]['state']=='UNKNOWN'
    assert json.loads(records[0]['result']['text'])=={'actual':'observed'}
    assert Path(records[0]['result']['content_ref'][7:]).is_file()
    assert not truth.query('rc72_mission_node_worker_attempt',mission_id=MISSION)
    with pytest.raises(Exception,match='EXISTING_INVOCATION_NO_REPLAY'):
        service.handoff(release_batch_id=BATCH)
    assert len(count)==1


def test_cold_replay_audits_historical_capture_without_restoring_authority(tmp_path):
    from rc6_runtime.truth import TruthRuntime
    service,truth,count,source=_service(tmp_path)
    service.handoff(release_batch_id=BATCH)
    source.unlink()
    cold=TruthRuntime(tmp_path/'r1.jsonl')
    # Base launcher can audit marked history without any native resource registration.
    from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
    launcher=DshHeadlessWorkerLauncher(dsh_bin=sys.executable,patch_path=str(tmp_path/'patch.json'),cwd=str(tmp_path),
        truth=cold,authority=RC72AuthorityRuntime(b'native-n1-test-signing-key'),coordinator_instance_id='coordinator',
        release_id=RELEASE,state_root=str(tmp_path/'cold-state'),command_runner=lambda *a,**k:pytest.fail('must not launch'))
    recovered=N1DshHandoffService(cold,source_commit=COMMIT,launcher=launcher,allowed_tools=[TOOL])
    assert recovered.handoff(release_batch_id=BATCH)['status']=='RESUMED'
    assert not launcher.authority._leases


def test_same_live_mcp_request_id_returns_original_single_observation(tmp_path):
    service,truth,count,source=_service(tmp_path,'duplicate')
    service.handoff(release_batch_id=BATCH)
    assert len(truth.query('rc72_n1_native_read',kind='CALL'))==1
    assert len(count)==1


def test_historic_original_input_refs_cannot_be_changed_even_with_valid_gate_signature(tmp_path):
    service,truth,count,source=_service(tmp_path)
    service.handoff(release_batch_id=BATCH)
    gate=truth.query('rc72_n1_native_read',kind='GATE')[0]
    gate['scope_payload']['canonical_assignment']['input_refs'].append('file:///outside')
    from rc7_runtime.rc72_n7_execution_admission import _hash
    gate['scope_sha256']=_hash(gate['scope_payload'])
    raw={k:v for k,v in gate.items() if k not in {'signature','artifact_type','artifact_version'}}
    gate['signature']=service.launcher.authority._sign(raw)
    gate['artifact_version']+=1
    truth.append_atomic('RC72_N1_NATIVE_READ_UPSERTED',gate)
    with pytest.raises(Exception,match='HANDOFF_SCOPE_CHANGED'):
        service.handoff(release_batch_id=BATCH)
    assert len(count)==1


def test_native_read_composes_with_strict_n1_gate_and_completed_replay_audit(tmp_path):
    import test_rc72_n1_completion as original
    from test_rc72_n1_strict_pipeline import _candidate_with_binding
    from rc7_runtime.rc72_n1_strict_pipeline import N1StrictPipelineService
    truth=original._truth(tmp_path);original._seed(truth)
    source=tmp_path/'reality.json';source.write_text(json.dumps(_candidate_with_binding()),encoding='utf-8')
    script=tmp_path/'strict-child.py'
    child=CHILD.replace('release-batch://RB-PAY-942','release-batch://'+original.BATCH)
    child=child.replace("dict(status='CANDIDATE',facts=[dict(observed=text)],unknowns=[],gaps=[])", 'json.loads(text)')
    script.write_text(child,encoding='utf-8')
    patch=tmp_path/'patch.json';patch.write_text('{}')
    count=[]
    def runner(command,**kwargs):
        count.append(1)
        return subprocess.run([sys.executable,str(script),str(Path(__file__).resolve().parents[1]),'normal'],**kwargs)
    launcher=NativeN1ReadDshLauncher(resources=[N1ReadResource('release-batch://'+original.BATCH,source)],
        dsh_bin=sys.executable,patch_path=str(patch),cwd=str(tmp_path),truth=truth,
        authority=RC72AuthorityRuntime(b'native-n1-strict-key'),coordinator_instance_id='coordinator',
        release_id=original.RELEASE,state_root=str(tmp_path/'state'),command_runner=runner)
    pipeline=N1StrictPipelineService(truth,source_commit=original.COMMIT,launcher=launcher,allowed_tools=[TOOL])
    result=pipeline.complete(release_batch_id=original.BATCH)
    assert result['completion']['gate']['decision']=='PASS'
    assert result['field_verified'] is False and result['bank_final'] is False
    assert pipeline.complete(release_batch_id=original.BATCH)['handoff']['status']=='RESUMED_FROM_CANONICAL_N1'
    assert len(count)==1
    call=truth.query('rc72_n1_native_read',kind='CALL')[0]
    Path(call['result']['content_ref'][7:]).write_text('changed')
    with pytest.raises(Exception,match='CAPTURE_CHANGED'):
        pipeline.complete(release_batch_id=original.BATCH)
    assert len(count)==1


@pytest.mark.parametrize('kind',['CALL','GATE'])
def test_signed_receipt_with_foreign_workitem_is_rejected(tmp_path,kind):
    service,truth,count,source=_service(tmp_path)
    service.handoff(release_batch_id=BATCH)
    row=truth.query('rc72_n1_native_read',kind=kind)[0]
    row['workitem_id']='foreign-workitem'
    raw={k:v for k,v in row.items() if k not in {'signature','artifact_type','artifact_version'}}
    row['signature']=service.launcher.authority._sign(raw)
    row['artifact_version']+=1
    truth.append_atomic('RC72_N1_NATIVE_READ_UPSERTED',row)
    with pytest.raises(Exception,match='SCOPE_'):
        service.handoff(release_batch_id=BATCH)
    assert len(count)==1


def test_fresh_interpreter_reopens_native_history_without_warm_registration(tmp_path):
    service,truth,count,source=_service(tmp_path)
    service.handoff(release_batch_id=BATCH)
    source.unlink()
    script='''import sys
from pathlib import Path
from rc6_runtime.truth import TruthRuntime
from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc7_runtime.rc72_authority import RC72AuthorityRuntime
from rc7_runtime.rc72_mission_node_handoff import N1DshHandoffService
root=Path(sys.argv[1])
truth=TruthRuntime(root/'r1.jsonl')
authority=RC72AuthorityRuntime(b'native-n1-test-signing-key')
def never(*args,**kwargs):raise AssertionError('historical replay launched a process')
launcher=DshHeadlessWorkerLauncher(dsh_bin=sys.executable,patch_path=str(root/'patch.json'),cwd=str(root),truth=truth,authority=authority,coordinator_instance_id='coordinator',release_id='PAYMENT-R9.4.2',state_root=str(root/'cold-state'),command_runner=never)
service=N1DshHandoffService(truth,source_commit='3'*40,launcher=launcher,allowed_tools=['mcp__pfc_aitest_rc7__read_scoped_reality_source'])
assert service.handoff(release_batch_id='RB-PAY-942')['status']=='RESUMED'
assert not authority._leases
'''
    before=truth.store.path.read_bytes()
    result=subprocess.run([sys.executable,'-c',script,str(tmp_path)],cwd=Path(__file__).resolve().parents[1],text=True,capture_output=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
    assert truth.store.path.read_bytes()==before


def test_removed_native_event_marker_cannot_downgrade_cold_history_to_legacy(tmp_path):
    from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
    service,truth,count,source=_service(tmp_path)
    service.handoff(release_batch_id=BATCH)
    assignment=truth.query('rc72_mission_node_worker_assignment')[0]
    event=dict(service._handoff_events(MISSION,service._runtime_assignment_id(assignment['assignment_id']))[0])
    event.pop('native_n1_read_gate_id')
    base=DshHeadlessWorkerLauncher(dsh_bin=sys.executable,patch_path=str(tmp_path/'patch.json'),cwd=str(tmp_path),truth=truth,
        authority=RC72AuthorityRuntime(b'native-n1-test-signing-key'),coordinator_instance_id='coordinator',release_id=RELEASE,state_root=str(tmp_path/'cold-state'))
    cold=N1DshHandoffService(truth,source_commit=COMMIT,launcher=base,allowed_tools=[TOOL])
    with pytest.raises(Exception,match='GATE_REQUIRED'):
        cold._audit_native_read(assignment,event)


def test_release_driver_reaudits_actual_native_n1_capture_before_continuation(tmp_path):
    import test_rc72_release_driver as product
    truth,driver,calls=product._driver(tmp_path)
    candidate=product._good_candidate()
    candidate['facts'].update(release_id=product.RELEASE,release_batch_id=product.BATCH,source_commit=product.COMMIT)
    candidate['facts']['deployment_records'][0]['application_id']='BLOAN'
    binding=product._binding()
    binding.update(release_id=product.RELEASE,mission_id=product.MISSION,release_batch_id=product.BATCH,source_commit=product.COMMIT)
    candidate['facts']['executable_bindings']=[binding]
    source=tmp_path/'registered-input.json';source.write_text(json.dumps(candidate),encoding='utf-8')
    script=tmp_path/'native-child.py'
    child=CHILD.replace('release-batch://RB-PAY-942','release-batch://'+product.BATCH)
    child=child.replace("dict(status='CANDIDATE',facts=[dict(observed=text)],unknowns=[],gaps=[])", 'json.loads(text)')
    script.write_text(child,encoding='utf-8')
    count=[]
    def runner(command,**kwargs):
        count.append(1)
        return subprocess.run([sys.executable,str(script),str(Path(__file__).resolve().parents[1]),'normal'],**kwargs)
    driver.n1_launcher=NativeN1ReadDshLauncher(resources=[N1ReadResource('release-batch://'+product.BATCH,source)],
        dsh_bin=sys.executable,patch_path=str(tmp_path/'patch.json'),cwd=str(tmp_path),truth=truth,
        authority=RC72AuthorityRuntime(b'native-n1-product-key'),coordinator_instance_id='coordinator',release_id=product.RELEASE,
        state_root=str(tmp_path/'native-state'),command_runner=runner)
    driver.n1_tools=[TOOL]
    result=driver.run(release_batch_id=product.BATCH)
    assert next(n for n in result['nodes'] if n['node_type']=='N1_REALITY')['state']=='PASS'
    before=truth.store.path.read_bytes()
    assert driver.run(release_batch_id=product.BATCH)==result
    assert len(count)==1 and truth.store.path.read_bytes()==before
    record=truth.query('rc72_n1_native_read',kind='CALL')[0]
    Path(record['result']['content_ref'][7:]).write_text('tampered native history')
    with pytest.raises(Exception,match='CAPTURE_CHANGED'):
        driver.run(release_batch_id=product.BATCH)
    assert len(count)==1
