"""R1-owned logical Primary bindings; no model-callable creation or lease grant.

The trusted launcher provisions actual directory-scoped OpenCode Sessions. Tools
only read this authority. The operational pointer is a disposable projection.
"""
from __future__ import annotations
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
import json
from urllib.parse import urlsplit
from pathlib import Path
import uuid

from .durable_core import (ActorRef, CommandEnvelope, ExtensionManifest, MigrationStep,
    PendingEvent, RootDefinition, RuntimeError, SubjectRef, canonical_json, canonical_sha256)
from .dispatch_receipts import runtime_coordination
from .general_work.execution_contract import require, stamp

EXTENSION_ID = 'primary_interaction_sessions'
KIND = 'PRIMARY_INTERACTION'
PREFIX = 'primary-interaction:v1:'
OWNER = ActorRef('SYSTEM', 'primary-session-owner')
CREATE = 'CREATE_PRIMARY_INTERACTION'
RECORD = 'RECORD_PRIMARY_BINDING'
CREATED = 'primary.interaction_created.v1'
RECORDED = 'primary.binding_recorded.v1'
POLICY = 'primary-session.v4.1'


def primary_coordination(runtime):
    # A mutex namespace, not a second database or durable truth. Primary control
    # intake must not wait behind a long G4 physical execution lock.
    return runtime_coordination(Path(str(runtime.db_path) + '.primary-authority.db'))


def now(): return datetime.now(timezone.utc).isoformat()
def subject_for(root): return SubjectRef(KIND, PREFIX + canonical_sha256(str(Path(root).resolve())))
def logical_id(subject): return 'logical-director:' + canonical_sha256(subject.subject_id)
def provision_id(subject, epoch): return 'primary-provision:' + canonical_sha256([subject.subject_id, epoch])


def exact(value, keys):
    require(isinstance(value, dict) and set(value) == set(keys.split()), 'PRIMARY_BINDING_SCHEMA_INVALID')


@dataclass(frozen=True)
class PrimaryState:
    subject_id: str
    workspace_root: str | None = None
    logical_agent_id: str | None = None
    epoch: int = 0
    bindings: dict = field(default_factory=dict)

    def to_dict(self): return {'subject_id':self.subject_id,'workspace_root':self.workspace_root,
        'logical_agent_id':self.logical_agent_id,'epoch':self.epoch,'bindings':self.bindings}


def transition(state, command_type, payload):
    require(isinstance(payload, dict) and len(canonical_json(payload).encode()) <= 16384, 'PRIMARY_EVENT_BUDGET')
    subject = SubjectRef(KIND, state.subject_id)
    require(payload.get('subject') == subject.to_dict(), 'PRIMARY_SUBJECT_MISMATCH')
    if command_type == CREATE:
        exact(payload, 'subject root_version creation_command workspace_root logical_agent_id')
        require(state.workspace_root is None and type(payload['root_version']) is int and payload['root_version'] == 1 and payload['creation_command'] == CREATE, 'PRIMARY_ROOT_CREATION_INVALID')
        require(isinstance(payload['workspace_root'], str) and len(payload['workspace_root'].encode()) <= 4096, 'PRIMARY_WORKSPACE_INVALID')
        # Replay must not resolve paths against the replay machine's filesystem.
        require(state.subject_id == PREFIX + canonical_sha256(payload['workspace_root']), 'PRIMARY_WORKSPACE_IDENTITY_INVALID')
        require(payload['logical_agent_id'] == logical_id(subject), 'PRIMARY_LOGICAL_IDENTITY_INVALID')
        return replace(state, workspace_root=payload['workspace_root'], logical_agent_id=payload['logical_agent_id'])
    exact(payload, 'subject operation data');op=payload['operation'];data=payload['data']
    require(state.workspace_root is not None and command_type == RECORD, 'PRIMARY_ROOT_REQUIRED')
    bindings={k:dict(v) for k,v in state.bindings.items()};current=bindings.get(str(state.epoch))
    if op == 'REQUEST':
        exact(data, 'epoch provision_id requested_at policy host_realm')
        require(isinstance(data['host_realm'], str) and len(data['host_realm']) == 64 and all(c in '0123456789abcdef' for c in data['host_realm']), 'PRIMARY_HOST_REALM_INVALID')
        require(type(data['epoch']) is int and data['epoch'] == state.epoch+1, 'PRIMARY_EPOCH_INVALID')
        require(current is None or current['state']=='FENCED', 'PRIMARY_PREDECESSOR_MUST_BE_FENCED')
        require(data['provision_id']==provision_id(subject,data['epoch']) and data['policy']==POLICY, 'PRIMARY_PROVISION_IDENTITY_INVALID')
        stamp(data['requested_at'])
        bindings[str(data['epoch'])]={**data,'state':'REQUESTED','session_id':None}
        return replace(state,epoch=data['epoch'],bindings=bindings)
    require(current is not None and type(data.get('epoch')) is int and data.get('epoch') == state.epoch, 'PRIMARY_STALE_EPOCH')
    if op == 'BIND':
        exact(data, 'epoch provision_id session_id directory_digest observed_at expires_at host_realm')
        require(data['host_realm'] == current['host_realm'], 'PRIMARY_HOST_REALM_MISMATCH')
        require(current['state']=='REQUESTED' and data['provision_id']==current['provision_id'], 'PRIMARY_BINDING_NOT_REQUESTED')
        require(isinstance(data['session_id'],str) and 0<len(data['session_id'])<=256 and all((v['session_id'], v['host_realm']) != (data['session_id'], data['host_realm']) for v in bindings.values()), 'PRIMARY_SESSION_REUSE_FORBIDDEN')
        require(data['directory_digest']==canonical_sha256(state.workspace_root), 'PRIMARY_HOST_DIRECTORY_MISMATCH')
        elapsed=(stamp(data['expires_at'])-stamp(data['observed_at'])).total_seconds()
        require(0<elapsed<=8*3600 and stamp(data['observed_at'])>=stamp(current['requested_at']), 'PRIMARY_LEASE_INVALID')
        current.update(**data,state='BOUND')
    elif op == 'FENCE':
        exact(data, 'epoch session_id reason observed_at')
        require(current['state'] in {'BOUND', 'REQUESTED'} and data['session_id']==current['session_id'], 'PRIMARY_BINDING_NOT_CURRENT')
        require(isinstance(data['reason'],str) and 0<len(data['reason'])<=256, 'PRIMARY_FENCE_REASON_INVALID')
        require(stamp(data['observed_at']) >= stamp(current.get('observed_at', current['requested_at'])), 'PRIMARY_FENCE_TIME_INVALID');current.update(state='FENCED',reason=data['reason'],fenced_at=data['observed_at'])
    else: raise RuntimeError('PRIMARY_OPERATION_INVALID','unknown binding transition')
    return replace(state,bindings=bindings)


