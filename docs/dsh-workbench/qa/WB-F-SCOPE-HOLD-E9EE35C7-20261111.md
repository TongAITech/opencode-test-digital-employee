# F independent Scope HOLD fix recheck — e9ee35c7

Candidate PR #223, exact source `e9ee35c73bc51d99748acebed81335c1a3ce6049`. Approved behavior design: `9623f30c1baf81d1a78490cca373689e42ceed80`. Date 2026-11-11.

**NOT_ACCEPTED — P1_UNKNOWN_RESOLVER_DEPENDENCY.** F #224's old exact fd9 failures remain historical evidence. Their direct regression cases now pass at e9; this does not close the remaining unknown-dependency hole. F changed no implementation or 08/09/10 and did not merge.

## P1: trusted resolver wrapper still executes unknown nested dependencies

`rc7_runtime/unadmitted_scope_guard.py:69–82` verifies the top-level CanonicalCriticalPathResolver.resolve function/receiver, resolver and schedule_semantics truth/release references and object identity. It does not validate callables reached inside that resolver. The real `rc72_critical_path.py:66–67` calls `self.schedule_semantics.resolve(task)` then `self._assess(...)`.

Two separate independent disposable-R1 cases replace either `c.schedule_semantics.resolve` or `c.critical_path._assess` with an unknown forwarding callback on the existing default object. No arbitrary Control method, raw writer, external service or production target is changed. Both dependencies retain the exact same objects, truth and release references. For each case the protected public `c.lease_next(worker_ref='w', capabilities=[])` passes preflight, **invokes that unknown callback**, and **writes the Task lease**. The diagnostic output is `RESULT T1`, `CALLS ['semantics.resolve']` / `CALLS ['critical._assess']`, `UNCHANGED False`.

This is the same explicit unknown-dependency boundary as the fixed adapter hole, one level deeper in the actual adapter's default call chain. A checked wrapper cannot establish what its unchecked delegate will execute. The expected result is MISSION_SCOPE_TARGET_UNRESOLVED before trying unknown dependency callables or writing. Supported default resolver/semantics/selector and legitimate clock behavior must remain usable. F does not implement the repair and does not demand arbitrary whole-program closure; these are two concrete callbacks reached by this protected operation.

## Exact-source actual execution

- Old F #224 independent matrix, run unchanged from `/tmp/f_hold_fd9_audit.py`: **34/34 passed**, 1.74 seconds. Both original cross-target start/private-persist matrices, last-output old targets, historical repair/repro/qualification derived targets, scope/reactivation/ready, missing-Gap and outer callbacks now pass on e9. No fd9 PASS was transferred.
- `python3 -m pytest tests/test_rc7_unadmitted_scope_hold.py -q`: **61/61 passed**, 1.48 seconds; actual pytest collection/execution.
- The same 15 affected legacy files enumerated in the workflow: **68/68 passed**, 2.56 seconds. No field-hardening skips are counted as PASS here.
- New independent matrix `/tmp/f_hold_e9_matrix.py`: **148 passed / 2 failed**, 1.97 seconds. The two retained failures are the exact unknown nested callback cases above. No audit-fixture errors occurred in this matrix.
- CI [42889398526](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42889398526): F inspected explicit checkout ref, checkout HEAD and git-rev logs for exact **e9ee35c73bc51d99748acebed81335c1a3ce6049** in both jobs. Actual Python **3.8.18** ran **129 passed** in 3.50 seconds; actual Python **3.11.18** ran **129 passed** in 3.65 seconds. These correct exact-head results do not exercise or cancel F's two failures.

## Independent lease/state footprint and compatibility

The new matrix includes **96 combinations**: default economy adapter or base scheduler × REPAIR/QUALIFY_DEFECT/PRODUCE × REGISTERED/READY/LEASED/RUNNING/OUTPUT_PRODUCED/BLOCKED/REPAIR_REQUIRED/CANCELLED × matching/nonmatching capabilities. Every case uses an existing Task with a future/missing Gap ref and a one-shot capabilities iterable. Every iterable is consumed exactly once.

Actual source and all 96 cases show **lease_next does not refresh REGISTERED tasks**: both implementations call ready_tasks, which selects only existing READY rows. REGISTERED remains unchanged and returns None. A's proposed implicit-refresh scenario is therefore not a reproduced defect on e9. READY ownership tasks with matching caps HOLD before any lease because the reachable Gap is absent. Nonmatching caps, non-READY states and ordinary PRODUCE future refs preserve their original applicable behavior. The matrix compares complete projection and R1 bytes for zero-effect paths. This distinction prevents a blanket ban on legitimate future registration refs.

