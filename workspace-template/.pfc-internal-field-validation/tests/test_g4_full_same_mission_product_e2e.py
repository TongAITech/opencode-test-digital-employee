from __future__ import annotations
import json, os, subprocess, sys, tempfile, time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping
WORKSPACE=Path(__file__).resolve().parents[2]; RUNTIME=WORKSPACE/'ai-test/runtime'; sys.path.insert(0,str(RUNTIME)); sys.path.insert(0,str(Path(__file__).parent))
from aitest_runtime import product_entry
from aitest_runtime.autonomous_orchestration import FakeOpenCodeSessionProvider
from aitest_runtime.canonical_runtime import create_canonical_runtime
from aitest_runtime.durable_core import canonical_sha256
from aitest_runtime.g2_1.managed_orchestration import G21AutonomousOrchestrationService
from aitest_runtime.g3.coverage import CoverageProviderResult, MappingCoveragePlatformProvider
from aitest_runtime.g3.service import G3TestingIntelligenceService
from aitest_runtime.g4.service import G4RealExecutionService
from aitest_runtime.r3_3.service import R33ApplicationService
from aitest_runtime.r3_e2.contracts import BrowserContextRef
from test_g3_testing_intelligence_product_path import make_repo, intake_request, binding, finish, human_gate_request

_STAGE_T0=time.monotonic()
def stage(msg):
    # Diagnostics are opt-in; final evidence remains structured JSON.
    if os.environ.get('AITEST_G4_E2E_STAGE_DEBUG') == '1':
        print(f"[G4-E2E +{time.monotonic()-_STAGE_T0:.1f}s] {msg}", flush=True)

class DeterministicExecutor:
    def __init__(self, capability_id='API'):
        self.capability_id=capability_id; self.capability_status='AVAILABLE'
        self.safety_profile={'construction_fixture':True}; self.auth_requirements={}
        self.side_effect_classification='ISOLATED_TEST_FIXTURE'; self.retry_semantics={'idempotent_fixture':True}
        self.evidence_channels=('PROVIDER_RESULT',); self.executions=0; self.cleanups=0
    def prepare(self, step, runtime_facts): return {'step':dict(step),'runtime_facts':dict(runtime_facts)}
    def execute(self, prepared, execution_context):
        self.executions+=1; return {'actual':prepared['step'].get('fixture_actual') or prepared['step'].get('expected'),'expected':prepared['step'].get('expected'),'n':self.executions}
    def observe(self, result): return {'actual':result['actual'],'oracle_result':'PASS' if result['actual']==result['expected'] else 'FAIL','oracle_reason':'deterministic governed provider observation','source_identity':f'deterministic:{self.capability_id.lower()}','side_effect_summary':'construction fixture only'}
    def collect_evidence(self, result): return [f'artifact:deterministic-{self.capability_id.lower()}-{result["n"]}']
    def cleanup(self, result): self.cleanups+=1; return {'cleaned':True}

class BrowserPort:
    def __init__(self, ref: BrowserContextRef): self.identity=ref; self.owner='AI'; self.handoffs=0; self.resume_ready=True
    def _ref(self): return BrowserContextRef(self.identity.browser_session_id,self.identity.browser_context_id_or_epoch,self.identity.context_binding_digest,self.owner,self.identity.observed_at)
    def inspect_context(self, ref):
        if (ref.browser_session_id,ref.browser_context_id_or_epoch,ref.context_binding_digest)!=(self.identity.browser_session_id,self.identity.browser_context_id_or_epoch,self.identity.context_binding_digest): raise AssertionError('CONTEXT_REPLACED')
        return self._ref()
    def inspect_lease(self, ref): self.inspect_context(ref); return self.owner
    def transfer_lease(self, ref, *, from_owner, to_owner):
        self.inspect_context(ref)
        if self.owner != from_owner: raise AssertionError(f'LEASE_OWNER:{self.owner}')
        self.owner=to_owner; self.handoffs+=1; return SimpleNamespace(to_dict=lambda:{'same_context':True,'handoff_id':f'h{self.handoffs}','from':from_owner,'to':to_owner})
    def verify_resume_condition(self, *, mission_id, browser_context_ref, resume_condition, completion_mode):
        self.inspect_context(browser_context_ref)
        if self.owner != 'HUMAN': raise AssertionError('RESUME_VERIFIER_REQUIRES_HUMAN_LEASE')
        if not self.resume_ready:
            return {'resume_safe':False,'auth_state':'UNAUTHENTICATED','page_identity':'MATCHED','business_state':'UNCHANGED','source_ref':'deterministic:r3e3-resume-verifier','evidence_digest':canonical_sha256({'mission_id':mission_id,'ready':False}),'observed_at':'2026-09-02T11:31:00Z'}
        return {'resume_safe':True,'auth_state':'AUTHENTICATED','page_identity':'MATCHED','business_state':'RESUME_SAFE','source_ref':'deterministic:r3e3-resume-verifier','evidence_digest':canonical_sha256({'mission_id':mission_id,'condition':dict(resume_condition),'mode':completion_mode}),'observed_at':'2026-09-02T11:31:00Z'}

