"""Concrete N3 source discovery -> independent mapping review -> code review.

Canonical node services retain all lineage, sufficiency and Gate decisions.
No target is inferred by this coordinator and no semantic callback can PASS it.
"""
import re

from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from .models import ContractError
from .rc72_code_tool_binding import canonical_code_tools
from .closed_loop_control import ClosedLoopControlPlane
from .dsh_code_evaluator import DshCodeEvaluator
from .rc72_authority import RC72AuthorityRuntime
from .rc72_n3_source_target_dispatch import N3SourceTargetDispatchService
from .rc72_n3_source_target_assignment import N3SourceTargetAssignmentService
from .rc72_n3_source_target_handoff import N3SourceTargetDshHandoffService
from .rc72_n3_source_target_anchor import N3SourceTargetEvidenceAnchorService
from .rc72_n3_source_target_promotion import N3SourceTargetCandidatePromotionService, N3SourceTargetPromotionError
from .rc72_n3_source_target_review import N3SourceTargetReviewService
from .rc72_n3_code_analysis_dispatch import N3CodeAnalysisDispatchService
from .rc72_n3_code_analysis_assignment import N3CodeAnalysisAssignmentService
from .rc72_n3_code_analysis_handoff import N3CodeAnalysisDshHandoffService
from .rc72_n3_code_analysis_anchor import N3CodeAnalysisEvidenceAnchorService
from .rc72_n3_code_analysis_promotion import N3CodeAnalysisCandidatePromotionService
from .rc72_n3_code_analysis_review import N3CodeAnalysisReviewService
from .rc72_n3_completion import N3DeliveryGateService


