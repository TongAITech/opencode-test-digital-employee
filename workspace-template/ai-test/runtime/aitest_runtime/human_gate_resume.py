"""G4 exact-Gate recovery. Caller prose is a verification request, never proof."""
from __future__ import annotations
from dataclasses import replace
from .durable_core import canonical_sha256, RuntimeError
from .general_work.execution_contract import require, stamp
from .primary_sessions import now
from .human_gate_resume_receipts import GateResumeReceipt
from .r3_e2.contracts import BrowserContextRef
from .g4.contracts import same_browser_context
from .mission_controls import require_no_pending_control


def gate_state(service,mid,gate_id):
    return service.runtime.replay_composed(mid).extension_state('r2_6_human_gate').gate(gate_id)


def resume_gate(service,mid,request):
    """Invoked under the existing G4 physical effect mutex for AUTO and explicit.

    The receipt belongs to a Gate, so concurrent AUTO and user requests converge.
    A submitted continuation without a result never executes again automatically.
    """
    gid=request.get('human_gate_id');require(isinstance(gid,str) and gid,'G4_HUMAN_GATE_SELECTION_REQUIRED')
    receipt=GateResumeReceipt(service.runtime,mid,gid);state=receipt.state()
    if state.phase=='COMPLETED':return state.records['COMPLETED']['result']
    if state.phase=='CONTINUATION_SENT':
        return {**state.records['RESUME_SAFE']['result'],'status':'UNKNOWN_SIDE_EFFECT',
            'gate_resume_safe':True,'continuation':state.records['CONTINUATION_SENT'],
            'reason':'CONTINUATION_SENT_WITHOUT_RECEIPT','automatic_replay':False}
    require(service.browser_provider is not None and service.browser_supervisor is not None,'G4_BROWSER_PROVIDER_REQUIRED')
    gate=gate_state(service,mid,gid);require(gate is not None,'G4_HUMAN_GATE_NOT_FOUND')
    goal=service._goal_id_for_gate(mid,gid)
    if goal:service.assert_goal_mutable(mid,goal,mutation='complete_human_takeover')
    if not state.intent:
        require(gate.status=='PENDING' and gate.gate_kind=='EXTERNAL_ACTION','G4_HUMAN_GATE_NOT_PENDING')
        takeover=service.state(mid).latest('HUMAN_TAKEOVER_REQUEST',lambda f:f.payload.get('human_gate_id')==gid)
        require(takeover is not None,'G4_HUMAN_TAKEOVER_NOT_FOUND')
        if takeover.payload.get('status')!='HUMAN_CONTROLLED':
            recovered=service.reconcile_human_takeover(mid,{'human_gate_id':gid})
            if recovered['status']!='WAITING_HUMAN':return recovered
            takeover=service.state(mid).latest('HUMAN_TAKEOVER_REQUEST',lambda f:f.payload.get('human_gate_id')==gid)
        mode=str(request.get('completion_mode') or 'EXPLICIT').upper()
        allowed=str(takeover.payload.get('resume_mode') or 'AUTO_OR_EXPLICIT').upper()
        require(mode in {'AUTO','EXPLICIT'} and allowed in {mode,'AUTO_OR_EXPLICIT'},'G4_HUMAN_COMPLETION_MODE_INVALID')
        cursor=service.recover_cursor(mid,root_attempt_id=gate.root_attempt_id)
        identity=str(request.get('operation_id') or 'auto-gate:'+canonical_sha256({'mission':mid,'gate':gid}))
        # Internal callers may name a decision; model-facing entry never forwards
        # a model decision ID and supplies its actual Host operation identity.
        decision=str(request.get('decision_id') or 'gate-resume:'+canonical_sha256(identity))
        context=dict(takeover.payload['browser_context_ref']);context['observed_lease_owner']='HUMAN'
        state=receipt.create({'mission_id':mid,'gate_id':gid,'task_id':gate.task_id,'root_attempt_id':gate.root_attempt_id,
            'origin_attempt_id':gate.origin_attempt_id,'takeover_ref':takeover.fact_id,'browser_context_ref':context,
            'decision_id':decision,'completion_mode':mode,'actor_id':str(request.get('actor_id') or 'g4-browser-supervisor'),
            'request_identity':identity,'cursor_ref':cursor['cursor']['fact_id'],'valid_until':request.get('valid_until')})
    if state.phase in {'REQUESTED','VERIFIED'} and state.intent['valid_until'] is not None and stamp(now())>stamp(state.intent['valid_until']):
        require(request.get('operation_id') and request['operation_id']!=state.intent['request_identity']
            and request.get('valid_until') and stamp(now())<stamp(request['valid_until']),'HOST_USER_TURN_EXPIRED')
        state=receipt.record('REAUTHORIZE',{'request_identity':request['operation_id'],'actor_id':request['actor_id'],
            'decision_id':'gate-resume:'+canonical_sha256(request['operation_id']),
            'valid_until':request['valid_until'],'observed_at':now()})
    intent=state.intent
    require((gate.task_id,gate.root_attempt_id,gate.origin_attempt_id)==
        (intent['task_id'],intent['root_attempt_id'],intent['origin_attempt_id']),'GATE_RESUME_LINEAGE_MISMATCH')
    takeover=service.state(mid).by_id(intent['takeover_ref']);require(takeover is not None,'GATE_RESUME_TAKEOVER_MISSING')
    context=intent['browser_context_ref'];ref=BrowserContextRef.from_dict(context)
    observed=service.browser_provider.inspect_context(ref)
    require(same_browser_context(context,observed.to_dict()),'G4_BROWSER_CONTEXT_REPLACED_DURING_HUMAN_CONTROL')
    owner=service.browser_provider.inspect_lease(ref).upper()
    mode=intent['completion_mode']
    # A canonical decision is inspected before any compensation or retry. An
    # exception from record_decision may occur after its transaction committed.
    if gate.decision_id is not None:
        require(gate.decision_id==intent['decision_id'] and gate.decision_outcome=='EXTERNAL_ACTION_COMPLETED'
            and gate.status=='RESOLVED','GATE_RESUME_FOREIGN_DECISION')
        require(state.phase in {'HAND_BACK_INTENT','DECIDED','RESUME_SAFE'},'GATE_RESUME_DECISION_WITHOUT_INTENT')
        require(owner=='AI','GATE_RESUME_COMMITTED_LEASE_RECONCILIATION_REQUIRED')
        if state.phase=='HAND_BACK_INTENT':state=receipt.record('DECIDED',{'decision_id':intent['decision_id']})
    else:
        require(gate.status=='PENDING','G4_HUMAN_GATE_NOT_PENDING')
        # A retired Attempt must not acquire a new Gate completion effect.
        latest=service.runtime.replay_composed(mid).extension_state('r1_3b_execution_resume').latest_attempt(gate.task_id)
        require(latest is not None and latest.root_attempt_id==gate.root_attempt_id,'GATE_RESUME_STALE_ATTEMPT')
        require(state.phase in {'REQUESTED','VERIFIED','HAND_BACK_INTENT'},'GATE_RESUME_PHASE_INVALID')
        if state.phase in {'REQUESTED','VERIFIED'}:
            verification=service.browser_supervisor.verify(mission_id=mid,browser_context_ref=ref,
                resume_condition=dict(takeover.payload.get('resume_condition') or {}),completion_mode=mode)
            state=receipt.record('VERIFIED',{'verification':verification})
            require_no_pending_control(service.runtime,mid)
            require(intent['valid_until'] is None or stamp(now())<=stamp(intent['valid_until']),'HOST_USER_TURN_EXPIRED')
            state=receipt.record('HAND_BACK_INTENT',{'verification':verification})
        # Fresh verification is repeated after a process restart. It is read-only;
        # known AI ownership reconciles the previous transfer without a second one.
        verification=service.browser_supervisor.verify(mission_id=mid,browser_context_ref=ref,
            resume_condition=dict(takeover.payload.get('resume_condition') or {}),completion_mode=mode,
            expected_owner=owner)
        require(owner in {'HUMAN','AI'},'G4_HUMAN_RESUME_LEASE_INVALID')
        require_no_pending_control(service.runtime,mid)
        if owner=='HUMAN':service.browser_provider.transfer_lease(ref,from_owner='HUMAN',to_owner='AI')
        ai=replace(ref,observed_lease_owner='AI')
        observed=service.browser_provider.inspect_context(ai)
        require(same_browser_context(context,observed.to_dict()) and service.browser_provider.inspect_lease(ai).upper()=='AI','G4_BROWSER_RECLAIM_VERIFICATION_FAILED')
        # Stable G4 lease fact persists actual handback for the production browser
        # adapter before the R2.6 decision; restart observes the same owner.
        _lease(service,mid,receipt,intent,observed.to_dict(),'AI_RECLAIMING','handback')
        service.human_gates.record_decision({'mission_id':mid,'gate_id':gid,'decision_id':intent['decision_id'],
            'outcome':'EXTERNAL_ACTION_COMPLETED','route':'NONE',
            'decision_payload':{'completion_mode':mode,'runtime_verification':verification,'caller_verification_authoritative':False},
            'decision_provenance':{'source_ref':verification['source_ref'],'source_digest':verification['evidence_digest'],'observed_at':verification['observed_at']},
            'actor':{'type':'USER' if mode=='EXPLICIT' else 'SYSTEM','id':intent['actor_id']}})
        state=receipt.record('DECIDED',{'decision_id':intent['decision_id']});gate=gate_state(service,mid,gid)
    if state.phase=='DECIDED':
        verification=gate.decision_payload['runtime_verification']
        lease=_lease(service,mid,receipt,intent,observed.to_dict(),'AI_CONTROLLED','ai')
        completed=_fact(service,mid,receipt,'completed','HUMAN_TAKEOVER_REQUEST',
            {**dict(takeover.payload),'browser_context_ref':lease['payload']['browser_context_ref'],'status':'RESUME_SAFE',
             'completion_mode':mode,'verification':verification,'caller_verification_authoritative':False,'sensitive_evidence_suppressed':True},
            (intent['takeover_ref'],lease['fact_id'],f'r2.6:{gid}'))
        recon=_fact(service,mid,receipt,'reconciliation','BROWSER_TAKEOVER_RECONCILIATION',
            {'gate_id':gid,'takeover_ref':completed['fact_id'],'status':'RESUME_COMPLETED','recoverable':False,
             'external_lease_owner':'AI','observed_at':verification['observed_at']},(lease['fact_id'],completed['fact_id']))
        binding=service.state(mid).latest('HUMAN_GATE_BINDING',lambda f:f.payload.get('gate_id')==gid)
        if binding is not None and binding.payload.get('mandatory') is True:
            status=service._goal_status_fact(mid,str(binding.payload['goal_id']))
            if status is None or status.payload.get('status')!='EXECUTING':
                service._set_goal_status(mid,str(binding.payload['goal_id']),'EXECUTING',reason='MANDATORY_HUMAN_GATE_COMPLETED',provenance_refs=(completed['fact_id'],))
        cursor=service.state(mid).by_id(intent['cursor_ref']);require(cursor is not None,'GATE_RESUME_CURSOR_MISSING')
        latest=service.runtime.replay_composed(mid).extension_state('r1_3b_execution_resume').latest_attempt(gate.task_id)
        require(latest is not None and latest.root_attempt_id==gate.root_attempt_id,'GATE_RESUME_STALE_ATTEMPT')
        result={'status':'RESUME_SAFE','truth_source':'R1_EVENT_STREAM','human_gate':gate.to_dict(),
            'browser_lease':lease,'takeover':completed,'reconciliation':recon,
            'cursor':{'payload':dict(cursor.payload),'cursor':cursor.to_dict()},
            'resume_attempt_id':latest.attempt_id,'root_attempt_id':gate.root_attempt_id}
        checkpoint=cursor.payload.get('last_safe_checkpoint');continuation=checkpoint.get('ui_journey_resume') if isinstance(checkpoint,dict) else None
        if continuation:continuation={**continuation,'attempt_id':latest.attempt_id}
        state=receipt.record('RESUME_SAFE',{'result':result,'continuation':continuation})
    result=dict(state.records['RESUME_SAFE']['result']);continuation=state.records['RESUME_SAFE']['continuation']
    if continuation:
        require_no_pending_control(service.runtime,mid)
        digest=canonical_sha256(continuation)
        effect='gate-continuation:'+canonical_sha256({'subject':state.subject_id,'request':digest})
        receipt.record('CONTINUATION_SENT',{'effect_id':effect,'request_digest':digest})
        # No catch converts a lost physical result to a retry. The durable SENT
        # record survives process death even before the provider returns.
        with continuation_permit(service.runtime,state.subject_id,continuation):
            result['ui_continuation']=service.execute_capability(mid,continuation)
        if result['ui_continuation'].get('status') in {'UNKNOWN_SIDE_EFFECT','RECONCILE_REQUIRED'}:
            return {**result,'status':'UNKNOWN_SIDE_EFFECT','gate_resume_safe':True,'automatic_replay':False}
    receipt.record('COMPLETED',{'result':result})
    return result


