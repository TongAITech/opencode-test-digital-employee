"""Actual subprocess wire protocol only; no vendor SDK install or model calls."""
import json
from pathlib import Path
import sys
import time

import pytest
from rc6_runtime.process_environment import scoped_process_environment
from rc7_release.rc72_sdk_wire import OwnedSDKWire,SDKWireError


SERVER='''import json,sys,time
from pathlib import Path
mode,log=sys.argv[1:]
def send(value):
 print(json.dumps(value),flush=True)
for raw in sys.stdin:
 r=json.loads(raw)
 with open(log,'a') as f:f.write(json.dumps(r)+'\\n')
 method=r['method']
 if method=='initialize':
  if mode=='init-timeout':time.sleep(5)
  if mode=='refuse':
   send(dict(jsonrpc='2.0',id=r['id'],error=dict(code=-32603,message='private-provider-token')));continue
  name='wrong-runtime' if mode=='identity' else 'deepseek-harness-sdk-runtime'
  result=dict(serverInfo=dict(name=name,version='engineering-1'))
 elif method=='session/prompt':
  if mode in ('prompt-timeout','blocked-stdin'):time.sleep(5)
  if mode=='host-request':
   send(dict(jsonrpc='2.0',id=999,method='approval/request',params=dict(toolName='dangerous-tool')));time.sleep(5)
  if mode=='oversized':
   print('x'*4096,flush=True);time.sleep(5)
  if mode=='flood':
   for i in range(1000):send(dict(jsonrpc='2.0',method='session.status',params=dict(sessionId='engineering-session',status='running')))
   time.sleep(5)
  send(dict(jsonrpc='2.0',method='session.event',params=dict(sessionId=r['params']['sessionId'],event=dict(type='engineering-native-event',payload='unaltered'))))
  result={} if mode=='no-receipt' else dict(messageId='native-queued-message')
 elif method=='session/wait':
  if mode=='wait-timeout':time.sleep(5)
  send(dict(jsonrpc='2.0',method='session.status',params=dict(sessionId=r['params']['sessionId'],status='idle')))
  result={}
 elif method=='shutdown':
  send(dict(jsonrpc='2.0',id=r['id'],result={}));break
 else:result={}
 send(dict(jsonrpc='2.0',id=True if mode=='boolean-id' else r['id']+1 if mode=='wrong-id' else r['id'],result=result))
 if mode=='blocked-stdin' and method=='initialize':time.sleep(5)
'''


def _client(tmp_path,mode='normal',**kwargs):
    script=tmp_path/'sdk-protocol-fixture.py';script.write_text(SERVER)
    log=tmp_path/'requests.jsonl'
    home=tmp_path/'private-worker-home'
    environment=scoped_process_environment(home=home)
    environment['DSH_HOME']=str(home/'.dsh')
    client=OwnedSDKWire([sys.executable,str(script),mode,str(log)],cwd=tmp_path,
        environment=environment,timeout_seconds=kwargs.pop('timeout_seconds',2),**kwargs)
    return client,log


def _requests(log):
    return [json.loads(x) for x in log.read_text().splitlines()] if log.exists() else []


def test_exact_route_native_enqueue_receipt_wait_frames_and_owned_shutdown(tmp_path):
    client,log=_client(tmp_path)
    with client:
        assert client.initialize(provider='approved-provider',model='approved-model')['serverInfo']['version']=='engineering-1'
        assert client.enqueue_text(session_id='fresh-native-worker',text='Do original work')=='native-queued-message'
        frames=client.wait()
        event=next(x for x in frames if x.get('method')=='session.event')
        assert event['params']==dict(sessionId='fresh-native-worker',event=dict(type='engineering-native-event',payload='unaltered'))
        # A wire wait produces no candidate/PASS/model-auth receipt.
        assert not hasattr(client,'field_verified')
    requests=_requests(log)
    assert [x['method'] for x in requests]==['initialize','session/prompt','session/wait','shutdown']
    assert requests[0]['params']==dict(cwd=str(tmp_path.resolve()),provider='approved-provider',model='approved-model',approvalRequests=True)
    assert requests[1]['params']==dict(sessionId='fresh-native-worker',contentBlocks=[dict(type='text',text='Do original work')])
    assert client.proc.poll() is not None and all(not t.is_alive() for t in client._readers)


