"""Local negative Scope guard, not a global writer fence or binding admission.

Only current in-process projections are inspected. Raw/scheduler/other-process
writers remain outside this guard. No tools/workbench, Host or PG dependency.
"""
from functools import wraps
from types import MethodType, FunctionType
import inspect

from .control_plane import TaskScheduler, GapRepairPlanner, ControlPlaneError, _stable_id
from .gap_router import GapRouter
from .rc72_scheduler_integration import EconomyAwareTaskSchedulerAdapter
from .rc72_critical_path import CanonicalCriticalPathResolver
from .rc72_schedule_semantics import WorkScheduleSemanticsService
from .rc72_economy_scheduler import EconomyAwareReadySelector
from .rc72_model_economy import BankCostWindowConfig

from .models import MISSION_SCOPE_FIELDS as RESERVED, MISSION_SCOPE_HOLD as HOLD
from .models import is_mission_object, require_unbound_mission
UNRESOLVED = 'MISSION_SCOPE_TARGET_UNRESOLVED'
_SCHEDULER = {name: getattr(TaskScheduler, name) for name in vars(TaskScheduler)
              if name != '__init__' and callable(getattr(TaskScheduler, name))}
_PLANNER = {name: getattr(GapRepairPlanner, name) for name in vars(GapRepairPlanner)
            if name != '__init__' and callable(getattr(GapRepairPlanner, name))}
from .control_plane import load_execution_terminal_receipt as _TERMINAL_LOAD

_ROUTE = GapRouter.route
_ADAPTER = {name: getattr(EconomyAwareTaskSchedulerAdapter, name)
            for name in vars(EconomyAwareTaskSchedulerAdapter)
            if name != '__init__' and callable(getattr(EconomyAwareTaskSchedulerAdapter, name))}

_SCHEDULER_DESCRIPTORS = {name: inspect.getattr_static(TaskScheduler, name) for name in _SCHEDULER}
_PLANNER_DESCRIPTORS = {name: inspect.getattr_static(GapRepairPlanner, name) for name in _PLANNER}
_ADAPTER_DESCRIPTORS = {name: inspect.getattr_static(EconomyAwareTaskSchedulerAdapter, name) for name in _ADAPTER}
_ROUTE_DESCRIPTOR = inspect.getattr_static(GapRouter, 'route')


# Exact held-object call chain used by the default economy lease. No descriptor
# is invoked while validating this closure; raw R1/global program replacement is
# deliberately not claimed to be fenced here.
_RESOLVER_CLOSURE = {name: inspect.getattr_static(CanonicalCriticalPathResolver, name)
                     for name in ('resolve', '_assess', '_unsafe', '_cycle_node', '_depends_transitively')}
_SEMANTICS_CLOSURE = {'resolve': inspect.getattr_static(WorkScheduleSemanticsService, 'resolve')}
_SELECTOR_CLOSURE = {'plan': inspect.getattr_static(EconomyAwareReadySelector, 'plan')}
_POLICY_CLOSURE = {'is_working_day': inspect.getattr_static(BankCostWindowConfig, 'is_working_day')}


def _known_object(value, cls, methods, error):
    if type(value) is not cls:
        raise error(UNRESOLVED)
    for name, descriptor in methods.items():
        if name in vars(value) or inspect.getattr_static(cls, name) is not descriptor:
            raise error(UNRESOLVED)
        actual = getattr(value, name)
        if type(descriptor) is staticmethod:
            valid = _bound(actual, descriptor.__func__, None, static=True)
        elif type(descriptor) is classmethod:
            valid = _bound(actual, descriptor.__func__, cls)
        else:
            valid = _bound(actual, descriptor, value)
        if not valid:
            raise error(UNRESOLVED)


def _bound(actual, method, receiver, static=False):
    # Intrinsic concrete types first: never introspect an unclassified callable.
    # Python FunctionType/MethodType cannot be impersonated by __getattr__.
    if type(method) is not FunctionType:
        return False
    if static:
        return type(actual) is FunctionType and actual is method
    return (type(actual) is MethodType and actual.__func__ is method and
            actual.__self__ is receiver)


def _expected_method(value, cls, name, method, descriptor, error):
    if inspect.getattr_static(cls, name) is not descriptor:
        raise error(UNRESOLVED)
    actual = getattr(value, name)
    if not _bound(actual, method, value, static=type(descriptor) is staticmethod):
        raise error(UNRESOLVED)



