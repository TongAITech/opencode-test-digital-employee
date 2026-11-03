"""Concrete formal N7 process/cleanup/evidence route; no success callbacks."""
from .models import ContractError
from .rc72_formal_runner import FormalN7RunnerAdapter
from .rc72_n7_execution_preparation import ExecutionPreparationService
from .rc72_n7_tool_dispatch import SignedToolDispatchService
from .rc72_n7_cleanup import ExecutionCleanupService
from .rc72_n7_evidence_review import ExecutionEvidenceReviewService
from .rc72_n7_finalization import ExecutionFinalizationService


class N7PipelineService:
    def __init__(self, preparation, *, runner, capture_root):
        if (not isinstance(preparation, ExecutionPreparationService)
                or not isinstance(runner, FormalN7RunnerAdapter) or runner.preparation is not preparation):
            raise ContractError('RC72_N7_PIPELINE_FORMAL_RUNTIME_REQUIRED')
        if runner.environment_adapter is None:
            raise ContractError('RC72_N7_PIPELINE_EXECUTION_ENVIRONMENT_REQUIRED')
        self.preparation, self.runner = preparation, runner
        self.truth, self.release_id, self.source_commit = preparation.truth, preparation.release_id, preparation.source_commit
        tools = {t for values in preparation.tool_registry.values() for t in values}
        self.dispatch = SignedToolDispatchService(preparation, adapters={t: runner for t in tools})
        self.cleanup = ExecutionCleanupService(preparation, adapters={t: runner.environment_adapter.cleanup for t in tools})
        self.review = ExecutionEvidenceReviewService(preparation, adapter_output_root=runner.root, capture_root=capture_root)
        self.finalization = ExecutionFinalizationService(self.review)
        from .rc72_conclusive_failure_evidence import ConclusiveAssertionFailureEvidence
        from .rc72_n8_execution_diagnosis import ExecutionDiagnosisService
        self.failure_evidence = ConclusiveAssertionFailureEvidence(self.review)
        self.diagnosis = ExecutionDiagnosisService(preparation,evidence_root=self.review.capture_root/'diagnosis',
            failure_evidence=self.failure_evidence)

    def complete(self, *, release_batch_id):
        batch = self.preparation._one('rc72_release_batch', release_batch_id=release_batch_id)
        node = self.preparation._one('rc72_mission_node', mission_id=batch['mission_id'], node_type='N7_EXECUTION')
        if node['state']=='NEEDS_REVISION':
            failed = [p for p in self.truth.query('rc72_n7_execution_preparation',release_batch_id=release_batch_id)
                      if self.failure_evidence.rows(p['preparation_id'])]
            if len(failed)==1:
                return self._diagnose_failure(failed[0]['preparation_id'])
            return dict(status='HOLD',reason='N7_EXECUTION_DIAGNOSIS_REQUIRED')
        if node['state'] in {'PASS', 'REVIEW_PENDING'}:
            bundles = self.truth.query('rc72_n7_evidence_bundle', release_batch_id=release_batch_id)
            current = [b for b in bundles if b.get('source_commit') == self.source_commit
                       and b.get('release_id') == self.release_id
                       and any(b['bundle_id'] in d.get('artifact_refs', [])
                               and d['delivery_id'] in node.get('delivery_refs', [])
                               and d['version'] == node.get('active_delivery_version')
                               for d in self.truth.query('rc72_node_delivery', mission_node_id=node['mission_node_id']))]
            if len(current) == 1:
                return self._finalize(current[0]['bundle_id'])
            if node['state'] in {'PASS', 'REVIEW_PENDING'}:
                raise ContractError('RC72_N7_PIPELINE_FINALIZED_BUNDLE_NOT_UNIQUE')
        plan = self.preparation.planning.plan(release_batch_id=release_batch_id)
        reuse = set()
        if plan.get('recovery_id'):
            from .rc72_n8_retry_truth import assert_reconciled_plan
            decisions = assert_reconciled_plan(self.preparation.planning, plan)['member_decisions']
            reuse = {d['workitem_id'] for d in decisions if d['disposition']=='REUSE_FOR_CURRENT_REVIEW'}
        node = self.preparation._one('rc72_mission_node', mission_id=plan['mission_id'], node_type='N7_EXECUTION')
        if node['state'] not in {'PASS','REVIEW_PENDING'}:
            for item in plan['items']:
                if item['workitem_id'] in reuse:
                    continue  # Native reconciliation authenticates historical scope.
                existing = self.truth.query('rc72_n7_execution_preparation', plan_id=plan['plan_id'], workitem_id=item['workitem_id'])
                if len(existing)>1:
                    raise ContractError('RC72_N7_PIPELINE_PREPARATION_NOT_UNIQUE')
                p = existing[0] if existing else self.preparation.prepare(plan_id=plan['plan_id'], workitem_id=item['workitem_id'])
                calls = self.truth.query('rc72_n7_tool_dispatch', preparation_id=p['preparation_id'])
                if not calls:
                    result = self.dispatch.dispatch(p['preparation_id'])
                elif len(calls)==1:
                    result = calls[0]
                else:
                    raise ContractError('RC72_N7_PIPELINE_DISPATCH_NOT_UNIQUE')
                if result['state']!='RETURNED':
                    return dict(status='HOLD', reason='N7_EXECUTION_DIAGNOSIS_REQUIRED', preparation_id=p['preparation_id'])
                observed = self.review.evidence.observation(p['preparation_id'])
                from .rc72_formal_runner import verified_formal_receipt
                formal = verified_formal_receipt(self.preparation,observed[0],observed[1],result['raw_result'])
                if not formal or formal['runner_result']['exit_code']!=0 or not formal['required_tool_observed']:
                    if formal is not None:
                        self.review.evidence.record(p['preparation_id'])
                    return dict(status='HOLD',reason='N7_EXECUTION_DIAGNOSIS_REQUIRED',preparation_id=p['preparation_id'])
                # Cleanup validates the signed returned execution and reuses its
                # own signed receipts; never restore business authority to replay.
                cleaned = self.cleanup.run(p['preparation_id'])
                if cleaned['state']!='CLEANUP_VERIFIED':
                    return dict(status='HOLD', reason='N7_CLEANUP_DIAGNOSIS_REQUIRED', preparation_id=p['preparation_id'])
                if observed[-1]['passed'] is False:
                    try:
                        self.failure_evidence.build(p['preparation_id'])
                    except ContractError as exc:
                        return dict(status='HOLD',reason='N7_CONCLUSIVE_FAILURE_EVIDENCE_INCOMPLETE',
                            preparation_id=p['preparation_id'],evidence_error=str(exc))
                    return self._diagnose_failure(p['preparation_id'])
        bundle = self.review.build(plan['plan_id'])
        if bundle['known_gaps']:
            return dict(status='HOLD', reason='N7_EVIDENCE_REVIEW_NOT_ACCEPTED', bundle_id=bundle['bundle_id'])
        return self._finalize(bundle['bundle_id'])

    def _diagnose_failure(self, preparation_id):
        result = self.diagnosis.run(preparation_id)
        professional = {}
        if result['failure_class'] == 'VALID_TEST_FAILURE':
            # This is an accepted *business discrepancy*, not a confirmed
            # product defect. Own the N9 reproduction queue in production and
            # keep the original N7 Attempt immutable across cold re-entry.
            from .rc72_n9_professional_intake import NativeN9ProfessionalIntakeService
            queued = NativeN9ProfessionalIntakeService(self).queue_reproduction(
                preparation_id=preparation_id, diagnosis_id=result['diagnosis_id'])
            professional = dict(reproduction_workitem_id=queued['reproduction_workitem_id'],
                                defect_confirmed=False)
        return dict(status='HOLD',reason='N9_FAILURE_QUALIFICATION_REQUIRED' if result['failure_class']=='VALID_TEST_FAILURE'
                    else 'N7_EXECUTION_DIAGNOSIS_REQUIRED',preparation_id=preparation_id,
                    diagnosis_id=result['diagnosis_id'],failure_class=result['failure_class'],
                    next_node=result.get('responsible_node'),**professional)

    def _finalize(self, bundle_id):
        result = self.finalization.finalize(bundle_id)
        if result.get('state') != 'N7_PASS':
            return dict(status='HOLD', reason='N7_INDEPENDENT_REVIEW_NOT_ACCEPTED',
                        bundle_id=bundle_id, review_result_id=result.get('review_result_id'))
        return result
