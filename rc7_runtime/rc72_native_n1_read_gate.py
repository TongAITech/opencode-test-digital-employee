"""Live parent-owned N1 input reads, bound to canonical workitem/assignment.

No child signing key, arbitrary filesystem path or caller success callback.
Returned native observations are independently auditable after the lease closes.
"""
from collections import Counter
from copy import deepcopy
from dataclasses import asdict,dataclass
import hashlib,hmac,json,re,secrets,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path

from rc6_runtime import contracts,truth as registry
from .models import ContractError
from .rc72_ledger_lock import ledger_lock
from .rc72_n7_execution_admission import _hash
from .rc72_native_n5_tool_gate import URL_ENV,TOKEN_ENV,CONTEXT_ENV

PROTOCOL='RC72_NATIVE_N1_READ_V1'
TOOL='mcp__pfc_aitest_rc7__read_scoped_reality_source'
_KIND='rc72_n1_native_read'
_EVENT='RC72_N1_NATIVE_READ_UPSERTED'
PROTOCOL_ENV='PFC_RC72_TOOL_GATE_PROTOCOL'


def _validate(payload):
    row=deepcopy(payload)
    for key in ('record_id','gate_id','release_id','source_commit','mission_id','workitem_id',
                'worker_id','attempt_id','assignment_id','lease_id','scope_sha256','signature'):
        contracts._require_str(row,key)
    if row.get('purpose')!=PROTOCOL or row.get('kind') not in {'GATE','CALL'}:
        raise contracts.DomainValidationError('N1_NATIVE_READ_PURPOSE_INVALID')
    states={'OPEN','COMPLETED','CLOSED'} if row['kind']=='GATE' else {'IN_FLIGHT','RETURNED','UNKNOWN'}
    if row.get('state') not in states:
        raise contracts.DomainValidationError('N1_NATIVE_READ_STATE_INVALID')
    if any(k in row for k in ('token','signing_key','node_pass','field_verified','bank_final')):
        raise contracts.DomainValidationError('N1_NATIVE_READ_CLAIM_OR_SECRET_FORBIDDEN')
    row.update(artifact_type=_KIND,artifact_version=contracts._artifact_version(row))
    return row


def install_overlay():
    contracts.VALIDATORS[_KIND]=_validate
    registry.EVENT_TYPES[_EVENT]=(_KIND,'record_id')
    registry.IDENTITY_FIELDS[_KIND]='record_id'
    registry.BUCKETS[_KIND]='rc72_n1_native_reads'


def _signed(authority,row):
    raw={k:v for k,v in row.items() if k not in {'signature','artifact_type','artifact_version'}}
    if not hmac.compare_digest(row['signature'],authority._sign(raw)):
        raise ContractError('N1_NATIVE_READ_SIGNATURE_INVALID')
    return row


@dataclass(frozen=True)
class N1ReadResource:
    source_ref:str
    path:object
    def __post_init__(self):
        if not isinstance(self.source_ref,str) or not self.source_ref.strip():
            raise ContractError('N1_NATIVE_READ_RESOURCE_REFERENCE_REQUIRED')
        path=Path(self.path).expanduser()
        if path.is_symlink() or not path.is_file():
            raise ContractError('N1_NATIVE_READ_REAL_SOURCE_FILE_REQUIRED')
        object.__setattr__(self,'path',path.resolve())


def _capture_result(row):
    result=row.get('result')
    if (not isinstance(result,dict) or set(result)!={'source_ref','content_ref','sha256','size_bytes','text'}
            or result['source_ref']!=row.get('source_ref') or row.get('result_sha256')!=_hash(result)):
        raise ContractError('N1_NATIVE_READ_OBSERVATION_INVALID')
    ref=result['content_ref']
    path=Path(ref[7:]) if isinstance(ref,str) and ref.startswith('file://') else None
    if path is None or path.is_symlink() or not path.is_file():
        raise ContractError('N1_NATIVE_READ_CAPTURE_REQUIRED')
    if type(result['size_bytes']) is not int or not 0<=result['size_bytes']<=262144 or path.stat().st_size>262144:
        raise ContractError('N1_NATIVE_READ_CAPTURE_SIZE_INVALID')
    raw=path.read_bytes()
    if (len(raw)!=result['size_bytes'] or hashlib.sha256(raw).hexdigest()!=result['sha256']
            or raw.decode('utf-8-sig')!=result['text']):
        raise ContractError('N1_NATIVE_READ_CAPTURE_CHANGED')
    return result


