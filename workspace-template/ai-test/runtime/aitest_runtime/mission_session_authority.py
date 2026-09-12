"""Typed R1 Session authority, granted by Runtime before Host dispatch.

Frozen R2.5 bindings anchor logical identity to the root Attempt. They are never
rewritten to point at a successor. Current authority joins that anchor with the
latest Attempt, current WorkGraph and a realm-bound, immutable Host lease. Each
root references one real Mission. It contains no Tasks or scheduling authority;
its separate root preserves frozen Mission bytes and composition hashes.
"""
from __future__ import annotations
from dataclasses import dataclass, field, replace
from datetime import timedelta
import json
from pathlib import Path
import uuid

from .durable_core import (ActorRef, CommandEnvelope, ExtensionManifest, MigrationStep,
    PendingEvent, RootDefinition, SubjectRef, canonical_json, canonical_sha256)
from .general_work.execution_contract import require, stamp
from .primary_sessions import PrimarySessionOwner, now
from .dispatch_receipts import runtime_coordination
from .g2_1.router import SessionRouter, AgentRoleRegistry

EXTENSION_ID='mission_session_authority'
COMMAND='RECORD_MISSION_SESSION_AUTHORITY'
EVENT='mission_authority.recorded.v1'
OWNER=ActorRef('SYSTEM','mission-session-owner')
POLICY='mission-session-authority.v4.1'
KIND='MISSION_SESSION_AUTHORITY'
PREFIX='mission-session-authority:v1:'
CREATE='CREATE_MISSION_SESSION_AUTHORITY'
CREATED='mission_authority.created.v1'

def subject_for(mid):return SubjectRef(KIND,PREFIX+canonical_sha256(SubjectRef('MISSION',mid).to_dict()))


def exact(value, keys):
    require(isinstance(value,dict) and set(value)==set(keys.split()),'MISSION_AUTHORITY_SCHEMA_INVALID')


@dataclass(frozen=True)
class AuthorityState:
    subject_id: str
    mission_id: str | None=None
    workspace_root: str | None=None
    requests: dict=field(default_factory=dict)
    grants: dict=field(default_factory=dict)
    def to_dict(self):return {'subject_id':self.subject_id,'mission_id':self.mission_id,'workspace_root':self.workspace_root,'requests':self.requests,'grants':self.grants}


def creation_transition(state,payload):
    exact(payload,'subject root_version creation_command workspace_root policy mission_ref')
    require(type(payload['root_version']) is int and payload['root_version']==1
        and payload['creation_command']==CREATE and payload['policy']==POLICY,'MISSION_AUTHORITY_ROOT_INVALID')
    require(isinstance(payload['workspace_root'],str) and 0<len(payload['workspace_root'])<=4096,'MISSION_AUTHORITY_WORKSPACE_INVALID')
    exact(payload['mission_ref'],'subject_kind subject_id');ref=payload['mission_ref']
    require(ref['subject_kind']=='MISSION' and isinstance(ref['subject_id'],str) and 0<len(ref['subject_id'])<=256,'MISSION_AUTHORITY_MISSION_REF_INVALID')
    require(subject_for(ref['subject_id']).subject_id==state.subject_id
        and payload['subject']==SubjectRef(KIND,state.subject_id).to_dict()
        and state.mission_id is None and not state.requests and not state.grants,'MISSION_AUTHORITY_ROOT_INVALID')
    return replace(state,mission_id=ref['subject_id'],workspace_root=payload['workspace_root'])


