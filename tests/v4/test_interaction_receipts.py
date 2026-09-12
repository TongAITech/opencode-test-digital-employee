"""Real canonical SQLite command/event/replay tests; fake host/session transport only."""
import copy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import multiprocessing
import os
from pathlib import Path
from contextlib import closing
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'workspace-template/ai-test/runtime'))
from aitest_runtime.canonical_runtime import create_canonical_runtime
from aitest_runtime.durable_core import ActorRef, CommandEnvelope, RuntimeError, RuntimeService, SubjectRef
from aitest_runtime.interaction_admission import decide, literal_start_proposal, parse_proposal, mission_intake
from aitest_runtime.interaction_receipts import R1InteractionOwner, ROOT_KIND, stream_id, interaction_receipt_extension
from aitest_runtime.hosted_interaction import hosted_interaction
from aitest_runtime.autonomous_orchestration import AutonomousOrchestrationService, FakeOpenCodeSessionProvider
from test_interaction_admission import NOW, HostFixture, turn, proposal

WORKSPACE=Path(__file__).resolve().parents[2]/'workspace-template'

def _process_claim(db, operation, barrier, results):
    owner=R1InteractionOwner(create_canonical_runtime(WORKSPACE,db_path=Path(db)))
    barrier.wait(timeout=15)
    results.put(owner.claim(operation)['fresh'])