def audit_native_handoff(service,assignment,event,calls,output):
    """Authenticate past calls without restoring permission or repeating reads."""
    install_overlay()
    authority=service.launcher.authority
    rows=service.truth.query(_KIND,record_id=event.get('native_n1_read_gate_id'))
    if len(rows)!=1:raise ContractError('N1_NATIVE_READ_GATE_REQUIRED')
    gate=_signed(authority,rows[0]);scope=gate['scope_payload']
    original=scope['canonical_assignment'];runtime=scope['runtime_assignment']
    expected=dict(release_id=original['release_id'],source_commit=original['source_commit'],
        mission_id=original['mission_id'],workitem_id=original['workitem_id'],
        worker_id=original['worker_instance_id'],attempt_id=runtime['attempt_id'],
        assignment_id=runtime['assignment_id'],lease_id=runtime['lease']['lease_id'])
    if any(gate.get(k)!=v for k,v in expected.items()):
        raise ContractError('N1_NATIVE_READ_HANDOFF_SCOPE_CHANGED')
    fixed=('release_id','source_commit','mission_id','release_batch_id','mission_node_id','workitem_id','worker_instance_id','input_refs','assignment_generation','team_role','stage','agent_id','dispatch_id')
    if (gate['kind']!='GATE' or gate['state']!='COMPLETED' or _hash(scope)!=gate['scope_sha256']
            or any(scope['canonical_assignment'].get(k)!=assignment.get(k) for k in fixed)
            or scope['canonical_assignment']['assignment_id']!=assignment['assignment_id']
            or any(scope['runtime_assignment'].get(k)!=event.get(k) for k in
                   ('assignment_id','attempt_id','mission_id','worker_instance_id','scope'))
            or gate['lease_id']!=event.get('lease_id')
            or gate.get('dsh_session_id')!=event.get('dsh_session_id')
            or gate.get('output_sha256')!=_hash(output) or gate.get('observed_calls_sha256')!=_hash(calls)):
        raise ContractError('N1_NATIVE_READ_HANDOFF_SCOPE_CHANGED')
    from rc6_runtime.authority import WorkerIdentity,TaskLease
    identity=WorkerIdentity(**scope['runtime_assignment']['identity'])
    lease_payload=dict(scope['runtime_assignment']['lease'])
    for key in ('allowed_tools','allowed_artifact_types'):lease_payload[key]=tuple(lease_payload[key])
    lease=TaskLease(**lease_payload)
    authority.validate_historical_lease(identity,lease)
    if (identity.role!='REALITY_RECON_WORKER' or identity.phase!='MISSION_NODE_EXECUTION'
            or identity.worker_id!=assignment['worker_instance_id'] or lease.allowed_artifact_types
            or identity.generation!=assignment['assignment_generation']
            or identity.session_id!='control-assignment://'+assignment['assignment_id']
            or lease.allowed_tools!=(TOOL,) or lease.scope_ref!='mission-node://'+assignment['mission_node_id']):
        raise ContractError('N1_NATIVE_READ_HISTORICAL_GRANT_INVALID')
    records=service.truth.query(_KIND,gate_id=gate['gate_id'],kind='CALL')
    if (not records or len(gate.get('call_refs',[]))!=len(records)
            or set(gate['call_refs'])!={r['record_id'] for r in records}
            or Counter(c['tool_name'] for c in calls)!=Counter(r['tool'] for r in records)):
        raise ContractError('N1_NATIVE_READ_CALL_DENOMINATOR_CHANGED')
    for row in records:
        _signed(authority,row)
        if (any(row.get(k)!=v for k,v in expected.items())
                or row['gate_id']!=gate['gate_id'] or row['state']!='RETURNED' or row['scope_sha256']!=gate['scope_sha256'] or row['tool']!=TOOL
                or row['source_ref'] not in scope['canonical_assignment']['input_refs']
                or row['arguments_sha256']!=_hash({'source_ref':row['source_ref']})
                or row['record_id']!='N1READ-'+_hash([gate['gate_id'],row['request_id']])[:24]
                or not lease.issued_at<=row['started_at']<=row['finished_at']<=lease.expires_at):
            raise ContractError('N1_NATIVE_READ_CALL_SCOPE_INVALID')
        _capture_result(row)
    return gate


