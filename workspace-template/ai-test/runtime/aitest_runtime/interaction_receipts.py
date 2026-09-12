"""Same-R1 receipt owner for F53 interaction operations; never a scheduled job.

Commands and events use the existing transaction/CAS/idempotency infrastructure.
This module owns no secondary database and creates no Mission, Task or Session.
Its internal API is not a model-callable authorization or capability issuer.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
import re
import uuid
from typing import Any, Mapping

from .durable_core import (ActorRef, CommandEnvelope, ExtensionManifest, MigrationStep,
    PendingEvent, RootDefinition, RuntimeError, SubjectRef, canonical_json, canonical_sha256)
from .durable_core.schema import connect
from .interaction_admission import ActualHostUserTurn, SubjectCandidate
from .r2_1.contracts import validate_secret_boundary
from .r2_2.contracts import normalize_scope

EXTENSION_ID = 'interaction_operation_receipts'
ROOT_KIND = 'INTERACTION_OPERATION'
PREFIX = 'interaction-operation:v1:'
GENERAL_INTENT_EVENT = 'interaction.general_intent_recorded.v1'
COMMAND_EVENT = {
    'CLAIM_INTERACTION_OPERATION': 'interaction.operation_claimed.v1',
    'BIND_INTERACTION_OPERATION': 'interaction.operation_bound.v1',
    'COMPLETE_INTERACTION_OPERATION': 'interaction.operation_completed.v1',
    'RECONCILE_INTERACTION_OPERATION': 'interaction.operation_reconcile_required.v1',
}
PROVENANCE_FIELDS = {'schema_version','host_session_id','host_message_id','host_tool_message_id',
                     'parent_message_id','source_ref','source_digest','observed_at','valid_until'}
IMMUTABLE_FIELDS = frozenset({'operation_id','request_digest','host_turn_ref','intent','action',
                              'effect','proposal','resolved_scope','subject'})


def stream_id(operation_id: str) -> str:
    if not isinstance(operation_id, str) or not re.fullmatch(r'interaction-op-[0-9a-f]{64}', operation_id):
        raise RuntimeError('INTERACTION_OPERATION_ID_INVALID', 'runtime operation identity is required')
    return PREFIX + canonical_sha256(operation_id)


def _require(condition: bool, code: str) -> None:
    if not condition: raise RuntimeError(code, code)


def _host(value: Any) -> dict[str, Any]:
    from datetime import datetime
    _require(isinstance(value, Mapping) and set(value) == PROVENANCE_FIELDS, 'INTERACTION_HOST_PROVENANCE_INVALID')
    result = dict(value)
    _require(result['schema_version'] == 1, 'INTERACTION_HOST_PROVENANCE_INVALID')
    _require(all(isinstance(result[k], str) and result[k] for k in PROVENANCE_FIELDS - {'schema_version','parent_message_id'}), 'INTERACTION_HOST_PROVENANCE_INVALID')
    _require(result['parent_message_id'] is None or isinstance(result['parent_message_id'], str), 'INTERACTION_HOST_PROVENANCE_INVALID')
    _require(bool(re.fullmatch('[0-9a-f]{64}', result['source_digest'])), 'INTERACTION_HOST_DIGEST_INVALID')
    from urllib.parse import quote
    expected = 'opencode://session/' + quote(result['host_session_id'], safe='') + '/message/' + quote(result['host_message_id'], safe='')
    _require(result['source_ref'] == expected, 'INTERACTION_HOST_REFERENCE_MISMATCH')
    try:
        start, end = (datetime.fromisoformat(result[k].replace('Z','+00:00')) for k in ('observed_at','valid_until'))
        valid = start.tzinfo is not None and end.tzinfo is not None and 0 < (end-start).total_seconds() <= 900
    except (ValueError, TypeError): valid = False
    _require(valid, 'INTERACTION_HOST_EXPIRY_INVALID')
    return result


@dataclass(frozen=True)
class ReceiptState:
    subject_id: str
    receipt: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self): return {'subject_id': self.subject_id, 'receipt': dict(self.receipt)}


class StateContribution:
    def initial_state(self, subject_id): return ReceiptState(subject_id)
    def root_exists(self, state, subject): return isinstance(state, ReceiptState) and state.subject_id == subject.subject_id and bool(state.receipt)
    def encode(self, state): return state.to_dict()
    def decode(self, value): return ReceiptState(value['subject_id'], value['receipt'])
    def hash(self, state): return canonical_sha256(self.encode(state))


def _transition(state: ReceiptState, command_type: str, payload: Mapping[str, Any]) -> ReceiptState:
    _require(payload.get('subject') == {'subject_kind': ROOT_KIND, 'subject_id': state.subject_id}, 'INTERACTION_RECEIPT_ROOT_MISMATCH')
    if command_type == 'CLAIM_INTERACTION_OPERATION':
        _require(not state.receipt, 'INTERACTION_OPERATION_ALREADY_CLAIMED')
        _require(set(payload) == {'subject','root_version','creation_command','operation'}, 'INTERACTION_CLAIM_SCHEMA_INVALID')
        op = payload['operation']
        _require(isinstance(op, Mapping) and set(op) in (IMMUTABLE_FIELDS, IMMUTABLE_FIELDS | {'operation_text'}), 'INTERACTION_OPERATION_SCHEMA_INVALID')
        _require(isinstance(op['proposal'], Mapping) and (op['resolved_scope'] is None or isinstance(op['resolved_scope'], Mapping)), 'INTERACTION_OPERATION_SCHEMA_INVALID')
        _require(stream_id(op['operation_id']) == state.subject_id, 'INTERACTION_OPERATION_ROOT_MISMATCH')
        if 'operation_text' in op:
            _require(op['intent'] in {'GENERAL_WORK','AITEST_DIAGNOSIS'} and isinstance(op['operation_text'], str)
                     and 0 < len(op['operation_text'].encode()) <= 8192, 'INTERACTION_OPERATION_TEXT_INVALID')
        host = _host(op['host_turn_ref'])
        _require(op['request_digest'] == canonical_sha256({'host_content': host['source_digest'], 'proposal': op['proposal']}), 'INTERACTION_REQUEST_DIGEST_MISMATCH')
        from .interaction_admission import Intent, ACTIONS
        try: intent = Intent(op['intent']); effect = ACTIONS[intent][op['action']]
        except (ValueError, KeyError, TypeError): raise RuntimeError('INTERACTION_OPERATION_KIND_INVALID','unsupported intent/action') from None
        _require(op['effect'] == effect and op['proposal'].get('intent') == op['intent'] and op['proposal'].get('action') == op['action'], 'INTERACTION_EFFECT_MISMATCH')
        expected_operation = 'interaction-op-' + canonical_sha256({'session': host['host_session_id'], 'message': host['host_message_id'], 'start': op['proposal'].get('start'), 'end': op['proposal'].get('end')})
        _require(op['operation_id'] == expected_operation, 'INTERACTION_HOST_SLOT_MISMATCH')
        target = op['subject']
        _require(target is None or isinstance(target, Mapping) and set(target) == {'subject_kind','subject_id'}, 'INTERACTION_TARGET_INVALID')
        _require(payload['root_version'] == 1 and payload['creation_command'] == command_type, 'INTERACTION_ROOT_VERSION_INVALID')
        validate_secret_boundary(op)
        return replace(state, receipt={**dict(op), 'state':'CLAIMED','bound_subject':None,'result':None,'reason':None})
    _require(bool(state.receipt), 'INTERACTION_OPERATION_NOT_FOUND')
    row = dict(state.receipt)
    if command_type == 'BIND_INTERACTION_OPERATION':
        _require(set(payload) == {'subject','target'}, 'INTERACTION_BIND_SCHEMA_INVALID')
        _require(row['state'] == 'CLAIMED', 'INTERACTION_BIND_STATE_INVALID')
        target = payload['target']
        _require(isinstance(target, Mapping) and set(target) == {'subject_kind','subject_id'}, 'INTERACTION_TARGET_INVALID')
        allowed_kind = {'GENERAL_WORK':'GENERAL_WORK','AITEST_DIAGNOSIS':'RUNTIME_DIAGNOSIS'}.get(row['intent'], 'MISSION')
        _require(target['subject_kind'] == allowed_kind and target['subject_id'] != state.subject_id, 'INTERACTION_CROSS_ROOT_KIND_MISMATCH')
        _require(row['subject'] is None or row['subject'] == target, 'INTERACTION_CROSS_ROOT_TARGET_MISMATCH')
        row.update(state='BOUND', bound_subject=dict(target))
    elif command_type == 'COMPLETE_INTERACTION_OPERATION':
        _require(set(payload) == {'subject','result'}, 'INTERACTION_COMPLETE_SCHEMA_INVALID')
        _require(row['state'] == 'BOUND', 'INTERACTION_COMPLETE_STATE_INVALID')
        result = payload['result']
        _require(isinstance(result, Mapping) and len(canonical_json(result).encode()) <= 65536, 'INTERACTION_RESULT_BUDGET_INVALID')
        validate_secret_boundary(result)
        row.update(state='COMPLETED', result=dict(result))
    elif command_type == 'RECONCILE_INTERACTION_OPERATION':
        _require(set(payload) == {'subject','reason'}, 'INTERACTION_RECONCILE_SCHEMA_INVALID')
        _require(row['state'] in {'CLAIMED','BOUND'}, 'INTERACTION_RECONCILE_STATE_INVALID')
        _require(isinstance(payload['reason'], str) and 0 < len(payload['reason']) <= 256, 'INTERACTION_RECONCILE_REASON_INVALID')
        row.update(state='RECONCILE_REQUIRED', reason=payload['reason'])
    else: raise RuntimeError('INTERACTION_COMMAND_UNKNOWN', command_type)
    return replace(state, receipt=row)


class CommandContribution:
    def handle(self, command, composed):
        _require(command.actor == ActorRef('SYSTEM','interaction-admission'), 'INTERACTION_TRUSTED_OWNER_REQUIRED')
        _require(command.session_id is None, 'INTERACTION_RECEIPT_HAS_NO_EXECUTION_SESSION')
        state = composed.extension_state(EXTENSION_ID)
        _transition(state, command.type, command.payload)
        if command.type == 'CLAIM_INTERACTION_OPERATION' and 'operation_text' in command.payload['operation']:
            # Both events are committed by the existing R1 command transaction.
            # A distinct event type lets existing compatibility checks reject a
            # composition that cannot replay durable General intent.
            operation = dict(command.payload['operation']); text = operation.pop('operation_text')
            base = {**command.payload, 'operation': operation}
            intent = {'subject': command.payload['subject'], 'operation_text': text,
                      'request_digest': operation['request_digest']}
            return [PendingEvent(COMMAND_EVENT[command.type], ROOT_KIND, command.mission_id, base),
                    PendingEvent(GENERAL_INTENT_EVENT, ROOT_KIND, command.mission_id, intent)]
        return [PendingEvent(COMMAND_EVENT[command.type], ROOT_KIND, command.mission_id, dict(command.payload))]


class ReducerContribution:
    def reduce(self, state, event, core_state):
        _require(event.mission_id == state.subject_id and event.entity_id == state.subject_id and event.entity_type == ROOT_KIND, 'INTERACTION_EVENT_IDENTITY_INVALID')
        _require(event.session_id is None and event.initiator_type == 'SYSTEM' and event.initiator_id == 'interaction-admission', 'INTERACTION_EVENT_OWNER_INVALID')
        if event.event_type == GENERAL_INTENT_EVENT:
            data = event.payload; row = dict(state.receipt)
            _require(set(data) == {'subject','operation_text','request_digest'} and data['subject'] == {'subject_kind':ROOT_KIND,'subject_id':state.subject_id}, 'INTERACTION_GENERAL_INTENT_INVALID')
            _require(row.get('state') == 'CLAIMED' and row.get('intent') in {'GENERAL_WORK','AITEST_DIAGNOSIS'}
                     and 'operation_text' not in row and data['request_digest'] == row['request_digest'], 'INTERACTION_GENERAL_INTENT_INVALID')
            _require(isinstance(data['operation_text'], str) and 0 < len(data['operation_text'].encode()) <= 8192, 'INTERACTION_OPERATION_TEXT_INVALID')
            validate_secret_boundary(data)
            return replace(state, receipt={**row, 'operation_text':data['operation_text']})
        command_type = next((k for k,v in COMMAND_EVENT.items() if v == event.event_type), None)
        _require(command_type is not None, 'INTERACTION_EVENT_UNKNOWN')
        return _transition(state, command_type, event.payload)


SQL = ('CREATE TABLE interaction_operation_projection(subject_id TEXT PRIMARY KEY, state_json TEXT NOT NULL, projection_seq INTEGER NOT NULL)',)

def _migrate(conn):
    for sql in SQL: conn.execute(sql)


class MigrationContribution:
    extension_id = EXTENSION_ID
    migrations = (MigrationStep(1, canonical_sha256(list(SQL)), _migrate),)


class ProjectionContribution:
    projection_tables = frozenset({'interaction_operation_projection'})
    def clear(self, conn, mission_id=None):
        conn.execute('DELETE FROM interaction_operation_projection' + (' WHERE subject_id=?' if mission_id else ''), (mission_id,) if mission_id else ())
    def apply(self, conn, composed):
        state = composed.extension_state(EXTENSION_ID)
        self.clear(conn, composed.mission_id)
        if state.receipt:
            conn.execute('INSERT INTO interaction_operation_projection VALUES(?,?,?)', (state.subject_id, canonical_json(state.to_dict()), composed.seq))
    def read(self, conn, mission_id):
        row = conn.execute('SELECT state_json FROM interaction_operation_projection WHERE subject_id=?',(mission_id,)).fetchone()
        return StateContribution().decode(json.loads(row['state_json'])) if row else ReceiptState(mission_id)
    def projection_seq(self, conn, mission_id):
        row = conn.execute('SELECT projection_seq FROM interaction_operation_projection WHERE subject_id=?',(mission_id,)).fetchone()
        return row['projection_seq'] if row else None
    def verify(self, replayed_state, projected_state):
        a = StateContribution().hash(replayed_state); b = StateContribution().hash(projected_state) if projected_state else None
        return {'ok':a==b,'replay_hash':a,'projection_hash':b}


def interaction_receipt_extension() -> ExtensionManifest:
    commands, events = frozenset(COMMAND_EVENT), frozenset(COMMAND_EVENT.values()) | {GENERAL_INTENT_EVENT}
    return ExtensionManifest(EXTENSION_ID, '1.1.0', commands, events,
        StateContribution(), CommandContribution(), ReducerContribution(), ProjectionContribution(), MigrationContribution(),
        subject_kinds=frozenset({ROOT_KIND}), roots=(RootDefinition(ROOT_KIND,PREFIX,1,'CLAIM_INTERACTION_OPERATION',COMMAND_EVENT['CLAIM_INTERACTION_OPERATION'],ROOT_KIND,commands,events),))


class R1InteractionOwner:
    def __init__(self, runtime):
        runtime.extension_registry.manifest(EXTENSION_ID)
        runtime.assert_writable_compatible()
        self.runtime = runtime

    def receipt(self, operation_id):
        key = stream_id(operation_id)
        if not self.runtime.get_head_seq(key): return None
        state = self.runtime.get_subject_state(SubjectRef(ROOT_KIND,key)).root_state
        return dict(state.receipt)

    def _execute(self, kind, operation_id, payload, expected_seq, *, idempotency=None):
        key = stream_id(operation_id)
        command = CommandEnvelope('interaction-command:' + uuid.uuid4().hex, kind, key, expected_seq,
            ActorRef('SYSTEM','interaction-admission'), {'subject':{'subject_kind':ROOT_KIND,'subject_id':key},**payload},
            idempotency_key=idempotency, correlation_id=operation_id)
        result = self.runtime.execute(command)
        if not result.ok: raise result.error or RuntimeError('INTERACTION_RECEIPT_REJECTED','receipt command rejected')
        return result

    def claim(self, operation: Mapping[str, Any]) -> dict[str, Any]:
        fields = IMMUTABLE_FIELDS | ({'operation_text'} if operation.get('intent') in {'GENERAL_WORK','AITEST_DIAGNOSIS'} and 'operation_text' in operation else set())
        immutable = {k:operation[k] for k in fields}
        existing = self.receipt(operation['operation_id'])
        if existing:
            _require({k:existing[k] for k in IMMUTABLE_FIELDS | ({'operation_text'} if 'operation_text' in existing else set())} == immutable, 'INTERACTION_REPLAY_CONFLICT')
            return {'fresh':False, **existing}
        result = self._execute('CLAIM_INTERACTION_OPERATION', operation['operation_id'],
            {'root_version':1,'creation_command':'CLAIM_INTERACTION_OPERATION','operation':immutable},0,
            idempotency='interaction-claim:' + operation['operation_id'])
        return {'fresh':result.outcome == 'APPLIED', **self.receipt(operation['operation_id'])}

    def bind(self, operation_id, subject):
        current = self.receipt(operation_id)
        _require(current is not None, 'INTERACTION_OPERATION_NOT_FOUND')
        ref = SubjectRef(subject['subject_kind'],subject['subject_id'])
        target = self.runtime.get_subject_state(ref) # actual immutable root owner, not model kind
        if ref.subject_kind == 'MISSION':
            core = target.root_state
            goal = core.goal(core.mission.active_goal_id) if core.mission else None
            _require(goal is not None, 'INTERACTION_TARGET_GOAL_MISSING')
            _require(canonical_sha256(normalize_scope(goal.definition.get('scope'))) == canonical_sha256(normalize_scope(current['resolved_scope'])), 'INTERACTION_CROSS_ROOT_SCOPE_MISMATCH')
        elif ref.subject_kind in {'GENERAL_WORK','RUNTIME_DIAGNOSIS'}:
            job = target.root_state
            _require(job.operation_id == current['operation_id'], 'INTERACTION_CROSS_ROOT_OPERATION_MISMATCH')
            _require(dict(job.host_turn_ref) == current['host_turn_ref'], 'INTERACTION_CROSS_ROOT_HOST_MISMATCH')
            purpose = current['proposal'].get('arguments',{}).get('purpose')
            _require(purpose is None or job.intent == purpose, 'INTERACTION_CROSS_ROOT_PURPOSE_MISMATCH')
        self._execute('BIND_INTERACTION_OPERATION', operation_id, {'target':ref.to_dict()}, self.runtime.get_head_seq(stream_id(operation_id)))

    def complete(self, operation_id, result):
        self._execute('COMPLETE_INTERACTION_OPERATION',operation_id,{'result':dict(result)},self.runtime.get_head_seq(stream_id(operation_id)))

    def uncertain(self, operation_id, reason):
        self._execute('RECONCILE_INTERACTION_OPERATION',operation_id,{'reason':reason},self.runtime.get_head_seq(stream_id(operation_id)))

    def candidates(self, turn: ActualHostUserTurn):
        # Enumerate canonical creation events then replay; never treat a mutable
        # projection row as scope or ownership authority. No alternate DB opens.
        conn = connect(self.runtime.db_path)
        try:
            rows = conn.execute("SELECT mission_id FROM events WHERE seq=1 AND event_type='mission.created' ORDER BY mission_id").fetchall()
            receipts = conn.execute("SELECT mission_id FROM events WHERE seq=1 AND event_type='interaction.operation_claimed.v1' ORDER BY mission_id").fetchall()
        finally: conn.close()
        _require(len(rows) <= 256 and len(receipts) <= 4096, 'INTERACTION_CONTEXT_QUERY_BUDGET_EXCEEDED')
        linked, unresolved = set(), set()
        for row in receipts:
            receipt = self.runtime.get_subject_state(SubjectRef(ROOT_KIND,row['mission_id'])).root_state.receipt
            target = receipt['bound_subject'] or receipt['subject']
            if not target and receipt['intent'] == 'TEST_MISSION_START':
                # R2's deterministic ID also exposes a crash after Mission create
                # but before the receipt's bind command; do not wake it blindly.
                target = {'subject_kind':'MISSION','subject_id':'r2.2:mission:' + receipt['operation_id']}
            if target and target['subject_kind'] == 'MISSION':
                if receipt['host_turn_ref']['host_session_id'] == turn.host_session_id: linked.add(target['subject_id'])
                if receipt['state'] != 'COMPLETED': unresolved.add(target['subject_id'])
        result = []
        for row in rows:
            state = self.runtime.get_subject_state(SubjectRef('MISSION',row['mission_id']))
            core = state.root_state
            goal = core.goal(core.mission.active_goal_id) if core.mission else None
            if goal is None: continue
            definition = goal.definition
            scope = definition.get('scope') or {}
            if not any(k != 'mode' and v for k,v in scope.items()): continue
            source = definition.get('intake',{}).get('source_manifest',{}).get('source_ref','')
            from urllib.parse import quote
            contextual = row['mission_id'] in linked or source.startswith('opencode://session/' + quote(turn.host_session_id,safe='') + '/message/')
            blocker = 'PRIOR_INTERACTION_RECONCILIATION_REQUIRED' if row['mission_id'] in unresolved else None
            result.append(SubjectCandidate('MISSION',row['mission_id'],scope,core.mission.status.value,state.seq,contextual,blocker))
        return tuple(result)