def semantics():
 return {
 'source_refs':[{'source_id':'REQ-018','source_kind':'REQUIREMENT','revision':'V2','locator':'requirement://REQ-018'},{'source_id':'SST-018','source_kind':'SST','revision':'V2','locator':'sst://SST-018'},{'source_id':'DESIGN-018','source_kind':'DESIGN','revision':'V2','locator':'design://DESIGN-018'}],
 'business_rules':[{'text':'Requested limit must not exceed the approved limit','source_id':'REQ-018','obligation_id':'REQ-018-BR-1','code_refs':['src/CreditLimitService.java'],'api_refs':['POST /limits'],'permission_refs':['LIMIT_WRITE'],'security_refs':['AUTHZ_LIMIT_WRITE'],'actors':['credit-operator'],'start_state_refs':['APPROVED'],'end_state_refs':['SYNCED']}],
 'field_data_rules':[{'text':'Requested limit must be non-negative','source_id':'SST-018','code_refs':['src/CreditLimitService.java']}],
 'state_transitions':[{'text':'Approved update transitions to SYNCED','source_id':'SST-018','code_refs':['src/LimitSyncService.java'],'critical_journey_refs':['LIMIT_UPDATE_JOURNEY']}],
 'positive_paths':[{'text':'Below approved is accepted','source_id':'REQ-018'}], 'negative_paths':[{'text':'Above approved is rejected','source_id':'REQ-018'}],
 'exception_paths':[{'text':'Sync timeout remains retryable','source_id':'DESIGN-018'}], 'boundary_rules':[{'text':'Equal approved is accepted','source_id':'REQ-018','code_refs':['src/CreditLimitService.java']}],
 'permission_rules':[{'text':'Only LIMIT_WRITE can update','source_id':'REQ-018','permission_refs':['LIMIT_WRITE'],'security_refs':['AUTHZ_LIMIT_WRITE']}],
 'cross_system_flows':[{'text':'cfg-data update syncs before final UI success','source_id':'DESIGN-018','critical_journey_refs':['LIMIT_UPDATE_JOURNEY']}],
 'acceptance_criteria':[{'text':'API and UI expose same final limit','source_id':'REQ-018','api_refs':['POST /limits'],'page_refs':['src/views/LimitPage.vue']}],
 'non_functional_risks':[{'text':'Authorization and latency are risks','source_id':'DESIGN-018','performance_refs':['LIMIT_P95'],'security_refs':['AUTHZ_LIMIT_WRITE']}], 'unknowns':[]}

def snap(app,pct,seq,target_commit='head',details=None):
 return {'snapshot_id':f'bank:{app}:V2:{seq}','application_id':app,'target_version':'V2','baseline_label':'master','baseline_commit':'UNKNOWN','target_commit':target_commit,'observed_at':f'2026-09-02T11:{seq:02d}:00Z','coverage_semantics':'BANK_EFFECTIVE_INCREMENTAL','source_identity':f'bank:{app}:V2:master:{seq}','effective_incremental_coverage_pct':float(pct),'effective_changed_lines_total':100,'covered_changed_lines':int(pct),'uncovered_changed_lines':100-int(pct),'details':details or [{'level':'APPLICATION','application_id':app,'coverage_pct':float(pct)}]}

def approve(orch,mid,gid):
 return orch.decide_human_gate({'mission_id':mid,'gate_id':gid,'decision_id':'approve:'+gid,'outcome':'APPROVED','route':'NONE','decision_payload':{'approved':True},'decision_provenance':{'source_ref':'human:'+gid,'source_digest':canonical_sha256(gid),'observed_at':'2026-09-02T11:30:00Z'},'actor':{'type':'USER','id':'reviewer'}})

