"""Concrete whole Requirement x SST native design and parent-scoped review."""
import re
from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from .models import ContractError
from .rc72_authority import RC72AuthorityRuntime
from .rc72_n4_parent_truth import N4ParentTruthService
from .rc72_n4_parent_guard import N4ParentScopedDesignEvaluator, N4ParentScopedDeliveryGateService
from .rc72_n4_test_design_dispatch import N4TestDesignDispatchService
from .rc72_n4_test_design_assignment import N4TestDesignAssignmentService
from .rc72_n4_test_design_handoff import N4TestDesignDshHandoffService
from .rc72_n4_test_design_anchor import N4TestDesignEvidenceAnchorService
from .rc72_n4_test_design_promotion import N4TestDesignCandidatePromotionService
from .rc72_n4_test_design_review import N4TestDesignReviewService


class N4PipelineService:
    def __init__(self, truth, *, source_commit, launcher, allowed_tools, evaluator):
        if not isinstance(source_commit, str) or not re.fullmatch('[0-9a-f]{40}', source_commit):
            raise ContractError('RC72_N4_PIPELINE_EXACT_SOURCE_REQUIRED')
        if not isinstance(evaluator, N4ParentScopedDesignEvaluator):
            raise ContractError('RC72_N4_PIPELINE_PARENT_SCOPED_REVIEW_REQUIRED')
        self.truth, self.source_commit, self.launcher, self.evaluator = truth, source_commit, launcher, evaluator
        for worker in self.launchers:
            if (not isinstance(worker, DshHeadlessWorkerLauncher) or worker.truth is not truth
                    or not isinstance(worker.authority, RC72AuthorityRuntime)):
                raise ContractError('RC72_N4_PIPELINE_NATIVE_WORKER_REQUIRED')
        for tools in (allowed_tools, evaluator.reviewer_allowed_tools):
            if (not isinstance(tools, (list, tuple)) or not tools or len(set(tools)) != len(tools)
                    or any(not isinstance(t, str) or not t.strip() or '*' in t for t in tools)):
                raise ContractError('RC72_N4_PIPELINE_EXACT_TOOLS_REQUIRED')
        self.tools = tuple(allowed_tools)

    @property
    def launchers(self):
        return self.launcher, self.evaluator.launcher

    def _one(self, kind, **filters):
        rows = self.truth.query(kind, **filters)
        if len(rows) != 1:
            raise ContractError('RC72_N4_PIPELINE_TRUTH_NOT_UNIQUE:' + kind)
        return rows[0]

    def complete(self, *, release_batch_id):
        batch = self._one('rc72_release_batch', release_batch_id=release_batch_id)
        if any(l.release_id != batch['release_id'] for l in self.launchers):
            raise ContractError('RC72_N4_PIPELINE_WORKER_RELEASE_MISMATCH')
        gate = N4ParentScopedDeliveryGateService(self.truth, source_commit=self.source_commit)
        if self._one('rc72_mission_node', mission_id=batch['mission_id'], node_type='N4_TEST_DESIGN')['state'] == 'PASS':
            return gate.complete(release_batch_id=release_batch_id)
        parent = N4ParentTruthService(self.truth).resolve(release_batch_id=release_batch_id)
        expected = {(req, sst) for req, ssts in parent['requirement_sst_map'].items() for sst in ssts}
        dispatch = N4TestDesignDispatchService(self.truth, source_commit=self.source_commit).dispatch(release_batch_id=release_batch_id)
        scopes = dispatch['design_scopes']
        if (len(scopes) != len(expected) or len(scopes) != len(dispatch['workitem_ids'])
                or {(s['requirement_id'], s['sst_id']) for s in scopes} != expected):
            raise ContractError('RC72_N4_PIPELINE_SCOPE_DENOMINATOR_CHANGED')
        if any(self._one('rc7_task', task_id=t)['state'] == 'READY' for t in dispatch['workitem_ids']):
            N4TestDesignAssignmentService(self.truth, source_commit=self.source_commit).assign_all(release_batch_id=release_batch_id)
        handoff = N4TestDesignDshHandoffService(self.truth, source_commit=self.source_commit,
            launcher=self.launcher, allowed_tools=self.tools)
        anchor = N4TestDesignEvidenceAnchorService(self.truth, source_commit=self.source_commit,
            state_root=str(self.launcher.state_root))
        promotion = N4TestDesignCandidatePromotionService(self.truth, source_commit=self.source_commit,
            release_id=batch['release_id'], mission_id=batch['mission_id'], state_root=str(self.launcher.state_root))
        review = N4TestDesignReviewService(self.truth, source_commit=self.source_commit,
            release_id=batch['release_id'], mission_id=batch['mission_id'], evaluator=self.evaluator)
        holds = []
        for scope, task_id in zip(scopes, dispatch['workitem_ids']):
            task = self._one('rc7_task', task_id=task_id)
            context = dict(scope, release_batch_id=release_batch_id)
            if task['state'] == 'LEASED':
                handoff.handoff(**context)
            elif task['state'] not in {'RUNNING', 'OUTPUT_PRODUCED', 'PASS', 'REPAIR_REQUIRED'}:
                holds.append(task_id)
                continue
            anchor.anchor(**context)
            promotion.promote(**context)
            review.review(**context)
        if holds:
            return dict(status='HOLD', reason='N4_REVIEW_RECOVERY_REQUIRED', workitem_ids=holds)
        return gate.complete(release_batch_id=release_batch_id)