class N3PipelineService:
    def __init__(self, truth, *, source_commit, source_launcher, source_tools,
                 source_reviewer, source_review_tools, code_launcher, code_tools, code_evaluator):
        if not isinstance(source_commit, str) or not re.fullmatch('[0-9a-f]{40}', source_commit):
            raise ContractError('RC72_N3_PIPELINE_EXACT_SOURCE_REQUIRED')
        if not isinstance(code_evaluator, DshCodeEvaluator):
            raise ContractError('RC72_N3_PIPELINE_CODE_REVIEWER_REQUIRED')
        self.truth, self.source_commit = truth, source_commit
        self.source_launcher, self.source_reviewer, self.code_launcher = source_launcher, source_reviewer, code_launcher
        self.code_evaluator = code_evaluator
        for launcher in self.launchers:
            if (not isinstance(launcher, DshHeadlessWorkerLauncher) or launcher.truth is not truth
                    or not isinstance(launcher.authority, RC72AuthorityRuntime)):
                raise ContractError('RC72_N3_PIPELINE_NATIVE_WORKER_REQUIRED')
        for tools in (source_tools, source_review_tools, code_tools, code_evaluator.reviewer_allowed_tools):
            if (not isinstance(tools, (tuple, list)) or not tools
                    or any(not isinstance(t, str) or not t.strip() or '*' in t for t in tools)
                    or len(set(tools)) != len(tools)):
                raise ContractError('RC72_N3_PIPELINE_EXACT_TOOLS_REQUIRED')
        try:
            code_tools = canonical_code_tools(code_tools)
        except ValueError:
            raise ContractError('RC72_N3_PIPELINE_REQUIRED_CODE_TOOLS_CHANGED')
        self.source_tools, self.source_review_tools, self.code_tools = tuple(source_tools), tuple(source_review_tools), tuple(code_tools)

    @property
    def launchers(self):
        return self.source_launcher, self.source_reviewer, self.code_launcher, self.code_evaluator.launcher

    def _one(self, kind, **filters):
        rows = self.truth.query(kind, **filters)
        if len(rows) != 1:
            raise ContractError('RC72_N3_PIPELINE_TRUTH_NOT_UNIQUE:' + kind)
        return rows[0]

    def complete(self, *, release_batch_id):
        batch = self._one('rc72_release_batch', release_batch_id=release_batch_id)
        if any(worker.release_id != batch['release_id'] for worker in self.launchers):
            raise ContractError('RC72_N3_PIPELINE_WORKER_RELEASE_MISMATCH')
        common = dict(release_id=batch['release_id'], mission_id=batch['mission_id'], source_commit=self.source_commit)
        node = self._one('rc72_mission_node', mission_id=batch['mission_id'], node_type='N3_CODE_ANALYSIS')
        gate = N3DeliveryGateService(self.truth, source_commit=self.source_commit)
        if node['state'] == 'PASS':
            return gate.complete(release_batch_id=release_batch_id)
        source = N3SourceTargetDispatchService(self.truth, source_commit=self.source_commit).dispatch(release_batch_id=release_batch_id)
        rows = source['dispatches']
        if len(rows) != len(batch['application_ids']) or {r['application_id'] for r in rows} != set(batch['application_ids']):
            raise ContractError('RC72_N3_PIPELINE_APPLICATION_DENOMINATOR_CHANGED')
        if any(self._one('rc7_task', task_id=r['workitem_id'])['state'] == 'READY' for r in rows):
            N3SourceTargetAssignmentService(self.truth, source_commit=self.source_commit).assign_all(release_batch_id=release_batch_id)
        handoff = N3SourceTargetDshHandoffService(self.truth, source_commit=self.source_commit,
            launcher=self.source_launcher, allowed_tools=self.source_tools)
        anchor = N3SourceTargetEvidenceAnchorService(self.truth, source_commit=self.source_commit,
            state_root=str(self.source_launcher.state_root))
        promotion = N3SourceTargetCandidatePromotionService(self.truth, state_root=str(self.source_launcher.state_root), **common)
        review = N3SourceTargetReviewService(ClosedLoopControlPlane(self.truth, batch['release_id'], batch['mission_id']),
            self.source_reviewer, allowed_tools=self.source_review_tools)
        holds = []
        for row in rows:
            task = self._one('rc7_task', task_id=row['workitem_id'])
            scope = dict(release_batch_id=release_batch_id, application_id=row['application_id'])
            if task['state'] == 'LEASED':
                handoff.handoff(**scope)
            elif task['state'] not in {'RUNNING', 'OUTPUT_PRODUCED', 'PASS', 'REPAIR_REQUIRED'}:
                holds.append(task['task_id'])
                continue
            anchor.anchor(**scope)
            try:
                candidate = promotion.promote(**scope)
            except N3SourceTargetPromotionError as exc:
                if str(exc) not in {'RC72_N3_PROMOTION_UNRESOLVED_DISCOVERY_UNKNOWNS',
                                    'RC72_N3_PROMOTION_UNRESOLVED_DISCOVERY_GAPS'}:
                    raise
                # The original anchored discovery remains authoritative. Do not
                # manufacture a candidate or independent review for ambiguity.
                holds.append(task['task_id'])
                continue
            result = review.review_and_apply(task_id=candidate['task_id'], artifact_id=candidate['artifact_id'])
            if result.task_state != 'PASS':
                holds.append(task['task_id'])
        if holds:
            return dict(status='HOLD', reason='N3_SOURCE_MAPPING_NOT_ACCEPTED', workitem_ids=holds)
        code = N3CodeAnalysisDispatchService(self.truth, source_commit=self.source_commit).dispatch(release_batch_id=release_batch_id)
        if (not code['targets'] or len(code['targets']) != len(code['workitem_ids'])
                or len({r['target_id'] for r in code['targets']}) != len(code['targets'])):
            raise ContractError('RC72_N3_PIPELINE_TARGET_DENOMINATOR_CHANGED')
        if any(self._one('rc7_task', task_id=tid)['state'] == 'READY' for tid in code['workitem_ids']):
            N3CodeAnalysisAssignmentService(self.truth, source_commit=self.source_commit).assign_all(release_batch_id=release_batch_id)
        handoff = N3CodeAnalysisDshHandoffService(self.truth, source_commit=self.source_commit,
            launcher=self.code_launcher, allowed_tools=self.code_tools)
        anchor = N3CodeAnalysisEvidenceAnchorService(self.truth, source_commit=self.source_commit,
            state_root=str(self.code_launcher.state_root))
        promotion = N3CodeAnalysisCandidatePromotionService(self.truth, state_root=str(self.code_launcher.state_root), **common)
        review = N3CodeAnalysisReviewService(self.truth, evaluator=self.code_evaluator, **common)
        holds = []
        for target, task_id in zip(code['targets'], code['workitem_ids']):
            task = self._one('rc7_task', task_id=task_id)
            scope = dict(release_batch_id=release_batch_id, target_id=target['target_id'])
            if task['state'] == 'LEASED':
                handoff.handoff(**scope)
            elif task['state'] not in {'RUNNING', 'OUTPUT_PRODUCED', 'PASS', 'REPAIR_REQUIRED'}:
                holds.append(task_id)
                continue
            anchor.anchor(**scope)
            promotion.promote(**scope)
            review.review(**scope)
        if holds:
            return dict(status='HOLD', reason='N3_CODE_REVIEW_RECOVERY_REQUIRED', workitem_ids=holds)
        return gate.complete(release_batch_id=release_batch_id)
