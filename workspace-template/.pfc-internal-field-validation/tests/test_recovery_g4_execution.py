"""Real loopback runners through governed R1/G3/G4; no bank or model claims.

AITEST_TEST_RUNTIME_SOURCE optionally selects a staged workspace-template.
Fixture OpenCode sessions provide orchestration only. HTTP, pytest, browser,
Git analysis, R1 persistence and enabled k6 execution are actual local work.
"""
from __future__ import annotations
import hashlib
import http.server
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import traceback

SOURCE_WORKSPACE = Path(__file__).resolve().parents[2]
RUNTIME_WORKSPACE = Path(os.environ.get('AITEST_TEST_RUNTIME_SOURCE') or SOURCE_WORKSPACE).resolve()
sys.path.insert(0, str(RUNTIME_WORKSPACE / 'ai-test/runtime'))
from aitest_runtime.canonical_runtime import create_canonical_runtime
from aitest_runtime.autonomous_orchestration import FakeOpenCodeSessionProvider
from aitest_runtime.g2_1.managed_orchestration import G21AutonomousOrchestrationService
from aitest_runtime.g3.service import G3TestingIntelligenceService
from aitest_runtime.g4.service import G4RealExecutionService
from aitest_runtime.r3_3.service import R33ApplicationService
from aitest_runtime.r3_3.contracts import RISK_DIMENSIONS
from aitest_runtime.recovery_intake import RecoveryIntakeService
from aitest_runtime.recovery_executors import OfflineExecutor, digest
# Reuse existing fixture construction helpers only after staged runtime imports.
sys.path.insert(0, str(Path(__file__).parent))
from test_g3_testing_intelligence_product_path import make_repo, intake_request, binding
from test_g4_full_same_mission_product_e2e import exec_task


class Handler(http.server.BaseHTTPRequestHandler):
    requests_seen = 0
    unexpected_side_effects = 0
    def log_message(self, *args):
        pass
    def do_GET(self):
        type(self).requests_seen += 1
        self.send_response(200)
        self.send_header('X-Content-Type-Options', 'nosniff')
        if self.path.startswith('/page'):
            body = b'<html><body><h1 id="status">Ready</h1></body></html>'
            self.send_header('Content-Type', 'text/html; charset=utf-8')
        else:
            body = b'{"ok":true,"service":"local-fixture"}'
            self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def do_POST(self):
        type(self).unexpected_side_effects += 1
        self.send_error(405)


