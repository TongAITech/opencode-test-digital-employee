"""R1-only Mission control; the background controller owns subsequent dispatch.

No model-authored Session identity or direct provider effect is accepted. A
control command and its existing interaction receipt can recover independently
without replaying a physical action or resolving a different Mission.
"""
from __future__ import annotations
from contextlib import closing
import json
import sqlite3
import uuid
from contextlib import contextmanager
from functools import wraps
from .general_work.execution_contract import stamp
from .primary_sessions import now
from .durable_core import ActorRef, CommandEnvelope, RuntimeError, canonical_sha256
from .dispatch_receipts import runtime_coordination, CoordinationBusy
from .general_work.execution_contract import require

COMMANDS = {'pause': 'PAUSE_MISSION', 'stop': 'CANCEL_MISSION', 'continue': 'CONTINUE_MISSION'}
TARGETS = {'pause': 'PAUSED', 'stop': 'CANCELLED', 'continue': 'ACTIVE'}


def generation(runtime, mission, through_seq):
    with closing(sqlite3.connect(runtime.db_path)) as conn:
        row=conn.execute("SELECT max(seq) FROM events WHERE mission_id=? AND seq<=? AND event_type IN ('mission.created','mission.activated','mission.paused','mission.blocked','mission.continued','mission.cancelled','mission.completed','mission.failed')",(mission,through_seq)).fetchone()
    require(row and row[0], 'MISSION_CONTROL_GENERATION_REQUIRED')
    return row[0]


def prepare_control(service, owner, admitted):
    runtime=service.runtime;op=admitted['operation_id'];action=admitted['action']
    require(admitted['intent']=='MISSION_CONTROL' and action in COMMANDS, 'MISSION_CONTROL_ACTION_INVALID')
    # This intake mutex is distinct from the physical-effect mutex. A long
    # admitted effect must not prevent durable receipt of a requested pause.
    with runtime_coordination(str(runtime.db_path)+'.control-intake.db'):
        prior=owner.receipt(op)
        if prior:
            request={**admitted,'subject':prior['subject'],'resolved_scope':prior['resolved_scope']}
            if 'control_intent' in prior:request['control_intent']=prior['control_intent']
            return owner.claim(request)
        require(admitted['status']=='ADMITTED' and admitted['subject'] is not None
            and admitted['subject']['subject_kind']=='MISSION', 'MISSION_CONTROL_ADMISSION_REQUIRED')
        mission=admitted['subject']['subject_id'];seq=admitted['expected_subject_seq']
        require(type(seq) is int and seq>0, 'MISSION_CONTROL_CURSOR_REQUIRED')
        original=runtime.replay_composed(mission,through_seq=seq)
        require(original.seq==seq and original.core_state.mission is not None, 'MISSION_CONTROL_CURSOR_INVALID')
        status=original.core_state.mission.status.value
        intent={'mission_id':mission,'admission_seq':seq,'control_generation':generation(runtime,mission,seq),
            'from_status':status,'target_status':TARGETS[action],'no_effect':status==TARGETS[action]}
        return owner.claim({**admitted,'control_intent':intent})


