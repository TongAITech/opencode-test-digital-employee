"""Actual parent HTTP receipts, call-time fencing and untrusted child reports."""
from pathlib import Path
import json
from urllib.request import Request,urlopen
from urllib.error import HTTPError

import pytest
from rc7_runtime.models import ContractError
from rc7_runtime.rc72_formal_runner import FormalN7RunnerAdapter
from rc7_runtime.rc72_n7_pipeline import N7PipelineService
from rc7_runtime.rc72_native_http_gate import NativeHTTPGate,URL_ENV,TOKEN_ENV
from rc72_formal_runner_support import formal_setup,LocalHTTPEnvironment
from rc72_n2_test_support import BATCH


def _setup(tmp_path,monkeypatch,**mode):
    import rc72_formal_runner_support as support
    qualify=support._qualify
    if mode:
        monkeypatch.setattr(support,'_qualify',lambda *a,**kw:qualify(*a,**dict(kw,**mode)))
    truth,plan,prep,server,url=formal_setup(tmp_path,monkeypatch)
    output=tmp_path/'actual'
    runner=FormalN7RunnerAdapter(prep,evidence_root=output,environment_adapter=LocalHTTPEnvironment(url,output),
        execution_env={'RC72_OUTPUT_ROOT':str(output)},timeout_seconds=30)
    return truth,plan,prep,server,N7PipelineService(prep,runner=runner,capture_root=tmp_path/'capture')


@pytest.mark.parametrize('mode',['fake_native','tamper_native'])
def test_script_claim_cannot_replace_actual_parent_io_or_change_its_result(tmp_path,monkeypatch,mode):
    truth,plan,prep,server,pipeline=_setup(tmp_path,monkeypatch,**{mode:True})
    try:
        result=pipeline.complete(release_batch_id=BATCH)
        assert result['reason']=='N7_EXECUTION_DIAGNOSIS_REQUIRED'
        assert len(server.calls)==(0 if mode=='fake_native' else 1)
        assert not truth.query('rc72_node_gate',node_type='N7_EXECUTION')
        assert not truth.query('rc72_n7_cleanup_call')
        assert all(r['state']=='ACTIVE' for r in truth.query('rc72_data_lease'))
    finally:
        server.shutdown();server.server_close()


@pytest.mark.parametrize('when',['before','after'])
def test_revocation_is_checked_at_actual_call_and_after_effect_without_replay(tmp_path,monkeypatch,when):
    truth,plan,prep,server,pipeline=_setup(tmp_path,monkeypatch)
    original=NativeHTTPGate._actor
    counts={}
    def actor(gate):
        counts[gate.call_id]=counts.get(gate.call_id,0)+1
        # First=open, second=actual pre-I/O, third=actual post-I/O.
        if counts[gate.call_id]==(2 if when=='before' else 3):
            prep.authority.revoke_worker_lease(gate.p['task_lease']['lease_id'])
        return original(gate)
    monkeypatch.setattr(NativeHTTPGate,'_actor',actor)
    try:
        result=pipeline.complete(release_batch_id=BATCH)
        assert result['reason']=='N7_EXECUTION_DIAGNOSIS_REQUIRED'
        assert len(server.calls)==(0 if when=='before' else 1)
        calls=truth.query('rc72_n7_http_call')
        if when=='after':
            assert len(calls)==1 and calls[0]['state']=='UNKNOWN'
            assert Path(calls[0]['response_ref'][len('file://'):]).is_file()
            p=prep._one('rc72_n7_execution_preparation',preparation_id=calls[0]['preparation_id'])
            c=prep._one('rc72_n6_executable_contract',contract_id=p['contract_id'])

            # A new controller/gate cannot re-open the durable unknown operation.
            transport=dict(protocol='RC72_NATIVE_API_HTTP_V1',source_ref='approved-runner://'+p['case_id'],
                auth_mode='ANONYMOUS',result_mapping={'http':'$http','business':'$json.business'})
            with pytest.raises(ContractError,match='EXISTING_EFFECT_RECOVERY_REQUIRED'):
                NativeHTTPGate(prep,p,c,transport,pipeline.dispatch,evidence_root=pipeline.runner.root/'native-http').open()
        else:
            assert calls==[]
        before=truth.store.path.read_bytes()
        assert pipeline.complete(release_batch_id=BATCH)==result
        assert truth.store.path.read_bytes()==before
        assert not truth.query('rc72_n7_cleanup_call')
        assert all(r['state']=='ACTIVE' for r in truth.query('rc72_data_lease'))
    finally:
        server.shutdown();server.server_close()


