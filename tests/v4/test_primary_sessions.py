"""Actual R1/entry admission; Host transport fixture, never a real-model PASS."""
from contextlib import closing
from dataclasses import replace
from datetime import timedelta
import copy
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'workspace-template/ai-test/runtime'))
from aitest_runtime.autonomous_orchestration import FakeOpenCodeSessionProvider, AutonomousOrchestrationService
from aitest_runtime.canonical_runtime import create_canonical_runtime, canonical_extension_manifests
from aitest_runtime.durable_core import RuntimeError, RuntimeService, ActorRef, CommandEnvelope
from aitest_runtime.primary_sessions import PrimarySessionOwner, EXTENSION_ID, OWNER, CREATE, RECORD, transition, stamp, now
from aitest_runtime import product_entry
from aitest_runtime.control_loop import _primary_session_tick

class Host(FakeOpenCodeSessionProvider):
    base_url = 'http://127.0.0.1:4096'
    def __init__(self, root):
        super().__init__(root); self.rows = {}
    def _directory_query(self): return 'directory=fixture'
    def _request(self, method, path):
        return copy.deepcopy(self.rows[path.split('/message/')[1].split('?')[0]])
    def call(self, sid, action, payload, text='你好'):
        self.rows['a'] = {'info': {'id':'a','sessionID':sid,'role':'assistant','agent':'aitest-director','parentID':'u'},
            'parts':[{'type':'tool','tool':'aitest_director','sessionID':sid,'messageID':'a','callID':'c',
                'state':{'status':'running','input':{'action':action,'payload':copy.deepcopy(payload)}}}]}
        self.rows['u'] = {'info': {'id':'u','sessionID':sid,'role':'user','time':{'created':int(time.time()*1000)}},
            'parts':[{'type':'text','text':text,'messageID':'u','sessionID':sid}]}
        return patch.dict(os.environ, {'AITEST_HOST_SESSION_ID':sid,'AITEST_HOST_MESSAGE_ID':'a','AITEST_HOST_CALL_ID':'c'})

class PrimaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)/'workspace';self.root.mkdir()
        self.runtime=create_canonical_runtime(self.root,db_path=Path(self.tmp.name)/'state/spine.db')
        self.host=Host(self.root);self.owner=PrimarySessionOwner(self.runtime,self.root,self.host)
    def tearDown(self): self.tmp.cleanup()
    def count(self, table):
        with closing(sqlite3.connect(self.runtime.db_path)) as c:return c.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
    def test_bind_restart_replay_same_logical_no_mission(self):
        first=self.owner.ensure_current(); self.assertEqual(first['epoch'],1)
        self.assertEqual(self.owner.ensure_current(),first);self.assertEqual(len(self.host.sessions),1)
        fresh=create_canonical_runtime(self.root,db_path=self.runtime.db_path)
        self.assertEqual(PrimarySessionOwner(fresh,self.root,self.host).current(),first)
        self.assertEqual(self.count('mission_projection'),0)
        self.assertTrue(fresh.verify_projection(self.owner.subject.subject_id)['ok'])
        self.assertEqual(fresh.rebuild_projections()['rebuilt'],1)
        with closing(sqlite3.connect(self.runtime.db_path)) as c:
            self.assertEqual(c.execute('SELECT DISTINCT session_id FROM events').fetchall(),[(None,)])
    def test_fence_successor_rejects_predecessor(self):
        old=self.owner.ensure_current();self.owner.fence('TEST_FENCE')
        with self.assertRaisesRegex(RuntimeError,'PRIMARY_CURRENT_BINDING_REQUIRED'): self.owner.current(old['session_id'])
        new=self.owner.ensure_current();self.assertEqual(new['epoch'],2)
        self.assertEqual(old['logical_agent_id'],new['logical_agent_id']);self.assertNotEqual(old['session_id'],new['session_id'])
        with self.assertRaisesRegex(RuntimeError,'STALE_CALLER'): self.owner.current(old['session_id'])
    def test_create_before_bind_crash_recovers_without_second_host_session(self):
        original=self.owner.record
        def fail(op,data):
            if op=='BIND':raise OSError('simulated crash after host create')
            return original(op,data)
        with patch.object(self.owner,'record',side_effect=fail):
            with self.assertRaises(OSError):self.owner.ensure_current()
        self.assertEqual(len(self.host.sessions),1);self.assertEqual(self.owner.state().epoch,1)
        new=self.owner.ensure_current();self.assertEqual(new['epoch'],1);self.assertEqual(len(self.host.sessions),1)
    def test_foreign_host_cannot_reuse_same_id_and_directory(self):
        old=self.owner.ensure_current();self.host.base_url='http://127.0.0.1:4900'
        with self.assertRaisesRegex(RuntimeError,'PRIMARY_HOST_REALM_MISMATCH'):self.owner.current(old['session_id'])
        new=self.owner.ensure_current();self.assertEqual(new['epoch'],2);self.assertNotEqual(new['session_id'],old['session_id'])
    def test_new_host_same_local_session_id_is_new_epoch_not_same_owner(self):
        old=self.owner.ensure_current();new_host=Host(self.root);new_host.base_url='http://127.0.0.1:4900'
        other=PrimarySessionOwner(self.runtime,self.root,new_host);new=other.ensure_current()
        self.assertEqual(old['session_id'],new['session_id']);self.assertEqual(new['epoch'],2)
        self.assertNotEqual(old['host_realm'],new['host_realm'])
        with self.assertRaisesRegex(RuntimeError,'PRIMARY_HOST_REALM_MISMATCH'):self.owner.current()
    def test_pending_host_change_fences_without_rebinding_old_request(self):
        original=self.owner.record
        def fail(op,data):
            if op=='BIND':raise OSError('crash')
            return original(op,data)
        with patch.object(self.owner,'record',side_effect=fail):
            with self.assertRaises(OSError):self.owner.ensure_current()
        new_host=Host(self.root);new_host.base_url='http://127.0.0.1:4900'
        other=PrimarySessionOwner(self.runtime,self.root,new_host);new=other.ensure_current()
        self.assertEqual(new['epoch'],2);self.assertEqual(other.state().bindings['1']['state'],'FENCED')
    def test_missing_or_expired_host_never_extends_old_lease(self):
        old=self.owner.ensure_current()
        with patch('aitest_runtime.primary_sessions.now',return_value=(stamp(old['expires_at'])+timedelta(seconds=1)).isoformat()):
            with self.assertRaisesRegex(RuntimeError,'PRIMARY_LEASE_EXPIRED'):self.owner.current()
            new=self.owner.ensure_current()
        self.assertEqual(new['epoch'],2);self.assertEqual(self.owner.state().bindings['1']['state'],'FENCED')
    def test_wrong_directory_and_ambiguous_recovery_fail_closed(self):
        self.owner.ensure_current();self.owner.fence('TEST')
        original=self.host.create_session
        def wrong(*args,**kwargs):return replace(original(*args,**kwargs),directory=str(self.root/'other'))
        with patch.object(self.host,'create_session',side_effect=wrong):
            with self.assertRaisesRegex(RuntimeError,'DIRECTORY_MISMATCH'):self.owner.ensure_current()
        self.assertEqual(self.owner.state().bindings['2']['state'],'REQUESTED')
    def test_model_actor_cannot_bind_and_old_registry_cannot_write_or_rebuild(self):
        self.owner.ensure_current();seq=self.runtime.get_head_seq(self.owner.subject.subject_id)
        result=self.runtime.execute(CommandEnvelope('forged',RECORD,self.owner.subject.subject_id,seq,ActorRef('AGENT','aitest-director'),
            {'subject':self.owner.subject.to_dict(),'operation':'FENCE','data':{}}))
        self.assertFalse(result.ok);self.assertEqual(self.runtime.get_head_seq(self.owner.subject.subject_id),seq)
        manifests=tuple(m for m in canonical_extension_manifests() if m.extension_id!=EXTENSION_ID)
        old=RuntimeService(self.runtime.db_path,extensions=manifests)
        with self.assertRaises(RuntimeError):old.assert_writable_compatible()
        with self.assertRaises(RuntimeError):old.rebuild_projections()
    def invoke(self, action, payload):
        service=AutonomousOrchestrationService(self.runtime,self.root,session_provider=self.host)
        with patch.object(product_entry,'workspace_root',return_value=self.root), patch.object(product_entry,'orchestration_service',return_value=service):
            return product_entry.orchestration_command('DIRECTOR',action,payload)
    def test_real_product_entry_chat_no_mission_and_no_runtime_effect(self):
        binding=self.owner.ensure_current();before=self.count('events')
        payload={'proposal':{'operations':[{'intent':'GENERAL_CHAT','action':'respond','start':0,'end':2}]}}
        with self.host.call(binding['session_id'],'interact',payload): result=self.invoke('interact',payload)
        self.assertEqual(result['operations'][0]['status'],'NO_MISSION');self.assertEqual(self.count('events'),before)
        self.assertEqual(self.count('mission_projection'),0)
    def test_product_rejects_stale_forged_role_call_and_payload_before_effect(self):
        binding=self.owner.ensure_current();sid=binding['session_id']
        mutations=[lambda r:r['info'].update(agent='aitest-general-worker'),
            lambda r:r['parts'][0]['state'].update(status='completed'),
            lambda r:r['parts'][0].update(tool='aitest_general_worker'),
            lambda r:r['parts'].append(copy.deepcopy(r['parts'][0])),
            lambda r:r['parts'][0]['state'].update(input={'action':'status','payload':{'mission_id':'forged'}})]
        before=self.count('events')
        for mutate in mutations:
            with self.host.call(sid,'status',{}):
                mutate(self.host.rows['a'])
                with self.assertRaises(RuntimeError):self.invoke('status',{})
        self.assertEqual(self.count('events'),before)
        self.owner.fence('TEST');self.owner.ensure_current();before=self.count('events')
        with self.host.call(sid,'status',{}):
            with self.assertRaisesRegex(RuntimeError,'STALE_CALLER'):self.invoke('status',{})
        self.assertEqual(self.count('events'),before)

    def test_restart_never_reattaches_pressure_poisoned_primary(self):
        old=self.owner.ensure_current()
        self.host.set_observation(old['session_id'],
            context_used=91000, context_limit=100000, context_utilization=0.91,
            message_count=12, compaction_count=0)
        new=self.owner.ensure_current()
        self.assertEqual(new['epoch'],2)
        self.assertNotEqual(new['session_id'],old['session_id'])
        self.assertEqual(self.owner.state().bindings['1']['state'],'FENCED')
        self.assertIn('CONTEXT_PRESSURE',self.owner.state().bindings['1']['reason'])
        with self.assertRaisesRegex(RuntimeError,'STALE_CALLER'):
            self.owner.current(old['session_id'])

    def test_control_loop_rotates_pressured_primary_and_follows_tui(self):
        old=self.owner.ensure_current()
        self.host.set_observation(old['session_id'],
            activity_state='idle', context_used=92000, context_limit=100000,
            context_utilization=0.92, message_count=20, compaction_count=0)
        result=_primary_session_tick(self.runtime,self.root,self.host)
        self.assertEqual(result['status'],'ROTATED')
        self.assertEqual(result['predecessor_session_id'],old['session_id'])
        self.assertNotEqual(result['successor_session_id'],old['session_id'])
        self.assertEqual(self.host.tui_selections[-1],result['successor_session_id'])
        with self.assertRaisesRegex(RuntimeError,'STALE_CALLER'):
            self.owner.current(old['session_id'])

    def test_control_loop_does_not_rotate_busy_pressured_primary(self):
        old=self.owner.ensure_current()
        self.host.set_observation(old['session_id'],
            activity_state='busy', context_used=93000, context_limit=100000,
            context_utilization=0.93, message_count=20, compaction_count=0)
        result=_primary_session_tick(self.runtime,self.root,self.host)
        self.assertEqual(result['status'],'WAIT')
        self.assertEqual(result['reason'],'PRIMARY_PRESSURE_WAIT_BUSY')
        self.assertEqual(self.owner.current()['session_id'],old['session_id'])
        self.assertEqual(getattr(self.host,'tui_selections',[]),[])

if __name__=='__main__':unittest.main()
