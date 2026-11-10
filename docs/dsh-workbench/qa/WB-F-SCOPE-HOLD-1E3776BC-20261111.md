# F independent local Scope HOLD guard acceptance

PR #223, exact tested source `1e3776bcc1a9ad11166cc2f504da0797cf306d0e`; approved behavior design `9623f30c1baf81d1a78490cca373689e42ceed80`. Date: 2026-11-11.

**LOCAL_SCOPE_HOLD_COMPONENT_QA_ACCEPTED_EXACT_1E3776BC.** No remaining P0/P1 was reproduced in the tested local component scope. This accepts only the specific negative guard behavior, not formal production binding, global writer closure, native field execution or a later integrated HEAD. F did not modify tested implementation or 08/09/10, and did not merge.

## Previous independent failures retained and freshly rechecked

- F #224, exact fd9: unresolved Gap allowed a lease prefix; unknown outer adapter forwarding methods ran. Historical failure retained. Its full independent34 cases are newly **34/34** on this source.
- F #227, exact e9: default resolver reached unknown schedule_semantics.resolve / critical._assess. Historical failure retained. Its full independent150 cases are newly **150/150** on this source.
- F #229, exact 1b: unknown callable's attribute hooks ran, and forged __func__/__self__ admitted unknown scheduler/planner/router dependency values. Historical failure retained. Its eight-case independent matrix is newly **8/8** on this source, including protected public start and both plain/spoof modes.

Those are exact-source reruns, not transfers of old results. F229's ordinary unknown object now has zero attribute hooks and zero calls; its spoof object is refused before an operation writes. The first two old original public start/private persist foreign-target counterexamples remain explicitly exercised.

## Implementation review

The delta from 1b changes only helper, tests and evidence. `_bound` first proves concrete FunctionType for the expected method, then concrete MethodType for bound values or concrete FunctionType plus identity for static values. Unknown objects receive no __func__/__self__ lookup. Real bound values must have the original function and exact receiver. Static method handling uses known descriptors, and unknown class method descriptors are rejected statically before ordinary attribute resolution. Scheduler, adapter, planner and router now share this check. The held default resolver/semantics/selector/policy closure retains its static descriptor, receiver, object identity and truth/release checks. No formal model, reader, PG/writer/008 or permission-granting change is present.

This identity proof covers known dependency slots in the current in-process call chain; arbitrary global replacement of all Python objects is not claimed to be fenced. Original valid clock injection is supported. Scope targets are still collected from self/input/old identities and reachable planner/Gap/Task footprints before the protected action; no trial planner invocation is used to discover targets.

## Actual new pytest execution at exact source

1. `python3 -m pytest /tmp/f_hold_fd9_audit.py /tmp/f_hold_e9_matrix.py /tmp/f_hold_1b_callable_matrix.py tests/test_rc7_unadmitted_scope_hold.py -q -p no:cacheprovider`: **294/294**, 5.17 seconds, no skip. Breakdown F34 + F150 + F8 + candidate102. The candidate102 includes all new author24 cases, which F read and actually ran.
2. The 15 affected legacy files enumerated in `.github/workflows/dsh-wb-unadmitted-scope-hold.yml`, excluding the new guard file: **68/68**, 2.60 seconds, no skip.
3. Additional independent `/tmp/f_hold_1e_independent.py`, included below: **19/19**, 0.60 seconds, no skip. Its18 ordinary/spoof cases install an Unknown object with a strict __getattribute__ tripwire in nine slots: outer.start; delegate.start and static _task_from_row; planner.plan; router.route; critical._assess; semantics.resolve; selector.plan; policy.is_working_day. All prove **zero unknown attribute probes, zero calls, unchanged R1 bytes, unchanged complete projection and equal cold replay**. The nineteenth case directly verifies real bound/static/class-bound identity, wrong receiver rejection, a real FunctionType with forged attributes, a MethodType wrapping the wrong function, and unclassified expected/actual callable values without hooks.

F's local fresh total is **381 passing tests**, not the author's reported number and not zero-test unittest discovery. No field-hardening skip is counted as a pass.

F independently inspected [CI 42892701258](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42892701258). Both checkout/ref and git-rev verification show exact **1e3776bcc1a9ad11166cc2f504da0797cf306d0e**. Actual Python **3.8.18** ran **170 passed**, 3.88 seconds; actual Python **3.11.18** ran **170 passed**, 4.93 seconds. CI is additional evidence, not a substitute for independent local negative probes.