def transition(state, payload):
    exact(payload,'subject operation data')
    require(state.mission_id is not None and payload['subject']==SubjectRef(KIND,state.subject_id).to_dict(),'MISSION_AUTHORITY_ROOT_REQUIRED')
    require(len(canonical_json(payload).encode())<=16384,'MISSION_AUTHORITY_EVENT_BUDGET')
    op=payload['operation'];data=payload['data']
    requests={k:dict(v) for k,v in state.requests.items()};grants={k:dict(v) for k,v in state.grants.items()}
    if op=='REQUEST':
        exact(data,'provision_token host_realm directory_digest requested_at policy provision')
        require(data['policy']==POLICY,'MISSION_AUTHORITY_POLICY_INVALID')
        for k in ('host_realm','directory_digest'):
            require(isinstance(data[k],str) and len(data[k])==64 and all(c in '0123456789abcdef' for c in data[k]),'MISSION_AUTHORITY_DIGEST_INVALID')
        require(data['directory_digest']==canonical_sha256(state.workspace_root),'MISSION_AUTHORITY_WORKSPACE_MISMATCH')
        exact(data['provision'],'task_id root_attempt_id logical_agent_id role agent_name phase title')
        p=data['provision'];require(p['phase'] in {'PLANNING','PLANNING_ROTATION','TASK_EXECUTION','TASK_ROTATION'},'MISSION_AUTHORITY_PHASE_INVALID')
        for k in ('logical_agent_id','role','agent_name','title'):
            require(isinstance(p[k],str) and 0<len(p[k])<=2048,'MISSION_AUTHORITY_PROVISION_INVALID')
        for k in ('task_id','root_attempt_id'):
            require(p[k] is None or isinstance(p[k],str) and 0<len(p[k])<=256,'MISSION_AUTHORITY_PROVISION_INVALID')
        require(isinstance(data['provision_token'],str) and 0<len(data['provision_token'])<=256,'MISSION_AUTHORITY_TOKEN_INVALID')
        stamp(data['requested_at']);token=data['provision_token']
        require(token not in requests,'MISSION_AUTHORITY_REQUEST_EXISTS');requests[token]=data
    elif op=='GRANT':
        exact(data,'session_id provision_token host_realm logical_agent_id role agent_name task_id root_attempt_id attempt_id plan_id plan_revision_id planning_lineage goal_id goal_revision epoch observed_at expires_at')
        request=requests.get(data['provision_token'])
        require(request is not None and request['host_realm']==data['host_realm'],'MISSION_AUTHORITY_REQUEST_REQUIRED')
        p=request['provision']
        require(all(data[k]==p[k] for k in ('task_id','logical_agent_id','role','agent_name')),'MISSION_AUTHORITY_PROVISION_MISMATCH')
        planning=p['phase'] in {'PLANNING','PLANNING_ROTATION'}
        require(p['root_attempt_id'] is None or p['root_attempt_id']==data['planning_lineage' if planning else 'root_attempt_id'],'MISSION_AUTHORITY_ROOT_MISMATCH')
        for k in ('goal_id','logical_agent_id','role','agent_name'):
            require(isinstance(data[k],str) and 0<len(data[k])<=256,'MISSION_AUTHORITY_GRANT_INVALID')
        for k in ('task_id','root_attempt_id','attempt_id','plan_id','plan_revision_id'):
            require(data[k] is None if planning else isinstance(data[k],str) and 0<len(data[k])<=256,'MISSION_AUTHORITY_GRANT_INVALID')
        require(data['planning_lineage']=='planning:'+data['logical_agent_id'] if planning else data['planning_lineage'] is None,'MISSION_AUTHORITY_PLANNER_LINEAGE_INVALID')
        require(isinstance(data['session_id'],str) and 0<len(data['session_id'])<=256 and data['session_id'] not in grants,'MISSION_AUTHORITY_SESSION_REUSE')
        require(type(data['epoch']) is int and data['epoch']==1+max((g['epoch'] for g in grants.values() if g['logical_agent_id']==data['logical_agent_id']),default=0),'MISSION_AUTHORITY_EPOCH_INVALID')
        require(type(data['goal_revision']) is int and data['goal_revision']>0,'MISSION_AUTHORITY_GOAL_INVALID')
        require(stamp(data['observed_at'])>=stamp(request['requested_at']) and 0<(stamp(data['expires_at'])-stamp(data['observed_at'])).total_seconds()<=8*3600,'MISSION_AUTHORITY_LEASE_INVALID')
        require(not any(g['state']=='GRANTED' and g['logical_agent_id']==data['logical_agent_id'] for g in grants.values()),'MISSION_AUTHORITY_PREDECESSOR_NOT_RETIRED')
        grants[data['session_id']]={**data,'state':'GRANTED'}
    elif op=='RETIRE':
        exact(data,'session_id reason observed_at');g=grants.get(data['session_id'])
        require(g is not None and g['state']=='GRANTED','MISSION_AUTHORITY_CURRENT_REQUIRED')
        require(isinstance(data['reason'],str) and 0<len(data['reason'])<=256 and stamp(data['observed_at'])>=stamp(g['observed_at']),'MISSION_AUTHORITY_RETIRE_INVALID')
        g.update(state='RETIRED',retired_at=data['observed_at'],reason=data['reason'])
    else:require(False,'MISSION_AUTHORITY_OPERATION_INVALID')
    return replace(state,requests=requests,grants=grants)