class StateContribution:
    def initial_state(self,sid):return PrimaryState(sid)
    def encode(self,state):return state.to_dict()
    def decode(self,value):return PrimaryState(**value)
    def hash(self,state):return canonical_sha256(state.to_dict())
    def root_exists(self,state,subject):return state.subject_id==subject.subject_id and state.workspace_root is not None


class CommandContribution:
    def handle(self,command,composed):
        require(command.actor==OWNER and command.session_id is None,'PRIMARY_TRUSTED_OWNER_REQUIRED')
        require(len(canonical_json(command.payload).encode())<=16384,'PRIMARY_EVENT_BUDGET')
        transition(composed.extension_state(EXTENSION_ID),command.type,dict(command.payload))
        return [PendingEvent(CREATED if command.type==CREATE else RECORDED,KIND,command.mission_id,dict(command.payload))]


class ReducerContribution:
    def reduce(self,state,event,core_state):
        require(event.initiator_type==OWNER.type and event.initiator_id==OWNER.id and event.session_id is None,'PRIMARY_TRUSTED_OWNER_REQUIRED')
        require(event.entity_type==KIND and event.entity_id==state.subject_id and event.mission_id==state.subject_id,'PRIMARY_EVENT_IDENTITY_INVALID')
        require(event.event_type in {CREATED,RECORDED},'PRIMARY_EVENT_UNSUPPORTED')
        return transition(state,CREATE if event.event_type==CREATED else RECORD,dict(event.payload))


SQL='CREATE TABLE primary_interaction_projection(subject_id TEXT PRIMARY KEY, state_json TEXT NOT NULL, projection_seq INTEGER NOT NULL)'
def migrate(conn):conn.execute(SQL)
class MigrationContribution:
    extension_id=EXTENSION_ID
    migrations=(MigrationStep(1,canonical_sha256(SQL),migrate),)
class ProjectionContribution:
    projection_tables=frozenset({'primary_interaction_projection'})
    def clear(self,conn,sid=None):conn.execute('DELETE FROM primary_interaction_projection'+(' WHERE subject_id=?' if sid else ''),(sid,) if sid else ())
    def apply(self,conn,composed):
        state=composed.extension_state(EXTENSION_ID);self.clear(conn,state.subject_id)
        conn.execute('INSERT INTO primary_interaction_projection VALUES(?,?,?)',(state.subject_id,canonical_json(state.to_dict()),composed.seq))
    def read(self,conn,sid):
        row=conn.execute('SELECT state_json FROM primary_interaction_projection WHERE subject_id=?',(sid,)).fetchone()
        return PrimaryState(**json.loads(row[0])) if row else PrimaryState(sid)
    def projection_seq(self,conn,sid):
        row=conn.execute('SELECT projection_seq FROM primary_interaction_projection WHERE subject_id=?',(sid,)).fetchone();return row[0] if row else None
    def verify(self,replayed,projected):
        a=canonical_sha256(replayed.to_dict());b=canonical_sha256(projected.to_dict()) if projected else None
        return {'ok':a==b,'replay_hash':a,'projection_hash':b}


def primary_session_extension():
    commands=frozenset({CREATE,RECORD});events=frozenset({CREATED,RECORDED})
    return ExtensionManifest(EXTENSION_ID,'1.0.0',commands,events,StateContribution(),CommandContribution(),ReducerContribution(),ProjectionContribution(),MigrationContribution(),
        subject_kinds=frozenset({KIND}),roots=(RootDefinition(KIND,PREFIX,1,CREATE,CREATED,KIND,commands,events),))


