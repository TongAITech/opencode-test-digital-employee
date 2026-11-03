"""Engineering target: actual local HTTP + actual approved pytest subprocess.

Only initial source/design/approval facts are fixtures. No Runner output, HTTP
response, process exit, probe or evidence receipt is injected or mocked.
"""
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from urllib.request import Request, urlopen
from urllib.parse import urlsplit, parse_qs, quote

from rc6_runtime.truth import TruthRuntime
from rc6_runtime.executable_spec import ExecutableSpecBuilder
from rc6_runtime.target import REQUIRED_REPOSITORIES, REQUIRED_DATABASE_APPS
from rc7_runtime.models import Task, TaskStatus, Evaluation, EvaluationResult, Artifact, Evidence
from rc7_runtime.truth_overlay import append_entity
from rc7_runtime.execution_environment import ExecutionEnvironmentAdapter, ToolProbeResult
from rc7_runtime.rc72_canonical_design import CanonicalDesignService
from test_rc72_n7_execution_preparation import _setup, _service
from rc72_n2_test_support import BATCH, RELEASE, COMMIT


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass
    def _send(self, value):
        raw = json.dumps(value).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)
    def do_GET(self):
        if urlsplit(self.path).path == '/precondition':
            self._send({'ready': self.server.precondition_ready})
            return
        if urlsplit(self.path).path == '/data':
            ref = parse_qs(urlsplit(self.path).query).get('ref', [''])[0]
            self._send({'data_ref': ref, 'data_exists': ref in self.server.allowed_data_refs})
            return
        self._send({'restored': self.server.restored, 'ready': getattr(self.server, 'tool_ready', True)})
    def do_DELETE(self):
        self.server.restored = True
        self._send({'restored': True})
    def do_POST(self):
        raw = self.rfile.read(int(self.headers['Content-Length']))
        if self.path == '/repair':
            ref = json.loads(raw)['data_ref']
            self.server.allowed_data_refs.add(ref)
            if not hasattr(self.server, 'repair_calls'):
                self.server.repair_calls = []
            self.server.repair_calls.append(ref)
            self._send({'data_ref': ref, 'data_exists': ref in self.server.allowed_data_refs})
            return
        self.server.calls.append(json.loads(raw))
        self.server.restored = False
        delay = getattr(self.server, 'business_delay', 0)
        if delay:
            import time
            time.sleep(delay)
        self._send({'http': {'status': 200}, 'business': {'outcome': 'APPROVED_FIXTURE_RESULT'}})


class LocalHTTPEnvironment(ExecutionEnvironmentAdapter):
    def __init__(self, url, root):
        self.url, self.root = url, Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
    @property
    def adapter_id(self):
        return 'engineering-local-real-http'
    def probe_tool(self, *, tool_id, target_id, layer):
        with urlopen(self.url + '/health', timeout=5) as response:
            raw = response.read()
        path = self.root / ('probe-' + target_id + '.json')
        path.write_bytes(raw)
        return ToolProbeResult(tool_id, json.loads(raw).get('ready') is True, self.url, 'python://urllib.request',
            'adapter://engineering-local-real-http', 'http-call://' + target_id,
            'file://' + str(path), 'target-probe://' + target_id)
    def resolve_precondition(self, spec, context):
        if spec['requirement'] != 'target deployment and API route are proven available':
            raise AssertionError('unknown precondition must not be guessed')
        with urlopen(self.url + '/precondition', timeout=5) as response:
            raw = response.read()
        path = self.root / ('precondition-' + context['attempt_id'] + '.json')
        path.write_bytes(raw)
        return {'success': json.loads(raw).get('ready') is True, 'evidence_ref': 'file://' + str(path)}
    def prepare_data(self, requirement, context, *, strategy):
        raise AssertionError('N5 owns data preparation')
    def verify_data(self, requirement, binding, context):
        ref = requirement['data_ref']
        with urlopen(self.url + '/data?ref=' + quote(ref, safe=''), timeout=5) as response:
            raw = response.read()
        path = self.root / ('data-' + context['attempt_id'] + '.json')
        path.write_bytes(raw)
        return {'success': json.loads(raw).get('data_exists') is True, 'data_ref': ref,
                'evidence_ref': 'file://' + str(path)}
    def cleanup(self, *, contract, context):
        phase = context['phase']
        request = Request(self.url + ('/cleanup' if phase == 'CLEANUP' else '/verify'),
                          method='DELETE' if phase == 'CLEANUP' else 'GET')
        with urlopen(request, timeout=5) as response:
            actual = json.loads(response.read())
        if phase == 'CLEANUP':
            return {'action_receipt': actual}
        return {'data_results': {ref['data_ref']: actual for ref in contract['data_refs']}}


