"""Real disposable R1 regression for local negative guard, never Field evidence."""
import copy
from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import Mission, Task, Gap, GapSeverity, Evaluation, EvaluationResult, Evidence
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane, ClosedLoopControlError
from rc7_runtime.control_plane import WorkerOutput
from rc7_runtime.truth_overlay import append_entity
from rc7_runtime.bank_mission import start_or_resume, BankMissionError
from rc7_runtime.unadmitted_scope_guard import HOLD, UNRESOLVED


def control(truth, name='M1'):
    return ClosedLoopControlPlane.bootstrap(truth, Mission(name, 'R', name))


def scope(truth, mission='M1', key='project_id', value=None):
    row = truth.query('rc7_mission', mission_id=mission)[0]
    row[key] = value
    row['artifact_version'] += 1
    truth.append_atomic('RC7_MISSION_UPSERTED', row)


def task(c, identity='T1'):
    value = Task(identity, c.mission_id, 'TEST_DESIGN', 'PRODUCE', 'valid work')
    c.register_task(value)
    return value


def gap(identity='G1', mission='M1'):
    return Gap(identity, mission, 'TEST_DESIGN', 'DESIGN_INSUFFICIENT', GapSeverity.HIGH,
               'TEST_DESIGN', 'missing coverage')


def unchanged(truth, call, *inputs, code=HOLD):
    before = truth.store.path.read_bytes()
    projection = copy.deepcopy(truth.projection.snapshot())
    originals = copy.deepcopy(inputs)
    with pytest.raises((RuntimeError, ValueError), match=code):
        call()
    assert truth.store.path.read_bytes() == before
    assert truth.projection.snapshot() == projection
    assert inputs == originals


@pytest.mark.parametrize('key', ['project_id','batch_id','scope_binding'])
@pytest.mark.parametrize('value', [None, False, '', [], {}, {'schema_version':1}])
def test_reserved_presence_and_cold_recovery(tmp_path, key, value):
    truth = TruthRuntime(tmp_path/'r1'); c = control(truth); task(c)
    scope(truth, key=key, value=value)
    mission = Mission('M1','R','M1')
    g = gap()
    calls = [lambda:c.register_task(Task('T2','M1','TEST_DESIGN','PRODUCE','next')),
             c.refresh_ready, lambda:c.lease_next(worker_ref='w',capabilities=iter(())),
             lambda:c._sync_mission(mission), lambda:c._persist_mission(mission),
             lambda:c._persist_gap(g), lambda:c._reactivate_source_tasks(()), c._mission,
             lambda:c.converge_mission(Evaluation('EV','M1','MISSION_EVALUATION',[],EvaluationResult.PASS,'reviewer'))]
    for call in calls:
        unchanged(truth, call, mission, g)
    before = truth.store.path.read_bytes()
    cold = TruthRuntime(truth.store.path)
    with pytest.raises(ClosedLoopControlError, match=HOLD):
        ClosedLoopControlPlane(cold,'R','M1')
    assert truth.store.path.read_bytes() == before


def test_cross_target_public_start_and_private_persist_old_counterexamples(tmp_path):
    truth = TruthRuntime(tmp_path/'r1'); first=control(truth); second=control(truth,'M2')
    task(second,'T2'); assert second.lease_next(worker_ref='w',capabilities=[]).task_id=='T2'
    scope(truth,'M2')
    incoming=Mission('M2','R','M2')
    unchanged(truth,lambda:first.start('T2',worker_ref='w'))
    unchanged(truth,lambda:first._persist_mission(incoming),incoming)
    unchanged(truth,lambda:first._sync_mission(incoming),incoming)


