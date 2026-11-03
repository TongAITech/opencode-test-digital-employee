"""Real identity + business HTTP; no auth success booleans or child credentials."""
from pathlib import Path
import json
import secrets
import time

import pytest
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import ContractError
from rc7_runtime.rc72_formal_runner import FormalN7RunnerAdapter,verified_formal_receipt
from rc7_runtime.rc72_n7_pipeline import N7PipelineService
from rc7_runtime.rc72_worker_http_auth import WorkerHTTPAuthAssetProvider,PROTOCOL,verify_auth_receipt
from rc72_formal_runner_support import formal_setup,LocalHTTPEnvironment
from rc72_n2_test_support import BATCH
from test_rc72_n7_execution_preparation import _service


def _setup(tmp_path,monkeypatch,*,mutation=None,actual_principal='bank-checker',actual_roles=None,provider=True,fail=False,spec_mutator=None,design_mutator=None,factory=False):
    import rc72_formal_runner_support as support
    def profile(value):
        auth=next(x for x in value['facts'] if x['kind']=='auth')
        url=next(x['attributes']['url'] for x in value['facts'] if x['kind']=='route' and x['id']=='gateway')
        # The profile deployment URI and API endpoint use this same live origin.
        from urllib.parse import urlsplit
        parts=urlsplit(url);origin=parts.scheme+'://'+parts.netloc
        auth['attributes'].update(authentication_mode='WORKER_HEADER',worker_http_auth=dict(
            asset_ref='bank-auth://worker-checker',principal='bank-checker',roles=['CHECKER'],device_bound=False,
            identity_probe=dict(url=origin+'/identity',principal_path='$json.principal',roles_path='$json.roles')))
        if spec_mutator:spec_mutator(auth['attributes']['worker_http_auth'])
    truth,plan,prep,server,url=formal_setup(tmp_path,monkeypatch,profile_mutator=profile,
        auth_mode='WORKER_HEADER',auth_role='CHECKER',fail=fail,design_mutator=design_mutator)
    root=tmp_path/'worker-assets'
    composed_pipeline = None
    if factory:
        from test_rc72_mission_factory import _setup as factory_setup
        from rc7_runtime.rc72_mission_factory import create_mission_driver
        _, options = factory_setup(tmp_path, truth=truth)
        root.mkdir()
        options.update(execution_authority=prep.authority, http_auth_asset_root=root,
            execution_environment=LocalHTTPEnvironment(url,tmp_path/'actual'/'runner'),
            execution_env={'RC72_OUTPUT_ROOT':str(tmp_path/'actual'/'runner')},
            evidence_root=tmp_path/'actual')
        composed_pipeline = create_mission_driver(truth, **options).n7_pipeline
        prep = composed_pipeline.preparation
    secret_values=[]
    original_prepare=prep.prepare
    server.identity_calls=[];server.business_headers=[];server.auth_tokens=set()
    server.actual_principal=actual_principal;server.actual_roles=['CHECKER'] if actual_roles is None else actual_roles
    def prepare(**kwargs):
        p=original_prepare(**kwargs)
        token='Bearer '+secrets.token_urlsafe(32)
        asset=dict(schema=PROTOCOL,auth_asset_ref='bank-auth://worker-checker',principal='bank-checker',role='CHECKER',
            issued_at=int(time.time())-5,expires_at=int(time.time())+600,headers={'Authorization':token},
            **{k:p[k] for k in ('preparation_id','release_id','source_commit','mission_id','workitem_id','attempt_id','worker_id','contract_id')})
        if mutation:mutation(asset)
        path=root/p['worker_id']/(p['attempt_id']+'.json')
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(asset))
        secret_values.append(token);server.auth_tokens.add(token)
        return p
    monkeypatch.setattr(prep,'prepare',prepare)
    original_get,original_post=support._Handler.do_GET,support._Handler.do_POST
    def get(handler):
        if handler.path!='/identity':return original_get(handler)
        header=handler.headers.get('Authorization')
        server.identity_calls.append(header)
        assert header in server.auth_tokens
        handler._send(dict(principal=server.actual_principal,roles=server.actual_roles))
    def post(handler):
        if handler.path=='/config/query':
            header=handler.headers.get('Authorization')
            server.business_headers.append(header)
            assert header in server.auth_tokens
        return original_post(handler)
    monkeypatch.setattr(support._Handler,'do_GET',get);monkeypatch.setattr(support._Handler,'do_POST',post)
    output=tmp_path/'actual'
    auth=WorkerHTTPAuthAssetProvider(prep,asset_root=root)
    runner=FormalN7RunnerAdapter(prep,evidence_root=output,environment_adapter=LocalHTTPEnvironment(url,output),
        execution_env={'RC72_OUTPUT_ROOT':str(output)},timeout_seconds=30,http_auth_provider=auth if provider else None)
    pipeline=composed_pipeline or N7PipelineService(prep,runner=runner,capture_root=tmp_path/'captured')
    return truth,plan,prep,server,pipeline,root,secret_values


