"""Actual R1/entry/rotation, labeled Host transport fixture; not real-model E2E."""
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import copy
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools/v4_review'))
from progress_regression import request, proposal
from test_primary_sessions import Host
from aitest_runtime.canonical_runtime import create_canonical_runtime, canonical_extension_manifests
from aitest_runtime.durable_core import RuntimeError, RuntimeService, ActorRef, CommandEnvelope
from aitest_runtime.g2_1.managed_orchestration import G21AutonomousOrchestrationService
from aitest_runtime.mission_session_authority import MissionSessionOwner, EXTENSION_ID, EVENT, COMMAND, subject_for, now, stamp
from aitest_runtime.mission_tool_admission import model_command
from aitest_runtime.dispatch_receipts import dispatch_context
from aitest_runtime import product_entry

class Transport(Host):
    def session_activity(self,sid):return 'idle'
    def abort_session(self,sid):return {'aborted':True}

class AuthorityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)/'workspace';self.root.mkdir()
        self.runtime=create_canonical_runtime(self.root,db_path=Path(self.tmp.name)/'spine.db')
        self.host=Transport(self.root);self.service=G21AutonomousOrchestrationService(self.runtime,self.root,session_provider=self.host)
        self.owner=MissionSessionOwner(self.service)
        started=self.service.start_test(request('worker-authority'))
        self.mid=started['intake']['intake']['mission_id']
        self.planner=list(self.owner.state(self.mid).grants.values())[0]
    def tearDown(self):self.tmp.cleanup()
    def worker(self):
        self.service.propose_plan(self.mid,proposal('worker-authority'))
        return [g for g in self.owner.state(self.mid).grants.values() if g['task_id']][-1]
    def context(self,g,tool,action,data):
        ctx=self.host.call(g['session_id'],action,data)
        self.host.rows['a']['info']['agent']=g['agent_name']
        self.host.rows['a']['parts'][0]['tool']=tool
        return ctx
    def test_first_prompt_already_has_durable_authority_and_bound_provision(self):
        seen=[];original=self.host.send_context
        def send(**kw):
            e=json.loads(kw['text'].split('\n',1)[1]);mid=e['mission_id']
            grant=self.owner.current(mid,kw['session_id'],agent=kw['agent'])
            seen.append(grant);return original(**kw)
        with patch.object(self.host,'send_context',side_effect=send):g=self.worker()
        self.assertEqual(seen,[g]);self.assertEqual(g['epoch'],1)
        self.assertTrue(self.runtime.verify_projection(self.mid)['ok'])
    def test_planner_product_status_and_first_worker_tool_before_post_receipt(self):
        data={'mission_id':self.mid}
        with self.context(self.planner,'aitest_planner','status',data),patch.object(product_entry,'workspace_root',return_value=self.root),patch.object(product_entry,'orchestration_service',return_value=self.service):
            self.assertEqual(product_entry.orchestration_command('PLANNER','status',data)['truth_source'],'R1_EVENT_STREAM')
        original=self.host.send_context;calls=[]
        def send(**kw):
            g=self.owner.current(self.mid,kw['session_id']);d={'mission_id':self.mid}
            with self.context(g,'aitest_worker','status',d),patch.object(product_entry,'workspace_root',return_value=self.root),patch.object(product_entry,'orchestration_service',return_value=self.service):
                calls.append(product_entry.orchestration_command('EXECUTOR','status',d))
            return original(**kw)
        with patch.object(self.host,'send_context',side_effect=send):self.worker()
        self.assertEqual(len(calls),1)
    def test_copied_valid_payload_and_wrong_agent_tool_input_rejected_before_effect(self):
        g=self.worker();data={k:g[k] for k in ('session_id','task_id','attempt_id')};data['mission_id']=self.mid
        for mode in ('foreign_session','wrong_agent','wrong_tool','wrong_input','duplicate_call','wrong_task','cross_mission'):
            with self.subTest(mode=mode):
                d=copy.deepcopy(data);ctx=self.context(g,'aitest_requirement_analyst','work_context',d)
                if mode=='wrong_agent':self.host.rows['a']['info']['agent']='aitest-executor'
                if mode=='wrong_tool':self.host.rows['a']['parts'][0]['tool']='aitest_executor'
                if mode=='wrong_input':self.host.rows['a']['parts'][0]['state']['input']['action']='status'
                if mode=='duplicate_call':self.host.rows['a']['parts'].append(copy.deepcopy(self.host.rows['a']['parts'][0]))
                if mode=='wrong_task':d['task_id']='unowned'
                if mode=='cross_mission':d['mission_id']='unowned'
                before=self.runtime.get_head_seq(self.mid)
                with ctx:
                    if mode=='foreign_session':os.environ['AITEST_HOST_SESSION_ID']=self.planner['session_id']
                    with self.assertRaises(RuntimeError):
                        with model_command(self.service,'g3','REQUIREMENT_ANALYST','work_context',d):self.fail('effect admitted')
                self.assertEqual(self.runtime.get_head_seq(self.mid),before)
    def test_rotation_keeps_root_anchor_and_fences_predecessor(self):
        old=self.worker();anchors=self.runtime.replay_composed(self.mid).extension_state('r2_5_session_orchestration').to_dict()
        result=self.service.rotate_session(self.mid,task_id=old['task_id'],reasons=['TEST_FORCED_PRESSURE'])
        self.assertEqual(result['status'],'ROTATED');new=self.owner.current(self.mid,result['successor_session_id'])
        self.assertEqual(new['logical_agent_id'],old['logical_agent_id']);self.assertEqual(new['root_attempt_id'],old['root_attempt_id']);self.assertEqual(new['epoch'],2)
        self.assertNotEqual(new['attempt_id'],old['attempt_id']);self.assertEqual(self.owner.state(self.mid).grants[old['session_id']]['state'],'RETIRED')
        self.assertEqual(self.runtime.replay_composed(self.mid).extension_state('r2_5_session_orchestration').to_dict(),anchors)
        with self.assertRaisesRegex(RuntimeError,'STALE_CALLER'):self.owner.current(self.mid,old['session_id'])
        data={'mission_id':self.mid}
        with self.context(new,'aitest_worker','status',data):
            with model_command(self.service,'orchestration','EXECUTOR','status',data):pass
    def test_lease_retries_do_not_extend_and_foreign_realm_rejected(self):
        g=self.worker();before=self.runtime.get_head_seq(self.mid)
        self.assertEqual(self.owner.before_dispatch(self.mid,g['session_id'],g['agent_name']),g)
        self.assertEqual(self.runtime.get_head_seq(self.mid),before)
        with patch('aitest_runtime.mission_session_authority.now',return_value=(stamp(g['expires_at'])+timedelta(seconds=1)).isoformat()):
            with self.assertRaisesRegex(RuntimeError,'LEASE_EXPIRED'):self.owner.before_dispatch(self.mid,g['session_id'],g['agent_name'])
        self.host.base_url='http://127.0.0.1:9999'
        with self.assertRaisesRegex(RuntimeError,'HOST_REALM_MISMATCH'):self.owner.current(self.mid,g['session_id'])
        self.assertEqual(self.runtime.get_head_seq(self.mid),before)
    def test_crash_before_grant_recovers_same_session_before_send(self):
        original=self.owner.__class__.record
        def fail(owner,mid,op,data):
            if op=='GRANT' and data['task_id']:raise OSError('before grant')
            return original(owner,mid,op,data)
        with patch.object(MissionSessionOwner,'record',new=fail):
            with self.assertRaises(OSError):self.worker()
        sends=len(self.host.messages);sessions=len(self.host.sessions)
        g21=self.service.session_control.state(self.mid)
        bound=[p for p in g21.provisions if p.task_id][-1]
        self.assertNotIn(bound.external_session_id,self.owner.state(self.mid).grants)
        result=self.service.dispatch_next(self.mid)
        self.assertEqual(len(self.host.sessions),sessions);self.assertEqual(len(self.host.messages),sends+1)
        self.assertEqual(self.owner.current(self.mid,bound.external_session_id)['session_id'],bound.external_session_id)
    def test_unknown_send_cannot_regrant_or_blind_replay(self):
        original=self.host.send_context
        def fail(**kw):original(**kw);raise ConnectionError('accepted then connection lost')
        with patch.object(self.host,'send_context',side_effect=fail):
            self.worker()
        dispatches=self.service.session_control.state(self.mid).context_dispatches
        self.assertEqual(dispatches[-1]['phase'],'UNKNOWN')
        grants=[g for g in self.owner.state(self.mid).grants.values() if g['task_id']];self.assertEqual(len(grants),1)
        g=grants[0];sends=len(self.host.messages);sessions=len(self.host.sessions)
        self.service.dispatch_next(self.mid)
        self.assertEqual(len(self.host.messages),sends);self.assertEqual(len(self.host.sessions),sessions)
        self.assertEqual(self.owner.state(self.mid).grants[g['session_id']],g)
    def test_old_planner_cannot_act_after_accepted_plan(self):
        self.worker()
        with self.assertRaisesRegex(RuntimeError,'STALE_CALLER'):self.owner.current(self.mid,self.planner['session_id'])
    def test_planner_rotation_has_separate_lane_and_no_worker_attempt(self):
        old=self.planner
        result=self.service.rotate_planning_session(self.mid,old['session_id'],['TEST_FORCED_PRESSURE'])
        self.assertEqual(result['status'],'ROTATED');new=self.owner.current(self.mid,result['successor_session_id'])
        self.assertEqual(new['epoch'],2);self.assertEqual(new['logical_agent_id'],old['logical_agent_id'])
        self.assertEqual(new['planning_lineage'],old['planning_lineage'])
        self.assertIsNone(new['attempt_id']);self.assertIsNone(new['root_attempt_id'])
        with self.assertRaisesRegex(RuntimeError,'STALE_CALLER'):self.owner.current(self.mid,old['session_id'])
    def test_model_cannot_grant_and_old_owner_cannot_write_or_rebuild(self):
        seq=self.runtime.get_head_seq(self.mid)
        denied=self.runtime.execute(CommandEnvelope('hostile',COMMAND,self.mid,seq,ActorRef('AGENT','aitest-planner'),{'operation':'REQUEST','data':{}}))
        self.assertFalse(denied.ok);self.assertEqual(self.runtime.get_head_seq(self.mid),seq)
        old=RuntimeService(self.runtime.db_path,extensions=[m for m in canonical_extension_manifests() if m.extension_id!=EXTENSION_ID])
        with self.assertRaises(RuntimeError):old.assert_writable_compatible()
        with self.assertRaises(RuntimeError):old.rebuild_projections()
        self.assertTrue(self.runtime.verify_projection(self.mid)['ok'])
    def test_request_precedes_external_creation_and_root_survives_full_rebuild(self):
        original=self.host.create_session;seen=[]
        def create(**kw):
            pending=[p for p in self.service.session_control.state(self.mid).provisions if p.task_id and p.status=='REQUESTED']
            self.assertEqual(len(pending),1)
            seen.append(self.owner.state(self.mid).requests[pending[0].provision_token])
            return original(**kw)
        with patch.object(self.host,'create_session',side_effect=create):g=self.worker()
        self.assertEqual(len(seen),1);sid=subject_for(self.mid).subject_id
        before=self.runtime.replay_composed(sid).to_dict()
        self.runtime.rebuild_projections()
        self.assertEqual(self.runtime.replay_composed(sid).to_dict(),before)
        self.assertTrue(self.runtime.verify_projection(sid)['ok'])
        with closing(sqlite3.connect(self.runtime.db_path)) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM mission_projection').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT count(*) FROM events WHERE mission_id=? AND event_type=?',(self.mid,EVENT)).fetchone()[0],0)
    def test_admission_holds_controller_lock_until_effect_then_stale_call_rejects(self):
        g=self.worker();data={'mission_id':self.mid};started=threading.Event()
        def rotate():
            started.set();return self.service.rotate_session(self.mid,task_id=g['task_id'],reasons=['TEST_RACE'])
        with self.context(g,'aitest_worker','status',data),ThreadPoolExecutor(max_workers=1) as pool:
            with model_command(self.service,'orchestration','EXECUTOR','status',data):
                future=pool.submit(rotate);self.assertTrue(started.wait(2));time.sleep(.05)
                self.assertFalse(future.done());self.assertEqual(self.owner.current(self.mid,g['session_id']),g)
            self.assertEqual(future.result(timeout=10)['status'],'ROTATED')
            with self.assertRaisesRegex(RuntimeError,'STALE_CALLER'):
                with model_command(self.service,'orchestration','EXECUTOR','status',data):self.fail('stale effect')
    def test_primary_domain_mutation_and_worker_wrong_domain_reject_before_services(self):
        from aitest_runtime.primary_sessions import PrimarySessionOwner
        primary=PrimarySessionOwner(self.runtime,self.root,self.host).ensure_current()
        for family,tool,action in [('g3','aitest_g3_director','register_intent'),('g4','aitest_g4_director','create_goal')]:
            data={'mission_id':self.mid}
            with self.host.call(primary['session_id'],action,data),patch.object(product_entry,'workspace_root',return_value=self.root),patch.object(product_entry,'orchestration_service',return_value=self.service):
                self.host.rows['a']['parts'][0]['tool']=tool
                before=self.runtime.get_head_seq(self.mid)
                with self.assertRaisesRegex(RuntimeError,'PRIMARY_DIRECT_EXECUTION_BYPASS_DENIED'):getattr(product_entry,family+'_command')('DIRECTOR',action,data)
                self.assertEqual(self.runtime.get_head_seq(self.mid),before)
        g=self.worker();data={'mission_id':self.mid}
        with self.context(g,'aitest_executor','execute_capability',data),patch.object(product_entry,'workspace_root',return_value=self.root),patch.object(product_entry,'orchestration_service',return_value=self.service),patch.object(product_entry,'g4_service') as effects:
            with self.assertRaisesRegex(RuntimeError,'ROLE_MISMATCH'):product_entry.g4_command('EXECUTOR','execute_capability',data)
            effects.assert_not_called()
    def test_goal_revision_fences_planner_before_new_plan(self):
        goal=self.runtime.get_state(self.mid).goal(self.planner['goal_id'])
        result=self.runtime.execute(CommandEnvelope('revise-goal-test','REVISE_GOAL',self.mid,self.runtime.get_head_seq(self.mid),
            ActorRef('USER','test-owner'),{'goal_id':goal.goal_id,'base_revision':goal.revision,'goal':{**dict(goal.definition),'intent':'changed goal'}}))
        self.assertTrue(result.ok)
        with self.assertRaisesRegex(RuntimeError,'PLANNER_STALE'):self.owner.current(self.mid,self.planner['session_id'])
    def test_generic_diagnosis_does_not_acquire_formal_defect_hunter_privileges(self):
        p=proposal('diagnosis');p['tasks'][0]['routing']['role']='DIAGNOSIS'
        self.service.propose_plan(self.mid,p)
        g=[g for g in self.owner.state(self.mid).grants.values() if g['task_id']][-1];d={'mission_id':self.mid}
        with self.context(g,'aitest_worker','status',d):
            with model_command(self.service,'orchestration','EXECUTOR','status',d):pass
        with self.context(g,'aitest_diagnosis','status',d):
            with self.assertRaisesRegex(RuntimeError,'ROLE_MISMATCH'):
                with model_command(self.service,'g5','DIAGNOSIS','status',d):self.fail('formal privilege escalation')
    def test_formal_defect_hunter_actual_host_entry_is_admitted(self):
        p=proposal('defect');p['tasks'][0]['routing']['role']='DEFECT_HUNTER'
        self.service.propose_plan(self.mid,p)
        g=[g for g in self.owner.state(self.mid).grants.values() if g['task_id']][-1]
        d={k:g[k] for k in ('session_id','attempt_id','task_id')};d['mission_id']=self.mid
        with self.context(g,'aitest_diagnosis','status',d),patch.object(product_entry,'workspace_root',return_value=self.root),patch.object(product_entry,'orchestration_service',return_value=self.service),patch.object(product_entry,'create_canonical_runtime',return_value=self.runtime):
            self.assertEqual(product_entry.g5_command('DIAGNOSIS','status',d)['truth_source'],'R1_EVENT_STREAM')

if __name__=='__main__':unittest.main(verbosity=2)