class HybridProvider(FakeOpenCodeSessionProvider):
    def __init__(self,text='测试 BLOAN-PF1.1.0'):
        super().__init__(WORKSPACE);self.host=HostFixture(text)
    def _directory_query(self):return self.host._directory_query()
    def _request(self,*args):return self.host._request(*args)


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.db=Path(self.temp.name)/'spine.db'
        self.runtime=create_canonical_runtime(WORKSPACE,db_path=self.db)
        self.owner=R1InteractionOwner(self.runtime)
        self.t=turn('测试 PF1.0.0');self.op=decide(self.t,parse_proposal(literal_start_proposal(self.t),self.t)[0],[],now_ms=NOW)
    def tearDown(self):self.temp.cleanup()
    def mission(self, version=None, message=None):
        t=turn('测试 '+(version or 'PF1.0.0'),message or 'u1')
        op=decide(t,parse_proposal(literal_start_proposal(t),t)[0],[],now_ms=NOW)
        service=AutonomousOrchestrationService(self.runtime,WORKSPACE,session_provider=FakeOpenCodeSessionProvider(WORKSPACE))
        result=service.intake_mission(mission_intake(t,op))
        return {'subject_kind':'MISSION','subject_id':result['intake']['mission_id']}
    def count(self, table):
        with closing(sqlite3.connect(self.db)) as c, c:return c.execute('SELECT count(*) FROM '+table).fetchone()[0]
    def test_receipt_root_is_not_mission_and_restores_replay(self):
        self.assertTrue(self.owner.claim(self.op)['fresh']);self.assertEqual(self.count('mission_projection'),0)
        restarted=R1InteractionOwner(create_canonical_runtime(WORKSPACE,db_path=self.db))
        self.assertFalse(restarted.claim(self.op)['fresh'])
        state=restarted.runtime.get_subject_state(SubjectRef(ROOT_KIND,stream_id(self.op['operation_id'])))
        self.assertEqual(state.root_state.receipt['state'],'CLAIMED')
        self.assertTrue(restarted.runtime.verify_projection(stream_id(self.op['operation_id']))['ok'])
        self.assertEqual(restarted.runtime.rebuild_projections()['rebuilt'],1)
        self.assertEqual(self.count('mission_projection'),0)
    def test_two_concurrent_claimers_only_one_fresh(self):
        barrier=threading.Barrier(2)
        def claim(_):
            owner=R1InteractionOwner(create_canonical_runtime(WORKSPACE,db_path=self.db));barrier.wait();return owner.claim(self.op)['fresh']
        with ThreadPoolExecutor(max_workers=2) as pool:values=list(pool.map(claim,range(2)))
        self.assertEqual(sorted(values),[False,True]);self.assertEqual(self.count('events'),1)
    def test_two_processes_share_one_durable_claim(self):
        ctx=multiprocessing.get_context('spawn');barrier=ctx.Barrier(2);results=ctx.Queue()
        processes=[ctx.Process(target=_process_claim,args=(str(self.db),self.op,barrier,results)) for _ in range(2)]
        for process in processes:process.start()
        try:
            values=[results.get(timeout=20) for _ in processes]
            for process in processes:process.join(timeout=20);self.assertEqual(process.exitcode,0)
            self.assertEqual(sorted(values),[False,True]);self.assertEqual(self.count('events'),1)
        finally:
            for process in processes:
                if process.is_alive():process.terminate();process.join()
    def test_changed_host_text_scope_or_intent_conflicts(self):
        self.owner.claim(self.op)
        changed=copy.deepcopy(self.op);changed['request_digest']='f'*64
        with self.assertRaisesRegex(RuntimeError,'REPLAY_CONFLICT'):self.owner.claim(changed)
        changed=copy.deepcopy(self.op);changed['host_turn_ref']['source_digest']='f'*64
        with self.assertRaisesRegex(RuntimeError,'REPLAY_CONFLICT'):self.owner.claim(changed)
        other=decide(self.t,parse_proposal(proposal(self.t.text,'GENERAL_CHAT','respond'),self.t)[0],[],now_ms=NOW)
        self.assertEqual(other['operation_id'],self.op['operation_id'])
        with self.assertRaisesRegex(RuntimeError,'REPLAY_CONFLICT'):self.owner.claim(other)
        for field,value in [('resolved_scope',{'version':'PF2.0.0'}),('subject',{'subject_kind':'MISSION','subject_id':'another'})]:
            changed=copy.deepcopy(self.op);changed[field]=value
            with self.assertRaisesRegex(RuntimeError,'REPLAY_CONFLICT'):self.owner.claim(changed)
    def test_real_mission_binding_completion_and_mixed_rebuild(self):
        self.owner.claim(self.op);target=self.mission();self.owner.bind(self.op['operation_id'],target)
        self.owner.complete(self.op['operation_id'],{'status':'PLANNING','mission_id':target['subject_id']})
        original=self.owner.receipt(self.op['operation_id'])
        restarted=R1InteractionOwner(create_canonical_runtime(WORKSPACE,db_path=self.db))
        replay=restarted.claim(self.op)
        self.assertFalse(replay['fresh']);self.assertEqual(replay['state'],'COMPLETED');self.assertEqual(replay['result'],original['result'])
        self.assertEqual(self.count('mission_projection'),1)
        self.assertEqual(restarted.runtime.rebuild_projections()['rebuilt'],2)
        self.assertEqual(restarted.receipt(self.op['operation_id']),original)
        self.assertTrue(restarted.runtime.verify_projection(stream_id(self.op['operation_id']))['ok'])
    def test_cross_root_kind_scope_and_fixed_target_rejected(self):
        target=self.mission();other=self.mission('PF2.0.0','u2');self.owner.claim(self.op)
        with self.assertRaises(RuntimeError):self.owner.bind(self.op['operation_id'],{'subject_kind':'GENERAL_WORK','subject_id':target['subject_id']})
        with self.assertRaisesRegex(RuntimeError,'SCOPE_MISMATCH'):self.owner.bind(self.op['operation_id'],other)
        self.owner.bind(self.op['operation_id'],target)
        with self.assertRaisesRegex(RuntimeError,'BIND_STATE'):self.owner.bind(self.op['operation_id'],target)
    def test_pending_and_reconcile_never_become_complete_on_replay(self):
        self.owner.claim(self.op);self.owner.uncertain(self.op['operation_id'],'InjectedAfterPossibleDispatch')
        resumed=R1InteractionOwner(create_canonical_runtime(WORKSPACE,db_path=self.db)).claim(self.op)
        self.assertFalse(resumed['fresh']);self.assertEqual(resumed['state'],'RECONCILE_REQUIRED')
        with self.assertRaisesRegex(RuntimeError,'COMPLETE_STATE'):self.owner.complete(self.op['operation_id'],{'status':'PASS'})
    def test_job_binding_requires_same_operation_host_and_purpose(self):
        from aitest_runtime.canonical_runtime import canonical_extension_manifests
        from aitest_runtime.general_work import GeneralWorkService,general_work_extension
        for intent,kind in [('GENERAL_WORK','GENERAL_WORK'),('AITEST_DIAGNOSIS','RUNTIME_DIAGNOSIS')]:
            for mismatch in ['operation','host','purpose',None]:
                with self.subTest(intent=intent,mismatch=mismatch):
                    manifest=general_work_extension()
                    manifests=tuple(m for m in canonical_extension_manifests() if m.extension_id!=manifest.extension_id)+(manifest,)
                    runtime=RuntimeService(Path(self.temp.name)/(kind+str(mismatch)+'.db'),extensions=manifests)
                    owner=R1InteractionOwner(runtime);t=turn('检查 launcher 日志')
                    p=proposal(t.text,intent,'read' if intent=='GENERAL_WORK' else 'diagnose')
                    p['operations'][0]['arguments']={'purpose':'inspect launcher logs'}
                    operation=decide(t,parse_proposal(p,t)[0],[],now_ms=NOW);owner.claim(operation)
                    host=copy.deepcopy(operation['host_turn_ref'])
                    if mismatch=='host':host['host_tool_message_id']='another-assistant'
                    job=GeneralWorkService(runtime).create(subject_kind=kind,
                        operation_id='another-operation' if mismatch=='operation' else operation['operation_id'],
                        host_turn_ref=host,intent='different purpose' if mismatch=='purpose' else 'inspect launcher logs',actor=ActorRef('SYSTEM','interaction-admission'))
                    if mismatch:
                        with self.assertRaisesRegex(RuntimeError,'CROSS_ROOT_'+mismatch.upper()+'_MISMATCH'):owner.bind(operation['operation_id'],job.subject.to_dict())
                        self.assertEqual(owner.receipt(operation['operation_id'])['state'],'CLAIMED')
                    else:
                        owner.bind(operation['operation_id'],job.subject.to_dict())
                        self.assertEqual(owner.receipt(operation['operation_id'])['state'],'BOUND')
                    self.assertEqual(runtime.rebuild_projections()['rebuilt'],2)
    def test_stale_cas_and_transaction_failure_no_partial_events(self):
        self.owner.claim(self.op)
        result=self.runtime.execute(CommandEnvelope('stale','RECONCILE_INTERACTION_OPERATION',stream_id(self.op['operation_id']),0,ActorRef('SYSTEM','interaction-admission'),{'subject':{'subject_kind':ROOT_KIND,'subject_id':stream_id(self.op['operation_id'])},'reason':'stale'}))
        self.assertEqual(result.error_code,'EXPECTED_SEQ_MISMATCH');self.assertEqual(self.count('events'),1)
        # Failure injection occurs within the real canonical transaction.
        from aitest_runtime.canonical_runtime import canonical_extension_manifests
        failed_db=Path(self.temp.name)/'failure.db'
        observed=[]
        def fail(stage):
            observed.append(stage)
            if stage=='after_event_insert':raise OSError('injected transaction fault')
        r=RuntimeService(failed_db,extensions=canonical_extension_manifests(),failure_injector=fail)
        with self.assertRaisesRegex(OSError,'injected transaction fault'):R1InteractionOwner(r).claim(self.op)
        self.assertEqual(observed,['after_command_insert','after_event_insert'])
        with closing(sqlite3.connect(failed_db)) as conn, conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM commands').fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT count(*) FROM events').fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT count(*) FROM interaction_operation_projection').fetchone()[0],0)
    def test_context_recovery_filters_current_host_session(self):
        self.mission();self.assertEqual(len(self.owner.candidates(self.t)),1)
        self.assertTrue(self.owner.candidates(self.t)[0].contextual)
        self.assertFalse(self.owner.candidates(replace(self.t,host_session_id='other'))[0].contextual)


class ProductEntryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.db=Path(self.temp.name)/'spine.db'
        self.runtime=create_canonical_runtime(WORKSPACE,db_path=self.db)
        self.provider=HybridProvider()
        self.service=AutonomousOrchestrationService(self.runtime,WORKSPACE,session_provider=self.provider)
        self.env=patch.dict(os.environ,{'AITEST_HOST_SESSION_ID':'s1','AITEST_HOST_MESSAGE_ID':'a1'});self.env.start()
    def tearDown(self):self.env.stop();self.temp.cleanup()
    def test_start_then_replay_opens_one_real_logical_planner_with_fake_transport(self):
        a=hosted_interaction(self.service,{},action='start_test',now_ms=NOW)
        self.assertEqual(a['operations'][0]['status'],'DISPATCHED',a)
        b=hosted_interaction(self.service,{},action='start_test',now_ms=NOW)
        self.assertEqual(b['operations'][0]['status'],'REPLAYED',b)
        with closing(sqlite3.connect(self.db)) as c, c:
            self.assertEqual(c.execute('SELECT count(*) FROM mission_projection').fetchone()[0],1)
        self.assertEqual(len(self.provider.sessions),1)
    def test_chat_negation_and_quoted_have_zero_mission_and_receipt_events(self):
        for text,intent,action in [('你好','GENERAL_CHAT','respond'),('不要测试 PF1.0.0','TEST_MISSION_START','start'),('“测试 PF1.0.0”','TEST_MISSION_START','start')]:
            self.provider.host=HostFixture(text)
            hosted_interaction(self.service,{'proposal':proposal(text,intent,action)},now_ms=NOW)
        with closing(sqlite3.connect(self.db)) as c, c:self.assertEqual(c.execute('SELECT count(*) FROM events').fetchone()[0],0)
        self.assertEqual(len(self.provider.sessions),0)
    def test_general_and_diagnosis_use_typed_jobs_without_mission(self):
        import time
        for i,(text,intent,action) in enumerate([('解释这个 Java 方法','GENERAL_WORK','read'),('检查 launcher 为什么慢','AITEST_DIAGNOSIS','diagnose')]):
            self.provider.host=HostFixture(text)
            user=self.provider.host.messages.pop('u1');mid='general-user-'+str(i)
            user['info'].update(id=mid,time={'created':int(time.time()*1000)})
            user['parts'][0]['messageID']=mid
            self.provider.host.messages[mid]=user
            self.provider.host.messages['a1']['info']['parentID']=mid
            result=hosted_interaction(self.service,{'proposal':proposal(text,intent,action)})
            self.assertEqual(result['operations'][0]['status'],'ACTIVE')
        with closing(sqlite3.connect(self.db)) as c, c:
            self.assertEqual(c.execute('SELECT count(*) FROM mission_projection').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT count(*) FROM general_work_projection').fetchone()[0],2)
        self.assertEqual(len(self.provider.sessions),2)
    def test_possible_dispatch_effect_never_repeats_after_fault(self):
        original=self.service.continue_test
        def dispatch_then_fail(*args,**kwargs):
            original(*args,**kwargs)
            raise OSError('injected after physical provider dispatch')
        with patch.object(self.service,'continue_test',side_effect=dispatch_then_fail):
            first=hosted_interaction(self.service,{},action='start_test',now_ms=NOW)
        self.assertEqual(first['operations'][0]['status'],'RECONCILE_REQUIRED')
        second=hosted_interaction(self.service,{},action='start_test',now_ms=NOW)
        self.assertEqual(second['operations'][0]['status'],'RECONCILE_REQUIRED')
        self.assertEqual(second['operations'][0]['reason'],'OPERATION_ALREADY_CONSUMED')
        self.assertEqual(len(self.provider.sessions),1)
        with closing(sqlite3.connect(self.db)) as c, c:self.assertEqual(c.execute('SELECT count(*) FROM mission_projection').fetchone()[0],1)
    def test_changed_semantic_proposal_cannot_reuse_completed_operation(self):
        hosted_interaction(self.service,{},action='start_test',now_ms=NOW)
        p=proposal(self.provider.host.messages['u1']['parts'][0]['text'],'GENERAL_CHAT','respond')
        with self.assertRaisesRegex(RuntimeError,'REPLAY_CONFLICT'):
            hosted_interaction(self.service,{'proposal':p},now_ms=NOW)
    def test_exposed_legacy_aliases_and_missing_host_cannot_bypass(self):
        from aitest_runtime import product_entry
        with patch.object(product_entry,'orchestration_service',return_value=self.service):
            self.assertEqual(product_entry.orchestration_command('DIRECTOR','intake_mission',{'request':{}})['reason'],'ACTION_NOT_AUTHORIZED_FOR_G2_ROLE')
            with patch.dict(os.environ,{'AITEST_HOST_SESSION_ID':'','AITEST_HOST_MESSAGE_ID':''}):
                with self.assertRaisesRegex(ValueError,'HOST_USER_TURN_REQUIRED'):product_entry.orchestration_command('DIRECTOR','start_test',{'request':{}})
    def test_pause_commits_before_separately_authorized_mixed_start(self):
        text='暂停这次测试，测试 PF2.0.0';self.provider.host=HostFixture('测试 BLOAN-PF1.1.0')
        hosted_interaction(self.service,{},action='start_test',now_ms=NOW)
        self.provider.host=HostFixture(text);self.provider.host.messages['u1']['info']['id']='u2';self.provider.host.messages['u1']['parts'][0]['messageID']='u2';self.provider.host.messages['u2']=self.provider.host.messages.pop('u1');self.provider.host.messages['a1']['info']['parentID']='u2'
        from aitest_runtime.interaction_admission import clauses
        slots=clauses(text)
        p={'operations':[{'intent':intent,'action':action,'start':slot['start'],'end':slot['end']} for slot,intent,action in zip(slots,['MISSION_CONTROL','TEST_MISSION_START'],['pause','start'])]}
        result=hosted_interaction(self.service,{'proposal':p},now_ms=NOW)
        self.assertEqual(result['operations'][0]['result']['status'],'PAUSED')
        self.assertEqual(result['operations'][1]['status'],'DISPATCHED')
        paused=result['operations'][0]['subject']['subject_id']
        self.assertEqual(self.runtime.replay_composed(paused).core_state.mission.status.value,'PAUSED')
        with closing(sqlite3.connect(self.db)) as c, c:self.assertEqual(c.execute('SELECT count(*) FROM mission_projection').fetchone()[0],2)

if __name__=='__main__':unittest.main()
