"""ReleaseBatch-rooted product driver; canonical services own every decision.

No stage callbacks, synthetic PASS, or driver-owned completion flags. A missing
production route is an explicit construction hold, never a completed Mission.
"""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import re

from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from .models import ContractError
from .closed_loop_control import ClosedLoopControlPlane
from .dsh_requirement_evaluator import DshRequirementEvaluator
from .rc72_authority import RC72AuthorityRuntime
from .rc72_domain import AutonomousMissionNode
from .rc72_field_mission_start import ReleaseBatchFieldMissionLauncher
from .rc72_mission_node_dispatch import N1AutonomousDispatchService
from .rc72_mission_node_assignment import N1AgentTeamsAssignmentService
from .rc72_n1_strict_pipeline import N1StrictPipelineService, N1StrictDshHandoffService
from .rc72_n1_strict_reality_gate import N1StrictRealityGateService
from .rc72_n2_requirement_dispatch import N2RequirementDispatchService
from .rc72_n2_requirement_assignment import N2RequirementAssignmentService
from .rc72_n2_candidate_guard import N2GovernedRequirementHandoffService
from .rc72_n2_requirement_promotion import N2RequirementCandidatePromotionService
from .rc72_n2_requirement_review import N2RequirementReviewService
from .rc72_n2_completion import N2DeliveryGateService
from .rc72_n3_pipeline import N3PipelineService
from .rc72_n3_completion import N3DeliveryGateService
from .rc72_n4_pipeline import N4PipelineService
from .rc72_n4_parent_guard import N4ParentScopedDeliveryGateService
from .rc72_n5_pipeline import N5PipelineService
from .rc72_n5_workitem_acceptance import N5OwnedWorkItemGateService
from .rc72_n6_pipeline import N6PipelineService
from .rc72_n7_pipeline import N7PipelineService
from .rc72_n8_product_recovery import NativeN8ProductRecoveryService
from .rc72_n9_accepted_scope import AcceptedScopeN9Service
from .rc72_expected_scope_input import ExpectedScopeInputService
from .rc72_n10_control import NativeN10ControlService


@contextmanager
def _driver_lock(truth, batch_id):
    """One controller per ledger + exact batch, including separate processes."""
    if not isinstance(batch_id, str) or not batch_id.strip():
        raise ContractError('RC72_RELEASE_DRIVER_BATCH_REQUIRED')
    digest = hashlib.sha256(batch_id.encode()).hexdigest()
    path = Path(truth.store.path).resolve()
    lock = path.parent / ('.' + path.name + '.release-driver-' + digest + '.lock')
    with lock.open('a+b') as handle:
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ContractError('RC72_RELEASE_DRIVER_ALREADY_RUNNING') from exc
        try:
            yield
        finally:
            if os.name == 'nt':
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def release_batch_status(truth, *, source_commit, release_batch_id):
    if not isinstance(source_commit, str) or not re.fullmatch('[0-9a-f]{40}', source_commit):
        raise ContractError('RC72_RELEASE_DRIVER_EXACT_SOURCE_REQUIRED')
    truth.rebuild_projection()
    batches = truth.query('rc72_release_batch', release_batch_id=release_batch_id)
    if len(batches) != 1:
        raise ContractError('RC72_RELEASE_DRIVER_TRUTH_NOT_UNIQUE:rc72_release_batch')
    batch = batches[0]
    rows = truth.query('rc72_mission_node', mission_id=batch['mission_id'])
    by_type = {row['node_type']: row for row in rows}
    if len(by_type) != len(rows):
        raise ContractError('RC72_RELEASE_DRIVER_DUPLICATE_NODE')
    nodes = [by_type[node.value] for node in AutonomousMissionNode.ordered() if node.value in by_type]
    return dict(release_batch_id=release_batch_id, mission_id=batch['mission_id'], release_id=batch['release_id'],
        source_commit=source_commit, nodes=nodes, field_verified=False, bank_final=False)



