"""Parent-owned actual API I/O, bound to one live native N7 invocation.

The child receives a revocable local capability, never a signing key or a way
to choose another endpoint, method or payload. Unknown effects are not replayed.
"""
from copy import deepcopy
from contextlib import contextmanager,ExitStack
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import urlsplit
from urllib.error import HTTPError
from urllib.request import Request,build_opener,HTTPRedirectHandler,ProxyHandler

from rc6_runtime import contracts,truth as registry
from .models import ContractError
from .rc72_ledger_lock import ledger_lock
from .rc72_n7_execution_admission import _hash
from .rc72_http_projection import map_response as _mapped

PROTOCOL='RC72_NATIVE_API_HTTP_V1'
URL_ENV='RC72_NATIVE_HTTP_URL'
TOKEN_ENV='RC72_NATIVE_HTTP_TOKEN'
_KIND='rc72_n7_http_call'
_EVENT='RC72_N7_HTTP_CALL_UPSERTED'


def _validate(payload):
    row=deepcopy(payload)
    for key in ('call_id','preparation_id','release_id','source_commit','mission_id','workitem_id','attempt_id',
                'worker_id','contract_id','contract_sha256','request_sha256','transport_sha256','business_auth_role','signature'):
        contracts._require_str(row,key)
    if row.get('purpose')!=PROTOCOL or row.get('state') not in {'IN_FLIGHT','RETURNED','UNKNOWN'}:
        raise contracts.DomainValidationError('N7_NATIVE_HTTP_CALL_INVALID')
    if row['business_auth_role']!='ANONYMOUS' or not isinstance(row.get('authorization'),dict):
        raise contracts.DomainValidationError('N7_NATIVE_HTTP_AUTHORIZATION_REQUIRED')
    if row['state']=='RETURNED':
        for key in ('response_ref','response_sha256','result_sha256'):
            contracts._require_str(row,key)
        if (not isinstance(row.get('completed_authorization'),dict)
                or not isinstance(row.get('status_code'),int) or isinstance(row.get('status_code'),bool)
                or not 100<=row['status_code']<=599 or not isinstance(row.get('result'),dict) or not row['result']):
            raise contracts.DomainValidationError('N7_NATIVE_HTTP_RETURNED_OBSERVATION_REQUIRED')
    if any(k in row for k in ('case_pass','field_verified','bank_final','token')):
        raise contracts.DomainValidationError('N7_NATIVE_HTTP_CALL_CLAIM_OR_SECRET_FORBIDDEN')
    row.update(artifact_type=_KIND,artifact_version=contracts._artifact_version(row))
    return row


def install_overlay():
    contracts.VALIDATORS[_KIND]=_validate
    registry.EVENT_TYPES[_EVENT]=(_KIND,'call_id')
    registry.IDENTITY_FIELDS[_KIND]='call_id'
    registry.BUCKETS[_KIND]='rc72_n7_http_calls'


def validate_mapping(transport,sources):
    if (not isinstance(transport,dict) or set(transport)!={'protocol','source_ref','result_mapping','auth_mode'}
            or transport.get('protocol')!=PROTOCOL or transport.get('auth_mode')!='ANONYMOUS'
            or transport.get('source_ref') not in sources):
        raise ContractError('N7_NATIVE_HTTP_APPROVED_TRANSPORT_REQUIRED')
    mapping=transport['result_mapping']
    if (not isinstance(mapping,dict) or not mapping
            or any(not isinstance(k,str) or not k or k in {'evidence','runner_receipt_id'} for k in mapping)
            or any(not isinstance(v,str) or not (v=='$http' or v=='$json' or v.startswith('$json.')) for v in mapping.values())):
        raise ContractError('N7_NATIVE_HTTP_FROZEN_RESULT_MAPPING_REQUIRED')
    return deepcopy(transport)