class PrimarySessionOwner:
    def __init__(self,runtime,workspace_root,provider=None):
        self.runtime=runtime;self.root=Path(workspace_root).resolve();self.subject=subject_for(self.root);self.provider=provider
    def state(self):
        if not self.runtime.get_head_seq(self.subject.subject_id):return PrimaryState(self.subject.subject_id)
        return self.runtime.get_subject_state(self.subject).root_state
    def _execute(self,command,payload):
        result=self.runtime.execute(CommandEnvelope('primary:'+uuid.uuid4().hex,command,self.subject.subject_id,
            self.runtime.get_head_seq(self.subject.subject_id),OWNER,{'subject':self.subject.to_dict(),**payload}))
        if not result.ok:raise result.error
        return self.state()
    def record(self,operation,data):return self._execute(RECORD,{'operation':operation,'data':data})
    def fence(self,reason):
        with primary_coordination(self.runtime):
            state=self.state();binding=state.bindings.get(str(state.epoch))
            if binding and binding['state'] in {'BOUND', 'REQUESTED'}:self.record('FENCE',{'epoch':state.epoch,'session_id':binding['session_id'],'reason':reason,'observed_at':now()})
    def host_realm(self):
        endpoint = getattr(self.provider, 'base_url', None)
        require(isinstance(endpoint, str) and bool(endpoint), 'PRIMARY_HOST_REALM_REQUIRED')
        url = urlsplit(endpoint)
        require(url.scheme in {'http', 'https'} and url.hostname and not url.username
            and not url.password and not url.query and not url.fragment, 'PRIMARY_HOST_REALM_INVALID')
        # Ports are part of authority. A launcher with a new endpoint conservatively
        # fences its predecessor; credentials never enter the R1 payload.
        return canonical_sha256({'origin': endpoint.rstrip('/'), 'workspace': str(self.root)})
    def current(self,session_id=None):
        state=self.state();binding=state.bindings.get(str(state.epoch))
        require(binding is not None and binding['state']=='BOUND','PRIMARY_CURRENT_BINDING_REQUIRED')
        require(session_id is None or binding['session_id']==session_id,'STALE_CALLER')
        require(binding['host_realm'] == self.host_realm(), 'PRIMARY_HOST_REALM_MISMATCH')
        require(stamp(now())<stamp(binding['expires_at']),'PRIMARY_LEASE_EXPIRED')
        return {'subject':self.subject.to_dict(),'logical_agent_id':state.logical_agent_id,**binding}
    def ensure_current(self):
        """Trusted launcher only. Never reads the old operational session pointer."""
        require(self.provider is not None,'PRIMARY_HOST_PROVIDER_REQUIRED')
        with primary_coordination(self.runtime):
            self.runtime.assert_writable_compatible();state=self.state()
            if state.workspace_root is None:
                state=self._execute(CREATE,{'root_version':1,'creation_command':CREATE,'workspace_root':str(self.root),'logical_agent_id':logical_id(self.subject)})
            binding=state.bindings.get(str(state.epoch))
            sessions=self.provider.list_sessions()
            if binding and binding['state']=='BOUND':
                matches=[x for x in sessions if x.session_id==binding['session_id'] and Path(x.directory).resolve()==self.root]
                if len(matches)==1 and binding['host_realm']==self.host_realm() and stamp(now())<stamp(binding['expires_at']):return self.current()
                self.fence('LEASE_EXPIRED_OR_HOST_BINDING_MISSING');state=self.state();binding=state.bindings.get(str(state.epoch))
            if binding and binding['state']=='REQUESTED' and binding['host_realm'] != self.host_realm():
                self.fence('PENDING_HOST_REALM_CHANGED');state=self.state();binding=state.bindings.get(str(state.epoch))
            if binding is None or binding['state']=='FENCED':
                epoch=state.epoch+1;state=self.record('REQUEST',{'epoch':epoch,'provision_id':provision_id(self.subject,epoch),'requested_at':now(),'policy':POLICY,'host_realm':self.host_realm()})
                binding=state.bindings[str(epoch)]
            require(binding['host_realm'] == self.host_realm(), 'PRIMARY_PENDING_HOST_REALM_MISMATCH')
            title='AITest Director '+binding['provision_id']
            matches=[x for x in sessions if x.title==title]
            require(len(matches)<=1,'PRIMARY_HOST_PROVISION_AMBIGUOUS')
            actual=matches[0] if matches else self.provider.create_session(title=title)
            require(Path(actual.directory).resolve()==self.root,'PRIMARY_HOST_DIRECTORY_MISMATCH')
            observed=now();self.record('BIND',{'epoch':state.epoch,'provision_id':binding['provision_id'],'session_id':actual.session_id,
                'host_realm':self.host_realm(),'directory_digest':canonical_sha256(str(self.root)),'observed_at':observed,'expires_at':(stamp(observed)+timedelta(hours=8)).isoformat()})
            return self.current()
