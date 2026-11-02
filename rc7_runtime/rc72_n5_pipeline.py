"""Native whole-inventory N5 discovery, independent verification and Gate.

Dispatched resolution plans retain their original discovery denominator until
all work is finalized. Replanning midway cannot erase completed or pending work.
"""
import re
from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from .models import ContractError
from .rc72_authority import RC72AuthorityRuntime
from .rc72_n5_data_inventory import N5DataRequirementInventoryService
from .rc72_n5_data_resolution import N5DataResolutionService
from .rc72_n5_data_discovery_dispatch import N5DataDiscoveryDispatchService
from .rc72_n5_data_discovery_assignment import N5DataDiscoveryAssignmentService
from .rc72_n5_data_discovery_handoff import N5DataDiscoveryDshHandoffService
from .rc72_n5_data_discovery_anchor import N5DataDiscoveryEvidenceAnchorService
from .rc72_n5_data_discovery_promotion import N5DataDiscoveryCandidatePromotionService
from .rc72_n5_data_verification_handoff import N5DataVerificationDshHandoffService
from .rc72_n5_data_verification_finalization import N5DataVerificationFinalizationService
from .rc72_n5_workitem_acceptance import N5WorkItemFinalizer, N5OwnedWorkItemGateService


class N5PipelineService:
    def __init__(self, truth, *, source_commit, launcher, allowed_tools, verifier, verification_tools):
        if not isinstance(source_commit, str) or not re.fullmatch('[0-9a-f]{40}', source_commit):
            raise ContractError('RC72_N5_PIPELINE_EXACT_SOURCE_REQUIRED')
        self.truth, self.source_commit, self.launcher, self.verifier = truth, source_commit, launcher, verifier
        for worker in self.launchers:
            if (not isinstance(worker, DshHeadlessWorkerLauncher) or worker.truth is not truth
                    or not isinstance(worker.authority, RC72AuthorityRuntime)):
                raise ContractError('RC72_N5_PIPELINE_NATIVE_WORKER_REQUIRED')
        for tools in (allowed_tools, verification_tools):
            if (not isinstance(tools, (list, tuple)) or not tools or len(set(tools)) != len(tools)
                    or any(not isinstance(t, str) or not t.strip() or '*' in t for t in tools)):
                raise ContractError('RC72_N5_PIPELINE_EXACT_TOOLS_REQUIRED')
        self.tools, self.verification_tools = tuple(allowed_tools), tuple(verification_tools)

    @property
    def launchers(self):
        return self.launcher, self.verifier

    def _one(self, kind, **filters):
        rows = self.truth.query(kind, **filters)
        if len(rows) != 1:
            raise ContractError('RC72_N5_PIPELINE_TRUTH_NOT_UNIQUE:' + kind)
        return rows[0]

    def complete(self, *, release_batch_id):
        batch = self._one('rc72_release_batch', release_batch_id=release_batch_id)
        if any(l.release_id != batch['release_id'] for l in self.launchers):
            raise ContractError('RC72_N5_PIPELINE_WORKER_RELEASE_MISMATCH')
        common = dict(release_id=batch['release_id'], source_commit=self.source_commit)
        gate = N5OwnedWorkItemGateService(self.truth, **common)
        if self._one('rc72_mission_node', mission_id=batch['mission_id'], node_type='N5_TEST_DATA')['state'] == 'PASS':
            return gate.complete(release_batch_id=release_batch_id)
        inventory = N5DataRequirementInventoryService(self.truth, source_commit=self.source_commit).materialize(release_batch_id=release_batch_id)
        required = set(inventory['data_requirement_ids'])
        resolver = N5DataResolutionService(self.truth, **common)
        rows = self.truth.query('rc72_n5_data_discovery_dispatch', release_batch_id=release_batch_id)
        if not rows:
            resolver.resolve_all(release_batch_id=release_batch_id)
            N5DataDiscoveryDispatchService(self.truth, **common).dispatch(release_batch_id=release_batch_id)
            rows = self.truth.query('rc72_n5_data_discovery_dispatch', release_batch_id=release_batch_id)
        plans = self.truth.query('rc72_n5_data_resolution_plan', release_batch_id=release_batch_id)
        if len(plans) != len(required) or {p['data_requirement_id'] for p in plans} != required:
            raise ContractError('RC72_N5_PIPELINE_PLAN_DENOMINATOR_CHANGED')
        if (len({r['data_requirement_id'] for r in rows}) != len(rows)
                or any(r['data_requirement_id'] not in required or r['mission_id'] != batch['mission_id']
                    or r['source_commit'] != self.source_commit for r in rows)):
            raise ContractError('RC72_N5_PIPELINE_DISCOVERY_DENOMINATOR_CHANGED')
        by_id = {r['data_requirement_id']: r for r in rows}
        if any(p['status'] not in {'DISCOVERY_REQUIRED', 'REUSE_VERIFIED'}
                or (p['status']=='DISCOVERY_REQUIRED' and p['data_requirement_id'] not in by_id) for p in plans):
            raise ContractError('RC72_N5_PIPELINE_DISCOVERY_PLAN_NOT_COVERED')
        if any(self._one('rc7_task', task_id=r['workitem_id'])['state']=='READY' for r in rows):
            N5DataDiscoveryAssignmentService(self.truth, **common).assign_all(release_batch_id=release_batch_id)
        handoff = N5DataDiscoveryDshHandoffService(self.truth, source_commit=self.source_commit,
            launcher=self.launcher, allowed_tools=self.tools)
        anchor = N5DataDiscoveryEvidenceAnchorService(self.truth, source_commit=self.source_commit,
            state_root=str(self.launcher.state_root))
        scoped = dict(common, mission_id=batch['mission_id'])
        promotion = N5DataDiscoveryCandidatePromotionService(self.truth, state_root=str(self.launcher.state_root), **scoped)
        verification = N5DataVerificationDshHandoffService(self.truth, launcher=self.verifier,
            allowed_tools=self.verification_tools, **scoped)
        finalizer = N5DataVerificationFinalizationService(self.truth, state_root=str(self.verifier.state_root), **scoped)
        workitems = N5WorkItemFinalizer(finalizer)
        holds = []
        for plan in sorted(plans, key=lambda p: p['data_requirement_id']):
            if plan['status'] == 'REUSE_VERIFIED':
                if plan['data_requirement_id'] in by_id:
                    anchor.anchor(release_batch_id=release_batch_id, data_requirement_id=plan['data_requirement_id'])
                    outcome = workitems.finalize(release_batch_id=release_batch_id,
                        data_requirement_id=plan['data_requirement_id'])
                    if outcome['status']=='REPAIR_REQUIRED':
                        holds.append(by_id[plan['data_requirement_id']]['workitem_id'])
                continue  # Final resolution/Gate revalidate the actual binding.
            row = by_id[plan['data_requirement_id']]
            task = self._one('rc7_task', task_id=row['workitem_id'])
            scope = dict(release_batch_id=release_batch_id, data_requirement_id=row['data_requirement_id'])
            if task['state'] == 'LEASED':
                handoff.handoff(**scope)
            elif task['state'] not in {'RUNNING','OUTPUT_PRODUCED','PASS','REPAIR_REQUIRED'}:
                holds.append(task['task_id'])
                continue
            anchor.anchor(**scope)
            if not self.truth.query('rc72_n5_data_binding', data_requirement_id=row['data_requirement_id']):
                promotion.promote(**scope)
            if task['state'] not in {'PASS','REPAIR_REQUIRED'}:
                verification.verify(**scope)
            result = workitems.finalize(**scope)
            if result['status'] == 'REPAIR_REQUIRED':
                holds.append(task['task_id'])
        if holds:
            return dict(status='HOLD', reason='N5_INDEPENDENT_VERIFICATION_NOT_ACCEPTED', workitem_ids=holds)
        # Only now may plans move from DISCOVERY_REQUIRED to REUSE_VERIFIED.
        resolution = resolver.resolve_all(release_batch_id=release_batch_id)
        if resolution['discovery_required_count']:
            return dict(status='HOLD', reason='N5_VERIFIED_BINDINGS_INCOMPLETE')
        return gate.complete(release_batch_id=release_batch_id)