def lineage(composed, session_id, provision):
    """Only durable joins; no caller-supplied IDs and no mutable projections."""
    core=composed.core_state;mission=core.mission
    require(mission is not None and mission.status.value=='ACTIVE','MISSION_NOT_ACTIVE')
    session=core.session(session_id)
    require(session is not None and session.status.value=='OPEN','STALE_CALLER')
    goal=core.goal(mission.active_goal_id)
    require(goal is not None,'MISSION_AUTHORITY_GOAL_REQUIRED')
    role=AgentRoleRegistry.default().resolve(provision.role)
    require(role.agent_name==provision.agent_name,'MISSION_AUTHORITY_ROLE_MISMATCH')
    attrs=dict(session.attributes or {})
    require(not attrs.get('opencode_agent') or attrs['opencode_agent']==role.agent_name,'MISSION_AUTHORITY_ROLE_MISMATCH')
    base={'session_id':session_id,'provision_token':provision.provision_token,
        'logical_agent_id':provision.logical_agent_id,'role':role.role,'agent_name':role.agent_name,
        'goal_id':goal.goal_id,'goal_revision':goal.revision,'task_id':None,'root_attempt_id':None,
        'attempt_id':None,'plan_id':None,'plan_revision_id':None,'planning_lineage':None}
    if provision.phase in {'PLANNING','PLANNING_ROTATION'}:
        expected=SessionRouter.logical_agent_id(role.agent_name,f'planning:{mission.mission_id}:{goal.revision}')
        require(role.role=='PLANNER' and provision.task_id is None and attrs.get('phase')=='PLANNING'
            and attrs.get('logical_agent_id')==expected and provision.logical_agent_id==expected,'MISSION_AUTHORITY_PLANNER_STALE')
        require(provision.root_attempt_id in {None,'planning:'+expected},'MISSION_AUTHORITY_PLANNER_LINEAGE_INVALID')
        return {**base,'planning_lineage':'planning:'+expected}
    graph=composed.extension_state('r1_2_work_graph')
    execution=composed.extension_state('r1_3b_execution_resume')
    task=graph.task(provision.task_id);attempt=execution.latest_attempt(provision.task_id)
    require(task is not None and task.lifecycle_state.value=='ACTIVE' and attempt is not None,'MISSION_AUTHORITY_ACTIVE_TASK_REQUIRED')
    plan=graph.plan(task.plan_id)
    require(plan is not None and plan.lifecycle_state.value=='OPEN' and plan.current_revision_id==task.plan_revision_id
        and attempt.plan_id==task.plan_id and attempt.plan_revision_id==task.plan_revision_id
        and attempt.runtime_session_id==session_id,'STALE_CALLER')
    route=composed.extension_state('g2_1_session_control').route(task.task_id)
    logical=SessionRouter.logical_agent_id(role.agent_name,task.task_id)
    anchors=[b for b in composed.extension_state('r2_5_session_orchestration').bindings if b.root_attempt_id==attempt.root_attempt_id]
    require(route is not None and route.role==role.role and route.agent_name==role.agent_name
        and provision.logical_agent_id==logical and len(anchors)==1 and anchors[0].logical_agent_id==logical
        and anchors[0].task_id==task.task_id,'MISSION_AUTHORITY_LOGICAL_BINDING_INVALID')
    require(provision.root_attempt_id in {None,attempt.root_attempt_id},'MISSION_AUTHORITY_ROOT_MISMATCH')
    return {**base,'task_id':task.task_id,'root_attempt_id':attempt.root_attempt_id,'attempt_id':attempt.attempt_id,
        'plan_id':task.plan_id,'plan_revision_id':task.plan_revision_id}


class StateContribution:
    def initial_state(self,mid):return AuthorityState(mid)
    def encode(self,state):return state.to_dict()
    def decode(self,value):return AuthorityState(**value)
    def hash(self,state):return canonical_sha256(state.to_dict())
    def root_exists(self,state,subject):return state.subject_id==subject.subject_id and state.mission_id is not None

class CommandContribution:
    def handle(self,command,composed):
        require(command.actor==OWNER and command.session_id is None,'MISSION_AUTHORITY_TRUSTED_OWNER_REQUIRED')
        payload=dict(command.payload);state=composed.extension_state(EXTENSION_ID)
        if command.type==CREATE:
            creation_transition(state,payload)
            return [PendingEvent(CREATED,KIND,command.mission_id,payload)]
        transition(state,payload)
        return [PendingEvent(EVENT,KIND,command.mission_id,payload)]

