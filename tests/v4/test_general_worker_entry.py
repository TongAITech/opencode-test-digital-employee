"""Routing-only port checks. The executor spy proves no worker execution or L4."""
import os
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'workspace-template/ai-test/runtime'))
from aitest_runtime import product_entry
from aitest_runtime.hosted_interaction import hosted_interaction
from test_interaction_admission import NOW,proposal
import test_interaction_receipts as fixtures
from test_interaction_admission import HostFixture


class GeneralEntryTests(unittest.TestCase):
    setUp = fixtures.ProductEntryTests.setUp
    tearDown = fixtures.ProductEntryTests.tearDown
    def test_general_route_passes_verified_own_text_to_typed_owner(self):
        text='把说明写到 notes/guide.md';self.provider.host=HostFixture(text)
        calls=[]
        class Port:
            def __init__(self,runtime,root,session_provider=None):
                self.runtime=runtime;self.provider=session_provider
            def start(self,admitted,owner):
                calls.append((admitted,owner,self.runtime,self.provider))
                return {'status':'PORT_RECEIVED_NO_EXECUTION','truth_source':'R1_EVENT_STREAM','job_id':'routing-spy-only'}
        module=ModuleType('aitest_runtime.general_work.execution');module.GeneralExecutionService=Port
        with patch.dict(sys.modules,{'aitest_runtime.general_work.execution':module}):
            result=hosted_interaction(self.service,{'proposal':proposal(text,'GENERAL_WORK','write')},now_ms=NOW)
        self.assertEqual(len(calls),1);admitted,owner,runtime,provider=calls[0]
        self.assertEqual(admitted['operation_text'],text)
        self.assertEqual(admitted['host_turn_ref']['host_message_id'],'u1')
        self.assertEqual(admitted['status'],'DELEGATION_REQUIRED')
        self.assertIs(runtime,self.runtime);self.assertIs(provider,self.provider)
        self.assertEqual(result['operations'][0]['status'],'PORT_RECEIVED_NO_EXECUTION')
        self.assertIsNone(owner.receipt(admitted['operation_id']))
    def test_worker_missing_host_and_unknown_action_fail_before_owner(self):
        with patch.dict(os.environ,{'AITEST_HOST_SESSION_ID':'','AITEST_HOST_MESSAGE_ID':''}):
            with self.assertRaisesRegex(ValueError,'WORKER_HOST_CONTEXT_REQUIRED'):product_entry.general_worker_command('status',{'job_id':'j'})
        with self.assertRaisesRegex(ValueError,'ACTION_NOT_ALLOWED'):product_entry.general_worker_command('open_shell',{'job_id':'j'})
    def test_worker_cli_has_separate_explicit_entry(self):
        args=product_entry.parser().parse_args(['general-work','--action','read_file','--payload','{}'])
        self.assertEqual(args.command,'general-work');self.assertEqual(args.action,'read_file')

if __name__=='__main__':unittest.main()
