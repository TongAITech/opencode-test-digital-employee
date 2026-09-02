from __future__ import annotations
import json, sys, tempfile
from pathlib import Path
WORKSPACE_ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(WORKSPACE_ROOT/'ai-test/runtime'))
from aitest_runtime.autonomous_orchestration import FakeOpenCodeSessionProvider
from aitest_runtime.canonical_runtime import create_canonical_runtime
from aitest_runtime.durable_core import canonical_sha256
from aitest_runtime.g2_1.managed_orchestration import G21AutonomousOrchestrationService
from aitest_runtime.r2_6 import HumanGateApplicationService
from aitest_runtime.r2_6.contracts import OUTCOMES, policy_digest

def req(tag):
 return {'intake_id':tag,'operation':'CREATE','scope':{'mode':'EXPLICIT_SET','project_id':'PFC','version':tag},'goal':{'title':'g2r','intent':'g2r','constraints':[]},'source':{'kind':'USER','source_ref':tag,'source_digest':canonical_sha256(tag),'observed_at':'2026-09-02T00:00:00Z','valid_until':None,'source_precedence':1},'actor':{'type':'USER','id':'test'},'resolution':{'resolution_id':'r:'+tag,'request_digest':canonical_sha256('r:'+tag),'snapshot_id':'s:'+tag,'fact_set_digest':canonical_sha256([]),'status':'RESOLVED','reason_code':None,'source_refs':[tag],'valid_until':'2026-09-03T00:00:00Z'}}
def task(k, caps=None):
 return {'task_key':k,'intent':'task '+k,'acceptance_criteria':[],'routing':{'role':'EXECUTOR','required_capabilities':caps or ['OPENCODE_AGENT_SESSION','TASK_OUTCOME_REPORT'],'isolation_policy':'DEDICATED_TASK_SESSION','parallelism_policy':'PARALLEL_SAFE'}}
def setup(tag,tasks,deps=None,root=None):
 root=root or Path(tempfile.mkdtemp(prefix='g2r-'))
 rt=create_canonical_runtime(root,db_path=root/'runtime-spine.db'); p=FakeOpenCodeSessionProvider(root); s=G21AutonomousOrchestrationService(rt,root,session_provider=p)
 mid=s.start_test(req(tag))['intake']['intake']['mission_id']; first=s.propose_plan(mid,{'objective':'g2r','tasks':tasks,'dependencies':deps or []})['next']; return root,rt,p,s,mid,first
def open_gate(rt,mid,dispatch,gid):
 a=dispatch['attempt']; routes={o:['NONE'] for o in OUTCOMES}; allowed=['EXTERNAL_ACTION_COMPLETED']; pol='g2r-wait'
 return HumanGateApplicationService(rt).open_gate({'mission_id':mid,'gate_id':gid,'plan_id':a['plan_id'],'plan_revision_id':a['plan_revision_id'],'task_id':dispatch['task_id'],'root_attempt_id':a['root_attempt_id'],'origin_attempt_id':a['attempt_id'],'origin_session_id':dispatch['external_session']['session_id'],'gate_kind':'EXTERNAL_ACTION','request_payload':{'action':'human'},'response_schema':{'type':'object'},'expires_at':None,'expiry_policy':'NONE','decision_policy_id':pol,'decision_policy_version':1,'decision_policy_digest':policy_digest(pol,1,allowed,routes),'allowed_outcomes':allowed,'allowed_routes_by_outcome':routes,'request_provenance':{'source_ref':gid,'source_digest':canonical_sha256(gid),'observed_at':'2026-09-02T00:00:00Z'},'actor':{'type':'SYSTEM','id':'g2r'}})
def decide(rt,mid,gid):
 return HumanGateApplicationService(rt).record_decision({'mission_id':mid,'gate_id':gid,'decision_id':'d:'+gid,'outcome':'EXTERNAL_ACTION_COMPLETED','route':'NONE','decision_payload':{'done':True},'decision_provenance':{'source_ref':'human:'+gid,'source_digest':canonical_sha256('d:'+gid),'observed_at':'2026-09-02T00:01:00Z'},'actor':{'type':'USER','id':'human'}})
