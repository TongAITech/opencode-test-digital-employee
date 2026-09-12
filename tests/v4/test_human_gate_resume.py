"""Actual R1/G4 owner with disposable browser transport; never bank/model PASS."""
import os, sys, tempfile, unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
ROOT=Path(__file__).resolve().parents[2]
WORKSPACE=ROOT/'workspace-template'
sys.path.insert(0,str(WORKSPACE/'ai-test/runtime'))
sys.path.insert(0,str(WORKSPACE/'.pfc-internal-field-validation/tests'))
from aitest_runtime.canonical_runtime import create_canonical_runtime
from aitest_runtime.autonomous_orchestration import FakeOpenCodeSessionProvider
from aitest_runtime.g2_1.managed_orchestration import G21AutonomousOrchestrationService
from aitest_runtime.g4.service import G4RealExecutionService
from aitest_runtime.durable_core import canonical_sha256, RuntimeError
from aitest_runtime.r3_e2.contracts import BrowserContextRef
from aitest_runtime.human_gate_resume_receipts import GateResumeReceipt
from test_g3_testing_intelligence_product_path import binding,intake_request
from test_g4_background_auto_resume_wave2 import BrowserPort,seed_g3,task

class Browser(BrowserPort):
    def verify_resume_condition(self,**kwargs):
        # Read-only verification supports either observed lease, as the product
        # CDP verifier does. Never change the actual lease to run a verifier.
        self.inspect_context(kwargs['browser_context_ref'])
        return {'resume_safe':self.resume_ready,'auth_state':'AUTHENTICATED' if self.resume_ready else 'UNVERIFIED',
            'page_identity':'MATCHED','business_state':'RESUME_SAFE','source_ref':'fixture:fresh-browser',
            'observed_at':'2026-09-12T00:00:00Z','evidence_digest':canonical_sha256({'ready':self.resume_ready})}

def seed(root,runtime,request=None,browser=None,provider=None,gate_id="gate-explicit"):
    provider = provider or FakeOpenCodeSessionProvider(root)
    orch = G21AutonomousOrchestrationService(runtime, root, session_provider=provider)
    mission_id = orch.start_test(request or intake_request())["intake"]["intake"]["mission_id"]
    # Frozen G4/R2.6 command IDs use globally unique domain IDs. Distinct
    # Missions share one Host and use distinct goal/batch/gate identities.
    goal_id='goal-explicit:'+canonical_sha256(mission_id)[:16]
    batch_id='batch-explicit:'+canonical_sha256(mission_id)[:16]
    case_fact, strategy_id = seed_g3(runtime, mission_id)
    plan = orch.propose_plan(
        mission_id,
        {
            "objective": "explicit user-turn resume",
            "tasks": [task()],
            "dependencies": [],
        },
    )
    dispatch_a = plan["next"]
    attempt = binding(dispatch_a)
    attempt["root_attempt_id"] = str(dispatch_a["attempt"]["root_attempt_id"])
    ref = BrowserContextRef("browser-explicit", "epoch-explicit", canonical_sha256({"ctx": "explicit"}), "AI", "2026-09-03T02:00:00Z")
    browser = browser or Browser(ref)
    if callable(getattr(browser,"context_ref",None)):ref=browser.context_ref()
    g4 = G4RealExecutionService(runtime, orchestration=orch, browser_provider=browser)
    g4.create_goal(mission_id, {
        "goal_id": goal_id,
        "project_id": "PFC",
        "release_id": "R2",
        "affected_applications": ["cfg-data"],
        "affected_application_target_versions": {"cfg-data": "V2"},
        "coverage_policy": {"target_pct": 95},
    })
    g4.create_batch(mission_id, {
        "batch_id": batch_id,
        "goal_id": goal_id,
        "case_refs": [case_fact["fact_id"]],
        "strategy_version_id": strategy_id,
        "target_application": "cfg-data",
        "status": "RUNNING",
    })
    g4.record_cursor(mission_id, {
        "task_id": attempt["task_id"],
        "attempt_id": attempt["attempt_id"],
        "case_id": "TC-AUTO",
        "case_version": "TC-AUTO:v1",
        "case_spec_fact_id": case_fact["fact_id"],
        "execution_batch_id": batch_id,
        "current_step_index": 2,
        "completed_step_ids": ["prepare", "navigate"],
        "pending_step_id": "verify-auth",
        "last_safe_checkpoint": "before-auth",
    })
    opened = g4.request_human_takeover(mission_id, {
        **attempt,
        "human_gate_id": gate_id,
        "takeover_id": "takeover-explicit",
        "case_id": "TC-AUTO",
        "browser_context_ref": ref.to_dict(),
        "required_action": "complete protected authentication",
        "reason": "AUTH_REQUIRED",
        "allowed_scope": {"environment": "TEST"},
        "resume_mode": "EXPLICIT",
        "resume_condition": {"authenticated": True, "page": "protected"},
        "goal_id": goal_id,
        "batch_id": batch_id,
        "mandatory_for_goal": True,
    })
    return mission_id,g4,browser,orch,attempt

class GateResumeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.db=self.root/'runtime-spine.db'
        self.runtime=create_canonical_runtime(self.root,db_path=self.db)
        self.mid,self.g4,self.browser,self.orch,self.attempt=seed(self.root,self.runtime)
        self.receipt=GateResumeReceipt(self.runtime,self.mid,'gate-explicit')
        self.request={'human_gate_id':'gate-explicit','completion_mode':'EXPLICIT','operation_id':'fixture-turn-a'}
    def tearDown(self):self.tmp.cleanup()
    def complete(self):return self.g4.complete_human_takeover(self.mid,self.request)
    def restart(self):
        self.runtime=create_canonical_runtime(self.root,db_path=self.db)
        self.g4=G4RealExecutionService(self.runtime,orchestration=self.orch,browser_provider=self.browser)
        self.receipt=GateResumeReceipt(self.runtime,self.mid,'gate-explicit')
    def test_fresh_verification_then_durable_replay(self):
        with self.assertRaisesRegex(RuntimeError,'REVALIDATION_FAILED'):self.complete()
        self.assertEqual(self.browser.owner,'HUMAN');self.assertEqual(self.receipt.state().phase,'REQUESTED')
        self.browser.resume_ready=True;result=self.complete();self.assertEqual(result['status'],'RESUME_SAFE')
        self.restart();self.assertEqual(self.complete(),result);self.assertEqual(self.browser.handoffs,2)
        self.runtime.rebuild_projections();self.assertEqual(self.receipt.state().phase,'COMPLETED')
    def test_crash_after_external_handback_no_second_transfer(self):
        self.browser.resume_ready=True;real=self.browser.transfer_lease
        def crash(*a,**kw):real(*a,**kw);raise SystemExit('process death after transfer')
        with patch.object(self.browser,'transfer_lease',side_effect=crash):
            with self.assertRaises(SystemExit):self.complete()
        self.assertEqual(self.receipt.state().phase,'HAND_BACK_INTENT');self.assertEqual(self.browser.owner,'AI')
        self.restart();self.assertEqual(self.complete()['status'],'RESUME_SAFE');self.assertEqual(self.browser.handoffs,2)
    def test_decision_commit_with_lost_return_is_recovered(self):
        self.browser.resume_ready=True;real=self.g4.human_gates.record_decision
        def crash(*a,**kw):real(*a,**kw);raise OSError('committed decision return lost')
        with patch.object(self.g4.human_gates,'record_decision',side_effect=crash):
            with self.assertRaises(OSError):self.complete()
        self.assertEqual(self.browser.owner,'AI');self.restart()
        self.assertEqual(self.complete()['status'],'RESUME_SAFE');self.assertEqual(self.browser.handoffs,2)
    def test_each_durable_boundary_recovers_once(self):
        # Every subcase owns a fresh actual R1/G4/Browser lineage.
        for phase in ('VERIFIED','HAND_BACK_INTENT','DECIDED','RESUME_SAFE','COMPLETED'):
            with self.subTest(phase=phase),tempfile.TemporaryDirectory() as td:
                root=Path(td);rt=create_canonical_runtime(root,db_path=root/'spine.db');mid,g4,browser,orch,_=seed(root,rt);browser.resume_ready=True
                real=GateResumeReceipt.record
                def crash(owner,stage,data):
                    result=real(owner,stage,data)
                    if stage==phase:raise SystemExit('after '+phase)
                    return result
                with patch.object(GateResumeReceipt,'record',new=crash):
                    with self.assertRaises(SystemExit):g4.complete_human_takeover(mid,self.request)
                rt=create_canonical_runtime(root,db_path=root/'spine.db');g4=G4RealExecutionService(rt,orchestration=orch,browser_provider=browser)
                self.assertEqual(g4.complete_human_takeover(mid,self.request)['status'],'RESUME_SAFE');self.assertEqual(browser.handoffs,2)
    def test_changed_context_after_handback_is_fenced(self):
        self.browser.resume_ready=True;real=GateResumeReceipt.record
        def crash(owner,phase,data):
            result=real(owner,phase,data)
            if phase=='HAND_BACK_INTENT':raise SystemExit()
            return result
        with patch.object(GateResumeReceipt,'record',new=crash):
            with self.assertRaises(SystemExit):self.complete()
        self.browser.identity=BrowserContextRef('other','other','other','HUMAN','2026-09-12T00:00:00Z')
        with self.assertRaises(AssertionError):self.complete()
        self.assertEqual(self.browser.handoffs,1)
    def test_two_controllers_one_decision(self):
        self.browser.resume_ready=True
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:self.complete(),range(2)))
        self.assertEqual(results[0],results[1]);self.assertEqual(self.browser.handoffs,2)

    def install_continuation(self):
        cursor=self.g4.recover_cursor(self.mid,root_attempt_id=self.attempt['root_attempt_id'])['payload']
        data={**cursor,'current_step_index':3,'pending_step_id':'submit',
            'last_safe_checkpoint':{'ui_journey_resume':{'task_id':self.attempt['task_id'],'capability_id':'UI','case_id':'TC-AUTO','case_version':'TC-AUTO:v1'}}}
        self.g4.record_cursor(self.mid,data)
    def test_continuation_sent_without_receipt_never_replays(self):
        self.install_continuation();self.browser.resume_ready=True;effects=[]
        def physical(*args):effects.append('submit');raise SystemExit('after actual submission')
        with patch.object(self.g4,'execute_capability',side_effect=physical):
            with self.assertRaises(SystemExit):self.complete()
        self.restart()
        with patch.object(self.g4,'execute_capability',side_effect=physical):
            result=self.complete();self.assertEqual(result['status'],'UNKNOWN_SIDE_EFFECT')
            self.g4.auto_resume_human_gates(self.mid)
        self.assertEqual(effects,['submit']);self.assertEqual(self.browser.handoffs,2)
        from aitest_runtime.g4.service import _R2_5_G4RealExecutionService
        with patch.object(_R2_5_G4RealExecutionService,'execute_capability') as direct:
            with self.assertRaisesRegex(RuntimeError,'UNKNOWN_SIDE_EFFECT_RECONCILIATION_REQUIRED'):
                self.g4.execute_capability(self.mid,{'capability_id':'UI','task_id':self.attempt['task_id']})
            direct.assert_not_called()
    def test_crash_after_continuation_claim_is_conservatively_unknown(self):
        self.install_continuation();self.browser.resume_ready=True;real=GateResumeReceipt.record;effects=[]
        def crash(owner,phase,data):
            result=real(owner,phase,data)
            if phase=='CONTINUATION_SENT':raise SystemExit('before physical call')
            return result
        with patch.object(GateResumeReceipt,'record',new=crash),patch.object(self.g4,'execute_capability',side_effect=lambda *args:effects.append(1)):
            with self.assertRaises(SystemExit):self.complete()
        self.restart();self.assertEqual(self.complete()['status'],'UNKNOWN_SIDE_EFFECT');self.assertEqual(effects,[])
    def test_background_finishes_closed_gate_after_receipt_crash(self):
        self.browser.resume_ready=True;real=GateResumeReceipt.record
        def crash(owner,phase,data):
            result=real(owner,phase,data)
            if phase=='DECIDED':raise SystemExit('before G4 facts')
            return result
        with patch.object(GateResumeReceipt,'record',new=crash):
            with self.assertRaises(SystemExit):self.complete()
        self.restart();result=self.g4.auto_resume_human_gates(self.mid)
        self.assertIn('gate-explicit',result['resumed_gate_refs']);self.assertEqual(self.receipt.state().phase,'COMPLETED')
        self.assertEqual(self.browser.handoffs,2)

    def test_auto_and_explicit_compete_for_one_gate(self):
        old=self.g4.state(self.mid).latest('HUMAN_TAKEOVER_REQUEST')
        self.g4._record(self.mid,'HUMAN_TAKEOVER_REQUEST',{**dict(old.payload),'resume_mode':'AUTO_OR_EXPLICIT'},provenance_refs=(old.fact_id,))
        self.browser.resume_ready=True
        def execute(mode):return self.g4.complete_human_takeover(self.mid,{**self.request,'completion_mode':mode})
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(execute,['AUTO','EXPLICIT']))
        self.assertEqual(results[0],results[1]);self.assertEqual(self.browser.handoffs,2)
    def test_owner_permit_allows_one_journaled_continuation_then_replays_receipt(self):
        from aitest_runtime.g4.service import _R2_5_G4RealExecutionService
        self.install_continuation();self.browser.resume_ready=True;effects=[]
        def physical(*args):effects.append('submit');return {'status':'PASS','evidence_refs':['fixture:physical-receipt']}
        with patch.object(_R2_5_G4RealExecutionService,'execute_capability',side_effect=physical):
            first=self.complete();self.assertEqual(first['ui_continuation']['status'],'PASS')
            self.restart();self.assertEqual(self.complete(),first)
        self.assertEqual(effects,['submit'])

    def test_fresh_product_cdp_adapter_recovers_lease_from_r1(self):
        from aitest_runtime.recovery_browser import CDPBrowserProvider
        config={'cdp_endpoint':'http://127.0.0.1:9222','allowed_origins':['http://127.0.0.1:8080']}
        class TransportFixture(CDPBrowserProvider):
            def _get(self,path):
                assert path=='/json/version'
                return {'webSocketDebuggerUrl':'ws://127.0.0.1:9222/devtools/browser/isolated-browser'}
            def verify_resume_condition(self,**kwargs):
                self.inspect_context(kwargs['browser_context_ref'])
                return {'resume_safe':True,'auth_state':'AUTHENTICATED','page_identity':'MATCHED','business_state':'RESUME_SAFE',
                    'source_ref':'fixture:cdp-dom-transport','evidence_digest':'a'*64,'observed_at':'2026-09-12T00:00:00Z'}
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);db=root/'spine.db';rt=create_canonical_runtime(root,db_path=db)
            browser=TransportFixture(root,config,rt);mid,g4,_,orch,_=seed(root,rt,browser=browser)
            actual=g4.human_gates.record_decision
            def crash(*a,**kw):actual(*a,**kw);raise SystemExit('decision committed')
            with patch.object(g4.human_gates,'record_decision',side_effect=crash):
                with self.assertRaises(SystemExit):g4.complete_human_takeover(mid,self.request)
            rt=create_canonical_runtime(root,db_path=db);fresh=TransportFixture(root,config,rt)
            self.assertIsNone(fresh._pending_owner);self.assertEqual(fresh.inspect_lease(fresh.context_ref()),'AI')
            g4=G4RealExecutionService(rt,orchestration=orch,browser_provider=fresh)
            with patch.object(fresh,'transfer_lease',side_effect=AssertionError('duplicate transfer')):
                self.assertEqual(g4.complete_human_takeover(mid,self.request)['status'],'RESUME_SAFE')

    def test_old_composition_cannot_write_or_rebuild_gate_owner_root(self):
        from aitest_runtime.canonical_runtime import canonical_extension_manifests
        from aitest_runtime.durable_core import RuntimeService
        from aitest_runtime.human_gate_resume_receipts import EXTENSION_ID
        with self.assertRaisesRegex(RuntimeError,'REVALIDATION_FAILED'):self.complete()
        old=RuntimeService(self.db,extensions=[m for m in canonical_extension_manifests() if m.extension_id!=EXTENSION_ID])
        with self.assertRaises(RuntimeError):old.assert_writable_compatible()
        with self.assertRaises(RuntimeError):old.rebuild_projections()
        self.assertEqual(self.receipt.state().phase,'REQUESTED')

