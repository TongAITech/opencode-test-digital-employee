import json
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools' / 'dsh_workbench'))
from wb_d_manifest_inspector import inspect, assess_compatibility
from wb_d_host_probe import probe

class CompatibilityTests(unittest.TestCase):
    def test_missing_invalid_and_recovered_version_never_certify_panel(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(assess_compatibility(inspect(root))['host_version_status'], 'HOST_IDENTITY_NOT_OBSERVED')
            path = Path(root) / 'package.json'
            path.write_text('{bad')
            self.assertEqual(inspect(root)['observations'][0]['result'], 'INVALID_JSON')
            for version, expected in [('1.18.26', 'DECLARED_VERSION_MATCH_RUNTIME_UNVERIFIED'), ('1.18.25', 'HOST_VERSION_MISMATCH')]:
                path.write_text(json.dumps({'name':'@deepseek-ai/dsh','version':version,'exports':{'./client':'./client.js'}}))
                report = assess_compatibility(inspect(root))
                self.assertEqual(report['host_version_status'], expected)
                self.assertEqual(report['panel_compatibility'], 'CAPABILITY_UNKNOWN')
                self.assertFalse(report['field_verified'])

    def test_conflicting_versions(self):
        inv = {'observations':[{'result':'METADATA_OBSERVED','metadata':{'name':'@deepseek-ai/dsh','version':v,'client_export_declared':True}} for v in ['1.18.26','1.18.27']]}
        self.assertEqual(assess_compatibility(inv)['host_version_status'], 'HOST_VERSION_CONFLICT')

    def test_permissions_route_and_failure_stop_before_details(self):
        class Reject:
            def __init__(self, code): self.code, self.calls = code, 0
            def open(self, request, timeout):
                self.calls += 1
                raise HTTPError(request.full_url, self.code, 'redacted', {}, None)
        for code, expected in [(401,'HOST_PERMISSION_DENIED'),(403,'HOST_PERMISSION_DENIED'),(404,'HOST_ROUTE_MISSING'),(500,'GET_UNAVAILABLE')]:
            reader = Reject(code)
            report = probe(base_url='http://127.0.0.1:4096',session_id='session_test_001',opener=reader)
            self.assertEqual(report['session_status'], expected)
            self.assertEqual(reader.calls, 1)
            self.assertEqual(report['session_identity'], 'NOT_OBSERVED')
            self.assertFalse(report['field_verified'])