## Behavior and residual limits

The freshly rerun matrices include all96 combinations of ownership/PRODUCE type, eight task states, capability match/mismatch, default economy/base scheduler; one-shot capabilities are consumed once. REGISTERED has no implicit refresh in lease_next, and stays unchanged; future references and unmatched capabilities remain legal. READY ownership tasks whose required Gap cannot resolve HOLD before prefix; repair PASS, qualification resolution and source reactivation guard reachable gaps before downstream writes. Batch-last scoped Evidence/Artifact/Gap/derived repair/repro/qualification identities reject with zero prefix. Wrong receivers, foreign truth/release, unknown callbacks, repeated/cold restoration and original legacy identity/lease/state errors remain exercised. PASS-dependent qualification remains in its original method location; preflight inspects only the target footprint.

The real bank/N1 and package-source contract tests pass as counted above. The helper is in REQUIRED_PRODUCT_FILES and included source directories. No full Windows bundle was built. Existing Q7 and exact Field-start prerequisites remain required. Bank TruthRuntime construction may touch mtime despite byte equality. Direct raw scheduler/planner/session/append, upstream writers, cross-process stale projections and concurrent writes remain disclosed residuals. The component grants no Host approval, Scope authority, formal binding creation, typed model/reader preservation, PostgreSQL admission/008, global writer fence or Human/NodeGate bypass. A must run the concentrated full integration regression on its resulting exact HEAD. Native DSH and Windows/offline field acceptance remain outstanding.

## New independent probe

Run from this exact source: `python3 -m pytest /tmp/f_hold_1e_independent.py -q -p no:cacheprovider`.

```python
import os,sys,copy,types
sys.path[:0]=[os.getcwd(),os.path.join(os.getcwd(),'tests')]
import pytest
from rc6_runtime.truth import TruthRuntime
from test_rc7_unadmitted_scope_hold import control,task
from rc7_runtime.unadmitted_scope_guard import _bound

CASES=[('outer','start'),('inner','start'),('inner','_task_from_row'),('planner','plan'),('router','route'),('critical','_assess'),('semantics','resolve'),('selector','plan'),('policy','is_working_day')]
@pytest.mark.parametrize('where,name',CASES)
@pytest.mark.parametrize('spoof',[False,True])
def test_zero_attribute_probe_unknown_callable(tmp_path,where,name,spoof):
 t=TruthRuntime(tmp_path/'r1');c=control(t);task(c);before=t.store.path.read_bytes();snapshot=copy.deepcopy(t.projection.snapshot());calls=[]
 obj={'outer':c.scheduler,'inner':c.scheduler.delegate,'planner':c.gap_planner,'router':c.gap_planner.router,'critical':c.critical_path,'semantics':c.schedule_semantics,'selector':c.scheduler.selector,'policy':c.scheduler.selector.cost_window_config}[where];original=getattr(obj,name)
 class Unknown:
  def __getattribute__(self,field):
   calls.append('getattribute:'+field)
   if spoof and field=='__func__':return getattr(original,'__func__',original)
   if spoof and field=='__self__':return obj
   raise AssertionError('unknown callable probed '+field)
  def __call__(self,*args,**kwargs):calls.append('call');raise AssertionError('unknown callable executed')
 object.__setattr__(obj,name,Unknown())
 with pytest.raises(RuntimeError,match='MISSION_SCOPE_TARGET_UNRESOLVED'):c.lease_next(worker_ref='w',capabilities=[])
 assert calls==[];assert t.store.path.read_bytes()==before;assert t.projection.snapshot()==snapshot
 assert TruthRuntime(t.store.path).projection.snapshot()==snapshot

def test_intrinsic_bound_and_static_identity():
 class C:
  def f(self):pass
  @staticmethod
  def s():pass
  @classmethod
  def k(cls):pass
 a=C();b=C()
 assert _bound(a.f,C.f,a);assert not _bound(b.f,C.f,a)
 assert _bound(C.s,C.s,None,static=True);assert not _bound(C.s,C.s,a)
 assert _bound(C.k,C.k.__func__,C)
 def fake():pass
 fake.__func__=C.f;fake.__self__=a
 assert not _bound(fake,C.f,a)
 assert not _bound(types.MethodType(fake,a),C.f,a)
 class P:
  def __getattribute__(self,n):raise AssertionError('probe '+n)
 assert not _bound(P(),C.f,a)
 assert not _bound(P(),C.s,None,static=True)
 assert not _bound(a.f,P(),a)
```
