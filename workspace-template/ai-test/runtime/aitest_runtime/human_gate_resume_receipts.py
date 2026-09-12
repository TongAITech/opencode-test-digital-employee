"""Same-R1 owner receipt for exact HumanGate handback and one UI continuation.

This typed non-Mission root owns no scheduler or new execution authority. The
G4 owner joins every request to a real pending Gate, Attempt and browser context.
SENT without a receipt is UNKNOWN; no non-idempotent continuation is replayed.
"""
from __future__ import annotations
from dataclasses import dataclass, field, replace
import json
import uuid
from .durable_core import (ActorRef, CommandEnvelope, ExtensionManifest, MigrationStep,
    PendingEvent, RootDefinition, SubjectRef, canonical_json, canonical_sha256)
from .general_work.execution_contract import require, stamp
from .r2_1.contracts import validate_secret_boundary

EXTENSION_ID='human_gate_resume'
KIND='HUMAN_GATE_RESUME'
PREFIX='human-gate-resume:v1:'
CREATE='CREATE_HUMAN_GATE_RESUME'
CREATED='human_gate_resume.created.v1'
COMMAND='RECORD_HUMAN_GATE_RESUME'
EVENT='human_gate_resume.recorded.v1'
OWNER=ActorRef('SYSTEM','human-gate-resume-owner')

def subject_for(mid,gate):return SubjectRef(KIND,PREFIX+canonical_sha256({'mission_id':mid,'gate_id':gate}))
def exact(value,keys):require(isinstance(value,dict) and set(value)==set(keys.split()),'GATE_RESUME_SCHEMA_INVALID')

@dataclass(frozen=True)
class ResumeState:
    subject_id:str
    intent:dict=field(default_factory=dict)
    phase:str=''
    records:dict=field(default_factory=dict)
    def to_dict(self):return {'subject_id':self.subject_id,'intent':self.intent,'phase':self.phase,'records':self.records}

def creation_transition(state,payload):
    exact(payload,'subject root_version creation_command intent')
    d=payload['intent']
    exact(d,'mission_id gate_id task_id root_attempt_id origin_attempt_id takeover_ref browser_context_ref decision_id completion_mode actor_id request_identity cursor_ref valid_until')
    require(all(isinstance(d[k],str) and 0<len(d[k])<=512 for k in d if k not in {'browser_context_ref','valid_until'}),'GATE_RESUME_INTENT_INVALID')
    require(d['valid_until'] is None or isinstance(d['valid_until'],str),'GATE_RESUME_EXPIRY_INVALID')
    if d['valid_until'] is not None:stamp(d['valid_until'])
    exact(d['browser_context_ref'],'browser_session_id browser_context_id_or_epoch context_binding_digest observed_lease_owner observed_at')
    require(d['completion_mode'] in {'EXPLICIT','AUTO'} and d['browser_context_ref']['observed_lease_owner']=='HUMAN','GATE_RESUME_MODE_INVALID')
    require(not state.intent and payload['root_version']==1 and payload['creation_command']==CREATE
        and payload['subject']==subject_for(d['mission_id'],d['gate_id']).to_dict()
        and payload['subject']==SubjectRef(KIND,state.subject_id).to_dict(),'GATE_RESUME_ROOT_INVALID')
    validate_secret_boundary(payload)
    return replace(state,intent=d,phase='REQUESTED')

PHASES={'REAUTHORIZE':{'REQUESTED','VERIFIED'},'VERIFIED':{'REQUESTED','VERIFIED'},'HAND_BACK_INTENT':{'VERIFIED'},
    'DECIDED':{'HAND_BACK_INTENT'},'RESUME_SAFE':{'DECIDED'},
    'CONTINUATION_SENT':{'RESUME_SAFE'},'COMPLETED':{'RESUME_SAFE','CONTINUATION_SENT'}}
FIELDS={'REAUTHORIZE':'request_identity actor_id decision_id valid_until observed_at','VERIFIED':'verification','HAND_BACK_INTENT':'verification',
    'DECIDED':'decision_id','RESUME_SAFE':'result continuation',
    'CONTINUATION_SENT':'effect_id request_digest','COMPLETED':'result'}

def transition(state,payload):
    exact(payload,'subject operation data')
    require(state.intent and payload['subject']==SubjectRef(KIND,state.subject_id).to_dict(),'GATE_RESUME_ROOT_REQUIRED')
    op=payload['operation'];d=payload['data']
    require(op in PHASES and state.phase in PHASES[op],'GATE_RESUME_PHASE_INVALID')
    exact(d,FIELDS[op]);require(len(canonical_json(d).encode())<=65536,'GATE_RESUME_EVENT_BUDGET')
    validate_secret_boundary(d)
    if op=='REAUTHORIZE':
        require(all(isinstance(v,str) and 0<len(v)<=512 for v in d.values()),'GATE_RESUME_REAUTH_INVALID')
        require(state.intent['valid_until'] is not None and stamp(state.intent['valid_until'])<stamp(d['observed_at'])<stamp(d['valid_until'])
            and d['request_identity']!=state.intent['request_identity'],'GATE_RESUME_REAUTH_INVALID')
        updated={**state.intent,**{k:v for k,v in d.items() if k!='observed_at'}}
        return replace(state,intent=updated,phase='REQUESTED',records={})
    if op in {'VERIFIED','HAND_BACK_INTENT'}:
        v=d['verification'];exact(v,'auth_state page_identity business_state resume_safe source_ref evidence_digest observed_at')
        require(v['resume_safe'] is True and all(isinstance(v[k],str) and v[k] for k in v if k!='resume_safe'),'GATE_RESUME_VERIFICATION_INVALID')
        if op=='HAND_BACK_INTENT':require(d==state.records['VERIFIED'],'GATE_RESUME_VERIFICATION_MISMATCH')
    if op=='DECIDED':require(d['decision_id']==state.intent['decision_id'],'GATE_RESUME_DECISION_MISMATCH')
    if op=='RESUME_SAFE':require(isinstance(d['result'],dict) and d['result'].get('status')=='RESUME_SAFE' and (d['continuation'] is None or isinstance(d['continuation'],dict)),'GATE_RESUME_RESULT_INVALID')
    if op=='CONTINUATION_SENT':
        require(state.records['RESUME_SAFE']['continuation'] is not None
            and d['request_digest']==canonical_sha256(state.records['RESUME_SAFE']['continuation'])
            and d['effect_id']=='gate-continuation:'+canonical_sha256({'subject':state.subject_id,'request':d['request_digest']}),'GATE_RESUME_EFFECT_ID_INVALID')
    if op=='COMPLETED':require(isinstance(d['result'],dict),'GATE_RESUME_RESULT_INVALID')
    return replace(state,phase=op,records={**state.records,op:d})