def _fact(service,mid,receipt,suffix,kind,payload,refs):
    fid='g4:gate-resume:'+canonical_sha256(receipt.subject.subject_id)+':'+suffix
    old=service.state(mid).by_id(fid)
    if old is not None:return old.to_dict()
    return service._record(mid,kind,payload,provenance_refs=refs,fact_id=fid)


def _lease(service,mid,receipt,intent,observed,state,suffix):
    return _fact(service,mid,receipt,'lease-'+suffix,'BROWSER_LEASE',
        {'lease_id':f"lease:{intent['gate_id']}:{suffix}",'browser_context_ref':observed,'state':state,'owner':'AI',
         'attempt_id':intent['origin_attempt_id'],'root_attempt_id':intent['root_attempt_id'],'task_id':intent['task_id']},
        (intent['takeover_ref'],f"r2.6:{intent['gate_id']}"))


# One ephemeral owner permit admits exactly the already-journaled continuation.
# It is never serialized, accepted from model input, or inherited across threads.
from contextvars import ContextVar
from contextlib import contextmanager, closing
import sqlite3
_continuation_permit=ContextVar('gate_continuation_permit',default=None)

@contextmanager
def continuation_permit(runtime,subject_id,request):
    token=_continuation_permit.set((str(runtime.db_path),subject_id,canonical_sha256(request)))
    try:yield
    finally:_continuation_permit.reset(token)

