from __future__ import annotations
import hashlib, json, os, subprocess, sys, tempfile
from pathlib import Path
from types import SimpleNamespace

WORKSPACE=Path(__file__).resolve().parents[2]
RUNTIME=WORKSPACE/'ai-test/runtime'
TESTS=Path(__file__).parent
sys.path.insert(0,str(RUNTIME)); sys.path.insert(0,str(TESTS))

from aitest_runtime.canonical_runtime import bootstrap_mission, create_canonical_runtime
from aitest_runtime.durable_core import RuntimeError, canonical_sha256
from aitest_runtime.g3.code_intelligence import analyze_repository
from aitest_runtime.g3.coverage import CoverageProviderResult, MappingCoveragePlatformProvider
from aitest_runtime.g3.service import G3TestingIntelligenceService
from aitest_runtime.g3.contracts import EXTENSION_ID as G3_EXT
from aitest_runtime.g4.contracts import EXTENSION_ID as G4_EXT, REDACTED_SENSITIVE_VALUE
from aitest_runtime.g4.service import G4RealExecutionService
from aitest_runtime.r3_e2.contracts import BrowserContextRef
from test_g2_waiting_human_nonblocking_scheduler_repair import setup, task, open_gate
from test_g4_full_same_mission_product_e2e import snap, semantics

EXPECTED_LEGACY='2e3183adfda3372350cd027d4a42e6394c9c538e7082f8e6e08527f4c67332a6'
LEGACY=WORKSPACE/'ai-test/state/aitest.db'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
def errcode(fn):
    try: fn(); return None
    except Exception as exc: return str(getattr(exc,'code',type(exc).__name__)) + ':' + str(exc)

def bind(dispatch):
    return {
        'mission_id': dispatch['attempt']['mission_id'], 'task_id': dispatch['task_id'],
        'attempt_id': dispatch['attempt']['attempt_id'], 'root_attempt_id': dispatch['attempt']['root_attempt_id'],
        'session_id': dispatch['external_session']['session_id'],
    }

class BrowserProbe:
    def __init__(self, ref: BrowserContextRef, *, resume_safe=False, fail_ai_to_human_once=False):
        self.identity=ref; self.owner='AI'; self.resume_safe=resume_safe; self.fail_once=fail_ai_to_human_once; self.transfers=[]
    def _ref(self): return BrowserContextRef(self.identity.browser_session_id,self.identity.browser_context_id_or_epoch,self.identity.context_binding_digest,self.owner,self.identity.observed_at)
    def inspect_context(self, ref):
        if (ref.browser_session_id,ref.browser_context_id_or_epoch,ref.context_binding_digest)!=(self.identity.browser_session_id,self.identity.browser_context_id_or_epoch,self.identity.context_binding_digest):
            raise AssertionError('CONTEXT_REPLACED')
        return self._ref()
    def inspect_lease(self, ref): self.inspect_context(ref); return self.owner
    def transfer_lease(self, ref, *, from_owner, to_owner):
        self.inspect_context(ref)
        if self.owner != from_owner: raise AssertionError('OWNER:'+self.owner)
        if from_owner=='AI' and to_owner=='HUMAN' and self.fail_once:
            self.fail_once=False; raise RuntimeError('INJECTED_TRANSFER_FAILURE','construction adversarial')
        self.owner=to_owner; self.transfers.append((from_owner,to_owner))
        return SimpleNamespace(to_dict=lambda:{'from':from_owner,'to':to_owner,'same_context':True})
    def verify_resume_condition(self, *, mission_id, browser_context_ref, resume_condition, completion_mode):
        self.inspect_context(browser_context_ref)
        return {
            'resume_safe': self.resume_safe,
            'auth_state':'AUTHENTICATED' if self.resume_safe else 'UNAUTHENTICATED',
            'page_identity':'MATCHED' if self.resume_safe else 'LOGIN_PAGE',
            'business_state':'RESUME_SAFE' if self.resume_safe else 'BLOCKED',
            'source_ref':'adversarial:browser-probe',
            'evidence_digest':canonical_sha256({'mission':mission_id,'safe':self.resume_safe,'mode':completion_mode}),
            'observed_at':'2026-09-02T12:00:00Z',
        }