class StateContribution:
    def initial_state(self,mid):return ResumeState(mid)
    def encode(self,state):return state.to_dict()
    def decode(self,value):return ResumeState(**value)
    def hash(self,state):return canonical_sha256(state.to_dict())
    def root_exists(self,state,subject):return state.subject_id==subject.subject_id and bool(state.intent)

class CommandContribution:
    def handle(self,command,composed):
        require(command.actor==OWNER and command.session_id is None,'GATE_RESUME_TRUSTED_OWNER_REQUIRED')
        payload=dict(command.payload);state=composed.extension_state(EXTENSION_ID)
        if command.type==CREATE:
            creation_transition(state,payload)
            return [PendingEvent(CREATED,KIND,command.mission_id,payload)]
        transition(state,payload)
        return [PendingEvent(EVENT,KIND,command.mission_id,payload)]

class ReducerContribution:
    def reduce(self,state,event,core_state):
        require(event.initiator_type==OWNER.type and event.initiator_id==OWNER.id and event.session_id is None,'GATE_RESUME_TRUSTED_OWNER_REQUIRED')
        require(event.entity_type==KIND and event.entity_id==state.subject_id and event.mission_id==state.subject_id,'GATE_RESUME_EVENT_INVALID')
        if event.event_type==CREATED:return creation_transition(state,dict(event.payload))
        require(event.event_type==EVENT,'GATE_RESUME_EVENT_INVALID')
        return transition(state,dict(event.payload))

SQL='CREATE TABLE human_gate_resume_projection(mission_id TEXT PRIMARY KEY,state_json TEXT NOT NULL,projection_seq INTEGER NOT NULL)'
def migrate(conn):conn.execute(SQL)
class MigrationContribution:
    extension_id=EXTENSION_ID
    migrations=(MigrationStep(1,canonical_sha256(SQL),migrate),)
class ProjectionContribution:
    projection_tables=frozenset({'human_gate_resume_projection'})
    def clear(self,conn,mid=None):conn.execute('DELETE FROM human_gate_resume_projection'+(' WHERE mission_id=?' if mid else ''),(mid,) if mid else ())
    def apply(self,conn,composed):
        self.clear(conn,composed.mission_id)
        conn.execute('INSERT INTO human_gate_resume_projection VALUES(?,?,?)',(composed.mission_id,canonical_json(composed.extension_state(EXTENSION_ID).to_dict()),composed.seq))
    def read(self,conn,mid):
        row=conn.execute('SELECT state_json FROM human_gate_resume_projection WHERE mission_id=?',(mid,)).fetchone()
        return ResumeState(**json.loads(row[0])) if row else ResumeState(mid)
    def projection_seq(self,conn,mid):
        row=conn.execute('SELECT projection_seq FROM human_gate_resume_projection WHERE mission_id=?',(mid,)).fetchone();return row[0] if row else None
    def verify(self,replayed,projected):
        a=canonical_sha256(replayed.to_dict());b=canonical_sha256(projected.to_dict()) if projected else None
        return {'ok':a==b,'replay_hash':a,'projection_hash':b}

def human_gate_resume_extension():
    commands=frozenset({COMMAND,CREATE});events=frozenset({EVENT,CREATED})
    return ExtensionManifest(EXTENSION_ID,'1.0.0',commands,events,StateContribution(),CommandContribution(),ReducerContribution(),ProjectionContribution(),MigrationContribution(),
        subject_kinds=frozenset({KIND}),roots=(RootDefinition(KIND,PREFIX,1,CREATE,CREATED,KIND,commands,events),))


class GateResumeReceipt:
    def __init__(self,runtime,mid,gate):self.runtime=runtime;self.subject=subject_for(mid,gate)
    def state(self):
        if not self.runtime.get_head_seq(self.subject.subject_id):return ResumeState(self.subject.subject_id)
        return self.runtime.get_subject_state(self.subject).root_state
    def execute(self,kind,payload):
        result=self.runtime.execute(CommandEnvelope('gate-resume:'+uuid.uuid4().hex,kind,self.subject.subject_id,
            self.runtime.get_head_seq(self.subject.subject_id),OWNER,{'subject':self.subject.to_dict(),**payload}))
        if not result.ok:raise result.error
        return self.state()
    def create(self,intent):return self.execute(CREATE,{'root_version':1,'creation_command':CREATE,'intent':intent})
    def record(self,phase,data):return self.execute(COMMAND,{'operation':phase,'data':data})