Two additional OUTPUT_PRODUCED cases independently check REPAIR PASS and QUALIFY_DEFECT resolution with missing required Gap targets: both reject before evaluation or task prefix. Software fixture states are explicit persisted test data, not a claim of production accepted execution.

The remaining **50 passing cases** exercise all self-owned/forwarded outer method names, delegate methods, planner methods and router.route through the guard's actual enumerated surfaces (39 override cases), all five component truth/release associations (10 cases), and a legal supplied clock (1 case). Unknown component override tripwires are not called; association mismatches HOLD. Old F34 and E61 add wrong bound-function receiver and cold replay/input/projection checks. Those successful top-level checks are why the two nested dependency counterexamples are specifically material.

## Scope and retained residuals

The required package-source helper remains included and its source contract test ran in E61; no complete Windows/offline package was rebuilt. This is a local negative guard only: production creation/binding, formal model and reader preservation, PostgreSQL admission/writer/008, Host fences and formal permissions are not accepted by it. Original Q7 and exact Field-start requirements remain. Bank TruthRuntime constructor mtime touches, direct scheduler/planner/session/raw append, external upstream writes and cross-process stale/concurrent projection races remain disclosed residuals. The protected lease callback failures above cannot be assigned to those residuals. A concentrates the full RC7/RC7.2 integration regression after a usable candidate; F gives no global or field PASS.

## New independent executable matrix

Run from this exact worktree: `python3 -m pytest /tmp/f_hold_e9_matrix.py -q`.

