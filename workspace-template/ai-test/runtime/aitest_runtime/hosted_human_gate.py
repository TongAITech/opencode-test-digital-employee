"""Actual Host request admission and background recovery of immutable Gate claims."""
from contextlib import closing
import sqlite3
from .dispatch_receipts import runtime_coordination
from .durable_core import SubjectRef, canonical_sha256
from .general_work.execution_contract import require, stamp
from .primary_sessions import now
from .interaction_admission import resolve_subject
from .interaction_receipts import R1InteractionOwner, ROOT_KIND, GATE_INTENT_EVENT
from .human_gate_resume_receipts import GateResumeReceipt


def prepare_gate(g4,owner,admitted,candidates):
    with runtime_coordination(g4.runtime.db_path):
        prior=owner.receipt(admitted['operation_id'])
        if prior:
            require('gate_intent' in prior,'INTERACTION_GATE_INTENT_REQUIRED')
            return owner.claim({**admitted,'subject':prior['subject'],'resolved_scope':prior['resolved_scope'],'gate_intent':prior['gate_intent']})
        require(admitted['intent']=='HUMAN_GATE_RESPONSE' and admitted['status']=='OWNER_ADMISSION_REQUIRED','HUMAN_GATE_ADMISSION_REQUIRED')
        possible=[]
        for candidate in candidates:
            resolution,selected=resolve_subject([candidate],scope=admitted['resolved_scope'],subject_id=admitted['proposal']['subject_id'])
            if resolution!='UNIQUE':continue
            for gate,takeover in g4._compatible_explicit_human_gates(selected.subject_id):possible.append((selected,gate,takeover))
        if not possible:return {'status':'NO_PENDING_HUMAN_GATE','intent':'REQUEST_TO_VERIFY_COMPLETION'}
        if len(possible)>1:return {'status':'CLARIFICATION_REQUIRED','reason':'MULTIPLE_COMPATIBLE_PENDING_HUMAN_GATES',
            'compatible_gates':[{'mission_id':s.subject_id,'gate_id':g.gate_id} for s,g,_ in possible[:16]]}
        candidate,gate,takeover=possible[0]
        if candidate.admission_blocker:return {'status':'BLOCKED','reason':candidate.admission_blocker}
        claim={**admitted,'subject':candidate.ref(),'resolved_scope':dict(candidate.scope),
            'gate_intent':{'mission_id':candidate.subject_id,'gate_id':gate.gate_id,'takeover_ref':takeover.fact_id,
                'root_attempt_id':gate.root_attempt_id,'browser_context_digest':canonical_sha256(takeover.payload.get('browser_context_ref'))}}
        return owner.claim(claim)