def g3_cycle(mid, orch, coverage_box, repos, cycle, replan_ref=None):
 scope={'requirement_id':'REQ-018','version':'V2','source_materials':[{'source_id':'REQ-018','source_kind':'REQUIREMENT','revision':'V2','content':'requested <= approved'},{'source_id':'SST-018','source_kind':'SST','revision':'V2','content':'sync to SYNCED'},{'source_id':'DESIGN-018','source_kind':'DESIGN','revision':'V2','content':'LIMIT_WRITE and API/UI agree'}]}
 if replan_ref: scope['replan_request_ref']=replan_ref
 stage(f'g3 cycle {cycle}: register intent')
 intent=product_entry.g3_command('DIRECTOR','register_intent',{'mission_id':mid,'intent_type':'TEST_CASE_DESIGN','scope':scope,'constraints':{'cycle':cycle}})
 stage(f'g3 cycle {cycle}: propose plan')
 plan_proposal={**intent['recommended_plan'],'planner_request_id':f"g3:{intent['intent']['fact_id']}:plan"}; plan_result=product_entry.orchestration_command('PLANNER','propose_plan',{'mission_id':mid,'proposal':plan_proposal}); first=plan_result['next'];
 if first is None: raise AssertionError('G3_PLAN_HANDOFF_FAILED:'+json.dumps(plan_result,sort_keys=True,default=str))
 b1=binding(first)
 stage(f'g3 cycle {cycle}: requirement')
 req=product_entry.g3_command('REQUIREMENT_ANALYST','analyze_requirement',{**b1,'scope_identity':'REQ-018','semantics':semantics()}); second=finish(orch,b1,f'req cycle {cycle}')['next']; b2=binding(second)
 stage(f'g3 cycle {cycle}: changes')
 ch=product_entry.g3_command('CODE_ANALYST','analyze_changes',{**b2,'scope_identity':'REQ-018','r3_1_reference':req['r3_1_reference'],'repositories':repos}); third=finish(orch,b2,f'change cycle {cycle}')['next']; b3=binding(third)
 java=ch['repositories'][0]['changed_files'][0]; lines=[int(str(x).rsplit('L',1)[1]) for x in java['diff_hunk_refs']]; uncovered=lines[-1]
 details=[{'level':'APPLICATION','application_id':'cfg-data','coverage_pct':80.0 if cycle==1 else 90.0}]+[{'level':'LINE','file_path':java['file_path'],'class_name':'CreditLimitService','line_number':ln,'covered':ln!=uncovered} for ln in lines]
 coverage_box['provider']=MappingCoveragePlatformProvider(CoverageProviderResult('AVAILABLE',('AGGREGATE','FILE','CLASS','LINE'),snapshot=snap('cfg-data',80 if cycle==1 else 90,cycle,target_commit=repos[0]['head_ref'],details=details)))
 stage(f'g3 cycle {cycle}: coverage')
 cov=product_entry.g3_command('CODE_ANALYST','acquire_coverage',{**b3,'profile':{'platform_profile_id':'bankcov','authenticated_context_ref':'auth','method':'API'},'query':{'application_id':'cfg-data','target_version':'V2','baseline_label':'master'},'change_analysis':ch['change_analysis']}); fourth=finish(orch,b3,f'coverage cycle {cycle}')['next']; b4=binding(fourth)
 gap=cov['coverage_gaps'][0]['fact_id'] if cov['coverage_gaps'] else cov['snapshot']['fact_id']
 risk={'dimensions':{'business_criticality':5,'change_magnitude':4,'impact_breadth':4,'change_uncertainty':2,'critical_journey_criticality':5,'historical_failure_signal':2,'security_data_sensitivity':4,'performance_sensitivity':4,'evidence_gap_penalty':2},'evidence_refs':[req['requirement']['fact_id'],ch['change_analysis']['fact_id'],cov['snapshot']['fact_id']]+([replan_ref] if replan_ref else []),'critical_journey_risk_refs':['LIMIT_UPDATE_JOURNEY'],'cycle':cycle}
 hyp={'hypothesis_id':f'HYP-E2E-{cycle}','trigger':'equality boundary','expected_invariant':'approved equality accepted consistently','suspected_surface':f'src/CreditLimitService.java:L{uncovered}','evidence_requirement':['API','DB'],'discriminating_test':'approved-1/approved/approved+1','defect_class':'BOUNDARY','severity':'HIGH','confidence_basis':['changed comparison',gap],'status':'READY_TO_TEST'}
 stage(f'g3 cycle {cycle}: strategy')
 st=product_entry.g3_command('TEST_STRATEGIST','create_strategy',{**b4,'scope_identity':'REQ-018','r3_1_reference':req['r3_1_reference'],'r3_2_references':ch['r3_2_references'],'risk_inputs':risk,'hypothesis_candidates':[hyp]})
 profiles={}
 if cycle==1:
  profiles['SECURITY']=product_entry.g3_command('TEST_STRATEGIST','design_test_profile',{**b4,'profile_type':'SECURITY','profile':{'authorized_scope':{'targets':['sut.test'],'environment':'TEST'},'oracle':{'pass':'no authorization bypass'},'safety_contract':{'target_environment':'TEST','rate_limits':{'rps':1},'safety_limits':{'destructive':False,'max_requests':2},'stop_conditions':['unexpected side effect'],'destructive':False}}})['profile']
  profiles['PERFORMANCE']=product_entry.g3_command('TEST_STRATEGIST','design_test_profile',{**b4,'profile_type':'PERFORMANCE','profile':{'authorized_scope':{'targets':['sut.test'],'environment':'TEST'},'oracle':{'pass':'p95 within governed SLO'},'slo':{'p95_ms':500},'safety_contract':{'target_environment':'TEST','load_model':{'vus':1,'duration_s':1},'resource_limits':{'max_vus':2},'stop_conditions':['error rate exceeds 1%']}}})['profile']
 fifth=finish(orch,b4,f'strategy cycle {cycle}')['next']; b5=binding(fifth)
 r33=R33ApplicationService(orch.runtime).state(mid); sid=st['strategy']['strategy_version_id']; pts=[p for p in r33.test_points if p.strategy_version_id==sid and p.designability=='DESIGNABLE'][:2]
 specs={p.point_id:{'objective':f'cycle {cycle} discriminate {p.point_id}','preconditions':[{'id':'P1','description':'authorized fixture ready'}],'test_data':[{'name':'approved','value':10000},{'name':'requested','value':10000}],'ordered_steps':[{'step':1,'action':'prepare exact boundary data'},{'step':2,'action':'submit governed request and observe synchronized state'}],'expected_results':[{'step':1,'expected':'boundary fixture is ready'},{'step':2,'expected':'API/data/downstream satisfy equality invariant'}],'oracle':{'type':'MULTI_CHANNEL_INVARIANT','pass':'all governed channels agree','insufficient':'any required channel missing'},'evidence_requirements':[{'channel':'API','required':'response'},{'channel':'DATA','required':'value'}],'postcondition':{'cleanup':'restore isolated record'},'coverage_gap_refs':[gap],'defect_hypothesis_refs':[st['hypotheses'][0]['fact_id']],'estimated_marginal_coverage_gain':1} for p in pts}
 stage(f'g3 cycle {cycle}: cases')
 cases=product_entry.g3_command('CASE_DESIGNER','design_cases',{**b5,'strategy_version_id':sid,'strategy_fingerprint':st['strategy']['strategy_fingerprint'],'detailed_specs':specs,'designer_session_ref':b5['session_id']}); sixth=finish(orch,b5,f'cases cycle {cycle}')['next']; b6=binding(sixth)
 firstcase=cases['ready_cases'][0]['case']; gid=f'g3-review-{cycle}'; hg=human_gate_request(b6,sixth['attempt'],gate_id=gid,gate_kind='APPROVAL',payload={'case_spec_ref':firstcase['fact_id'],'question':'approve?'},review=True)
 stage(f'g3 cycle {cycle}: evaluate case')
 ev=product_entry.g3_command('EVALUATOR','evaluate_case_design',{**b6,'scope_identity':'REQ-018','r3_1_reference':req['r3_1_reference'],'r3_2_reference':ch['r3_2_references'][0],'case_spec_fact_id':firstcase['fact_id'],'reviewer_session_ref':b6['session_id'],'human_gate_request':hg}); stage(f'g3 cycle {cycle}: evaluated'); approve(orch,mid,gid); stage(f'g3 cycle {cycle}: approved'); done=finish(orch,b6,f'review cycle {cycle}'); stage(f'g3 cycle {cycle}: review task finished')
 return {'intent':intent,'requirement':req,'change':ch,'coverage':cov,'strategy':st,'cases':cases,'evaluation':ev,'plan_done':done,'profiles':profiles}