def run(root: Path) -> dict:
    checks = {}
    capabilities = {}
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    origin = f'http://127.0.0.1:{server.server_port}'
    old = {key: os.environ.get(key) for key in ('AITEST_WORKSPACE_ROOT', 'AITEST_RUNTIME_SPINE_DB', 'PFC_LOCAL_STATE_ROOT', 'AITEST_DB_PATH')}
    db = root / 'state/runtime-spine.db'
    legacy = root / 'forbidden-legacy/aitest.db'
    os.environ.update(AITEST_WORKSPACE_ROOT=str(root), AITEST_RUNTIME_SPINE_DB=str(db), PFC_LOCAL_STATE_ROOT=str(root), AITEST_DB_PATH=str(legacy))
    try:
        runtime = create_canonical_runtime(root, db_path=db)
        orch = G21AutonomousOrchestrationService(runtime, root, session_provider=FakeOpenCodeSessionProvider(root))
        request = intake_request()
        request.pop('resolution', None)
        request.update(intake_id='real-local-g4-execution', scope={'mode': 'EXPLICIT_SET', 'project_id': 'LOCAL-VALIDATION', 'version': '1.12.0'})
        started = orch.start_test(request)
        mission = started['intake']['intake']['mission_id']
        checks['default_intake_uses_r1_without_bank_resolution_injection'] = started['intake']['intake']['resolution']['status'] == 'BLOCKED'
        repo, base, head = make_repo(root, 'local-target',
            {'src/loan.py': 'def accepts(amount):\n    return amount > 1\n'},
            {'src/loan.py': 'def accepts(amount):\n    return amount > 0\n'})
        document = root / 'requirement.md'
        document.write_text('Loan amount must be positive. The local service must expose readiness in API and browser.\n', encoding='utf-8')
        intake = RecoveryIntakeService(runtime)
        source = intake.import_document(mission, document, 'LOCAL-REQUIREMENT')['document']['fact_id']
        artifacts = [
            {'artifact_id': 'BR-1', 'kind': 'BR', 'text': 'Loan amount must be positive', 'source_refs': [source], 'asset_refs': [{'kind': 'CODE', 'ref': 'src/loan.py'}]},
            {'artifact_id': 'SR-1', 'kind': 'SR', 'text': 'The local service readiness API responds with ok true', 'source_refs': [source], 'parent_refs': ['BR-1'], 'asset_refs': [{'kind': 'CODE', 'ref': 'src/loan.py'}]},
            {'artifact_id': 'TR-1', 'kind': 'TR', 'text': 'Validate local readiness over HTTP, browser rendering and native unit assertions', 'source_refs': [source], 'parent_refs': ['SR-1'], 'asset_refs': [{'kind': 'CODE', 'ref': 'src/loan.py'}]},
        ]
        analysis = intake.analyze_requirements(mission, 'LOCAL-REQUIREMENT', artifacts)
        g3 = G3TestingIntelligenceService(runtime)
        change = g3.analyze_changes(mission, 'LOCAL-REQUIREMENT', [{'repository_id': 'local-target', 'application_id': 'local-target', 'repository_path': str(repo), 'base_ref': base, 'head_ref': head}], analysis['r3_1_reference'])
        risk = {'dimensions': {name: 2 for name in RISK_DIMENSIONS}, 'evidence_refs': [analysis['analysis']['requirement']['fact_id'], change['change_analysis']['fact_id']]}
        strategy = g3.create_strategy(mission, 'LOCAL-REQUIREMENT', analysis['r3_1_reference'], change['r3_2_references'], risk)
        sid = strategy['strategy']['strategy_version_id']
        points = [point for point in R33ApplicationService(runtime).state(mission).test_points if point.strategy_version_id == sid and point.designability == 'DESIGNABLE'][:1]
        assert points, 'real G3 strategy produced no designable case'
        specs = {point.point_id: {
            'objective': 'Verify local readiness through concrete execution assertions',
            'preconditions': ['Approved loopback fixture is listening'],
            'test_data': {'amount': 1, 'readiness_path': '/api'},
            'ordered_steps': [{'step': 1, 'action': 'Execute the locally approved readiness runner'}],
            'expected_results': [{'step': 1, 'expected': 'HTTP 200 and ok true; page shows Ready; unit assertion succeeds'}],
            'oracle': {'type': 'EXPLICIT_ASSERTIONS', 'pass': 'Runner assertions all succeed'},
            'evidence_requirements': [{'channel': 'PROVIDER_RESULT', 'required': 'hashed execution receipt bound to the canonical attempt'}],
            'postcondition': {'cleanup': 'close temporary resources'},
        } for point in points}
        designed = g3.design_cases(mission, sid, strategy['strategy']['strategy_fingerprint'], specs)
        assert designed['ready_cases'], designed
        case_fact = designed['ready_cases'][0]['case']
        case = case_fact['payload']['r3_3_case']
        checks['br_sr_tr_to_real_g3_case'] = bool(set(case['coverage_obligation_refs']) & {item['fact_id'] for item in analysis['artifacts']})
        executable = str(Path(sys.executable).resolve())
        test = root / 'test_local_unit.py'
        test.write_text('def test_actual_local_contract():\n    assert sum([2, 3, 5]) == 10\n')
        config = {'approved': True, 'approval_ref': 'fixture:local-runner-approval', 'allowed_origins': [origin], 'allowed_methods': ['GET', 'HEAD'],
                  'native_runners': {'local-pytest': {'cwd': str(root), 'argv': [executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', str(test)], 'executable_sha256': digest(executable)}}}
        chrome = Path(os.environ.get('AITEST_TEST_CHROMIUM') or ('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' if sys.platform == 'darwin' else RUNTIME_WORKSPACE / 'runtime/browser/chrome-win64/chrome.exe'))
        if chrome.is_file() and os.name != 'nt':
            config['local_chromium_path'] = str(chrome)
        providers = {name: OfflineExecutor(RUNTIME_WORKSPACE, name, config) for name in ('API', 'UNIT', 'SECURITY', 'BROWSER_UI', 'PERFORMANCE')}
        g4 = G4RealExecutionService(runtime, orchestration=orch, capability_executors=providers)
        g4.create_goal(mission, {'goal_id': 'local-goal', 'project_id': 'LOCAL-VALIDATION', 'release_id': '1.12.0', 'requirement_scope': ['LOCAL-REQUIREMENT'], 'affected_applications': ['local-target'], 'affected_application_target_versions': {'local-target': '1.12.0'}, 'coverage_policy': {'target_pct': 95}})
        g4.create_batch(mission, {'batch_id': 'local-batch', 'goal_id': 'local-goal', 'case_refs': [case_fact['fact_id']], 'strategy_version_id': sid, 'target_application': 'local-target', 'status': 'RUNNING'})
        plan = orch.propose_plan(mission, {'objective': 'Run local offline validation against governed G3 case', 'tasks': [exec_task('real-local-execution', case_fact['fact_id'])], 'dependencies': []})
        bound = binding(plan['next'])
        scope = {'origins': [origin], 'runner_ids': ['local-pytest'], 'environment': 'LOCAL_FIXTURE'}
        security = g3.design_test_profile(mission, 'SECURITY', {'authorized_scope': scope, 'oracle': {'pass': 'required passive headers present'},
                   'safety_contract': {'target_environment': 'LOCAL_FIXTURE', 'rate_limits': {'rps': 1}, 'safety_limits': {'destructive': False, 'max_requests': 1}, 'stop_conditions': ['request failure'], 'destructive': False}})['profile']['fact_id']
        performance = g3.design_test_profile(mission, 'PERFORMANCE', {'authorized_scope': scope, 'oracle': {'pass': 'p95 below explicit bound'}, 'slo': {'p95_ms': 500},
                      'safety_contract': {'target_environment': 'LOCAL_FIXTURE', 'load_model': {'vus': 1, 'duration_s': 1}, 'resource_limits': {'max_vus': 1, 'max_duration_s': 1}, 'stop_conditions': ['request failure']}})['profile']['fact_id']

        def execute(name, step_id, expected, runner_request, profile=None):
            data = {**bound, 'capability_id': name, 'case_id': case['tc_id'], 'case_version': case['case_version_id'], 'case_spec_fact_id': case_fact['fact_id'], 'execution_batch_id': 'local-batch',
                    'executor_request': runner_request, 'step': {'step_id': step_id, 'expected': expected}, 'execution_node': 'REAL_LOCAL_FIXTURE'}
            if profile:
                data['g3_test_profile_fact_id'] = profile
            return g4.execute_capability(mission, data)

        common = {'url': origin + '/api', 'method': 'GET', 'authorized_scope': scope}
        for name, expected, runner_request, profile in [
            ('API', {'status_code': 200, 'json_subset': {'ok': True}}, common, None),
            ('SECURITY', {'required_headers': ['x-content-type-options']}, common, security),
            ('UNIT', {'exit_code': 0}, {'runner_id': 'local-pytest', 'authorized_scope': scope}, None),
        ]:
            result = execute(name, 'real-' + name.lower(), expected, runner_request, profile)
            capabilities[name] = {'status': result['status'], 'execution': result['execution'], 'fact_id': result.get('result', {}).get('fact_id'), 'scope': 'REAL_LOCAL_FIXTURE'}
            checks[name.lower() + '_real_g4_execution'] = result['status'] == 'PASS' and result['execution'] == 'COMPLETED'
        if chrome.is_file():
            result = execute('BROWSER_UI', 'real-ui', {'selector': '#status', 'text': 'Ready'}, {**common, 'url': origin + '/page', 'browser_context_ref': 'local-isolated-smoke-context'})
            capabilities['UI'] = {'status': result['status'], 'execution': result['execution'], 'fact_id': result.get('result', {}).get('fact_id'), 'scope': 'REAL_LOCAL_FIXTURE'}
            checks['ui_real_g4_execution'] = result['status'] == 'PASS'
        else:
            capabilities['UI'] = {'status': 'NOT_RUN_PAYLOAD_UNAVAILABLE', 'required': str(chrome)}
        k6 = RUNTIME_WORKSPACE / 'runtime/tools/k6' / ('k6.exe' if os.name == 'nt' else 'k6')
        if k6.is_file():
            result = execute('PERFORMANCE', 'real-k6', {'p95_ms': 500}, common, performance)
            capabilities['Performance'] = {'status': result['status'], 'execution': result['execution'], 'fact_id': result.get('result', {}).get('fact_id'), 'scope': 'REAL_LOCAL_FIXTURE'}
            checks['performance_real_g4_execution'] = result['status'] == 'PASS'
        else:
            capabilities['Performance'] = {'status': 'NOT_RUN_PAYLOAD_UNAVAILABLE', 'required': str(k6)}
        failure = execute('API', 'intentional-oracle-failure', {'status_code': 201}, common)
        checks['failed_assertion_is_evidenced_not_confirmed_defect'] = failure['status'] == 'FAIL' and bool(g4.state(mission).by_kind('UNEXPECTED_OBSERVATION'))
        requests_before = Handler.requests_seen
        denied = execute('API', 'denied-scope', {'status_code': 200}, {**common, 'authorized_scope': {'origins': ['http://outside.invalid']}})
        checks['out_of_scope_target_no_http_side_effect'] = denied['status'] == 'FAIL' and Handler.requests_seen == requests_before
        restart = create_canonical_runtime(root, db_path=db)
        facts = G4RealExecutionService(restart).state(mission).by_kind('EXECUTION_STEP_RESULT')
        checks['r1_restart_retains_same_attempt_case_and_evidence'] = bool(facts) and all(f.payload['attempt_id'] == bound['attempt_id'] and f.payload['case_version'] == case['case_version_id'] and f.payload['evidence_refs'] for f in facts)
        verified = True
        for fact in facts:
            for ref in fact.payload['evidence_refs']:
                _, _, sha, filename = ref.split(':', 3)
                evidence = root / 'evidence/executions' / filename
                verified = verified and evidence.is_file() and digest(evidence) == sha
        checks['all_canonical_evidence_references_match_real_bytes'] = verified
        checks['no_legacy_truth_database'] = not legacy.exists()
        checks['no_unapproved_http_method_executed'] = Handler.unexpected_side_effects == 0
        if os.name == 'nt' or os.environ.get('AITEST_REQUIRE_WINDOWS_PAYLOADS') == '1':
            checks['all_windows_runner_payloads_executed'] = all(capabilities[name]['status'] == 'PASS' for name in ('API', 'UNIT', 'SECURITY', 'UI', 'Performance'))
        result = {'status': 'PASS' if all(checks.values()) else 'FAIL', 'classification': 'LOCAL_VALIDATION_PASS' if all(checks.values()) else 'LOCAL_VALIDATION_FAIL',
                  'checks': checks, 'failed': [name for name, passed in checks.items() if not passed], 'capabilities': capabilities,
                  'mission_id': mission, 'r1_event_count': restart.get_head_seq(mission), 'evidence_count': len(facts),
                  'orchestration': 'FIXTURE_OPENCODE_SESSIONS_ONLY', 'bank_field_validation': 'BANK_FIELD_VALIDATION_REQUIRED',
                  'actual_bank_coverage': 'NOT_ASSERTED', 'security_runner': 'API_PASSIVE_BASELINE_NOT_ZAP', 'runtime_source': str(RUNTIME_WORKSPACE)}
        (root / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        return result
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=5)
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def main():
    configured = os.environ.get('AITEST_TEST_EVIDENCE_ROOT')
    try:
        if configured:
            root = Path(configured) / 'recovery-g4-execution'
            root.mkdir(parents=True, exist_ok=False)
            result = run(root)
        else:
            with tempfile.TemporaryDirectory(prefix='recovery-g4-execution-') as temp:
                result = run(Path(temp))
    except Exception as exc:
        result = {'status': 'FAIL', 'error_type': type(exc).__name__, 'error': str(exc), 'traceback': traceback.format_exc(), 'bank_field_validation': 'BANK_FIELD_VALIDATION_REQUIRED'}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