def boot_mission(root, db, *, mission_id, goal_id, goal):
    oldroot, olddb=os.environ.get('AITEST_WORKSPACE_ROOT'), os.environ.get('AITEST_RUNTIME_SPINE_DB')
    os.environ['AITEST_WORKSPACE_ROOT']=str(root); os.environ['AITEST_RUNTIME_SPINE_DB']=str(db)
    try: bootstrap_mission(root,mission_id=mission_id,goal_id=goal_id,goal=goal)
    finally:
        if oldroot is None: os.environ.pop('AITEST_WORKSPACE_ROOT',None)
        else: os.environ['AITEST_WORKSPACE_ROOT']=oldroot
        if olddb is None: os.environ.pop('AITEST_RUNTIME_SPINE_DB',None)
        else: os.environ['AITEST_RUNTIME_SPINE_DB']=olddb

def govern_focused_case(g4, rt, mid, binding_data, case_id, *, goal_id, case_version="1", target_application="cfg-data"):
    """Legacy adversarial setup adapter for the frozen R2-2 governed execution contract."""
    g3=G3TestingIntelligenceService(rt)
    strategy_id=f"strategy:{case_id}"
    portfolio=g3._record(
        mid, "TEST_STRATEGY_PORTFOLIO",
        {"r3_3_strategy":{"strategy_version_id":strategy_id,"strategy_fingerprint":canonical_sha256({"strategy":strategy_id})}},
        fact_id=f"g3:adv-strategy:{case_id}",
    )
    case=g3._record(
        mid, "CASE_SPECIFICATION",
        {"r3_3_case":{"tc_id":case_id,"case_version_id":case_version,"strategy_version_id":strategy_id}},
        provenance_refs=(portfolio["fact_id"],), fact_id=f"g3:adv-case:{case_id}:{case_version}",
    )
    g3._record(
        mid, "CASE_VALUE_LINK", {"case_version_id":case_version,"value":"ADVERSARIAL_SETUP"},
        provenance_refs=(case["fact_id"],portfolio["fact_id"]), fact_id=f"g3:adv-link:{case_id}:{case_version}",
    )
    focused=g4.create_focused_execution_binding(mid,{**binding_data,"goal_id":goal_id,"target_application":target_application,"case_id":case_id,"case_version":case_version,"case_spec_fact_id":case["fact_id"],"binding_id":f"adv-focus:{case_id}:{binding_data['root_attempt_id']}"})
    return {"case_spec_fact_id":case["fact_id"],"focused_execution_binding_id":focused["binding"]["payload"]["binding_id"]}

def bootstrap_goal(tag='goal', *, target=95.0):
    root=Path(tempfile.mkdtemp(prefix='g4-adv-goal-')); db=root/'runtime-spine.db'; mid='m-'+tag
    boot_mission(root,db,mission_id=mid,goal_id='core-'+tag,goal={'objective':'adversarial '+tag,'scope_digest':tag})
    rt=create_canonical_runtime(root,db_path=db); g4=G4RealExecutionService(rt)
    g4.create_goal(mid,{'goal_id':tag,'project_id':'PFC','release_id':'V2','requirement_scope':['REQ'],'affected_applications':['cfg-data'],'affected_application_target_versions':{'cfg-data':'V2'},'coverage_policy':{'target_pct':target}})
    return root,db,mid,rt,g4

def bank_available(rt, mid, g4, goal_id, pct, seq, measurement_id):
    provider=MappingCoveragePlatformProvider(CoverageProviderResult('AVAILABLE',('AGGREGATE',),snapshot=snap('cfg-data',pct,seq,'head-adv')))
    cv=G3TestingIntelligenceService(rt,coverage_provider=provider).acquire_coverage(mid,{'platform_profile_id':'bankcov','authenticated_context_ref':'auth','method':'API'},{'application_id':'cfg-data','target_version':'V2','baseline_label':'master'})
    return g4.record_coverage_from_g3(mid,{'measurement_id':measurement_id,'goal_id':goal_id,'state':'AVAILABLE','g3_snapshot_fact_id':cv['snapshot']['fact_id']})

def make_body_repo(root: Path, name: str, path: str, before: str, after: str):
    repo=root/name; repo.mkdir();
    subprocess.run(['git','init','-q',str(repo)],check=True); subprocess.run(['git','-C',str(repo),'config','user.email','test@example.invalid'],check=True); subprocess.run(['git','-C',str(repo),'config','user.name','Test'],check=True)
    p=repo/path; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(before,encoding='utf-8')
    subprocess.run(['git','-C',str(repo),'add','.'],check=True); subprocess.run(['git','-C',str(repo),'commit','-qm','base'],check=True); base=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
    p.write_text(after,encoding='utf-8'); subprocess.run(['git','-C',str(repo),'add','.'],check=True); subprocess.run(['git','-C',str(repo),'commit','-qm','head'],check=True); head=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
    return repo,base,head