@pytest.mark.parametrize('mode,code',[('identity','SERVER_IDENTITY'),('refuse','REQUEST_REFUSED'),
    ('wrong-id','RESPONSE_ID_MISMATCH'),('boolean-id','RESPONSE_ID_MISMATCH'),('init-timeout','REQUEST_TIMEOUT')])
def test_bad_handshake_never_enqueues_prompt_or_reveals_server_error(tmp_path,mode,code):
    client,log=_client(tmp_path,mode,timeout_seconds=0.2 if mode=='init-timeout' else 2)
    with client:
        with pytest.raises(SDKWireError,match=code) as error:
            client.initialize(provider='approved',model='exact')
        assert not error.value.prompt_may_have_been_enqueued
        assert 'private-provider-token' not in str(error.value)
        with pytest.raises(SDKWireError,match='UNUSABLE'):
            client._request('session/prompt',{})
    assert [x['method'] for x in _requests(log)]==['initialize']
    assert client.proc.poll() is not None


@pytest.mark.parametrize('mode,code',[('no-receipt','ENQUEUE_RECEIPT'),('prompt-timeout','REQUEST_TIMEOUT'),
    ('wait-timeout','REQUEST_TIMEOUT'),('host-request','HOST_DECISION_REQUIRED'),
    ('oversized','WIRE_LIMIT'),('flood','WIRE_LIMIT'),('blocked-stdin','REQUEST_TIMEOUT')])
def test_uncertain_prompt_never_retries_and_owns_process_cleanup(tmp_path,mode,code):
    client,log=_client(tmp_path,mode,timeout_seconds=2,max_frame_bytes=1024 if mode=='oversized' else 2097152,
        max_frames=4 if mode=='flood' else 4096)
    started=time.monotonic()
    with client:
        client.initialize(provider='approved',model='exact')
        client.timeout=0.2
        with pytest.raises(SDKWireError,match=code) as error:
            client.enqueue_text(session_id='fresh-worker',text='x'*500000 if mode=='blocked-stdin' else 'approved work')
            client.wait()
        assert error.value.prompt_may_have_been_enqueued
        with pytest.raises(SDKWireError):client.enqueue_text(session_id='different-worker',text='must not replay')
    assert time.monotonic()-started<4
    assert len([x for x in _requests(log) if x['method']=='session/prompt'])<=1
    assert not any(x.get('result',{}).get('outcome')=='allowed-once' for x in _requests(log))
    assert client.proc.poll() is not None and all(not t.is_alive() for t in client._readers)


def test_missing_explicit_home_is_rejected_before_process_start(tmp_path):
    with pytest.raises(SDKWireError,match='EXPLICIT_PROCESS'):
        OwnedSDKWire([sys.executable,'-c','raise RuntimeError("must not run")'],cwd=tmp_path,environment={})


def test_total_wire_budget_is_bounded_independently_of_frame_and_queue_limits(tmp_path):
    client,log=_client(tmp_path,'flood',timeout_seconds=2,max_frame_bytes=1024,
        max_total_bytes=2048,max_frames=4096)
    with client:
        client.initialize(provider='approved',model='exact')
        with pytest.raises(SDKWireError,match='WIRE_LIMIT'):
            client.enqueue_text(session_id='fresh-worker',text='original')
            client.wait()
    assert client.proc.poll() is not None
    assert len([r for r in _requests(log) if r['method']=='session/prompt'])==1


def test_prompt_cannot_precede_exact_route_initialization(tmp_path):
    client,log=_client(tmp_path)
    with client:
        with pytest.raises(SDKWireError,match='SINGLE_FRESH_TURN') as error:
            client.enqueue_text(session_id='fresh-worker',text='must not enqueue')
        assert not error.value.prompt_may_have_been_enqueued
    assert not _requests(log) and client.proc.poll() is not None


def test_local_prompt_size_refusal_does_not_claim_possible_enqueue(tmp_path):
    client,log=_client(tmp_path,max_frame_bytes=1024)
    with client:
        client.initialize(provider='approved',model='exact')
        with pytest.raises(SDKWireError,match='REQUEST_SIZE') as error:
            client.enqueue_text(session_id='fresh-worker',text='x'*2048)
        assert not error.value.prompt_may_have_been_enqueued
    assert [r['method'] for r in _requests(log)]==['initialize']