def finish_gate(g4,owner,claim):
    with runtime_coordination(g4.runtime.db_path):
        claim=owner.receipt(claim['operation_id']);op=claim['operation_id']
        if claim['state']=='COMPLETED':return {'status':'REPLAYED','subject':claim['subject'],'result':claim['result']}
        require(claim['state'] in {'CLAIMED','BOUND'} and 'gate_intent' in claim,'INTERACTION_GATE_RECONCILIATION_REQUIRED')
        intent=claim['gate_intent'];mid=intent['mission_id'];gid=intent['gate_id']
        if claim['state']=='CLAIMED':owner.bind(op,claim['subject'])
        state=GateResumeReceipt(g4.runtime,mid,gid).state()
        if not state.intent or state.phase in {'REQUESTED','VERIFIED'}:
            # Starting a new effect requires a still-current admitted Host turn;
            # already-committed owner effects are recovered without Host history.
            if stamp(now())>stamp(claim['host_turn_ref']['valid_until']):
                result={'status':'REJECTED','reason':'HOST_USER_TURN_EXPIRED','effect':'NONE'}
                owner.complete(op,result);return {'status':'COMPLETED','subject':claim['subject'],'result':result}
            takeover=g4.state(mid).by_id(intent['takeover_ref'])
            require(takeover is not None and canonical_sha256(takeover.payload.get('browser_context_ref'))==intent['browser_context_digest'],'GATE_RESUME_CLAIM_CONTEXT_MISMATCH')
            latest=g4.state(mid).latest('HUMAN_TAKEOVER_REQUEST',lambda f:f.payload.get('human_gate_id')==gid)
            require(latest is not None and latest.fact_id==takeover.fact_id,'GATE_RESUME_TAKEOVER_CHANGED')
        else:
            require(state.intent['root_attempt_id']==intent['root_attempt_id'] and state.intent['takeover_ref']==intent['takeover_ref'],'GATE_RESUME_CLAIM_LINEAGE_MISMATCH')
        try:
            result=g4.complete_human_takeover(mid,{'human_gate_id':gid,'completion_mode':'EXPLICIT','operation_id':op,
                'actor_id':'host-user:'+canonical_sha256(claim['host_turn_ref']['source_ref']),'valid_until':claim['host_turn_ref']['valid_until']})
        except Exception as exc:
            reason=getattr(exc,'code',type(exc).__name__)
            if reason in {'G4_HUMAN_RESUME_REVALIDATION_FAILED','G4_HUMAN_RESUME_RUNTIME_VERIFICATION_FAILED'}:
                return {'status':'WAITING_HUMAN','subject':claim['subject'],'reason':reason,'verification':'NOT_YET_COMPLETE'}
            return {'status':'RECONCILE_REQUIRED','subject':claim['subject'],'reason':reason}
        summary={k:result[k] for k in ('status','root_attempt_id','resume_attempt_id','gate_resume_safe','reason','continuation','automatic_replay') if k in result}
        summary.update(mission_id=mid,gate_id=gid,completion_authority='BROWSER_RUNTIME_FRESH_VERIFICATION',user_text_authoritative=False)
        if result['status'] not in {'RESUME_SAFE','UNKNOWN_SIDE_EFFECT'}:return {'status':result['status'],'subject':claim['subject'],'result':summary}
        if result.get('ui_continuation'):
            summary['ui_continuation_status']=result['ui_continuation'].get('status','UNKNOWN')
        owner.complete(op,summary)
        return {'status':'COMPLETED','subject':claim['subject'],'result':summary}


def apply_gate(g4,owner,admitted,candidates):
    claim=prepare_gate(g4,owner,admitted,candidates)
    if 'state' not in claim:return claim
    return finish_gate(g4,owner,claim)


def recover_gate_interactions(g4,mission_id):
    sql="""SELECT e.mission_id FROM events e WHERE e.event_type=?
        AND json_extract(e.payload_json,'$.gate_intent.mission_id')=?
        AND NOT EXISTS (SELECT 1 FROM events d WHERE d.mission_id=e.mission_id AND d.event_type='interaction.operation_completed.v1')
        ORDER BY e.created_at,e.mission_id LIMIT 64"""
    with closing(sqlite3.connect(g4.runtime.db_path)) as conn:rows=conn.execute(sql,(GATE_INTENT_EVENT,mission_id)).fetchall()
    owner=R1InteractionOwner(g4.runtime);results=[]
    for row in rows:
        claim=g4.runtime.get_subject_state(SubjectRef(ROOT_KIND,row[0])).root_state.receipt
        try:result=finish_gate(g4,owner,claim)
        except Exception as exc:result={'status':'RECONCILE_REQUIRED','reason':getattr(exc,'code',type(exc).__name__)}
        results.append({'operation_id':claim['operation_id'],**result})
    return results


def recover_owned_resumes(g4,mission_id):
    from .human_gate_resume_receipts import CREATED, KIND
    sql="""SELECT e.mission_id FROM events e WHERE e.event_type=?
        AND json_extract(e.payload_json,'$.intent.mission_id')=?
        AND NOT EXISTS (SELECT 1 FROM events d WHERE d.mission_id=e.mission_id
          AND d.event_type='human_gate_resume.recorded.v1' AND json_extract(d.payload_json,'$.operation')='COMPLETED')
        ORDER BY e.created_at,e.mission_id LIMIT 64"""
    with closing(sqlite3.connect(g4.runtime.db_path)) as conn:rows=conn.execute(sql,(CREATED,mission_id)).fetchall()
    results=[]
    for row in rows:
        state=g4.runtime.get_subject_state(SubjectRef(KIND,row[0])).root_state
        try:result=g4.complete_human_takeover(mission_id,{'human_gate_id':state.intent['gate_id'],'completion_mode':state.intent['completion_mode']})
        except Exception as exc:result={'status':'RECONCILE_REQUIRED','reason':getattr(exc,'code',type(exc).__name__)}
        results.append({'gate_id':state.intent['gate_id'],'status':result['status']})
    return results