class HostGateTests(unittest.TestCase):
    def setUp(self):
        from test_interaction_admission import NOW,turn
        from aitest_runtime.interaction_admission import literal_start_proposal,parse_proposal,decide,mission_intake
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.db=self.root/'spine.db'
        self.runtime=create_canonical_runtime(self.root,db_path=self.db)
        t=turn('测试 PF1.0.0');op=decide(t,parse_proposal(literal_start_proposal(t),t)[0],[],now_ms=NOW)
        self.mid,self.g4,self.browser,self.orch,self.attempt=seed(self.root,self.runtime,mission_intake(t,op))
        self.env=patch.dict(os.environ,{'AITEST_HOST_SESSION_ID':'s1','AITEST_HOST_MESSAGE_ID':'a1'});self.env.start()
        self.nextid=2
    def tearDown(self):self.env.stop();self.tmp.cleanup()
    def call(self,text='已登录',gate=None,clock_ms=None):
        from test_interaction_admission import HostFixture,NOW,proposal
        from test_interaction_receipts import HybridProvider
        from aitest_runtime.autonomous_orchestration import AutonomousOrchestrationService
        from aitest_runtime.hosted_interaction import hosted_interaction
        clock_ms=NOW if clock_ms is None else clock_ms
        self.clock=datetime.fromtimestamp(clock_ms/1000,timezone.utc).isoformat()
        provider=HybridProvider();provider.host=HostFixture(text)
        provider.host.messages['u1']['info']['time']['created']=clock_ms
        uid='u'+str(self.nextid);self.nextid+=1
        provider.host.messages[uid]=provider.host.messages.pop('u1');provider.host.messages[uid]['info']['id']=uid
        provider.host.messages[uid]['parts'][0]['messageID']=uid;provider.host.messages['a1']['info']['parentID']=uid
        service=AutonomousOrchestrationService(self.runtime,self.root,session_provider=provider)
        p=proposal(text,'HUMAN_GATE_RESPONSE','verify')
        if gate:p['operations'][0]['arguments']={'gate_id':gate}
        with patch('aitest_runtime.product_entry.g4_service',return_value=self.g4),patch('aitest_runtime.hosted_human_gate.now',return_value=self.clock),patch('aitest_runtime.human_gate_resume.now',return_value=self.clock):
            return hosted_interaction(service,{'proposal':p},now_ms=clock_ms)['operations'][0]
    def test_actual_host_phrase_is_request_then_background_resumes(self):
        from aitest_runtime.interaction_receipts import R1InteractionOwner
        result=self.call();self.assertEqual(result['status'],'WAITING_HUMAN');self.assertEqual(self.browser.owner,'HUMAN')
        claim=R1InteractionOwner(self.runtime).receipt(result['operation_id']);self.assertEqual(claim['gate_intent']['gate_id'],'gate-explicit')
        self.browser.resume_ready=True
        # No original Host messages/provider or another user turn needed.
        with patch('aitest_runtime.hosted_human_gate.now',return_value=self.clock),patch('aitest_runtime.human_gate_resume.now',return_value=self.clock):
            self.g4.auto_resume_human_gates(self.mid)
        claim=R1InteractionOwner(self.runtime).receipt(result['operation_id']);self.assertEqual(claim['state'],'COMPLETED')
        self.assertEqual(claim['result']['status'],'RESUME_SAFE');self.assertEqual(self.browser.handoffs,2)
    def test_quoted_negated_and_example_phrases_do_not_complete(self):
        for text in ('“已登录”','不要继续','例如已登录','如果已登录'):
            with self.subTest(text=text):
                result=self.call(text);self.assertIn(result['status'],{'DENIED','CLARIFICATION_REQUIRED'})
        self.assertEqual(self.browser.handoffs,1)
    def test_model_gate_argument_cannot_select_an_unrelated_gate(self):
        self.browser.resume_ready=True;result=self.call(gate='foreign-gate')
        self.assertEqual(result['result']['gate_id'],'gate-explicit');self.assertEqual(self.browser.handoffs,2)

    def other_mission(self,*,gate=False,authorized=True):
        from dataclasses import replace
        from test_interaction_admission import NOW,turn
        from aitest_runtime.interaction_admission import literal_start_proposal,parse_proposal,decide,mission_intake
        t=turn('测试 PF2.0.0','other-start')
        if not authorized:t=replace(t,host_session_id='foreign-host')
        op=decide(t,parse_proposal(literal_start_proposal(t),t)[0],[],now_ms=NOW);request=mission_intake(t,op)
        if gate:return seed(self.root,self.runtime,request,provider=self.orch.raw_session_provider,gate_id='gate-other')[0]
        return self.orch.start_test(request)['intake']['intake']['mission_id']
    def test_two_authorized_missions_select_one_compatible_gate(self):
        other=self.other_mission();self.browser.resume_ready=True;result=self.call()
        self.assertEqual(result['result']['mission_id'],self.mid);self.assertNotEqual(other,self.mid)
        self.assertEqual(result['result']['status'],'RESUME_SAFE')
    def test_two_compatible_gates_require_clarification_despite_model_gate_hint(self):
        other=self.other_mission(gate=True);self.browser.resume_ready=True;result=self.call(gate='gate-explicit')
        self.assertEqual(result['status'],'CLARIFICATION_REQUIRED')
        self.assertEqual({g['mission_id'] for g in result['compatible_gates']},{self.mid,other});self.assertEqual(self.browser.handoffs,1)
    def test_unrelated_host_gate_excluded(self):
        self.other_mission(gate=True,authorized=False);self.browser.resume_ready=True;result=self.call()
        self.assertEqual(result['result']['mission_id'],self.mid);self.assertEqual(result['result']['status'],'RESUME_SAFE')
    def test_expired_unstarted_request_rejected_then_new_host_turn_reauthorizes(self):
        from test_interaction_admission import NOW
        from aitest_runtime.interaction_receipts import R1InteractionOwner
        first=self.call();self.assertEqual(first['status'],'WAITING_HUMAN')
        later=datetime.fromtimestamp((NOW+3600000)/1000,timezone.utc).isoformat()
        with patch('aitest_runtime.hosted_human_gate.now',return_value=later),patch('aitest_runtime.human_gate_resume.now',return_value=later):
            self.browser.resume_ready=True;self.g4.auto_resume_human_gates(self.mid)
        owner=R1InteractionOwner(self.runtime);claim=owner.receipt(first['operation_id'])
        self.assertEqual(claim['result']['reason'],'HOST_USER_TURN_EXPIRED');self.assertEqual(self.browser.handoffs,1)
        new=self.call(clock_ms=NOW+3600000);self.assertEqual(new['result']['status'],'RESUME_SAFE')
        state=GateResumeReceipt(self.runtime,self.mid,'gate-explicit').state()
        self.assertEqual(state.intent['request_identity'],new['operation_id']);self.assertEqual(self.browser.handoffs,2)

if __name__=='__main__':unittest.main()