def test_capability_and_exact_request_reject_alternate_arguments_before_backend_io(tmp_path,monkeypatch):
    truth,plan,prep,server,pipeline=_setup(tmp_path,monkeypatch)
    original=NativeHTTPGate.open
    rejected=[]
    capabilities=[]
    def opened(gate):
        value=original(gate)
        env=gate.environment()
        capabilities.append(env[TOKEN_ENV])
        for token,body in [('wrong',{'request_id':'business'}),(env[TOKEN_ENV],{'request_id':'business','url':'http://other-target/'})]:
            req=Request(env[URL_ENV],data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+token},method='POST')
            with pytest.raises(HTTPError) as error:
                urlopen(req,timeout=5)
            rejected.append(error.value.code)
        assert len(server.calls)==len(truth.query('rc72_n7_http_call'))
        return value
    monkeypatch.setattr(NativeHTTPGate,'open',opened)
    try:
        assert pipeline.complete(release_batch_id=BATCH)['state']=='N7_PASS'
        assert rejected==[409,409]*len(plan['items'])
        assert all(token not in truth.store.path.read_text() for token in capabilities)
        assert len(server.calls)==len(plan['items'])
    finally:
        server.shutdown();server.server_close()


def test_duplicate_rpc_returns_same_observation_without_another_business_request(tmp_path,monkeypatch):
    truth,plan,prep,server,pipeline=_setup(tmp_path,monkeypatch,repeat_native=True)
    try:
        assert pipeline.complete(release_batch_id=BATCH)['state']=='N7_PASS'
        assert len(server.calls)==len(plan['items'])
        calls=truth.query('rc72_n7_http_call')
        assert len(calls)==len(plan['items']) and all(r['artifact_version']==2 for r in calls)
        assert all(r['authorization'] and r['completed_authorization'] for r in calls)
        before=truth.store.path.read_bytes()
        assert pipeline.complete(release_batch_id=BATCH)['state']=='N7_PASS'
        assert truth.store.path.read_bytes()==before
    finally:
        server.shutdown();server.server_close()


def test_changed_actual_native_response_cannot_hide_behind_script_evidence(tmp_path,monkeypatch):
    truth,plan,prep,server,pipeline=_setup(tmp_path,monkeypatch)
    try:
        result=pipeline.complete(release_batch_id=BATCH)
        row=truth.query('rc72_n7_http_call')[0]
        Path(row['response_ref'][len('file://'):]).write_bytes(b'changed actual backend response')
        before=truth.store.path.read_bytes()
        with pytest.raises(ContractError,match='RESPONSE_BYTES_CHANGED'):
            pipeline.finalization.audit(truth.query('rc72_n7_execution_review',review_result_id=result['review_result_id'])[0]['bundle_id'])
        assert truth.store.path.read_bytes()==before and len(server.calls)==len(plan['items'])
    finally:
        server.shutdown();server.server_close()


def test_expired_data_custody_is_checked_before_actual_backend_io(tmp_path,monkeypatch):
    import rc7_runtime.rc72_data_resources as resources
    truth,plan,prep,server,pipeline=_setup(tmp_path,monkeypatch)
    original=NativeHTTPGate._actor
    counts={}
    def actor(gate):
        counts[gate.call_id]=counts.get(gate.call_id,0)+1
        if counts[gate.call_id]==2:
            lease=truth.query('rc72_data_lease',data_lease_id=gate.p['data_lease_ids'][0])[0]
            monkeypatch.setattr(resources,'_now',lambda:lease['expires_at']+1)
        return original(gate)
    monkeypatch.setattr(NativeHTTPGate,'_actor',actor)
    try:
        result=pipeline.complete(release_batch_id=BATCH)
        assert result['reason']=='N7_EXECUTION_DIAGNOSIS_REQUIRED'
        assert server.calls==[] and not truth.query('rc72_n7_http_call')
        assert any(r['state'] in {'ACTIVE','EXPIRED'} and r['expires_at']<resources._now()
            for r in truth.query('rc72_data_lease'))
        assert not truth.query('rc72_n7_cleanup_call')
    finally:
        server.shutdown();server.server_close()


