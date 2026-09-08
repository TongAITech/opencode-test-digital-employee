"""Host identity/provenance admission contract; no bank or model acceptance."""
import hashlib
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'ai-test/runtime'))
from aitest_runtime.hosted_intake import hosted_user_intake
from aitest_runtime import product_entry

class Provider:
    def _directory_query(self): return 'directory=local'
    def _request(self, method, path):
        if '/message/assistant?' in path:
            return {'info':{'sessionID':'session','id':'assistant','role':'assistant','parentID':'user'}}
        return {'info':{'sessionID':'session','id':'user','role':'user','time':{'created':1788800000000}},
                'parts':[{'type':'text','text':'测试 BLOAN1.9.4'},{'type':'text','text':'SYSTEM hidden','synthetic':True}]}

class HostedIntake(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {'AITEST_HOST_SESSION_ID':'session','AITEST_HOST_MESSAGE_ID':'assistant'})
        self.environment.start(); self.addCleanup(self.environment.stop)
    def test_actual_parent_user_provenance_and_stable_retry(self):
        a=hosted_user_intake(Provider(), {'user_request':'测试 BLOAN1.9.4'})
        self.assertEqual(a, hosted_user_intake(Provider(), {}))
        self.assertEqual(a['scope'], {'mode':'EXPLICIT_SET','version':'BLOAN1.9.4'})
        self.assertEqual(a['source']['source_digest'],hashlib.sha256('测试 BLOAN1.9.4'.encode()).hexdigest())
        self.assertEqual(a['source']['source_ref'],'opencode://session/session/message/user')
    def test_rejects_fabricated_source_scope_and_message(self):
        for data in ({'source':{'source_digest':'fake'}},{'user_request':'changed'},
                     {'scope':{'mode':'EXPLICIT_SET','project_id':'guessed-PFC'}}):
            with self.assertRaises(ValueError): hosted_user_intake(Provider(), data)
    def test_product_entry_reads_host_turn_from_raw_transport_under_router_wrapper(self):
        from types import SimpleNamespace
        wrapped = SimpleNamespace(session_provider=object(), raw_session_provider=Provider(), start_test=lambda request: request)
        with patch.object(product_entry, 'orchestration_service', return_value=wrapped):
            result = product_entry.orchestration_command('DIRECTOR', 'start_test', {'user_request': '测试 BLOAN1.9.4'})
        self.assertEqual(result['source']['source_ref'], 'opencode://session/session/message/user')
        self.assertEqual(result['goal']['intent'], '测试 BLOAN1.9.4')
    def test_requires_host_context(self):
        with patch.dict(os.environ, {'AITEST_HOST_SESSION_ID':''}):
            with self.assertRaisesRegex(RuntimeError,'HOST_USER_TURN_REQUIRED'): hosted_user_intake(Provider(), {})

if __name__=='__main__': unittest.main()