class ReleaseBatchDriver:
    def __init__(self, truth, *, source_commit, n1_launcher, n1_tools,
                 n2_launcher, n2_tools, n2_evaluator, n3_pipeline=None, n4_pipeline=None, n5_pipeline=None, n7_pipeline=None, n8_pipeline=None, n9_pipeline=None, expected_scope=None, n10_pipeline=None, bank_pip_mirror=None):
        if not isinstance(source_commit, str) or not re.fullmatch('[0-9a-f]{40}', source_commit):
            raise ContractError('RC72_RELEASE_DRIVER_EXACT_SOURCE_REQUIRED')
        if not isinstance(n2_evaluator, DshRequirementEvaluator):
            raise ContractError('RC72_RELEASE_DRIVER_INDEPENDENT_REVIEWER_REQUIRED')
        for launcher in (n1_launcher, n2_launcher, n2_evaluator.launcher):
            if (not isinstance(launcher, DshHeadlessWorkerLauncher) or launcher.truth is not truth
                    or not isinstance(launcher.authority, RC72AuthorityRuntime)):
                raise ContractError('RC72_RELEASE_DRIVER_NATIVE_WORKER_REQUIRED')
        self.truth, self.source_commit = truth, source_commit
        self.bank_pip_mirror=bank_pip_mirror
        self.n1_launcher, self.n2_launcher = n1_launcher, n2_launcher
        if not isinstance(n1_tools, (list, tuple)) or not isinstance(n2_tools, (list, tuple)):
            raise ContractError('RC72_RELEASE_DRIVER_EXACT_TOOLS_REQUIRED')
        self.n1_tools, self.n2_tools = tuple(n1_tools), tuple(n2_tools)
        for tools in (self.n1_tools, self.n2_tools, n2_evaluator.allowed_tools):
            if not tools or len(set(tools)) != len(tools) or any(not isinstance(t, str) or not t.strip() or '*' in t for t in tools):
                raise ContractError('RC72_RELEASE_DRIVER_EXACT_TOOLS_REQUIRED')
        self.n2_evaluator = n2_evaluator
        if n3_pipeline is not None and (not isinstance(n3_pipeline, N3PipelineService)
                or n3_pipeline.truth is not truth or n3_pipeline.source_commit != source_commit):
            raise ContractError('RC72_RELEASE_DRIVER_N3_PIPELINE_SCOPE_MISMATCH')
        self.n3_pipeline = n3_pipeline
        if n4_pipeline is not None and (not isinstance(n4_pipeline, N4PipelineService)
                or n4_pipeline.truth is not truth or n4_pipeline.source_commit != source_commit):
            raise ContractError('RC72_RELEASE_DRIVER_N4_PIPELINE_SCOPE_MISMATCH')
        self.n4_pipeline = n4_pipeline
        if n5_pipeline is not None and (not isinstance(n5_pipeline, N5PipelineService)
                or n5_pipeline.truth is not truth or n5_pipeline.source_commit != source_commit):
            raise ContractError('RC72_RELEASE_DRIVER_N5_PIPELINE_SCOPE_MISMATCH')
        self.n5_pipeline = n5_pipeline
        if n7_pipeline is not None and (not isinstance(n7_pipeline,N7PipelineService)
                or n7_pipeline.truth is not truth or n7_pipeline.source_commit!=source_commit):
            raise ContractError('RC72_RELEASE_DRIVER_N7_PIPELINE_SCOPE_MISMATCH')
        self.n7_pipeline=n7_pipeline
        self.n8_pipeline=n8_pipeline
        self._assert_n8_scope()
        self.n9_pipeline=n9_pipeline
        self._assert_n9_scope()
        self.expected_scope=expected_scope
        self._assert_expected_scope()
        self.n10_pipeline=n10_pipeline
        self._assert_n10_scope()

    def _assert_expected_scope(self,release_batch_id=None):
        policy=self.expected_scope
        if (policy is None and release_batch_id is not None
                and self.truth.query('rc72_expected_scope_input',release_batch_id=release_batch_id)):
            raise ContractError('RC72_RELEASE_DRIVER_EXPECTED_SCOPE_PROVIDER_REQUIRED')
        if policy is not None and (not isinstance(policy,ExpectedScopeInputService)
                or policy.truth is not self.truth or policy.source_commit!=self.source_commit
                or policy.pipeline.truth is not self.truth or policy.pipeline.source_commit!=self.source_commit
                or tuple(policy.pipeline.handoff_service.allowed_tools)!=self.n1_tools
                or policy.pipeline.handoff_service.launcher is not self.n1_launcher):
            raise ContractError('RC72_RELEASE_DRIVER_EXPECTED_SCOPE_MISMATCH')

    def _assert_n10_scope(self,release_batch_id=None):
        pipeline=self.n10_pipeline
        if (pipeline is None and release_batch_id is not None
                and self.truth.query('rc72_libra_measurement',release_batch_id=release_batch_id)):
            raise ContractError('RC72_RELEASE_DRIVER_NATIVE_N10_PROVIDER_REQUIRED')
        if pipeline is not None and (not isinstance(pipeline,NativeN10ControlService)
                or pipeline.truth is not self.truth or pipeline.source_commit!=self.source_commit
                or pipeline.n9 is not self.n9_pipeline or pipeline.expected_scope is not self.expected_scope
                or pipeline.n9.pipeline is not self.n7_pipeline):
            raise ContractError('RC72_RELEASE_DRIVER_N10_PIPELINE_SCOPE_MISMATCH')

    def _assert_n8_scope(self):
        n8=self.n8_pipeline
        if n8 is not None and (not isinstance(n8,NativeN8ProductRecoveryService)
                or self.n7_pipeline is None or n8.n7 is not self.n7_pipeline
                or n8.diagnosis is not self.n7_pipeline.diagnosis
                or n8.boundary.diagnosis is not n8.diagnosis
                or n8.boundary.preparation is not self.n7_pipeline.preparation
                or n8.boundary.cleanup.adapters!=self.n7_pipeline.cleanup.adapters
                or n8.continuation.diagnosis is not n8.diagnosis
                or n8.continuation.preparation is not self.n7_pipeline.preparation
                or (n8.capability_broker is not None and (
                    n8.capability_broker.truth is not self.truth
                    or n8.capability_broker.release_id != self.n7_pipeline.release_id
                    or n8.capability_broker.authority is not self.n7_pipeline.preparation.authority))
                or n8.truth is not self.truth
                or n8.source_commit!=self.source_commit
                or n8.release_id!=self.n7_pipeline.release_id):
            raise ContractError('RC72_RELEASE_DRIVER_N8_NATIVE_SCOPE_MISMATCH')

    def _assert_n9_scope(self):
        n9=self.n9_pipeline
        if n9 is not None and (not isinstance(n9,AcceptedScopeN9Service) or n9.pipeline is not self.n7_pipeline
                or n9.truth is not self.truth or n9.source_commit!=self.source_commit):
            raise ContractError('RC72_RELEASE_DRIVER_N9_PIPELINE_SCOPE_MISMATCH')

    def _has_gate(self,node_type):
        return (node_type in self._gate_types() or node_type=='N6_EXECUTABLE_READINESS'
                or node_type=='N7_EXECUTION' and self.n7_pipeline is not None
                or node_type=='N8_DIAGNOSIS_RECOVERY' and self.n8_pipeline is not None
                or node_type=='N9_DEFECT' and self.n9_pipeline is not None
                or node_type=='N10_RELEASE_CONVERGENCE' and self.n10_pipeline is not None)

    def _diagnosis_bypassed(self,nodes,mission_id):
        by_type={n['node_type']:n for n in nodes}
        n7,n8,n9=(by_type.get(k,{}) for k in ('N7_EXECUTION','N8_DIAGNOSIS_RECOVERY','N9_DEFECT'))
        return (n7.get('state')=='PASS' and n8.get('state')=='NOT_STARTED'
            and n9.get('state') not in {None,'NOT_STARTED'} and any(e['kind']=='FORWARD'
                and e['from_node_type']=='N7_EXECUTION' and e['to_node_type']=='N9_DEFECT'
                and e['source_gate_id'] in n7['gate_refs']
                for e in self.truth.query('rc72_node_transition',mission_id=mission_id)))

    def _one(self, kind, **filters):
        rows = self.truth.query(kind, **filters)
        if len(rows) != 1:
            raise ContractError('RC72_RELEASE_DRIVER_TRUTH_NOT_UNIQUE:' + kind)
        return rows[0]

    def status(self, *, release_batch_id):
        return release_batch_status(self.truth, source_commit=self.source_commit, release_batch_id=release_batch_id)

    def _n2(self, batch):
        bid = batch['release_batch_id']
        dispatch = N2RequirementDispatchService(self.truth, source_commit=self.source_commit).dispatch(release_batch_id=bid)
        N2RequirementAssignmentService(self.truth, source_commit=self.source_commit).assign_all(release_batch_id=bid)
        handoff = N2GovernedRequirementHandoffService(self.truth, source_commit=self.source_commit,
            launcher=self.n2_launcher, allowed_tools=self.n2_tools)
        promotion = N2RequirementCandidatePromotionService(self.truth, release_id=batch['release_id'],
            mission_id=batch['mission_id'], source_commit=self.source_commit, state_root=str(self.n2_launcher.state_root))
        review = N2RequirementReviewService(ClosedLoopControlPlane(self.truth, batch['release_id'], batch['mission_id']), self.n2_evaluator)
        if (len(dispatch['requirement_ids']) != len(dispatch['workitem_ids'])
                or len(dispatch['requirement_ids']) != len(batch['requirement_ids'])
                or set(dispatch['requirement_ids']) != set(batch['requirement_ids'])):
            raise ContractError('RC72_RELEASE_DRIVER_REQUIREMENT_DENOMINATOR_CHANGED')
        holds = []
        for requirement_id, task_id in zip(dispatch['requirement_ids'], dispatch['workitem_ids']):
            task = self._one('rc7_task', task_id=task_id)
            if task['state'] == 'PASS':
                continue  # The whole-node gate below independently audits this.
            if task['state'] == 'REPAIR_REQUIRED':
                continue  # Native whole-node review retains this failed member.
            if task['state'] in {'BLOCKED', 'HUMAN_REQUIRED'}:
                holds.append(task_id)
                continue
            if task['state'] == 'LEASED':
                handoff.handoff(release_batch_id=bid, requirement_id=requirement_id)
            elif task['state'] not in {'RUNNING', 'OUTPUT_PRODUCED'}:
                holds.append(task_id)
                continue
            # Promotion revalidates existing raw anchor + candidate bytes. A
            # promoted candidate is not a reason to launch its producer again.
            candidate = promotion.promote(release_batch_id=bid, requirement_id=requirement_id)
            review.review_and_apply(task_id=candidate['task_id'], artifact_id=candidate['artifact_id'])
        if holds:
            return dict(status='HOLD', reason='N2_REPAIR_OR_HUMAN_REVIEW_REQUIRED', workitem_ids=holds)
        return N2DeliveryGateService(self.truth, source_commit=self.source_commit).complete(release_batch_id=bid)

    @staticmethod
    def _gate_types():
        return {'N1_REALITY': N1StrictRealityGateService, 'N2_REQUIREMENT': N2DeliveryGateService,
            'N3_CODE_ANALYSIS': N3DeliveryGateService, 'N4_TEST_DESIGN': N4ParentScopedDeliveryGateService,
            'N5_TEST_DATA': N5OwnedWorkItemGateService}

    def _complete_gate(self, node_type, batch):
        if node_type=='N8_DIAGNOSIS_RECOVERY' and self.n8_pipeline is not None:
            n7=self._one('rc72_mission_node',mission_id=batch['mission_id'],node_type='N7_EXECUTION')
            if n7['state']=='PASS':
                return self.n8_pipeline.audit(release_batch_id=batch['release_batch_id'])
            return self.n8_pipeline.complete(release_batch_id=batch['release_batch_id'])
        if node_type=='N10_RELEASE_CONVERGENCE' and self.n10_pipeline is not None:
            return self.n10_pipeline.complete(release_batch_id=batch['release_batch_id'])
        if node_type=='N9_DEFECT' and self.n9_pipeline is not None:
            return self.n9_pipeline.complete(release_batch_id=batch['release_batch_id'])
        if node_type=='N1_REALITY':
            N1StrictDshHandoffService(self.truth, source_commit=self.source_commit, launcher=self.n1_launcher,
                allowed_tools=self.n1_tools).audit_recorded_native_handoff(release_batch_id=batch['release_batch_id'])
        if node_type=='N7_EXECUTION' and self.n7_pipeline is not None:
            return self.n7_pipeline.complete(release_batch_id=batch['release_batch_id'])
        if node_type=='N6_EXECUTABLE_READINESS':
            return N6PipelineService(self.truth,release_id=batch['release_id'],source_commit=self.source_commit).complete(release_batch_id=batch['release_batch_id'])
        options = dict(source_commit=self.source_commit)
        if node_type == 'N5_TEST_DATA':
            options['release_id'] = batch['release_id']
        result=self._gate_types()[node_type](self.truth, **options).complete(release_batch_id=batch['release_batch_id'])
        if (node_type=='N1_REALITY' and self.expected_scope is not None
                and self._one('rc72_mission_node',mission_id=batch['mission_id'],node_type='N1_REALITY')['state']=='PASS'):
            self.expected_scope.freeze(release_batch_id=batch['release_batch_id'])
        return result

    def _validated_n8_continue(self, batch, recovered):
        """Accept only a real new admitted N7 plan before another driver turn.

        The retry planner owns all R1 restoration and N6 compilation. This
        check prevents a replayed N8 CONTINUE response from spinning forever
        while N7 is still NOT_STARTED, or from reusing an old signed Attempt.
        """
        if (recovered.get('status')!='CONTINUE'
                or recovered.get('reason')!='N8_ACCEPTED_N5_REPAIR_N7_RETRY_READY'
                or not recovered.get('recovery_plan_id')):
            raise ContractError('RC72_RELEASE_DRIVER_UNVERIFIED_N8_CONTINUATION')
        original=self._one('rc72_n7_execution_preparation',
            preparation_id=recovered['preparation_id'])
        if original['release_batch_id']!=batch['release_batch_id']:
            raise ContractError('RC72_RELEASE_DRIVER_N8_RETRY_BATCH_CHANGED')
        if recovered['recovery_plan_id']==original['plan_id']:
            raise ContractError('RC72_RELEASE_DRIVER_N8_FRESH_N7_NOT_ADMITTED')
        planned=self.n7_pipeline.preparation.planning.assert_current(
            recovered['recovery_plan_id'])
        node=self._one('rc72_mission_node',mission_id=batch['mission_id'],
            node_type='N7_EXECUTION')
        if (planned.get('recovery_id') is None
                or planned['plan_id']==original['plan_id']
                or planned['release_batch_id']!=batch['release_batch_id']
                or planned['mission_id']!=batch['mission_id']
                or node['state'] not in {'READY','RUNNING'}
                or not self.truth.query('execution_attempt',attempt_id=original['attempt_id'])):
            raise ContractError('RC72_RELEASE_DRIVER_N8_FRESH_N7_NOT_ADMITTED')
        return planned

    def run(self, *, release_batch_id):
        with _driver_lock(self.truth, release_batch_id):
            self.truth.rebuild_projection()
            batch = self._one('rc72_release_batch', release_batch_id=release_batch_id)
            if any(l.release_id != batch['release_id'] for l in (self.n1_launcher, self.n2_launcher, self.n2_evaluator.launcher)):
                raise ContractError('RC72_RELEASE_DRIVER_WORKER_RELEASE_MISMATCH')
            if self.n3_pipeline is not None and (self.n3_pipeline.truth is not self.truth
                    or self.n3_pipeline.source_commit != self.source_commit
                    or any(l.truth is not self.truth or l.release_id != batch['release_id'] for l in self.n3_pipeline.launchers)):
                raise ContractError('RC72_RELEASE_DRIVER_N3_PIPELINE_SCOPE_MISMATCH')
            if self.n4_pipeline is not None and (self.n4_pipeline.truth is not self.truth
                    or self.n4_pipeline.source_commit != self.source_commit
                    or any(l.truth is not self.truth or l.release_id != batch['release_id'] for l in self.n4_pipeline.launchers)):
                raise ContractError('RC72_RELEASE_DRIVER_N4_PIPELINE_SCOPE_MISMATCH')
            if self.n5_pipeline is not None and (self.n5_pipeline.truth is not self.truth
                    or self.n5_pipeline.source_commit != self.source_commit
                    or any(l.truth is not self.truth or l.release_id != batch['release_id'] for l in self.n5_pipeline.launchers)):
                raise ContractError('RC72_RELEASE_DRIVER_N5_PIPELINE_SCOPE_MISMATCH')
            if self.n7_pipeline is not None and (self.n7_pipeline.truth is not self.truth
                    or self.n7_pipeline.source_commit!=self.source_commit or self.n7_pipeline.release_id!=batch['release_id']):
                raise ContractError('RC72_RELEASE_DRIVER_N7_PIPELINE_SCOPE_MISMATCH')
            self._assert_n8_scope()
            self._assert_n9_scope()
            self._assert_n10_scope(release_batch_id=release_batch_id)
            self._assert_expected_scope(release_batch_id=batch['release_batch_id'])
            # Admission is rechecked even when canonical nodes already exist.
            ReleaseBatchFieldMissionLauncher(self.truth, source_commit=self.source_commit,bank_pip_mirror=self.bank_pip_mirror).start(release_batch_id=release_batch_id)
            # Cold continuation audits accepted source bytes, not merely PASS labels.
            prefix=self.status(release_batch_id=release_batch_id)['nodes']
            for node in prefix:
                if node['node_type']=='N8_DIAGNOSIS_RECOVERY' and self._diagnosis_bypassed(prefix,batch['mission_id']):
                    continue
                if node['state'] != 'PASS':
                    break
                if self._has_gate(node['node_type']):
                    audited = self._complete_gate(node['node_type'], batch)
                    if audited.get('status')=='HOLD':
                        return dict(self.status(release_batch_id=release_batch_id), **audited)
            while True:
                snapshot = self.status(release_batch_id=release_batch_id)
                by_type={n['node_type']:n for n in snapshot['nodes']}
                failed_n7=by_type['N7_EXECUTION']
                active_n8=by_type['N8_DIAGNOSIS_RECOVERY']
                # A genuine N7 failure suspends ordinary forward iteration:
                # N8 must own its original failed Attempt and any N5 backedge
                # before N5 normal completion or N7 can run again. In particular
                # the first incomplete node is often N7 NEEDS_REVISION (before
                # N8 READY), or N5 RUNNING (after N8 signed compensation).
                if (self.n8_pipeline is not None and active_n8['state']!='NOT_STARTED'
                        and failed_n7['state'] in {'NEEDS_REVISION','BLOCKED','STALE','NOT_STARTED'}):
                    repaired=self.n8_pipeline.complete(release_batch_id=release_batch_id)
                    if repaired.get('status')=='CONTINUE':
                        self._validated_n8_continue(batch,repaired)
                        continue
                    return dict(self.status(release_batch_id=release_batch_id),**repaired)
                pending = [n for n in snapshot['nodes'] if n['state'] != 'PASS']
                if self._diagnosis_bypassed(snapshot['nodes'],batch['mission_id']):
                    pending = [n for n in pending if n['node_type']!='N8_DIAGNOSIS_RECOVERY']

                if not pending:
                    # N10 terminal PASS is admitted only by the production
                    # native independent reviewer, then re-audited against
                    # live original R1. A historical node label alone is not
                    # a ReleaseBatch completion decision.
                    if self.n10_pipeline is not None:
                        terminal=self._complete_gate('N10_RELEASE_CONVERGENCE',batch)
                        if terminal.get('status')=='PASS':
                            return dict(self.status(release_batch_id=release_batch_id),**terminal)
                        if terminal.get('status')=='HOLD':
                            return dict(self.status(release_batch_id=release_batch_id),**terminal)
                    return dict(snapshot, status='HOLD', reason='RELEASE_CONVERGENCE_AUDIT_REQUIRED')
                node = pending[0]
                if node['state'] == 'REVIEW_PENDING':
                    if not self._has_gate(node['node_type']):
                        return dict(snapshot, status='HOLD', reason='NATIVE_GATE_ROUTE_NOT_IMPLEMENTED')
                    audited = self._complete_gate(node['node_type'], batch)
                    if audited.get('status')=='HOLD':
                        return dict(self.status(release_batch_id=release_batch_id), **audited)
                    if self._one('rc72_mission_node', mission_node_id=node['mission_node_id'])['state']=='PASS':
                        continue
                    return dict(self.status(release_batch_id=release_batch_id), status='HOLD', reason='NATIVE_NODE_GATE_NOT_PASS')
                if node['state'] not in {'READY', 'RUNNING'}:
                    return dict(snapshot, status='HOLD', reason='NODE_NOT_READY', mission_node_id=node['mission_node_id'])
                if node['node_type'] == 'N1_REALITY':
                    N1AutonomousDispatchService(self.truth, source_commit=self.source_commit).dispatch(release_batch_id=release_batch_id)
                    N1AgentTeamsAssignmentService(self.truth, source_commit=self.source_commit).assign(release_batch_id=release_batch_id)
                    n1 = (self.expected_scope.pipeline if self.expected_scope is not None else
                        N1StrictPipelineService(self.truth, source_commit=self.source_commit, launcher=self.n1_launcher,
                            allowed_tools=self.n1_tools))
                    n1.complete(release_batch_id=release_batch_id)
                    if (self.expected_scope is not None and
                            self._one('rc72_mission_node',mission_id=batch['mission_id'],node_type='N1_REALITY')['state']=='PASS'):
                        self.expected_scope.freeze(release_batch_id=release_batch_id)
                elif node['node_type'] == 'N2_REQUIREMENT':
                    result = self._n2(batch)
                    if result.get('status') == 'HOLD':
                        return dict(self.status(release_batch_id=release_batch_id), **result)
                elif node['node_type'] == 'N3_CODE_ANALYSIS' and self.n3_pipeline is not None:
                    result = self.n3_pipeline.complete(release_batch_id=release_batch_id)
                    if result.get('status') == 'HOLD':
                        return dict(self.status(release_batch_id=release_batch_id), **result)
                elif node['node_type'] == 'N4_TEST_DESIGN' and self.n4_pipeline is not None:
                    result = self.n4_pipeline.complete(release_batch_id=release_batch_id)
                    if result.get('status') == 'HOLD':
                        return dict(self.status(release_batch_id=release_batch_id), **result)
                elif node['node_type'] == 'N5_TEST_DATA' and self.n5_pipeline is not None:
                    result = self.n5_pipeline.complete(release_batch_id=release_batch_id)
                    if result.get('status') == 'HOLD':
                        return dict(self.status(release_batch_id=release_batch_id), **result)
                elif node['node_type']=='N6_EXECUTABLE_READINESS':
                    result = N6PipelineService(self.truth,release_id=batch['release_id'],source_commit=self.source_commit).complete(release_batch_id=release_batch_id)
                    if result.get('status')=='HOLD':
                        return dict(self.status(release_batch_id=release_batch_id), **result)
                elif node['node_type']=='N7_EXECUTION' and self.n7_pipeline is not None:
                    result = self.n7_pipeline.complete(release_batch_id=release_batch_id)
                    if result.get('status')=='HOLD':
                        # N7 runner/process failures have already persisted
                        # a real blocked Attempt, but may not yet have started
                        # N8's first independent diagnosis process.
                        if (self.n8_pipeline is not None
                                and result.get('reason')=='N7_EXECUTION_DIAGNOSIS_REQUIRED'
                                and result.get('preparation_id')):
                            prepared=self._one('rc72_n7_execution_preparation',
                                preparation_id=result['preparation_id'])
                            dispatch=self.truth.query('rc72_n7_tool_dispatch',
                                preparation_id=prepared['preparation_id'])
                            if (len(dispatch)==1 and dispatch[0]['state'] in {'FAILED','RETURNED'}):
                                # Native N8 first admits the original signed
                                # Attempt if N7 failed before it was projected.
                                # It cannot start another N7 business call.
                                recovery=self.n8_pipeline.complete(release_batch_id=release_batch_id)
                                return dict(self.status(release_batch_id=release_batch_id),**recovery)
                        return dict(self.status(release_batch_id=release_batch_id), **result)
                elif node['node_type']=='N8_DIAGNOSIS_RECOVERY' and self.n8_pipeline is not None:
                    result=self.n8_pipeline.complete(release_batch_id=release_batch_id)
                    if result.get('status')=='CONTINUE':
                        self._validated_n8_continue(batch,result)
                        continue
                    return dict(self.status(release_batch_id=release_batch_id),**result)
                elif node['node_type']=='N10_RELEASE_CONVERGENCE' and self.n10_pipeline is not None:
                    result=self.n10_pipeline.complete(release_batch_id=release_batch_id)
                    if result.get('status')=='HOLD':
                        return dict(self.status(release_batch_id=release_batch_id), **result)
                elif node['node_type']=='N9_DEFECT' and self.n9_pipeline is not None:
                    result=self.n9_pipeline.complete(release_batch_id=release_batch_id)
                    if result.get('status')=='HOLD':
                        return dict(self.status(release_batch_id=release_batch_id), **result)
                else:
                    return dict(snapshot, status='HOLD', reason='NATIVE_PRODUCT_ROUTE_NOT_IMPLEMENTED',
                        mission_node_id=node['mission_node_id'])
                current = self._one('rc72_mission_node', mission_node_id=node['mission_node_id'])
                if current['state'] != 'PASS':
                    return dict(self.status(release_batch_id=release_batch_id), status='HOLD', reason='NATIVE_NODE_GATE_NOT_PASS')