def _close(server):
    server.shutdown();server.server_close()


@pytest.mark.parametrize('factory',[False,True],ids=['direct-runner','owned-mission-factory'])
def test_exact_worker_asset_is_verified_by_real_identity_then_real_business_and_cold_audit_needs_no_secret(tmp_path,monkeypatch,factory):
    truth,plan,prep,server,pipeline,root,secrets_used=_setup(tmp_path,monkeypatch,factory=factory)
    try:
        result=pipeline.complete(release_batch_id=BATCH)
        assert result['state']=='N7_PASS'
        count=len(plan['items'])
        assert count==len(server.calls)==len(server.identity_calls)==len(server.business_headers)
        assert server.identity_calls==server.business_headers==secrets_used
        calls=truth.query('rc72_n7_http_call')
        assert len(calls)==count and all(r['state']=='RETURNED' and r['business_auth_role']=='CHECKER' for r in calls)
        for token in secrets_used:
            assert token not in truth.store.path.read_text()
            assert token not in json.dumps(pipeline.runner.execution_env)
            for folder in (tmp_path/'actual',tmp_path/'captured'):
                for file in folder.rglob('*'):
                    if file.is_file():assert token.encode() not in file.read_bytes()
        for file in root.rglob('*.json'):file.unlink()
        cold=_service(TruthRuntime(truth.store.path))
        for call in calls:
            p=cold._one('rc72_n7_execution_preparation',preparation_id=call['preparation_id'])
            c=cold._one('rc72_n6_executable_contract',contract_id=p['contract_id'])
            dispatch=cold._one('rc72_n7_tool_dispatch',preparation_id=p['preparation_id'])
            assert verified_formal_receipt(cold,p,c,dispatch['raw_result'])['native_http_protocol']=='RC72_NATIVE_API_HTTP_V1'
            assert verify_auth_receipt(cold,p,c,call['worker_auth_receipt'])['role']=='CHECKER'
            forged=dict(call['worker_auth_receipt'],role='CAPTAIN')
            forged['signature']=cold.authority._sign({k:v for k,v in forged.items() if k!='signature'})
            with pytest.raises(ContractError,match='SCOPE_INVALID'):
                verify_auth_receipt(cold,p,c,forged)
    finally:_close(server)


@pytest.mark.parametrize('principal,roles',[('captain-session',['CHECKER']),('bank-checker',['CAPTAIN']),('bank-checker',['CHECKER','CAPTAIN'])])
def test_actual_wrong_account_or_privileged_role_is_not_accepted_from_export_metadata(tmp_path,monkeypatch,principal,roles):
    truth,plan,prep,server,pipeline,root,_=_setup(tmp_path,monkeypatch,actual_principal=principal,actual_roles=roles)
    try:
        result=pipeline.complete(release_batch_id=BATCH)
        assert result['status']=='HOLD' and not server.calls and len(server.identity_calls)==1
        assert not truth.query('rc72_node_gate',node_type='N7_EXECUTION')
        assert not truth.query('rc72_n7_cleanup_call')
        assert all(r['state']=='ACTIVE' for r in truth.query('rc72_data_lease'))
        assert truth.query('rc72_n7_http_call')[0]['state']=='UNKNOWN'
    finally:_close(server)


