from __future__ import annotations
import json, os, sys, tempfile
from pathlib import Path
WORKSPACE=Path(__file__).resolve().parents[2]; RUNTIME=WORKSPACE/'ai-test/runtime'; TESTS=Path(__file__).parent
sys.path[:0]=[str(RUNTIME),str(TESTS)]
from aitest_runtime import product_entry
from aitest_runtime.autonomous_orchestration import FakeOpenCodeSessionProvider
from aitest_runtime.canonical_runtime import create_canonical_runtime
from aitest_runtime.durable_core import canonical_sha256
from aitest_runtime.g2_1.managed_orchestration import G21AutonomousOrchestrationService
from aitest_runtime.g2_1.router import AgentRoleRegistry
from aitest_runtime.r2_6.contracts import GATE_KINDS, OUTCOMES, ROUTES
from aitest_runtime.r2_6.service import HumanGateApplicationService
from aitest_runtime.r3_6.service import R36ApplicationService
from aitest_runtime.r4_1.contracts import campaign_digest, quality_version_digest
from aitest_runtime.r4_1.service import R41ApplicationService
from aitest_runtime.r4_3.service import R43ApplicationService
from test_g5_adversarial_defect_truth import explicit_code, safe_non_confirmed
from test_g5_worker_binding_and_recovery import G5_CAPABILITIES, binding, request, task

ALT=['ENVIRONMENT_PROBLEM','TEST_DATA_PROBLEM','AUTOMATION_DEFECT','CASE_SPEC_DEFECT','KNOWLEDGE_FACT_ERROR','UNKNOWN_INCONCLUSIVE']
HIGH={'severity':'S1','security_sensitive':True}; ORDINARY={'severity':'S3','security_sensitive':False,'performance_sensitive':False,'regulatory_sensitive':False}

def tref(t,i,d,c=1,o='EC0_RUNTIME_ORACLE'):
 return {'ref_type':t,'object_id':i,'object_version':'1','revision':1,'source_digest':d,'source_cursor':c,'origin':o,'observed_at':'2026-09-03T10:00:00Z','freshness':'CURRENT','availability':'AVAILABLE','field_validation_state':'NOT_APPLICABLE','correlation_id':'ec0:'+i}

def mk(root,s):
 rt=create_canonical_runtime(root,db_path=root/'runtime-spine.db'); orch=G21AutonomousOrchestrationService(rt,root,session_provider=FakeOpenCodeSessionProvider(root)); started=orch.start_test(request('human-'+s)); mid=started['intake']['intake']['mission_id']; first=orch.propose_plan(mid,task('DEFECT_HUNTER',sorted(G5_CAPABILITIES)))['next']; return rt,orch,mid,binding(first),first

