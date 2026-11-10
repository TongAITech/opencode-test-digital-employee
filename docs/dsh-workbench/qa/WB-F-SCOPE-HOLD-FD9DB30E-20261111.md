# F independent formal runtime negative guard review

PR #223, exact tested source `fd9db30e81e3c8b186275ca4eb432790b75f801e`; approved design `9623f30c1baf81d1a78490cca373689e42ceed80`. Review date: 2026-11-11.

**NOT_ACCEPTED: P1_UNRESOLVED_GAP_PREFIX and P1_UNKNOWN_ADAPTER_CALLBACK.** F changed no implementation, 08/09/10, model, reader or writer; no branch was merged. Findings were sent to A during testing.

## P1_UNRESOLVED_GAP_PREFIX

`rc7_runtime/unadmitted_scope_guard.py:124–128` collects an existing Task's gap_refs using `Targets.old(..., required=False)`. An absent referenced Gap therefore adds no Mission to the target set and is treated as safe. The approved design explicitly requires unresolved write targets to HOLD before the first write, with absent-Mission bootstrap as the narrow exception.

Reproduction through real public calls and a disposable persisted R1: bootstrap an unbound M1, register a REPAIR Task T with gap_refs=['MISSING'], then lease_next(worker_ref='w', capabilities=[]). Registration is currently permitted. During leasing, the guard passes; scheduler first persists Task LEASED, then Control's `_gap('MISSING')` raises `GAP_NOT_FOUND:MISSING`. Measured before/after R1 bytes **differ**, projection **differs**, Task is **LEASED**. This is not a zero-effect legacy missing-task error. It is not a raw-scheduler bypass, external process race or lack of field environment. The missing target cannot establish an unbound Mission, and the explicit new unresolved-target contract must apply before that prefix write.

Expected: when an existing referenced Gap is needed by the action's write footprint but cannot be resolved, reject with MISSION_SCOPE_TARGET_UNRESOLVED before lease/ready/Gap/mission mutation. Do not blindly reject legitimate new Gap inputs that the operation itself is creating. The exact candidate's ordinary scoped-Mission tests pass and do not cover this case.

## P1_UNKNOWN_ADAPTER_CALLBACK

`unadmitted_scope_guard.py:42–57` recognizes the default EconomyAwareTaskSchedulerAdapter, but checks instance overrides for only ready_tasks, lease_next, lease_task and _plan. It then unwraps the delegate and checks TaskScheduler's methods. Adapter-level forwarding overrides such as refresh_ready, task, start and submit_worker_output are left unverified.

Independent tests install an unknown forwarding callback at each of those **four adapter methods**. Protected Control calls execute it instead of failing closed. All four callbacks are actually observed; the ordinary forwarding cases complete without MISSION_SCOPE_TARGET_UNRESOLVED. A separate tripwire on adapter.refresh_ready raises because it is executed at all. This is a substituted scheduler dependency, explicitly covered by the design's unknown-callback boundary, not an arbitrary replacement of Control's own implementation. Checking the delegate cannot prove which adapter callable will run. Even the early scheduler.task call used to retain old errors can invoke an unknown callback before target inspection.

Expected: every adapter operation actually used during preflight and the protected action must be known before it is invoked; unknown substitutions must HOLD without trying the callback. Preserve the standard supported adapter and injected clock's ordinary unbound behavior. F reports the defect and does not implement a repair.

## Exact-source actual checks

- `python3 -m pytest tests/test_rc7_unadmitted_scope_hold.py -q`: **32 passed**, 1.88 seconds. This is actual pytest collection/execution, not zero-test unittest discovery.
- The 15 affected legacy files enumerated by this candidate's workflow, excluding the new file: **68 passed**, 3.13 seconds. Combined local candidate/affected coverage is 100 actual tests.
- Independent `/tmp/f_hold_fd9_audit.py` final matrix: **28 passed, 6 failed**, 1.32 seconds. Six failures represent the missing-Gap counterexample plus five tests of the adapter hole (one tripwire and four forwarding overrides), i.e. two distinct P1 findings. The matrix and its exact expectations are included below; failures are retained rather than omitted.
- First independent run was 26 passed/4 failed. Two failures were F fixture setup errors: a synthetic PASS source Task lacked its required durable PASS evaluation. F corrected only the temporary fixture by appending a matching evaluation before that Task, preserving runtime durable acceptance checks. The corrected repro and qualification target cases pass; these setup errors are not product defects.
- A separate minimal public missing-Gap diagnostic reports `ERROR ClosedLoopControlError GAP_NOT_FOUND:MISSING`, `BYTES_UNCHANGED False`, `PROJECTION_UNCHANGED False`, `TASK LEASED`.
- GitHub run [42886918199](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42886918199), pull_request event, has explicit checkout of **fd9db30e81e3c8b186275ca4eb432790b75f801e** in both logs and git-rev verification. Real Python **3.8.18**: **100 passed**, 4.23 seconds; real Python **3.11.18**: **100 passed**, 4.01 seconds. These exact-head CI passes are corroboration only; neither covers or cancels F's failures.
- Source packaging declares `rc7_runtime/unadmitted_scope_guard.py` in REQUIRED_PRODUCT_FILES and includes rc7_runtime in SOURCE_DIRS; the real package-source test passed. No full Windows/offline package was rebuilt or claimed.

