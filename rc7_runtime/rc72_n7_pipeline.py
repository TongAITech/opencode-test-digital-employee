"""Concrete formal N7 process/cleanup/evidence route; no success callbacks."""
from .models import ContractError
from .rc72_formal_runner import FormalN7RunnerAdapter
from .rc72_n7_execution_preparation import ExecutionPreparationService
from .rc72_n7_tool_dispatch import SignedToolDispatchService
from .rc72_n7_cleanup import ExecutionCleanupService
from .rc72_n7_evidence_review import ExecutionEvidenceReviewService
from .rc72_n7_finalization import ExecutionFinalizationService


class N7PipelineService:
    def __init__(self, preparation, *, runner, capture_root,
                 captain_scheduler=None, captain_session_id=None,
                 captain_lease_id=None, team_id=None):
        if (not isinstance(preparation, ExecutionPreparationService)
                or not isinstance(runner, FormalN7RunnerAdapter) or runner.preparation is not preparation):
            raise ContractError('RC72_N7_PIPELINE_FORMAL_RUNTIME_REQUIRED')
        if runner.environment_adapter is None:
            raise ContractError('RC72_N7_PIPELINE_EXECUTION_ENVIRONMENT_REQUIRED')
        self.preparation, self.runner = preparation, runner
        self.truth, self.release_id, self.source_commit = preparation.truth, preparation.release_id, preparation.source_commit
        self.captain_scheduler = captain_scheduler
        self.captain_session_id, self.captain_lease_id, self.team_id = (
            captain_session_id, captain_lease_id, team_id)
        if any(value is not None for value in (
                captain_scheduler, captain_session_id, captain_lease_id, team_id)):
            from .rc72_captain_scheduling import CaptainFencedWorkItemScheduler
            if (not isinstance(captain_scheduler, CaptainFencedWorkItemScheduler)
                    or captain_scheduler.truth is not self.truth
                    or captain_scheduler.release_id != self.release_id
                    or any(not isinstance(value, str) or not value.strip() for value in (
                        captain_session_id, captain_lease_id, team_id))):
                raise ContractError('RC72_N7_PIPELINE_CAPTAIN_SCOPE_REQUIRED')
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

    def _prepare_governed_item(self, plan, item):
        """Use the production N7 pipeline's exact planned Case/ETU/WorkItem.

        The frozen Case and data refs (not a prompt) determine scoped Worker
        input. The Captain is permitted to allocate the WorkItem, but may not
        claim a Test PASS or bypass formal N7 oracle/cleanup/review.
        """
        workitem_id = item['workitem_id']
        existing = self.truth.query(
            'rc72_n7_execution_preparation',
            plan_id=plan['plan_id'], workitem_id=workitem_id)
        if len(existing) > 1:
            raise ContractError('RC72_N7_PIPELINE_PREPARATION_NOT_UNIQUE')
        if existing:
            current = existing[0]
            captain_leases = self.truth.query(
                'rc72_captain_dispatch_lease', mission_id=plan['mission_id'])
            if captain_leases and self.captain_scheduler is None:
                # A legacy N7Pipeline instance must not drive or replay a
                # prepared WorkItem belonging to a Captain-governed Mission.
                # Tool-level fencing alone would authenticate the *old* owner
                # without authenticating this invoking pipeline's identity.
                raise ContractError('RC72_N7_PIPELINE_GOVERNED_ENTRY_REQUIRED')
            if self.captain_scheduler is not None:
                if not current.get('captain_admission_id'):
                    raise ContractError('RC72_N7_PIPELINE_UNFENCED_PREPARATION_FORBIDDEN')
                admission = self.truth.query(
                    'rc72_captain_etu_admission',
                    admission_id=current['captain_admission_id'])
                if (len(admission) != 1
                        or admission[0].get('mission_id') != plan['mission_id']
                        or admission[0].get('workitem_id') != workitem_id
                        or admission[0].get('etu_id') != item['etu_id']
                        or admission[0].get('worker_id') != current.get('worker_id')
                        or admission[0].get('session_id') != current.get('session_id')
                        or admission[0].get('team_id') != self.team_id
                        or admission[0].get('captain_session_id') != self.captain_session_id
                        or admission[0].get('captain_lease_id') != self.captain_lease_id):
                    raise ContractError('RC72_N7_PIPELINE_EXISTING_CAPTAIN_SCOPE_MISMATCH')
                # Recheck current owner; a matching historical record is not
                # an authority to execute after handoff or TTL expiration.
                self.captain_scheduler.fencer.assert_owner(
                    mission_id=plan['mission_id'],
                    lease_id=self.captain_lease_id,
                    captain_session_id=self.captain_session_id)
            return current
        if self.captain_scheduler is None:
            return self.preparation.prepare(
                plan_id=plan['plan_id'], workitem_id=workitem_id)
        etu = self.preparation._one('rc72_etu', etu_id=item['etu_id'])
        contract = self.preparation._one(
            'rc72_n6_executable_contract', contract_id=item['contract_id'])
        admission = self.captain_scheduler.dispatch_etu(
            mission_id=plan['mission_id'], team_id=self.team_id,
            captain_session_id=self.captain_session_id,
            captain_lease_id=self.captain_lease_id,
            role=etu['test_level'] + '_EXECUTE', etu_id=item['etu_id'],
            workitem_id=workitem_id,
            canonical_refs=dict(
                etu_refs=[item['etu_id']],
                executable_contract_refs=[item['contract_id']],
                data_refs=[value['data_ref'] for value in contract['data_refs']]))
        return self.preparation.prepare(
            plan_id=plan['plan_id'], workitem_id=workitem_id,
            fenced_admission=admission)

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
                p = self._prepare_governed_item(plan, item)
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
        return dict(status='HOLD',reason='N9_FAILURE_QUALIFICATION_REQUIRED' if result['failure_class']=='VALID_TEST_FAILURE'
                    else 'N7_EXECUTION_DIAGNOSIS_REQUIRED',preparation_id=preparation_id,
                    diagnosis_id=result['diagnosis_id'],failure_class=result['failure_class'],
                    next_node=result.get('responsible_node'))

    def _finalize(self, bundle_id):
        result = self.finalization.finalize(bundle_id)
        if result.get('state') != 'N7_PASS':
            return dict(status='HOLD', reason='N7_INDEPENDENT_REVIEW_NOT_ACCEPTED',
                        bundle_id=bundle_id, review_result_id=result.get('review_result_id'))
        return result
