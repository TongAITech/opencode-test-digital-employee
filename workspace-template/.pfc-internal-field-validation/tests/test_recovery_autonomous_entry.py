"""Real OpenCode -> Director tool -> Planner tool -> Router worker tools.

A deterministic localhost OpenAI protocol fixture supplies tool decisions. It is
not an AI semantic planner, a bank provider, or bank acceptance. No test code
calls start_test/propose_plan/report_task_outcome directly; only OpenCode tools
author Mission/Plan/Task truth. Every Python tool uses the packaged executable
on Windows. The user's only input is the exact natural-language test request.
"""
from __future__ import annotations
import base64
import http.server
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import urllib.request

WORKSPACE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE / 'ai-test/runtime'))
from aitest_runtime.autonomous_orchestration import DirectoryScopedOpenCodeSessionProvider
from aitest_runtime.canonical_runtime import create_canonical_runtime
from aitest_runtime.bounded_evidence import mission_evidence_directory


def texts(content):
    if isinstance(content, str): return content
    if isinstance(content, list): return '\n'.join(p.get('text', '') for p in content if isinstance(p, dict))
    return ''


class ModelFixture(http.server.BaseHTTPRequestHandler):
    requests = []
    errors = []
    decisions = []
    max_request_bytes = 0
    def log_message(self, *args): pass
    def do_POST(self):
        try:
            size = int(self.headers.get('Content-Length', '0'))
            self.__class__.max_request_bytes = max(self.max_request_bytes, size)
            if size > 256 * 1024: raise ValueError('CONTEXT_TOO_LARGE_ERROR')
            body = json.loads(self.rfile.read(size))
            messages = body.get('messages', [])
            tools = {t['function']['name'] for t in body.get('tools', [])}
            self.requests.append({'path': self.path, 'request_bytes': size, 'tool_names': sorted(tools)})
            envelope = None
            for message in messages:
                text = texts(message.get('content'))
                if message.get('role') == 'user' and text.startswith(('AITEST_CANONICAL_PLANNING_CONTEXT\n', 'AITEST_CANONICAL_CONTEXT\n')):
                    envelope = json.loads(text.split('\n', 1)[1])
            previous_tools = {m.get('name') for m in messages if m.get('role') == 'tool'}
            # OpenAI-compatible tool results commonly omit name. Recover it
            # from the assistant's corresponding tool call in this Session.
            for message in messages:
                previous_tools.update(t.get('function', {}).get('name') for t in message.get('tool_calls', []))
            name = None; args = {}; role = 'OTHER'
            if envelope and envelope.get('task_id'):
                role = envelope['logical_agent']
                if 'aitest_context' not in previous_tools:
                    mission = envelope['mission_id']
                    source = mission_evidence_directory(self.server.durable_root, mission) / 'local-observations.jsonl'
                    source.parent.mkdir(parents=True, exist_ok=True)
                    if not source.exists():
                        source.write_text('{"classification":"SYNTHETIC_ONLY","observation":"local protocol tool roundtrip"}\n' * 50, encoding='utf-8')
                    name = 'aitest_context'; args = {'mission_id': mission, 'source_ref': 'evidence:local-observations.jsonl', 'limit': 1024}
                elif 'aitest_worker' not in previous_tools:
                    name = 'aitest_worker'; args = {'action': 'report_task_outcome', 'payload': {
                        key: envelope[key] for key in ('mission_id', 'task_id', 'attempt_id', 'session_id')}}
                    args['payload'].update(outcome='SUCCEEDED', summary='Synthetic protocol fixture verified bounded source reference and routed worker tool')
            elif envelope:
                role = 'PLANNER'
                if 'aitest_planner' not in previous_tools:
                    proposal = {'objective': 'Synthetic tool protocol qualification, no bank testing claim', 'tasks': [], 'dependencies': []}
                    for key, task_role, intent in [('inspect-reference', 'CODE_ANALYST', 'Inspect one bounded local evidence reference'),
                                                   ('evaluate-reference', 'EVALUATOR', 'Evaluate the prior local reference observation')]:
                        proposal['tasks'].append({'task_key': key, 'intent': intent,
                            'acceptance_criteria': [{'id': key + '-complete', 'description': 'Record the local fixture observation through the bound worker outcome tool'}],
                            'routing': {'role': task_role, 'required_capabilities': ['OPENCODE_AGENT_SESSION', 'TASK_OUTCOME_REPORT'],
                                        'isolation_policy': 'DEDICATED_TASK_SESSION', 'parallelism_policy': 'SERIAL'}})
                    proposal['dependencies'] = [{'from': 'inspect-reference', 'to': 'evaluate-reference'}]
                    name = 'aitest_planner'; args = {'action': 'propose_plan', 'payload': {'mission_id': envelope['mission_id'], 'proposal': proposal}}
            elif any(m.get('role') == 'user' and texts(m.get('content')).strip() == '测试 BLOAN1.9.4' for m in messages):
                role = 'DIRECTOR'
                if 'aitest_director' not in previous_tools:
                    name = 'aitest_director'; args = {'action': 'start_test', 'payload': {'user_request': '测试 BLOAN1.9.4'}}
            if name and name not in tools: raise ValueError('REQUIRED_ROLE_TOOL_NOT_AVAILABLE:' + name)
            self.decisions.append({'role': role, 'tool': name, 'mission_id': (envelope or {}).get('mission_id'),
                                   'session_id': (envelope or {}).get('session_id')})
            delta = {'role': 'assistant'}
            if name:
                delta['tool_calls'] = [{'index': 0, 'id': 'call_' + uuid.uuid4().hex[:12], 'type': 'function',
                                        'function': {'name': name, 'arguments': json.dumps(args, ensure_ascii=False)}}]
            else: delta['content'] = 'Synthetic protocol fixture complete. Bank validation remains required.'
            chunk = {'id': 'chatcmpl_' + uuid.uuid4().hex, 'object': 'chat.completion.chunk', 'created': int(time.time()),
                     'model': 'fixture', 'choices': [{'index': 0, 'delta': delta, 'finish_reason': None}]}
            finish = {**chunk, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'tool_calls' if name else 'stop'}],
                      'usage': {'prompt_tokens': 100, 'completion_tokens': 50, 'total_tokens': 150}}
            raw = ('data: ' + json.dumps(chunk, ensure_ascii=False) + '\n\ndata: ' + json.dumps(finish) + '\n\ndata: [DONE]\n\n').encode()
            self.send_response(200); self.send_header('Content-Type', 'text/event-stream'); self.send_header('Content-Length', str(len(raw))); self.end_headers()
            self.wfile.write(raw)
        except Exception as exc:
            self.errors.append(type(exc).__name__ + ':' + str(exc))
            self.send_response(500); self.end_headers()