@pytest.mark.parametrize('change',['worker','attempt','asset','role','expiry','header'])
def test_wrong_scope_expired_or_injected_asset_never_reaches_identity_or_business(tmp_path,monkeypatch,change):
    def mutate(asset):
        if change=='worker':asset['worker_id']='other-worker'
        elif change=='attempt':asset['attempt_id']='other-attempt'
        elif change=='asset':asset['auth_asset_ref']='bank-auth://captain'
        elif change=='role':asset['role']='CAPTAIN'
        elif change=='expiry':asset['expires_at']=int(time.time())-1
        else:asset['headers']['Authorization']='Bearer token\r\nX-Privilege: Captain'
    truth,plan,prep,server,pipeline,root,_=_setup(tmp_path,monkeypatch,mutation=mutate)
    try:
        assert pipeline.complete(release_batch_id=BATCH)['status']=='HOLD'
        assert not server.identity_calls and not server.calls
        assert not truth.query('rc72_n7_cleanup_call')
        assert all(r['state']=='ACTIVE' for r in truth.query('rc72_data_lease'))
    finally:_close(server)


def test_missing_auth_provider_never_falls_back_to_anonymous(tmp_path,monkeypatch):
    truth,plan,prep,server,pipeline,root,_=_setup(tmp_path,monkeypatch,provider=False)
    try:
        with pytest.raises(ContractError,match='FORMAL_SCOPED_HTTP_AUTH_PROVIDER_REQUIRED'):
            pipeline.complete(release_batch_id=BATCH)
        assert not server.identity_calls and not server.calls
        assert not truth.query('rc72_n7_http_call')
    finally:_close(server)


def test_asset_rotation_during_actual_business_keeps_unknown_custody_without_replay(tmp_path,monkeypatch):
    import rc72_formal_runner_support as support
    truth,plan,prep,server,pipeline,root,_=_setup(tmp_path,monkeypatch)
    original=support._Handler.do_POST
    def post(handler):
        if handler.path=='/config/query':
            files=list(root.rglob('*.json'))
            assert len(files)==1
            asset=json.loads(files[0].read_text())
            asset['headers']['Authorization']='Bearer '+secrets.token_urlsafe(32)
            files[0].write_text(json.dumps(asset))
        return original(handler)
    monkeypatch.setattr(support._Handler,'do_POST',post)
    try:
        result=pipeline.complete(release_batch_id=BATCH)
        assert result['status']=='HOLD' and len(server.calls)==1
        call=truth.query('rc72_n7_http_call')[0]
        assert call['state']=='UNKNOWN' and call['status_code']==200 and call['worker_auth_receipt']
        assert call['error_code']=='WORKER_HTTP_AUTH_ASSET_CHANGED_DURING_EFFECT'
        assert Path(call['response_ref'][len('file://'):]).is_file()
        assert all(r['state']=='ACTIVE' for r in truth.query('rc72_data_lease'))
        assert not truth.query('rc72_n7_cleanup_call')
        before=truth.store.path.read_bytes()
        assert pipeline.complete(release_batch_id=BATCH)==result and len(server.calls)==1
        assert truth.store.path.read_bytes()==before
    finally:_close(server)


def test_revoked_permission_after_identity_proof_fsync_prevents_business_request(tmp_path,monkeypatch):
    truth,plan,prep,server,pipeline,root,_=_setup(tmp_path,monkeypatch)
    append=truth.append_atomic
    revoked=[]
    def persist(event,payload):
        result=append(event,payload)
        if event=='RC72_N7_HTTP_CALL_UPSERTED' and payload.get('worker_auth_receipt') and not revoked:
            p=prep._one('rc72_n7_execution_preparation',preparation_id=payload['preparation_id'])
            revoked.append(p['task_lease']['lease_id'])
            prep.authority.revoke_worker_lease(revoked[0])
        return result
    monkeypatch.setattr(truth,'append_atomic',persist)
    try:
        assert pipeline.complete(release_batch_id=BATCH)['status']=='HOLD'
        assert revoked and len(server.identity_calls)==1 and not server.calls
        assert truth.query('rc72_n7_http_call')[0]['state']=='UNKNOWN'
        assert not truth.query('rc72_n7_cleanup_call')
    finally:_close(server)