def reject_reserved(value, error=ControlPlaneError):
    if is_mission_object(value):
        require_unbound_mission(value, error)
        return
    values = value if isinstance(value, dict) else vars(value)
    if RESERVED.intersection(values):
        raise error(HOLD)


def check_missions(truth, mission_ids, error=ControlPlaneError, allow_new=()):
    for mission_id in sorted(set(mission_ids)):
        if not isinstance(mission_id, str) or not mission_id.strip():
            raise error(UNRESOLVED)
        rows = truth.query('rc7_mission', mission_id=mission_id)
        if not rows and mission_id in allow_new:
            continue
        if len(rows) != 1:
            raise error(UNRESOLVED)
        reject_reserved(rows[0], error)


def _trusted_components(control, error, leasing=False):
    scheduler = control.scheduler
    if type(scheduler) is EconomyAwareTaskSchedulerAdapter:
        if type(scheduler.delegate) is not TaskScheduler:
            raise error(UNRESOLVED)
        if any(name in vars(scheduler) for name in set(_SCHEDULER) | set(_ADAPTER)):
            raise error(UNRESOLVED)
        if (scheduler.truth is not control.truth or scheduler.release_id != control.release_id or
                EconomyAwareTaskSchedulerAdapter.__getattr__ is not _ADAPTER['__getattr__']):
            raise error(UNRESOLVED)
        for name, method in _ADAPTER.items():
            _expected_method(scheduler, EconomyAwareTaskSchedulerAdapter, name, method, _ADAPTER_DESCRIPTORS[name], error)
        for name, method in _SCHEDULER.items():
            if name not in _ADAPTER:
                descriptor = _SCHEDULER_DESCRIPTORS[name]
                if inspect.getattr_static(TaskScheduler, name) is not descriptor:
                    raise error(UNRESOLVED)
                if not _bound(getattr(scheduler, name), method, scheduler.delegate, static=type(descriptor) is staticmethod):
                    raise error(UNRESOLVED)
        if leasing:
            resolver = scheduler.descriptor_resolver
            if type(resolver) is not MethodType:
                raise error(UNRESOLVED)
            owner = resolver.__self__
            _known_object(owner, CanonicalCriticalPathResolver, _RESOLVER_CLOSURE, error)
            semantics = owner.schedule_semantics
            _known_object(semantics, WorkScheduleSemanticsService, _SEMANTICS_CLOSURE, error)
            _known_object(scheduler.selector, EconomyAwareReadySelector, _SELECTOR_CLOSURE, error)
            _known_object(scheduler.selector.cost_window_config, BankCostWindowConfig, _POLICY_CLOSURE, error)
            if (type(owner) is not CanonicalCriticalPathResolver or
                    resolver.__func__ is not _RESOLVER_CLOSURE['resolve'] or
                    type(scheduler.selector) is not EconomyAwareReadySelector or
                    'plan' in vars(scheduler.selector) or
                    owner.truth is not control.truth or owner.release_id != control.release_id or
                    owner.schedule_semantics.truth is not control.truth or
                    owner.schedule_semantics.release_id != control.release_id or
                    owner is not getattr(control, 'critical_path', None) or
                    owner.schedule_semantics is not getattr(control, 'schedule_semantics', None)):
                raise error(UNRESOLVED)
        scheduler = scheduler.delegate
    if type(scheduler) is not TaskScheduler or type(control.gap_planner) is not GapRepairPlanner:
        raise error(UNRESOLVED)
    if (scheduler.truth is not control.truth or scheduler.release_id != control.release_id or
            control.gap_planner.truth is not control.truth or
            control.gap_planner.release_id != control.release_id or
            control.gap_planner.scheduler is not control.scheduler):
        raise error(UNRESOLVED)
    from . import control_plane as original_control
    if original_control.load_execution_terminal_receipt is not _TERMINAL_LOAD:
        raise error(UNRESOLVED)
    for name, method in _SCHEDULER.items():
        _expected_method(scheduler, TaskScheduler, name, method, _SCHEDULER_DESCRIPTORS[name], error)
    for name, method in _PLANNER.items():
        _expected_method(control.gap_planner, GapRepairPlanner, name, method, _PLANNER_DESCRIPTORS[name], error)
    if type(control.gap_planner.router) is not GapRouter:
        raise error(UNRESOLVED)
    _expected_method(control.gap_planner.router, GapRouter, 'route', _ROUTE, _ROUTE_DESCRIPTOR, error)