def test_scoped_output_evaluation_and_gap_targets(tmp_path):
    truth=TruthRuntime(tmp_path/'r1'); first=control(truth); second=control(truth,'M2')
    task(second,'T2');second.lease_next(worker_ref='w',capabilities=[]);second.start('T2',worker_ref='w')
    output=WorkerOutput('T2','w')
    scope(truth,'M2')
    unchanged(truth,lambda:first.submit_worker_output(output),output)
    ev=Evaluation('EV','M2','TEST_DESIGN',[],EvaluationResult.PASS,'reviewer')
    unchanged(truth,lambda:first.accept_evaluation('T2',evaluation=ev),ev)
    g=gap('G2','M2'); unchanged(truth,lambda:first._persist_gap(g),g)


def test_last_output_old_target_scoped_no_evidence_prefix(tmp_path):
    truth=TruthRuntime(tmp_path/'r1');first=control(truth);second=control(truth,'M2')
    task(first);first.lease_next(worker_ref='w',capabilities=[]);first.start('T1',worker_ref='w')
    old=Evidence('E2','M2','PROOF','file://source','file://content')
    append_entity(truth,old,release_id='R')
    scope(truth,'M2')
    output=WorkerOutput('T1','w',evidence=(Evidence('E1','M1','PROOF','file://s','file://c'),
                                        Evidence('E2','M1','PROOF','file://s','file://c')))
    unchanged(truth,lambda:first.submit_worker_output(output),output)
    assert truth.query('rc7_evidence',evidence_id='E1') == []


def test_last_gap_target_scoped_no_evaluation_prefix(tmp_path):
    truth=TruthRuntime(tmp_path/'r1');first=control(truth);control(truth,'M2')
    task(first);first.lease_next(worker_ref='w',capabilities=[]);first.start('T1',worker_ref='w')
    first.submit_worker_output(WorkerOutput('T1','w'))
    existing=gap('G2','M2');append_entity(truth,existing,release_id='R')
    scope(truth,'M2')
    gaps=(gap(),gap('G2','M1'))
    ev=Evaluation('EV','M1','TEST_DESIGN',[],EvaluationResult.REPAIR_REQUIRED,'reviewer',gap_refs=['G1','G2'])
    unchanged(truth,lambda:first.accept_evaluation('T1',evaluation=ev,gaps=gaps),ev,gaps)
    assert not truth.query('rc7_evaluation',evaluation_id='EV')


def test_bootstrap_dynamic_vars_and_unknown_target_callback(tmp_path):
    truth=TruthRuntime(tmp_path/'r1')
    for key in ('project_id','batch_id','scope_binding'):
        incoming=Mission('NEW','R','new');setattr(incoming,key,None)
        unchanged(truth,lambda:ClosedLoopControlPlane.bootstrap(truth,incoming),incoming)
    first=control(truth)
    missing=Mission('MISSING','R','missing')
    unchanged(truth,lambda:first._persist_mission(missing),missing,code=UNRESOLVED)
    first.gap_planner.plan=lambda *args,**kwargs:pytest.fail('unknown plan executed')
    unchanged(truth,first.refresh_ready,code=UNRESOLVED)


def test_legacy_wire_unrelated_fields_caps_and_old_errors(tmp_path):
    truth=TruthRuntime(tmp_path/'r1');first=control(truth);second=control(truth,'M2')
    row=truth.query('rc7_mission',mission_id='M1')[0]
    row.update(scope_ref='legacy',namespace='old',diagnostic_score=0.5,artifact_version=row['artifact_version']+1)
    truth.append_atomic('RC7_MISSION_UPSERTED',row)
    task(first);task(second,'T2')
    first.lease_next(worker_ref='w',capabilities=(x for x in ()))
    first.start('T1',worker_ref='w')
    second.lease_next(worker_ref='w',capabilities=[])
    first.start('T2',worker_ref='w') # valid legacy cross-target behavior retained
    assert truth.query('rc7_task',task_id='T2')[0]['state']=='RUNNING'
    with pytest.raises(RuntimeError,match='TASK_MISSION_MISMATCH'):
        first.register_task(Task('X','M2','N1','TEST','wrong controller'))
    with pytest.raises(RuntimeError,match='TASK_LEASE_OWNER_MISMATCH'):
        first.start('T2',worker_ref='other')
    assert not {'project_id','batch_id','scope_binding'} & truth.query('rc7_mission',mission_id='M1')[0].keys()