@pytest.mark.parametrize('change',['device_bound','foreign_probe','wildcard_role'])
def test_unsupported_or_unbounded_auth_contract_is_rejected_before_any_auth_io(tmp_path,monkeypatch,change):
    def mutate(spec):
        if change=='device_bound':spec['device_bound']=True
        elif change=='foreign_probe':spec['identity_probe']['url']='http://127.0.0.1:1/identity'
        else:spec['roles']=['*']
    truth,plan,prep,server,pipeline,root,_=_setup(tmp_path,monkeypatch,spec_mutator=mutate)
    try:
        with pytest.raises(ContractError,match='WORKER_HTTP_AUTH_'):
            pipeline.complete(release_batch_id=BATCH)
        assert not server.identity_calls and not server.calls
        assert not truth.query('rc72_n7_tool_dispatch')
        assert not truth.query('rc72_n7_http_call')
    finally:_close(server)


def test_auth_asset_expiry_during_business_retains_custody_even_when_file_is_unchanged(tmp_path,monkeypatch):
    import rc72_formal_runner_support as support
    from rc7_runtime import rc72_worker_http_auth as auth_module
    truth,plan,prep,server,pipeline,root,_=_setup(tmp_path,monkeypatch)
    original=support._Handler.do_POST
    clock=auth_module._now
    def post(handler):
        if handler.path=='/config/query':monkeypatch.setattr(auth_module,'_now',lambda:clock()+601)
        return original(handler)
    monkeypatch.setattr(support._Handler,'do_POST',post)
    try:
        assert pipeline.complete(release_batch_id=BATCH)['status']=='HOLD'
        assert len(server.calls)==1 and truth.query('rc72_n7_http_call')[0]['state']=='UNKNOWN'
        assert truth.query('rc72_n7_http_call')[0]['error_code']=='WORKER_HTTP_AUTH_ASSET_EXPIRED_OR_NOT_ISSUED'
        assert not truth.query('rc72_n7_cleanup_call')
        assert all(r['state']=='ACTIVE' for r in truth.query('rc72_data_lease'))
    finally:_close(server)


def test_authenticated_business_discrepancy_reaches_independent_n8_n9_without_exposing_secret(tmp_path,monkeypatch):
    def expectation(candidate):
        for case in candidate['cases']:
            for check in case['oracle']['checks']:
                if check['type']=='BUSINESS_RULE':check['expected']='APPROVED_OTHER_OUTCOME'
    truth,plan,prep,server,pipeline,root,secret_values=_setup(tmp_path,monkeypatch,design_mutator=expectation)
    try:
        result=pipeline.complete(release_batch_id=BATCH)
        assert result['reason']=='N9_FAILURE_QUALIFICATION_REQUIRED' and result['failure_class']=='VALID_TEST_FAILURE'
        assert len(server.calls)==1 and len(server.identity_calls)==1
        assert all(x['state']=='RELEASED' for x in truth.query('rc72_data_lease'))
        assert not truth.query('rc7_defect') and not truth.query('rc72_node_gate',node_type='N7_EXECUTION')
        diagnostic=truth.query('rc72_n8_process_diagnosis')[0]
        assert diagnostic['diagnostic_process']['pid']!=diagnostic['review_process']['pid']
        for path in (tmp_path/'captured').rglob('*'):
            if path.is_file():
                for token in secret_values:assert token.encode() not in path.read_bytes()
        before=truth.store.path.read_bytes()
        assert pipeline.complete(release_batch_id=BATCH)==result
        assert truth.store.path.read_bytes()==before and len(server.calls)==1
    finally:_close(server)