class ReducerContribution:
    def reduce(self,state,event,core_state):
        require(event.initiator_type==OWNER.type and event.initiator_id==OWNER.id and event.session_id is None,'MISSION_AUTHORITY_TRUSTED_OWNER_REQUIRED')
        require(event.entity_type==KIND and event.entity_id==state.subject_id and event.mission_id==state.subject_id,'MISSION_AUTHORITY_EVENT_INVALID')
        if event.event_type==CREATED:return creation_transition(state,dict(event.payload))
        require(event.event_type==EVENT,'MISSION_AUTHORITY_EVENT_INVALID')
        return transition(state,dict(event.payload))

SQL='CREATE TABLE mission_session_authority_projection(mission_id TEXT PRIMARY KEY,state_json TEXT NOT NULL,projection_seq INTEGER NOT NULL)'
def migrate(conn):conn.execute(SQL)
class MigrationContribution:
    extension_id=EXTENSION_ID
    migrations=(MigrationStep(1,canonical_sha256(SQL),migrate),)
class ProjectionContribution:
    projection_tables=frozenset({'mission_session_authority_projection'})
    def clear(self,conn,mid=None):conn.execute('DELETE FROM mission_session_authority_projection'+(' WHERE mission_id=?' if mid else ''),(mid,) if mid else ())
    def apply(self,conn,composed):
        self.clear(conn,composed.mission_id)
        conn.execute('INSERT INTO mission_session_authority_projection VALUES(?,?,?)',(composed.mission_id,canonical_json(composed.extension_state(EXTENSION_ID).to_dict()),composed.seq))
    def read(self,conn,mid):
        row=conn.execute('SELECT state_json FROM mission_session_authority_projection WHERE mission_id=?',(mid,)).fetchone()
        return AuthorityState(**json.loads(row[0])) if row else AuthorityState(mid)
    def projection_seq(self,conn,mid):
        row=conn.execute('SELECT projection_seq FROM mission_session_authority_projection WHERE mission_id=?',(mid,)).fetchone();return row[0] if row else None
    def verify(self,replayed,projected):
        a=canonical_sha256(replayed.to_dict());b=canonical_sha256(projected.to_dict()) if projected else None
        return {'ok':a==b,'replay_hash':a,'projection_hash':b}

def mission_session_extension():
    commands=frozenset({COMMAND,CREATE});events=frozenset({EVENT,CREATED})
    return ExtensionManifest(EXTENSION_ID,'1.0.0',commands,events,StateContribution(),CommandContribution(),ReducerContribution(),ProjectionContribution(),MigrationContribution(),
        subject_kinds=frozenset({KIND}),roots=(RootDefinition(KIND,PREFIX,1,CREATE,CREATED,KIND,commands,events),))


