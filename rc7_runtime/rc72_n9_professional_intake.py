"""Professional N9 intake from a real N8-qualified business assertion failure.

An accepted discrepancy is *not* proof of a product defect. Queue governed,
independent reproduction against the original frozen Case/Attempt; do not
mark defects, repair, RCA or regression complete. Cold re-entry reauthenticates
signed process evidence and must not replay the business operation.
"""
from .closed_loop_control import ClosedLoopControlPlane
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
        wid='N9REPRO-'+_hash([p['mission_id'],p['attempt_id'],diagnosis_id])[:24]
        refs=['r1://artifact/'+p['contract_id'],'r1://artifact/'+diagnosis_id,
              'r1://evidence/'+failure['evidence_id']]
        expected=dict(mission_id=p['mission_id'],node='DEFECT',task_type='DEFECT_REPRODUCTION',
            required_capabilities=['defect_reproduction'],input_artifact_refs=refs,gap_refs=[gap['gap_id']])
        existing=self.truth.query('rc7_task',task_id=wid)
        if len(existing)>1:raise ContractError('N9_PROFESSIONAL_REPRODUCTION_NOT_UNIQUE')
        if not existing:
            ClosedLoopControlPlane(self.truth,self.release_id,p['mission_id']).register_task(
                Task(task_id=wid,mission_id=p['mission_id'],node='DEFECT',
                     task_type='DEFECT_REPRODUCTION',
                     objective='Independently reproduce approved business discrepancy for Case '+p['case_id']+
                        ' from original N7 Attempt '+p['attempt_id'],
                     required_capabilities=['defect_reproduction'],
                     input_artifact_refs=refs,gap_refs=[gap['gap_id']],
                     acceptance_criteria=[
                         'New independent scoped execution with immutable original Case and business oracle',
                         'Captured actual/expected discrepancy and complete R1 evidence',
                         'Professional causal review: no product defect without independent RCA',
                         'No reuse of the failed Attempt or its execution lease'],priority=0))
        task=self._one('rc7_task',task_id=wid)
        if any(task.get(key)!=value for key,value in expected.items()):
            raise ContractError('N9_PROFESSIONAL_REPRODUCTION_SCOPE_CHANGED')
        return dict(status='HOLD',reason='N9_INDEPENDENT_REPRODUCTION_REQUIRED',
            reproduction_workitem_id=wid,diagnosis_id=diagnosis_id,
            original_attempt_id=p['attempt_id'],gap_id=gap['gap_id'],
            defect_confirmed=False)
