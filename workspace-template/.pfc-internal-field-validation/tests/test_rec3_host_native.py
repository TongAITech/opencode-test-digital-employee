"""Host policy contracts; actual host process/API execution is qualified separately."""
from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / 'tools/recovery'))
sys.path.insert(0, str(REPO / 'workspace-template/ai-test/runtime'))
import host_opencode
import launcher


class HostNativeTests(unittest.TestCase):
    def test_host_resolution_and_bundled_fallback_rejection(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); workspace = root / 'installed'; workspace.mkdir()
            host = root / 'host-bin/opencode'; host.parent.mkdir(); host.write_text('external host shim')
            self.assertEqual(host_opencode.resolve(workspace, {'AITEST_HOST_OPENCODE': str(host)}), host.resolve())
            bundled = workspace / 'runtime/opencode/opencode.exe'; bundled.parent.mkdir(parents=True); bundled.write_bytes(b'not a host')
            with self.assertRaisesRegex(RuntimeError, 'BUNDLED_OPENCODE_AS_BANK_RUNTIME_FORBIDDEN'):
                host_opencode.resolve(workspace, {'AITEST_HOST_OPENCODE': str(bundled)})
            with self.assertRaisesRegex(RuntimeError, 'HOST_NATIVE_OPENCODE_REQUIRED'):
                host_opencode.resolve(workspace, {'PATH': ''})

    def test_prepare_preserves_host_provider_auth_and_environment(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); host = root / 'host'; host.mkdir(); workspace = root / 'workspace'; workspace.mkdir()
            config = host / 'opencode.json'; config.write_bytes(b'{"model":"existing/model"}')
            auth = host / 'auth.json'; auth.write_bytes(b'HOST_SECRET_MUST_NOT_BE_COPIED')
            protected = {'XDG_CONFIG_HOME': str(host), 'XDG_DATA_HOME': str(host / 'data'),
                         'XDG_CACHE_HOME': str(host / 'cache'), 'XDG_STATE_HOME': str(host / 'state'),
                         'OPENCODE_CONFIG': str(config), 'OPENCODE_CONFIG_DIR': str(host),
                         'OPENCODE_CONFIG_CONTENT': '{"host-setting":"keep"}',
                         'OPENAI_API_KEY': 'ENVIRONMENT_FIXTURE_ONLY'}
            before = {p: p.read_bytes() for p in (config, auth)}
            with patch.dict(os.environ, protected), patch.object(launcher, 'WORKSPACE', workspace), patch.object(launcher, 'DATA', workspace / 'data'):
                prepared = launcher.prepare()
                self.assertEqual({k: prepared[k] for k in protected}, protected)
            self.assertEqual({p: p.read_bytes() for p in before}, before)
            self.assertFalse(any(p.name in {'auth.json', 'opencode.json'} for p in workspace.rglob('*')))
            self.assertFalse((workspace / 'data/opencode-config').exists())
            self.assertTrue((workspace / 'data/state/runtime-spine.db').exists())

    def test_capability_checks_never_gate_by_version_and_fail_on_missing_tools(self):
        root = Path.cwd()
        for version in ('1.14.22', '1.18.3', '99.4.7-custom'):
            calls = []
            def request(method, path, body=None, **_):
                calls.append((method, path))
                if path == '/global/health': return {'healthy': True, 'version': version}
                if path == '/path': return {'directory': str(root)}
                if path == '/agent': return [{'name': n} for n in host_opencode.REQUIRED_AGENTS]
                if path == '/experimental/tool/ids': return list(host_opencode.REQUIRED_TOOLS)
                if path == '/config': return {'instructions': ['AGENTS.md'], 'model': 'fixture/model'}
                if path == '/provider': return {'connected': ['fixture'], 'all': [{'id': 'fixture', 'models': {'model': {}}}]}
                if path == '/session/status': return {}
                if path.endswith('/message?limit=2'): return [{'info': {'role': 'user'}}]
                if path.endswith('/abort'): return True
                return {'id': 'ses_fixture'}
            client = host_opencode.CapabilityClient('http://127.0.0.1:9999', root)
            with patch.object(client, 'request', side_effect=request):
                result = client.probe()
            self.assertIsNone(result['exact_version_pin'])
            self.assertEqual(result['reported_version'], version)
            self.assertEqual(result['gates']['SESSION_ABORT'], 'PASS')
            self.assertNotEqual(result['gates']['AUTH_READY'], 'PASS')
            self.assertIn(('DELETE', '/session/ses_fixture'), calls)
        original = request
        with patch.object(client, 'request', side_effect=lambda method, path, *a, **k: [] if path == '/experimental/tool/ids' else original(method, path, *a, **k)):
            with self.assertRaisesRegex(host_opencode.CompatibilityRequired, 'AITEST_WORKSPACE_LOADED'):
                client.probe()


if __name__ == '__main__':
    unittest.main(verbosity=2)