def main():
    binary = Path(os.environ.get('AITEST_REAL_OPENCODE') or WORKSPACE / 'runtime/opencode/opencode.exe')
    if not binary.is_file(): raise RuntimeError('Actual pinned OpenCode binary required')
    old = dict(os.environ); process = None; model = None; event_response = None
    executed = []; event_ready = threading.Event()
    with tempfile.TemporaryDirectory(prefix='recovery-autonomous-', ignore_cleanup_errors=True) as temporary:
        root = Path(temporary); workspace = root / 'workspace'; durable = root / 'data'
        shutil.copytree(WORKSPACE, workspace, ignore=lambda directory, names: [name for name in names if name == '__pycache__' or name.endswith('.pyc') or (Path(directory) == WORKSPACE and name == 'runtime')])
        payload = Path(os.environ.get('AITEST_REAL_OPENCODE_PAYLOAD') or WORKSPACE / '.opencode')
        if not (payload / 'node_modules/@opencode-ai/plugin/package.json').is_file():
            raise RuntimeError('OFFLINE_OPENCODE_PLUGIN_PAYLOAD_REQUIRED')
        for destination in (workspace / '.opencode', root / 'oc-config/opencode'):
            destination.mkdir(parents=True, exist_ok=True)
            if not (destination / 'node_modules').exists():
                shutil.copytree(payload / 'node_modules', destination / 'node_modules')
            for name in ('package.json', 'package-lock.json'):
                shutil.copy2(payload / name, destination / name)
        (workspace / 'PFC_R1_R4_INSTALLATION.json').write_text('{"classification":"LOCAL_PROTOCOL_FIXTURE"}', encoding='utf-8')
        python = workspace / 'runtime/python'
        if os.name == 'nt': shutil.copytree(WORKSPACE / 'runtime/python', python)
        else:
            python.mkdir(parents=True); (python / 'python').symlink_to(sys.executable)
        try:
            model = http.server.ThreadingHTTPServer(('127.0.0.1', 0), ModelFixture)
            model.durable_root = durable
            threading.Thread(target=model.serve_forever, daemon=True).start()
            with socket.socket() as sock: sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
            env = dict(os.environ)
            env.update(AITEST_WORKSPACE_ROOT=str(workspace), AITEST_RUNTIME_SPINE_DB=str(durable / 'state/runtime-spine.db'),
                PFC_LOCAL_STATE_ROOT=str(durable), AITEST_OPENCODE_ENDPOINT=f'http://127.0.0.1:{port}',
                OPENCODE_SERVER_USERNAME='opencode', OPENCODE_SERVER_PASSWORD=uuid.uuid4().hex,
                OPENCODE_DISABLE_AUTOUPDATE='1', OPENCODE_DISABLE_MODELS_FETCH='1', OPENCODE_DISABLE_DEFAULT_PLUGINS='1',
                OPENCODE_DISABLE_LSP_DOWNLOAD='1', OPENCODE_DISABLE_SHARE='1', OPENCODE_TEST_HOME=str(root / 'oc-home'),
                npm_config_offline='true', npm_config_registry='http://127.0.0.1:9',
                XDG_DATA_HOME=str(root/'oc-data'), XDG_CONFIG_HOME=str(root/'oc-config'), XDG_CACHE_HOME=str(root/'oc-cache'),
                BUN_INSTALL_CACHE_DIR=str(root/'bun-cache'), NO_PROXY='localhost,127.0.0.1,::1', no_proxy='localhost,127.0.0.1,::1',
                PYTHONPATH=os.pathsep.join(filter(None, [str(workspace/'ai-test/runtime'), env.get('PYTHONPATH')])) , PYTHONDONTWRITEBYTECODE='1')
            env['OPENCODE_CONFIG_CONTENT'] = json.dumps({'autoupdate': False, 'share': 'disabled', 'enabled_providers': ['fixture'],
                'model': 'fixture/fixture', 'small_model': 'fixture/fixture', 'provider': {'fixture': {'npm': '@ai-sdk/openai-compatible',
                'name': 'Synthetic protocol fixture', 'options': {'baseURL': f'http://127.0.0.1:{model.server_port}/v1', 'apiKey': 'synthetic-not-a-credential'},
                'models': {'fixture': {'name': 'Fixture', 'limit': {'context': 131072, 'output': 8192}}}}}})
            os.environ.update(env)
            with (root/'server.log').open('w') as log:
                process = subprocess.Popen([str(binary), 'serve', '--hostname', '127.0.0.1', '--port', str(port)], cwd=workspace, env=env, stdout=log, stderr=subprocess.STDOUT)
            provider = DirectoryScopedOpenCodeSessionProvider(workspace, timeout=30)
            deadline = time.monotonic() + 90
            while True:
                try:
                    if provider.health().get('healthy'): break
                except Exception:
                    if process.poll() is not None or time.monotonic() > deadline: raise RuntimeError('OPENCODE_START_FAILED:' + (root/'server.log').read_text(errors='replace')[-2500:])
                    time.sleep(.3)
            def observe_tools():
                nonlocal event_response
                auth = base64.b64encode(('opencode:' + env['OPENCODE_SERVER_PASSWORD']).encode()).decode()
                request = urllib.request.Request(env['AITEST_OPENCODE_ENDPOINT'] + '/event?' + provider._directory_query(), headers={'Authorization': 'Basic ' + auth})
                try:
                    event_response = urllib.request.urlopen(request, timeout=200)
                    event_ready.set()
                    for raw in event_response:
                        if len(raw) > 65536 or not raw.startswith(b'data: '): continue
                        event = json.loads(raw[6:])
                        part = event.get('properties', {}).get('part', {})
                        if part.get('type') == 'tool':
                            record = {'session_id': part.get('sessionID'), 'tool': part.get('tool'),
                                      'status': part.get('state', {}).get('status')}
                            if record['status'] == 'error': record['error'] = part.get('state', {}).get('error', '')[:2000]
                            executed.append(record)
                except Exception:
                    event_ready.set()
            threading.Thread(target=observe_tools, daemon=True).start()
            if not event_ready.wait(10): raise RuntimeError('OPENCODE_TOOL_EVENT_OBSERVER_UNAVAILABLE')
            user = provider.create_session(title='Synthetic natural-language Director intake qualification')
            provider.send_context(session_id=user.session_id, agent='aitest-director', text='测试 BLOAN1.9.4')
            deadline = time.monotonic() + 180
            runtime = create_canonical_runtime(workspace)
            mission = None; composed = None
            while time.monotonic() < deadline:
                from aitest_runtime.g2_1.managed_orchestration import G21AutonomousOrchestrationService
                service = G21AutonomousOrchestrationService(runtime, workspace, session_provider=provider)
                missions = service._all_mission_ids()
                if missions:
                    mission = missions[0]; composed = runtime.replay_composed(mission)
                    graph = composed.extension_state('r1_2_work_graph')
                    if len(graph.tasks) == 2 and all(t.lifecycle_state.value == 'SUCCEEDED' for t in graph.tasks): break
                if ModelFixture.errors: raise RuntimeError('MODEL_PROTOCOL_FIXTURE_FAILED:' + json.dumps(ModelFixture.errors))
                if any(p['status'] == 'error' for p in executed): raise RuntimeError('ACTUAL_OPENCODE_TOOL_FAILED:' + json.dumps(executed))
                time.sleep(.3)
            else:
                states = []
                for session in provider.list_sessions():
                    messages = provider._request('GET', f'/session/{session.session_id}/message?{provider._directory_query()}')
                    states.append({'session': session.session_id, 'messages': messages})
                (root/'failure.json').write_text(json.dumps(states), encoding='utf-8')
                raise RuntimeError('AUTONOMOUS_TOOL_PIPELINE_TIMEOUT:' + json.dumps(states)[-12000:] + '\n' + (root/'server.log').read_text(errors='replace')[-2000:])
            state = service.session_control.state(mission)
            planner = [p for p in state.provisions if p.role == 'PLANNER']
            workers = [p for p in state.provisions if p.task_id]
            assert len(planner) == 1 and len(workers) == 2
            ids = [user.session_id, planner[0].external_session_id, *(p.external_session_id for p in workers)]
            assert len(set(ids)) == 4
            assert {p.role for p in workers} == {'CODE_ANALYST', 'EVALUATOR'}
            assert len({p.logical_agent_id for p in [*planner, *workers]}) == 3
            # Observe live OpenCode tool events before Runtime closes terminal
            # Sessions. Durable R1 Mission/Plan/Task results confirm mutations
            # even when a Session is deleted before its final tool-result event.
            for name in ('aitest_director', 'aitest_planner', 'aitest_worker', 'aitest_context'):
                assert any(p['tool'] == name and p['status'] in {'running', 'completed'} for p in executed), executed
            assert not any(p['status'] == 'error' for p in executed), executed
            assert any(p['tool'] == 'aitest_director' and p['session_id'] == user.session_id for p in executed)
            assert any(p['tool'] == 'aitest_planner' and p['session_id'] == planner[0].external_session_id for p in executed)
            assert all(any(p['tool'] == 'aitest_worker' and p['session_id'] == worker.external_session_id for p in executed) for worker in workers)
            assert not (workspace / 'ai-test/state/aitest.db').exists()
            print(json.dumps({'status': 'PASS', 'classification': 'REAL_OPENCODE_WITH_SYNTHETIC_MODEL_PROTOCOL_FIXTURE',
                'gates': {**{g: 'PASS' for g in ('NATURAL_LANGUAGE_START_TEST', 'MISSION_INTAKE', 'PLANNER_SESSION', 'SCHEDULER_AUTO_ADVANCE', 'SESSION_ROUTER')},
                          'AUTONOMOUS_PLAN': 'SIMULATED_SEMANTIC_PLANNER'},
                'user_request': '测试 BLOAN1.9.4', 'mission_id': mission, 'distinct_session_count': len(set(ids)),
                'worker_roles': [p.role for p in workers], 'executed_tools': executed,
                'tool_mutation_result_authority': 'R1_EVENT_STREAM; live OpenCode events captured before terminal Session cleanup',
                'semantic_planner': 'SIMULATED_SEMANTIC_PLANNER', 'real_model_autonomous_plan': 'NOT_EXECUTED',
                'max_model_request_bytes': ModelFixture.max_request_bytes,
                'python_executable': sys.executable, 'BANK_FIELD_VALIDATION_REQUIRED': True}, ensure_ascii=False, indent=2))
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                try: process.wait(timeout=10)
                except subprocess.TimeoutExpired: process.kill(); process.wait()
            if model is not None: model.shutdown(); model.server_close()
            os.environ.clear(); os.environ.update(old)
    return 0

if __name__ == '__main__': raise SystemExit(main())