def test_formal_bank_resume_scope_bytes_unchanged(tmp_path):
    path=tmp_path/'r1'
    start_or_resume(r1_path=str(path),mission_id='M1',release_id='R',goal='goal',graph_version='v1')
    truth=TruthRuntime(path);scope(truth)
    before=path.read_bytes()
    for _ in range(3):
        with pytest.raises(BankMissionError,match=HOLD):
            start_or_resume(r1_path=str(path),mission_id='M1',release_id='R',goal='goal',graph_version='v1')
        assert path.read_bytes()==before


def test_n1_real_dispatch_new_and_existing_receipt_hold(tmp_path):
    from test_rc72_mission_node_dispatch import _truth, _started, COMMIT
    from rc7_runtime.rc72_mission_node_dispatch import N1AutonomousDispatchService
    for existing in (False,True):
        directory=tmp_path/str(existing);directory.mkdir()
        truth=_truth(directory)
        _started(truth,release_id='R',mission_id='M1',batch_id='B1')
        dispatcher=N1AutonomousDispatchService(truth,source_commit=COMMIT)
        if existing:dispatcher.dispatch(release_batch_id='B1')
        else:control(truth)
        scope(truth)
        unchanged(truth,lambda:dispatcher.dispatch(release_batch_id='B1'))


def test_package_source_guard_is_required_without_build():
    from rc7_release.package import REQUIRED_PRODUCT_FILES,SOURCE_DIRS
    assert 'rc7_runtime' in SOURCE_DIRS
    assert 'rc7_runtime/unadmitted_scope_guard.py' in REQUIRED_PRODUCT_FILES
    assert Path('rc7_runtime/unadmitted_scope_guard.py').is_file()


def test_complete_binding_stays_hold_without_codec_authority(tmp_path):
    from test_dsh_workbench_mission_scope_binding_codec import bound
    truth=TruthRuntime(tmp_path/'r1');first=control(truth)
    scope(truth,value=bound()['scope_binding'],key='scope_binding')
    unchanged(truth,first.refresh_ready)


def test_derived_planner_task_scoped_no_gap_or_evaluation_prefix(tmp_path):
    from rc7_runtime.control_plane import _stable_id
    truth=TruthRuntime(tmp_path/'r1');first=control(truth);second=control(truth,'M2')
    task(first);first.lease_next(worker_ref='w',capabilities=[]);first.start('T1',worker_ref='w')
    first.submit_worker_output(WorkerOutput('T1','w'))
    g=gap()
    derived=_stable_id('TASK-REPAIR','M1','G1','TEST_DESIGN')
    task(second,derived);scope(truth,'M2')
    ev=Evaluation('EV','M1','TEST_DESIGN',[],EvaluationResult.REPAIR_REQUIRED,'reviewer',gap_refs=['G1'])
    unchanged(truth,lambda:first.accept_evaluation('T1',evaluation=ev,gaps=(g,)),ev,g)
    assert not truth.query('rc7_gap',gap_id='G1')
    assert not truth.query('rc7_evaluation',evaluation_id='EV')


def test_source_reactivation_cross_gap_target_no_task_prefix(tmp_path):
    truth=TruthRuntime(tmp_path/'r1');first=control(truth);control(truth,'M2')
    append_entity(truth,gap('G2','M2'),release_id='R')
    value=Task('T1','M1','TEST_DESIGN','PRODUCE','work',gap_refs=['G2'])
    first.register_task(value)
    row=truth.query('rc7_task',task_id='T1')[0]
    row.update(state='BLOCKED',artifact_version=row['artifact_version']+1)
    truth.append_atomic('RC7_TASK_UPSERTED',row)
    scope(truth,'M2')
    unchanged(truth,lambda:first._reactivate_source_tasks(('G2',)),value)


