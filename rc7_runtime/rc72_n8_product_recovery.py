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
        # Do not accidentally repair one failure while ignoring siblings.
        if len(admitted)!=1:
            raise ContractError('N8_PRODUCT_FAILED_ATTEMPT_NOT_UNIQUE')
        p,attempt=admitted[0]
        if p['mission_id']!=batch['mission_id'] or p['release_batch_id']!=release_batch_id:
            raise ContractError('N8_PRODUCT_ATTEMPT_SCOPE_CHANGED')
        diag=self.truth.query('rc72_diagnosis_case',source_binding_id=p['binding_id'])
        if not edges:
            # The native N7 runner can fail its process/tool checks before
            # N7Pipeline calls N8. Recover only a *real* frozen failed Attempt.
            # The diagnosis service itself creates an R1 DIAGNOSIS transition
            # and independent reviewers. No caller passes a failure class.
            if n7['state']!='RUNNING' or n8['state']!='NOT_STARTED' or diag:
                raise ContractError('N8_PRODUCT_ACCEPTED_N7_FAILURE_TRANSITION_REQUIRED')
            self.diagnosis.run(p['preparation_id'])
            return self._failure(release_batch_id)
        if len(edges)!=1 or len(diag)!=1:
            raise ContractError('N8_PRODUCT_ACCEPTED_N7_FAILURE_TRANSITION_REQUIRED')
        case=diag[0]
        if (case['mission_id']!=p['mission_id']
                or case['source_attempt_id']!=p['attempt_id']
                or case['transition_id']!=edges[0]['transition_id']
                or case['failure_evidence_refs']!=edges[0]['evidence_refs']
                or not set(attempt['evidence_refs']).issubset(set(edges[0]['evidence_refs']))):
            raise ContractError('N8_PRODUCT_ORIGINAL_FAILURE_EVIDENCE_CHANGED')
        for eid in edges[0]['evidence_refs']:
            ev=self._one('rc7_evidence',evidence_id=eid)
            if ev['mission_id']!=p['mission_id']:
                raise ContractError('N8_PRODUCT_FOREIGN_FAILURE_EVIDENCE')
        return batch,n7,n8,p

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