class Targets:
    def __init__(self, truth, error):
        self.truth, self.error, self.ids = truth, error, set()

    def mission(self, value):
        if not isinstance(value, str) or not value.strip():
            raise self.error(UNRESOLVED)
        self.ids.add(value)

    def old(self, kind, field, identity, required=False):
        if not isinstance(identity, str) or not identity.strip():
            raise self.error(UNRESOLVED)
        rows = self.truth.query(kind, **{field: identity})
        if len(rows) > 1 or (required and not rows):
            raise self.error(UNRESOLVED)
        if rows:
            self.mission(rows[0].get('mission_id'))
            return rows[0]
        return None

    def entity(self, value):
        if value is None:
            return
        if isinstance(value, (list, tuple)):
            for item in value:
                self.entity(item)
            return
        if not hasattr(value, '__dict__'):
            return
        row = vars(value)
        if 'mission_id' in row:
            self.mission(row['mission_id'])
        for field, kind in (('task_id','rc7_task'),('gap_id','rc7_gap'),('evaluation_id','rc7_evaluation'),
                            ('defect_id','rc7_defect'),('artifact_id','rc7_artifact'),('evidence_id','rc7_evidence')):
            if row.get(field):
                self.old(kind, field, row[field])
        for gap_id in row.get('gap_refs', ()):
            self.old('rc7_gap', 'gap_id', gap_id)
        if row.get('source_gap_id'):
            self.old('rc7_gap', 'gap_id', row['source_gap_id'])
        for field in ('artifacts','evidence'):
            if field in row:
                self.entity(row[field])

    def task(self, task_id, required=True, required_gaps=False):
        row = self.old('rc7_task', 'task_id', task_id, required)
        if row:
            for gap_id in row.get('gap_refs', []):
                self.old('rc7_gap', 'gap_id', gap_id, required=required_gaps)
        return row

    def batch(self, mission_id, leasing_caps=None):
        # Ready refresh and source reactivation operate only within this Mission.
        for row in self.truth.query('rc7_task', mission_id=mission_id):
            needs_gaps = (leasing_caps is not None and row.get('state') == 'READY' and
                          row.get('task_type') in ('REPAIR', 'QUALIFY_DEFECT') and
                          set(row.get('required_capabilities', ())).issubset(leasing_caps))
            self.task(row['task_id'], required_gaps=needs_gaps)
        for row in self.truth.query('rc7_gap', mission_id=mission_id):
            self.old('rc7_gap', 'gap_id', row['gap_id'], True)

    def reactivation(self, mission_id, repaired_gap_ids):
        repaired = set(repaired_gap_ids)
        for row in self.truth.query('rc7_task', mission_id=mission_id):
            if (row.get('task_type') != 'REPAIR' and
                    row.get('state') in ('REPAIR_REQUIRED', 'BLOCKED') and
                    repaired.intersection(row.get('gap_refs', ()))):
                self.task(row['task_id'], required_gaps=True)

    def planned_gap(self, control, gap, evaluation=None):
        # Default router/source inspection is read-only; never execute plan().
        decision = control.gap_planner.router.route(gap)
        if decision.target_node == 'HUMAN_GATE':
            return
        if gap.category == 'PRODUCT_DEFECT' and decision.target_node == 'DEFECT':
            from .control_plane import EXECUTION_TERMINAL_KIND
            artifacts = set()
            receipts = []
            for evidence_id in gap.evidence_refs:
                rows = self.truth.query('rc7_evidence', evidence_id=evidence_id)
                if len(rows) == 1 and rows[0].get('kind') == EXECUTION_TERMINAL_KIND:
                    receipts.append(evidence_id)
            if receipts:
                for receipt_id in receipts:
                    payload = _TERMINAL_LOAD(self.truth, mission_id=gap.mission_id, receipt_id=receipt_id)
                    artifact_id = payload.get('execution_artifact_id')
                    if not isinstance(artifact_id, str) or not artifact_id:
                        raise self.error(UNRESOLVED)
                    artifacts.add(artifact_id)
            else:
                candidates = list(self.truth.query('rc7_evaluation', mission_id=gap.mission_id))
                if evaluation is not None:
                    candidates.append(vars(evaluation))
                for candidate in candidates:
                    dimensions = candidate.get('dimensions', {})
                    if (candidate.get('node') == 'EXECUTION' and gap.gap_id in candidate.get('gap_refs', ()) and
                            dimensions.get('failure_class') == 'PRODUCT' and dimensions.get('test_result') == 'FAIL'):
                        artifacts.update(candidate.get('artifact_refs', ()))
            if not artifacts:
                raise self.error(UNRESOLVED)
            for source_artifact in artifacts:
                row = self.old('rc7_artifact', 'artifact_id', source_artifact, True)
                self.task(row.get('producer_task_id'))
                self.task(_stable_id('TASK-DEFECT-REPRO', gap.mission_id, gap.gap_id, source_artifact), False)
            self.task(_stable_id('TASK-DEFECT', gap.mission_id, gap.gap_id, 'DEFECT'), False)
        else:
            self.task(_stable_id('TASK-REPAIR', gap.mission_id, gap.gap_id, decision.target_node), False)