def test_raw_scheduler_remains_explicit_residual(tmp_path):
    truth=TruthRuntime(tmp_path/'r1');first=control(truth);task(first)
    first.lease_next(worker_ref='w',capabilities=[]);scope(truth)
    unchanged(truth,lambda:first.start('T1',worker_ref='w'))
    # Disposable fixture proves local negative guard is not a global writer lock.
    first.scheduler.start('T1',worker_ref='w')
    assert truth.query('rc7_task',task_id='T1')[0]['state']=='RUNNING'


def test_scoped_actions_never_reach_writer(tmp_path,monkeypatch):
    truth=TruthRuntime(tmp_path/'r1');first=control(truth);task(first)
    first.lease_next(worker_ref='w',capabilities=[]);scope(truth)
    calls=[]
    def forbidden(*args,**kwargs):
        calls.append((args,kwargs))
        pytest.fail('business writer reached')
    monkeypatch.setattr(truth,'append_atomic',forbidden)
    unchanged(truth,lambda:first.start('T1',worker_ref='w'))
    unchanged(truth,lambda:first._persist_mission(Mission('M1','R','M1')))
    assert calls==[]


@pytest.mark.parametrize('kind',['REPAIR','QUALIFY_DEFECT'])
def test_missing_reachable_gap_before_lease_no_prefix(tmp_path,kind):
    truth=TruthRuntime(tmp_path/'r1');first=control(truth)
    first.register_task(Task('T1','M1','TEST_DESIGN',kind,'work',gap_refs=['MISSING']))
    unchanged(truth,lambda:first.lease_next(worker_ref='w',capabilities=[]),code=UNRESOLVED)
    assert truth.query('rc7_task',task_id='T1')[0]['state']=='READY'


def test_future_gap_refs_not_blindly_required(tmp_path):
    truth=TruthRuntime(tmp_path/'r1');first=control(truth)
    first.register_task(Task('T1','M1','TEST_DESIGN','REPAIR','future',gap_refs=['MISSING'],required_capabilities=['future']))
    first.refresh_ready()  # Neither registration nor ready refresh touches a Gap.
    assert first.lease_next(worker_ref='w',capabilities=iter(())) is None
    assert truth.query('rc7_task',task_id='T1')[0]['state']=='READY'
    # A new legitimate Gap is not required to have an old row.
    incoming=gap();first._persist_gap(incoming)
    assert truth.query('rc7_gap',gap_id='G1')


def test_repair_pass_missing_gap_and_source_reactivation_preflight(tmp_path):
    truth=TruthRuntime(tmp_path/'r1');first=control(truth)
    first.register_task(Task('T1','M1','TEST_DESIGN','REPAIR','work',gap_refs=['MISSING']))
    # Explicit raw scheduler setup is a disclosed residual, not the tested API.
    first.scheduler.lease_next('M1',worker_ref='w',capabilities=[])
    first.start('T1',worker_ref='w');first.submit_worker_output(WorkerOutput('T1','w'))
    ev=Evaluation('EV','M1','TEST_DESIGN',[],EvaluationResult.PASS,'reviewer')
    unchanged(truth,lambda:first.accept_evaluation('T1',evaluation=ev),ev,code=UNRESOLVED)
    source=Task('SOURCE','M1','TEST_DESIGN','PRODUCE','source',gap_refs=['MISSING'])
    first.register_task(source)
    row=truth.query('rc7_task',task_id='SOURCE')[0];row.update(state='BLOCKED',artifact_version=row['artifact_version']+1)
    truth.append_atomic('RC7_TASK_UPSERTED',row)
    unchanged(truth,lambda:first._reactivate_source_tasks(('MISSING',)),source,code=UNRESOLVED)


