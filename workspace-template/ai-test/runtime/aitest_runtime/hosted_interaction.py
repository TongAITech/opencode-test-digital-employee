"""Product entry composition for model proposals, host admission and R1 receipts."""
from __future__ import annotations
import time
from typing import Any, Mapping

from .hosted_intake import actual_host_user_turn, validate_host_payload
from .interaction_admission import (AdmissionError, Intent, clauses, decide,
    literal_start_proposal, mission_intake, parse_proposal)


def _execution_summary(value: Mapping[str, Any]) -> dict[str, Any]:
    # G2.1 returns internal provisioning metadata. Completion receipts and the
    # Primary need bounded status/identity, never copies of tokens or capsules.
    allowed = {'status','mission_id','session_id','logical_agent_id','task_id','attempt_id','reason','prompt_sent'}
    return {key:value[key] for key in allowed if key in value and
            isinstance(value[key],(str,int,bool)) and len(str(value[key]).encode())<=1024}


def hosted_interaction(service: Any, payload: Mapping[str, Any], *, action: str = 'interact',
                       owner: Any = None, now_ms: int | None = None) -> dict[str, Any]:
    clock_ms = (lambda: int(time.time()*1000)) if now_ms is None else (lambda: now_ms)
    now_ms = clock_ms()
    provider = getattr(service, 'raw_session_provider', service.session_provider)
    turn = actual_host_user_turn(provider, now_ms=now_ms)
    validate_host_payload(payload, turn)
    base = {'truth_source':'R1_EVENT_STREAM','host_turn_ref':turn.provenance(),
            'semantic_proposal_is_authority':False,'operations':[]}
    proposal = payload.get('proposal')
    if proposal is None and action == 'start_test':
        proposal = literal_start_proposal(turn,payload.get('scope'))
    elif proposal is None and action == 'continue_test':
        slots = clauses(turn.text)
        if len(slots) != 1: raise AdmissionError('MIXED_TURN_REQUIRES_SEMANTIC_PROPOSAL')
        proposal = {'operations':[{'intent':'MISSION_CONTROL','action':'continue',
                                  'start':slots[0]['start'],'end':slots[0]['end'],
                                  'scope':dict(payload.get('scope') or {})}]}
    if proposal is None:
        return {**base,'status':'SEMANTIC_PROPOSAL_REQUIRED','clauses':list(clauses(turn.text)),
                'intent_classes':[i.value for i in Intent],
                'reason':'The host model proposes intent/action for every complete clause; Runtime independently admits effects.'}
    operations = parse_proposal(proposal, turn)
    if owner is None:
        from .interaction_receipts import R1InteractionOwner
        try: owner = R1InteractionOwner(service.runtime)
        except (ImportError, AttributeError) as exc:
            return {**base,'status':'BLOCKED','reason':'INTERACTION_R1_OWNER_UNAVAILABLE'}
        # Registration/core failures are not replaced by another persistence layer.
    candidates = owner.candidates(turn)
    decisions = [decide(turn, operation,candidates,now_ms=now_ms) for operation in operations]
    # Pause/stop is never queued behind a new start in the same mixed turn.
    decisions.sort(key=lambda d: 0 if d['action'] in {'pause','stop','stop_runtime'} else 1)
    results = []
    for admitted in decisions:
        item = dict(admitted)
        if admitted['intent'] in {'GENERAL_WORK','AITEST_DIAGNOSIS'} and admitted['status']=='DELEGATION_REQUIRED':
            if clock_ms() > turn.expires_ms:
                item.update(status='BLOCKED',reason='HOST_USER_TURN_EXPIRED')
                results.append(item); continue
            try:
                from .general_work.execution import GeneralExecutionService
            except ModuleNotFoundError as exc:
                if exc.name != 'aitest_runtime.general_work.execution':raise
                item.update(status='BLOCKED',reason='GENERAL_EXECUTION_OWNER_UNAVAILABLE')
                results.append(item); continue
            verified_operation={**admitted,'operation_text':turn.text[admitted['proposal']['start']:admitted['proposal']['end']]}
            worker_result=GeneralExecutionService(service.runtime,service.workspace_root,
                session_provider=provider).start(verified_operation,owner)
            # The typed owner decides policy and durable replay. Preserve its
            # status; a routing proposal is never relabeled as successful work.
            item.update(status=worker_result['status'],result=worker_result)
            item.pop('execution_authorized',None)
            item.pop('reason',None)
            if 'subject' in worker_result:item['subject']=worker_result['subject']
            results.append(item);continue
        # Controls contain only an R1 state transition. A crash after that
        # transition can be reconciled from its durable command receipt without
        # repeating provider work. This is narrower than start/dispatch recovery.
        if admitted['intent']=='MISSION_CONTROL' and admitted['action'] in {'pause','stop','continue'} and (
                admitted['status']=='ADMITTED' or owner.receipt(admitted['operation_id'])):
            if clock_ms() > turn.expires_ms:
                item.update(status='BLOCKED',reason='HOST_USER_TURN_EXPIRED')
            else:
                from .mission_controls import apply_control
                try:item.update(apply_control(service,owner,admitted))
                except Exception as exc:item.update(status='RECONCILE_REQUIRED',reason=getattr(exc,'code',type(exc).__name__))
            results.append(item);continue
        prior = owner.receipt(admitted['operation_id'])
        if prior:
            # Replay the canonical original resolution. New candidates may have
            # appeared since creation; model proposal and host binding must still
            # match every immutable claim field. A changed request never replays.
            replay_request = {**admitted,'subject':prior['subject'],'resolved_scope':prior['resolved_scope']}
            claimed = owner.claim(replay_request)
            item.update(status='REPLAYED' if claimed['state']=='COMPLETED' else 'RECONCILE_REQUIRED',
                        reason='OPERATION_ALREADY_CONSUMED',subject=claimed['bound_subject'] or claimed['subject'],
                        result=claimed.get('result'))
            results.append(item); continue
        if admitted['status'] != 'ADMITTED':
            results.append(item); continue
        if admitted['intent'] == 'MISSION_QUERY':
            item['result'] = service.status(admitted['subject']['subject_id'])
            from .mission_controls import pending_controls
            item['result']['pending_controls'] = [{'operation_id':r['operation_id'],'action':r['action']} for r in pending_controls(service.runtime,mission_id=admitted['subject']['subject_id'],limit=16)]
            results.append(item); continue
        if admitted['intent'] != 'TEST_MISSION_START' and not (admitted['intent'] == 'MISSION_CONTROL' and admitted['action'] == 'continue'):
            item.update(status='BLOCKED',reason='TYPED_OPERATION_EXECUTOR_REQUIRED')
            results.append(item); continue
        # A control operation lacking an executor must not let a following start
        # undermine the requested pause/stop.
        if any(d['action'] in {'pause','stop','stop_runtime'} and d['status'] in {'ADMITTED','OWNER_ADMISSION_REQUIRED'}
               and not any(r['operation_id']==d['operation_id'] and r['status'] in {'COMPLETED','REPLAYED'} for r in results) for d in decisions):
            item.update(status='BLOCKED',reason='PREEMPTING_CONTROL_MUST_COMPLETE_FIRST')
            results.append(item); continue
        if clock_ms() > turn.expires_ms:
            item.update(status='BLOCKED',reason='HOST_USER_TURN_EXPIRED')
            results.append(item); continue
        claimed = owner.claim(admitted)
        if not claimed['fresh']:
            item.update(status='REPLAYED' if claimed['state']=='COMPLETED' else 'RECONCILE_REQUIRED',
                        reason='OPERATION_ALREADY_CONSUMED',result=claimed.get('result'))
            results.append(item); continue
        operation_id = admitted['operation_id']
        try:
            subject = admitted['subject']
            intake = None
            if subject is None:
                # R2.2 uses the runtime operation ID as its own durable intake
                # idempotency key. No raw model intake/source envelope is accepted.
                request = mission_intake(turn,admitted)
                intake = service.intake_mission(request)
                subject = {'subject_kind':'MISSION','subject_id':intake['intake']['mission_id']}
            owner.bind(operation_id,subject)
            if clock_ms() > turn.expires_ms:
                raise AdmissionError('HOST_USER_TURN_EXPIRED')
            next_result = service.continue_test(mission_id=subject['subject_id'])
            result = {'status':next_result.get('status','DISPATCHED'),'truth_source':'R1_EVENT_STREAM',
                      'mission_id':subject['subject_id'],'intake':_execution_summary(intake) if intake else None,
                      'next':_execution_summary(next_result),
                      'resumed_existing_mission':admitted['subject'] is not None}
            owner.complete(operation_id,result)
            item.update(status='DISPATCHED',execution_authorized=True,subject=subject,result=result)
        except BaseException as exc:
            # A possible external session/dispatch effect is not blindly retried.
            # Abrupt process death leaves CLAIMED/BOUND, which also blocks replay.
            reason = getattr(exc,'code',type(exc).__name__)
            try: owner.uncertain(operation_id,reason)
            except Exception: pass
            if not isinstance(exc,Exception): raise
            item.update(status='RECONCILE_REQUIRED',reason=reason)
        results.append(item)
    return {**base,'status':'INTERACTION_PROCESSED','operations':results}
