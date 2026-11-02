"""Parent-owned, call-time N5 tool execution for exact existing-data repair.

The child receives an invocation capability, never the authority signing key.
Only registered parent handlers execute effects. Durable intent precedes I/O;
unknown effects cannot be automatically replayed by another controller.
"""
from collections import Counter
from copy import deepcopy
from dataclasses import asdict, dataclass
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import secrets
import threading
import time

from rc6_runtime import contracts, truth as registry
from rc6_runtime.agent_runtime import WorkerAssignment
from .models import ContractError
from .rc72_ledger_lock import ledger_lock
from .rc72_n7_execution_admission import _hash

_CALL = 'rc72_native_tool_call'
_GATE = 'rc72_native_tool_gate'
_CALL_EVENT = 'RC72_NATIVE_TOOL_CALL_UPSERTED'
_GATE_EVENT = 'RC72_NATIVE_TOOL_GATE_UPSERTED'
PROTOCOL = 'RC72_NATIVE_N5_CALL_GATE_V1'
URL_ENV = 'PFC_RC72_TOOL_GATE_URL'
TOKEN_ENV = 'PFC_RC72_TOOL_GATE_TOKEN'
CONTEXT_ENV = 'PFC_RC72_TOOL_GATE_CONTEXT'


def _validate(payload):
    row = deepcopy(payload)
    for key in ('gate_id', 'release_id', 'source_commit', 'mission_id', 'repair_id', 'worker_id',
                'workitem_id', 'attempt_id', 'assignment_id', 'lease_id', 'data_ref', 'signature'):
        contracts._require_str(row, key)
    if row.get('purpose') != PROTOCOL:
        raise contracts.DomainValidationError('NATIVE_TOOL_GATE_PURPOSE_INVALID')
    if row.get('kind') == 'CALL':
        contracts._require_str(row, 'call_id')
        contracts._require_str(row, 'request_id')
        contracts._require_str(row, 'tool')
        if row.get('access_mode') not in {'READ', 'WRITE'}:
            raise contracts.DomainValidationError('NATIVE_TOOL_ACCESS_MODE_INVALID')
        if row.get('state') not in {'IN_FLIGHT', 'RETURNED', 'UNKNOWN'}:
            raise contracts.DomainValidationError('NATIVE_TOOL_CALL_STATE_INVALID')
        kind = _CALL
    else:
        if row.get('kind') != 'GATE' or row.get('state') not in {'OPEN', 'COMPLETED', 'CLOSED'}:
            raise contracts.DomainValidationError('NATIVE_TOOL_GATE_STATE_INVALID')
        kind = _GATE
    for key in ('case_pass', 'field_verified', 'bank_final', 'n5_pass'):
        if key in row:
            raise contracts.DomainValidationError('NATIVE_TOOL_PREMATURE_CLAIM')
    row.update(artifact_type=kind, artifact_version=contracts._artifact_version(row))
    return row


def install_rc72_native_tool_gate_overlay():
    for kind, event, key, bucket in ((_CALL, _CALL_EVENT, 'call_id', 'rc72_native_tool_calls'),
                                    (_GATE, _GATE_EVENT, 'gate_id', 'rc72_native_tool_gates')):
        contracts.VALIDATORS[kind] = _validate
        registry.EVENT_TYPES[event] = (kind, key)
        registry.IDENTITY_FIELDS[kind] = key
        registry.BUCKETS[kind] = bucket


def _signed(authority, row):
    raw = {k: v for k, v in row.items() if k not in {'signature', 'artifact_type', 'artifact_version'}}
    if not hmac.compare_digest(row['signature'], authority._sign(raw)):
        raise ContractError('NATIVE_TOOL_RECEIPT_SIGNATURE_INVALID')
    return row


@dataclass(frozen=True)
class N5ToolHandler:
    name: str
    mode: str
    execute: object

    def __post_init__(self):
        if (not isinstance(self.name, str) or not self.name.startswith('mcp__pfc_aitest_rc7__')
                or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]{0,80}', self.name[len('mcp__pfc_aitest_rc7__'):])
                or '*' in self.name or self.mode not in {'READ', 'WRITE'} or not callable(self.execute)):
            raise ContractError('NATIVE_N5_REGISTERED_EXACT_HANDLER_REQUIRED')


