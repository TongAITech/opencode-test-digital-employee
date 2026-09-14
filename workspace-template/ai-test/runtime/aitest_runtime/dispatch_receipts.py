"""Runtime-owned prompt delivery journal; R1 is authority, locks only coordinate."""
from __future__ import annotations
import hashlib
import json
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path

class ContextDeliveryUnconfirmed(RuntimeError):
    """A prior send may have reached the host; never rotate/reissue implicitly."""

class CoordinationBusy(RuntimeError):
    pass

_locks = {}
_guard = threading.Lock()
_owned = threading.local()

@contextmanager
def runtime_coordination(db_path, timeout=5):
    key=str(Path(db_path).resolve())
    with _guard: lock=_locks.setdefault(key,threading.RLock())
    if not lock.acquire(timeout=timeout):raise CoordinationBusy('RUNTIME_COORDINATION_BUSY')
    owned=getattr(_owned,'keys',set())
    handle=None
    try:
        if key in owned:
            yield;return
        # Contains no scheduling/job state and is never used as a recovery truth.
        path=Path(key).with_suffix('.coordination.lock');handle=open(path,'a+b')
        handle.seek(0,2)
        if handle.tell()==0:handle.write(b'0');handle.flush()
        deadline=time.monotonic()+timeout
        while True:
            try:
                if os.name=='nt':
                    import msvcrt
                    handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                break
            except (OSError,BlockingIOError):
                if time.monotonic()>=deadline:raise CoordinationBusy('RUNTIME_COORDINATION_BUSY')
                time.sleep(.02)
        _owned.keys=owned|{key}
        try:yield
        finally:
            _owned.keys=owned
            if os.name=='nt':
                import msvcrt
                handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(),fcntl.LOCK_UN)
    finally:
        if handle:handle.close()
        lock.release()

def business_cursor(runtime, mission_id):
    """Latest durable semantic progress; control-loop output is not progress."""
    g4_control_kinds = {"GOAL_EVALUATION", "TESTING_GOAL_STATUS", "REPLAN_REQUEST"}
    latest = 0
    for event in runtime.list_events(mission_id):
        et = str(event.event_type)
        relevant = et.startswith((
            "plan.created.",
            "plan.revision_recorded.",
            "plan.revision_activated.",
            "task.outcome_recorded.",
            "g3.",
            "r3.",
            "r4.",
        ))
        if et == "g4.fact_recorded.v1":
            fact_kind = str((event.payload or {}).get("fact_kind") or "")
            relevant = fact_kind not in g4_control_kinds
        elif et.startswith("g4."):
            # Unknown G4 control/event shapes are not allowed to reset retry
            # budgets until explicitly classified as semantic input.
            relevant = False
        if relevant:
            latest = max(latest, int(event.seq))
    return latest

def reconcile_context_receipt(service, mission_id, prior):
    reader=getattr(service.raw_session_provider,'find_context_receipt',None)
    receipt=reader(prior['session_id'],prior['context_digest']) if callable(reader) else None
    if not receipt:return False
    payload={k:prior[k] for k in ('dispatch_id','session_id','context_digest','mode','business_cursor')}
    service.session_control.record_context_dispatch(mission_id,{**payload,'phase':'ACCEPTED','host_receipt':receipt})
    return True

def dispatch_context(service, *,session_id,agent,text,mode='INITIAL',cursor=None):
    try:envelope=json.loads(text.split('\n',1)[1]);mission_id=envelope['mission_id']
    except (ValueError,KeyError,IndexError,TypeError) as exc:raise RuntimeError('G21_CONTEXT_ENVELOPE_REQUIRED') from exc
    runtime=service.runtime
    with runtime_coordination(runtime.db_path):
        from .mission_session_authority import MissionSessionOwner
        MissionSessionOwner(service).before_dispatch(mission_id,session_id,agent)
        if mode not in {'INITIAL','AUTO_CONTINUE'}:raise ValueError('G21_DISPATCH_MODE_INVALID')
        cursor=business_cursor(runtime,mission_id) if cursor is None else cursor
        identity={'mission_id':mission_id,'session_id':session_id,'mode':mode}
        if mode=='AUTO_CONTINUE':identity['business_cursor']=cursor
        did='g21:context:'+hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()[:40]
        # Distinguish an actual wake from an older identical-looking bootstrap.
        # Its unique identity is present in the bytes retrieved from the Host.
        envelope['runtime_dispatch_id']=did
        text=text.split('\n',1)[0]+'\n'+json.dumps(envelope,ensure_ascii=False,sort_keys=True)
        if len(text.encode())>16384:raise RuntimeError('G21_FINAL_BOOTSTRAP_BYTE_BUDGET')
        prior=service.session_control.state(mission_id).context_dispatch(did)
        if prior:
            if prior['phase']=='ACCEPTED':return {'accepted':True,'status':'ALREADY_ACCEPTED','dispatch_id':did,'prompt_sent':False}
            if reconcile_context_receipt(service,mission_id,prior):
                return {'accepted':True,'status':'HOST_RECEIPT_RECONCILED','dispatch_id':did,'prompt_sent':False}
            raise ContextDeliveryUnconfirmed('CONTEXT_DELIVERY_UNCONFIRMED:'+did)
        payload={'dispatch_id':did,'session_id':session_id,'context_digest':hashlib.sha256(text.encode()).hexdigest(),
                 'phase':'CLAIMED','mode':mode,'business_cursor':cursor}
        service.session_control.record_context_dispatch(mission_id,payload)
        try:
            response=service.raw_session_provider.send_context(session_id=session_id,agent=agent,text=text)
        except Exception as exc:
            # A transport exception is ambiguous. Persist the state when possible;
            # a crash before this receipt leaves CLAIMED, which is equally fenced.
            try:service.session_control.record_context_dispatch(mission_id,{**payload,'phase':'UNKNOWN'})
            except Exception:pass
            raise ContextDeliveryUnconfirmed('CONTEXT_DELIVERY_UNCONFIRMED:'+did) from exc
        service.session_control.record_context_dispatch(mission_id,{**payload,'phase':'ACCEPTED'})
        return {**dict(response or {}),'accepted':True,'dispatch_id':did,'prompt_sent':True}
