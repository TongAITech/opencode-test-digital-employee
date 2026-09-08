"""Real OpenCode -> Director tool -> Planner tool -> Router worker tools.

A deterministic localhost OpenAI protocol fixture supplies tool decisions. It is
not an AI semantic planner, a bank provider, or bank acceptance. No test code
calls start_test/propose_plan/report_task_outcome directly; only OpenCode tools
author Mission/Plan/Task truth. Every Python tool uses the packaged executable
on Windows. The user's only input is the exact natural-language test request.
"""
from __future__ import annotations
import base64
import hashlib
import http.server
import json
import os
from pathlib import Path
import shutil
import sqlite3
import zipfile
import io
from contextlib import redirect_stdout
from unittest.mock import patch
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
    worker_sessions = {}
    source_bytes = 0
    source_digest = None
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
                mission = envelope['mission_id']
                source = mission_evidence_directory(self.server.durable_root, mission) / 'local-observations.jsonl'
                source.parent.mkdir(parents=True, exist_ok=True)
                if not source.exists():
                    row = (json.dumps({'classification': 'SYNTHETIC_ONLY', 'observation': 'bounded context pressure regression ' * 80}) + '\n').encode('utf-8')
                    digest = hashlib.sha256()
                    with source.open('wb') as output:
                        for _ in range(4500): output.write(row); digest.update(row)
                    self.__class__.source_bytes = source.stat().st_size
                    self.__class__.source_digest = digest.hexdigest()
                sessions = self.worker_sessions.setdefault(envelope['root_attempt_id'], [])
                if envelope['session_id'] not in sessions: sessions.append(envelope['session_id'])
                generation = sessions.index(envelope['session_id'])
                reads = sum(t.get('function', {}).get('name') == 'aitest_context' for message in messages for t in message.get('tool_calls', []))
                stress_worker = role == 'aitest-code-analyst'
                # Real bounded tool results grow the real OpenCode message
                # history. Return idle after seven pages and let the actual
                # background process discover pressure; the fixture never
                # requests rotation and never sets observation/utilization.
                page_budget = (7 if generation < 2 else 0) if stress_worker else 1
                if reads < page_budget:
                    name = 'aitest_context'; args = {'mission_id': mission, 'source_ref': 'evidence:local-observations.jsonl',
                        'offset': (generation * 7 + reads) * 4096, 'limit': 4096 if stress_worker else 512, 'expected_sha256': self.source_digest}
                elif not {'aitest_worker','aitest_executor'} & previous_tools and (not stress_worker or generation >= 2):
                    name = 'aitest_executor' if role=='aitest-executor' else 'aitest_worker'; args = {'action': 'report_task_outcome', 'payload': {
                        key: envelope[key] for key in ('mission_id', 'task_id', 'attempt_id', 'session_id')}}
                    args['payload'].update(outcome='SUCCEEDED', summary='Synthetic protocol fixture verified bounded evidence after automatic Runtime successor continuation')
            elif envelope:
                role = 'PLANNER'
                if 'aitest_planner' not in previous_tools:
                    proposal = {'objective': 'Synthetic tool protocol qualification, no bank testing claim', 'tasks': [], 'dependencies': []}
                    roles=[('requirements','REQUIREMENT_ANALYST'),('inspect-reference','CODE_ANALYST'),('strategy','TEST_STRATEGIST'),('cases','CASE_DESIGNER'),('execution','EXECUTOR'),('evaluate-reference','EVALUATOR'),('diagnosis','DIAGNOSIS')]
                    for key, task_role in roles:
                        intent='Verify Router-owned '+task_role+' transport against one bounded synthetic evidence reference'
                        proposal['tasks'].append({'task_key': key, 'intent': intent,
                            'acceptance_criteria': [{'id': key + '-complete', 'description': 'Record the local fixture observation through the bound worker outcome tool'}],
                            'routing': {'role': task_role, 'required_capabilities': ['OPENCODE_AGENT_SESSION', 'TASK_OUTCOME_REPORT'],
                                        'isolation_policy': 'DEDICATED_TASK_SESSION', 'parallelism_policy': 'SERIAL'}})
                    proposal['dependencies'] = [{'from':a[0],'to':b[0]} for a,b in zip(roles,roles[1:])]
                    name = 'aitest_planner'; args = {'action': 'propose_plan', 'payload': {'mission_id': envelope['mission_id'], 'proposal': proposal}}
            elif any(m.get('role') == 'user' and texts(m.get('content')).strip() == 'SYNTHETIC_MODEL_BOUNDARY_QUALIFICATION' for m in messages):
                role = 'BOUNDARY_FIXTURE_ONLY'
                if 'aitest_recovery' not in previous_tools:
                    with sqlite3.connect(self.server.durable_root / 'state/runtime-spine.db') as db:
                        mission = db.execute('SELECT mission_id FROM mission_projection LIMIT 1').fetchone()[0]
                    name = 'aitest_recovery'; args = {'action': 'import_document', 'payload': {
                        'mission_id': mission, 'path': str(self.server.boundary_source), 'source_id': 'model-boundary-fixture'}}
                else:
                    checks = [t for m in messages for t in m.get('tool_calls', []) if t.get('function', {}).get('name') == 'aitest_recovery' and json.loads(t['function']['arguments']).get('payload', {}).get('__qualification_boundary')]
                    if len(checks) < 2:
                        name = 'aitest_recovery'; args = {'action': 'intake_context', 'payload': {'__qualification_boundary': 'status' if not checks else 'error'}}
            elif any(m.get('role') == 'user' and texts(m.get('content')).strip() == '测试 BLOAN-PF1.1.0' for m in messages):
                role = 'DIRECTOR'
                if 'aitest_director' not in previous_tools:
                    name = 'aitest_director'; args = {'action': 'start_test', 'payload': {'user_request': '测试 BLOAN-PF1.1.0'}}
            if name and name not in tools: raise ValueError('REQUIRED_ROLE_TOOL_NOT_AVAILABLE:' + name + ':available=' + ','.join(sorted(tools)))
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
    if not binary.is_file(): raise RuntimeError('External host OpenCode fixture required')
    old = dict(os.environ); process = None; loop = None; model = None; event_response = None
    executed = []; bounded_pages = []; boundary_outputs = []; event_ready = threading.Event()
    with tempfile.TemporaryDirectory(prefix='recovery-autonomous-', ignore_cleanup_errors=True) as temporary:
        root = Path(temporary); workspace = root / 'workspace'; durable = root / 'data'
        shutil.copytree(WORKSPACE, workspace, ignore=lambda directory, names: [name for name in names if name == '__pycache__' or name.endswith('.pyc') or (Path(directory) == WORKSPACE and name == 'runtime')])
        payload = Path(os.environ.get('AITEST_REAL_OPENCODE_PAYLOAD') or WORKSPACE / '.opencode')
        if not (payload / 'node_modules/@opencode-ai/plugin/package.json').is_file():
            raise RuntimeError('OFFLINE_OPENCODE_PLUGIN_PAYLOAD_REQUIRED')
        for destination in (workspace / '.opencode', root / 'oc-config/opencode'):
            destination.mkdir(parents=True, exist_ok=True)
            # A preceding source test may leave a partial ignored node_modules
            # directory. Its presence does not prove the offline SDK is present.
            shutil.copytree(payload / 'node_modules', destination / 'node_modules', dirs_exist_ok=True)
            for name in ('package.json', 'package-lock.json'):
                shutil.copy2(payload / name, destination / name)
        (workspace / 'INSTALL_MANIFEST.json').write_text('{"classification":"LOCAL_PROTOCOL_FIXTURE"}', encoding='utf-8')
        # Test-only branch in the temporary tool copy: exercise large Runtime
        # result shapes and error presentation through actual OpenCode/Bun.
        # The production tool API and R1/domain implementations stay unchanged.
        boundary_code = '''
  if (args.payload.__qualification_boundary === "error") throw new Error("😀".repeat(10000))
  const identityHeavy = Object.fromEntries(Array.from({length:20}, (_,i) => ["field_"+i+"_id", "x".repeat(1600)]))
  Object.assign(identityHeavy, {status:"PASS", truth_source:"R1_EVENT_STREAM", mission_id:"required-mission", task_id:"required-task", attempt_id:"required-attempt", session_id:"required-session"})
  identityHeavy.next = {status:"DISPATCHED", task_id:"next-task", attempt:{attempt_id:"next-attempt",root_attempt_id:"next-root"}, external_session:{session_id:"next-session"}}
  const fallback = JSON.parse(modelResult(identityHeavy))
  for (const key of ["status","truth_source","mission_id","task_id","attempt_id","session_id"])
    if (fallback[key] !== identityHeavy[key]) throw new Error("BOUNDARY_REQUIRED_CONTROL_LOST:"+key)
  if (fallback.next.status !== "DISPATCHED" || fallback.next.attempt.attempt_id !== "next-attempt" || fallback.next.external_session.session_id !== "next-session") throw new Error("BOUNDARY_NEXT_TASK_CONTROL_LOST")
  const asciiError = modelError("x".repeat(50000)).message
  if (!asciiError.includes("omitted=true") || Buffer.byteLength(asciiError,"utf8") > 16384) throw new Error("BOUNDARY_ERROR_OMISSION_REQUIRED")
  const largeKey = modelResult({status:"PASS", ["x".repeat(20000)+"_id"]:"value"})
  if (Buffer.byteLength(largeKey,"utf8") > 16384 || JSON.parse(largeKey).status !== "PASS") throw new Error("BOUNDARY_LARGE_KEY_ESCAPE")
  return modelResult({status:"PASS",truth_source:"R1_EVENT_STREAM",mission_id:"synthetic-mission",
    task_id:"synthetic-task",attempt_id:"synthetic-attempt",session_id:"synthetic-session",
    core:{events:Array.from({length:20000}, (_,i) => ({event_id:"synthetic-"+i,body:"合成运行时事实".repeat(40)}))},
    next:{status:"PLAN_COMPLETE"}, ["x".repeat(20000)+"_id"]:"oversized-key-fixture"})
'''
        recovery_tool = workspace / '.opencode/tools/aitest.ts'
        prefix, recovery_part = recovery_tool.read_text(encoding='utf-8').split('export const recovery = boundedTool(tool, {', 1)
        recovery_part = recovery_part.replace('  async execute(args, context) {',
            '  async execute(args, context) {\n    if (args.payload.__qualification_boundary) {\n' + boundary_code + '\n    }', 1)
        recovery_tool.write_text(prefix + 'export const recovery = boundedTool(tool, {' + recovery_part, encoding='utf-8')
        python = workspace / 'runtime/python'
        if os.name == 'nt': shutil.copytree(WORKSPACE / 'runtime/python', python)
        else:
            python.mkdir(parents=True); (python / 'python').symlink_to(sys.executable)
        try:
            model = http.server.ThreadingHTTPServer(('127.0.0.1', 0), ModelFixture)
            model.durable_root = durable
            model.workspace = workspace
            model.boundary_source = workspace / 'qualification-source.txt'
            model.boundary_source.write_text('SYNTHETIC DOCUMENT ' * 60000, encoding='utf-8')
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
                process = subprocess.Popen([str(binary), 'serve', '--print-logs', '--log-level', 'DEBUG', '--hostname', '127.0.0.1', '--port', str(port)], cwd=workspace, env=env, stdout=log, stderr=subprocess.STDOUT)
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
                                      'status': part.get('state', {}).get('status'),
                                      'fixture_boundary_kind': part.get('state', {}).get('input', {}).get('payload', {}).get('__qualification_boundary')}
                            if record['status'] == 'error':
                                error = part.get('state', {}).get('error', '')
                                record.update(error=error[:2000], error_bytes=len(error.encode('utf-8')))
                            executed.append(record)
                            if record['tool'] == 'aitest_context' and record['status'] == 'completed':
                                output = part.get('state', {}).get('output', '')
                                page = json.loads(output)
                                bounded_pages.append({key: page[key] for key in ('source_bytes', 'returned_bytes', 'source_sha256', 'offset')})
                                bounded_pages[-1].update(session_id=record['session_id'], response_bytes=len(output.encode('utf-8')))
                            if record['status'] == 'completed' and record['tool'] == 'aitest_recovery':
                                output = part.get('state', {}).get('output', '')
                                boundary_outputs.append({'tool': record['tool'], 'kind': record['fixture_boundary_kind'] or 'import', 'bytes': len(output.encode('utf-8')), 'value': json.loads(output)})

                except Exception:
                    event_ready.set()
            threading.Thread(target=observe_tools, daemon=True).start()
            if not event_ready.wait(10): raise RuntimeError('OPENCODE_TOOL_EVENT_OBSERVER_UNAVAILABLE')
            loop_command = [sys.executable, '-X', 'utf8', '-m', 'aitest_runtime.control_loop', '--workspace-root', str(workspace), '--interval', '3']
            with (root / 'control-loop.log').open('w') as log:
                loop = subprocess.Popen(loop_command, cwd=workspace, env=env, stdout=log, stderr=subprocess.STDOUT)
            user = provider.create_session(title='Synthetic natural-language Director intake qualification')
            provider._request('POST', f'/session/{user.session_id}/prompt_async?{provider._directory_query()}',
                              {'parts': [{'type': 'text', 'text': '测试 BLOAN-PF1.1.0'}]})
            deadline = time.monotonic() + int(os.environ.get('AITEST_QUALIFICATION_TIMEOUT','240'))
            runtime = create_canonical_runtime(workspace)
            mission = None; composed = None; boundary_session = None; boundary_head = None; boundary_idle_since = 0
            while time.monotonic() < deadline:
                from aitest_runtime.g2_1.managed_orchestration import G21AutonomousOrchestrationService
                service = G21AutonomousOrchestrationService(runtime, workspace, session_provider=provider)
                missions = service._all_mission_ids()
                if missions:
                    mission = missions[0]; composed = runtime.replay_composed(mission)
                    graph = composed.extension_state('r1_2_work_graph')
                    if len(graph.tasks) == 7 and all(t.lifecycle_state.value == 'SUCCEEDED' for t in graph.tasks):
                        if boundary_session is None:
                            head = runtime.get_head_seq(mission)
                            if head != boundary_head:
                                boundary_head = head; boundary_idle_since = time.monotonic()
                            elif time.monotonic() - boundary_idle_since >= 1:
                                # This separate, explicitly synthetic Session
                                # tests result presentation after the one-turn
                                # autonomous Mission has already completed.
                                boundary_session = provider.create_session(title='Synthetic model-result boundary qualification only')
                                provider._request('POST', f'/session/{boundary_session.session_id}/prompt_async?{provider._directory_query()}',
                                    {'parts': [{'type': 'text', 'text': 'SYNTHETIC_MODEL_BOUNDARY_QUALIFICATION'}]})
                        elif (len({p['kind'] for p in boundary_outputs}) == 2
                                and any(p.get('fixture_boundary_kind') == 'error' and p['status'] == 'error' for p in executed)): break
                if loop.poll() is not None: raise RuntimeError('REAL_CONTROL_LOOP_EXITED:' + (root / 'control-loop.log').read_text(errors='replace')[-2000:])
                if ModelFixture.errors: raise RuntimeError('MODEL_PROTOCOL_FIXTURE_FAILED:' + json.dumps(ModelFixture.errors))
                if any(p['status'] == 'error' and p.get('error') != 'Tool execution aborted' and p.get('fixture_boundary_kind') != 'error' for p in executed): raise RuntimeError('ACTUAL_OPENCODE_TOOL_FAILED:' + json.dumps(executed))
                time.sleep(.3)
            else:
                states = []
                for session in provider.list_sessions():
                    messages = provider._request('GET', f'/session/{session.session_id}/message?{provider._directory_query()}')
                    states.append({'session': session.session_id, 'messages': messages})
                (root/'failure.json').write_text(json.dumps(states), encoding='utf-8')
                diagnostics={'server_log':(root/'server.log').read_text(errors='replace')[-8000:],
                    'control_log':(root/'control-loop.log').read_text(errors='replace')[-3000:],
                    'decisions':ModelFixture.decisions[-30:],'errors':ModelFixture.errors,'tools':executed[-12:],
                    'sessions':[{'id':item['session'],'messages':[{'role':m.get('info',{}).get('role'),'agent':m.get('info',{}).get('agent'),'error':m.get('info',{}).get('error'),
                        'parts':[{'type':p.get('type'),'text_prefix':str(p.get('text',''))[:100],'tool':p.get('tool'),'status':p.get('state',{}).get('status'),'error':str(p.get('state',{}).get('error',''))[:1000]} for p in m.get('parts',[])]} for m in item['messages']]} for item in states]}
                raise RuntimeError('AUTONOMOUS_TOOL_PIPELINE_TIMEOUT:' + json.dumps(diagnostics,ensure_ascii=False)[-18000:])
            state = service.session_control.state(mission)
            planner = [p for p in state.provisions if p.role == 'PLANNER']
            workers = [p for p in state.provisions if p.task_id]
            assert len(planner) == 1 and len(workers) >= 9
            ids = [user.session_id, planner[0].external_session_id, *(p.external_session_id for p in workers)]
            assert len(set(ids)) >= 11
            assert {p.role for p in workers} == {'REQUIREMENT_ANALYST','CODE_ANALYST','TEST_STRATEGIST','CASE_DESIGNER','EXECUTOR','EVALUATOR','DIAGNOSIS'}
            assert len({p.logical_agent_id for p in [*planner, *workers]}) == 8
            # Observe live OpenCode tool events before Runtime closes terminal
            # Sessions. Durable R1 Mission/Plan/Task results confirm mutations
            # even when a Session is deleted before its final tool-result event.
            for name in ('aitest_director', 'aitest_planner', 'aitest_worker', 'aitest_context'):
                assert any(p['tool'] == name and p['status'] in {'running', 'completed'} for p in executed), executed
            assert not any(p['status'] == 'error' and p.get('error') != 'Tool execution aborted' and p.get('fixture_boundary_kind') != 'error' for p in executed), executed
            assert all(p['bytes'] <= 16384 and p['value']['_model_projection']['omitted'] is True for p in boundary_outputs)
            imported = next(p['value'] for p in boundary_outputs if p['kind'] == 'import')
            assert imported['_model_projection']['source_bytes'] > 1024 * 1024
            assert imported['document']['fact_id'] and imported['document']['payload']['text']['_omitted'] is True
            huge_status = next(p['value'] for p in boundary_outputs if p['kind'] == 'status')
            assert huge_status['_model_projection']['source_bytes'] > 10 * 1024 * 1024
            assert huge_status['status'] == 'PASS' and huge_status['next']['status'] == 'PLAN_COMPLETE'
            for key in ('mission_id', 'task_id', 'attempt_id', 'session_id'): assert huge_status[key].startswith('synthetic-')
            assert all(p['error_bytes'] <= 16384 for p in executed if p.get('fixture_boundary_kind') == 'error' and p['status'] == 'error')
            assert any('😀' * 10 in p.get('error', '') for p in executed if p.get('fixture_boundary_kind') == 'error' and p['status'] == 'error')
            assert any(p['tool'] == 'aitest_director' and p['session_id'] == user.session_id for p in executed)
            assert any(p['tool'] == 'aitest_planner' and p['session_id'] == planner[0].external_session_id for p in executed)
            user_messages = provider._request('GET', f'/session/{user.session_id}/message?{provider._directory_query()}&limit=10')
            assert any(m.get('info', {}).get('role') == 'assistant' and m['info'].get('agent') == 'aitest-director' for m in user_messages)
            final_workers = [provision for provision in workers if composed.extension_state('r1_3b_execution_resume').latest_attempt(provision.task_id).runtime_session_id == provision.external_session_id]
            assert all(any(p['tool'] == ('aitest_executor' if worker.role=='EXECUTOR' else 'aitest_worker') and p['session_id'] == worker.external_session_id for p in executed) for worker in final_workers)
            stress_workers = [p for p in workers if p.role == 'CODE_ANALYST']
            rotations = [r for r in state.rotations if r.task_id == stress_workers[0].task_id]
            assert len(rotations) >= 2 and all(r.status == 'COMPLETED' for r in rotations), state.to_dict()
            attempts = [a for a in composed.extension_state('r1_3b_execution_resume').attempts if a.task_id == stress_workers[0].task_id]
            assert len(attempts) >= 3 and len({a.root_attempt_id for a in attempts}) == 1
            assert len({p.logical_agent_id for p in stress_workers}) == 1
            assert not any('SESSION_UNREACHABLE' in r.reasons for r in state.rotations), json.dumps({
                'rotations':[r.to_dict() for r in state.rotations if 'SESSION_UNREACHABLE' in r.reasons],
                'observations':[o.to_dict() for o in state.observations if o.provider_state.get('reachable') is False]},ensure_ascii=False)
            rotation_evidence = []
            for rotation in rotations:
                checkpoint = rotation.checkpoint
                assert checkpoint['mission_id'] == mission and checkpoint['task_id'] == stress_workers[0].task_id
                assert checkpoint['logical_agent_id'] == stress_workers[0].logical_agent_id
                assert checkpoint['root_attempt_id'] == attempts[0].root_attempt_id
                assert composed.core_state.session(checkpoint['predecessor_session_id']).status.value == 'CLOSED'
                observation = next(o for o in reversed(state.observations)
                    if o.session_id == checkpoint['predecessor_session_id'] and o.recorded_seq < rotation.requested_seq)
                assert observation.provider_state['pressure']['metrics_source'] == 'OPENCODE_MESSAGE_API'
                assert 'ESTIMATED_CONTEXT_PRESSURE' in rotation.reasons, rotation.to_dict()
                pages = [p for p in bounded_pages if p['session_id'] == rotation.predecessor_session_id]
                assert pages, 'Each rotation must follow an actual completed bounded evidence read'
                rotation_evidence.append({'task_id': rotation.task_id, 'logical_agent_id': checkpoint['logical_agent_id'],
                    'root_attempt_id': rotation.root_attempt_id, 'predecessor_session_id': rotation.predecessor_session_id,
                    'successor_session_id': rotation.successor_session_id, 'status': rotation.status,
                    'reasons': list(rotation.reasons), 'bounded_page_count': len(pages),
                    'observed_message_bytes_plus_reserve': observation.provider_state['pressure']['estimated_context_used']})
            predecessors = {r.checkpoint['predecessor_session_id'] for r in rotations}
            assert all(p['session_id'] in predecessors for p in executed if p['status'] == 'error' and p.get('fixture_boundary_kind') != 'error'), executed
            assert ModelFixture.source_bytes >= 10 * 1024 * 1024
            assert bounded_pages and all(p['returned_bytes'] <= 4096 and p['response_bytes'] <= 16384 for p in bounded_pages)
            assert all(p['source_bytes'] == ModelFixture.source_bytes and p['source_sha256'] == ModelFixture.source_digest for p in bounded_pages)
            assert ModelFixture.max_request_bytes < 256 * 1024
            # Restart the actual background process and rehydrate this same
            # Mission, then export its real R1 snapshot/evidence with the product
            # exporter and replay that snapshot in a separate Runtime instance.
            loop.terminate(); loop.wait(timeout=10)
            before_tasks = graph.to_dict()
            with (root / 'control-loop-restart.log').open('w') as log:
                restarted = subprocess.run([*loop_command, '--once'], cwd=workspace, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=45)
            assert restarted.returncode == 0, (root / 'control-loop-restart.log').read_text(errors='replace')[-2000:]
            restored = create_canonical_runtime(workspace)
            assert restored.replay_composed(mission).extension_state('r1_2_work_graph').to_dict() == before_tasks
            sys.path.insert(0, str(WORKSPACE.parent / 'tools/recovery'))
            import launcher
            (durable / 'exports').mkdir(parents=True, exist_ok=True)
            with patch.object(launcher, 'DATA', durable), redirect_stdout(io.StringIO()):
                exported = Path(launcher.evidence_export())
            restored_dir = root / 'export-replay'
            with zipfile.ZipFile(exported) as archive: archive.extractall(restored_dir)
            exported_runtime = create_canonical_runtime(workspace, db_path=restored_dir / 'state/runtime-spine.db')
            assert exported_runtime.replay_composed(mission).extension_state('r1_2_work_graph').to_dict() == before_tasks
            exported_source = mission_evidence_directory(restored_dir, mission) / 'local-observations.jsonl'
            assert exported_source.stat().st_size == ModelFixture.source_bytes

            assert not (workspace / 'ai-test/state/aitest.db').exists()
            print(json.dumps({'status': 'PASS', 'classification': 'REAL_OPENCODE_WITH_SYNTHETIC_MODEL_PROTOCOL_FIXTURE',
                'gates': {**{g: 'PASS' for g in ('NATURAL_LANGUAGE_START_TEST', 'MISSION_INTAKE', 'PLANNER_SESSION', 'SCHEDULER_AUTO_ADVANCE', 'SESSION_ROUTER', 'AUTO_ROTATION', 'SUCCESSOR_RESUME', 'CONTEXT_STRESS')},
                          'AUTONOMOUS_PLAN': 'SIMULATED_SEMANTIC_PLANNER'},
                'context_stress_transport': 'REAL_OPENCODE', 'default_agent_selected_without_override': True,
                'model_result_boundary': 'PASS', 'boundary_qualification_session': boundary_session.session_id, 'max_boundary_result_bytes': max(p['bytes'] for p in boundary_outputs),
                'large_import_body_omitted': True, 'large_runtime_projection_bytes': huge_status['_model_projection']['source_bytes'],
                'multibyte_error_byte_budget': 'PASS',
                'rotation_count': len(rotations), 'source_bytes': ModelFixture.source_bytes,
                'rotation_evidence': rotation_evidence, 'unreachable_rotation_count': 0,
                'max_bounded_response_bytes': max(p['response_bytes'] for p in bounded_pages),
                'bounded_page_count': len(bounded_pages), 'same_mission_task_logical_agent_root_attempt': True,
                'pressure_metrics_source': 'OPENCODE_MESSAGE_API', 'rotation_reason': 'ESTIMATED_CONTEXT_PRESSURE',
                'CONTEXT_TOO_LARGE_ERROR': 0, 'AI_APICallError_CONTEXT_OVERFLOW': 0, 'overflow_count': 0,
                'control_loop_restart_same_mission': 'PASS', 'evidence_export_same_mission_replay': 'PASS',
                'user_request': '测试 BLOAN-PF1.1.0', 'mission_id': mission, 'distinct_session_count': len(set(ids)),
                'worker_roles': sorted({p.role for p in workers}),
                'executed_tools': sorted({(p['session_id'], p['tool'], p['status']) for p in executed if p['status'] in {'running', 'completed'}}),
                'rotation_cancelled_tool_count': sum(p['status'] == 'error' and p.get('fixture_boundary_kind') != 'error' for p in executed),
                'tool_mutation_result_authority': 'R1_EVENT_STREAM; live OpenCode events captured before terminal Session cleanup',
                'semantic_planner': 'SIMULATED_SEMANTIC_PLANNER', 'real_model_autonomous_plan': 'NOT_EXECUTED',
                'max_model_request_bytes': ModelFixture.max_request_bytes,
                'python_executable': sys.executable, 'BANK_FIELD_VALIDATION_REQUIRED': True}, ensure_ascii=False, indent=2))
        finally:
            if loop is not None and loop.poll() is None:
                loop.terminate()
                try: loop.wait(timeout=10)
                except subprocess.TimeoutExpired: loop.kill(); loop.wait()
            if process is not None and process.poll() is None:
                process.terminate()
                try: process.wait(timeout=10)
                except subprocess.TimeoutExpired: process.kill(); process.wait()
            if model is not None: model.shutdown(); model.server_close()
            os.environ.clear(); os.environ.update(old)
    return 0

if __name__ == '__main__': raise SystemExit(main())