class NativeN1ReadGate:
    def __init__(self,service,assignment,resources,*,capture_root):
        from .rc72_mission_node_handoff import N1DshHandoffService
        from rc6_runtime.agent_runtime import WorkerAssignment
        if not isinstance(service,N1DshHandoffService) or not isinstance(assignment,WorkerAssignment):
            raise ContractError('N1_NATIVE_READ_OWNED_SERVICE_REQUIRED')
        install_overlay()
        self.service,self.assignment=service,assignment
        self.truth,self.authority=service.truth,service.launcher.authority
        if service.launcher is None or service.allowed_tools!=(TOOL,) or assignment.lease.allowed_tools!=(TOOL,):
            raise ContractError('N1_NATIVE_READ_EXACT_TOOL_REQUIRED')
        if not isinstance(resources,(tuple,list)) or not resources or any(not isinstance(r,N1ReadResource) for r in resources):
            raise ContractError('N1_NATIVE_READ_REGISTERED_SOURCES_REQUIRED')
        self.resources={r.source_ref:r for r in resources}
        if len(self.resources)!=len(resources):raise ContractError('N1_NATIVE_READ_DUPLICATE_SOURCE')
        self.capture_root=Path(capture_root).resolve()
        self.canonical,self.task=service._preflight(self._batch())
        if set(self.resources)-set(self.canonical['input_refs']):
            raise ContractError('N1_NATIVE_READ_SOURCE_NOT_IN_WORKITEM')
        self.scope=dict(canonical_assignment=self.canonical,runtime_assignment=asdict(assignment))
        self.gate_id='N1GATE-'+_hash([assignment.assignment_id,assignment.lease.lease_id])[:24]
        self.base=dict(purpose=PROTOCOL,gate_id=self.gate_id,scope_sha256=_hash(self.scope),
            release_id=self.canonical['release_id'],source_commit=service.source_commit,
            mission_id=assignment.mission_id,workitem_id=self.canonical['workitem_id'],worker_id=assignment.worker_instance_id,
            attempt_id=assignment.attempt_id,assignment_id=assignment.assignment_id,lease_id=assignment.lease.lease_id)
        self.token=secrets.token_urlsafe(32);self.active=False;self.server=None
        self._effect=threading.Lock()

    def _batch(self):
        rows=self.truth.query('rc72_mission_node_worker_assignment',worker_instance_id=self.assignment.worker_instance_id)
        if len(rows)!=1:raise ContractError('N1_NATIVE_READ_CANONICAL_ASSIGNMENT_REQUIRED')
        return rows[0]['release_batch_id']

    def _actor(self):
        a=self.assignment
        if not self.active or getattr(self.service.launcher,'_native_gate',None) is not self:
            raise ContractError('N1_NATIVE_READ_LIVE_CONTROLLER_REQUIRED')
        current,task=self.service._preflight(self.canonical['release_batch_id'])
        if current!=self.canonical or task!=self.task:
            raise ContractError('N1_NATIVE_READ_CANONICAL_SCOPE_CHANGED')
        if (a.worker_instance_id!=current['worker_instance_id'] or a.identity.worker_id!=a.worker_instance_id
                or a.identity.role!='REALITY_RECON_WORKER' or a.identity.phase!='MISSION_NODE_EXECUTION'
                or a.attempt_id!=self.service._attempt_id(current['assignment_id'])
                or a.assignment_id!=self.service._runtime_assignment_id(current['assignment_id'])
                or a.mission_id!=current['mission_id'] or a.scope!='mission-node://'+current['mission_node_id']
                or a.scope!=a.lease.scope_ref or a.allowed_artifact_types or a.lease.allowed_artifact_types
                or tuple(a.input_refs)!=tuple(current['input_refs']) or tuple(a.allowed_tools)!=(TOOL,)
                or a.identity.generation!=current['assignment_generation']
                or a.identity.session_id!='control-assignment://'+current['assignment_id']):
            raise ContractError('N1_NATIVE_READ_RUNTIME_SCOPE_MISMATCH')
        if (self.authority.get_identity(a.worker_instance_id)!=a.identity
                or self.authority.get_lease(a.lease.lease_id)!=a.lease):
            raise ContractError('N1_NATIVE_READ_LIVE_GRANT_CHANGED')
        self.authority.authorize_tool(a.worker_instance_id,a.lease.lease_id,TOOL)

    def _persist(self,row):
        existing=self.truth.query(_KIND,record_id=row['record_id'])
        raw={k:v for k,v in row.items() if k not in {'signature','artifact_type','artifact_version'}}
        self.truth.append_atomic(_EVENT,dict(raw,signature=self.authority._sign(raw),artifact_version=existing[0]['artifact_version']+1 if existing else 1))
        return self.truth.query(_KIND,record_id=row['record_id'])[0]

    def open(self):
        with ledger_lock(self.truth,busy='N1_NATIVE_READ_LEDGER_BUSY'):
            if self.truth.query(_KIND,assignment_id=self.assignment.assignment_id):raise ContractError('N1_NATIVE_READ_EXISTING_INVOCATION_NO_REPLAY')
            self.active=True
            try:self._actor()
            except BaseException:self.active=False;raise
            self._persist(dict(self.base,record_id=self.gate_id,kind='GATE',state='OPEN',scope_payload=self.scope))
        gate=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                try:
                    if self.path!='/call' or not hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+gate.token):
                        raise ContractError('N1_NATIVE_READ_CAPABILITY_REQUIRED')
                    size=int(self.headers.get('Content-Length','0'))
                    if not 0<size<=65536:raise ContractError('N1_NATIVE_READ_REQUEST_TOO_LARGE')
                    request=json.loads(self.rfile.read(size))
                    if set(request)!={'request_id','tool','arguments'}:raise ContractError('N1_NATIVE_READ_EXACT_REQUEST_REQUIRED')
                    value,status=gate.invoke(**request),200
                except Exception as exc:value,status=dict(error=str(exc) if isinstance(exc,ContractError) else type(exc).__name__),409
                raw=json.dumps(value,ensure_ascii=False).encode()
                self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)))
                self.end_headers();self.wfile.write(raw)
        try:
            self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.server.daemon_threads=True
            threading.Thread(target=self.server.serve_forever,daemon=True).start()
        except BaseException:self.active=False;raise
        return self

    def environment(self):
        if not self.active or self.server is None:raise ContractError('N1_NATIVE_READ_LIVE_CONTROLLER_REQUIRED')
        return {URL_ENV:'http://127.0.0.1:%d/call'%self.server.server_address[1],TOKEN_ENV:self.token,
            CONTEXT_ENV:json.dumps(dict(mission_id=self.base['mission_id'],task_id=self.base['workitem_id'],worker_id=self.base['worker_id'])),
            PROTOCOL_ENV:PROTOCOL}

    def _child_result(self,row):
        result=row['result']
        if (getattr(self.service,'expected_scope_input_schema',None)=='RC72_EXPECTED_RELEASE_SCOPE_V1'
                and row['source_ref']=='release-batch://'+self.canonical['release_batch_id']):
            # N1 owns input provenance, not the full SST planning payload. Keep
            # every original byte in the signed parent observation/capture;
            # only the model-facing projection is reduced.
            from .rc72_expected_scope_input import parse_expected_scope
            view={key:result[key] for key in ('source_ref','content_ref','sha256','size_bytes')}
            view['projection']='RC72_EXPECTED_SCOPE_METADATA_V1'
            try:
                batch=self.service._one('rc72_release_batch',release_batch_id=self.canonical['release_batch_id'])
                payload=parse_expected_scope(result['text'],batch,self.service.source_commit)
                view.update(expected_requirement_count=len(payload['requirement_ssts']),
                    expected_sst_count=len(payload['required_levels_by_sst']),
                    expected_required_level_count=sum(len(v) for v in payload['required_levels_by_sst'].values()))
            except (ContractError,ValueError,TypeError) as exc:
                view['policy_error']=str(exc) if isinstance(exc,ContractError) else 'EXPECTED_SCOPE_JSON_INVALID'
            result=view
        return dict(result=result,call_id=row['record_id'])

    def invoke(self,request_id,tool,arguments):
        if not isinstance(request_id,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,96}',request_id):
            raise ContractError('N1_NATIVE_READ_REQUEST_ID_INVALID')
        arguments=json.loads(json.dumps(arguments,allow_nan=False))
        with self._effect:
            with ledger_lock(self.truth,busy='N1_NATIVE_READ_LEDGER_BUSY'):
                self._actor()
                if tool!=TOOL or not isinstance(arguments,dict) or set(arguments)!={'source_ref'} or arguments['source_ref'] not in self.resources:
                    raise ContractError('N1_NATIVE_READ_ARGUMENTS_OUTSIDE_SCOPE')
                rid='N1READ-'+_hash([self.gate_id,request_id])[:24]
                existing=self.truth.query(_KIND,record_id=rid)
                if existing:
                    row=_signed(self.authority,existing[0])
                    if row['state']!='RETURNED':raise ContractError('N1_NATIVE_READ_UNKNOWN_EFFECT_NO_REPLAY')
                    if row['source_ref']!=arguments['source_ref']:raise ContractError('N1_NATIVE_READ_REQUEST_SCOPE_CHANGED')
                    _capture_result(row)
                    return self._child_result(row)
                row=self._persist(dict(self.base,record_id=rid,kind='CALL',request_id=request_id,tool=tool,
                    source_ref=arguments['source_ref'],arguments_sha256=_hash(arguments),state='IN_FLIGHT',started_at=int(time.time())))
            observed={}
            try:
                path=self.resources[arguments['source_ref']].path
                if path.is_symlink() or path.resolve()!=path:raise ContractError('N1_NATIVE_READ_SOURCE_PATH_CHANGED')
                with path.open('rb') as stream:raw=stream.read(262145)
                if len(raw)>262144:raise ContractError('N1_NATIVE_READ_SOURCE_SIZE_EXCEEDED')
                text=raw.decode('utf-8-sig');sha=hashlib.sha256(raw).hexdigest()
                self.capture_root.mkdir(parents=True,exist_ok=True);capture=self.capture_root/(sha+'.source')
                if capture.is_symlink() or capture.exists() and capture.read_bytes()!=raw:raise ContractError('N1_NATIVE_READ_CAPTURE_CONFLICT')
                if not capture.exists():
                    import os
                    with capture.open('xb') as target:target.write(raw);target.flush();os.fsync(target.fileno())
                result=dict(source_ref=arguments['source_ref'],content_ref='file://'+str(capture),sha256=sha,size_bytes=len(raw),text=text)
                observed=dict(result=result,result_sha256=_hash(result))
                with ledger_lock(self.truth,busy='N1_NATIVE_READ_LEDGER_BUSY'):
                    self._actor()
                    row=self._persist(dict(row,state='RETURNED',**observed,finished_at=int(time.time())))
                return self._child_result(row)
            except BaseException as exc:
                with ledger_lock(self.truth,busy='N1_NATIVE_READ_LEDGER_BUSY'):
                    current=self.truth.query(_KIND,record_id=rid)[0]
                    if current['state']!='RETURNED':self._persist(dict(current,state='UNKNOWN',**observed,error_type=type(exc).__name__))
                raise

    def observed(self,calls):
        records=self.truth.query(_KIND,gate_id=self.gate_id,kind='CALL')
        if not records or any(r['state']!='RETURNED' for r in records) or Counter(c['tool_name'] for c in calls)!=Counter(r['tool'] for r in records):
            raise ContractError('N1_NATIVE_READ_ACTUAL_CALLS_REQUIRED')
        for row in records:_signed(self.authority,row);_capture_result(row)
        return records

    def complete(self,invocation,output):
        with ledger_lock(self.truth,busy='N1_NATIVE_READ_LEDGER_BUSY'):
            self._actor();records=self.observed(invocation.tool_calls)
            gate=self.truth.query(_KIND,record_id=self.gate_id)[0]
            self._persist(dict(gate,state='COMPLETED',call_refs=[r['record_id'] for r in records],
                dsh_session_id=invocation.dsh_session_id,observed_calls_sha256=_hash(invocation.tool_calls),output_sha256=_hash(output)))

    def close(self):
        self.active=False;self.token=''
        if self.server is not None:self.server.shutdown();self.server.server_close();self.server=None
        with ledger_lock(self.truth,busy='N1_NATIVE_READ_LEDGER_BUSY'):
            rows=self.truth.query(_KIND,record_id=self.gate_id)
            if rows and rows[0]['state']=='OPEN':self._persist(dict(rows[0],state='CLOSED'))


install_overlay()