class MissionSessionOwner:
    def __init__(self,service):
        self.service=service;self.runtime=service.runtime;self.root=Path(service.workspace_root).resolve()
        self.provider=service.raw_session_provider
    def realm(self):return PrimarySessionOwner(self.runtime,self.root,self.provider).host_realm()
    def state(self,mid):
        subject=subject_for(mid)
        if not self.runtime.get_head_seq(subject.subject_id):return AuthorityState(subject.subject_id)
        state=self.runtime.get_subject_state(subject).root_state
        require(state.mission_id==mid and state.workspace_root==str(self.root),'MISSION_AUTHORITY_WORKSPACE_MISMATCH')
        return state
    def record(self,mid,op,data):
        with runtime_coordination(self.runtime.db_path):
            composed=self.runtime.get_subject_state(SubjectRef('MISSION',mid))
            require(composed.root_state.mission is not None,'MISSION_AUTHORITY_MISSION_REQUIRED')
            if op in {'REQUEST','GRANT'}:
                mission=self.runtime.replay_composed(mid);p=mission.extension_state('g2_1_session_control').provision(data['provision_token'])
                require(p is not None,'MISSION_AUTHORITY_PROVISION_REQUIRED')
                if op=='REQUEST':require(data['provision']=={k:getattr(p,k) for k in data['provision']},'MISSION_AUTHORITY_PROVISION_MISMATCH')
                else:
                    expected=lineage(mission,data['session_id'],p)
                    require(all(data[k]==v for k,v in expected.items()),'MISSION_AUTHORITY_LINEAGE_MISMATCH')
                    require(p.status=='BOUND' and p.external_session_id==data['session_id'],'MISSION_AUTHORITY_PROVISION_NOT_BOUND')
            subject=subject_for(mid)
            result=self.runtime.execute(CommandEnvelope('mission-authority:'+uuid.uuid4().hex,COMMAND,subject.subject_id,
                self.runtime.get_head_seq(subject.subject_id),OWNER,{'subject':subject.to_dict(),'operation':op,'data':data}))
            if not result.ok:raise result.error
            return self.state(mid)
    def ensure_root(self,mid):
        self.runtime.get_subject_state(SubjectRef('MISSION',mid))
        subject=subject_for(mid)
        if self.runtime.get_head_seq(subject.subject_id):self.state(mid);return
        result=self.runtime.execute(CommandEnvelope('mission-authority-root:'+uuid.uuid4().hex,CREATE,
            subject.subject_id,0,OWNER,{'subject':subject.to_dict(),'root_version':1,'creation_command':CREATE,
                'workspace_root':str(self.root),'policy':POLICY,'mission_ref':SubjectRef('MISSION',mid).to_dict()}))
        if not result.ok:raise result.error
    def request(self,mid,token):
        with runtime_coordination(self.runtime.db_path):
            self.ensure_root(mid)
            p=self.service.session_control.state(mid).provision(token)
            require(p is not None,'MISSION_AUTHORITY_PROVISION_REQUIRED')
            data={'provision_token':token,'host_realm':self.realm(),'directory_digest':canonical_sha256(str(self.root)),
                'policy':POLICY,'provision':{k:getattr(p,k) for k in ('task_id','root_attempt_id','logical_agent_id','role','agent_name','phase','title')}}
            prior=self.state(mid).requests.get(token)
            if prior:
                require(all(prior[k]==v for k,v in data.items()),'MISSION_AUTHORITY_REQUEST_CONFLICT');return prior
            self.record(mid,'REQUEST',{**data,'requested_at':now()});return self.state(mid).requests[token]
    def retire(self,mid,sid,reason):
        grant=self.state(mid).grants.get(sid)
        if grant and grant['state']=='GRANTED':self.record(mid,'RETIRE',{'session_id':sid,'reason':reason,'observed_at':now()})
    def before_dispatch(self,mid,sid,agent):
        with runtime_coordination(self.runtime.db_path):
            prior=self.state(mid).grants.get(sid)
            if prior:return self.current(mid,sid,agent=agent)
            actual=[s for s in self.provider.list_sessions() if s.session_id==sid and Path(s.directory).resolve()==self.root]
            require(len(actual)==1,'MISSION_AUTHORITY_HOST_SESSION_REQUIRED')
            ps=[p for p in self.service.session_control.state(mid).provisions if p.title==actual[0].title and p.agent_name==agent]
            require(len(ps)==1,'MISSION_AUTHORITY_HOST_PROVISION_AMBIGUOUS');p=ps[0]
            request=self.state(mid).requests.get(p.provision_token)
            require(request is not None and request['host_realm']==self.realm(),'MISSION_AUTHORITY_HOST_REALM_MISMATCH')
            self.service._bind_provision_if_needed(mid,p.provision_token,sid)
            composed=self.runtime.replay_composed(mid);p=self.service.session_control.state(mid).provision(p.provision_token)
            derived=lineage(composed,sid,p)
            for old in list(self.state(mid).grants.values()):
                if old['state']=='GRANTED' and old['logical_agent_id']==derived['logical_agent_id']:
                    self.retire(mid,old['session_id'],'SUCCESSOR_BEFORE_DISPATCH')
            epoch=1+max((g['epoch'] for g in self.state(mid).grants.values() if g['logical_agent_id']==derived['logical_agent_id']),default=0)
            observed=now();self.record(mid,'GRANT',{**derived,'host_realm':self.realm(),'epoch':epoch,
                'observed_at':observed,'expires_at':(stamp(observed)+timedelta(hours=8)).isoformat()})
            return self.current(mid,sid,agent=agent)
    def current(self,mid,sid,*,agent=None):
        composed=self.runtime.replay_composed(mid);grant=self.state(mid).grants.get(sid)
        require(grant is not None and grant['state']=='GRANTED','STALE_CALLER')
        require(grant['host_realm']==self.realm(),'MISSION_AUTHORITY_HOST_REALM_MISMATCH')
        require(stamp(now())<stamp(grant['expires_at']),'MISSION_AUTHORITY_LEASE_EXPIRED')
        require(agent is None or grant['agent_name']==agent,'MISSION_AUTHORITY_ROLE_MISMATCH')
        p=composed.extension_state('g2_1_session_control').provision(grant['provision_token'])
        require(p is not None and p.status=='BOUND' and p.external_session_id==sid,'MISSION_AUTHORITY_PROVISION_NOT_BOUND')
        derived=lineage(composed,sid,p)
        require(all(grant[k]==v for k,v in derived.items()),'STALE_CALLER')
        return dict(grant)
