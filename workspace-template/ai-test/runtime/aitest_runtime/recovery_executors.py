"""Offline execution adapters; G4 remains the admission and Evidence authority.

No package manager is invoked here. Target origins and native runner identities
come from a locally approved binding. Raw headers/bodies/stdio never enter R1.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import uuid
import threading
from pathlib import Path
from urllib.parse import urlsplit

from .durable_core import RuntimeError


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def binding(root):
    path = Path(root) / 'bindings' / 'execution.json'
    if not path.is_file():
        return {}
    result = json.loads(path.read_text(encoding='utf-8'))
    if result.get('approved') is not True or not result.get('approval_ref'):
        return {}
    return result


def safe_binding_context(root):
    """Read approved execution identities without exposing local secrets/argv.

    This is configuration discovery only. G4 still admits the actual request,
    checks its scope and runner identity, and records execution Evidence in R1.
    """
    config = binding(root)
    if not config:
        return {'status': 'BANK_BINDING_REQUIRED', 'binding_source': 'LOCAL_APPROVED_CONFIGURATION',
                'allowed_origins': [], 'allowed_methods': [], 'native_runner_ids': [],
                'authorized_scope': {'origins': [], 'runner_ids': []}}
    origins = []
    for item in config.get('allowed_origins') or []:
        parsed = urlsplit(str(item))
        if parsed.scheme in ('http', 'https') and parsed.hostname and not parsed.username and not parsed.password and parsed.path in ('', '/') and not parsed.query and not parsed.fragment:
            origins.append(f'{parsed.scheme}://{parsed.netloc}'.lower())
    methods = [str(item).upper() for item in config.get('allowed_methods', ['GET', 'HEAD'])
               if str(item).upper() in {'GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'}]
    runners = [str(key) for key, value in (config.get('native_runners') or {}).items()
               if isinstance(value, dict) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}', str(key))]
    auth_ref = config.get('auth_env_ref')
    auth_ready = not auth_ref or bool(re.fullmatch(r'[A-Z][A-Z0-9_]+', str(auth_ref)) and os.environ.get(auth_ref))
    result = {'status': 'READY' if origins or runners else 'BANK_BINDING_REQUIRED',
            'binding_source': 'LOCAL_APPROVED_CONFIGURATION', 'approval_ref': config['approval_ref'],
            'allowed_origins': sorted(set(origins)), 'allowed_methods': sorted(set(methods)),
            'native_runner_ids': sorted(runners), 'auth_state': 'READY' if auth_ready else 'AUTH_REQUIRED',
            'authorized_scope': {'origins': sorted(set(origins)), 'runner_ids': sorted(runners)},
            'execution_requires_g4_admission': True, 'native_identity_check': 'REQUIRED_BEFORE_EXECUTION'}
    from .r2_1.contracts import validate_secret_boundary
    validate_secret_boundary(result)
    return result


def allowed_url(url, config, request):
    parsed = urlsplit(str(url))
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise RuntimeError('RECOVERY_TARGET_INVALID', 'absolute HTTP(S) URL without credentials required')
    origin = f'{parsed.scheme}://{parsed.netloc}'.lower()
    configured = [str(x).rstrip('/').lower() for x in config.get('allowed_origins', [])]
    scope = request.get('authorized_scope') or {}
    requested = [str(x).rstrip('/').lower() for x in scope.get('origins', [])]
    if origin not in configured or origin not in requested:
        raise RuntimeError('RECOVERY_TARGET_OUTSIDE_APPROVED_SCOPE', origin)
    return str(url)


def bounded_process(argv, *, cwd=None, timeout_s=120, env=None, output_limit=8 * 1024 * 1024):
    """Stream/hash child output with a hard memory budget; never persist raw stdio."""
    timeout_s = float(timeout_s)
    if not math.isfinite(timeout_s) or not 0 < timeout_s <= 900:
        raise RuntimeError('RECOVERY_PROCESS_BUDGET_INVALID', 'timeout must be 0..900 seconds')
    options = {'start_new_session': True} if os.name != 'nt' else {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP}
    process = subprocess.Popen(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, shell=False, **options)
    observed = {'bytes': 0, 'hash': hashlib.sha256()}
    overflow = threading.Event()

    def terminate_tree():
        if os.name == 'nt':
            subprocess.run(['taskkill.exe', '/PID', str(process.pid), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def consume():
        while True:
            chunk = process.stdout.read(65536)
            if not chunk:
                break
            observed['bytes'] += len(chunk)
            observed['hash'].update(chunk)
            if observed['bytes'] > output_limit:
                overflow.set()
                break

    reader = threading.Thread(target=consume, daemon=True)
    reader.start()
    deadline = time.monotonic() + timeout_s
    timed_out = False
    try:
        while process.poll() is None:
            if overflow.is_set() or time.monotonic() >= deadline:
                timed_out = not overflow.is_set()
                terminate_tree()
                break
            time.sleep(0.02)
        process.wait(timeout=10)
        reader.join(timeout=2)
        if reader.is_alive():
            terminate_tree()
            reader.join(timeout=2)
        if overflow.is_set():
            raise RuntimeError('RECOVERY_OUTPUT_BUDGET_EXCEEDED', str(output_limit))
        if timed_out or reader.is_alive():
            raise RuntimeError('RECOVERY_PROCESS_TIMEOUT', str(timeout_s))
        return {'exit_code': process.returncode, 'output_sha256': observed['hash'].hexdigest(), 'output_bytes': observed['bytes']}
    finally:
        if process.poll() is None:
            terminate_tree()
            process.wait(timeout=10)
        if not reader.is_alive():
            process.stdout.close()


class OfflineExecutor:
    capability_status = 'AVAILABLE'
    safety_profile = {'binding_required': True, 'scope_enforced': True, 'runtime_install': False}
    auth_requirements = {'mode': 'LOCAL_BINDING_OR_HUMAN'}
    side_effect_classification = 'GOVERNED_TEST'
    retry_semantics = {'automatic_retry': False}
    evidence_channels = ('PROVIDER_RESULT',)

    def __init__(self, root, capability_id, config=None):
        self.root = Path(root).resolve()
        self.capability_id = capability_id
        self.config = dict(config if config is not None else binding(self.root))
        self.evidence = Path(os.environ.get('PFC_LOCAL_STATE_ROOT') or self.root) / 'evidence' / 'executions'

    def prepare(self, step, runtime_facts):
        if not self.config.get('approved') or not self.config.get('approval_ref'):
            raise RuntimeError('RECOVERY_BANK_BINDING_REQUIRED', self.capability_id)
        return {'step': dict(step), 'lineage': dict(runtime_facts)}

    def execute(self, prepared, execution_context):
        request = dict(execution_context.get('executor_request') or {})
        started = time.monotonic()
        # Exceptions are normalized to failure evidence after admission. No automatic
        # retries: the Runtime must decide whether a repeat is safe.
        try:
            actual, passed = getattr(self, '_run_' + self.capability_id.lower())(prepared['step'], request)
            reason = 'Explicit runner assertions satisfied' if passed else 'Runner assertion failed'
        except Exception as exc:
            actual, passed = {'error_type': type(exc).__name__, 'error_code': getattr(exc, 'code', 'RUNNER_FAILED')}, False
            reason = 'Runner failed; inspect binding and local diagnostics'
        value = {'capability': self.capability_id, 'actual': actual, 'oracle_result': 'PASS' if passed else 'FAIL',
                 'oracle_reason': reason, 'elapsed_ms': round((time.monotonic() - started) * 1000),
                 'lineage': prepared['lineage'], 'source_identity': 'recovery-offline-runner:1.9.5',
                 'side_effect_summary': 'Bounded execution against approved target'}
        self.evidence.mkdir(parents=True, exist_ok=True)
        path = self.evidence / (uuid.uuid4().hex + '.json')
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        return {**value, 'evidence_refs': [f'artifact:sha256:{digest(path)}:{path.name}']}

    def observe(self, result):
        return {k: result[k] for k in ('actual', 'oracle_result', 'oracle_reason', 'source_identity', 'side_effect_summary')}

    def collect_evidence(self, result):
        return result['evidence_refs']

    def cleanup(self, result):
        return {'cleaned': True}

    def _http(self, request):
        import httpx
        url = allowed_url(request.get('url'), self.config, request)
        method = str(request.get('method') or 'GET').upper()
        allowed = self.config.get('allowed_methods', ['GET', 'HEAD'])
        if method not in allowed:
            raise RuntimeError('RECOVERY_METHOD_NOT_APPROVED', method)
        headers = {}
        env_name = self.config.get('auth_env_ref')
        if env_name:
            if not re.fullmatch(r'[A-Z][A-Z0-9_]+', env_name) or not os.environ.get(env_name):
                raise RuntimeError('RECOVERY_AUTH_REQUIRED', 'binding environment reference not available')
            headers['Authorization'] = os.environ[env_name]
        # Disable redirects so an approved origin cannot redirect to another system.
        # Cap the response stream before allocation and never persist response bodies.
        with httpx.Client(timeout=min(float(request.get('timeout_s', 10)), 30), follow_redirects=False, trust_env=False) as client:
            with client.stream(method, url, headers=headers, json=request.get('json')) as response:
                content = bytearray()
                for block in response.iter_bytes():
                    content.extend(block)
                    if len(content) > 2 * 1024 * 1024:
                        raise RuntimeError('RECOVERY_RESPONSE_BUDGET_EXCEEDED', '2MiB')
                return response.status_code, dict(response.headers), bytes(content)

    def _run_api(self, step, request):
        expected = step.get('expected')
        if not isinstance(expected, dict) or isinstance(expected.get('status_code'), bool) or not isinstance(expected.get('status_code'), int):
            raise RuntimeError('RECOVERY_EXPLICIT_ORACLE_REQUIRED', 'step.expected.status_code')
        if not 100 <= expected['status_code'] <= 599 or 'json_subset' in expected and not isinstance(expected['json_subset'], dict):
            raise RuntimeError('RECOVERY_EXPLICIT_ORACLE_REQUIRED', 'valid HTTP status and JSON subset object required')
        code, headers, body = self._http(request)
        checks = {'status_code': code == expected['status_code']}
        if 'json_subset' in expected:
            obj = json.loads(body)
            checks['json_subset'] = isinstance(obj, dict) and all(obj.get(k) == v for k, v in expected['json_subset'].items())
        return {'status_code': code, 'response_sha256': hashlib.sha256(body).hexdigest(), 'bytes': len(body), 'checks': checks}, all(checks.values())

    def _run_security(self, step, request):
        limits = request.get('safety_limits') or {}
        rates = request.get('rate_limits') or {}
        max_requests = limits.get('max_requests')
        rps = rates.get('rps')
        if (request.get('destructive') or not request.get('stop_conditions') or
            isinstance(max_requests, bool) or not isinstance(max_requests, int) or max_requests < 1 or
            isinstance(rps, bool) or not isinstance(rps, (int, float)) or not math.isfinite(rps) or rps <= 0):
            raise RuntimeError('RECOVERY_SECURITY_CONTRACT_REQUIRED', 'limits and stop conditions')
        required = (step.get('expected') or {}).get('required_headers')
        if not isinstance(required, list) or not required:
            raise RuntimeError('RECOVERY_EXPLICIT_ORACLE_REQUIRED', 'required_headers')
        # A single passive HTTP inspection, explicitly not a ZAP active scan.
        # Waiting one approved interval also respects sub-1-RPS profiles.
        if rps < 1:
            if 1 / rps > 30:
                raise RuntimeError('RECOVERY_SECURITY_CONTRACT_REQUIRED', 'rate interval exceeds bounded runner budget')
            time.sleep(1 / rps)
        request = {**request, 'method': 'GET'}
        code, headers, body = self._http(request)
        missing = [str(k).lower() for k in required if str(k).lower() not in headers]
        return {'runner': 'API_PASSIVE_BASELINE_NOT_ZAP', 'request_count': 1, 'status_code': code,
                'missing_headers': missing, 'response_sha256': hashlib.sha256(body).hexdigest()}, not missing and code < 500

    def _run_unit(self, step, request):
        runner_id = str(request.get('runner_id') or '')
        if runner_id not in (request.get('authorized_scope') or {}).get('runner_ids', []):
            raise RuntimeError('RECOVERY_NATIVE_RUNNER_OUTSIDE_SCOPE', runner_id)
        spec = (self.config.get('native_runners') or {}).get(runner_id)
        if not isinstance(spec, dict):
            raise RuntimeError('RECOVERY_NATIVE_RUNNER_BINDING_REQUIRED', runner_id)
        cwd = Path(spec['cwd']).resolve()
        argv = spec.get('argv')
        if not cwd.is_dir() or not isinstance(argv, list) or not argv or any(not isinstance(x, str) for x in argv):
            raise RuntimeError('RECOVERY_NATIVE_RUNNER_INVALID', runner_id)
        # Commands are authored and approved locally, never arbitrary model shell text.
        executable = Path(argv[0]).resolve()
        if not executable.is_file() or digest(executable) != spec.get('executable_sha256'):
            raise RuntimeError('RECOVERY_NATIVE_RUNNER_IDENTITY_MISMATCH', runner_id)
        expected = step.get('expected')
        if not isinstance(expected, dict) or expected.get('exit_code') != 0:
            raise RuntimeError('RECOVERY_EXPLICIT_ORACLE_REQUIRED', 'native runner requires expected.exit_code=0')
        completed = bounded_process([str(executable), *argv[1:]], cwd=cwd,
                                    timeout_s=min(float(spec.get('timeout_s', 120)), 900),
                                    env={**os.environ, 'PIP_NO_INDEX': '1', 'npm_config_offline': 'true'})
        return {'runner_id': runner_id, **completed}, completed['exit_code'] == 0

    def _run_performance(self, step, request):
        url = allowed_url(request.get('url'), self.config, request)
        if 'GET' not in self.config.get('allowed_methods', ['GET', 'HEAD']):
            raise RuntimeError('RECOVERY_METHOD_NOT_APPROVED', 'GET')
        model, limits = request.get('load_model') or {}, request.get('resource_limits') or {}
        vus = int(model.get('vus', 1)); duration = int(model.get('duration_s', 1))
        if not request.get('stop_conditions') or not (1 <= vus <= min(int(limits.get('max_vus', 1)), 10)) or not (1 <= duration <= min(int(limits.get('max_duration_s', 10)), 60)):
            raise RuntimeError('RECOVERY_LOAD_BUDGET_INVALID', 'VUs/duration/stop conditions')
        # A fixed local script prevents arbitrary JavaScript or scope expansion.
        k6 = self.root / 'runtime' / 'tools' / 'k6' / ('k6.exe' if os.name == 'nt' else 'k6')
        if not k6.is_file():
            raise RuntimeError('RECOVERY_K6_PAYLOAD_REQUIRED', 'runtime/tools/k6')
        slo = request.get('slo') or {}
        threshold = float(slo.get('p95_ms', 0))
        if not math.isfinite(threshold) or threshold <= 0:
            raise RuntimeError('RECOVERY_EXPLICIT_ORACLE_REQUIRED', 'slo.p95_ms')
        script = "import http from 'k6/http'; import {sleep} from 'k6';\n" + 'export const options=' + json.dumps({
            'vus': vus, 'duration': f'{duration}s', 'maxRedirects': 0,
            'thresholds': {'http_req_duration': [f'p(95)<{threshold}'], 'http_req_failed': [{'threshold': 'rate<0.01', 'abortOnFail': True}]}}) + ';\n' + \
            'export default function(){ http.get(' + json.dumps(url) + ',{timeout:"5s",redirects:0});sleep(1); }\n'
        with tempfile.TemporaryDirectory(prefix='aitest-k6-') as folder:
            source = Path(folder) / 'test.js'; source.write_text(script, encoding='utf-8')
            summary = Path(folder) / 'summary.json'
            completed = bounded_process([str(k6), 'run', '--quiet', '--summary-export', str(summary), str(source)],
                                       timeout_s=duration + 20,
                                       env={**os.environ, 'K6_NO_USAGE_REPORT': 'true', 'K6_WEB_DASHBOARD': 'false',
                                            'HTTP_PROXY': '', 'HTTPS_PROXY': '', 'ALL_PROXY': '', 'http_proxy': '', 'https_proxy': '', 'all_proxy': ''})
            metrics = json.loads(summary.read_text()) if summary.is_file() else {}
        duration_metrics = metrics.get('metrics', {}).get('http_req_duration', {})
        duration_values = duration_metrics.get('values', duration_metrics)
        observed_p95 = duration_values.get('p(95)')
        if not isinstance(observed_p95, (int, float)) or not math.isfinite(observed_p95):
            observed_p95 = None
        return {'runner': 'k6', **completed, 'vus': vus, 'duration_s': duration,
                'observed_p95_ms': observed_p95, 'required_p95_ms': threshold,
                'summary_sha256': hashlib.sha256(json.dumps(metrics, sort_keys=True).encode()).hexdigest()}, completed['exit_code'] == 0 and observed_p95 is not None and observed_p95 < threshold

    def _run_browser_ui(self, step, request):
        from playwright.sync_api import sync_playwright
        url = allowed_url(request.get('url'), self.config, request)
        expected = step.get('expected') or {}
        if not isinstance(expected, dict) or not expected.get('selector'):
            raise RuntimeError('RECOVERY_EXPLICIT_ORACLE_REQUIRED', 'expected.selector')
        context_ref = request.get('browser_context_ref')
        if isinstance(context_ref, dict):
            # A 4A-authenticated browser is an existing governed resource. This
            # path only asserts the current page and never replaces its profile.
            from .recovery_browser import CDPBrowserProvider
            from .r3_e2.contracts import BrowserContextRef
            provider = CDPBrowserProvider(self.root)
            ref = BrowserContextRef.from_dict(context_ref)
            provider.inspect_context(ref)
            if provider.inspect_lease(ref) != 'AI':
                raise RuntimeError('RECOVERY_BROWSER_HUMAN_LEASE', 'AI assertions wait for governed takeover completion')
            if not provider.allowed(url):
                raise RuntimeError('RECOVERY_BROWSER_SCOPE_MISMATCH', 'Browser and executor approvals must both cover this page')
            with sync_playwright() as driver:
                browser = driver.chromium.connect_over_cdp(provider.endpoint, timeout=5000)
                pages = [page for page in (browser.contexts[0].pages if browser.contexts else []) if page.url == url]
                if len(pages) != 1:
                    raise RuntimeError('RECOVERY_BROWSER_PAGE_BINDING_REQUIRED', 'Exactly one existing approved page must match the requested URL')
                element = pages[0].locator(expected['selector']).first
                checks = {'visible': element.is_visible()}
                if 'text' in expected: checks['text'] = element.inner_text() == expected['text']
                provider.inspect_context(ref)
                if provider.inspect_lease(ref) != 'AI':
                    raise RuntimeError('RECOVERY_BROWSER_LEASE_CHANGED', 'Human control resumed during observation')
                return {'runner': 'playwright-existing-governed-context', 'checks': checks,
                        'context_binding_digest': ref.context_binding_digest}, all(checks.values())
        chrome = self.root / 'runtime' / 'browser' / 'chrome-win64' / 'chrome.exe'
        configured = self.config.get('local_chromium_path') if os.name != 'nt' else None
        with sync_playwright() as driver:
            browser = driver.chromium.launch(executable_path=configured or str(chrome), headless=True)
            try:
                context = browser.new_context(service_workers='block')
                def route(route):
                    try: allowed_url(route.request.url, self.config, request)
                    except RuntimeError: route.abort(); return
                    if route.request.method not in self.config.get('allowed_methods', ['GET', 'HEAD']):
                        route.abort(); return
                    route.continue_()
                context.route('**/*', route)
                # WebSocket connections are outside this navigation/assertion runner.
                if hasattr(context, 'route_web_socket'):
                    context.route_web_socket('**/*', lambda socket: socket.close())
                page = context.new_page(); page.goto(url, wait_until='domcontentloaded', timeout=20000)
                element = page.locator(expected['selector']).first
                checks = {'visible': element.is_visible()}
                if 'text' in expected: checks['text'] = element.inner_text() == expected['text']
                return {'runner': 'playwright', 'checks': checks}, all(checks.values())
            finally:
                browser.close()


def provider_bundle(root, profile=None):
    config = binding(root)
    # Unbound CAT/DB/Manual remain governed G4 gates; no fake data provider.
    ports = {'capability_executors': {name: OfflineExecutor(root, name, config)
            for name in ('API', 'UNIT', 'BROWSER_UI', 'SECURITY', 'PERFORMANCE')}}
    if (Path(root) / 'bindings/browser.json').is_file():
        from .recovery_browser import CDPBrowserProvider
        ports['browser_provider'] = CDPBrowserProvider(root)
    return ports
