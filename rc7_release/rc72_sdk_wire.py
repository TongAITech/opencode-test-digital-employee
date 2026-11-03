"""Owned, bounded SDK stdio transport for one fresh Worker turn.

This is a wire seam, not a model-readiness receipt or a Worker evidence adapter.
It preserves native messages; enqueue/wait never manufacture business completion.
"""
import json
from pathlib import Path
import queue
import re
import subprocess
import threading
import time


class SDKWireError(RuntimeError):
    def __init__(self, code, *, prompt_may_have_been_enqueued=False):
        super().__init__(code)
        self.prompt_may_have_been_enqueued = prompt_may_have_been_enqueued


class OwnedSDKWire:
    """No retries, shared runtime, implicit home or ambient-environment fallback.

    Caller owns the native Worker lease, selected scoped environment and command.
    A poisoned client cannot send more work. Close always reaps its direct child.
    """
    def __init__(self, command, *, cwd, environment, timeout_seconds=10,
                 max_frame_bytes=2097152, max_frames=4096, max_total_bytes=16777216):
        if (not isinstance(command, (list, tuple)) or not command
                or any(not isinstance(x, str) or not x or '\0' in x for x in command)
                or not isinstance(environment, dict)
                or any(not isinstance(k, str) or not re.fullmatch('[A-Za-z_][A-Za-z0-9_]*',k)
                       or not isinstance(v, str) or '\0' in v for k,v in environment.items())
                or not environment.get('DSH_HOME')
                or not isinstance(timeout_seconds, (int,float)) or isinstance(timeout_seconds,bool)
                or not 0 < timeout_seconds <= 300
                or not isinstance(max_frame_bytes,int) or isinstance(max_frame_bytes,bool) or not 1024 <= max_frame_bytes <= 8388608
                or not isinstance(max_frames,int) or isinstance(max_frames,bool) or not 1 <= max_frames <= 16384
                or not isinstance(max_total_bytes,int) or isinstance(max_total_bytes,bool)
                or not max_frame_bytes <= max_total_bytes <= 134217728):
            raise SDKWireError('MISSION_SDK_EXPLICIT_PROCESS_CONFIGURATION_REQUIRED')
        self.timeout=float(timeout_seconds)
        self.max_frame_bytes=max_frame_bytes
        self.max_frames=max_frames
        self.max_total_bytes=max_total_bytes
        self._cwd=str(Path(cwd).resolve())
        self.frames=[]
        self._messages=queue.Queue(maxsize=max_frames)
        self._overflow=threading.Event()
        self._closed=False
        self._poisoned=False
        self._initialized=False
        self._submitted=False
        self._message_id=None
        self._session_id=None
        self._next_id=0
        self._stderr_bytes=0
        try:
            self.proc=subprocess.Popen(list(command), cwd=str(Path(cwd).resolve()),
                env=dict(environment), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, shell=False, bufsize=0)
        except OSError:
            raise SDKWireError('MISSION_SDK_PROCESS_START_FAILED') from None
        self._readers=[threading.Thread(target=self._read_stdout,daemon=True),
                       threading.Thread(target=self._drain_stderr,daemon=True)]
        for reader in self._readers:reader.start()

    def _enqueue(self,value):
        try:self._messages.put_nowait(value)
        except queue.Full:self._overflow.set()

    def _read_stdout(self):
        total=0
        try:
            while True:
                raw=self.proc.stdout.readline(self.max_frame_bytes+1)
                if not raw:break
                total+=len(raw)
                if len(raw)>self.max_frame_bytes or total>self.max_total_bytes:
                    self._overflow.set();break
                try:message=json.loads(raw.decode('utf-8'))
                except (UnicodeError,ValueError):
                    self._enqueue(('invalid',None));continue
                self._enqueue(('message',message))
        except (OSError,ValueError):pass
        finally:self._enqueue(('eof',None))

    def _drain_stderr(self):
        # Never retain/print provider error text, which can contain credentials.
        try:
            while True:
                raw=self.proc.stderr.read(4096)
                if not raw:return
                self._stderr_bytes+=len(raw)
        except (OSError,ValueError):pass

    def _fail(self,code):
        self._poisoned=True
        raise SDKWireError(code,prompt_may_have_been_enqueued=self._submitted)

    def _request(self,method,params=None,*,marks_prompt=False):
        if self._closed or self._poisoned:self._fail('MISSION_SDK_CLIENT_UNUSABLE')
        self._next_id+=1
        request=dict(jsonrpc='2.0',id=self._next_id,method=method)
        if params is not None:request['params']=params
        raw=(json.dumps(request,ensure_ascii=False,allow_nan=False)+'\n').encode('utf-8')
        if len(raw)>self.max_frame_bytes:self._fail('MISSION_SDK_REQUEST_SIZE_EXCEEDED')
        if marks_prompt:self._submitted=True
        deadline=time.monotonic()+self.timeout
        write_error=[]
        def write():
            try:
                offset=0
                while offset<len(raw):
                    count=self.proc.stdin.write(raw[offset:])
                    if not count:raise OSError('closed pipe')
                    offset+=count
                self.proc.stdin.flush()
            except (OSError,ValueError):write_error.append(True)
        writer=threading.Thread(target=write,daemon=True)
        self._readers.append(writer)
        writer.start();writer.join(timeout=self.timeout)
        if writer.is_alive():self._fail('MISSION_SDK_REQUEST_TIMEOUT')
        if write_error:self._fail('MISSION_SDK_TRANSPORT_LOST')
        invalid=0
        while True:
            if self._overflow.is_set():self._fail('MISSION_SDK_WIRE_LIMIT_EXCEEDED')
            remaining=deadline-time.monotonic()
            if remaining<=0:self._fail('MISSION_SDK_REQUEST_TIMEOUT')
            try:kind,message=self._messages.get(timeout=min(remaining,0.1))
            except queue.Empty:continue
            if self._overflow.is_set():self._fail('MISSION_SDK_WIRE_LIMIT_EXCEEDED')
            if kind=='eof':self._fail('MISSION_SDK_TRANSPORT_LOST')
            if kind=='invalid':
                invalid+=1
                if invalid>32:self._fail('MISSION_SDK_INVALID_FRAME_LIMIT')
                continue
            if not isinstance(message,dict) or message.get('jsonrpc')!='2.0':
                self._fail('MISSION_SDK_PROTOCOL_INVALID')
            if len(self.frames)>=self.max_frames:self._fail('MISSION_SDK_WIRE_LIMIT_EXCEEDED')
            self.frames.append(message)
            if 'method' in message:
                if 'id' in message:
                    # No fabricated approval, user answer or implicit privilege.
                    self._fail('MISSION_SDK_HOST_DECISION_REQUIRED')
                continue
            if type(message.get('id')) is not int or message['id']!=request['id']:
                self._fail('MISSION_SDK_RESPONSE_ID_MISMATCH')
            if 'error' in message:self._fail('MISSION_SDK_REQUEST_REFUSED')
            if 'result' not in message:self._fail('MISSION_SDK_RESULT_REQUIRED')
            return message['result']

    def initialize(self,*,provider,model):
        if self._initialized or self._submitted:self._fail('MISSION_SDK_INITIALIZE_ONCE_REQUIRED')
        if any(not isinstance(x,str) or not x or '\0' in x or x.strip()!=x for x in (provider,model)):
            self._fail('MISSION_SDK_EXACT_MODEL_ROUTE_REQUIRED')
        result=self._request('initialize',dict(cwd=self._cwd,
            provider=provider,model=model,approvalRequests=True))
        info=result.get('serverInfo') if isinstance(result,dict) else None
        if (not isinstance(info,dict) or info.get('name')!='deepseek-harness-sdk-runtime'
                or not isinstance(info.get('version'),str) or not info['version']):
            self._fail('MISSION_SDK_SERVER_IDENTITY_REQUIRED')
        self._initialized=True
        return result

    def enqueue_text(self,*,session_id,text):
        if not self._initialized or self._submitted:self._fail('MISSION_SDK_SINGLE_FRESH_TURN_REQUIRED')
        if any(not isinstance(x,str) or not x or '\0' in x for x in (session_id,text)):
            self._fail('MISSION_SDK_SESSION_AND_PROMPT_REQUIRED')
        self._session_id=session_id
        # Mark immediately before the write, after local size validation: an
        # interrupted write/response is not replayable, even without a receipt.
        result=self._request('session/prompt',dict(sessionId=session_id,contentBlocks=[dict(type='text',text=text)]),marks_prompt=True)
        if not isinstance(result,dict) or not isinstance(result.get('messageId'),str) or not result['messageId']:
            self._fail('MISSION_SDK_DURABLE_ENQUEUE_RECEIPT_REQUIRED')
        self._message_id=result['messageId']
        return self._message_id

    def wait(self):
        if self._message_id is None:self._fail('MISSION_SDK_ENQUEUE_RECEIPT_REQUIRED')
        result=self._request('session/wait',dict(sessionId=self._session_id))
        if result!={}:self._fail('MISSION_SDK_WAIT_RESULT_INVALID')
        # Native inbox splicing, assistant final, tool calls and usage still need
        # independent Worker-side validation. This is only the native wait result.
        return tuple(self.frames)

    def close(self):
        if self._closed:return
        if self._initialized and not self._poisoned and self.proc.poll() is None:
            original=self.timeout
            self.timeout=min(original,1.0)
            try:self._request('shutdown')
            except SDKWireError:pass
            finally:self.timeout=original
        self._closed=True
        if self.proc.poll() is None:
            try:self.proc.wait(timeout=0.25)
            except subprocess.TimeoutExpired:
                self.proc.terminate()
                try:self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.proc.kill();self.proc.wait(timeout=5)
        for pipe in (self.proc.stdin,self.proc.stdout,self.proc.stderr):
            if pipe is not None:pipe.close()
        for reader in self._readers:reader.join(timeout=1)

    def __enter__(self):return self

    def __exit__(self,*_):self.close()