def protected(method):
    """Preflight all local write targets before entering the mutating method."""
    signature = inspect.signature(method)
    @wraps(method)
    def guarded(self, *args, **kwargs):
        from .closed_loop_control import ClosedLoopControlError
        error = ClosedLoopControlError
        bound = signature.bind(self, *args, **kwargs)
        for sequence in ('gaps', 'repaired_gap_ids'):
            if sequence in bound.arguments:
                bound.arguments[sequence] = tuple(bound.arguments[sequence])
        values = bound.arguments
        name = method.__name__
        # Preserve existing early identity/missing/owner errors without writes.
        if name == 'register_task' and values['task'].mission_id != self.mission_id:
            raise error('TASK_MISSION_MISMATCH')
        if name in ('register_task','refresh_ready','lease_next','start','submit_worker_output',
                    'accept_evaluation','accept_defect_resolution','_resolve_source_gaps','_reactivate_source_tasks'):
            _trusted_components(self, error, leasing=name == 'lease_next')
        if name in ('start','accept_evaluation','accept_defect_resolution'):
            task = self.scheduler.task(values['task_id'])
            if name == 'start' and task.lease_owner != values['worker_ref']:
                raise ControlPlaneError('TASK_LEASE_OWNER_MISMATCH')
        if name == 'submit_worker_output':
            output = values['output']
            task = self.scheduler.task(output.task_id)
            if task.state.value != 'RUNNING':
                raise ControlPlaneError('TASK_NOT_RUNNING')
            if task.lease_owner != output.worker_ref:
                raise ControlPlaneError('TASK_LEASE_OWNER_MISMATCH')
        if name == 'lease_next':
            bound.arguments['capabilities'] = tuple(bound.arguments['capabilities'])
        targets = Targets(self.truth, error)
        targets.mission(self.mission_id)
        for key, value in values.items():
            if key != 'self':
                targets.entity(value)
        if 'mission' in values:
            reject_reserved(values['mission'], error)
        if 'task_id' in values:
            targets.task(values['task_id'])
        if 'output' in values:
            targets.task(values['output'].task_id)
        if name in ('register_task','refresh_ready','lease_next','accept_evaluation',
                    'accept_defect_resolution','_resolve_source_gaps','_reactivate_source_tasks'):
            targets.batch(self.mission_id, set(values['capabilities']) if name == 'lease_next' else None)
        if name == '_resolve_source_gaps':
            targets.task(values['task'].task_id)
        if name == '_reactivate_source_tasks':
            for gap_id in values['repaired_gap_ids']:
                targets.old('rc7_gap','gap_id',gap_id)
            targets.reactivation(self.mission_id, values['repaired_gap_ids'])
        if name == 'accept_defect_resolution':
            targets.task(values['task_id'], required_gaps=True)
        if name == 'accept_evaluation':
            evaluation = values['evaluation']
            task = self.scheduler.task(values['task_id'])
            if task.task_type == 'REPAIR' and evaluation.result.value == 'PASS':
                targets.task(task.task_id, required_gaps=True)
                targets.reactivation(self.mission_id, task.gap_refs)
            if (task.state.value == 'OUTPUT_PRODUCED' and
                    evaluation.mission_id == task.mission_id and evaluation.node == task.node and
                    evaluation.evaluator_ref != task.lease_owner and
                    set(evaluation.gap_refs) == {gap.gap_id for gap in values.get('gaps', ())} and
                    evaluation.result.value in ('PASS', 'REPAIR_REQUIRED', 'BLOCKED')):
                for gap in values.get('gaps', ()):
                    targets.planned_gap(self, gap, evaluation)
        check_missions(self.truth, targets.ids, error)
        return method(*bound.args, **bound.kwargs)
    return guarded
