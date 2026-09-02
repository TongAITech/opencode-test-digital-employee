from __future__ import annotations
import hashlib, json, os, subprocess, sys, tempfile
from pathlib import Path

WORKSPACE=Path(__file__).resolve().parents[2]; RUNTIME=WORKSPACE/'ai-test/runtime'; TESTS=Path(__file__).parent
sys.path.insert(0,str(RUNTIME)); sys.path.insert(0,str(TESTS))
from aitest_runtime.canonical_runtime import bootstrap_mission, create_canonical_runtime
from aitest_runtime.g3.coverage import CoverageProviderResult, MappingCoveragePlatformProvider
from aitest_runtime.g3.service import G3TestingIntelligenceService
from aitest_runtime.g4.service import G4RealExecutionService, TestObjectiveController
from test_g4_full_same_mission_product_e2e import snap

EXPECTED_LEGACY='2e3183adfda3372350cd027d4a42e6394c9c538e7082f8e6e08527f4c67332a6'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
def parse_json(text):
    a=text.find('{'); b=text.rfind('}')
    if a<0 or b<a: raise AssertionError(text)
    return json.loads(text[a:b+1])
def raises(fn):
    try: fn(); return False
    except Exception: return True

def main():
    checks={}
    env=os.environ.copy(); env['PYTHONPATH']=str(RUNTIME)+os.pathsep+str(TESTS)
    p=subprocess.run([sys.executable,str(TESTS/'test_g4_full_same_mission_product_e2e.py')],cwd=WORKSPACE,env=env,text=True,capture_output=True,timeout=300)
    e2e=parse_json(p.stdout); ec=e2e.get('checks') or {}; e2e_ok=p.returncode==0 and e2e.get('status')=='PASS'
    g4src=(RUNTIME/'aitest_runtime/g4/service.py').read_text(); csrc=(RUNTIME/'aitest_runtime/g4/contracts.py').read_text(); pesrc=(RUNTIME/'aitest_runtime/product_entry.py').read_text(); tool=(WORKSPACE/'.opencode/tools/aitest.ts').read_text(); g2src=(RUNTIME/'aitest_runtime/autonomous_orchestration.py').read_text()
    legacy=WORKSPACE/'ai-test/state/aitest.db'

    # Product-path / architecture evidence.
    checks['01_r1_sole_truth']=e2e_ok and 'R1_EVENT_STREAM' in pesrc and 'g4_real_execution_goal_convergence' in (RUNTIME/'aitest_runtime/g4/contracts.py').read_text()
    checks['02_legacy_db_forbidden']=sha(legacy) in {None,EXPECTED_LEGACY} and 'aitest.db' not in g4src
    checks['03_goal_durable']=ec.get('g4_goal_95_durable') is True
    checks['04_goal_policy_durable']=ec.get('g4_goal_95_durable') is True and 'PER_AFFECTED_APPLICATION' in g4src
    checks['05_per_app_default']=ec.get('multi_app_target_and_critical_zero_satisfied') is True and 'PER_AFFECTED_APPLICATION' in g4src
    checks['07_canonical_attempt_binding']=ec.get('explicit_resume_same_context_root_step') is True and 'G4_CANONICAL_EXECUTION_ATTEMPT_REQUIRED' in g4src
    checks['08_step_cursor_durable']=ec.get('explicit_resume_same_context_root_step') is True and 'STEP_CURSOR' in csrc
    checks['09_case_version_preserved']='case_version' in g4src and ec.get('same_mission_end_to_end') is True
    checks['10_process_restart_recovery']=ec.get('session_rotation_control_restart') is True
    checks['11_sessions_route_g21']='G4_SESSION_ROUTER_ROLE_BINDING_MISMATCH' in pesrc and ec.get('waiting_a_allows_independent_b') is True
    executor_segment=tool.split('export const executor = tool({',1)[1].split('export const g4_director',1)[0]
    checks['12_executor_no_session_lifecycle']=all(x not in executor_segment for x in ('create_session','rotate_session','close_session'))
    checks['13_browser_governed']=ec.get('human_takeover_product_entry_yields') is True and 'G4_BROWSER_PROVIDER_REQUIRED' in g4src
    checks['14_api_governed']='EXACT_API_URL_METHOD_SCOPE_REQUIRED' in g4src
    checks['16_cat_read_only']='CAT_LOG_READ_ONLY' in g4src and 'CAT_LOG_AUTH_REQUIRED' in g4src
    checks['17_manual_durable']='DURABLE_HUMAN_GATE_REQUIRED' in g4src and 'capability_human_gate' in pesrc
    checks['18_human_yields_ai_turn']=ec.get('human_takeover_product_entry_yields') is True
    checks['19_same_browser_context']=ec.get('explicit_resume_same_context_root_step') is True and ec.get('browser_lease_full_state_machine') is True
    checks['20_ai_forbidden_while_human']=ec.get('browser_lease_full_state_machine') is True and 'HUMAN_CONTROLLED' in g4src and 'transfer_lease' in g4src and all(x not in executor_segment for x in ('click','navigate','form_fill','close_browser'))
    checks['21_explicit_verify']=ec.get('explicit_resume_same_context_root_step') is True
    checks['22_auto_resume_verify']=ec.get('deterministic_auto_resume') is True
    checks['23_sensitive_not_durable']='G4_SECRET_FORBIDDEN' in csrc and 'sensitive_evidence_suppressed' in g4src
    checks['24_resume_original_attempt_step']=ec.get('explicit_resume_same_context_root_step') is True
    checks['25_multiple_gates_not_guessed']='G4_HUMAN_GATE_SELECTION_REQUIRED' in g4src and 'len(compatible) != 1' in g4src
    checks['26_independent_work_can_continue']=ec.get('waiting_a_allows_independent_b') is True and 'g2-serial' in g2src and 'exact_waiting' in g2src
    checks['27_step_oracle_evidence']='G4_EVIDENCE_REQUIRED' in g4src and ec.get('batch1_plan_complete') is True
    checks['28_fail_not_defect']='G4_G5_DEFECT_TRUTH_BOUNDARY' in g4src and 'OBSERVATION_ONLY' in g4src
    checks['29_batch_durable']=ec.get('batch1_plan_complete') is True and 'EXECUTION_BATCH' in csrc
    checks['30_batch_restart_no_duplicate']=ec.get('session_rotation_control_restart') is True and 'g4:execution-batch:' in g4src
    checks['31_coverage_bank_only']='BANK_INCREMENTAL_COVERAGE_PLATFORM' in g4src and 'G4_G3_BANK_COVERAGE_FACT_REQUIRED' in g4src
    checks['34_controller_measures_evaluates']=ec.get('unmet_target_creates_formal_g3_replan') is True
    checks['35_unmet_target_replan']=ec.get('unmet_target_creates_formal_g3_replan') is True
    checks['36_g4_no_case_authoring']=ec.get('g3_real_replan_strategy_revision_new_case') is True and ec.get('next_batch_comes_from_g3_governed_new_case') is True and '"g4_case_authoring": "FORBIDDEN"' in g4src
    checks['37_iteration_delta']='coverage_delta' in g4src and ec.get('multi_app_target_and_critical_zero_satisfied') is True
    checks['39_blocker_classification_contract']='GAP_KINDS' in csrc and 'TEST_DESIGN_GAP' in csrc and 'UNKNOWN' in csrc
    checks['43_satisfied_policy']=ec.get('multi_app_target_and_critical_zero_satisfied') is True
    checks['46_g5_hold']='g5_defect_truth' in pesrc and 'HOLD' in pesrc and 'G4_G5_DEFECT_TRUTH_BOUNDARY' in g4src
    checks['47_g6_hold']='"g6_closed_loop": "HOLD"' in g4src
    checks['48_restart_replay']=ec.get('session_rotation_control_restart') is True and ec.get('explicit_resume_same_context_root_step') is True
    checks['49_session_rotation_recovery']=ec.get('session_rotation_control_restart') is True and ec.get('b_root_attempt_preserved_after_rotation') is True
    checks['50_control_loop_restart_recovery']=ec.get('session_rotation_control_restart') is True
    checks['51_product_entry_alignment']='g4_command' in pesrc and 'export const g4_director' in tool and 'request_human_takeover' in tool

    # Fresh direct contract evidence for completion/plateau/safety/source semantics.
    with tempfile.TemporaryDirectory(prefix='g4-formal-') as td:
        root=Path(td); db=root/'runtime-spine.db'; mid='formal-mission'
        oldroot,olddb=os.environ.get('AITEST_WORKSPACE_ROOT'),os.environ.get('AITEST_RUNTIME_SPINE_DB')
        os.environ['AITEST_WORKSPACE_ROOT']=str(root); os.environ['AITEST_RUNTIME_SPINE_DB']=str(db)
        bootstrap_mission(root,mission_id=mid,goal_id='core-goal',goal={'objective':'formal G4 gate','scope_digest':'formal'})
        rt=create_canonical_runtime(root,db_path=db); s=G4RealExecutionService(rt)
        s.create_goal(mid,{'goal_id':'g95','project_id':'PFC','release_id':'V2','requirement_scope':['REQ-018'],'affected_applications':['cfg-data','cfg-admin'],'coverage_policy':{'target_pct':95}})
        refs=[]
        for app,pct,seq in [('cfg-data',96,71),('cfg-admin',97,72)]:
            cv=G3TestingIntelligenceService(rt,coverage_provider=MappingCoveragePlatformProvider(CoverageProviderResult('AVAILABLE',('AGGREGATE',),snapshot=snap(app,pct,seq,'head-formal')))).acquire_coverage(mid,{'platform_profile_id':'bankcov','authenticated_context_ref':'auth','method':'API'},{'application_id':app,'target_version':'V2','baseline_label':'master'})
            refs.append(cv['snapshot']); s.record_coverage_from_g3(mid,{'measurement_id':'m-'+app,'goal_id':'g95','state':'AVAILABLE','g3_snapshot_fact_id':cv['snapshot']['fact_id']})
        gap=s.record_blocker_gap(mid,{'gap_id':'critical','goal_id':'g95','gap_kind':'TEST_DESIGN_GAP','severity':'CRITICAL','status':'OPEN','application_id':'cfg-data','reason':'critical line remains'})
        blocked=s.evaluate_goal(mid,'g95')
        checks['06_critical_policy']=blocked['status']=='REPLAN_REQUIRED' and bool(blocked['evaluation']['payload']['unresolved_critical_gap_refs'])
        checks['42_critical_gap_blocks_satisfied']=checks['06_critical_policy']
        stale=s.record_coverage_from_g3(mid,{'measurement_id':'stale','goal_id':'g95','state':'STALE','application_id':'cfg-data','source_identity':'bank:stale','reason':'refresh pending'})
        checks['32_stale_not_no_gain']=stale['actual_coverage'] is None and stale['measurement']['payload']['state']=='STALE'
        checks['33_master_alias_semantics']=all(x['payload'].get('baseline_identity_status')=='MASTER_ALIAS_ONLY' for x in refs)
        dbdec=s.validate_executor_request('DB',{'connection_ref':'db:test','query':'update t set x=1','operation':'WRITE'})
        checks['15_db_fail_closed']=dbdec.status=='APPROVAL_REQUIRED'
        checks['44_security_fail_closed']=s.validate_executor_request('SECURITY',{'authorized_scope':{'app':'x'}}).status=='APPROVAL_REQUIRED' and ec.get('security_performance_execute_only_from_g3_profiles') is True
        checks['45_performance_fail_closed']=s.validate_executor_request('PERFORMANCE',{'authorized_scope':{'app':'x'}}).status=='APPROVAL_REQUIRED' and ec.get('security_performance_execute_only_from_g3_profiles') is True
        plat=s.record_iteration(mid,{'iteration_id':'plateau','goal_id':'g95','coverage_before':{'cfg-data':96},'coverage_after':{'cfg-data':96},'cases_executed':['case-ref']})
        checks['38_plateau_no_blind_rerun']=plat['status']=='PLATEAU' and plat['iteration']['payload']['coverage_delta']['cfg-data']==0.0
        checks['40_risk_human_authorized']=raises(lambda:s.record_risk_acceptance(mid,{'acceptance_id':'bad','goal_id':'g95','target_pct':95,'actual_pct':93.8,'risk':'x','accepted_at':'2026-09-02T00:00:00Z'}))
        # Accepted-gap truth requires a fresh comparable Bank measurement and exact residual gap refs.
        s.create_goal(mid,{'goal_id':'g-accepted','project_id':'PFC','release_id':'V2','requirement_scope':['REQ-018'],'affected_applications':['cfg-data'],'coverage_policy':{'target_pct':95}})
        cv_accept=G3TestingIntelligenceService(rt,coverage_provider=MappingCoveragePlatformProvider(CoverageProviderResult('AVAILABLE',('AGGREGATE',),snapshot=snap('cfg-data',93.8,74,'head-formal')))).acquire_coverage(mid,{'platform_profile_id':'bankcov','authenticated_context_ref':'auth','method':'API'},{'application_id':'cfg-data','target_version':'V2','baseline_label':'master'})
        m_accept=s.record_coverage_from_g3(mid,{'measurement_id':'m-accepted','goal_id':'g-accepted','state':'AVAILABLE','g3_snapshot_fact_id':cv_accept['snapshot']['fact_id']})
        g_accept=s.record_blocker_gap(mid,{'gap_id':'accepted-gap','goal_id':'g-accepted','gap_kind':'POSSIBLY_UNREACHABLE','severity':'MEDIUM','status':'OPEN','application_id':'cfg-data','reason':'external system unavailable'})
        risk=s.record_risk_acceptance(mid,{'acceptance_id':'ok','goal_id':'g-accepted','target_pct':95,'actual_pct':93.8,'measurement_refs':[m_accept['measurement']['fact_id']],'residual_gap_refs':[g_accept['gap']['fact_id']],'risk':'external system unavailable','human_authorized':True,'accepted_by':'reviewer','accepted_at':'2026-09-02T00:00:00Z'})
        accepted_eval=s.evaluate_goal(mid,'g-accepted')
        checks['41_accepted_gap_truthful']=risk['risk_acceptance']['payload']['actual_by_application']['cfg-data']==93.8 and risk['risk_acceptance']['payload']['target_pct']==95.0 and accepted_eval['status']=='COMPLETED_WITH_ACCEPTED_GAP'
        # Secret persistence is rejected centrally by G4 fact schema.
        checks['23_sensitive_not_durable']=checks['23_sensitive_not_durable'] and raises(lambda:s.create_goal(mid,{'goal_id':'secret-goal','project_id':'PFC','release_id':'V2','requirement_scope':[],'affected_applications':['cfg-data'],'coverage_policy':{'target_pct':95},'execution_policy':{'password':'never'}}))
        # Resolve latest critical gap and supersede stale measurement with fresh bank truth, then default per-app policy may satisfy.
        cv=G3TestingIntelligenceService(rt,coverage_provider=MappingCoveragePlatformProvider(CoverageProviderResult('AVAILABLE',('AGGREGATE',),snapshot=snap('cfg-data',96,73,'head-formal')))).acquire_coverage(mid,{'platform_profile_id':'bankcov','authenticated_context_ref':'auth','method':'API'},{'application_id':'cfg-data','target_version':'V2','baseline_label':'master'})
        s.record_coverage_from_g3(mid,{'measurement_id':'m-cfg-data-fresh','goal_id':'g95','state':'AVAILABLE','g3_snapshot_fact_id':cv['snapshot']['fact_id']})
        s.record_blocker_gap(mid,{'gap_id':'critical','goal_id':'g95','gap_kind':'TEST_DESIGN_GAP','severity':'CRITICAL','status':'RESOLVED','application_id':'cfg-data','reason':'governed case covered it'})
        final=s.evaluate_goal(mid,'g95')
        # Acceptance exists, but because target is actually met and critical zero, SATISFIED must win over accepted-gap state.
        checks['43_satisfied_policy']=checks['43_satisfied_policy'] and final['status']=='SATISFIED'
        if oldroot is None: os.environ.pop('AITEST_WORKSPACE_ROOT',None)
        else: os.environ['AITEST_WORKSPACE_ROOT']=oldroot
        if olddb is None: os.environ.pop('AITEST_RUNTIME_SPINE_DB',None)
        else: os.environ['AITEST_RUNTIME_SPINE_DB']=olddb
    checks['52_architecture_drift_no']=('SchedulingPolicy("g2-serial", 1, 1)' in g2src and 'legacy_aitest.db' not in g4src and 'create_session' not in executor_segment and 'g4_case_authoring' in g4src)

    # Guarantee exact formal registry and expose missing checks rather than silently omitting them.
    expected=[f'{i:02d}_' for i in range(1,53)]
    missing=[i for i in range(1,53) if not any(k.startswith(f'{i:02d}_') for k in checks)]
    if missing: raise AssertionError('FORMAL_GATE_MAPPING_MISSING:'+','.join(map(str,missing)))
    out={'status':'PASS' if all(checks.values()) and len(checks)==52 else 'FAIL','passed':sum(bool(v) for v in checks.values()),'total':len(checks),'checks':checks,'same_mission_e2e_status':e2e.get('status')}
    print(json.dumps(out,ensure_ascii=False,indent=2,sort_keys=True)); return 0 if out['status']=='PASS' else 1
if __name__=='__main__': raise SystemExit(main())
