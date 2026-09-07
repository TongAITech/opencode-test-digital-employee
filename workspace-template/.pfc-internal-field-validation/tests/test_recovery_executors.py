"""Real local HTTP/pytest smoke plus admission negatives. No bank PASS."""
from __future__ import annotations
import http.server
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE / 'ai-test/runtime'))
from aitest_runtime.recovery_executors import OfflineExecutor, allowed_url, bounded_process, digest
from aitest_runtime.durable_core import RuntimeError


class Handler(http.server.BaseHTTPRequestHandler):
    request_count = 0
    def log_message(self, *args): pass
    def do_GET(self):
        type(self).request_count += 1
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers(); self.wfile.write(b'{"ok":true}')


class TestOfflineExecutors(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True); cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.old_state = os.environ.pop('PFC_LOCAL_STATE_ROOT', None)
        self.config = {'approved': True, 'approval_ref': 'construction:local-only', 'allowed_origins': [self.url]}
        self.request = {'url': self.url, 'method': 'GET', 'authorized_scope': {'origins': [self.url]}}

    def tearDown(self):
        if self.old_state is not None: os.environ['PFC_LOCAL_STATE_ROOT'] = self.old_state
        self.temp.cleanup()

    def execute(self, name, expected, request=None, config=None):
        provider = OfflineExecutor(self.root, name, config or self.config)
        prepared = provider.prepare({'step_id': 'one', 'expected': expected}, {'mission_id': 'local-smoke'})
        result = provider.execute(prepared, {'executor_request': request or self.request})
        self.assertEqual(len(provider.collect_evidence(result)), 1)
        self.assertEqual(len(list((self.root / 'evidence/executions').glob('*.json'))), 1)
        return result

    def test_real_http_assertion_and_evidence(self):
        result = self.execute('API', {'status_code': 200, 'json_subset': {'ok': True}})
        self.assertEqual(result['oracle_result'], 'PASS')
        self.assertNotIn('body', json.dumps(result))

    def test_mismatched_oracle_is_failure(self):
        self.assertEqual(self.execute('API', {'status_code': 201})['oracle_result'], 'FAIL')

    def test_scope_escape_is_blocked(self):
        with self.assertRaises(RuntimeError): allowed_url('http://elsewhere.invalid', self.config, self.request)
        with self.assertRaises(RuntimeError): allowed_url(self.url, self.config, {**self.request, 'authorized_scope': {}})
        with self.assertRaises(RuntimeError): allowed_url('http://user:secret@127.0.0.1', self.config, self.request)

    def test_unapproved_binding_fails_before_execution(self):
        with self.assertRaises(RuntimeError): OfflineExecutor(self.root, 'API', {}).prepare({}, {})

    def test_security_is_explicit_passive_baseline(self):
        request = {**self.request, 'safety_limits': {'max_requests': 1}, 'rate_limits': {'rps': 1}, 'stop_conditions': ['error']}
        result = self.execute('SECURITY', {'required_headers': ['x-content-type-options']}, request)
        self.assertEqual(result['oracle_result'], 'PASS')
        self.assertEqual(result['actual']['runner'], 'API_PASSIVE_BASELINE_NOT_ZAP')

    def test_real_pytest_bound_runner(self):
        test = self.root / 'test_local.py'; test.write_text('def test_sum():\n    assert 2 + 3 == 5\n')
        executable = str(Path(sys.executable).resolve())
        config = {**self.config, 'native_runners': {'pytest-smoke': {'cwd': str(self.root),
            'argv': [executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', str(test)],
            'executable_sha256': digest(executable)}}}
        result = self.execute('UNIT', {'exit_code': 0}, {'runner_id': 'pytest-smoke', 'authorized_scope': {'runner_ids': ['pytest-smoke']}}, config)
        self.assertEqual(result['oracle_result'], 'PASS', result)

    def test_native_runner_hash_mismatch(self):
        config = {**self.config, 'native_runners': {'bad': {'cwd': str(self.root), 'argv': [sys.executable, '-c', 'pass'], 'executable_sha256': '0' * 64}}}
        result = self.execute('UNIT', {}, {'runner_id': 'bad', 'authorized_scope': {'runner_ids': ['bad']}}, config)
        self.assertEqual(result['oracle_result'], 'FAIL')
        self.assertEqual(result['actual']['error_code'], 'RECOVERY_NATIVE_RUNNER_IDENTITY_MISMATCH')

    def test_native_runner_id_must_be_inside_authorized_scope(self):
        executable = str(Path(sys.executable).resolve())
        config = {**self.config, 'native_runners': {'allowed': {'cwd': str(self.root), 'argv': [executable, '-c', 'pass'], 'executable_sha256': digest(executable)}}}
        result = self.execute('UNIT', {'exit_code': 0}, {'runner_id': 'allowed', 'authorized_scope': {'runner_ids': ['different']}}, config)
        self.assertEqual(result['actual']['error_code'], 'RECOVERY_NATIVE_RUNNER_OUTSIDE_SCOPE')

    def test_oracle_rejected_before_http(self):
        before = Handler.request_count
        result = self.execute('API', {'status_code': True})
        self.assertEqual(result['actual']['error_code'], 'RECOVERY_EXPLICIT_ORACLE_REQUIRED')
        self.assertEqual(Handler.request_count, before)

    def test_security_rejects_nonpositive_and_fractional_budgets(self):
        before = Handler.request_count
        for max_requests, rps in ((-1, 1), (0.5, 1), (1, -2), (1, float('inf'))):
            provider = OfflineExecutor(self.root, 'SECURITY', self.config)
            prepared = provider.prepare({'expected': {'required_headers': ['x-content-type-options']}}, {})
            result = provider.execute(prepared, {'executor_request': {**self.request, 'safety_limits': {'max_requests': max_requests}, 'rate_limits': {'rps': rps}, 'stop_conditions': ['error']}})
            self.assertEqual(result['actual']['error_code'], 'RECOVERY_SECURITY_CONTRACT_REQUIRED')
        self.assertEqual(Handler.request_count, before)

    def test_child_output_and_time_are_bounded(self):
        with self.assertRaisesRegex(RuntimeError, 'RECOVERY_OUTPUT_BUDGET_EXCEEDED'):
            bounded_process([sys.executable, '-c', 'import os; os.write(1,b"x"*1000000)'], output_limit=4096)
        with self.assertRaisesRegex(RuntimeError, 'RECOVERY_PROCESS_TIMEOUT'):
            bounded_process([sys.executable, '-c', 'import time; time.sleep(5)'], timeout_s=0.1)

    def test_child_output_is_hashed_without_returning_raw_text(self):
        result = bounded_process([sys.executable, '-c', 'print("native-output")'])
        self.assertEqual(result['exit_code'], 0)
        self.assertGreater(result['output_bytes'], 0)
        self.assertNotIn('native-output', json.dumps(result))


if __name__ == '__main__': unittest.main()