def seed(rt,mid,s,sufficient=True):
 svc=R36ApplicationService(rt); origin={'mission_id':mid,'architecture_baseline_ref':'v7','source':'EC0_RUNTIME_ORACLE_FIXTURE'}; scope={'project_id':'PFC','environment_id':'TEST','version_scope':'G5-EC0'}; ev='evidence:'+s; aid='anomaly-'+s; cid='candidate-'+s; eid='evidence-'+s; rid='repro-'+s; fid='fp-'+s; did='defect-'+s
 assert svc.record_test_anomaly({'mission_id':mid,'idempotency_key':'a:'+s,'origin_lineage':origin,'anomaly':{'anomaly_id':aid,'scope':scope,'trigger':'FAIL','upstream_refs':{'observation':{'ref_id':'g4:obs:'+s,'digest':canonical_sha256({'o':s})}},'source_refs':[{'ref_id':'src:'+s,'digest':canonical_sha256({'s':s})}],'evidence_refs':[ev],'observed_digests':{'oracle':canonical_sha256({'x':s})},'candidate_signal':'governed failure'}}).ok
 assert svc.create_defect_candidate({'mission_id':mid,'idempotency_key':'c:'+s,'origin_lineage':origin,'candidate':{'candidate_id':cid,'scope':scope,'anomaly_refs':[aid],'classification':'PRODUCT_DEFECT_CANDIDATE','alternative_classifications':ALT,'hypothesis':'product invariant violated','affected_scope':{'component':'cfg-data'},'supporting_evidence_refs':[ev],'contradicting_evidence_refs':[]}}).ok
 assert svc.record_evidence_assessment({'mission_id':mid,'idempotency_key':'e:'+s,'origin_lineage':origin,'evidence_assessment':{'assessment_id':eid,'candidate_id':cid,'evidence_refs':[ev],'evidence_role':'PRIMARY','evidence_sufficiency':'SUFFICIENT' if sufficient else 'INSUFFICIENT','relevance':'DIRECT','verification_method':'GOVERNED_RUNTIME','freshness':'CURRENT','scope_match':'EXACT','conflict_refs':[],'evidence_class':'ENGINEERING_EVIDENCE'}}).ok
 assert svc.evaluate_reproducibility({'mission_id':mid,'idempotency_key':'r:'+s,'origin_lineage':origin,'reproducibility':{'reproducibility_id':rid,'candidate_id':cid,'status':'REPRODUCED','attempt_refs':['attempt:'+s+':1','attempt:'+s+':2'],'evidence_refs':[ev],'controlled_variables':{'build':'same'},'signature':'sig:'+s,'comparison':'same violation reproduced','blocking_basis':None}}).ok
 assert svc.assess_false_positive({'mission_id':mid,'idempotency_key':'f:'+s,'origin_lineage':origin,'false_positive':{'false_positive_id':fid,'candidate_id':cid,'status':'NOT_FALSE_POSITIVE','alternatives_considered':ALT,'evidence_refs':[ev],'unresolved_refs':[],'decision_basis':'alternatives excluded'}}).ok
 return {'candidate_id':cid,'assessment_id':did,'assessment':{'assessment_id':did,'candidate_id':cid,'outcome':'CONFIRMED_DEFECT','final_classification':'PRODUCT_DEFECT','evidence_assessment_refs':[eid],'reproducibility_ref':rid,'false_positive_ref':fid,'causal_basis_refs':[],'unresolved_contradiction_refs':[],'evidence_class':'ENGINEERING_EVIDENCE','decision_basis':'frozen prerequisites satisfied'}}

def ap(b,s,risk): return {**b,'candidate_id':s['candidate_id'],'defect_assessment':s['assessment'],'policy_context':risk}
def count(rt,mid): return sum(x.outcome=='CONFIRMED_DEFECT' for x in R36ApplicationService(rt).state(mid).defect_assessments)
def invoke(fn):
 try: return fn(),None
 except Exception as e: return None,e

def exact_ref(rt,mid,did):
 a=R36ApplicationService(rt).state(mid).defect_assessment(did); ev=next(e for e in rt.list_events(mid) if e.event_type=='r3.6.defect_truth_assessed.v1' and e.entity_id==did); return tref('R3_6_DEFECT_ASSESSMENT',did,a.defect_assessment_digest,ev.seq,ev.event_type)

def r41(rt,mid,s):
 svc=R41ApplicationService(rt); p=tref('PROJECT','p-'+s,canonical_sha256({'p':s})); sut=tref('SUT','sut-'+s,canonical_sha256({'sut':s})); fv=tref('FIELD_VALIDATION_STATE','fv-'+s,canonical_sha256({'fv':s})); req=tref('REQUIREMENT','req-'+s,canonical_sha256({'req':s})); q={'quality_version_id':'qv-'+s,'stream_owner_mission_id':mid,'project_ref':p,'sut_ref':sut,'environment_scope':{'environment_id':'TEST'},'version_label':'G5-EC0','requirement_baseline_refs':[req],'sst_baseline_refs':[],'design_baseline_refs':[],'source_refs':[req],'scope_digest':canonical_sha256({'scope':s}),'version_digest':'0'*64,'predecessor_version_ref':None,'field_validation_state_ref':fv}; q['version_digest']=quality_version_digest(q); qe=svc.create_quality_version(q).entity; qr=tref('QUALITY_VERSION',qe.quality_version_id,qe.version_digest,qe.created_seq,'r4.1.quality_version_created.v1'); c={'campaign_id':'camp-'+s,'stream_owner_mission_id':mid,'quality_version_ref':qr,'campaign_key':'ck-'+s,'campaign_kind':'SCOPED_EVALUATION','campaign_digest':'0'*64,'baseline_selection_revision_ref':None,'current_selection_revision_ref':None,'provenance':[req]}; c['campaign_digest']=campaign_digest(c); ce=svc.create_test_campaign(c).entity; return qr,[tref('TEST_CAMPAIGN',ce.campaign_id,ce.campaign_digest,ce.created_seq,'r4.1.test_campaign_created.v1')]

