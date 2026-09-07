"""Required default-intake regression; baseline failures are intentional evidence.

No injected resolver/resolution. Set MAC_DELIVERY_EVIDENCE_ROOT to a fresh
owned directory to retain databases; otherwise use an isolated temp directory.
This is DIRECT_DIAGNOSTIC, never native hosted-turn acceptance.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import platform
import sqlite3
import sys
import tempfile
import traceback
import unittest

WORKSPACE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE / 'ai-test/runtime'))


class MacDeliveryDefaultPath(unittest.TestCase):
    def test_default_intake_and_restart_without_legacy_store(self):
        configured = os.environ.get('MAC_DELIVERY_EVIDENCE_ROOT')
        root = Path(configured) / 'default-resolver' if configured else Path(tempfile.mkdtemp(prefix='mac-delivery-test-'))
        root.mkdir(parents=True, exist_ok=False)
        legacy = root / 'legacy-sentinel/aitest.db'
        legacy.parent.mkdir()
        db = root / 'runtime-spine.db'
        old = {k: os.environ.get(k) for k in ('AITEST_WORKSPACE_ROOT', 'AITEST_DB_PATH', 'AITEST_RUNTIME_SPINE_DB')}
        os.environ.update(AITEST_WORKSPACE_ROOT=str(root), AITEST_DB_PATH=str(legacy), AITEST_RUNTIME_SPINE_DB=str(db))
        try:
            from aitest_runtime.canonical_runtime import create_canonical_runtime, canonical_extension_manifests
            from aitest_runtime.r2_2 import MissionIntakeOrchestrator
            from aitest_runtime.r2_2.normalizer import normalize_request
            text = 'Controlled local intake diagnosis; business facts remain unknown.'
            request = {'intake_id': 'mac-delivery-default-retry-001', 'operation': 'CREATE',
                       'scope': {'mode': 'EXPLICIT_SET', 'project_id': 'MAC-DELIVERY-DIAGNOSTIC'},
                       'goal': {'intent': text}, 'actor': {'type': 'SYSTEM', 'id': 'isolated-diagnostic'},
                       'source': {'kind': 'CONTROL_PLANE', 'source_ref': 'diagnostic:mac-delivery-default-retry-001',
                                  'source_digest': hashlib.sha256(text.encode()).hexdigest(),
                                  'observed_at': '2026-09-07T12:00:00Z', 'valid_until': None, 'source_precedence': None}}
            normalized = normalize_request(request)
            (root / 'request.json').write_text(json.dumps(request, indent=2))
            attempts = []
            for number in (1, 2):
                runtime = create_canonical_runtime(root, db_path=db)
                item = {'attempt': number, 'fresh_runtime_instance': True, 'legacy_before': legacy.exists()}
                try:
                    result = MissionIntakeOrchestrator(runtime).intake(request)
                    item['result'] = result.to_dict()
                except Exception as exc:
                    item.update(error_type=type(exc).__name__, error=str(exc), traceback=traceback.format_exc())
                item['legacy_after'] = legacy.exists()
                item['legacy_bytes'] = legacy.stat().st_size if legacy.exists() else None
                with sqlite3.connect(f'file:{db}?mode=ro', uri=True) as conn:
                    item['integrity'] = conn.execute('PRAGMA integrity_check').fetchone()[0]
                    names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
                    item['counts'] = {n: conn.execute('SELECT COUNT(*) FROM "' + n.replace('"', '""') + '"').fetchone()[0] for n in names}
                    item['events'] = [dict(zip([d[0] for d in c.description], row)) for c in [conn.execute('SELECT * FROM events ORDER BY seq')] for row in c.fetchall()]
                attempts.append(item)
            evidence = {'evidence_type': 'DIRECT_DIAGNOSTIC', 'host': {'system': platform.system(), 'macOS': platform.mac_ver()[0], 'architecture': platform.machine(), 'python': platform.python_version()},
                        'normalization_passed': bool(normalized), 'resolver_injected': False, 'resolution_injected': False,
                        'native_session_id': None, 'native_message_id': None, 'native_tool_call_id': None,
                        'product_acceptance': 'NOT_RUN', 'database_retained': True, 'attempts': attempts}
            (root / 'result.json').write_text(json.dumps(evidence, indent=2))
            failures = [x for x in attempts if 'error' in x]
            self.assertFalse(failures, 'Default intake failed: ' + '; '.join(x['error'] for x in failures))
            self.assertFalse(legacy.exists(), 'Default canonical path accessed/created legacy SQLite')
            self.assertEqual(attempts[0]['result']['mission_id'], attempts[1]['result']['mission_id'])
            self.assertEqual(attempts[0]['counts']['events'], attempts[1]['counts']['events'])
        finally:
            for key, value in old.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


if __name__ == '__main__':
    unittest.main()