def _profile(url, environment):
    timestamp = datetime.now(timezone.utc).isoformat()
    facts = []
    def fact(kind, identifier, attributes, source=None):
        source = source or 'engineering-fact://%s/%s' % (kind, identifier)
        facts.append(dict(kind=kind, id=identifier, status='READY', attributes=attributes,
                          source_ref=source, verified_at=timestamp))
        return identifier
    release = RELEASE
    env = fact('environment', environment['name'], dict(deployed_release_id=release), environment['source_ref'])
    repos = {app: fact('repository', app, dict(application=app, release_id=release, revision='engineering-source-1')) for app in REQUIRED_REPOSITORIES}
    databases = {app: fact('database', app, dict(application=app, environment_id=env, profile_id='engineering-db-' + app)) for app in REQUIRED_DATABASE_APPS}
    frontend = fact('route', 'frontend', dict(environment_id=env, url=url + '/ui'))
    gateway = fact('route', 'gateway', dict(environment_id=env, url=url))
    auth = fact('auth', 'local-auth', dict(environment_id=env))
    cat = fact('cat', 'local-cat', dict(environment_id=env))
    account = fact('account', 'local-account', dict(environment_id=env))
    return dict(max_age_seconds=3600, facts=facts, selectors=dict(release_id=release, deployment_mode='REMOTE_DEPLOYMENT',
        environment_fact_id=env, repository_fact_ids=repos, frontend_route_fact_id=frontend,
        gateway_route_fact_id=gateway, database_fact_ids=databases, auth_fact_id=auth,
        cat_fact_id=cat, account_fact_id=account))


def _qualify(root, source_case, contract, *, fail=False, emit_tool=True):
    root.mkdir(parents=True, exist_ok=True)
    source = root / 'test_formal_api.py'
    # Business I/O only occurs inside the test, never during collect/readiness.
    code = '''import hashlib,json,os
from pathlib import Path
from urllib.request import Request,urlopen

def test_formal_api():
    assert 'RC72_PARENT_SECRET' not in os.environ
    c=json.loads(os.environ['RC72_EXECUTABLE_CONTRACT'])
    actor=json.loads(os.environ['RC72_ATTEMPT_CONTEXT'])
    with urlopen(Request(c['endpoint']['url'], data=json.dumps(c['input']).encode(), headers={'Content-Type':'application/json'}, method='POST'), timeout=5) as response:
        actual=json.loads(response.read())
    out=Path(os.environ['RC72_OUTPUT_ROOT'])
    out.mkdir(parents=True,exist_ok=True)
    files=[]
    for i,requirement in enumerate(c['evidence_required']):
        data=json.dumps({'request':c['input'],'response':actual},sort_keys=True).encode()
        name=actor['attempt_id']+'-'+str(i)+'.json'
        (out/name).write_bytes(data)
        files.append(dict(requirement=requirement,attempt_id=actor['attempt_id'],tool=c['tool_route']['tool'],path=name,sha256=hashlib.sha256(data).hexdigest()))
    actual['evidence']=files
    with open(os.environ['RC6_EXECUTION_MANIFEST'],'a',encoding='utf-8') as manifest:
        if EMIT_TOOL:
            manifest.write(json.dumps(dict(type='tool_call',tool_id=c['tool_route']['tool'],call_ref='http-call://'+actor['attempt_id'],evidence_ref='file://'+str(out/files[0]['path'])))+'\\n')
        manifest.write(json.dumps(dict(type='actual_result',value=actual))+'\\n')
    assert not FAIL_AFTER_ACTUAL
'''
    # Qualification binds exact UTF-8 bytes. Text-mode Windows writes would
    # translate LF to CRLF while read_text normalizes the candidate back to LF.
    source.write_bytes(code.replace('EMIT_TOOL', str(emit_tool)).replace('FAIL_AFTER_ACTUAL', str(fail)).encode('utf-8'))
    frozen = {k: deepcopy(v) for k, v in source_case.items() if k not in
              {'execution', 'source_artifact_id', 'source_artifact_sha256', 'source_case_sha256'}}
    frozen.update(status='FROZEN', case_version=1, release_id=RELEASE,
                  expected=json.dumps(source_case['expected_results'], ensure_ascii=False, sort_keys=True))
    spec = ExecutableSpecBuilder().build(case=frozen, target_requirements=(contract['requirement_id'],),
        test_data_refs=tuple(ref['data_ref'] for ref in contract['data_refs']), oracle_refs=('oracle://approved-n4',),
        cleanup_policy=contract['cleanup'], runner_type='PYTEST', automation_mapping={'reuse': {}})
    spec_path = root / 'spec.json'
    spec_path.write_text(json.dumps(dict(spec=asdict(spec), frozen_case=frozen, design_content_hash=source_case['source_case_sha256'])), encoding='utf-8')
    mission, task_id, artifact_id, evaluation_id = ['SCRIPT-' + value + '-' + source_case['tc_id'] for value in ('MISSION', 'TASK', 'ART', 'EVAL')]
    binding = dict(spec_id=spec.spec_id, tc_id=spec.tc_id, case_version=spec.case_version,
        runner_type=spec.runner_type, case_fingerprint=spec.case_fingerprint, oracle_fingerprint=spec.oracle_fingerprint,
        design_content_hash=source_case['source_case_sha256'])
    envelope = dict(task_id=task_id, artifact=dict(artifact_id=artifact_id, artifact_type='SCRIPT_MODEL'),
        semantic_payload=dict(binding=binding, source_text=source.read_text(), test_symbol='test_formal_api'))
    candidate = root / 'candidate.json'
    candidate.write_text(json.dumps(envelope), encoding='utf-8')
    truth = TruthRuntime(root / 'r1.jsonl')
    source_evidence = 'SOURCE-' + source_case['tc_id']
    append_entity(truth, Evidence(source_evidence, mission, 'RUNTIME_PERSISTED_SCRIPT_SOURCE',
        'runtime://approved-script', 'file://' + str(source), content_hash='sha256:' + hashlib.sha256(source.read_bytes()).hexdigest()), release_id=RELEASE)
    append_entity(truth, Artifact(artifact_id, mission, 'SCRIPT_MODEL', task_id, 'file://' + str(candidate),
        evidence_refs=[source_evidence], content_hash='sha256:' + hashlib.sha256(candidate.read_bytes()).hexdigest()), release_id=RELEASE)
    append_entity(truth, Evaluation(evaluation_id=evaluation_id, mission_id=mission, node='SCRIPT_READINESS',
        result=EvaluationResult.PASS, evaluator_ref='independent-upstream-reviewer', dimensions={'gate_status': 'SCRIPT_READY', 'business_assertion_executed': False}, artifact_refs=[artifact_id]), release_id=RELEASE)
    append_entity(truth, Task(task_id, mission, 'SCRIPT_READINESS', 'PRODUCE', 'approved engineering script',
        state=TaskStatus.PASS, lease_owner='approved-source-producer', output_artifact_refs=[artifact_id], evaluation_id=evaluation_id), release_id=RELEASE)
    folder = root / 'qualification'
    folder.mkdir()
    result = dict(status='PASS', evaluation_result='PASS', task_state='PASS', validation_status='SCRIPT_READY',
        mission_id=mission, task_id=task_id, evaluation_id=evaluation_id, spec_ref='file://' + str(spec_path),
        spec_id=spec.spec_id, tc_id=spec.tc_id, case_fingerprint=spec.case_fingerprint,
        oracle_fingerprint=spec.oracle_fingerprint, runner_type='PYTEST', source_ref='file://' + str(source))
    (folder / 'result.json').write_text(json.dumps(result), encoding='utf-8')


