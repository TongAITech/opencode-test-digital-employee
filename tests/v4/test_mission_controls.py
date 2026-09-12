"""R1 controls, concurrency and effects; deterministic Host protocol fixture."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'workspace-template/ai-test/runtime'))
from aitest_runtime.canonical_runtime import create_canonical_runtime
from aitest_runtime.autonomous_orchestration import AutonomousOrchestrationService
from aitest_runtime.durable_core import RuntimeError
from aitest_runtime.g2_1.managed_orchestration import G21AutonomousOrchestrationService
from aitest_runtime.g4.service import G4RealExecutionService, _R2_5_G4RealExecutionService
from aitest_runtime.hosted_interaction import hosted_interaction
from aitest_runtime.interaction_receipts import R1InteractionOwner
from aitest_runtime.mission_controls import apply_control, prepare_control, reconcile_controls, pending_controls
from aitest_runtime.hosted_intake import actual_host_user_turn
from aitest_runtime.interaction_admission import decide, parse_proposal
from test_interaction_admission import NOW, HostFixture, proposal
from test_interaction_receipts import WORKSPACE, HybridProvider

class ControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=Path(self.tmp.name)/'spine.db'
        self.runtime=create_canonical_runtime(WORKSPACE,db_path=self.db);self.host=HybridProvider()
        self.service=AutonomousOrchestrationService(self.runtime,WORKSPACE,session_provider=self.host)
        self.env=patch.dict(os.environ,{'AITEST_HOST_SESSION_ID':'s1','AITEST_HOST_MESSAGE_ID':'a1'});self.env.start()
        initial=hosted_interaction(self.service,{},action='start_test',now_ms=NOW)
        self.mission=initial['operations'][0]['subject']['subject_id'];self.nextid=2
        self.owner=R1InteractionOwner(self.runtime)
    def tearDown(self):self.env.stop();self.tmp.cleanup()
    def control(self,text,action,*,invoke=True):
        host=HostFixture(text);mid='u'+str(self.nextid);self.nextid+=1
        host.messages[mid]=host.messages.pop('u1');host.messages[mid]['info']['id']=mid
        host.messages[mid]['parts'][0]['messageID']=mid;host.messages['a1']['info']['parentID']=mid
        self.host.host=host;p=proposal(text,'MISSION_CONTROL',action)
        if invoke:return hosted_interaction(self.service,{'proposal':p},now_ms=NOW)['operations'][0]
        turn=actual_host_user_turn(self.host,now_ms=NOW)
        return decide(turn,parse_proposal(p,turn)[0],self.owner.candidates(turn),now_ms=NOW)
    def count(self,event=None):
        with closing(sqlite3.connect(self.db)) as c:
            return c.execute('SELECT count(*) FROM events'+(' WHERE event_type=?' if event else ''),(event,) if event else ()).fetchone()[0]
    def test_pause_continue_stop_no_new_mission_or_direct_dispatch(self):
        sessions=len(self.host.sessions);messages=len(self.host.messages)
        for text,action,status in [('暂停测试','pause','PAUSED'),('继续测试','continue','ACTIVE'),('停止测试','stop','CANCELLED')]:
            result=self.control(text,action);self.assertEqual(result['status'],'COMPLETED')
            self.assertEqual(self.runtime.replay_composed(self.mission).core_state.mission.status.value,status)
        self.assertEqual(len(self.host.sessions),sessions);self.assertEqual(len(self.host.messages),messages)
        self.assertEqual(self.count('mission.created'),1)
    def test_query_on_paused_mission_creates_no_mission_or_event(self):
        self.control('暂停测试','pause');before=self.count()
        self.host.host=HostFixture('查询任务状态');p=proposal('查询任务状态','MISSION_QUERY','query')
        result=hosted_interaction(self.service,{'proposal':p},now_ms=NOW)
        self.assertEqual(result['operations'][0]['status'],'ADMITTED');self.assertEqual(self.count(),before)
        self.assertEqual(self.count('mission.created'),1)
    def test_duplicate_concurrent_controls_single_transition(self):
        op=self.control('暂停测试','pause',invoke=False);barrier=threading.Barrier(2)
        def execute(_):
            barrier.wait();return apply_control(self.service,self.owner,op)
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(execute,range(2)))
        self.assertEqual({r['status'] for r in results},{'COMPLETED','REPLAYED'})
        self.assertEqual(self.count('mission.paused'),1)
    def test_crash_after_state_before_receipt_recovers_without_second_pause(self):
        op=self.control('暂停测试','pause',invoke=False)
        with patch.object(self.owner,'complete',side_effect=OSError('receipt interrupted')):
            with self.assertRaises(OSError):apply_control(self.service,self.owner,op)
        self.assertEqual(self.owner.receipt(op['operation_id'])['state'],'BOUND')
        result=apply_control(self.service,self.owner,op)
        self.assertEqual(result['status'],'COMPLETED');self.assertEqual(self.count('mission.paused'),1)
        self.assertEqual(apply_control(self.service,self.owner,op)['status'],'REPLAYED')
    def test_crash_before_state_recovers_and_changed_request_is_rejected(self):
        op=self.control('暂停测试','pause',invoke=False);prepare_control(self.service,self.owner,op);self.owner.bind(op['operation_id'],op['subject'])
        self.assertEqual(apply_control(self.service,self.owner,op)['status'],'COMPLETED')
        changed={**op,'request_digest':'f'*64}
        with self.assertRaisesRegex(RuntimeError,'REPLAY_CONFLICT'):apply_control(self.service,self.owner,changed)
    def test_paused_mission_blocks_fresh_g4_effect_and_gate_resume(self):
        self.control('暂停测试','pause');service=G4RealExecutionService(self.runtime)
        with patch.object(_R2_5_G4RealExecutionService,'execute_capability') as effect, patch.object(_R2_5_G4RealExecutionService,'complete_human_takeover') as resume:
            with self.assertRaisesRegex(RuntimeError,'MISSION_NOT_ACTIVE'):service.execute_capability(self.mission,{})
            with self.assertRaisesRegex(RuntimeError,'MISSION_NOT_ACTIVE'):service.complete_human_takeover(self.mission,{})
            effect.assert_not_called();resume.assert_not_called()
    def test_pause_waits_for_admitted_effect_then_rejects_next_effect(self):
        service=G4RealExecutionService(self.runtime);started=threading.Event();release=threading.Event();calls=[]
        def physical(*args):started.set();release.wait(3);calls.append('physical');return {'status':'COMPONENT_EFFECT'}
        op=self.control('暂停测试','pause',invoke=False)
        with patch.object(_R2_5_G4RealExecutionService,'execute_capability',side_effect=physical):
            with ThreadPoolExecutor(max_workers=2) as pool:
                effect=pool.submit(service.execute_capability,self.mission,{})
                self.assertTrue(started.wait(2));pause=pool.submit(apply_control,self.service,self.owner,op)
                time.sleep(.05);release.set();effect.result();pause.result();reconcile_controls(self.service)
            with self.assertRaisesRegex(RuntimeError,'MISSION_NOT_ACTIVE'):service.execute_capability(self.mission,{})
        self.assertEqual(calls,['physical'])
    def test_old_noop_continue_cannot_undo_new_pause(self):
        old=self.control('继续测试','continue',invoke=False)
        self.control('暂停测试','pause')
        result=apply_control(self.service,self.owner,old)
        self.assertEqual(result['result']['effect'],'NONE')
        self.assertEqual(self.runtime.replay_composed(self.mission).core_state.mission.status.value,'PAUSED')
    def test_noop_pause_crash_cannot_create_transition_after_new_continue(self):
        self.control('暂停测试','pause');old=self.control('暂停测试','pause',invoke=False)
        newer=self.control('继续测试','continue',invoke=False)
        with patch.object(self.owner,'complete',side_effect=OSError('noop receipt crash')):
            with self.assertRaises(OSError):apply_control(self.service,self.owner,old)
        # A separate already-authorized request applies a newer control; the
        # stale pending observation must not reinterpret itself after restart.
        apply_control(self.service,self.owner,newer)
        result=apply_control(self.service,self.owner,old)
        self.assertEqual(result['result']['effect'],'NONE');self.assertEqual(self.count('mission.paused'),1)
        self.assertEqual(self.runtime.replay_composed(self.mission).core_state.mission.status.value,'ACTIVE')
    def test_old_effectful_pause_rejected_after_new_control_generation(self):
        old=self.control('暂停测试','pause',invoke=False)
        self.control('暂停测试','pause');self.control('继续测试','continue')
        result=apply_control(self.service,self.owner,old)
        self.assertEqual(result['result']['reason'],'STALE_CONTROL_GENERATION')
        self.assertEqual(self.count('mission.paused'),1)
    def test_long_effect_pause_durable_and_background_recovers_no_user_turn(self):
        service=G4RealExecutionService(self.runtime);started=threading.Event();release=threading.Event()
        def physical(*args):started.set();release.wait(10);return {'status':'COMPONENT_EFFECT'}
        op=self.control('暂停测试','pause',invoke=False)
        with patch.object(_R2_5_G4RealExecutionService,'execute_capability',side_effect=physical):
            with ThreadPoolExecutor(max_workers=1) as pool:
                effect=pool.submit(service.execute_capability,self.mission,{})
                self.assertTrue(started.wait(2));begin=time.monotonic()
                result=apply_control(self.service,self.owner,op)
                self.assertLess(time.monotonic()-begin,1)
                self.assertEqual(result['status'],'CONTROL_PENDING')
                self.assertIn('control_intent',self.owner.receipt(op['operation_id']))
                time.sleep(5.2);self.assertFalse(effect.done());release.set();effect.result()
            # Same product G4 boundary cannot begin another effect while the
            # pause is queued; then the non-LLM recovery owner drains it.
            with self.assertRaisesRegex(RuntimeError,'MISSION_CONTROL_PENDING'):service.execute_capability(self.mission,{})
            recovered=reconcile_controls(self.service)
        self.assertEqual(recovered['status'],'PASS');self.assertEqual(self.count('mission.paused'),1)
        self.assertEqual(reconcile_controls(self.service)['operations'],[])
    def test_actual_product_intake_can_queue_pause_while_g4_holds_effect_lock(self):
        from aitest_runtime.primary_sessions import PrimarySessionOwner
        from aitest_runtime import product_entry
        self.host.base_url='http://127.0.0.1:4096'
        primary=PrimarySessionOwner(self.runtime,WORKSPACE,self.host).ensure_current();sid=primary['session_id']
        text='暂停测试 BLOAN-PF1.1.0';payload={'proposal':proposal(text,'MISSION_CONTROL','pause',scope={'mode':'EXPLICIT_SET','version':'BLOAN-PF1.1.0'})}
        h=HostFixture(text);h.messages['u1']['info']['time']['created']=int(time.time()*1000)
        for row in h.messages.values():
            row['info']['sessionID']=sid
            for part in row['parts']:part['sessionID']=sid
        h.messages['a1']['info']['agent']='aitest-director'
        h.messages['a1']['parts']=[{'type':'tool','tool':'aitest_director','sessionID':sid,'messageID':'a1','callID':'c',
            'state':{'status':'running','input':{'action':'interact','payload':payload}}}]
        self.host.host=h;service=G4RealExecutionService(self.runtime);started=threading.Event();release=threading.Event()
        def physical(*args):started.set();release.wait(5);return {'status':'COMPONENT_EFFECT'}
        with patch.object(_R2_5_G4RealExecutionService,'execute_capability',side_effect=physical), patch.object(product_entry,'workspace_root',return_value=WORKSPACE), patch.object(product_entry,'orchestration_service',return_value=self.service), patch.dict(os.environ,{'AITEST_HOST_SESSION_ID':sid,'AITEST_HOST_MESSAGE_ID':'a1','AITEST_HOST_CALL_ID':'c'}):
            with ThreadPoolExecutor(max_workers=1) as pool:
                effect=pool.submit(service.execute_capability,self.mission,{})
                self.assertTrue(started.wait(2));begin=time.monotonic()
                result=product_entry.orchestration_command('DIRECTOR','interact',payload)
                self.assertLess(time.monotonic()-begin,1);item=result['operations'][0]
                self.assertEqual(item['status'],'CONTROL_PENDING')
                self.assertIn('control_intent',self.owner.receipt(item['operation_id']))
                release.set();effect.result()
        reconcile_controls(self.service)
        self.assertEqual(self.runtime.replay_composed(self.mission).core_state.mission.status.value,'PAUSED')
    def test_invalid_blocked_pause_is_durably_rejected_without_blocking_continue(self):
        from aitest_runtime.durable_core import CommandEnvelope, ActorRef
        blocked=self.runtime.execute(CommandEnvelope('block-for-test','BLOCK_MISSION',self.mission,self.runtime.get_head_seq(self.mission),ActorRef('SYSTEM','test'),{'reason':'fixture'}))
        self.assertTrue(blocked.ok)
        result=self.control('暂停测试','pause')
        self.assertEqual(result['result']['reason'],'CONTROL_INVALID_FROM_STATE')
        self.assertEqual(self.owner.receipt(result['operation_id'])['state'],'COMPLETED')
        resumed=self.control('继续测试','continue');self.assertEqual(resumed['result']['status'],'ACTIVE')
        self.assertEqual(pending_controls(self.runtime),[])
    def test_completed_history_is_excluded_before_pending_page_limit(self):
        for _ in range(4):self.control('继续测试','continue')
        op=self.control('暂停测试','pause',invoke=False);prepare_control(self.service,self.owner,op)
        pending=pending_controls(self.runtime,limit=1)
        self.assertEqual([r['operation_id'] for r in pending],[op['operation_id']])
        self.assertEqual(pending_controls(self.runtime,mission_id='unrelated',stopping_only=True,limit=1),[])
        apply_control(self.service,self.owner,op);self.assertEqual(pending_controls(self.runtime,limit=1),[])
    def test_control_intent_atomic_replay_and_legacy_unprepared_claim_denied(self):
        op=self.control('暂停测试','pause',invoke=False);prepare_control(self.service,self.owner,op)
        self.assertTrue(self.owner.receipt(op['operation_id'])['control_intent'])
        self.runtime.rebuild_projections()
        self.assertEqual(apply_control(self.service,self.owner,op)['status'],'COMPLETED')
        old=self.control('继续测试','continue',invoke=False);self.owner.claim(old)
        with self.assertRaisesRegex(RuntimeError,'MISSION_CONTROL_RECONCILIATION_REQUIRED'):apply_control(self.service,self.owner,old)
    def test_paused_g21_reconciliation_keeps_owned_session(self):
        # Separate Mission uses the production provisioning/reconciliation owner,
        # with only Host transport substituted. The non-G21 initial one is intact.
        service=G21AutonomousOrchestrationService(self.runtime,WORKSPACE,session_provider=self.host)
        self.host.host=HostFixture('测试 PF3.0.0')
        self.host.host.messages['u1']['info']['id']='u-new';self.host.host.messages['u1']['parts'][0]['messageID']='u-new'
        self.host.host.messages['u-new']=self.host.host.messages.pop('u1');self.host.host.messages['a1']['info']['parentID']='u-new'
        created=hosted_interaction(service,{},action='start_test',now_ms=NOW)
        mission=created['operations'][0]['subject']['subject_id']
        self.service=service
        op=self.control('暂停测试 PF3.0.0','pause',invoke=False)
        # Literal scope is Runtime validated against actual text.
        p=proposal('暂停测试 PF3.0.0','MISSION_CONTROL','pause',scope={'mode':'EXPLICIT_SET','version':'PF3.0.0'})
        turn=actual_host_user_turn(self.host,now_ms=NOW);op=decide(turn,parse_proposal(p,turn)[0],self.owner.candidates(turn),now_ms=NOW)
        apply_control(service,self.owner,op);before=set(self.host.sessions)
        service.reconcile_external_sessions();self.assertEqual(set(self.host.sessions),before)
        self.assertEqual(self.runtime.replay_composed(mission).core_state.mission.status.value,'PAUSED')

if __name__=='__main__':unittest.main()
