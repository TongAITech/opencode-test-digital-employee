"""Actual pinned OpenCode server + automatic rotation; synthetic no-reply content, no model/bank pass."""
from __future__ import annotations
import json
import importlib.util
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
from aitest_runtime.hosted_intake import hosted_user_intake
from test_g2_1_session_router_control_loop import request, one_task


def main():
    binary = Path(os.environ.get('AITEST_REAL_OPENCODE') or WORKSPACE / 'runtime/opencode/opencode.exe')
    if not binary.is_file(): raise RuntimeError('External host OpenCode fixture required')
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
            env['OPENCODE_CONFIG_CONTENT'] = json.dumps({'enabled_providers':['fixture'],'model':'fixture/local-no-model','provider':{'fixture':{'npm':'@ai-sdk/openai-compatible','options':{'baseURL':'http://127.0.0.1:9/v1','apiKey':'synthetic-only'},'models':{'local-no-model':{'name':'Local fixture'}}}}})
            env['AITEST_MODEL_KEY'] = 'synthetic-not-a-credential'
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
            catalog = provider._request('GET', '/provider?' + provider._directory_query())
            assert catalog['connected'] == ['fixture'], catalog['connected']
            runtime = create_canonical_runtime(WORKSPACE)
            orch = G21AutonomousOrchestrationService(runtime, WORKSPACE, session_provider=provider)
            user_session = provider.create_session(title='Local hosted intake proof')
            user_message = provider._request('POST', f'/session/{user_session.session_id}/message?{provider._directory_query()}',
                {'agent':'aitest-director','noReply':True,'parts':[{'type':'text','text':'测试 BLOAN-PF1.1.0'}]})
            os.environ.update(AITEST_HOST_SESSION_ID=user_session.session_id, AITEST_HOST_MESSAGE_ID=user_message['info']['id'])
            hosted = hosted_user_intake(provider, {'user_request':'测试 BLOAN-PF1.1.0'})
            assert hosted['scope'] == {'mode':'EXPLICIT_SET','version':'BLOAN-PF1.1.0'}
            assert hosted['source']['source_ref'].endswith(user_message['info']['id'])
            admitted = orch.start_test(hosted)
            assert admitted['status'] == 'PLANNING', admitted
            os.environ.pop('AITEST_HOST_SESSION_ID', None); os.environ.pop('AITEST_HOST_MESSAGE_ID', None)
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
                'checkpoint_and_attempt_lineage':'PASS','approved_provider_allowlist':'PASS',
                'unconfigured_model_allows_process_start':'PASS','hosted_natural_language_mission_intake':'PASS',
                'bank_model_turn':'NOT_EXECUTED','BANK_FIELD_VALIDATION_REQUIRED':True}
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