def formal_setup(tmp_path, monkeypatch, *, fail=False, emit_tool=True, profile_mutator=None, design_mutator=None):
    import test_rc72_n1_executable_binding as n1
    import rc72_integrated_test_support as support
    import test_rc72_n4_test_design_handoff as n4
    server = ThreadingHTTPServer(('127.0.0.1', 0), _Handler)
    server.calls, server.restored, server.allowed_data_refs, server.precondition_ready = [], True, set(), True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = 'http://127.0.0.1:%d' % server.server_address[1]
    original_binding = n1._binding
    def binding():
        raw = original_binding()
        raw['endpoint']['url'] = url + '/config/query'
        profile = _profile(url, raw['environment'])
        if profile_mutator is not None:
            profile_mutator(profile)
        raw['environment'].update(target_profile=profile, deployed_release_id=profile['selectors']['release_id'])
        raw['authoritative_sources'] += [fact['source_ref'] for fact in profile['facts']]
        return raw
    monkeypatch.setattr(n1, '_binding', binding)
    original_install = support.install_execution_sources
    def install(*args):
        original_install(*args)
        original = n4._candidate
        def candidate(*args, **kwargs):
            value = original(*args, **kwargs)
            if design_mutator is not None:
                design_mutator(value)
            for case in value['cases']:
                root = tmp_path / 'qualified' / case['tc_id']
                source_ref = 'approved-runner://' + case['tc_id']
                case['execution']['runner'] = dict(script_result_ref='file://' + str(root / 'qualification' / 'result.json'),
                    cwd=str(root), source_ref=source_ref)
                case['execution']['authoritative_sources'].append(source_ref)
            return value
        monkeypatch.setattr(n4, '_candidate', candidate)
    monkeypatch.setattr(support, 'install_execution_sources', install)
    try:
        truth, plan = _setup(tmp_path, monkeypatch)
        server.allowed_data_refs = {ref['data_ref'] for c in truth.query('rc72_n6_executable_contract') for ref in c['data_refs']}
        design = CanonicalDesignService(truth, release_id=RELEASE, source_commit=COMMIT).load(release_batch_id=BATCH)
        for case in design.cases:
            contract = next(c for c in truth.query('rc72_n6_executable_contract') if c['case_id'] == case['tc_id'])
            _qualify(tmp_path / 'qualified' / case['tc_id'], case, contract, fail=fail, emit_tool=emit_tool)
        return truth, plan, _service(truth), server, url
    except BaseException:
        server.shutdown()
        server.server_close()
        raise
