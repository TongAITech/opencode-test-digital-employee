"""Production N8 non-bypass failure admission and real scoped-data recovery.

This is the ReleaseBatch entrypoint, not a fixture callback. An N7 failure is
not automatically a product defect or a permission to re-run a business action.
Only original signed N7 Attempt/Process/Review and the canonical N7->N8
diagnosis transition may enter this service. Existing N5 repair is only
*consumed* after accepted independent evidence; this service never invents
a verified DataRef, target restoration, new Case or PASS Gate.
"""
from .models import ContractError
from .rc72_domain import AutonomousMissionNode as Node
from .rc72_n7_pipeline import N7PipelineService
from .rc72_n8_execution_diagnosis import ExecutionDiagnosisService
from .rc72_n8_repair_boundary import RepairBoundaryService
from .rc72_n8_retry_continuation import DataRepairContinuationService


class NativeN8ProductRecoveryService:
    def __init__(self, n7):
        if (not isinstance(n7, N7PipelineService)
                or not isinstance(n7.diagnosis, ExecutionDiagnosisService)
                or n7.diagnosis.preparation is not n7.preparation):
            raise ContractError('N8_PRODUCT_NATIVE_N7_AND_DIAGNOSIS_REQUIRED')
        self.n7, self.diagnosis, self.truth = n7, n7.diagnosis, n7.truth
        self.release_id, self.source_commit = n7.release_id, n7.source_commit
        # Reuse the same exact cleanup adapter as N7, but only through the
        # separately signed N8 repair-authority boundary.
        self.boundary = RepairBoundaryService(self.diagnosis, cleanup_adapters=n7.cleanup.adapters)
        self.continuation = DataRepairContinuationService(self.diagnosis)

    def _one(self, kind, **filters):
        rows=self.truth.query(kind, **filters)
        if len(rows)!=1:
            raise ContractError('N8_PRODUCT_R1_NOT_UNIQUE:'+kind)
        return rows[0]

    def _failure(self,release_batch_id):
        batch=self._one('rc72_release_batch',release_batch_id=release_batch_id)
        if batch['release_id']!=self.release_id:
            raise ContractError('N8_PRODUCT_RELEASE_CHANGED')
        nodes={n['node_type']:n for n in self.truth.query('rc72_mission_node',mission_id=batch['mission_id'])}
        n7=nodes.get('N7_EXECUTION');n8=nodes.get('N8_DIAGNOSIS_RECOVERY')
        if n7 is None or n8 is None:
            raise ContractError('N8_PRODUCT_NODE_DENOMINATOR_MISSING')
        if n7['state'] not in {'NOT_STARTED','RUNNING','NEEDS_REVISION','BLOCKED','STALE','READY'}:
            raise ContractError('N8_PRODUCT_NOT_A_FAILED_N7')
        # A ready N8 node without its actual N7 failure transition is never
        # permission to touch N5 repair or classify a failure.
        edges=[e for e in self.truth.query('rc72_node_transition',mission_id=batch['mission_id'])
               if e.get('kind')=='DIAGNOSIS'
               and e.get('from_node_type')=='N7_EXECUTION'
               and e.get('to_node_type')=='N8_DIAGNOSIS_RECOVERY'
               and e.get('from_mission_node_id')==n7['mission_node_id']
               and e.get('to_mission_node_id')==n8['mission_node_id']
               and e.get('evidence_refs')]
        attempts=self.truth.query('rc72_n7_execution_preparation',release_batch_id=release_batch_id)
        admitted=[]
        for p in attempts:
            if p.get('release_id')!=self.release_id or p.get('source_commit')!=self.source_commit:
                raise ContractError('N8_PRODUCT_PREPARATION_SCOPE_CHANGED')
            current=self.truth.query('execution_attempt',attempt_id=p['attempt_id'])
            if len(current)>1:
                raise ContractError('N8_PRODUCT_ATTEMPT_NOT_UNIQUE')
            if current and current[0]['status']=='BLOCKED' and current[0]['reason']!='CLEANUP_AND_EVIDENCE_CLOSURE_REQUIRED':
                admitted.append((p,current[0]))
        # An N7 tool or precondition may fail before ExecutionEvidenceService
        # wrote its original Attempt.  Materialize only the authenticated
        # already-returned/failed dispatch evidence, never launch a runner or
        # infer that a missing Attempt means PASS.
        if not admitted and n7['state']=='RUNNING' and n8['state']=='NOT_STARTED':
            pending=[]
            for p in attempts:
                dispatch=self.truth.query('rc72_n7_tool_dispatch',preparation_id=p['preparation_id'])
                historical=self.truth.query('execution_attempt',attempt_id=p['attempt_id'])
                if (len(dispatch)==1 and dispatch[0]['state'] in {'FAILED','RETURNED'}
                        and not historical):
                    pending.append(p)
            if len(pending)==1:
                self.diagnosis.evidence.record(pending[0]['preparation_id'])
                return self._failure(release_batch_id)
        # Historical BLOCKED Attempts remain immutable by design. A repaired
        # failure cannot be deleted to make a second N7 failure appear unique:
        # select only the strictly newest generation with a *complete*, signed
        # repair -> new binding lineage for every earlier blocked Attempt.
        if len(admitted)>1:
            newest=max(p['attempt_generation'] for p,_ in admitted)
            current=[member for member in admitted if member[0]['attempt_generation']==newest]
            if len(current)!=1:
                raise ContractError('N8_PRODUCT_CONCURRENT_FAILURE_SCOPE_AMBIGUOUS')
            candidate=current[0][0]
            by_attempt={row['attempt_id']:row for row in attempts}
            for old,_ in admitted:
                if old['attempt_id']==candidate['attempt_id']:
                    continue
                prior_case=self._one('rc72_diagnosis_case',source_binding_id=old['binding_id'])
                repair=self._one('rc72_diagnosis_repair',diagnosis_id=prior_case['diagnosis_id'])
                recovered=self._one('rc72_diagnosis_recovery',diagnosis_id=prior_case['diagnosis_id'])
                successor=by_attempt.get(recovered['replacement_attempt_id'])
                binding=self._one('rc72_workitem_attempt_binding',
                    binding_id=recovered['replacement_binding_id'])
                if (prior_case['source_attempt_id']!=old['attempt_id']
                        or repair['original_attempt_id']!=old['attempt_id']
                        or recovered['original_attempt_id']!=old['attempt_id']
                        or successor is None
                        or successor['attempt_id']!=binding['attempt_id']
                        or successor['workitem_id']!=old['workitem_id']
                        or successor['case_id']!=old['case_id']
                        or successor['attempt_generation']!=old['attempt_generation']+1
                        or binding['parent_attempt_id']!=old['attempt_id']):
                    raise ContractError('N8_PRODUCT_HISTORICAL_FAILURE_UNRESOLVED')
            # Every prior failed generation has a genuine replacement. No
            # unrelated unresolved Case can be silently excluded.
            admitted=current
        if len(admitted)!=1:
            raise ContractError('N8_PRODUCT_FAILED_ATTEMPT_NOT_UNIQUE')
        p,attempt=admitted[0]
        if p['mission_id']!=batch['mission_id'] or p['release_batch_id']!=release_batch_id:
            raise ContractError('N8_PRODUCT_ATTEMPT_SCOPE_CHANGED')
        diag=self.truth.query('rc72_diagnosis_case',source_binding_id=p['binding_id'])
        if len(diag)>1:
            raise ContractError('N8_PRODUCT_DIAGNOSIS_NOT_UNIQUE')
        if not diag:
            # Older N8 deliveries do not certify the new failed Attempt.
            # Only a currently RUNNING N7 may issue the next independent
            # process diagnosis and persist a fresh signed transition.
            if (n7['state']!='RUNNING' or n8['state'] not in {'NOT_STARTED','PASS'}
                    or attempt['status']!='BLOCKED'):
                raise ContractError('N8_PRODUCT_ACCEPTED_N7_FAILURE_TRANSITION_REQUIRED')
            self.diagnosis.run(p['preparation_id'])
            return self._failure(release_batch_id)
        case=diag[0]
        matched=[edge for edge in edges if edge['transition_id']==case['transition_id']]
        if len(matched)!=1:
            raise ContractError('N8_PRODUCT_ACCEPTED_N7_FAILURE_TRANSITION_REQUIRED')
        edge=matched[0]
        if (case['mission_id']!=p['mission_id']
                or case['source_attempt_id']!=p['attempt_id']
                or case['failure_evidence_refs']!=edge['evidence_refs']
                or not set(attempt['evidence_refs']).issubset(set(edge['evidence_refs']))):
            raise ContractError('N8_PRODUCT_ORIGINAL_FAILURE_EVIDENCE_CHANGED')
        for eid in edge['evidence_refs']:
            ev=self._one('rc7_evidence',evidence_id=eid)
            if ev['mission_id']!=p['mission_id']:
                raise ContractError('N8_PRODUCT_FOREIGN_FAILURE_EVIDENCE')
        return batch,n7,n8,p

    def audit(self,*,release_batch_id):
        """Read-only historical N8 admission after fresh N7 became PASS.

        An N8 PASS is an accepted diagnosis, not permission to reuse the
        original N7 Attempt. Reopen only the independent original proof on
        cold recovery and leave repaired N5/N6/N7 deliveries untouched.
        """
        batch=self._one('rc72_release_batch',release_batch_id=release_batch_id)
        if batch.get('release_id')!=self.release_id:
            raise ContractError('N8_PRODUCT_HISTORICAL_RELEASE_CHANGED')
        n7=self._one('rc72_mission_node',mission_id=batch['mission_id'],node_type='N7_EXECUTION')
        n8=self._one('rc72_mission_node',mission_id=batch['mission_id'],node_type='N8_DIAGNOSIS_RECOVERY')
        if n7['state']!='PASS' or n8['state']!='PASS' or not n8['gate_refs']:
            raise ContractError('N8_PRODUCT_HISTORICAL_GATE_REQUIRED')
        cases=self.truth.query('rc72_diagnosis_case',mission_id=batch['mission_id'])
        if not cases:
            raise ContractError('N8_PRODUCT_HISTORICAL_DIAGNOSIS_REQUIRED')
        # This cold/re-entry check must not create new events. R1 already
        # contains a complete and independently reviewed N8 receipt for
        # every affected source Attempt; the original source is re-read.
        before=self.truth.store.path.read_bytes()
        verified=[]
        for case in cases:
            p=self._one('rc72_n7_execution_preparation',binding_id=case['source_binding_id'])
            if p['release_batch_id']!=release_batch_id or p['source_commit']!=self.source_commit:
                raise ContractError('N8_PRODUCT_HISTORICAL_SOURCE_CHANGED')
            receipt=self.diagnosis._verify(self._one('rc72_n8_process_diagnosis',diagnosis_id=case['diagnosis_id']))
            if receipt['preparation_id']!=p['preparation_id'] or receipt['result']['failure_class']=='UNKNOWN':
                raise ContractError('N8_PRODUCT_HISTORICAL_PROOF_CHANGED')
            result=self.diagnosis.run(p['preparation_id'])
            if result.get('diagnosis_id')!=case['diagnosis_id']:
                raise ContractError('N8_PRODUCT_HISTORICAL_ACCEPTANCE_CHANGED')
            verified.append(case['diagnosis_id'])
        if self.truth.store.path.read_bytes()!=before:
            raise ContractError('N8_PRODUCT_HISTORICAL_AUDIT_MUST_BE_READONLY')
        return dict(status='AUDITED',reason='N8_ACCEPTED_HISTORICAL_DIAGNOSIS_VERIFIED',
            diagnosis_ids=sorted(verified),field_verified=False,bank_final=False)

    def complete(self,*,release_batch_id):
        batch,n7,n8,p=self._failure(release_batch_id)
        result=self.diagnosis.run(p['preparation_id'])
        if result['failure_class']=='UNKNOWN':
            return dict(status='HOLD',reason='N8_UNKNOWN_CAUSE_NO_AUTO_PASS',
                preparation_id=p['preparation_id'],diagnosis_id=result['diagnosis_id'],
                failure_class='UNKNOWN')
        if result['failure_class']=='VALID_TEST_FAILURE':
            # Distinct N9 professional qualification needs real confirmed
            # independent RCA before product defect or fresh N7 execution.
            from .rc72_n9_professional_intake import NativeN9ProfessionalIntakeService
            candidate=NativeN9ProfessionalIntakeService(self.n7).queue_reproduction(
                preparation_id=p['preparation_id'],diagnosis_id=result['diagnosis_id'])
            return dict(status='HOLD',reason='N8_PROFESSIONAL_N9_QUALIFICATION_REQUIRED',
                preparation_id=p['preparation_id'],diagnosis_id=result['diagnosis_id'],
                failure_class=result['failure_class'],
                qualification_workitem_id=candidate['qualification_workitem_id'],
                defect_confirmed=False)
        if result['failure_class']=='TEST_DATA_GAP':
            # Actual cleanup is scope fenced, resource-leased and proved by
            # canonical frozen Oracle and two signed cleanup receipts.
            fence=self.boundary.open(p['preparation_id'])
            if fence['state']!='REPAIR_OPEN':
                return dict(status='HOLD',reason='N8_SCOPED_COMPENSATION_NOT_VERIFIED',
                    preparation_id=p['preparation_id'],failure_class='TEST_DATA_GAP',
                    boundary_id=fence['boundary_id'])
            outcome=self._one('rc72_diagnosis_outcome',diagnosis_id=result['diagnosis_id'])
            accepted=self.truth.query('rc72_diagnosis_repair',diagnosis_id=result['diagnosis_id'])
            if not accepted:
                return dict(status='HOLD',reason='N8_VERIFIED_N5_REPAIR_REQUIRED',
                    preparation_id=p['preparation_id'],diagnosis_id=result['diagnosis_id'],
                    boundary_id=fence['boundary_id'],failure_class='TEST_DATA_GAP',
                    affected_data_refs=list(outcome['affected_refs']),
                    # Client or approved N5 service may now prepare and verify
                    # the *original* DataRefs. Absence is not an implicit PASS.
                    source_node='N5_TEST_DATA',field_verified=False,bank_final=False)
            if len(accepted)!=1:
                raise ContractError('N8_PRODUCT_REPAIR_NOT_UNIQUE')
            plan=self.continuation.reconcile(p['preparation_id'])
            return dict(status='CONTINUE',reason='N8_ACCEPTED_N5_REPAIR_N7_RETRY_READY',
                preparation_id=p['preparation_id'],diagnosis_id=result['diagnosis_id'],
                recovery_plan_id=plan['plan_id'],original_attempt_id=p['attempt_id'],
                field_verified=False,bank_final=False)
        # Capability/provider/flaky/other classification must be handled by
        # an explicitly admitted, scoped provider. Never guess or fall through
        # to N9, and never replay an original business operation.
        return dict(status='HOLD',reason='N8_SCOPED_RECOVERY_PROVIDER_REQUIRED',
            preparation_id=p['preparation_id'],diagnosis_id=result['diagnosis_id'],
            failure_class=result['failure_class'],
            action=result.get('action'),field_verified=False,bank_final=False)