def apply_control(service, owner, admitted):
    """Persist intake first; recover the original decision, never a newer one."""
    runtime=service.runtime;op=admitted['operation_id'];action=admitted['action']
    claim=prepare_control(service,owner,admitted)
    if claim['state']=='COMPLETED':return {'status':'REPLAYED','result':claim['result'],'subject':claim['bound_subject']}
    require(claim['state'] in {'CLAIMED','BOUND'} and 'control_intent' in claim, 'MISSION_CONTROL_RECONCILIATION_REQUIRED')
    try:
        with runtime_coordination(runtime.db_path,timeout=.1):
            claim=owner.receipt(op) # another controller may have drained it
            if claim['state']=='COMPLETED':return {'status':'REPLAYED','result':claim['result'],'subject':claim['bound_subject']}
            if claim['state']=='CLAIMED':owner.bind(op,claim['subject'])
            mission=claim['subject']['subject_id'];intent=claim['control_intent'];key='interaction-control:'+op
            with closing(sqlite3.connect(runtime.db_path)) as conn:
                conn.row_factory=sqlite3.Row
                rows=conn.execute("SELECT * FROM commands WHERE idempotency_key=? AND status='APPLIED'",(key,)).fetchall()
            require(len(rows)<=1,'MISSION_CONTROL_COMMAND_AMBIGUOUS')
            if rows:
                row=rows[0]
                require(row['mission_id']==mission and row['command_type']==COMMANDS[action]
                    and row['actor_type']=='SYSTEM' and row['actor_id']=='interaction-mission-control'
                    and json.loads(row['payload_json'])=={'reason':key}, 'MISSION_CONTROL_RECEIPT_MISMATCH')
                result={'status':TARGETS[action],'mission_id':mission,'command_ref':row['command_id'],
                    'transition_seq':row['last_seq'],'effect':'R1_STATE_TRANSITION_ONLY','dispatch_owner':'BACKGROUND_CONTROL_LOOP'}
            elif intent['no_effect']:
                # Already-in-state was decided durably at original admission.
                # A crash cannot turn it into a new transition after newer work.
                result={'status':intent['from_status'],'mission_id':mission,'already_in_state':True,
                    'observed_seq':intent['admission_seq'],'historical_observation':True,'effect':'NONE'}
            elif intent['from_status'] not in {'pause':{'ACTIVE'},'stop':{'CREATED','ACTIVE','PAUSED','BLOCKED'},'continue':{'PAUSED','BLOCKED'}}[action]:
                result={'status':'REJECTED','reason':'CONTROL_INVALID_FROM_STATE','mission_id':mission,'effect':'NONE'}
            else:
                composed=runtime.replay_composed(mission)
                if generation(runtime,mission,composed.seq)!=intent['control_generation']:
                    result={'status':'REJECTED','reason':'STALE_CONTROL_GENERATION','mission_id':mission,'effect':'NONE'}
                elif stamp(now()) > stamp(claim['host_turn_ref']['valid_until']):
                    result={'status':'REJECTED','reason':'HOST_USER_TURN_EXPIRED','mission_id':mission,'effect':'NONE'}
                else:
                    command=CommandEnvelope('control:'+uuid.uuid4().hex,COMMANDS[action],mission,composed.seq,
                        ActorRef('SYSTEM','interaction-mission-control'),{'reason':key},idempotency_key=key)
                    applied=runtime.execute(command)
                    if not applied.ok:raise applied.error
                    result={'status':TARGETS[action],'mission_id':mission,'command_ref':command.command_id,
                        'transition_seq':applied.last_seq,'effect':'R1_STATE_TRANSITION_ONLY','dispatch_owner':'BACKGROUND_CONTROL_LOOP'}
            owner.complete(op,result)
            return {'status':'COMPLETED','subject':claim['subject'],'result':result}
    except CoordinationBusy:
        return {'status':'CONTROL_PENDING','subject':claim['subject'],'reason':'DRAINING_INFLIGHT_EFFECT',
            'result':{'status':'CONTROL_PENDING','operation_id':op,'dispatch_owner':'BACKGROUND_CONTROL_LOOP'}}


def pending_controls(runtime, *, mission_id=None, stopping_only=False, limit=64):
    from .interaction_receipts import CONTROL_INTENT_EVENT, ROOT_KIND
    from .durable_core import SubjectRef
    # Query pending canonical events rather than limiting lifetime history.
    # Completed streams are excluded before LIMIT; projections grant no authority.
    sql = """SELECT intent.mission_id FROM events AS intent WHERE intent.event_type=?
        AND NOT EXISTS (SELECT 1 FROM events AS done WHERE done.mission_id=intent.mission_id
                        AND done.event_type='interaction.operation_completed.v1')"""
    args=[CONTROL_INTENT_EVENT]
    if mission_id is not None:
        sql += " AND json_extract(intent.payload_json,'$.control_intent.mission_id')=?";args.append(mission_id)
    if stopping_only:sql += " AND json_extract(intent.payload_json,'$.control_intent.target_status') IN ('PAUSED','CANCELLED')"
    sql += ' ORDER BY intent.created_at,intent.mission_id LIMIT ?';args.append(limit)
    with closing(sqlite3.connect(runtime.db_path)) as conn:rows=conn.execute(sql,args).fetchall()
    result=[]
    for row in rows:
        receipt=runtime.get_subject_state(SubjectRef(ROOT_KIND,row[0])).root_state.receipt
        if receipt['state'] in {'CLAIMED','BOUND'}:result.append(dict(receipt))
    return result


def reconcile_controls(service):
    from .interaction_receipts import R1InteractionOwner
    owner=R1InteractionOwner(service.runtime);results=[]
    for claim in pending_controls(service.runtime)[:64]:
        try:result=apply_control(service,owner,claim)
        except Exception as exc:result={'status':'RECONCILE_REQUIRED','reason':getattr(exc,'code',type(exc).__name__)}
        results.append({'operation_id':claim['operation_id'],**result})
    return {'status':'PENDING' if any(r['status'] in {'CONTROL_PENDING','RECONCILE_REQUIRED'} for r in results) else 'PASS','operations':results}


def require_no_pending_control(runtime, mission_id):
    require(not any(r['subject']['subject_id']==mission_id and r['action'] in {'pause','stop'} for r in pending_controls(runtime, mission_id=mission_id, stopping_only=True, limit=1)), 'MISSION_CONTROL_PENDING')


@contextmanager
def active_effect(runtime, mission_id):
    """Pause drains an already admitted call and blocks every later SUT call."""
    with runtime_coordination(runtime.db_path):
        require_no_pending_control(runtime,mission_id)
        core=runtime.replay_composed(mission_id).core_state
        require(core.mission is not None and core.mission.status.value=='ACTIVE', 'MISSION_NOT_ACTIVE')
        yield


def governed_effect(method):
    @wraps(method)
    def call(self,mission_id,*args,**kwargs):
        with active_effect(self.runtime,mission_id):return method(self,mission_id,*args,**kwargs)
    return call