def finish(s,mid,d):
 return s.report_task_outcome(mid,task_id=d['task_id'],attempt_id=d['attempt']['attempt_id'],session_id=d['external_session']['session_id'],outcome='SUCCEEDED',summary='done')
def main():
 c={}
 # 1 A waiting -> B dispatch
 root,rt,p,s,mid,a=setup('one',[task('A'),task('B')]); open_gate(rt,mid,a,'ga'); b=s.dispatch_next(mid); c['waiting_human_active_does_not_consume_slot']=b['task_id']!=a['task_id'] and b['status']=='DISPATCHED'
 # 2 ordinary active recovery priority
 root,rt,p,s,mid,a=setup('two',[task('A'),task('B')]); r=s.dispatch_next(mid); c['ordinary_active_crash_recovery_still_prioritized']=r['task_id']==a['task_id'] and 'ACTIVE_DISPATCH' in r['status']
 # 3 dependency blocked
 root,rt,p,s,mid,a=setup('three',[task('A'),task('B')],[{'from':'A','to':'B'}]); open_gate(rt,mid,a,'g3'); r=s.dispatch_next(mid); c['dependency_blocked_ready_not_dispatched']=r['status']!='DISPATCHED'
 # 4 capability/router fail closed
 blocked=False
 try:
  setup('four',[task('A'),task('B',['MISSING_CAP'])])
 except Exception as exc:
  blocked='SESSION_ROUTER_CAPABILITY_UNAVAILABLE' in str(exc)
 c['capability_router_safety_still_govern_selection']=blocked
 # 5 multiple waiting, only one runnable
 root,rt,p,s,mid,a=setup('five',[task('A'),task('B'),task('C')]); open_gate(rt,mid,a,'g5a'); b=s.dispatch_next(mid); open_gate(rt,mid,b,'g5b'); cc=s.dispatch_next(mid); again=s.dispatch_next(mid); c['multiple_waiting_human_do_not_consume_slot_and_only_one_runnable']=cc['status']=='DISPATCHED' and again['task_id']==cc['task_id']
 # 6 A human done while B running: no preempt
 root,rt,p,s,mid,a=setup('six',[task('A'),task('B'),task('C')]); open_gate(rt,mid,a,'g6'); b=s.dispatch_next(mid); decide(rt,mid,'g6'); r=s.dispatch_next(mid); c['resume_ready_does_not_preempt_running']=r['task_id']==b['task_id']
 # 7 after B complete A resumes before new C
 out=finish(s,mid,b); nxt=out['next']; c['resume_ready_prioritized_after_running_finishes']=nxt['task_id']==a['task_id']
 # 8 bad gate binding rejected and does not suspend A
 root,rt,p,s,mid,a=setup('eight',[task('A'),task('B')]); bad=False
 try:
  aa=dict(a); aa['task_id']='not-'+a['task_id']; open_gate(rt,mid,aa,'bad')
 except Exception: bad=True
 r=s.dispatch_next(mid); c['erroneous_gate_binding_cannot_suspend_unrelated_task']=bad and r['task_id']==a['task_id']
 # 9 new process decision same
 root,rt,p,s,mid,a=setup('nine',[task('A'),task('B')]); open_gate(rt,mid,a,'g9'); rt2=create_canonical_runtime(root,db_path=root/'runtime-spine.db'); s2=G21AutonomousOrchestrationService(rt2,root,session_provider=p); r=s2.dispatch_next(mid); c['new_process_restart_decision_consistent']=r['status']=='DISPATCHED' and r['task_id']!=a['task_id']
 out={'status':'PASS' if all(c.values()) else 'FAIL','count':len(c),'checks':c}; print(json.dumps(out,indent=2,sort_keys=True)); return 0 if out['status']=='PASS' else 1
if __name__=='__main__': raise SystemExit(main())
