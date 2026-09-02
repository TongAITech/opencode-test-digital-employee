from __future__ import annotations
import json, os, sys, tempfile
from pathlib import Path

WORKSPACE=Path(__file__).resolve().parents[2]; RUNTIME=WORKSPACE/'ai-test/runtime'; TESTS=Path(__file__).parent
sys.path.insert(0,str(RUNTIME)); sys.path.insert(0,str(TESTS))
from aitest_runtime import product_entry
from aitest_runtime.autonomous_orchestration import FakeOpenCodeSessionProvider
from aitest_runtime.canonical_runtime import create_canonical_runtime
from aitest_runtime.g2_1 import G21AutonomousOrchestrationService
from aitest_runtime.durable_core import canonical_sha256
from test_g4_full_same_mission_product_e2e import intake_request, exec_task, binding

def decide(orch, mid, gate_id, outcome):
    return orch.decide_human_gate({'mission_id':mid,'gate_id':gate_id,'decision_id':'decision:'+gate_id,'outcome':outcome,'route':'NONE','decision_payload':{'completed':True},'decision_provenance':{'source_ref':'human:'+gate_id,'source_digest':canonical_sha256(gate_id),'observed_at':'2026-09-02T12:00:00Z'},'actor':{'type':'USER','id':'reviewer'}})

def main()->int:
    checks={}
    with tempfile.TemporaryDirectory(prefix='g4-human-capability-') as td:
        root=Path(td); db=root/'runtime-spine.db'; oldroot=os.environ.get('AITEST_WORKSPACE_ROOT'); olddb=os.environ.get('AITEST_RUNTIME_SPINE_DB')
        os.environ['AITEST_WORKSPACE_ROOT']=str(root); os.environ['AITEST_RUNTIME_SPINE_DB']=str(db)
        runtime=create_canonical_runtime(root,db_path=db); provider=FakeOpenCodeSessionProvider(root); orch=G21AutonomousOrchestrationService(runtime,root,session_provider=provider)
        oldos,oldds=product_entry.orchestration_service,product_entry.default_service
        product_entry.orchestration_service=lambda _root=None: orch; product_entry.default_service=lambda _rt,_root: orch
        try:
            started=product_entry.orchestration_command('DIRECTOR','start_test',{'request':intake_request()}); mid=started['intake']['intake']['mission_id']
            plan=product_entry.orchestration_command('PLANNER','propose_plan',{'mission_id':mid,'proposal':{'objective':'capability HumanGate product path','tasks':[exec_task('EXEC-HUMAN','TC-HUMAN')],'dependencies':[]}})
            b=binding(plan['next']); root_attempt=plan['next']['attempt']['root_attempt_id']
            cat=product_entry.g4_command('EXECUTOR','capability_human_gate',{**b,'capability_id':'CAT_LOG','gate_id':'cat-auth','executor_request':{'provider_ref':'cat:bank','operation':'READ'},'required_action':'authenticate CAT'})
            cg=cat.get('human_gate') or {}
            checks['cat_auth_required_creates_canonical_r26_gate']=cat.get('status')=='WAITING_HUMAN' and cat.get('ai_turn')=='YIELD' and cg.get('gate_kind')=='EXTERNAL_ACTION' and cg.get('root_attempt_id')==root_attempt and cg.get('origin_attempt_id')==b['attempt_id'] and cg.get('origin_session_id')==b['session_id']
            decide(orch,mid,'cat-auth','EXTERNAL_ACTION_COMPLETED')
            manual=product_entry.g4_command('EXECUTOR','capability_human_gate',{**b,'capability_id':'MANUAL','gate_id':'manual-action','executor_request':{'required_action':'prepare external test data'},'required_action':'prepare external test data'})
            mg=manual.get('human_gate') or {}
            checks['manual_executor_is_durable_human_gate']=manual.get('status')=='WAITING_HUMAN' and mg.get('gate_kind')=='EXTERNAL_ACTION' and mg.get('root_attempt_id')==root_attempt
            decide(orch,mid,'manual-action','EXTERNAL_ACTION_COMPLETED')
            dbgate=product_entry.g4_command('EXECUTOR','capability_human_gate',{**b,'capability_id':'DB_DATA','gate_id':'db-write-approval','executor_request':{'connection_ref':'db:test','query':'update t set x=1','operation':'WRITE'},'required_action':'approve governed DB write'})
            dg=dbgate.get('human_gate') or {}
            checks['db_write_approval_creates_canonical_r26_gate']=dbgate.get('status')=='WAITING_HUMAN' and dg.get('gate_kind')=='APPROVAL' and set(dg.get('allowed_outcomes') or [])=={'APPROVED','REJECTED'}
            r26=runtime.replay_composed(mid).extension_state('r2_6_human_gate'); gates=list(getattr(r26,'gates',()))
            checks['human_gate_truth_is_only_r26_and_exact_lineage']=len(gates)==3 and sum(g.status=='PENDING' for g in gates)==1 and all(g.mission_id==mid and g.task_id==b['task_id'] and g.root_attempt_id==root_attempt for g in gates)
        finally:
            product_entry.orchestration_service,product_entry.default_service=oldos,oldds
            if oldroot is None: os.environ.pop('AITEST_WORKSPACE_ROOT',None)
            else: os.environ['AITEST_WORKSPACE_ROOT']=oldroot
            if olddb is None: os.environ.pop('AITEST_RUNTIME_SPINE_DB',None)
            else: os.environ['AITEST_RUNTIME_SPINE_DB']=olddb
    out={'status':'PASS' if all(checks.values()) else 'FAIL','passed':sum(bool(v) for v in checks.values()),'total':len(checks),'checks':checks}
    print(json.dumps(out,ensure_ascii=False,indent=2,sort_keys=True)); return 0 if out['status']=='PASS' else 1
if __name__=='__main__': raise SystemExit(main())