@pytest.mark.parametrize('method',['register','refresh_ready','ready_tasks','lease_next','lease_task',
                                   'task','start','submit_worker_output','persist_evaluated_task',
                                   '_row','_required_row','_persist_task','_inputs_valid','_task_from_row'])
def test_every_outer_forwarding_override_rejected_without_invocation(tmp_path,method):
    truth=TruthRuntime(tmp_path/'r1');first=control(truth);task(first)
    calls=[]
    def forbidden(*args,**kwargs):
        calls.append(method)
        pytest.fail('unknown outer adapter method invoked')
    setattr(first.scheduler,method,forbidden)
    unchanged(truth,first.refresh_ready,code=UNRESOLVED)
    assert calls==[]


@pytest.mark.parametrize('location',['outer','delegate','planner','router'])
def test_wrong_bound_methods_rejected_for_real_receivers(tmp_path,location):
    a=TruthRuntime(tmp_path/'a');b=TruthRuntime(tmp_path/'b')
    first=control(a);other=control(b);task(first);task(other)
    first.lease_next(worker_ref='w',capabilities=[]);other.lease_next(worker_ref='w',capabilities=[])
    scope(b)
    if location=='outer':first.scheduler.start=other.scheduler.start
    elif location=='delegate':first.scheduler.delegate.start=other.scheduler.delegate.start
    elif location=='planner':first.gap_planner.plan=other.gap_planner.plan
    else:first.gap_planner.router.route=other.gap_planner.router.route
    before=b.store.path.read_bytes();projection=copy.deepcopy(b.projection.snapshot())
    unchanged(a,lambda:first.start('T1',worker_ref='w'),code=UNRESOLVED)
    assert b.store.path.read_bytes()==before and b.projection.snapshot()==projection


@pytest.mark.parametrize('dependency',['delegate','planner','resolver','schedule_semantics'])
def test_same_class_foreign_truth_dependencies_rejected(tmp_path,dependency):
    a=TruthRuntime(tmp_path/'a');b=TruthRuntime(tmp_path/'b')
    first=control(a);other=control(b);task(first);task(other)
    if dependency=='delegate':first.scheduler.delegate=other.scheduler.delegate
    elif dependency=='planner':first.gap_planner=other.gap_planner
    elif dependency=='resolver':first.scheduler.descriptor_resolver=other.critical_path.resolve
    else:first.critical_path.schedule_semantics=other.schedule_semantics
    before=b.store.path.read_bytes()
    unchanged(a,lambda:first.lease_next(worker_ref='w',capabilities=[]),code=UNRESOLVED)
    assert b.store.path.read_bytes()==before


def test_unknown_delegate_is_not_queried_during_adapter_validation(tmp_path):
    truth=TruthRuntime(tmp_path/'r1');first=control(truth);task(first)
    class Tripwire:
        def __getattr__(self,name):
            pytest.fail('unknown delegate queried: '+name)
    first.scheduler.delegate=Tripwire()
    unchanged(truth,first.refresh_ready,code=UNRESOLVED)


def test_missing_gap_defect_resolution_no_prefix(tmp_path):
    truth=TruthRuntime(tmp_path/'r1');first=control(truth)
    first.register_task(Task('T1','M1','DEFECT','QUALIFY_DEFECT','work',gap_refs=['MISSING']))
    first.scheduler.lease_next('M1',worker_ref='w',capabilities=[])
    first.start('T1',worker_ref='w');first.submit_worker_output(WorkerOutput('T1','w'))
    # Missing target must be resolved before this action's downstream writes.
    class DefectInput:
        mission_id='M1'
    ev=Evaluation('EV','M1','DEFECT',[],EvaluationResult.PASS,'reviewer')
    unchanged(truth,lambda:first.accept_defect_resolution('T1',defect=DefectInput(),evaluation=ev),ev,code=UNRESOLVED)