def validate_transport(transport,contract):
    validate_mapping(transport,contract['authoritative_sources'])
    if contract['tool_route']['family']!='API':
        raise ContractError('N7_NATIVE_HTTP_APPROVED_TRANSPORT_REQUIRED')
    profile=contract['environment'].get('target_profile',{})
    auth_id=profile.get('selectors',{}).get('auth_fact_id')
    facts=[r for r in profile.get('facts',[]) if r.get('kind')=='auth' and r.get('id')==auth_id]
    if len(facts)!=1 or facts[0].get('attributes',{}).get('authentication_mode')!='ANONYMOUS':
        raise ContractError('N7_NATIVE_HTTP_AUTH_PROVIDER_REQUIRED:N1')
    route=urlsplit(contract['endpoint']['url'])
    if route.scheme not in {'http','https'} or not route.netloc or route.username or route.password or route.fragment:
        raise ContractError('N7_NATIVE_HTTP_EXACT_HTTP_TARGET_REQUIRED')
    if contract['request'].get('content_type','application/json')!='application/json':
        raise ContractError('N7_NATIVE_HTTP_JSON_CONTENT_TYPE_REQUIRED')
    try:
        json.dumps(contract['input'],allow_nan=False)
    except (ValueError,TypeError) as exc:
        raise ContractError('N7_NATIVE_HTTP_JSON_INPUT_REQUIRED') from exc
    if contract['request']['method'].upper() in {'GET','HEAD'} and contract['input']:
        raise ContractError('N7_NATIVE_HTTP_GET_INPUT_BINDING_REQUIRED')
    if contract['request']['method'].upper() not in {'GET','POST','PUT','PATCH','DELETE','HEAD'}:
        raise ContractError('N7_NATIVE_HTTP_METHOD_NOT_SUPPORTED')
    return deepcopy(transport)


def verify_receipt(preparation,p,contract,call_id,transport,actual):
    install_overlay()
    row=preparation._one(_KIND,call_id=call_id)
    signed={k:v for k,v in row.items() if k not in {'signature','artifact_type','artifact_version'}}
    if not hmac.compare_digest(row['signature'],preparation.authority._sign(signed)):
        raise ContractError('N7_NATIVE_HTTP_SIGNATURE_INVALID')
    if row['state']!='RETURNED':
        raise ContractError('N7_NATIVE_HTTP_RETURNED_SCOPE_REQUIRED')
    from .rc72_lease_renewal import verify_execution_authorization
    verify_execution_authorization(preparation,p,row.get('authorization'))
    verify_execution_authorization(preparation,p,row.get('completed_authorization'))
    request=_request(contract)
    if (row['state']!='RETURNED' or row.get('business_auth_role')!='ANONYMOUS' or row['call_id']!='N7HTTP-'+_hash([p['preparation_id'],contract['contract_sha256']])[:24]
            or any(row.get(k)!=p[k] for k in ('preparation_id','release_id','source_commit','mission_id','workitem_id','attempt_id','worker_id','contract_id'))
            or row['contract_sha256']!=contract['contract_sha256'] or row['request_sha256']!=_hash(request)
            or row['transport_sha256']!=_hash(validate_transport(transport,contract))
            or row.get('result')!=actual or row.get('result_sha256')!=_hash(actual)):
        raise ContractError('N7_NATIVE_HTTP_RETURNED_SCOPE_REQUIRED')
    path=Path(row['response_ref'][len('file://'):]) if row['response_ref'].startswith('file://') else None
    if path is None or path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=row['response_sha256']:
        raise ContractError('N7_NATIVE_HTTP_RESPONSE_BYTES_CHANGED')
    raw=path.read_bytes()
    try:
        body=json.loads(raw.decode('utf-8'))
    except (ValueError,UnicodeError):
        body=None
    if _mapped(transport['result_mapping'],row['status_code'],body)!=actual:
        raise ContractError('N7_NATIVE_HTTP_ACTUAL_RESULT_CHANGED')
    return row


def _request(contract):
    method=contract['request']['method'].upper()
    return dict(url=contract['endpoint']['url'],method=method,
        body=deepcopy(contract['input']) if method not in {'GET','HEAD'} else None)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        return None


