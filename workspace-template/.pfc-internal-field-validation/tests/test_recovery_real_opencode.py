"""Actual pinned OpenCode server + automatic rotation; synthetic no-reply content, no model/bank pass."""
from __future__ import annotations
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import uuid

WORKSPACE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE / 'ai-test/runtime'))
sys.path.insert(0, str(Path(__file__).parent))
from aitest_runtime.autonomous_orchestration import DirectoryScopedOpenCodeSessionProvider
from aitest_runtime.canonical_runtime import create_canonical_runtime
from aitest_runtime.g2_1.managed_orchestration import G21AutonomousOrchestrationService
from test_g2_1_session_router_control_loop import request, one_task


def main():
    binary = Path(os.environ.get('AITEST_REAL_OPENCODE') or WORKSPACE / 'runtime/opencode/opencode.exe')
    if not binary.is_file(): raise RuntimeError('Actual pinned OpenCode binary required')
    processes = []
    old = dict(os.environ)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
        root = Path(directory)
        try:
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
            env = dict(os.environ)
            env.update(AITEST_WORKSPACE_ROOT=str(WORKSPACE), AITEST_RUNTIME_SPINE_DB=str(root/'runtime-spine.db'),
                PFC_LOCAL_STATE_ROOT=str(root), AITEST_OPENCODE_ENDPOINT=f'http://127.0.0.1:{port}',
                OPENCODE_SERVER_USERNAME='opencode', OPENCODE_SERVER_PASSWORD=uuid.uuid4().hex,
                OPENCODE_DISABLE_AUTOUPDATE='1', OPENCODE_DISABLE_MODELS_FETCH='1', OPENCODE_DISABLE_DEFAULT_PLUGINS='1',
                OPENCODE_DISABLE_LSP_DOWNLOAD='1', OPENCODE_DISABLE_SHARE='1',
                XDG_DATA_HOME=str(root/'oc-data'), XDG_CONFIG_HOME=str(root/'oc-config'), XDG_CACHE_HOME=str(root/'oc-cache'),
                BUN_INSTALL_CACHE_DIR=str(root/'bun-cache'), NO_PROXY='localhost,127.0.0.1,::1', no_proxy='localhost,127.0.0.1,::1',
                PYTHONPATH=str(WORKSPACE/'ai-test/runtime'), PYTHONDONTWRITEBYTECODE='1')
            env['OPENCODE_CONFIG_CONTENT'] = json.dumps({'autoupdate':False, 'share':'disabled', 'model':'bank/local-no-model',
                'provider':{'bank':{'npm':'@ai-sdk/openai-compatible','name':'No model construction endpoint',
                    'options':{'baseURL':'http://127.0.0.1:9/v1','apiKey':'synthetic-not-a-credential'},'models':{'local-no-model':{'name':'no model'}}}}})
            os.environ.update(env)
            with (root/'server.log').open('w') as log:
                server = subprocess.Popen([str(binary),'serve','--hostname','127.0.0.1','--port',str(port)],cwd=WORKSPACE,env=env,stdout=log,stderr=subprocess.STDOUT)
            processes.append(server)
            provider = DirectoryScopedOpenCodeSessionProvider(WORKSPACE, timeout=30)
            deadline = time.monotonic()+90
            while True:
                try:
                    if provider.health().get('healthy'): break
                except Exception:
                    if server.poll() is not None or time.monotonic()>deadline:
                        raise RuntimeError('REAL_OPENCODE_START_FAILED: '+(root/'server.log').read_text(errors='replace')[-2500:])
                    time.sleep(.5)
            runtime = create_canonical_runtime(WORKSPACE)
            orch = G21AutonomousOrchestrationService(runtime, WORKSPACE, session_provider=provider)
            mission = orch.start_test(request('actual-opencode-'+uuid.uuid4().hex, 'LOCAL-OPENCODE-ONLY'))['intake']['intake']['mission_id']
            first = orch.propose_plan(mission, one_task())['next']
            sid = first['external_session']['session_id']
            # Persist synthetic input via real OpenCode API without buying a model
            # response or presenting an external bank observation as successful.
            provider._request('POST',f'/session/{sid}/message?{provider._directory_query()}',
                {'agent':'aitest-executor','noReply':True,'parts':[{'type':'text','text':'本地合成负载仅用于上下文预算验证。'*1200}]})
            observed = provider.observe_session(sid)
            assert observed['pressure']['metrics_source']=='OPENCODE_MESSAGE_API', observed
            with (root/'loop.log').open('w') as log:
                loop = subprocess.Popen([sys.executable,'-X','utf8','-m','aitest_runtime.control_loop','--workspace-root',str(WORKSPACE),'--interval','1'],cwd=WORKSPACE,env=env,stdout=log,stderr=subprocess.STDOUT)
            processes.append(loop)
            deadline=time.monotonic()+90
            while True:
                restored = G21AutonomousOrchestrationService(create_canonical_runtime(WORKSPACE), WORKSPACE, session_provider=provider)
                rotations = restored.session_control.state(mission).rotations
                execution = restored.runtime.replay_composed(mission).extension_state('r1_3b_execution_resume')
                latest = execution.latest_attempt(first['task_id'])
                if rotations and latest.attempt_id != first['attempt']['attempt_id']: break
                if loop.poll() is not None or time.monotonic()>deadline:
                    raise RuntimeError('REAL_OPENCODE_ROTATION_NOT_OBSERVED: '+(root/'loop.log').read_text(errors='replace')[-2500:])
                time.sleep(.5)
            execution = restored.runtime.replay_composed(mission).extension_state('r1_3b_execution_resume')
            latest = execution.latest_attempt(first['task_id'])
            assert latest.root_attempt_id==first['attempt']['root_attempt_id']
            assert latest.attempt_id!=first['attempt']['attempt_id']
            assert rotations[-1].checkpoint['predecessor_session_id']==sid
            result={'status':'PASS','classification':'REAL_OPENCODE_LOCAL_API_ROTATE_RESUME',
                'version':subprocess.check_output([str(binary),'--version'],text=True).strip(),
                'metrics_source':observed['pressure']['metrics_source'],'rotation_count':len(rotations),
                'checkpoint_and_attempt_lineage':'PASS','bank_model_turn':'NOT_EXECUTED','BANK_FIELD_VALIDATION_REQUIRED':True}
            assert result['version']=='1.18.3'
            print(json.dumps(result,indent=2))
        finally:
            for process in reversed(processes):
                if process.poll() is None:
                    process.terminate()
                    try: process.wait(timeout=10)
                    except subprocess.TimeoutExpired: process.kill(); process.wait()
            os.environ.clear(); os.environ.update(old)
    return 0


if __name__=='__main__': raise SystemExit(main())