def exec_task(k,case_ref):
 return {'task_key':k,'intent':f'execute governed G3 case {case_ref}','acceptance_criteria':[{'id':'evidence','description':'oracle/evidence durable'}],'routing':{'role':'EXECUTOR','required_capabilities':['OPENCODE_AGENT_SESSION','TASK_OUTCOME_REPORT'],'isolation_policy':'DEDICATED_TASK_SESSION','parallelism_policy':'PARALLEL_SAFE'}}

def latest_binding_for_task(orch, mid, task_id):
 execution=orch.runtime.replay_composed(mid).extension_state('r1_3b_execution_resume')
 latest=execution.latest_attempt(task_id)
 if latest is None: raise AssertionError(f'NO_CANONICAL_ATTEMPT:{task_id}')
 return {'mission_id':mid,'task_id':task_id,'attempt_id':latest.attempt_id,'session_id':latest.runtime_session_id,'root_attempt_id':latest.root_attempt_id}

def dispatch_selects(envelope, *, task_id, root_attempt_id):
 if envelope.get('task_id')==task_id: return True
 attempt=envelope.get('attempt') if isinstance(envelope.get('attempt'),dict) else {}
 rotation=envelope.get('rotation') if isinstance(envelope.get('rotation'),dict) else {}
 roots={str(x) for x in (envelope.get('root_attempt_id'),attempt.get('root_attempt_id'),rotation.get('root_attempt_id')) if x}
 return root_attempt_id in roots