def main():
    checks={}; details={}; before_legacy=sha(LEGACY)

    # R-1: lexical IDs must not reorder temporal fact truth.
    with tempfile.TemporaryDirectory(prefix='projection-adv-') as td:
        root=Path(td); db=root/'runtime-spine.db'; mid='projection-mission'
        boot_mission(root,db,mission_id=mid,goal_id='projection-core',goal={'objective':'projection order','scope_digest':'projection'})
        rt=create_canonical_runtime(root,db_path=db); g3=G3TestingIntelligenceService(rt); g4=G4RealExecutionService(rt)
        g3._record(mid,'KNOWLEDGE_GAP',{'ordinal':1},fact_id='z-first-g3'); g3._record(mid,'KNOWLEDGE_GAP',{'ordinal':2},fact_id='a-second-g3')
        g4._record(mid,'CAPABILITY_STATUS',{'capability_id':'API','status':'PARTIAL','ordinal':1},fact_id='z-first-g4'); g4._record(mid,'CAPABILITY_STATUS',{'capability_id':'API','status':'AVAILABLE','ordinal':2},fact_id='a-second-g4')
        gp=rt.get_extension_projection(G3_EXT,mid); fp=rt.get_extension_projection(G4_EXT,mid)
        checks['projection_created_seq_g3']=gp.latest('KNOWLEDGE_GAP').fact_id=='a-second-g3' and [f.fact_id for f in gp.by_kind('KNOWLEDGE_GAP')]==['z-first-g3','a-second-g3']
        checks['projection_created_seq_g4']=fp.latest('CAPABILITY_STATUS').fact_id=='a-second-g4' and [f.fact_id for f in fp.by_kind('CAPABILITY_STATUS')]==['z-first-g4','a-second-g4']
        verify=rt.verify_projection(mid); checks['runtime_verify_projection_counterexample']=verify.get('ok') is True; details['projection_verify']=verify

    # R-4: real Git, method-body-only edits must not silently claim COMPLETE symbol truth.
    with tempfile.TemporaryDirectory(prefix='multilang-adv-') as td:
        r=Path(td)
        cases=[
            ('java','src/A.java','class A {\n  int calc(int x) {\n    return x + 1;\n  }\n}\n','class A {\n  int calc(int x) {\n    return x + 2;\n  }\n}\n','JAVA'),
            ('ts','src/a.ts','export class A {\n  calc(x: number) {\n    return x + 1;\n  }\n}\n','export class A {\n  calc(x: number) {\n    return x + 2;\n  }\n}\n','TYPESCRIPT'),
            ('vue','src/A.vue','<script setup lang="ts">\nfunction calc(x:number) {\n  return x + 1\n}\n</script>\n','<script setup lang="ts">\nfunction calc(x:number) {\n  return x + 2\n}\n</script>\n','VUE'),
        ]
        repo_specs=[]
        for name,path,before,after,lang in cases:
            repo,base,head=make_body_repo(r,name,path,before,after)
            spec={'repository_path':str(repo),'repository_id':name,'application_id':name,'base_ref':base,'head_ref':head}; repo_specs.append(spec)
            _,env,meta=analyze_repository(spec)
            warning_prefix='MISSING_SYMBOL_MAPPING:'+path+':'
            checks['multilang_body_'+name]=env.code_intelligence_status=='PARTIAL' and meta['provider_capabilities'].get(lang)=='PARTIAL' and any(str(w).startswith(warning_prefix) for w in env.warnings) and not env.changed_symbols
            details['multilang_'+name]={'status':env.code_intelligence_status,'caps':meta['provider_capabilities'],'warnings':list(env.warnings),'symbols':[x.to_dict() for x in env.changed_symbols]}
        # G3 product semantics must carry the unresolved symbol truth into a durable coverage/risk obligation.
        db=r/'runtime-spine.db'; mid='multilang-mission'; boot_mission(r,db,mission_id=mid,goal_id='multi-core',goal={'objective':'multilang obligations','scope_digest':'multi'})
        rt=create_canonical_runtime(r,db_path=db); g3svc=G3TestingIntelligenceService(rt)
        req=g3svc.analyze_requirement(mid,'REQ-MULTI',semantics())
        change=g3svc.analyze_changes(mid,'REQ-MULTI',repo_specs,req['r3_1_reference'])
        obligations=change['coverage_objective']['payload'].get('risk_obligations') or []
        checks['multilang_missing_symbol_remains_coverage_risk_obligation']=change['status']=='PARTIAL' and {x.get('file_path') for x in obligations}=={'src/A.java','src/a.ts','src/A.vue'} and all(x.get('status')=='OPEN' and x.get('changed_line_refs') for x in obligations)

    # R-3: missing/stale measurements cannot terminal-complete; acceptance is version-bound.
    root,db,mid,rt,g4=bootstrap_goal('risk')
    no_measure=g4.evaluate_goal(mid,'risk'); checks['accepted_gap_missing_measurement_waits']=no_measure['status']=='WAITING_MEASUREMENT'
    stale=g4.record_coverage_from_g3(mid,{'measurement_id':'risk-stale','goal_id':'risk','state':'STALE','application_id':'cfg-data','source_identity':'bank:stale','reason':'refresh'}); stale_eval=g4.evaluate_goal(mid,'risk')
    checks['accepted_gap_stale_measurement_waits']=stale_eval['status']=='WAITING_MEASUREMENT' and stale['measurement']['payload']['observed_at']!='1970-01-01T00:00:00Z'
    m1=bank_available(rt,mid,g4,'risk',93.8,31,'risk-m1'); gap=g4.record_blocker_gap(mid,{'gap_id':'risk-gap','goal_id':'risk','gap_kind':'POSSIBLY_UNREACHABLE','severity':'MEDIUM','status':'OPEN','application_id':'cfg-data','reason':'external branch'})
    risk=g4.record_risk_acceptance(mid,{'acceptance_id':'risk-a1','goal_id':'risk','measurement_refs':[m1['measurement']['fact_id']],'residual_gap_refs':[gap['gap']['fact_id']],'actual_pct':93.8,'risk':'external branch','human_authorized':True,'accepted_by':'reviewer','accepted_at':'2026-09-02T12:01:00Z'})
    accepted=g4.evaluate_goal(mid,'risk'); checks['accepted_gap_current_binding_completes']=accepted['status']=='COMPLETED_WITH_ACCEPTED_GAP' and accepted['evaluation']['payload']['risk_acceptance_ref']==risk['risk_acceptance']['fact_id']

    # New R2-5 correctly locks a terminal goal. Test stale acceptance on a separate non-terminal goal.
    root2,db2,mid2,rt_risk2,g4_risk2=bootstrap_goal('risk-revision')
    m1b=bank_available(rt_risk2,mid2,g4_risk2,'risk-revision',93.8,41,'risk-r1')
    gapb=g4_risk2.record_blocker_gap(mid2,{'gap_id':'risk-gap-r1','goal_id':'risk-revision','gap_kind':'POSSIBLY_UNREACHABLE','severity':'MEDIUM','status':'OPEN','application_id':'cfg-data','reason':'external branch'})
    riskb=g4_risk2.record_risk_acceptance(mid2,{'acceptance_id':'risk-a-r1','goal_id':'risk-revision','measurement_refs':[m1b['measurement']['fact_id']],'residual_gap_refs':[gapb['gap']['fact_id']],'actual_pct':93.8,'risk':'external branch','human_authorized':True,'accepted_by':'reviewer','accepted_at':'2026-09-02T12:01:00Z'})
    m2=bank_available(rt_risk2,mid2,g4_risk2,'risk-revision',94.0,42,'risk-r2'); stale_accept=g4_risk2.evaluate_goal(mid2,'risk-revision')
    checks['old_risk_acceptance_invalid_after_new_measurement']=stale_accept['status']=='REPLAN_REQUIRED' and stale_accept['evaluation']['payload']['risk_acceptance_ref'] is None and stale_accept['evaluation']['payload']['stale_risk_acceptance_ref']==riskb['risk_acceptance']['fact_id']

    root3,db3,mid3,rt_mismatch,g4_mismatch=bootstrap_goal('risk-mismatch-goal')
    mismatch=g4_mismatch.record_coverage_from_g3(mid3,{'measurement_id':'risk-mismatch','goal_id':'risk-mismatch-goal','state':'SOURCE_IDENTITY_MISMATCH','application_id':'cfg-data','source_identity':'bank:mismatch','reason':'baseline changed'}); mismatch_eval=g4_mismatch.evaluate_goal(mid3,'risk-mismatch-goal')
    checks['source_identity_mismatch_waits']=mismatch_eval['status']=='WAITING_MEASUREMENT' and mismatch['measurement']['payload']['observed_at']!='1970-01-01T00:00:00Z'

    # R-2/R-5B/D: canonical attempt + same browser; caller assertions cannot override runtime verifier.
    root,rt,p,orch,mid,dispatch=setup('human-adv',[task('A'),task('B')]); b=bind(dispatch)
    g4=G4RealExecutionService(rt,orchestration=orch)
    g4.create_goal(mid,{'goal_id':'human-goal','project_id':'PFC','release_id':'V2','requirement_scope':['REQ'],'affected_applications':['cfg-data'],'affected_application_target_versions':{'cfg-data':'V2'},'coverage_policy':{'target_pct':95}})
    human_case=govern_focused_case(g4,rt,mid,b,'TC-H',goal_id='human-goal')
    g4.record_cursor(mid,{**b,**human_case,'case_id':'TC-H','case_version':'1','current_step_index':0,'completed_step_ids':[],'pending_step_id':'login','last_safe_checkpoint':'before'})
    ref=BrowserContextRef('browser-h','ctx-h',canonical_sha256({'ctx':'h'}),'AI','2026-09-02T12:02:00Z'); browser=BrowserProbe(ref,resume_safe=False)
    g4=G4RealExecutionService(rt,orchestration=orch,browser_provider=browser)
    takeover=g4.request_human_takeover(mid,{**b,'human_gate_id':'gate-h','takeover_id':'tk-h','case_id':'TC-H','browser_context_ref':ref.to_dict(),'required_action':'login','reason':'AUTH','allowed_scope':{'environment':'TEST'},'resume_mode':'AUTO_OR_EXPLICIT','resume_condition':{'auth':'required'},'goal_id':'human-goal','mandatory_for_goal':True})
    neg_auto=errcode(lambda:g4.complete_human_takeover(mid,{'human_gate_id':'gate-h','completion_mode':'AUTO','resume_condition_verified':True,'verification':{'auth_state':'VERIFIED','page_identity':'VERIFIED','business_state':'RESUME_SAFE'}}))
    checks['auto_resume_rejects_caller_assertion_when_not_logged_in']=neg_auto is not None and 'G4_HUMAN_RESUME_REVALIDATION_FAILED' in neg_auto and browser.owner=='HUMAN'
    neg_exp=errcode(lambda:g4.complete_human_takeover(mid,{'human_gate_id':'gate-h','completion_mode':'EXPLICIT','verification':{'auth_state':'VERIFIED','page_identity':'VERIFIED','business_state':'RESUME_SAFE'},'actor_id':'human'}))
    checks['explicit_resume_also_requires_runtime_verification']=neg_exp is not None and 'G4_HUMAN_RESUME_REVALIDATION_FAILED' in neg_exp and browser.owner=='HUMAN'
    # New Runtime/service instance proves resume isn't coupled to original Conversation/Session object.
    browser.resume_safe=True; rt2=create_canonical_runtime(root,db_path=root/'runtime-spine.db'); g4new=G4RealExecutionService(rt2,browser_provider=browser)
    positive=g4new.complete_human_takeover(mid,{'human_gate_id':'gate-h','completion_mode':'EXPLICIT','actor_id':'human'})
    checks['runtime_verified_resume_new_process_same_context_root_cursor']=positive['status']=='RESUME_SAFE' and browser.owner=='AI' and positive['root_attempt_id']==b['root_attempt_id'] and positive['cursor']['payload']['pending_step_id']=='login'
    statuses=[f.payload.get('status') for f in g4new.state(mid).by_kind('TESTING_GOAL_STATUS') if f.payload.get('goal_id')=='human-goal']
    checks['goal_lifecycle_human_wait_and_resume_durable']='WAITING_HUMAN' in statuses and 'EXECUTING' in statuses

    # Unrelated pending R2.6 gate is not a current TestingGoal blocker.
    bank_available(rt2,mid,g4new,'human-goal',96.0,33,'human-m')
    # The unrelated gate is canonical and exact-bound to a real Attempt, but lacks any G4 mandatory goal binding.
    open_gate(rt2,mid,dispatch,'unrelated-gate')
    unrelated_eval=g4new.evaluate_goal(mid,'human-goal')
    checks['unrelated_human_gate_does_not_block_goal']=unrelated_eval['status']=='SATISFIED' and unrelated_eval['evaluation']['payload']['mandatory_human_gate_refs']==[]

    # R-5D: transfer failure leaves a durable recoverable state, then reconcile succeeds.
    root,rt,p,orch,mid,dispatch=setup('lease-adv',[task('A')]); b=bind(dispatch); ref=BrowserContextRef('browser-f','ctx-f',canonical_sha256({'ctx':'f'}),'AI','2026-09-02T12:03:00Z'); browser=BrowserProbe(ref,resume_safe=True,fail_ai_to_human_once=True)
    g4=G4RealExecutionService(rt,orchestration=orch,browser_provider=browser); g4.create_goal(mid,{'goal_id':'lease-goal','project_id':'PFC','release_id':'V2','requirement_scope':['REQ'],'affected_applications':['cfg-data'],'affected_application_target_versions':{'cfg-data':'V2'},'coverage_policy':{'target_pct':95}}); lease_case=govern_focused_case(g4,rt,mid,b,'TC-F',goal_id='lease-goal'); g4.record_cursor(mid,{**b,**lease_case,'case_id':'TC-F','case_version':'1','current_step_index':0,'completed_step_ids':[],'pending_step_id':'login','last_safe_checkpoint':'before'})
    blocked=g4.request_human_takeover(mid,{**b,'human_gate_id':'gate-f','takeover_id':'tk-f','case_id':'TC-F','browser_context_ref':ref.to_dict(),'required_action':'login','reason':'AUTH','allowed_scope':{'environment':'TEST'},'resume_mode':'AUTO_OR_EXPLICIT','resume_condition':{'auth':'required'}})
    recon=g4.reconcile_human_takeover(mid,{'human_gate_id':'gate-f'})
    checks['lease_transfer_failure_reconciles_without_split_truth']=blocked['status']=='BLOCKED' and blocked['reconciliation']['payload']['recoverable'] is True and recon['status']=='WAITING_HUMAN' and browser.owner=='HUMAN'

    # R-5C: value-based secret redaction catches generic nested actual/metadata/body fields.
    secret_fact=g4._record(mid,'EVIDENCE_BUNDLE',{'bundle_id':'secret-test','actual':{'value':'otp=482911','nested':{'v':'Bearer abcdef123456'}},'metadata':{'generic':'password=hunter2'},'body':{'field':'eyJabc.def.ghi'}})
    serialized=json.dumps(secret_fact['payload'],sort_keys=True)
    checks['generic_field_secret_values_redacted']=all(raw not in serialized for raw in ('482911','hunter2','abcdef123456','eyJabc.def.ghi')) and serialized.count(REDACTED_SENSITIVE_VALUE)>=4

    # R-5A/E: lifecycle is durable and timestamp truth never fabricates 1970.
    root,db,mid,rt,g4=bootstrap_goal('lifecycle')
    initial=g4.goal_status(mid,'lifecycle'); wait=g4.evaluate_goal(mid,'lifecycle'); m=bank_available(rt,mid,g4,'lifecycle',96.0,34,'life-m'); done=g4.evaluate_goal(mid,'lifecycle')
    lifecycle=[f.payload.get('status') for f in g4.state(mid).by_kind('TESTING_GOAL_STATUS') if f.payload.get('goal_id')=='lifecycle']
    checks['goal_lifecycle_terminal_status_durable']=initial=='ACTIVE' and wait['status']=='WAITING_MEASUREMENT' and done['status']=='SATISFIED' and lifecycle[-1]=='SATISFIED' and 'WAITING_COVERAGE_REFRESH' in lifecycle and 'MEASURING' in lifecycle
    checks['timestamp_truth_no_epoch_fallback']=all('1970-01-01T00:00:00Z' not in json.dumps(f.payload,sort_keys=True) for f in g4.state(mid).facts)

    after_legacy=sha(LEGACY); checks['legacy_aitest_db_unchanged']=((before_legacy is None and after_legacy is None) or before_legacy==EXPECTED_LEGACY==after_legacy)
    out={'status':'PASS' if all(checks.values()) else 'FAIL','passed':sum(bool(v) for v in checks.values()),'total':len(checks),'checks':checks,'details':details}
    print(json.dumps(out,ensure_ascii=False,indent=2,sort_keys=True)); return 0 if out['status']=='PASS' else 1

if __name__=='__main__': raise SystemExit(main())