Independent passing cases include both original foreign-target start/private-persist counterexamples over three reserved keys × three values; last-output old Artifact/Evidence targets with zero prefix; repair/reproduction/qualification historical derived Task targets; source resolve/reactivate and ready-scan foreign Gap footprints; unsupported planner/router callbacks. Passing negative cases compare R1 bytes, complete projections, input objects and cold replay. The remaining planned broad entrypoint matrix is not claimed independently complete after the P1 findings. Existing bank/N1/bootstrap/legacy/one-shot tests and affected regressions ran as described; no wider acceptance is inferred from them.

## Boundaries retained

This candidate is a local negative guard, not a Scope admission capability, production binding, model-preservation solution or global writer fence. Existing Q7 and exact Field-start qualification remain prerequisites. Bank TruthRuntime construction may touch mtime; unchanged bytes/projections do not prove unchanged mtime. Direct raw scheduler/planner/session/append paths, external upstream writes, cross-process stale projections and concurrent writer races remain residual. These disclosed residuals do **not** excuse either protected-call finding above. No native DSH, Windows field, Human/NodeGate, PostgreSQL admission or final release PASS is claimed.

## Independent pytest matrix

Run from this exact worktree: `python3 -m pytest /tmp/f_hold_fd9_audit.py -q`. Synthetic R1 only, no production evidence.