class NativeHTTPGate:
    def __init__(self,preparation,p,contract,transport,dispatcher,*,evidence_root,timeout_seconds=30):
        install_overlay()
        self.preparation,self.truth,self.authority=preparation,preparation.truth,preparation.authority
        self.p,self.contract=deepcopy(p),deepcopy(contract)
        self.transport=validate_transport(transport,contract)
        self.dispatcher=dispatcher
        self.root=Path(evidence_root).resolve()
        if isinstance(timeout_seconds,bool) or not isinstance(timeout_seconds,(int,float)) or not timeout_seconds>0:
            raise ContractError('N7_NATIVE_HTTP_TIMEOUT_REQUIRED')
        self.timeout=min(float(timeout_seconds),30)
        self.call_id='N7HTTP-'+_hash([p['preparation_id'],contract['contract_sha256']])[:24]
        self.token=secrets.token_urlsafe(32)
        self.active=False
        self.server=None
        self._effect=threading.Lock()

    @contextmanager
    def _decision(self):
        # Retry only lock acquisition before entering a decision. No handler or
        # external request is repeated because of this bounded contention wait.
        deadline=time.monotonic()+min(self.timeout,10)
        with ExitStack() as stack:
            while True:
                try:
                    stack.enter_context(ledger_lock(self.truth,busy='N7_NATIVE_HTTP_LEDGER_BUSY'))
                    break
                except ContractError as exc:
                    if str(exc)!='N7_NATIVE_HTTP_LEDGER_BUSY' or time.monotonic()>=deadline:
                        raise
                    time.sleep(0.01)
            yield

    def _actor(self):
        pid=self.p['preparation_id']
        if (not self.active or self.dispatcher is None
                or self.preparation._active_dispatches.get(pid) is not self.dispatcher
                or pid not in self.dispatcher._live_invocations):
            raise ContractError('N7_NATIVE_HTTP_LIVE_DISPATCH_REQUIRED')
        current=self.preparation._assert_current_locked(pid)
        if current!=self.p or self.preparation._one('rc72_n6_executable_contract',contract_id=self.p['contract_id'])!=self.contract:
            raise ContractError('N7_NATIVE_HTTP_PREPARATION_CHANGED')
        plan=self.preparation._one('rc72_n7_execution_plan',plan_id=self.p['plan_id'])
        snapshot=self.preparation._one('rc72_decomposition_snapshot',snapshot_id=plan['snapshot_id'])
        cases=[r for r in snapshot['planning_cases'] if r['case_id']==self.p['case_id']]
        if len(cases)!=1 or cases[0]['auth_role']!='ANONYMOUS':
            raise ContractError('N7_NATIVE_HTTP_AUTH_ROLE_NOT_SUPPORTED')
        self.authority.authorize_tool(self.p['worker_id'],self.p['task_lease']['lease_id'],self.contract['tool_route']['tool'])

    def _persist(self,row):
        existing=self.truth.query(_KIND,call_id=self.call_id)
        raw={k:v for k,v in row.items() if k not in {'signature','artifact_type','artifact_version'}}
        value=dict(raw,signature=self.authority._sign(raw),artifact_version=existing[0]['artifact_version']+1 if existing else 1)
        self.truth.append_atomic(_EVENT,value)
        return self.preparation._one(_KIND,call_id=self.call_id)

    def open(self):
        with self._decision():
            if self.truth.query(_KIND,call_id=self.call_id):
                raise ContractError('N7_NATIVE_HTTP_EXISTING_EFFECT_RECOVERY_REQUIRED')
            self.active=True
            try:
                self._actor()
            except BaseException:
                self.active=False
                raise
        gate=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):
                pass
            def do_POST(self):
                try:
                    if self.path!='/execute' or not hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+gate.token):
                        raise ContractError('N7_NATIVE_HTTP_CAPABILITY_REQUIRED')
                    size=int(self.headers.get('Content-Length','0'))
                    if not 0<size<=256 or json.loads(self.rfile.read(size))!={'request_id':'business'}:
                        raise ContractError('N7_NATIVE_HTTP_FIXED_REQUEST_REQUIRED')
                    result,status=gate.invoke(),200
                except Exception as exc:
                    result,status=dict(error=str(exc) if isinstance(exc,ContractError) else type(exc).__name__),409
                data=json.dumps(result,ensure_ascii=False).encode()
                self.send_response(status)
                self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        try:
            self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
            self.server.daemon_threads=True
            threading.Thread(target=self.server.serve_forever,daemon=True).start()
        except BaseException:
            self.active=False
            raise
        return self

    def environment(self):
        if not self.active or self.server is None:
            raise ContractError('N7_NATIVE_HTTP_LIVE_DISPATCH_REQUIRED')
        return {URL_ENV:'http://127.0.0.1:%d/execute'%self.server.server_address[1],TOKEN_ENV:self.token}

    def invoke(self):
        with self._effect:
            with self._decision():
                self._actor()
                existing=self.truth.query(_KIND,call_id=self.call_id)
                if existing:
                    row=existing[0]
                    if row['state']!='RETURNED':
                        raise ContractError('N7_NATIVE_HTTP_UNKNOWN_EFFECT_NO_REPLAY')
                    verify_receipt(self.preparation,self.p,self.contract,self.call_id,self.transport,row['result'])
                    return dict(call_id=self.call_id,result=row['result'])
                request=_request(self.contract)
                from .rc72_lease_renewal import execution_authorization_snapshot
                row=self._persist(dict(purpose=PROTOCOL,call_id=self.call_id,state='IN_FLIGHT',
                    **{k:self.p[k] for k in ('preparation_id','release_id','source_commit','mission_id','workitem_id','attempt_id','worker_id','contract_id')},
                    contract_sha256=self.contract['contract_sha256'],request_sha256=_hash(request),transport_sha256=_hash(self.transport),
                    business_auth_role='ANONYMOUS',authorization=execution_authorization_snapshot(self.preparation,self.p),started_at=int(time.time())))
            observed={}
            try:
                data=None if request['body'] is None else json.dumps(request['body'],sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()
                req=Request(request['url'],data=data,headers={'Content-Type':'application/json'},method=request['method'])
                opener=build_opener(ProxyHandler({}),_NoRedirect())
                try:
                    response=opener.open(req,timeout=self.timeout)
                except HTTPError as exc:
                    response=exc
                with response:
                    status=response.code
                    raw=response.read(16*1024*1024+1)
                if len(raw)>16*1024*1024:
                    raise ContractError('N7_NATIVE_HTTP_RESPONSE_SIZE_LIMIT')
                self.root.mkdir(parents=True,exist_ok=True)
                path=self.root/(hashlib.sha256(raw).hexdigest()+'.body')
                if path.exists() and path.read_bytes()!=raw or path.is_symlink():
                    raise ContractError('N7_NATIVE_HTTP_CAPTURE_CONFLICT')
                if not path.exists():
                    with path.open('xb') as out:
                        out.write(raw)
                        out.flush()
                        import os
                        os.fsync(out.fileno())
                try:
                    body=json.loads(raw.decode('utf-8'))
                except (ValueError,UnicodeError):
                    body=None
                observed=dict(status_code=status,response_ref='file://'+str(path),response_sha256=hashlib.sha256(raw).hexdigest())
                result=_mapped(self.transport['result_mapping'],status,body)
                with self._decision():
                    self._actor()
                    row=self._persist(dict(row,state='RETURNED',**observed,result=result,result_sha256=_hash(result),
                        completed_authorization=execution_authorization_snapshot(self.preparation,self.p),finished_at=int(time.time())))
                return dict(call_id=self.call_id,result=result)
            except BaseException as exc:
                with self._decision():
                    current=self.preparation._one(_KIND,call_id=self.call_id)
                    if current['state']!='RETURNED':
                        self._persist(dict(row,state='UNKNOWN',**observed,error_type=type(exc).__name__,finished_at=int(time.time())))
                raise

    def close(self):
        self.active=False
        self.token=''
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server=None


install_overlay()
