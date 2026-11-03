"""Read-only full-denominator obligation rollup from actual accepted N7 proof.

Approved secondary coverage uses the same original Case/Attempt, not fabricated
ETUs, copied Cases, caller PASS flags or a second physical business invocation.
"""
from dataclasses import asdict

from .models import ContractError
from .rc72_canonical_design import CanonicalDesignService
from .rc72_n7_pipeline import N7PipelineService


class AcceptedObligationExecutionProof:
    def __init__(self, pipeline):
        if not isinstance(pipeline, N7PipelineService):
            raise ContractError('OBLIGATION_PROOF_NATIVE_N7_REQUIRED')
        self.pipeline = pipeline
        self.truth, self.release_id, self.source_commit = pipeline.truth, pipeline.release_id, pipeline.source_commit

    def audit(self, *, release_batch_id):
        from .rc72_ledger_lock import ledger_lock
        with ledger_lock(self.truth, busy='OBLIGATION_PROOF_LEDGER_BUSY'):
            return self._audit_locked(release_batch_id=release_batch_id)

    def _audit_locked(self, *, release_batch_id):
        one = self.pipeline.preparation._one
        batch = one('rc72_release_batch', release_batch_id=release_batch_id)
        node = one('rc72_mission_node', mission_id=batch['mission_id'], node_type='N7_EXECUTION')
        if batch['release_id'] != self.release_id or node['state'] != 'PASS':
            raise ContractError('OBLIGATION_PROOF_ACCEPTED_N7_REQUIRED')
        # Re-audit signed process/cleanup/source/capture/reviewer/WorkItem/Gate
        # facts. This accepted audit never repairs journal writes or dispatches.
        deliveries = [d for d in self.truth.query('rc72_node_delivery', mission_node_id=node['mission_node_id'])
                      if d['delivery_id'] in node['delivery_refs'] and d['version'] == node['active_delivery_version']]
        if len(deliveries) != 1 or len(deliveries[0]['artifact_refs']) != 1:
            raise ContractError('OBLIGATION_PROOF_ACTIVE_N7_DELIVERY_REQUIRED')
        accepted = self.pipeline.finalization.audit(deliveries[0]['artifact_refs'][0])
        if accepted.get('state') != 'N7_PASS':
            raise ContractError('OBLIGATION_PROOF_N7_AUDIT_NOT_ACCEPTED')
        review = one('rc72_n7_execution_review', review_result_id=accepted['review_result_id'])
        bundle = one('rc72_n7_evidence_bundle', bundle_id=review['bundle_id'])
        plan = one('rc72_n7_execution_plan', plan_id=bundle['plan_id'])
        design = CanonicalDesignService(self.truth, release_id=self.release_id,
            source_commit=self.source_commit).load(release_batch_id=release_batch_id)
        results = {r['case_id']: r for r in bundle['case_results']}
        items = {r['case_id']: r for r in plan['items']}
        cases = {r['tc_id']: r for r in design.cases}
        if (len(results) != len(bundle['case_results']) or len(items) != len(plan['items'])
                or set(results) != set(cases) or set(items) != set(cases)):
            raise ContractError('OBLIGATION_PROOF_CASE_DENOMINATOR_MISMATCH')
        etus = []
        for etu_id in sorted({r['etu_id'] for r in items.values()}):
            etu = one('rc72_etu', etu_id=etu_id)
            members = sorted(k for k, v in items.items() if v['etu_id'] == etu_id)
            if (etu['mission_id'] != batch['mission_id'] or etu['release_batch_id'] != release_batch_id
                    or etu['state'] not in {'REGISTERED','READY','LEASED','RUNNING','EVIDENCE_READY','PASS'}
                    or sorted(etu['case_ids']) != members):
                raise ContractError('OBLIGATION_PROOF_ETU_SCOPE_MISMATCH')
            etus.append(dict(etu_id=etu_id, case_ids=members,
                attempt_ids=[results[k]['attempt_id'] for k in members]))
        obligations = []
        for obligation in design.obligations:
            oid = obligation.obligation_id
            stored = one('rc72_test_obligation', obligation_id=oid)
            expected = asdict(obligation)
            ignored = {'status', 'created_at', 'updated_at'}
            if any(stored.get(k) != v for k, v in expected.items() if k not in ignored):
                raise ContractError('OBLIGATION_PROOF_CANONICAL_OBLIGATION_CHANGED')
            members = sorted(k for k, c in cases.items() if c['obligation_id'] == oid
                or any(link['subject_id'] == oid for link in c.get('coverage_links', [])))
            if not members:
                raise ContractError('OBLIGATION_PROOF_OBLIGATION_WITHOUT_CASE')
            obligations.append(dict(obligation_id=oid, case_ids=members,
                secondary_case_ids=[k for k in members if cases[k]['obligation_id'] != oid],
                source_case_sha256s={k: cases[k]['source_case_sha256'] for k in members},
                attempt_ids=[results[k]['attempt_id'] for k in members],
                etu_ids=sorted({items[k]['etu_id'] for k in members})))
        return dict(release_batch_id=release_batch_id, source_commit=self.source_commit,
            mission_id=batch['mission_id'], n4_delivery_id=design.delivery['delivery_id'],
            n4_gate_id=design.gate['gate_id'], n7_gate_id=accepted['gate_id'],
            bundle_id=bundle['bundle_id'], review_result_id=accepted['review_result_id'],
            verified_obligation_ids=[r['obligation_id'] for r in obligations],
            obligations=obligations, etus=etus, case_count=len(cases),
            attempt_ids=sorted({r['attempt_id'] for r in results.values()}),
            field_verified=False, bank_final=False)