```python
import os,sys,copy
sys.path[:0]=[os.getcwd(),os.path.join(os.getcwd(),'tests')]
import pytest
from test_rc7_unadmitted_scope_hold import control,scope,task,gap
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import Mission,Task,Artifact,Evidence,Evaluation,EvaluationResult,Gap,GapSeverity,TaskStatus
from rc7_runtime.control_plane import WorkerOutput,_stable_id
from rc7_runtime.truth_overlay import append_entity

def blocked(t,call,code='MISSION_SCOPE_NOT_ADMITTED',inputs=()):
 b=t.store.path.read_bytes();p=copy.deepcopy(t.projection.snapshot());i=copy.deepcopy(inputs)
 with pytest.raises(RuntimeError,match=code):call()
 assert b==t.store.path.read_bytes();assert p==t.projection.snapshot();assert i==inputs
 cold=TruthRuntime(t.store.path);assert cold.projection.snapshot()==p;assert b==t.store.path.read_bytes()

def ready(t,c):
 task(c);c.lease_next(worker_ref='w',capabilities=iter(()));c.start('T1',worker_ref='w');c.submit_worker_output(WorkerOutput('T1','w'))

@pytest.mark.parametrize('key',['project_id','batch_id','scope_binding'])
@pytest.mark.parametrize('value',[None,{},'bound-fixture'])
@pytest.mark.parametrize('action',['start','persist'])
def test_original_foreign_targets(tmp_path,key,value,action):
 t=TruthRuntime(tmp_path/'r1');a=control(t);b=control(t,'M2');task(b,'T2');b.lease_next(worker_ref='w',capabilities=[]);scope(t,'M2',key,value)
 incoming=Mission('M2','R','M2')
 blocked(t,lambda:a.start('T2',worker_ref='w') if action=='start' else a._persist_mission(incoming),inputs=(incoming,))

@pytest.mark.parametrize('kind',['artifact','evidence'])
def test_last_output_foreign_old_identity(tmp_path,kind):
 t=TruthRuntime(tmp_path/'r1');a=control(t);control(t,'M2');task(a);a.lease_next(worker_ref='w',capabilities=[]);a.start('T1',worker_ref='w')
 def obj(id,mission):
  return Artifact(id,mission,'TEST_DESIGN','T1','runtime://fixture') if kind=='artifact' else Evidence(id,mission,'fixture','runtime://s','runtime://c')
 append_entity(t,obj('Z','M2'),release_id='R');scope(t,'M2')
 output=WorkerOutput('T1','w',**{kind+'s' if kind=='artifact' else 'evidence':(obj('A','M1'),obj('Z','M1'))})
 blocked(t,lambda:a.submit_worker_output(output),inputs=(output,))
 assert not t.query('rc7_'+kind,**{kind+'_id':'A'})

@pytest.mark.parametrize('derived',['repair','repro','qualification'])
def test_derived_old_task_targets(tmp_path,derived):
 t=TruthRuntime(tmp_path/'r1');a=control(t);b=control(t,'M2');ready(t,a)
 if derived=='repair':g=gap();id=_stable_id('TASK-REPAIR','M1','G1','TEST_DESIGN')
 else:
  g=Gap('G1','M1','TEST_DESIGN','PRODUCT_DEFECT',GapSeverity.HIGH,'DEFECT','fixture')
  append_entity(t,Evaluation('SOURCE-PASS','M1','EXECUTION',[],EvaluationResult.PASS,'reviewer'),release_id='R');source=Task('SOURCE','M1','EXECUTION','PRODUCE','fixture',state=TaskStatus.PASS,evaluation_id='SOURCE-PASS');append_entity(t,source,release_id='R')
  append_entity(t,Artifact('SRC','M1','EXECUTION_CONCLUSION','SOURCE','runtime://fixture'),release_id='R')
  append_entity(t,Evaluation('SOURCE-EV','M1','EXECUTION',['SRC'],EvaluationResult.REPAIR_REQUIRED,'reviewer',gap_refs=['G1'],dimensions={'failure_class':'PRODUCT','test_result':'FAIL'}),release_id='R')
  id=_stable_id('TASK-DEFECT-REPRO','M1','G1','SRC') if derived=='repro' else _stable_id('TASK-DEFECT','M1','G1','DEFECT')
 task(b,id);scope(t,'M2');ev=Evaluation('EV','M1','TEST_DESIGN',[],EvaluationResult.REPAIR_REQUIRED,'reviewer',gap_refs=['G1'])
 blocked(t,lambda:a.accept_evaluation('T1',evaluation=ev,gaps=iter((g,))),inputs=(ev,g))
 assert not t.query('rc7_evaluation',evaluation_id='EV');assert not t.query('rc7_gap',gap_id='G1')

@pytest.mark.parametrize('operation',['resolve','reactivate','refresh'])
def test_followup_foreign_gap(tmp_path,operation):
 t=TruthRuntime(tmp_path/'r1');a=control(t);control(t,'M2');g=gap('G2','M2');append_entity(t,g,release_id='R');v=Task('T1','M1','TEST_DESIGN','PRODUCE','fixture',gap_refs=['G2']);a.register_task(v);scope(t,'M2')
 ev=Evaluation('EV','M1','TEST_DESIGN',[],EvaluationResult.PASS,'reviewer')
 call=(lambda:a._resolve_source_gaps(v,ev)) if operation=='resolve' else (lambda:a._reactivate_source_tasks(iter(('G2',)))) if operation=='reactivate' else a.refresh_ready
 blocked(t,call,inputs=(v,ev))

@pytest.mark.parametrize('replacement',['scheduler','planner','router'])
def test_unknown_components_not_executed(tmp_path,replacement):
 t=TruthRuntime(tmp_path/'r1');a=control(t);task(a)
 def forbidden(*args,**kwargs):pytest.fail('untrusted callback executed')
 if replacement=='scheduler':a.scheduler.refresh_ready=forbidden
 elif replacement=='planner':a.gap_planner.plan=forbidden
 else:a.gap_planner.router.route=forbidden
 blocked(t,a.refresh_ready,'MISSION_SCOPE_TARGET_UNRESOLVED')

def test_missing_gap_target_must_hold_before_lease(tmp_path):
 t=TruthRuntime(tmp_path/'r1');a=control(t);a.register_task(Task('T1','M1','TEST_DESIGN','REPAIR','repair',gap_refs=['MISSING']))
 blocked(t,lambda:a.lease_next(worker_ref='w',capabilities=[]),'MISSION_SCOPE_TARGET_UNRESOLVED')

@pytest.mark.parametrize('method',['refresh_ready','task','start','submit_worker_output'])
def test_default_adapter_unknown_overrides(tmp_path,method):
 t=TruthRuntime(tmp_path/'r1');a=control(t);task(a);a.lease_next(worker_ref='w',capabilities=[])
 if method=='submit_worker_output':a.start('T1',worker_ref='w')
 original=getattr(a.scheduler,method);calls=[]
 def callback(*args,**kwargs):calls.append(method);return original(*args,**kwargs)
 setattr(a.scheduler,method,callback)
 call=a.refresh_ready if method=='refresh_ready' else (lambda:a.submit_worker_output(WorkerOutput('T1','w'))) if method=='submit_worker_output' else (lambda:a.start('T1',worker_ref='w'))
 try:blocked(t,call,'MISSION_SCOPE_TARGET_UNRESOLVED')
 finally:print('UNKNOWN_ADAPTER_INVOKED',method,calls)
```

## Minimal prefix-write diagnostic

```python
import sys,os,tempfile,copy
sys.path[:0]=[os.getcwd(),os.path.join(os.getcwd(),'tests')]
from test_rc7_unadmitted_scope_hold import control
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import Task,Evaluation,EvaluationResult
from rc7_runtime.control_plane import WorkerOutput
with tempfile.TemporaryDirectory() as root:
 t=TruthRuntime(root+'/r1');c=control(t)
 c.register_task(Task('T','M1','TEST_DESIGN','REPAIR','repair',gap_refs=['MISSING']))
 before=t.store.path.read_bytes();snap=copy.deepcopy(t.projection.snapshot())
 try:c.lease_next(worker_ref='w',capabilities=[])
 except Exception as error:print('ERROR',type(error).__name__,str(error))
 print('BYTES_UNCHANGED',before==t.store.path.read_bytes(),'PROJECTION_UNCHANGED',snap==t.projection.snapshot(),'EVALUATION',len(t.query('rc7_evaluation',evaluation_id='EV')),'TASK',t.query('rc7_task',task_id='T')[0]['state'])
```