def main():
 checks={}
 with tempfile.TemporaryDirectory(prefix='g4-full-e2e-') as td:
  root=Path(td); db=root/'runtime-spine.db'; os.environ['AITEST_WORKSPACE_ROOT']=str(root); os.environ['AITEST_RUNTIME_SPINE_DB']=str(db)
  repo1,b1,h1=make_repo(root,'cfg-data',{'src/CreditLimitService.java':'public class CreditLimitService { boolean ok(long r,long a){return r<a;} }\n'},{'src/CreditLimitService.java':'public class CreditLimitService { boolean ok(long r,long a){if(r<0)return false;return r<=a;} }\n','src/LimitSyncService.java':'public class LimitSyncService { String sync(){return "SYNCED";} }\n'})
  repo2,b2,h2=make_repo(root,'cfg-admin',{'src/LimitPage.vue':'<template><div>old</div></template>\n'},{'src/LimitPage.vue':'<template><button @click="submit">submit</button></template>\n','src/api/limit.ts':'export const load=()=>fetch("/limits")\n'})
  repos=[{'repository_id':'cfg-data','application_id':'cfg-data','repository_path':str(repo1),'base_ref':b1,'head_ref':h1},{'repository_id':'cfg-admin','application_id':'cfg-admin','repository_path':str(repo2),'base_ref':b2,'head_ref':h2}]
  runtime=create_canonical_runtime(root,db_path=db); provider=FakeOpenCodeSessionProvider(root); orch=G21AutonomousOrchestrationService(runtime,root,session_provider=provider); coverage_box={'provider':MappingCoveragePlatformProvider(CoverageProviderResult('SOURCE_UNAVAILABLE',()))}
  oo,od,og3,gb,gx=product_entry.orchestration_service,product_entry.default_service,product_entry.G3TestingIntelligenceService,product_entry._G4_BROWSER_PROVIDER,product_entry._G4_CAPABILITY_EXECUTORS
  api_executor=DeterministicExecutor('API'); security_executor=DeterministicExecutor('SECURITY'); performance_executor=DeterministicExecutor('PERFORMANCE'); product_entry._G4_CAPABILITY_EXECUTORS={'API':api_executor,'SECURITY':security_executor,'PERFORMANCE':performance_executor}; product_entry.orchestration_service=lambda _root=None: orch; product_entry.default_service=lambda _rt,_root: orch; product_entry.G3TestingIntelligenceService=lambda rt,orchestration=None:G3TestingIntelligenceService(rt,coverage_provider=coverage_box['provider'],orchestration=orchestration or orch)
  try:
   stage('start mission')
   started=product_entry.orchestration_command('DIRECTOR','start_test',{'request':intake_request()}); mid=started['intake']['intake']['mission_id']; checks['same_user_opencode_mission']=started['truth_source']=='R1_EVENT_STREAM'
   stage('g3 cycle 1')
   firstg3=g3_cycle(mid,orch,coverage_box,repos,1); initial_cases=[x['case'] for x in firstg3['cases']['ready_cases']]; checks['g3_requirement_git_strategy_case_review']=len(initial_cases)>=1 and firstg3['evaluation']['status']=='WAITING_FOR_HUMAN' and firstg3['plan_done']['next']['status']=='PLAN_COMPLETE'
   stage('g3 cycle 1 done')
   strategy1=firstg3['strategy']['strategy']['strategy_version_id']
   g4=G4RealExecutionService(runtime,orchestration=orch)
   goal=product_entry.g4_command('DIRECTOR','create_goal',{'mission_id':mid,'goal_id':'goal-95','project_id':'PFC','release_id':'V2','requirement_scope':['REQ-018'],'affected_applications':['cfg-data','cfg-admin'],'affected_application_target_versions':{'cfg-data':'V2','cfg-admin':'V2'},'coverage_policy':{'target_pct':95,'aggregation_policy':'PER_AFFECTED_APPLICATION','critical_gap_policy':'ZERO_UNRESOLVED_CRITICAL'}}); checks['g4_goal_95_durable']=goal['goal']['payload']['coverage_policy']['target_pct']==95.0
   case_refs=[x['fact_id'] for x in initial_cases[:2]] or [initial_cases[0]['fact_id']]
   batch1=g4.create_batch(mid,{'batch_id':'batch-1','goal_id':'goal-95','case_refs':case_refs,'strategy_version_id':strategy1,'target_application':'cfg-data','status':'READY','expected_value':{'reach':'first gaps','find':'high-value observations'}})
   stage('g4 batch1 plan')
   plan1=product_entry.orchestration_command('PLANNER','propose_plan',{'mission_id':mid,'proposal':{'objective':'execute G3 governed batch 1','tasks':[exec_task('EXEC-A',case_refs[0]),exec_task('EXEC-B',case_refs[-1])],'dependencies':[]}}); a=plan1['next']; ab=binding(a); g4.create_batch(mid,{'batch_id':'batch-1','goal_id':'goal-95','case_refs':case_refs,'strategy_version_id':strategy1,'target_application':'cfg-data','status':'RUNNING'})
   g3state=G3TestingIntelligenceService(runtime).state(mid); case_a_fact=g3state.by_id(case_refs[0]); case_b_fact=g3state.by_id(case_refs[-1]); assert case_a_fact is not None and case_b_fact is not None
   case_payload=case_a_fact.payload['r3_3_case']; case_id=str(case_payload['tc_id']); case_ver=str(case_payload['case_version_id'])
   g4.record_cursor(mid,{'task_id':ab['task_id'],'attempt_id':ab['attempt_id'],'case_id':case_id,'case_version':case_ver,'current_step_index':0,'completed_step_ids':[],'pending_step_id':'login','last_safe_checkpoint':'before-login','case_spec_fact_id':case_a_fact.fact_id,'execution_batch_id':'batch-1'})
   ref=BrowserContextRef('browser-session-e2e','context-epoch-e2e',canonical_sha256({'ctx':'e2e'}),'AI','2026-09-02T11:40:00Z'); bp=BrowserPort(ref); product_entry._G4_BROWSER_PROVIDER=bp
   stage('explicit takeover')
   takeover=product_entry.g4_command('EXECUTOR','request_human_takeover',{**ab,'human_gate_id':'g4-4a-explicit','takeover_id':'tk-explicit','case_id':case_id,'browser_context_ref':ref.to_dict(),'required_action':'complete 4A in same browser','reason':'4A_AUTH','allowed_scope':{'environment':'TEST'},'resume_mode':'AUTO_OR_EXPLICIT','resume_condition':{'auth':'verified'},'goal_id':'goal-95','mandatory_for_goal':True}); checks['human_takeover_product_entry_yields']=takeover['status']=='WAITING_HUMAN' and takeover['ai_turn']=='YIELD' and takeover['blocking_tool_call'] is False and bp.owner=='HUMAN'
   stage('dispatch independent B')
   b=orch.dispatch_next(mid); checks['waiting_a_allows_independent_b']=b['task_id']!=a['task_id'] and b['status']=='DISPATCHED'; bb=binding(b)
   # Control-loop restart + rotation on B.
   provider.set_observation(bb['session_id'],message_count=61,compaction_count=0,context_utilization=0.4,healthy=True); runtime_restart=create_canonical_runtime(root,db_path=db); orch_restart=G21AutonomousOrchestrationService(runtime_restart,root,session_provider=provider); product_entry.orchestration_service=lambda _root=None: orch_restart; product_entry.default_service=lambda _rt,_root: orch_restart
   stage('restart + rotation')
   tick=orch_restart.supervise_once(); rots=[x['result'] for x in tick['supervision'] if x.get('task_id')==bb['task_id'] and x.get('result',{}).get('status')=='ROTATED']; rot=rots[0]['rotation']; checks['session_rotation_control_restart']=rot['root_attempt_id']==b['attempt']['root_attempt_id']
   # New Runtime completes explicit human gate and recovers original cursor/context.
   stage('explicit resume')
   explicit=product_entry.g4_command('EXECUTOR','complete_human_takeover',{'mission_id':mid,'human_gate_id':'g4-4a-explicit','completion_mode':'EXPLICIT','verification':{'auth_state':'VERIFIED','page_identity':'VERIFIED','business_state':'RESUME_SAFE'},'source_ref':'human:4a','actor_id':'human'}); checks['explicit_resume_same_context_root_step']=explicit['resume_attempt_id']==ab['attempt_id'] and explicit['root_attempt_id']==a['attempt']['root_attempt_id'] and explicit['cursor']['payload']['pending_step_id']=='login' and bp.owner=='AI'
   lease_states=[f.payload['state'] for f in G4RealExecutionService(runtime_restart,orchestration=orch_restart,browser_provider=bp).state(mid).by_kind('BROWSER_LEASE') if str(f.payload.get('lease_id','')).startswith('lease:g4-4a-explicit:')]; checks['browser_lease_full_state_machine']=lease_states==['AI_CONTROLLED','TAKEOVER_REQUESTED','HUMAN_CONTROLLED','HUMAN_COMPLETED_PENDING_VERIFY','AI_RECLAIMING','AI_CONTROLLED']
   # A cannot preempt rotated B while B owns runnable slot. Rotation/recovery may return
   # a canonical repair envelope rather than the normal DISPATCHED shape, so infer identity
   # from durable execution lineage instead of changing the frozen Runtime contract.
   stillb=orch_restart.dispatch_next(mid); checks['human_completion_does_not_preempt_b']=dispatch_selects(stillb,task_id=b['task_id'],root_attempt_id=b['attempt']['root_attempt_id'])
   bcur=latest_binding_for_task(orch_restart,mid,b['task_id']); checks['b_root_attempt_preserved_after_rotation']=bcur['root_attempt_id']==b['attempt']['root_attempt_id']
   g4r=G4RealExecutionService(runtime_restart,orchestration=orch_restart,browser_provider=bp)
   stage('execute B api/security/perf')
   api_b=product_entry.g4_command('EXECUTOR','execute_capability',{**bcur,'capability_id':'API','case_id':str(case_b_fact.payload['r3_3_case']['tc_id']),'case_version':str(case_b_fact.payload['r3_3_case']['case_version_id']),'case_spec_fact_id':case_b_fact.fact_id,'execution_batch_id':'batch-1','executor_request':{'url':'https://sut.test/limits','method':'POST','authorized_scope':{'environment':'TEST'}},'step':{'step_id':'api-step','expected':'200/SYNCED','fixture_actual':'200/SYNCED'},'execution_node':'node-b'}); checks['api_execution_uses_provider_contract']=api_b['status']=='PASS' and api_b['execution']=='COMPLETED' and api_executor.executions>=1 and api_executor.cleanups>=1
   sec=product_entry.g4_command('EXECUTOR','execute_capability',{**bcur,'capability_id':'SECURITY','g3_test_profile_fact_id':firstg3['profiles']['SECURITY']['fact_id'],'case_id':str(case_b_fact.payload['r3_3_case']['tc_id']),'case_version':str(case_b_fact.payload['r3_3_case']['case_version_id']),'case_spec_fact_id':case_b_fact.fact_id,'execution_batch_id':'batch-1','executor_request':{},'step':{'step_id':'security-step','expected':'no authorization bypass','fixture_actual':'no authorization bypass'},'execution_node':'node-b'}); perf=product_entry.g4_command('EXECUTOR','execute_capability',{**bcur,'capability_id':'PERFORMANCE','g3_test_profile_fact_id':firstg3['profiles']['PERFORMANCE']['fact_id'],'case_id':str(case_b_fact.payload['r3_3_case']['tc_id']),'case_version':str(case_b_fact.payload['r3_3_case']['case_version_id']),'case_spec_fact_id':case_b_fact.fact_id,'execution_batch_id':'batch-1','executor_request':{},'step':{'step_id':'performance-step','expected':'p95 within governed SLO','fixture_actual':'p95 within governed SLO'},'execution_node':'node-b'}); checks['security_performance_execute_only_from_g3_profiles']=sec['status']=='PASS' and perf['status']=='PASS' and security_executor.executions==1 and performance_executor.executions==1 and security_executor.cleanups==1 and performance_executor.cleanups==1
   stage('complete B and recover A')
   bout=orch_restart.report_task_outcome(mid,task_id=bcur['task_id'],attempt_id=bcur['attempt_id'],session_id=bcur['session_id'],outcome='SUCCEEDED',summary='B complete'); arecovered=bout['next']; checks['a_resume_ready_after_b']=dispatch_selects(arecovered,task_id=a['task_id'],root_attempt_id=a['attempt']['root_attempt_id']); arb=latest_binding_for_task(orch_restart,mid,a['task_id'])
   # Second takeover uses AUTO to prove deterministic auto-resume, same root/cursor.
   g4r.record_cursor(mid,{'task_id':arb['task_id'],'attempt_id':arb['attempt_id'],'case_id':case_id,'case_version':case_ver,'current_step_index':1,'completed_step_ids':['login'],'pending_step_id':'confirm','last_safe_checkpoint':'after-login','case_spec_fact_id':case_a_fact.fact_id,'execution_batch_id':'batch-1'})
   stage('auto takeover/resume A')
   bp.resume_ready=False
   product_entry.g4_command('EXECUTOR','request_human_takeover',{**arb,'human_gate_id':'g4-auto','takeover_id':'tk-auto','case_id':case_id,'browser_context_ref':bp._ref().to_dict(),'required_action':'confirm protected page state','reason':'AUTH_REVERIFY','allowed_scope':{'environment':'TEST'},'resume_mode':'AUTO','resume_condition':{'protected_probe':'pass'},'goal_id':'goal-95','mandatory_for_goal':True})
   not_ready=product_entry.g4_command('DIRECTOR','control_tick',{'mission_id':mid,'goal_id':'goal-95','replan_context':{}}); checks['auto_resume_waits_for_real_runtime_observation']=bp.owner=='HUMAN' and not_ready['auto_resume']['status']=='WAITING'
   bp.resume_ready=True
   auto_tick=product_entry.g4_command('DIRECTOR','control_tick',{'mission_id':mid,'goal_id':'goal-95','replan_context':{}}); auto=G4RealExecutionService(runtime_restart,orchestration=orch_restart,browser_provider=bp).recover_cursor(mid,root_attempt_id=arb['root_attempt_id']); checks['deterministic_auto_resume']=auto['payload']['current_step_index']==1 and bp.owner=='AI' and 'g4-auto' in auto_tick['auto_resume']['resumed_gate_refs']
   g4r.record_step_result(mid,{'task_id':arb['task_id'],'attempt_id':arb['attempt_id'],'case_id':case_id,'case_version':case_ver,'step_id':'confirm','executor_capability':'BROWSER_UI','expected':'SYNCED visible','actual':'SYNCED visible','oracle_result':'PASS','oracle_reason':'page/business state verified','evidence_refs':['artifact:ui-a','artifact:network-a'],'source_identity':'sut:test','execution_node':'node-a','case_spec_fact_id':case_a_fact.fact_id,'execution_batch_id':'batch-1'})
   aout=orch_restart.report_task_outcome(mid,task_id=arb['task_id'],attempt_id=arb['attempt_id'],session_id=arb['session_id'],outcome='SUCCEEDED',summary='A complete'); checks['batch1_plan_complete']=aout['next']['status']=='PLAN_COMPLETE'; g4r.create_batch(mid,{'batch_id':'batch-1','goal_id':'goal-95','case_refs':case_refs,'strategy_version_id':strategy1,'target_application':'cfg-data','status':'COMPLETED'})
   # Fresh post-batch bank snapshots: both apps below target. These are real G3 provider facts consumed by G4.
   stage('batch1 coverage measure')
   refs=[]
   for app,pct,seq,head in [('cfg-data',90,41,h1),('cfg-admin',94,42,h2)]:
    svc=G3TestingIntelligenceService(runtime_restart,coverage_provider=MappingCoveragePlatformProvider(CoverageProviderResult('AVAILABLE',('AGGREGATE',),snapshot=snap(app,pct,seq,head))),orchestration=orch_restart); cv=svc.acquire_coverage(mid,{'platform_profile_id':'bankcov','authenticated_context_ref':'auth','method':'API'},{'application_id':app,'target_version':'V2','baseline_label':'master'}); refs.append(cv['snapshot']['fact_id']); g4r.record_coverage_from_g3(mid,{'measurement_id':f'm1-{app}','goal_id':'goal-95','batch_id':'batch-1','state':'AVAILABLE','g3_snapshot_fact_id':cv['snapshot']['fact_id']})
   gap=g4r.record_blocker_gap(mid,{'gap_id':'critical-remaining','goal_id':'goal-95','gap_kind':'TEST_DESIGN_GAP','severity':'CRITICAL','status':'OPEN','application_id':'cfg-data','file':'src/CreditLimitService.java','line':2,'reason':'critical changed line remains uncovered','source_refs':refs})
   g4r.record_iteration(mid,{'iteration_id':'iter-1','goal_id':'goal-95','coverage_before':{'cfg-data':0,'cfg-admin':0},'coverage_after':{'cfg-data':90,'cfg-admin':94},'new_changed_lines_covered':['cfg-data:1-90','cfg-admin:1-94'],'remaining_coverage_gaps':[gap['gap']['fact_id']],'cases_executed':case_refs,'status':'PROGRESSING','strategy_revision_ref':strategy1})
   stage('control tick -> replan')
   ctrl=product_entry.g4_command('DIRECTOR','control_tick',{'mission_id':mid,'goal_id':'goal-95','replan_context':{'strategy_revision_ref':strategy1,'actual_coverage_snapshot_refs':refs,'remaining_coverage_gap_refs':[gap['gap']['fact_id']]}}); replan_ref=ctrl['replan']['fact_id']; checks['unmet_target_creates_formal_g3_replan']=ctrl['status']=='REPLANNING' and ctrl['replan']['payload']['authority']=='G3' and ctrl['replan']['payload']['g4_case_authoring']=='FORBIDDEN'
   # G3 governed replan: a new durable TestIntent/plan creates a new Strategy and new Case, not manual G4 injection.
   stage('g3 cycle 2 governed replan')
   product_entry.orchestration_service=lambda _root=None: orch_restart; coverage_box['provider']=MappingCoveragePlatformProvider(CoverageProviderResult('SOURCE_UNAVAILABLE',())); secondg3=g3_cycle(mid,orch_restart,coverage_box,repos,2,replan_ref); strategy2=secondg3['strategy']['strategy']['strategy_version_id']; newcases=[x['case'] for x in secondg3['cases']['ready_cases']]; old_ids={x['fact_id'] for x in initial_cases}; checks['g3_real_replan_strategy_revision_new_case']=strategy2!=strategy1 and any(x['fact_id'] not in old_ids for x in newcases) and secondg3['plan_done']['next']['status']=='PLAN_COMPLETE'
   stage('g3 cycle 2 done; create next batch')
   newcase=next(x for x in newcases if x['fact_id'] not in old_ids); batch2=g4r.create_batch(mid,{'batch_id':'batch-2','goal_id':'goal-95','case_refs':[newcase['fact_id']],'strategy_version_id':strategy2,'target_application':'cfg-data','target_coverage_gaps':[gap['gap']['fact_id']],'status':'READY'}); checks['next_batch_comes_from_g3_governed_new_case']=batch2['batch']['payload']['case_refs']==[newcase['fact_id']]
   stage('execute governed batch2: propose plan')
   p2=orch_restart.propose_plan(mid,{'objective':'execute governed replan batch','tasks':[exec_task('EXEC-C',newcase['fact_id'])],'dependencies':[]})
   stage('execute governed batch2: plan returned')
   c=p2['next']; cb=binding(c); ncp=newcase['payload']['r3_3_case']
   stage('execute governed batch2: mark running')
   g4r.create_batch(mid,{'batch_id':'batch-2','goal_id':'goal-95','case_refs':[newcase['fact_id']],'strategy_version_id':strategy2,'target_application':'cfg-data','status':'RUNNING'})
   stage('execute governed batch2: cursor')
   g4r.record_cursor(mid,{'task_id':cb['task_id'],'attempt_id':cb['attempt_id'],'case_id':str(ncp['tc_id']),'case_version':str(ncp['case_version_id']),'current_step_index':0,'completed_step_ids':[],'pending_step_id':'execute','last_safe_checkpoint':'ready','case_spec_fact_id':newcase['fact_id'],'execution_batch_id':'batch-2'})
   stage('execute governed batch2: capability')
   product_entry.g4_command('EXECUTOR','execute_capability',{**cb,'capability_id':'API','case_id':str(ncp['tc_id']),'case_version':str(ncp['case_version_id']),'case_spec_fact_id':newcase['fact_id'],'execution_batch_id':'batch-2','executor_request':{'url':'https://sut.test/limits','method':'POST','authorized_scope':{'environment':'TEST'}},'step':{'step_id':'execute','expected':'critical line reached + invariant pass','fixture_actual':'critical line reached + invariant pass'},'execution_node':'node-c'})
   stage('execute governed batch2: outcome')
   cout=orch_restart.report_task_outcome(mid,task_id=cb['task_id'],attempt_id=cb['attempt_id'],session_id=cb['session_id'],outcome='SUCCEEDED',summary='replan case complete')
   stage('execute governed batch2: complete')
   g4r.create_batch(mid,{'batch_id':'batch-2','goal_id':'goal-95','case_refs':[newcase['fact_id']],'strategy_version_id':strategy2,'target_application':'cfg-data','status':'COMPLETED'})
   stage('final coverage + satisfaction')
   finalrefs=[]
   for app,pct,seq,head in [('cfg-data',96,51,h1),('cfg-admin',97,52,h2)]:
    svc=G3TestingIntelligenceService(runtime_restart,coverage_provider=MappingCoveragePlatformProvider(CoverageProviderResult('AVAILABLE',('AGGREGATE',),snapshot=snap(app,pct,seq,head))),orchestration=orch_restart); cv=svc.acquire_coverage(mid,{'platform_profile_id':'bankcov','authenticated_context_ref':'auth','method':'API'},{'application_id':app,'target_version':'V2','baseline_label':'master'}); finalrefs.append(cv['snapshot']['fact_id']); g4r.record_coverage_from_g3(mid,{'measurement_id':f'm2-{app}','goal_id':'goal-95','batch_id':'batch-2','state':'AVAILABLE','g3_snapshot_fact_id':cv['snapshot']['fact_id']})
   g4r.record_blocker_gap(mid,{'gap_id':'critical-remaining','goal_id':'goal-95','gap_kind':'TEST_DESIGN_GAP','severity':'CRITICAL','status':'RESOLVED','application_id':'cfg-data','file':'src/CreditLimitService.java','line':2,'reason':'covered by governed replan case','source_refs':finalrefs}); g4r.record_iteration(mid,{'iteration_id':'iter-2','goal_id':'goal-95','coverage_before':{'cfg-data':90,'cfg-admin':94},'coverage_after':{'cfg-data':96,'cfg-admin':97},'new_changed_lines_covered':['critical-remaining'],'remaining_coverage_gaps':[],'cases_executed':[newcase['fact_id']],'status':'TARGET_REACHED','strategy_revision_ref':strategy2}); final=product_entry.g4_command('DIRECTOR','control_tick',{'mission_id':mid,'goal_id':'goal-95'}); per=final['evaluation']['payload']['per_application']; checks['multi_app_target_and_critical_zero_satisfied']=final['status']=='SATISFIED' and per['cfg-data']['pct']>=95 and per['cfg-admin']['pct']>=95 and not final['evaluation']['payload']['unresolved_critical_gap_refs']
   checks['same_mission_end_to_end']=all(x['mission_id']==mid for x in [firstg3['requirement']['requirement'],firstg3['change']['change_analysis'],firstg3['strategy']['portfolio'],newcase,final['evaluation']])
   # Raw-source repair R-1: after the real same-Mission G3/G4 flow, materialized projections must exactly match Event replay.
   projection_verification=runtime_restart.verify_projection(mid)
   if projection_verification.get('ok') is not True:
    raise AssertionError('G3_G4_PROJECTION_VERIFICATION_FAILED:'+json.dumps(projection_verification,sort_keys=True,default=str))
   stage('e2e main completed')
  finally:
   product_entry.orchestration_service=oo; product_entry.default_service=od; product_entry.G3TestingIntelligenceService=og3; product_entry._G4_BROWSER_PROVIDER=gb; product_entry._G4_CAPABILITY_EXECUTORS=gx
 out={'status':'PASS' if all(checks.values()) else 'FAIL','passed':sum(checks.values()),'total':len(checks),'checks':checks}; print(json.dumps(out,ensure_ascii=False,indent=2,sort_keys=True)); return 0 if out['status']=='PASS' else 1
if __name__=='__main__': raise SystemExit(main())
