"""Host-native OpenCode adapter. Never reads/copies host configuration or auth files."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import shutil
import urllib.error
import urllib.parse
import urllib.request

COMPATIBILITY = 'OPENCODE_ADAPTER_COMPATIBILITY_REQUIRED'
REQUIRED_AGENTS = {'aitest-director', 'aitest-planner', 'aitest-requirement-analyst',
                   'aitest-code-analyst', 'aitest-test-strategist', 'aitest-case-designer',
                   'aitest-executor', 'aitest-evaluator', 'aitest-diagnosis'}
REQUIRED_TOOLS = {'aitest_director', 'aitest_planner', 'aitest_worker', 'aitest_context'}


class CompatibilityRequired(RuntimeError):
    def __init__(self, capability: str):
        super().__init__(COMPATIBILITY + ': ' + capability)
        self.capability = capability


def resolve(workspace: Path, env=None) -> Path:
    env = os.environ if env is None else env
    candidate = env.get('AITEST_HOST_OPENCODE') or shutil.which('opencode', path=env.get('PATH'))
    if not candidate:
        raise RuntimeError('HOST_NATIVE_OPENCODE_REQUIRED: PATH 中没有 opencode')
    executable = Path(candidate).resolve()
    if not executable.is_file():
        raise RuntimeError('HOST_NATIVE_OPENCODE_REQUIRED: 宿主入口不存在')
    # A PATH mistake must never select an older bundled runtime silently.
    for root in (workspace, Path(__file__).resolve().parents[2]):
        if executable.is_relative_to(root.resolve()):
            raise RuntimeError('BUNDLED_OPENCODE_AS_BANK_RUNTIME_FORBIDDEN')
    return executable


def command(executable: Path, *arguments: str, env=None) -> list[str]:
    env = os.environ if env is None else env
    if os.name == 'nt':
        bash = env.get('AITEST_GIT_BASH')
        if not bash or not Path(bash).is_file():
            raise RuntimeError('WINDOWS_GIT_BASH_HOST_RESOLUTION_REQUIRED')
        # Supports the user's existing shell/npm/cmd shim without parsing or
        # copying it. Values are positional arguments, never interpolated code.
        return [bash, '-c', 'exec "$1" "${@:2}"', 'aitest-host-opencode', str(executable), *arguments]
    return [str(executable), *arguments]


class CapabilityClient:
    def __init__(self, endpoint, workspace, env=None):
        self.endpoint = endpoint.rstrip('/')
        parsed = urllib.parse.urlsplit(self.endpoint)
        if parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1', 'localhost', '::1'}:
            raise RuntimeError('OPENCODE_CONTROL_ENDPOINT_MUST_BE_LOOPBACK')
        self.workspace = Path(workspace).resolve()
        self.env = os.environ if env is None else env
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(self, method, path, body=None, *, budget=2 * 1024 * 1024, timeout=20):
        separator = '&' if '?' in path else '?'
        url = self.endpoint + path + separator + urllib.parse.urlencode({'directory': str(self.workspace)})
        headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
        password = self.env.get('OPENCODE_SERVER_PASSWORD')
        if password:
            pair = self.env.get('OPENCODE_SERVER_USERNAME', 'opencode') + ':' + password
            headers['Authorization'] = 'Basic ' + base64.b64encode(pair.encode()).decode()
        data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        try:
            with self.opener.open(urllib.request.Request(url, data=data, headers=headers, method=method), timeout=timeout) as response:
                raw = response.read(budget + 1)
            if len(raw) > budget:
                raise CompatibilityRequired('BOUNDED_RESPONSE')
            return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            # Provider errors may contain secret values; never echo bodies.
            if exc.code in {401, 403}:
                raise RuntimeError('OPENCODE_TRANSPORT_AUTH_REQUIRED') from None
            raise CompatibilityRequired('HTTP_' + str(exc.code)) from None
        except (UnicodeError, ValueError):
            raise CompatibilityRequired('JSON_RESPONSE') from None

    def probe(self) -> dict:
        gates = {}
        health = self.request('GET', '/global/health')
        if not isinstance(health, dict) or health.get('healthy') is not True:
            raise CompatibilityRequired('OPENCODE_PROCESS_READY')
        gates['OPENCODE_PROCESS_READY'] = 'PASS'
        # Version is informational. It is never compared with an exact pin.
        reported_version = str(health.get('version', 'UNREPORTED'))[:80]
        paths = self.request('GET', '/path')
        agents = self.request('GET', '/agent')
        tool_ids = self.request('GET', '/experimental/tool/ids')
        names = {x.get('name') for x in agents if isinstance(x, dict)} if isinstance(agents, list) else set()
        if not isinstance(paths, dict) or Path(paths.get('directory', '')).resolve() != self.workspace:
            raise CompatibilityRequired('WORKSPACE_DIRECTORY')
        if not REQUIRED_AGENTS.issubset(names) or not isinstance(tool_ids, list) or not all(isinstance(x, str) for x in tool_ids) or not REQUIRED_TOOLS.issubset(set(tool_ids)):
            raise CompatibilityRequired('AITEST_WORKSPACE_LOADED')
        config = self.request('GET', '/config')
        instructions = config.get('instructions', []) if isinstance(config, dict) else []
        if not any(str(x).replace('\\', '/').endswith('AGENTS.md') for x in instructions):
            raise CompatibilityRequired('AITEST_AGENTS_INSTRUCTIONS')
        gates['AITEST_WORKSPACE_LOADED'] = 'PASS'
        selected = config.get('model') if isinstance(config, dict) else None
        # The host catalog can contain thousands of advertised models. This
        # transient local control-plane read is never returned to an Agent.
        catalog = self.request('GET', '/provider', budget=16 * 1024 * 1024)
        connected = catalog.get('connected', []) if isinstance(catalog, dict) else []
        providers = catalog.get('all', []) if isinstance(catalog, dict) else []
        provider_id, _, model_id = str(selected or '').partition('/')
        if not isinstance(providers, list) or not isinstance(connected, list):
            raise CompatibilityRequired('PROVIDER_CATALOG')
        known = next((p for p in providers if isinstance(p, dict) and p.get('id') == provider_id), {})
        gates['PROVIDER_READY'] = 'READY' if provider_id in connected else 'AUTH_REQUIRED'
        gates['MODEL_READY'] = 'READY' if model_id and model_id in known.get('models', {}) else 'MODEL_SELECTION_REQUIRED'
        # Catalog presence is not proof of successful bank authentication.
        gates['AUTH_READY'] = 'MODEL_TURN_VERIFICATION_REQUIRED' if provider_id in connected else 'AUTH_REQUIRED'
        del config, catalog, providers, known
        probe_id = None
        try:
            session = self.request('POST', '/session', {'title': 'AITest capability check (no model invocation)'})
            probe_id = session.get('id') if isinstance(session, dict) else None
            if not isinstance(probe_id, str) or not probe_id.startswith('ses_'):
                raise CompatibilityRequired('SESSION_CREATE')
            gates['SESSION_CREATE'] = 'PASS'
            prefix = '/session/' + urllib.parse.quote(probe_id, safe='')
            if self.request('GET', prefix).get('id') != probe_id:
                raise CompatibilityRequired('SESSION_READ')
            gates['SESSION_READ'] = 'PASS'
            self.request('POST', prefix + '/message', {'agent': 'aitest-director', 'noReply': True,
                         'parts': [{'type': 'text', 'text': 'AITest capability probe; no Mission or model invocation.'}]})
            messages = self.request('GET', prefix + '/message?limit=2')
            if not isinstance(messages, list) or not messages:
                raise CompatibilityRequired('SESSION_MESSAGE')
            gates['SESSION_MESSAGE'] = 'PASS'
            if not isinstance(self.request('GET', '/session/status'), dict):
                raise CompatibilityRequired('SESSION_STATUS')
            gates['SESSION_STATUS'] = 'PASS'
            if self.request('POST', prefix + '/abort', {}) is not True:
                raise CompatibilityRequired('SESSION_ABORT')
            gates['SESSION_ABORT'] = 'PASS'
        finally:
            if probe_id:
                try:
                    self.request('DELETE', '/session/' + urllib.parse.quote(probe_id, safe=''))
                except Exception:
                    pass  # Cleanup is best effort; no user Session is targeted.
        return {'gates': gates, 'reported_version': reported_version,
                'exact_version_pin': None, 'model_turn': 'NOT_EXECUTED',
                'host_provider_auth_copied': False, 'bank_field_validation_required': True}
