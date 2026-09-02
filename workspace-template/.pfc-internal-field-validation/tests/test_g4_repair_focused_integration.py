from __future__ import annotations
import hashlib, json, os, subprocess, sys, tempfile
from pathlib import Path

WORKSPACE=Path(__file__).resolve().parents[2]
RUNTIME=WORKSPACE/'ai-test/runtime'
TESTS=Path(__file__).parent
sys.path.insert(0,str(RUNTIME)); sys.path.insert(0,str(TESTS))
from aitest_runtime.canonical_runtime import bootstrap_mission, create_canonical_runtime
from aitest_runtime.g3.coverage import CoverageProviderResult, MappingCoveragePlatformProvider
from aitest_runtime.g3.service import G3TestingIntelligenceService
from aitest_runtime.g4.service import G4RealExecutionService
from test_g4_full_same_mission_product_e2e import snap

LEGACY=WORKSPACE/'ai-test/state/aitest.db'
EXPECTED_LEGACY='2e3183adfda3372350cd027d4a42e6394c9c538e7082f8e6e08527f4c67332a6'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def parse_json(text):
    a=text.find('{'); b=text.rfind('}')
    if a<0 or b<a: raise AssertionError(text)
    return json.loads(text[a:b+1])

def main():
    checks={}; before=sha(LEGACY)
    # Re-run the real same-Mission chain; focused claims derive from fresh product evidence, not cached JSON.
    env=os.environ.copy(); env['PYTHONPATH']=str(RUNTIME)+os.pathsep+str(TESTS)
    p=subprocess.run([sys.executable,str(TESTS/'test_g4_full_same_mission_product_e2e.py')],cwd=WORKSPACE,env=env,text=True,capture_output=True,timeout=240)
    e2e=parse_json(p.stdout); c=e2e.get('checks') or {}
    checks['canonical_execution_attempt_cursor']=p.returncode==0 and c.get('explicit_resume_same_context_root_step') is True and c.get('b_root_attempt_preserved_after_rotation') is True
    checks['canonical_r26_gate_and_ai_turn_yield']=c.get('human_takeover_product_entry_yields') is True and c.get('waiting_a_allows_independent_b') is True
    checks['same_r3e3_context_reclaimed_original_attempt_step']=c.get('explicit_resume_same_context_root_step') is True and c.get('deterministic_auto_resume') is True
    checks['session_rotation_control_restart_preserves_root_cursor']=c.get('session_rotation_control_restart') is True and c.get('b_root_attempt_preserved_after_rotation') is True

    with tempfile.TemporaryDirectory(prefix='g4-focused-') as td:
        root=Path(td); db=root/'runtime-spine.db'
        oldroot,olddb=os.environ.get('AITEST_WORKSPACE_ROOT'),os.environ.get('AITEST_RUNTIME_SPINE_DB')
        os.environ['AITEST_WORKSPACE_ROOT']=str(root); os.environ['AITEST_RUNTIME_SPINE_DB']=str(db)
        try:
            mid='focus-mission'; bootstrap_mission(root,mission_id=mid,goal_id='focus-goal',goal={'objective':'focused G4 construction evidence','scope_digest':'focus'})
            runtime=create_canonical_runtime(root,db_path=db)
            provider=MappingCoveragePlatformProvider(CoverageProviderResult('AVAILABLE',('AGGREGATE',),snapshot=snap('cfg-data',93.8,61,'head-focus')))
            cv=G3TestingIntelligenceService(runtime,coverage_provider=provider).acquire_coverage(mid,{'platform_profile_id':'bankcov','authenticated_context_ref':'auth','method':'API'},{'application_id':'cfg-data','target_version':'V2','baseline_label':'master'})
            g4=G4RealExecutionService(runtime)
            g4.create_goal(mid,{'goal_id':'focus-g4','project_id':'PFC','release_id':'V2','requirement_scope':['REQ-018'],'affected_applications':['cfg-data'],'coverage_policy':{'target_pct':95}})
            m=g4.record_coverage_from_g3(mid,{'measurement_id':'focus-m','goal_id':'focus-g4','state':'AVAILABLE','g3_snapshot_fact_id':cv['snapshot']['fact_id']})
            checks['g3_bank_snapshot_to_g4_master_alias']=m['measurement']['payload'].get('baseline_identity_status')=='MASTER_ALIAS_ONLY' and m['actual_coverage']==93.8
            subenv=env.copy(); subenv['AITEST_WORKSPACE_ROOT']=str(root); subenv['AITEST_RUNTIME_SPINE_DB']=str(db)
            q=subprocess.run([sys.executable,'-m','aitest_runtime.product_entry','g4','--role','DIRECTOR','--action','status','--payload',json.dumps({'mission_id':mid})],cwd=WORKSPACE,env=subenv,text=True,capture_output=True,timeout=60)
            sj=parse_json(q.stdout)
            checks['product_entry_subprocess_g4_truth']=q.returncode==0 and sj.get('truth_source')=='R1_EVENT_STREAM' and sj.get('mission_id')==mid
        finally:
            if oldroot is None: os.environ.pop('AITEST_WORKSPACE_ROOT',None)
            else: os.environ['AITEST_WORKSPACE_ROOT']=oldroot
            if olddb is None: os.environ.pop('AITEST_RUNTIME_SPINE_DB',None)
            else: os.environ['AITEST_RUNTIME_SPINE_DB']=olddb
    after=sha(LEGACY)
    checks['legacy_aitest_db_unchanged']=before==EXPECTED_LEGACY==after
    out={'status':'PASS' if all(checks.values()) else 'FAIL','passed':sum(bool(v) for v in checks.values()),'total':len(checks),'checks':checks}
    print(json.dumps(out,ensure_ascii=False,indent=2,sort_keys=True)); return 0 if out['status']=='PASS' else 1
if __name__=='__main__': raise SystemExit(main())