def require_no_unknown_continuation(runtime,mid,request):
    from .human_gate_resume_receipts import KIND
    from .durable_core import SubjectRef
    sql="""SELECT e.mission_id FROM events e WHERE e.event_type='human_gate_resume.created.v1'
        AND json_extract(e.payload_json,'$.intent.mission_id')=?
        AND EXISTS (SELECT 1 FROM events s WHERE s.mission_id=e.mission_id
            AND s.event_type='human_gate_resume.recorded.v1' AND json_extract(s.payload_json,'$.operation')='CONTINUATION_SENT')
        AND NOT EXISTS (SELECT 1 FROM events d WHERE d.mission_id=e.mission_id
            AND d.event_type='human_gate_resume.recorded.v1' AND json_extract(d.payload_json,'$.operation')='COMPLETED')"""
    with closing(sqlite3.connect(runtime.db_path)) as conn:rows=conn.execute(sql,(mid,)).fetchall()
    permit=_continuation_permit.get()
    for row in rows:
        state=runtime.get_subject_state(SubjectRef(KIND,row[0])).root_state
        expected=(str(runtime.db_path),row[0],canonical_sha256(request))
        require(len(rows)==1 and permit==expected and state.records['CONTINUATION_SENT']['request_digest']==expected[2],'UNKNOWN_SIDE_EFFECT_RECONCILIATION_REQUIRED')
    if rows:_continuation_permit.set(None) # exactly one physical entry