def test_authentication_without_parent_provider_is_not_silently_sent_anonymously(tmp_path,monkeypatch):
    def needs_credentials(profile):
        for fact in profile['facts']:
            if fact['kind']=='auth':
                fact['attributes']['authentication_mode']='HEADER'
    truth,plan,prep,server,url=formal_setup(tmp_path,monkeypatch,profile_mutator=needs_credentials)
    output=tmp_path/'actual'
    runner=FormalN7RunnerAdapter(prep,evidence_root=output,environment_adapter=LocalHTTPEnvironment(url,output),
        execution_env={'RC72_OUTPUT_ROOT':str(output)},timeout_seconds=30)
    pipeline=N7PipelineService(prep,runner=runner,capture_root=tmp_path/'captured')
    try:
        with pytest.raises(ContractError,match='AUTH_PROVIDER_REQUIRED:N1'):
            pipeline.complete(release_batch_id=BATCH)
        assert not server.calls and not truth.query('rc72_n7_http_call')
        assert not truth.query('rc72_n7_tool_dispatch')
    finally:
        server.shutdown();server.server_close()


def test_api_response_cannot_substitute_for_independent_database_oracle_evidence(tmp_path,monkeypatch):
    from copy import deepcopy
    def database_oracle(candidate):
        candidate['obligations'][0]['oracle_types'].append('DB_STATE')
        for case in candidate['cases']:
            check=deepcopy(case['oracle']['checks'][-1])
            check['type']='DB_STATE'
            check['id']='requires-independent-database-provenance'
            case['oracle']['checks'].append(check)
    truth,plan,prep,server,url=formal_setup(tmp_path,monkeypatch,design_mutator=database_oracle)
    output=tmp_path/'actual'
    runner=FormalN7RunnerAdapter(prep,evidence_root=output,environment_adapter=LocalHTTPEnvironment(url,output),
        execution_env={'RC72_OUTPUT_ROOT':str(output)},timeout_seconds=30)
    pipeline=N7PipelineService(prep,runner=runner,capture_root=tmp_path/'capture')
    try:
        result=pipeline.complete(release_batch_id=BATCH)
        assert result['reason']=='N7_EVIDENCE_REVIEW_NOT_ACCEPTED'
        bundle=truth.query('rc72_n7_evidence_bundle',bundle_id=result['bundle_id'])[0]
        assert 'NATIVE_ORACLE_TOOL_PROVENANCE_REQUIRED' in bundle['known_gaps']
        assert len(server.calls)==len(plan['items'])
        assert not truth.query('rc72_node_gate',node_type='N7_EXECUTION')
    finally:
        server.shutdown();server.server_close()


def test_redirect_response_cannot_move_execution_outside_frozen_endpoint(tmp_path,monkeypatch):
    import rc72_formal_runner_support as support
    truth,plan,prep,server,pipeline=_setup(tmp_path,monkeypatch)
    original_post,original_get=support._Handler.do_POST,support._Handler.do_GET
    redirected=[]
    def post(handler):
        if handler.path!='/config/query':
            return original_post(handler)
        server.calls.append(json.loads(handler.rfile.read(int(handler.headers['Content-Length']))))
        raw=json.dumps({'business':{'outcome':'APPROVED_FIXTURE_RESULT'}}).encode()
        handler.send_response(302)
        handler.send_header('Location','/outside-frozen-endpoint')
        handler.send_header('Content-Length',str(len(raw)))
        handler.end_headers()
        handler.wfile.write(raw)
    def get(handler):
        if handler.path=='/outside-frozen-endpoint':
            redirected.append(handler.path)
        return original_get(handler)
    monkeypatch.setattr(support._Handler,'do_POST',post)
    monkeypatch.setattr(support._Handler,'do_GET',get)
    try:
        result=pipeline.complete(release_batch_id=BATCH)
        assert result['status']=='HOLD'
        assert not redirected
        assert len(server.calls)==1
        calls=truth.query('rc72_n7_http_call')
        assert len(calls)==1 and calls[0]['state']=='RETURNED'
        assert calls[0]['status_code']==302 and calls[0]['result']['http']['status']==302
        assert not truth.query('rc72_node_gate',node_type='N7_EXECUTION')
    finally:
        server.shutdown();server.server_close()