```python
import sys,os,copy
sys.path[:0]=[os.getcwd(),os.path.join(os.getcwd(),'tests')]
import pytest
from test_rc7_unadmitted_scope_hold import control,scope,task,gap,unchanged
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import Task,Evaluation,EvaluationResult
from rc7_runtime.control_plane import WorkerOutput

@pytest.mark.parametrize('adapter',[True,False])
@pytest.mark.parametrize('kind',['REPAIR','QUALIFY_DEFECT','PRODUCE'])
@pytest.mark.parametrize('state',['REGISTERED','READY','LEASED','RUNNING','OUTPUT_PRODUCED','BLOCKED','REPAIR_REQUIRED','CANCELLED'])
@pytest.mark.parametrize('matching',[True,False])
def test_actual_lease_state_footprint(tmp_path,adapter,kind,state,matching):
 t=TruthRuntime(tmp_path/'r1');c=control(t)
 c.register_task(Task('T','M1','TEST_DESIGN',kind,'future',gap_refs=['FUTURE'],required_capabilities=['x']))
 row=t.query('rc7_task',task_id='T')[0];row.update(state=state,artifact_version=row['artifact_version']+1);t.append_atomic('RC7_TASK_UPSERTED',row)
 if not adapter:c.scheduler=c.scheduler.delegate;c.gap_planner.scheduler=c.scheduler
 before=t.store.path.read_bytes();projection=copy.deepcopy(t.projection.snapshot())
 class Caps:
  count=0
  def __iter__(self):
   self.count+=1
   if self.count>1:pytest.fail('capabilities consumed twice')
   yield from ['x'] if matching else []
 caps=Caps()
 if state=='READY' and matching and kind!='PRODUCE':
  unchanged(t,lambda:c.lease_next(worker_ref='w',capabilities=caps),code='MISSION_SCOPE_TARGET_UNRESOLVED')
 else:
  result=c.lease_next(worker_ref='w',capabilities=caps)
  if state=='READY' and matching:assert result.task_id=='T' and t.query('rc7_task',task_id='T')[0]['state']=='LEASED'
  else:assert result is None;assert before==t.store.path.read_bytes();assert projection==t.projection.snapshot()
 assert caps.count==1

@pytest.mark.parametrize('kind',['REPAIR','QUALIFY_DEFECT'])
def test_reachable_missing_gap_after_output(tmp_path,kind):
 t=TruthRuntime(tmp_path/'r1');c=control(t)
 c.register_task(Task('T','M1','DEFECT' if kind=='QUALIFY_DEFECT' else 'TEST_DESIGN',kind,'future',gap_refs=['FUTURE']))
 row=t.query('rc7_task',task_id='T')[0];row.update(state='OUTPUT_PRODUCED',lease_owner='w',artifact_version=row['artifact_version']+1);t.append_atomic('RC7_TASK_UPSERTED',row)
 ev=Evaluation('EV','M1',row['node'],[],EvaluationResult.PASS,'reviewer')
 class DefectInput:mission_id='M1'
 call=(lambda:c.accept_evaluation('T',evaluation=ev)) if kind=='REPAIR' else (lambda:c.accept_defect_resolution('T',defect=DefectInput(),evaluation=ev))
 unchanged(t,call,ev,code='MISSION_SCOPE_TARGET_UNRESOLVED');assert not t.query('rc7_evaluation',evaluation_id='EV')

@pytest.mark.parametrize('location',['semantics.resolve','critical._assess'])
def test_unknown_nested_dependency_must_not_run(tmp_path,location):
 t=TruthRuntime(tmp_path/'r1');c=control(t);task(c);calls=[]
 obj,method=(c.schedule_semantics,'resolve') if location.startswith('semantics') else (c.critical_path,'_assess');original=getattr(obj,method)
 def callback(*args,**kwargs):calls.append(location);return original(*args,**kwargs)
 setattr(obj,method,callback)
 try:unchanged(t,lambda:c.lease_next(worker_ref='w',capabilities=[]),code='MISSION_SCOPE_TARGET_UNRESOLVED')
 finally:print('UNKNOWN_DEPENDENCY_INVOKED',calls)

from rc7_runtime.unadmitted_scope_guard import _SCHEDULER,_ADAPTER,_PLANNER
CASES=[('outer',n) for n in sorted(set(_SCHEDULER)|set(_ADAPTER))]+[('inner',n) for n in sorted(_SCHEDULER)]+[('planner',n) for n in sorted(_PLANNER)]+[('router','route')]
@pytest.mark.parametrize('where,method',CASES)
def test_complete_known_dependency_override_surface(tmp_path,where,method):
 t=TruthRuntime(tmp_path/'r1');c=control(t);task(c);calls=[]
 obj={'outer':c.scheduler,'inner':c.scheduler.delegate,'planner':c.gap_planner,'router':c.gap_planner.router}[where]
 def callback(*args,**kwargs):calls.append((where,method));pytest.fail('unknown component method called')
 setattr(obj,method,callback)
 unchanged(t,c.refresh_ready,code='MISSION_SCOPE_TARGET_UNRESOLVED');assert not calls

@pytest.mark.parametrize('where',['outer','inner','planner','resolver','semantics'])
@pytest.mark.parametrize('field',['truth','release_id'])
def test_truth_release_association_before_writes(tmp_path,where,field):
 t=TruthRuntime(tmp_path/'r1');other=TruthRuntime(tmp_path/'other');c=control(t);task(c)
 obj={'outer':c.scheduler,'inner':c.scheduler.delegate,'planner':c.gap_planner,'resolver':c.critical_path,'semantics':c.schedule_semantics}[where]
 setattr(obj,field,other if field=='truth' else 'FOREIGN')
 unchanged(t,lambda:c.lease_next(worker_ref='w',capabilities=[]),code='MISSION_SCOPE_TARGET_UNRESOLVED')

def test_legal_clock_is_retained(tmp_path):
 from datetime import datetime,timezone
 t=TruthRuntime(tmp_path/'r1');c=control(t);task(c);calls=[]
 def clock():calls.append(True);return datetime(2026,11,11,10,0,tzinfo=timezone.utc)
 c.scheduler.clock=clock
 assert c.lease_next(worker_ref='w',capabilities=[]).task_id=='T1';assert calls
```

## Minimal actual callback diagnostic

```python
import os,sys,tempfile
sys.path[:0]=[os.getcwd(),os.path.join(os.getcwd(),'tests')]
from test_rc7_unadmitted_scope_hold import control,task
from rc6_runtime.truth import TruthRuntime
for location in ['semantics.resolve','critical._assess']:
 with tempfile.TemporaryDirectory() as root:
  truth=TruthRuntime(root+'/r1');c=control(truth);task(c);calls=[]
  target,attr=(c.schedule_semantics,'resolve') if location.startswith('semantics') else (c.critical_path,'_assess')
  original=getattr(target,attr)
  def callback(*args,**kwargs):calls.append(location);return original(*args,**kwargs)
  setattr(target,attr,callback);before=truth.store.path.read_bytes()
  try:result=c.lease_next(worker_ref='w',capabilities=[]);print(location,'RESULT',result.task_id if result else None)
  except Exception as e:print(location,'ERROR',str(e))
  print('CALLS',calls,'UNCHANGED',before==truth.store.path.read_bytes())
```