def test_nonownership_task_future_gap_ref_does_not_block_legal_lease(tmp_path):
    truth=TruthRuntime(tmp_path/'r1');first=control(truth)
    first.register_task(Task('T1','M1','TEST_DESIGN','PRODUCE','work',gap_refs=['FUTURE']))
    assert first.lease_next(worker_ref='w',capabilities=[]).task_id=='T1'
    assert truth.query('rc7_task',task_id='T1')[0]['state']=='LEASED'


@pytest.mark.parametrize('where,method',[
    ('critical','resolve'),('critical','_assess'),('critical','_unsafe'),
    ('critical','_cycle_node'),('critical','_depends_transitively'),
    ('semantics','resolve'),('selector','plan'),('policy','is_working_day')])
def test_default_resolver_held_closure_unknown_callbacks_never_run(tmp_path,where,method):
    truth=TruthRuntime(tmp_path/'r1');first=control(truth);task(first);calls=[]
    target={'critical':first.critical_path,'semantics':first.schedule_semantics,
            'selector':first.scheduler.selector,'policy':first.scheduler.selector.cost_window_config}[where]
    original=getattr(target,method)
    def callback(*args,**kwargs):
        calls.append((where,method))
        return original(*args,**kwargs)
    object.__setattr__(target,method,callback)
    unchanged(truth,lambda:first.lease_next(worker_ref='w',capabilities=[]),code=UNRESOLVED)
    assert calls==[]


@pytest.mark.parametrize('where,method',[('critical','resolve'),('critical','_assess'),('semantics','resolve'),('selector','plan'),('policy','is_working_day')])
def test_resolver_closure_wrong_receiver_not_invoked(tmp_path,where,method):
    a=TruthRuntime(tmp_path/'a');b=TruthRuntime(tmp_path/'b')
    first=control(a);other=control(b);task(first);task(other)
    def objects(c):
        return {'critical':c.critical_path,'semantics':c.schedule_semantics,
                'selector':c.scheduler.selector,'policy':c.scheduler.selector.cost_window_config}
    object.__setattr__(objects(first)[where],method,getattr(objects(other)[where],method))
    before=b.store.path.read_bytes();projection=copy.deepcopy(b.projection.snapshot())
    unchanged(a,lambda:first.lease_next(worker_ref='w',capabilities=[]),code=UNRESOLVED)
    assert b.store.path.read_bytes()==before and b.projection.snapshot()==projection


@pytest.mark.parametrize('dependency',['semantics','policy','descriptor'])
def test_unknown_resolver_held_object_not_probed(tmp_path,dependency):
    truth=TruthRuntime(tmp_path/'r1');first=control(truth);task(first);calls=[]
    class Tripwire:
        def __getattr__(self,name):
            calls.append(name)
            pytest.fail('unknown dependency probed')
        def __call__(self,*args,**kwargs):
            calls.append('call')
            pytest.fail('unknown descriptor executed')
    if dependency=='semantics':first.critical_path.schedule_semantics=Tripwire()
    elif dependency=='policy':first.scheduler.selector.cost_window_config=Tripwire()
    else:first.scheduler.descriptor_resolver=Tripwire()
    unchanged(truth,lambda:first.lease_next(worker_ref='w',capabilities=[]),code=UNRESOLVED)
    assert calls==[]


def test_unknown_class_descriptor_is_not_executed(tmp_path,monkeypatch):
    from rc7_runtime.rc72_critical_path import CanonicalCriticalPathResolver
    truth=TruthRuntime(tmp_path/'r1');first=control(truth);task(first);calls=[]
    def descriptor(instance):
        calls.append(True)
        pytest.fail('unknown property executed')
    monkeypatch.setattr(CanonicalCriticalPathResolver,'_assess',property(descriptor))
    unchanged(truth,lambda:first.lease_next(worker_ref='w',capabilities=[]),code=UNRESOLVED)
    assert calls==[]