def _scope(row, actor):
    return dict(release_id=row['release_id'], source_commit=row['source_commit'], mission_id=row['mission_id'],
        repair_id=row['repair_id'], workitem_id=actor['workitem_id'], worker_id=actor['identity']['worker_id'],
        attempt_id=actor['verification_attempt_id'], assignment_id=actor['assignment_id'], lease_id=actor['lease']['lease_id'],
        identity=actor['identity'], lease=actor['lease'], allowed_tools=actor['allowed_tools'],
        data_ref=row['original_binding']['data_ref'], precondition_refs=row['original_binding']['precondition_refs'],
        binding_revision=row['original_binding']['artifact_version'], source_case_sha256=row['requirement']['source_case_sha256'])


def verify_native_handoff(service, row, actor, event, calls, output):
    """Historical proof only: never reconstitute a token, lease or live gate."""
    gate_id = event.get('native_tool_gate_id')
    gate = _signed(service.authority, service._one(_GATE, gate_id=gate_id))
    scope = _scope(row, actor)
    if (gate['state'] != 'COMPLETED' or gate.get('scope_sha256') != _hash(scope)
            or any(gate[k] != v for k, v in scope.items() if k in gate)
            or gate.get('observed_calls_sha256') != _hash(calls) or gate.get('output_sha256') != _hash(output)
            or gate.get('dsh_session_id') != event.get('dsh_session_id')):
        raise ContractError('NATIVE_TOOL_HANDOFF_SCOPE_OR_OBSERVATION_CHANGED')
    refs = gate.get('call_refs', [])
    records = service.truth.query(_CALL, gate_id=gate_id)
    if not refs or set(refs) != {c['call_id'] for c in records} or len(refs) != len(records):
        raise ContractError('NATIVE_TOOL_HANDOFF_DENOMINATOR_CHANGED')
    for call in records:
        _signed(service.authority, call)
        if (call['state'] != 'RETURNED' or call['scope_sha256'] != gate['scope_sha256']
                or call['result_sha256'] != _hash(call['result'])
                or call['arguments_sha256'] != _hash(dict(data_ref=scope['data_ref'], precondition_refs=scope['precondition_refs']))
                or call['tool'] not in scope['allowed_tools']
                or call['call_id'] != 'N5TOOL-' + _hash([gate_id, call['request_id']])[:24]):
            raise ContractError('NATIVE_TOOL_HANDOFF_CALL_INVALID')
    if Counter(c['tool'] for c in records) != Counter(c['tool_name'] for c in calls):
        raise ContractError('NATIVE_TOOL_HANDOFF_TOOL_MISMATCH')
    _verify_output(scope, records, output)
    return gate


def _validate_observation(scope, result):
    if (not isinstance(result, dict) or set(result) != {'data_ref', 'data_exists', 'precondition_results'}
            or result['data_ref'] != scope['data_ref'] or not isinstance(result['data_exists'], bool)
            or not isinstance(result['precondition_results'], dict)
            or set(result['precondition_results']) != set(scope['precondition_refs'])
            or not all(isinstance(v, bool) for v in result['precondition_results'].values())):
        raise ContractError('NATIVE_N5_ACTUAL_OBSERVATION_SCHEMA_INVALID')


def _verify_output(scope, records, output):
    if not records:
        raise ContractError('NATIVE_TOOL_ACTUAL_CALL_REQUIRED')
    for record in records:
        _validate_observation(scope, record['result'])
    actual = records[-1]['result']
    success = actual['data_exists'] and all(actual['precondition_results'].values())
    prepared = scope['identity']['role'] == 'DATA_PREPARER'
    expected = ('PREPARED' if prepared else 'VERIFIED') if success else 'REPAIR_REQUIRED'
    if output.get('status') not in {expected, 'REPAIR_REQUIRED'} or output.get('data_ref') != scope['data_ref']:
        raise ContractError('NATIVE_TOOL_OUTPUT_CONTRADICTS_ACTUAL_OBSERVATION')


