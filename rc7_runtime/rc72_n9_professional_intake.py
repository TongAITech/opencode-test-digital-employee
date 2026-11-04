"""Professional N9 intake from a real N8-qualified business assertion failure.

An accepted discrepancy is *not* proof of a product defect. Queue governed,
independent reproduction against the original frozen Case/Attempt; do not
mark defects, repair, RCA or regression complete. Cold re-entry reauthenticates
signed process evidence and must not replay the business operation.
"""
from .closed_loop_control import ClosedLoopControlPlane
from .rc72_ledger_lock import ledger_lock
from .models import ContractError, Task
from .rc72_n7_execution_admission import _hash
from .rc72_domain import AutonomousMissionNode


class NativeN9ProfessionalIntakeService:
    def __init__(self, pipeline):
        from .rc72_n7_pipeline import N7PipelineService
        if not isinstance(pipeline, N7PipelineService):
            raise ContractError('N9_PROFESSIONAL_NATIVE_N7_REQUIRED')
        if pipeline.failure_evidence is None or pipeline.diagnosis is None:
            raise ContractError('N9_PROFESSIONAL_NATIVE_DIAGNOSIS_REQUIRED')
        self.pipeline, self.truth = pipeline, pipeline.truth
        self.release_id, self.source_commit = pipeline.release_id, pipeline.source_commit

    def _one(self, kind, **filters):
        rows = self.truth.query(kind, **filters)
        if len(rows) != 1:
            raise ContractError('N9_PROFESSIONAL_R1_NOT_UNIQUE:' + kind)
        return rows[0]

    def queue_reproduction(self, *, preparation_id, diagnosis_id):
        p=self._one('rc72_n7_execution_preparation',preparation_id=preparation_id)
        if p['release_id']!=self.release_id or p['source_commit']!=self.source_commit:
            raise ContractError('N9_PROFESSIONAL_SOURCE_CHANGED')
        attempt=self._one('execution_attempt',attempt_id=p['attempt_id'])
        receipt=self.pipeline.diagnosis._verify(
            self._one('rc72_n8_process_diagnosis',diagnosis_id=diagnosis_id))
        outcome=self._one('rc72_diagnosis_outcome',diagnosis_id=diagnosis_id)
        case=self._one('rc72_diagnosis_case',diagnosis_id=diagnosis_id)
        failure=self.pipeline.failure_evidence.audit(preparation_id)
        proof=failure['proof']
        result=receipt['result']
        if (receipt['preparation_id']!=preparation_id
                or receipt['source_commit']!=self.source_commit
                or receipt['release_id']!=self.release_id
                or result.get('failure_class')!='VALID_TEST_FAILURE'
                or result.get('confidence')!='COMPLETE_FROZEN_CONTRACT_DISCREPANCY'
                or result.get('affected_refs')!=[p['case_id']]
                or outcome['failure_class']!='VALID_TEST_FAILURE'
                or outcome['responsible_node']!='N9_DEFECT'
                or outcome.get('source_delivery_id')!=receipt['delivery_id']
                or outcome['source_attempt_id']!=p['attempt_id']
                or case['source_attempt_id']!=p['attempt_id']
                or case['source_binding_id']!=p['binding_id']
                or attempt['status']!='BLOCKED' or attempt.get('assertion_passed') is not False
                or proof['attempt_id']!=p['attempt_id'] or proof['case_id']!=p['case_id']
                or proof['contract_id']!=p['contract_id']
                or failure['evidence_id'] not in outcome['evidence_refs']
                or not outcome.get('gap_id')):
            raise ContractError('N9_PROFESSIONAL_ACCEPTED_DISCREPANCY_REQUIRED')
        node=self.pipeline.diagnosis.runtime.node_by_type(
            p['mission_id'],AutonomousMissionNode.N8_DIAGNOSIS_RECOVERY)
        gate_id='N8GATE-'+_hash([diagnosis_id,receipt['input_sha256']])[:24]
        gate=self._one('rc72_node_gate',gate_id=gate_id)
        if (node['state']!='PASS' or gate_id not in node['gate_refs']
                or gate['decision']!='PASS' or gate['delivery_id']!=receipt['delivery_id']
                or gate['reviewer_worker_id']!=receipt['reviewer_worker_id']
                or gate['reviewer_session_id']!=receipt['reviewer_session_id']
                or receipt['reviewer_worker_id'] in {p['worker_id'],receipt['diagnosis_worker_id']}
                or failure['evidence_id'] not in gate['evidence_refs']):
            raise ContractError('N9_PROFESSIONAL_INDEPENDENT_N8_GATE_REQUIRED')
        gap=self._one('rc7_gap',gap_id=outcome['gap_id'])
        if (gap['mission_id']!=p['mission_id'] or gap['target_node']!='N9_DEFECT'
                or gap['category']!='VALID_TEST_FAILURE'):
            raise ContractError('N9_PROFESSIONAL_ORIGINAL_GAP_REQUIRED')
        # A historical N8 PASS and an R1 Gap label alone are not N9 authority.
        # Revalidate the *entire* immutable semantic route, including its
        # exact original N8 delivery.  Without these checks a replaced Gap or
        # BackEdge can smuggle an independent-analyst Task past the review gate
        # when the original business failure is no longer its source.
        if (outcome.get('action')!='SEMANTIC_BACK_EDGE'
                or not outcome.get('back_edge_id')
                or not outcome.get('transition_id')
                or outcome.get('source_delivery_id')!=receipt['delivery_id']
                or gap.get('source_node')!='N8_DIAGNOSIS_RECOVERY'
                or gap.get('description')!=outcome.get('rationale')):
            raise ContractError('N9_PROFESSIONAL_SEMANTIC_ROUTE_REQUIRED')
        edge=self._one('rc72_back_edge',back_edge_id=outcome['back_edge_id'])
        transition=self._one('rc72_node_transition',transition_id=outcome['transition_id'])
        if (edge.get('mission_id')!=p['mission_id']
                or edge.get('gap_id')!=gap['gap_id']
                or edge.get('from_node')!='N8_DIAGNOSIS_RECOVERY'
                or edge.get('from_delivery_id')!=receipt['delivery_id']
                or edge.get('return_node')!='N9_DEFECT'
                or edge.get('reason')!='VALID_TEST_FAILURE'
                or edge.get('invalidated_refs')!=outcome.get('affected_refs')
                or transition.get('mission_id')!=p['mission_id']
                or transition.get('kind')!='BACK_EDGE'
                or transition.get('from_node_type')!='N8_DIAGNOSIS_RECOVERY'
                or transition.get('from_mission_node_id')!=node['mission_node_id']
                or transition.get('to_node_type')!='N9_DEFECT'
                or transition.get('back_edge_id')!=edge['back_edge_id']
                or transition.get('reason')!='VALID_TEST_FAILURE'
                or transition.get('evidence_refs')!=outcome.get('evidence_refs')):
            raise ContractError('N9_PROFESSIONAL_SEMANTIC_ROUTE_CHANGED')
        target=self.pipeline.diagnosis.runtime.node_by_type(
            p['mission_id'],AutonomousMissionNode.N9_DEFECT)
        if transition.get('to_mission_node_id')!=target['mission_node_id']:
            raise ContractError('N9_PROFESSIONAL_SEMANTIC_ROUTE_CHANGED')
        wid='N9QUAL-'+_hash([p['mission_id'],p['attempt_id'],diagnosis_id])[:24]
        plan=self._one('rc72_n7_execution_plan',plan_id=p['plan_id'])
        members=[item for item in plan['items'] if item['workitem_id']==p['workitem_id']]
        if (len(members)!=1 or members[0]['case_id']!=p['case_id']
                or members[0]['contract_id']!=p['contract_id']):
            raise ContractError('N9_PROFESSIONAL_FROZEN_CASE_REQUIRED')
        # These are real, approved N4 Case Artifacts rather than invented
        # r1:// pseudo-input schemes that the RC7 scheduler cannot lease.
        refs=list(members[0]['input_artifact_refs'])
        if not refs or any(not self.truth.query('rc7_artifact',artifact_id=ref) for ref in refs):
            raise ContractError('N9_PROFESSIONAL_APPROVED_CASE_ARTIFACT_REQUIRED')
        # Existing RC7 DefectReproductionExecutionService requires
        # EXECUTION / test_execution and a previously qualified PRODUCT_DEFECT
        # Gap. N8 VALID_TEST_FAILURE proves only a frozen discrepancy, not
        # product causality; it MUST NOT masquerade as that runnable service.
        # Admit a real defect_analysis qualification task first. Only after
        # independent RCA can the governed reproduction/fix path be selected.
        criteria=[
            'Independently establish whether original assertion discrepancy is product-caused',
            'Verify original N8 diagnosis '+diagnosis_id+' and conclusive failure evidence '+failure['evidence_id'],
            'Preserve frozen Case, request/response, Oracle and complete original R1 evidence',
            'Request genuinely new scoped reproduction Attempt; no old N7 execution lease reuse',
            'No product Defect or fix/regression PASS until causal and lifecycle evidence exists']
        objective=('Independently qualify original VALID_TEST_FAILURE for Case '+p['case_id']+
                   ' from original N7 Attempt '+p['attempt_id'])
        expected=dict(mission_id=p['mission_id'],node='DEFECT',
            task_type='N9_DISCREPANCY_QUALIFICATION',
            objective=objective,acceptance_criteria=criteria,
            required_capabilities=['defect_analysis'],input_artifact_refs=refs,gap_refs=[gap['gap_id']])
        # All expensive/recursive independent N8 proof audits have already
        # completed. Serialize ONLY the new frozen N9 Task reservation here:
        # a concurrent Captain/DSH Session cannot register two same-ID tasks.
        # Do not call the conclusive failure auditor while holding this lock.
        with ledger_lock(self.truth,busy='N9_PROFESSIONAL_TASK_LEDGER_BUSY'):
            existing=self.truth.query('rc7_task',task_id=wid)
            if len(existing)>1:raise ContractError('N9_PROFESSIONAL_REPRODUCTION_NOT_UNIQUE')
            if not existing:
                ClosedLoopControlPlane(self.truth,self.release_id,p['mission_id']).register_task(
                    Task(task_id=wid,mission_id=p['mission_id'],node='DEFECT',
                         task_type='N9_DISCREPANCY_QUALIFICATION',objective=objective,
                         required_capabilities=['defect_analysis'],
                         input_artifact_refs=refs,gap_refs=[gap['gap_id']],
                         acceptance_criteria=criteria,priority=0))
            task=self._one('rc7_task',task_id=wid)
            if any(task.get(key)!=value for key,value in expected.items()):
                raise ContractError('N9_PROFESSIONAL_REPRODUCTION_SCOPE_CHANGED')
        return dict(status='HOLD',reason='N9_INDEPENDENT_QUALIFICATION_REQUIRED',
            qualification_workitem_id=wid,diagnosis_id=diagnosis_id,
            original_attempt_id=p['attempt_id'],gap_id=gap['gap_id'],
            defect_confirmed=False)
