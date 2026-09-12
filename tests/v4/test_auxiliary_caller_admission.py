"""Auxiliary product boundaries with real R1/files and a labeled Host fixture."""
from contextlib import closing
import copy
import hashlib
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import test_mission_session_authority as fixture
from aitest_runtime import product_entry, bounded_evidence
from aitest_runtime.canonical_runtime import create_canonical_runtime
from aitest_runtime.g2_1.managed_orchestration import G21AutonomousOrchestrationService
from aitest_runtime.mission_session_authority import MissionSessionOwner
from aitest_runtime.durable_core import RuntimeError
from aitest_runtime.g3.contracts import EXTENSION_ID as G3

class AuxiliaryTests(unittest.TestCase):
    context=fixture.AuthorityTests.context
    worker=fixture.AuthorityTests.worker
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)/'workspace';self.root.mkdir()
        self.runtime=create_canonical_runtime(self.root,db_path=Path(self.tmp.name)/'state/spine.db')
        self.host=fixture.Transport(self.root);self.service=G21AutonomousOrchestrationService(self.runtime,self.root,session_provider=self.host)
        self.owner=MissionSessionOwner(self.service);r=fixture.request('auxiliary');r['scope']['environment_id']='LOCAL_FIXTURE'
        started=self.service.start_test(r);self.mid=started['intake']['intake']['mission_id'];self.g=self.worker()
        self.patches=[patch.object(product_entry,'workspace_root',return_value=self.root),patch.object(product_entry,'orchestration_service',return_value=self.service)]
        for p in self.patches:p.start()
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()
    def invoke(self,family,action,payload):
        with self.context(self.g,'aitest_'+family,action,payload):return product_entry.auxiliary_command(family,action,payload)
    def test_document_import_persists_from_product_input_only(self):
        folder=self.root/'attachments';folder.mkdir();source=folder/'requirement.txt';source.write_text('借款额度必须大于零',encoding='utf-8')
        payload={'mission_id':self.mid,'path':'attachments/requirement.txt','source_id':'REQ-LOCAL','revision':'1'}
        result=self.invoke('recovery','import_document',payload)
        self.assertEqual(result['status'],'PASS')
        facts=self.runtime.replay_composed(self.mid).extension_state(G3).by_kind('SOURCE_DOCUMENT')
        self.assertEqual(len(facts),1);self.assertEqual(facts[0].payload['sha256'],hashlib.sha256(source.read_bytes()).hexdigest())
        before=self.runtime.get_head_seq(self.mid);outside=Path(self.tmp.name)/'private.txt';outside.write_text('HOST_PRIVATE_CANARY')
        for value in (str(outside),'../private.txt'):
            with self.assertRaisesRegex(RuntimeError,'SCOPE_DENIED'):self.invoke('recovery','import_document',{**payload,'path':value})
        self.assertEqual(self.runtime.get_head_seq(self.mid),before)
    def test_knowledge_uses_r1_scope_task_role_and_rejects_forgery(self):
        data={'mission_id':self.mid}
        result=self.invoke('knowledge','task_view',data)
        self.assertEqual(result['task_id'],self.g['task_id']);self.assertEqual(result['items'],[])
        for fields,reason in [({'scope':{'project_id':'OTHER','environment_id':'LOCAL_FIXTURE','version_scope':'auxiliary'}},'SCOPE_MISMATCH'),
            ({'role':'aitest-executor'},'ROLE_MISMATCH'),({'task_id':'unowned'},'BINDING_MISMATCH')]:
            with self.assertRaisesRegex(RuntimeError,reason):self.invoke('knowledge','task_view',{**data,**fields})
    def test_auxiliary_stale_and_foreign_call_rejected_before_intake(self):
        data={'mission_id':self.mid};before=self.runtime.get_head_seq(self.mid)
        with self.context(self.g,'aitest_recovery','intake_context',data):
            self.host.rows['a']['info']['agent']='aitest-director'
            with self.assertRaisesRegex(RuntimeError,'AGENT_MISMATCH'):product_entry.auxiliary_command('recovery','intake_context',data)
        self.assertEqual(self.runtime.get_head_seq(self.mid),before)
        self.service.rotate_session(self.mid,task_id=self.g['task_id'],reasons=['TEST_STALE_AUX'])
        with self.assertRaisesRegex(RuntimeError,'STALE_CALLER'):self.invoke('recovery','intake_context',data)
    def test_evidence_entry_checks_actual_raw_input_and_current_grant(self):
        folder=bounded_evidence.mission_evidence_directory(self.runtime.db_path.parent.parent,self.mid);folder.mkdir(parents=True)
        (folder/'result.txt').write_text('ACTUAL_LOCAL_EVIDENCE_CANARY',encoding='utf-8')
        data={'mission_id':self.mid,'source_ref':'evidence:result.txt'}
        with self.context(self.g,'aitest_context','read',data):
            self.host.rows['a']['parts'][0]['state']['input']=copy.deepcopy(data)
            result=bounded_evidence.model_read(self.root,data)
            self.assertEqual(result['text'],'ACTUAL_LOCAL_EVIDENCE_CANARY')
            self.host.rows['a']['parts'][0]['state']['input']['source_ref']='evidence:other.txt'
            with self.assertRaisesRegex(RuntimeError,'ACTUAL_TOOL_CALL_REQUIRED'):bounded_evidence.model_read(self.root,data)
        self.service.rotate_session(self.mid,task_id=self.g['task_id'],reasons=['TEST_STALE_PAGE'])
        with self.context(self.g,'aitest_context','read',data):
            self.host.rows['a']['parts'][0]['state']['input']=copy.deepcopy(data)
            with self.assertRaisesRegex(RuntimeError,'STALE_CALLER'):bounded_evidence.model_read(self.root,data)
    def test_cross_mission_and_retired_caller_are_denied(self):
        with self.assertRaises(RuntimeError):self.invoke('recovery','intake_context',{'mission_id':'another-mission'})
        self.owner.retire(self.mid,self.g['session_id'],'TEST_RETIRE')
        with self.assertRaisesRegex(RuntimeError,'STALE_CALLER'):self.invoke('knowledge','task_view',{'mission_id':self.mid})
    def test_executor_cannot_bypass_requirement_analyst_import_authority(self):
        started=self.service.start_test(fixture.request('aux-executor'));mid=started['intake']['intake']['mission_id']
        p=fixture.proposal('aux-executor');p['tasks'][0]['routing']['role']='EXECUTOR';self.service.propose_plan(mid,p)
        g=[g for g in self.owner.state(mid).grants.values() if g['task_id']][-1];data={'mission_id':mid}
        before=self.runtime.get_head_seq(mid)
        with self.context(g,'aitest_recovery','intake_context',data):
            with self.assertRaisesRegex(RuntimeError,'AUXILIARY_ROLE_NOT_AUTHORIZED'):product_entry.auxiliary_command('recovery','intake_context',data)
        self.assertEqual(self.runtime.get_head_seq(mid),before)
    @unittest.skipIf(os.name=='nt','POSIX symlink replacement; Windows file component uses held reparse guards')
    def test_replacement_with_external_symlink_before_open_is_denied(self):
        from aitest_runtime import auxiliary_tool_admission as admission
        folder=self.root/'attachments';folder.mkdir();source=folder/'race.txt';source.write_text('ORIGINAL_LOCAL')
        outside=Path(self.tmp.name)/'private.txt';outside.write_text('OUTSIDE_PRIVATE_CANARY')
        original=admission.scoped_document_bytes
        def race(root,rel):source.unlink();source.symlink_to(outside);return original(root,rel)
        before=self.runtime.get_head_seq(self.mid)
        with patch.object(admission,'scoped_document_bytes',side_effect=race):
            with self.assertRaises(OSError):self.invoke('recovery','import_document',{'mission_id':self.mid,'path':'attachments/race.txt','source_id':'RACE'})
        self.assertEqual(self.runtime.get_head_seq(self.mid),before)
    def test_replacement_after_read_cannot_change_parsed_or_cached_bytes(self):
        from aitest_runtime import recovery_intake as intake
        folder=self.root/'attachments';folder.mkdir();source=folder/'stable.txt';raw=b'ADMITTED_ORIGINAL_BYTES';source.write_bytes(raw)
        parse=intake.parse_document_bytes
        def replace_then_parse(data,**kw):
            source.unlink();source.write_bytes(b'REPLACEMENT_MUST_NOT_BE_IMPORTED')
            return parse(data,**kw)
        with patch.object(intake,'parse_document_bytes',side_effect=replace_then_parse):
            self.invoke('recovery','import_document',{'mission_id':self.mid,'path':'attachments/stable.txt','source_id':'STABLE'})
        fact=self.runtime.replay_composed(self.mid).extension_state(G3).by_kind('SOURCE_DOCUMENT')[0]
        self.assertEqual(fact.payload['text'],raw.decode());self.assertEqual(fact.payload['sha256'],hashlib.sha256(raw).hexdigest())
        self.assertEqual((self.runtime.db_path.parent/'attachments'/(fact.payload['sha256']+'.txt')).read_bytes(),raw)
        with self.assertRaisesRegex(RuntimeError,'REVISION_CONFLICT'):
            self.invoke('recovery','import_document',{'mission_id':self.mid,'path':'attachments/stable.txt','source_id':'STABLE'})
    def test_document_reader_keeps_document_budget_above_general_file_budget(self):
        from aitest_runtime.auxiliary_tool_admission import scoped_document_bytes
        folder=self.root/'attachments';folder.mkdir();source=folder/'large.docx';raw=b'x'*(5*1024*1024);source.write_bytes(raw)
        self.assertEqual(hashlib.sha256(scoped_document_bytes(self.root,'attachments/large.docx')).hexdigest(),hashlib.sha256(raw).hexdigest())

if __name__=='__main__':unittest.main(verbosity=2)