class NativeN5ToolGate:
    def __init__(self, service, assignment, handlers):
        from .rc72_n5_existing_data_repair import ExistingDataRepairService
        if not isinstance(service, ExistingDataRepairService) or not isinstance(assignment, WorkerAssignment):
            raise ContractError('NATIVE_N5_OWNED_SERVICE_ASSIGNMENT_REQUIRED')
        self.service, self.assignment = service, assignment
        self.truth, self.authority = service.truth, service.authority
        if not isinstance(handlers, (list, tuple)):
            raise ContractError('NATIVE_N5_REGISTERED_HANDLER_SET_REQUIRED')
        self.handlers = {h.name: h for h in handlers if isinstance(h, N5ToolHandler)}
        if len(self.handlers) != len(handlers) or set(assignment.allowed_tools) - set(self.handlers):
            raise ContractError('NATIVE_N5_REGISTERED_HANDLER_SET_REQUIRED')
        matches = []
        for row in self.truth.query('rc72_n5_existing_data_repair'):
            for stage, actor in (('VERIFIER', row), ('PREPARER', row.get('producer', {}))):
                if actor.get('assignment_id') == assignment.assignment_id:
                    matches.append((row, stage, actor))
        if len(matches) != 1:
            raise ContractError('NATIVE_N5_ASSIGNMENT_NOT_UNIQUE')
        row, self.stage, actor = matches[0]
        service._signed(row)
        self.repair_id = row['repair_id']
        self.scope = _scope(row, actor)
        self.gate_id = 'N5GATE-' + _hash([assignment.assignment_id, assignment.lease.lease_id])[:24]
        self.expected_args = dict(data_ref=self.scope['data_ref'], precondition_refs=self.scope['precondition_refs'])
        self.token = secrets.token_urlsafe(32)
        self.active, self.server, self.thread = False, None, None
        self._mutex = threading.RLock()
        self._effect_mutex = threading.Lock()
        self._base = dict(purpose=PROTOCOL, gate_id=self.gate_id, scope_sha256=_hash(self.scope),
                         **{k: self.scope[k] for k in ('release_id', 'source_commit', 'mission_id', 'repair_id',
                             'worker_id', 'workitem_id', 'attempt_id', 'assignment_id', 'lease_id', 'data_ref')})

    def _persist(self, kind, payload):
        key, event = ('call_id', _CALL_EVENT) if kind == _CALL else ('gate_id', _GATE_EVENT)
        current = self.truth.query(kind, **{key: payload[key]})
        raw = {k: v for k, v in payload.items() if k not in {'signature', 'artifact_type', 'artifact_version'}}
        value = dict(raw, signature=self.authority._sign(raw), artifact_version=current[0]['artifact_version'] + 1 if current else 1)
        try:
            self.truth.append_atomic(event, value)
        except Exception:
            self.truth.rebuild_projection()
            observed = self.truth.query(kind, **{key: payload[key]})
            if not observed or _hash(observed[0]) != _hash(dict(value, artifact_type=kind)):
                raise
        return _signed(self.authority, self.service._one(kind, **{key: payload[key]}))

    def _validate_actor(self):
        row = self.service._signed(self.service._one('rc72_n5_existing_data_repair', repair_id=self.repair_id))
        self.service._live(row)
        actor = self.service._producer_row(row) if self.stage == 'PREPARER' else row
        if actor.get('state') != 'DISPATCHING' or _hash(_scope(row, actor)) != _hash(self.scope):
            raise ContractError('NATIVE_N5_CURRENT_ACTOR_CHANGED')
        a = self.assignment
        if (_hash(asdict(a.identity)) != _hash(actor['identity']) or _hash(asdict(a.lease)) != _hash(actor['lease'])
                or a.scope != 'task:%s/attempt:%s' % (actor['workitem_id'], actor['verification_attempt_id'])
                or a.worker_instance_id != actor['identity']['worker_id'] or a.attempt_id != actor['verification_attempt_id']
                or tuple(a.allowed_tools) != tuple(actor['allowed_tools']) or a.allowed_artifact_types
                or a.lease.allowed_artifact_types or tuple(a.lease.allowed_tools) != tuple(actor['allowed_tools'])):
            raise ContractError('NATIVE_N5_SIGNED_ASSIGNMENT_SCOPE_CHANGED')
        task = self.service._ensure_workitem(actor, create=False)
        if task['state'] != 'RUNNING' or task.get('lease_owner') != a.worker_instance_id:
            raise ContractError('NATIVE_N5_CURRENT_WORKITEM_OWNER_REQUIRED')
        expected_role, expected_phase = ('DATA_PREPARER', 'DATA_REPAIR_PREPARATION') if self.stage == 'PREPARER' else ('DATA_VERIFIER', 'DATA_VERIFICATION')
        if a.identity.role != expected_role or a.identity.phase != expected_phase or int(time.time()) >= a.lease.expires_at:
            raise ContractError('NATIVE_N5_ROLE_PHASE_OR_DEADLINE_INVALID')
        for tool in a.allowed_tools:
            if expected_role == 'DATA_VERIFIER' and self.handlers[tool].mode != 'READ':
                raise ContractError('NATIVE_N5_VERIFIER_WRITE_FORBIDDEN')
            self.authority.authorize_tool(a.worker_instance_id, a.lease.lease_id, tool)

    def open(self):
        with self._mutex, ledger_lock(self.truth, busy='NATIVE_TOOL_LEDGER_BUSY'):
            if self.active or self.truth.query(_GATE, gate_id=self.gate_id):
                raise ContractError('NATIVE_TOOL_EXISTING_INVOCATION_RECOVERY_REQUIRED')
            self._validate_actor()
            self._persist(_GATE, dict(self._base, kind='GATE', state='OPEN', started_at=int(time.time())))
            self.active = True
        gate = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                try:
                    if self.path != '/call' or not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + gate.token):
                        raise ContractError('NATIVE_TOOL_INVOCATION_CAPABILITY_REQUIRED')
                    size = int(self.headers.get('Content-Length', '0'))
                    if not 0 < size <= 65536:
                        raise ContractError('NATIVE_TOOL_REQUEST_SIZE_INVALID')
                    request = json.loads(self.rfile.read(size))
                    if set(request) != {'request_id', 'tool', 'arguments'}:
                        raise ContractError('NATIVE_TOOL_REQUEST_FIELDS_INVALID')
                    response, status = gate.invoke(**request), 200
                except Exception as exc:
                    response, status = dict(error=str(exc) if isinstance(exc, ContractError) else type(exc).__name__), 409
                raw = json.dumps(response, ensure_ascii=False).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
        try:
            self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            self.server.daemon_threads = True
            self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.thread.start()
        except BaseException:
            self.close()
            raise
        return self

    def environment(self):
        if not self.active or self.server is None:
            raise ContractError('NATIVE_TOOL_LIVE_CONTROLLER_REQUIRED')
        return {URL_ENV: 'http://127.0.0.1:%d/call' % self.server.server_address[1], TOKEN_ENV: self.token,
                CONTEXT_ENV: json.dumps(dict(mission_id=self.scope['mission_id'], task_id=self.scope['workitem_id'],
                    worker_id=self.scope['worker_id']), sort_keys=True)}

    def invoke(self, request_id, tool, arguments):
        with self._effect_mutex:
            return self._invoke_owned(request_id, tool, arguments)

    def _invoke_owned(self, request_id, tool, arguments):
        if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,96}', request_id):
            raise ContractError('NATIVE_TOOL_REQUEST_ID_INVALID')
        # Freeze JSON bytes before authorization; a mutable caller object cannot
        # change the actual handler arguments after the decision.
        arguments = json.loads(json.dumps(arguments, allow_nan=False))
        with self._mutex, ledger_lock(self.truth, busy='NATIVE_TOOL_LEDGER_BUSY'):
            if not self.active:
                raise ContractError('NATIVE_TOOL_LIVE_CONTROLLER_REQUIRED')
            self._validate_actor()
            if tool not in self.assignment.allowed_tools or _hash(arguments) != _hash(self.expected_args):
                raise ContractError('NATIVE_TOOL_NAME_OR_EXACT_ARGUMENTS_FORBIDDEN')
            call_id = 'N5TOOL-' + _hash([self.gate_id, request_id])[:24]
            prior = self.truth.query(_CALL, call_id=call_id)
            if prior:
                row = _signed(self.authority, prior[0])
                if (row['tool'] != tool or row['arguments_sha256'] != _hash(arguments)
                        or row['gate_id'] != self.gate_id or row['scope_sha256'] != self._base['scope_sha256']):
                    raise ContractError('NATIVE_TOOL_REQUEST_REPLAY_SCOPE_CHANGED')
                if row['state'] != 'RETURNED':
                    raise ContractError('NATIVE_TOOL_EFFECTS_UNKNOWN_NO_REPLAY')
                return dict(result=row['result'], call_id=call_id)
            if self.truth.query(_CALL, gate_id=self.gate_id, tool=tool):
                raise ContractError('NATIVE_TOOL_SINGLE_EXACT_OPERATION_REQUIRED')
            mode = self.handlers[tool].mode
            for owner in self.truth.query('rc72_data_lease', data_ref=self.scope['data_ref']):
                if owner['state'] in {'ACTIVE', 'EXPIRED'} and (mode == 'WRITE' or owner['mode'] == 'EXCLUSIVE_WRITE'):
                    raise ContractError('NATIVE_TOOL_DATA_LEASE_CUSTODY_HELD')
            for call in self.truth.query(_CALL, data_ref=self.scope['data_ref']):
                if call['state'] in {'IN_FLIGHT', 'UNKNOWN'} and (mode == 'WRITE' or call['access_mode'] == 'WRITE'):
                    raise ContractError('NATIVE_TOOL_OTHER_CALL_CUSTODY_HELD')
            row = self._persist(_CALL, dict(self._base, kind='CALL', call_id=call_id, request_id=request_id,
                tool=tool, access_mode=self.handlers[tool].mode, arguments_sha256=_hash(arguments), state='IN_FLIGHT', started_at=int(time.time())))
        try:
            result = json.loads(json.dumps(self.handlers[tool].execute(deepcopy(arguments)), allow_nan=False))
            _validate_observation(self.scope, result)
            with self._mutex, ledger_lock(self.truth, busy='NATIVE_TOOL_LEDGER_BUSY'):
                if not self.active:
                    raise ContractError('NATIVE_TOOL_CONTROLLER_CLOSED_DURING_EFFECT')
                self._validate_actor()
                row = self._persist(_CALL, dict(row, state='RETURNED', result=result, result_sha256=_hash(result), finished_at=int(time.time())))
            return dict(result=row['result'], call_id=call_id)
        except BaseException as exc:
            with self._mutex, ledger_lock(self.truth, busy='NATIVE_TOOL_LEDGER_BUSY'):
                observed = _signed(self.authority, self.service._one(_CALL, call_id=row['call_id']))
                if observed['state'] != 'RETURNED':
                    self._persist(_CALL, dict(row, state='UNKNOWN', error_type=type(exc).__name__, finished_at=int(time.time())))
            raise

    def verify_observed(self, calls):
        records = self.truth.query(_CALL, gate_id=self.gate_id)
        for row in records:
            _signed(self.authority, row)
        if (not calls or not records or any(row['state'] != 'RETURNED' for row in records)
                or Counter(c['tool_name'] for c in calls) != Counter(r['tool'] for r in records)):
            raise ContractError('NATIVE_TOOL_ACTUAL_CALLS_DO_NOT_MATCH_DSH_OBSERVATION')
        return records

    def verify_output(self, output):
        records = self.truth.query(_CALL, gate_id=self.gate_id)
        _verify_output(self.scope, records, output)

    def complete(self, invocation, output):
        with self._mutex, ledger_lock(self.truth, busy='NATIVE_TOOL_LEDGER_BUSY'):
            if not self.active or self.service._one(_GATE, gate_id=self.gate_id)['state'] != 'OPEN':
                raise ContractError('NATIVE_TOOL_HANDOFF_LIVE_CONTROLLER_REQUIRED')
            self._validate_actor()
            records = self.verify_observed(invocation.tool_calls)
            self.verify_output(output)
            current = self.service._one(_GATE, gate_id=self.gate_id)
            self._persist(_GATE, dict(current, state='COMPLETED', call_refs=[r['call_id'] for r in records],
                observed_calls_sha256=_hash(invocation.tool_calls), output_sha256=_hash(output),
                dsh_session_id=invocation.dsh_session_id, finished_at=int(time.time())))

    def close(self):
        with self._mutex:
            self.active = False
            self.token = ''
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server, self.thread = None, None
        with ledger_lock(self.truth, busy='NATIVE_TOOL_LEDGER_BUSY'):
            current = self.service._one(_GATE, gate_id=self.gate_id)
            if current['state'] == 'OPEN':
                self._persist(_GATE, dict(current, state='CLOSED', finished_at=int(time.time())))


install_rc72_native_tool_gate_overlay()