def main():
 foundation={'r26_choice_kind':'CHOICE' in GATE_KINDS,'r26_outcomes_exact':{'CHOICE_SELECTED','REJECTED'}.issubset(OUTCOMES),'r26_routes_exact':{'RESUME_EXECUTION','PLAN_REVISION','BLOCK'}.issubset(ROUTES),'r43_service_real':callable(R43ApplicationService.open_confirmed_defect_lifecycle),'diagnosis_fixture':AgentRoleRegistry.default().resolve('DIAGNOSIS').agent_name=='aitest-diagnosis'}
 supplemental={'no_custom_r26_g5_enum':all(x not in GATE_KINDS|OUTCOMES for x in {'CONFIRM_DEFECT','REQUEST_MORE_EVIDENCE','REJECT_DEFECT'})}
 names=['no_gate_blocks_confirmation','pending_gate_blocks_confirmation','choice_gate_exact_frozen_shape','confirm_without_continuation_blocks','applied_continuation_is_allowing','stale_binding_rejected_after_continuation','successor_binding_confirms','rejected_block_blocks','plan_revision_more_evidence_blocks','human_cannot_bypass_r36','ordinary_needs_no_gate','ordinary_autonomous_confirm','r43_real_service_called','r43_exact_handoff_idempotent','same_mission_typed_reuse_one_lifecycle','ambiguous_requires_review','cross_mission_merge_forbidden']
 behavior={n:False for n in names}; command=getattr(product_entry,'g5_command',None); hunter=None
 try: hunter=AgentRoleRegistry.default().resolve('DEFECT_HUNTER')
 except Exception: pass
 if callable(command) and hunter is not None:
  with tempfile.TemporaryDirectory(prefix='g5-human-') as td:
   root=Path(td); old=(os.environ.get('AITEST_WORKSPACE_ROOT'),os.environ.get('AITEST_RUNTIME_SPINE_DB')); os.environ['AITEST_WORKSPACE_ROOT']=str(root); os.environ['AITEST_RUNTIME_SPINE_DB']=str(root/'runtime-spine.db')
   try:
    rt,orch,mid,b,first=mk(root,'main'); s=seed(rt,mid,'main'); before=count(rt,mid); v,e=invoke(lambda:command('DEFECT_HUNTER','assess_defect_truth',ap(b,s,HIGH))); behavior['no_gate_blocks_confirmation']=safe_non_confirmed(v,e) and count(rt,mid)==before
    gid='g5-human-main'; command('DIRECTOR','request_human_review',{**b,'candidate_id':s['candidate_id'],'gate_id':gid,'policy_context':HIGH}); r26=HumanGateApplicationService(rt); g=r26.state(mid).gate(gid) or next((x for x in r26.state(mid).gates if x.task_id==b['task_id']),None)
    if g:
     behavior['choice_gate_exact_frozen_shape']=g.gate_kind=='CHOICE' and set(g.allowed_outcomes)=={'CHOICE_SELECTED','REJECTED'} and set(g.allowed_routes_by_outcome)>=set(OUTCOMES)
     v,e=invoke(lambda:command('DEFECT_HUNTER','assess_defect_truth',ap(b,s,HIGH))); behavior['pending_gate_blocks_confirmation']=safe_non_confirmed(v,e) and count(rt,mid)==before
     r26.record_decision({'mission_id':mid,'gate_id':g.gate_id,'decision_id':'confirm','outcome':'CHOICE_SELECTED','route':'RESUME_EXECUTION','decision_payload':{'choice':'CONFIRM_DEFECT'},'actor':{'type':'USER','id':'reviewer'}}); v,e=invoke(lambda:command('DEFECT_HUNTER','assess_defect_truth',ap(b,s,HIGH))); behavior['confirm_without_continuation_blocks']=safe_non_confirmed(v,e) and count(rt,mid)==before
     old_attempt=b['attempt_id']; orch.rotate_session(mid,task_id=b['task_id'],reasons=['CONTROL_OVERRIDE']); latest=rt.replay_composed(mid).extension_state('r1_3b_execution_resume').latest_attempt(b['task_id']); nb={**b,'attempt_id':latest.attempt_id,'session_id':latest.runtime_session_id}; r26.record_continuation({'mission_id':mid,'gate_id':g.gate_id,'route':'RESUME_EXECUTION','canonical_reference':{'successor_attempt_id':latest.attempt_id,'successor_session_id':latest.runtime_session_id,'predecessor_attempt_id':old_attempt,'successor_root_attempt_id':latest.root_attempt_id},'continuation_operation_id':'apply','actor':{'type':'SYSTEM','id':'ec0'}}); behavior['applied_continuation_is_allowing']=r26.state(mid).gate(g.gate_id).is_allowing is True
     v,e=invoke(lambda:command('DEFECT_HUNTER','assess_defect_truth',ap(b,s,HIGH))); behavior['stale_binding_rejected_after_continuation']=explicit_code(e or v) in {'G5_ATTEMPT_NOT_CURRENT','G5_SESSION_NOT_OPEN'}
     command('DEFECT_HUNTER','assess_defect_truth',ap(nb,s,HIGH)); behavior['successor_binding_confirms']=count(rt,mid)==before+1
   finally:
    if old[0] is None: os.environ.pop('AITEST_WORKSPACE_ROOT',None)
    else: os.environ['AITEST_WORKSPACE_ROOT']=old[0]
    if old[1] is None: os.environ.pop('AITEST_RUNTIME_SPINE_DB',None)
    else: os.environ['AITEST_RUNTIME_SPINE_DB']=old[1]
  for mode in ('reject','more'):
   with tempfile.TemporaryDirectory(prefix='g5-human-'+mode+'-') as td:
    root=Path(td); old=(os.environ.get('AITEST_WORKSPACE_ROOT'),os.environ.get('AITEST_RUNTIME_SPINE_DB')); os.environ['AITEST_WORKSPACE_ROOT']=str(root); os.environ['AITEST_RUNTIME_SPINE_DB']=str(root/'runtime-spine.db')
    try:
     rt,orch,mid,b,_=mk(root,mode); s=seed(rt,mid,mode); gid='g-'+mode; command('DIRECTOR','request_human_review',{**b,'candidate_id':s['candidate_id'],'gate_id':gid,'policy_context':HIGH}); r=HumanGateApplicationService(rt); g=r.state(mid).gate(gid) or next(x for x in r.state(mid).gates if x.task_id==b['task_id'])
     if mode=='reject': r.record_decision({'mission_id':mid,'gate_id':g.gate_id,'decision_id':'d','outcome':'REJECTED','route':'BLOCK','decision_payload':{'choice':'REJECT_DEFECT'},'actor':{'type':'USER','id':'u'}})
     else: r.record_decision({'mission_id':mid,'gate_id':g.gate_id,'decision_id':'d','outcome':'CHOICE_SELECTED','route':'PLAN_REVISION','decision_payload':{'choice':'REQUEST_MORE_EVIDENCE'},'actor':{'type':'USER','id':'u'}})
     v,e=invoke(lambda:command('DEFECT_HUNTER','assess_defect_truth',ap(b,s,HIGH))); behavior['rejected_block_blocks' if mode=='reject' else 'plan_revision_more_evidence_blocks']=safe_non_confirmed(v,e) and count(rt,mid)==0
    finally:
     if old[0] is None: os.environ.pop('AITEST_WORKSPACE_ROOT',None)
     else: os.environ['AITEST_WORKSPACE_ROOT']=old[0]
     if old[1] is None: os.environ.pop('AITEST_RUNTIME_SPINE_DB',None)
     else: os.environ['AITEST_RUNTIME_SPINE_DB']=old[1]
  with tempfile.TemporaryDirectory(prefix='g5-human-insufficient-') as td:
   root=Path(td); old=(os.environ.get('AITEST_WORKSPACE_ROOT'),os.environ.get('AITEST_RUNTIME_SPINE_DB')); os.environ['AITEST_WORKSPACE_ROOT']=str(root); os.environ['AITEST_RUNTIME_SPINE_DB']=str(root/'runtime-spine.db')
   try:
    rt,orch,mid,b,_=mk(root,'ins'); s=seed(rt,mid,'ins',False); gid='g-ins'; command('DIRECTOR','request_human_review',{**b,'candidate_id':s['candidate_id'],'gate_id':gid,'policy_context':HIGH}); r=HumanGateApplicationService(rt); g=r.state(mid).gate(gid) or next(x for x in r.state(mid).gates if x.task_id==b['task_id']); r.record_decision({'mission_id':mid,'gate_id':g.gate_id,'decision_id':'c','outcome':'CHOICE_SELECTED','route':'RESUME_EXECUTION','decision_payload':{'choice':'CONFIRM_DEFECT'},'actor':{'type':'USER','id':'u'}}); olda=b['attempt_id']; orch.rotate_session(mid,task_id=b['task_id'],reasons=['CONTROL_OVERRIDE']); latest=rt.replay_composed(mid).extension_state('r1_3b_execution_resume').latest_attempt(b['task_id']); nb={**b,'attempt_id':latest.attempt_id,'session_id':latest.runtime_session_id}; r.record_continuation({'mission_id':mid,'gate_id':g.gate_id,'route':'RESUME_EXECUTION','canonical_reference':{'successor_attempt_id':latest.attempt_id,'successor_session_id':latest.runtime_session_id,'predecessor_attempt_id':olda,'successor_root_attempt_id':latest.root_attempt_id},'continuation_operation_id':'a','actor':{'type':'SYSTEM','id':'ec0'}}); v,e=invoke(lambda:command('DEFECT_HUNTER','assess_defect_truth',ap(nb,s,HIGH))); behavior['human_cannot_bypass_r36']=safe_non_confirmed(v,e) and count(rt,mid)==0
   finally:
    if old[0] is None: os.environ.pop('AITEST_WORKSPACE_ROOT',None)
    else: os.environ['AITEST_WORKSPACE_ROOT']=old[0]
    if old[1] is None: os.environ.pop('AITEST_RUNTIME_SPINE_DB',None)
    else: os.environ['AITEST_RUNTIME_SPINE_DB']=old[1]
  with tempfile.TemporaryDirectory(prefix='g5-ordinary-') as td:
   root=Path(td); old=(os.environ.get('AITEST_WORKSPACE_ROOT'),os.environ.get('AITEST_RUNTIME_SPINE_DB')); os.environ['AITEST_WORKSPACE_ROOT']=str(root); os.environ['AITEST_RUNTIME_SPINE_DB']=str(root/'runtime-spine.db')
   try:
    rt,orch,mid,b,_=mk(root,'ordinary'); s=seed(rt,mid,'ordinary'); r=HumanGateApplicationService(rt); n=len(r.state(mid).gates); command('DEFECT_HUNTER','assess_defect_truth',ap(b,s,ORDINARY)); a=R36ApplicationService(rt).state(mid).defect_assessment(s['assessment_id']); behavior['ordinary_needs_no_gate']=len(r.state(mid).gates)==n; behavior['ordinary_autonomous_confirm']=a is not None and a.outcome=='CONFIRMED_DEFECT'
    if a:
     qv,camps=r41(rt,mid,'ordinary'); ar=exact_ref(rt,mid,s['assessment_id']); calls=[]; original=R43ApplicationService.open_confirmed_defect_lifecycle
     def spy(self,*args,**kwargs): calls.append(1); return original(self,*args,**kwargs)
     R43ApplicationService.open_confirmed_defect_lifecycle=spy
     try:
      h={**b,'candidate_id':s['candidate_id'],'defect_assessment_ref':ar,'defect_assessment_digest':a.defect_assessment_digest,'quality_version_ref':qv,'campaign_refs':camps}; command('DEFECT_HUNTER','handoff_confirmed_defect',h); c1=len(R43ApplicationService(rt).state(mid).confirmed_defect_lifecycles); command('DEFECT_HUNTER','handoff_confirmed_defect',h); c2=len(R43ApplicationService(rt).state(mid).confirmed_defect_lifecycles); behavior['r43_real_service_called']=bool(calls) and c1==1; behavior['r43_exact_handoff_idempotent']=c1==c2==1
      life=R43ApplicationService(rt).state(mid).confirmed_defect_lifecycles[0]; lr=tref('R4_3_CONFIRMED_DEFECT_LIFECYCLE',life.lifecycle_id,life.lifecycle_digest,life.created_seq,'r4.3.confirmed_defect_lifecycle_opened.v1'); command('DEFECT_HUNTER','handoff_confirmed_defect',{**h,'duplicate_correlation_decision':'SAME_CONFIRMED_LIFECYCLE','existing_lifecycle_ref':lr}); behavior['same_mission_typed_reuse_one_lifecycle']=len(R43ApplicationService(rt).state(mid).confirmed_defect_lifecycles)==1
      v,e=invoke(lambda:command('DEFECT_HUNTER','handoff_confirmed_defect',{**h,'duplicate_correlation_decision':'AMBIGUOUS_REVIEW_REQUIRED'})); behavior['ambiguous_requires_review']=explicit_code(e or v)=='G5_DUPLICATE_AMBIGUOUS'
      v,e=invoke(lambda:command('DEFECT_HUNTER','handoff_confirmed_defect',{**h,'mission_id':'other','duplicate_correlation_decision':'SAME_CONFIRMED_LIFECYCLE','existing_lifecycle_ref':lr})); behavior['cross_mission_merge_forbidden']=explicit_code(e or v) in {'G5_DUPLICATE_AMBIGUOUS','G5_R4_3_HANDOFF_REJECTED','G5_ROUTE_REQUIRED','G5_ATTEMPT_TASK_MISMATCH'}
     finally: R43ApplicationService.open_confirmed_defect_lifecycle=original
   finally:
    if old[0] is None: os.environ.pop('AITEST_WORKSPACE_ROOT',None)
    else: os.environ['AITEST_WORKSPACE_ROOT']=old[0]
    if old[1] is None: os.environ.pop('AITEST_RUNTIME_SPINE_DB',None)
    else: os.environ['AITEST_RUNTIME_SPINE_DB']=old[1]
 fixture_ok=all(foundation.values()); runtime_green=all(behavior.values()); contract={**behavior,**supplemental}; missing=[k for k,v in contract.items() if not v]; status='PASS' if fixture_ok and runtime_green and not missing else 'FAIL'; red=fixture_ok and status=='FAIL' and bool(missing); out={'suite':'test_g5_human_gate_and_duplicate_correlation','status':status,'fixture_ok':fixture_ok,'truthful_red':red,'red_kind':'MISSING_G5_INTEGRATION' if red else None,'foundation_checks':foundation,'runtime_behavior_checks':behavior,'supplemental_checks':supplemental,'contract_checks':contract,'runtime_green_evidence':runtime_green,'oracle_contract':{'current_red_is_truthful':red,'future_green_requires_real_runtime':True},'missing_contract_checks':missing}; print(json.dumps(out,ensure_ascii=False,indent=2,sort_keys=True)); return 0 if status=='PASS' else 1
if __name__=='__main__': raise SystemExit(main())
