"""Close owned discovery WorkItems from independently audited native results."""
from dataclasses import asdict
import hashlib
from pathlib import Path

from .candidate_payload import CandidatePayloadReader

from .closed_loop_control import ClosedLoopControlPlane
from .models import ContractError, Evaluation, EvaluationResult, Gap, GapSeverity
from .rc72_n5_data_verification_finalization import N5DataVerificationFinalizationService
from .rc72_n5_completion import N5DeliveryGateService


class N5WorkItemFinalizer:
    def __init__(self, finalizer):
        if not isinstance(finalizer, N5DataVerificationFinalizationService):
            raise ContractError('RC72_N5_NATIVE_FINALIZER_REQUIRED')
        self.finalizer, self.truth = finalizer, finalizer.truth

    def _one(self, kind, **filters):
        rows = self.truth.query(kind, **filters)
        if len(rows)!=1:
            raise ContractError('RC72_N5_WORKITEM_TRUTH_NOT_UNIQUE:'+kind)
        return rows[0]

    def finalize(self, **scope):
        # Reparse actual raw verifier bytes and native source/actor lineage before
        # interpreting a durable result, including interrupted/repeated calls.
        outcome = self.finalizer.finalize(**scope)
        row = self._one('rc72_n5_data_verification_result', finalization_id=outcome['finalization_id'])
        task = self._one('rc7_task', task_id=row['workitem_id'])
        artifact = row['candidate_artifact_id']
        if (row['release_id'] != self.finalizer.release_id or row['mission_id'] != self.finalizer.mission_id
                or row['source_commit'] != self.finalizer.source_commit or task['node'] != 'TEST_DATA'
                or task['mission_id'] != row['mission_id'] or task['output_artifact_refs'] != [artifact]
                or task['lease_owner'] == row['verifier_worker_id']):
            raise ContractError('RC72_N5_WORKITEM_INDEPENDENT_PROOF_REQUIRED')
        negative = row['decision']=='REPAIR_REQUIRED'
        gaps = []
        if negative:
            gaps = [Gap(gap_id='GAP-N5-VERIFY-'+hashlib.sha256(row['finalization_id'].encode()).hexdigest()[:24],
                mission_id=row['mission_id'], source_node='TEST_DATA', target_node='TEST_DATA',
                category='TEST_DATA_GAP', severity=GapSeverity.HIGH,
                description='Independent data verification requires repair: '+row['verification'],
                subject_refs=[artifact,row['data_requirement_id'],row['case_id']],
                evidence_refs=[row['verification_evidence_id']],
                acceptance_criteria=['Repair the exact scoped data and independently verify all frozen Case preconditions'])]
        evaluation = Evaluation(evaluation_id='EVAL-N5-VERIFY-'+hashlib.sha256(row['finalization_id'].encode()).hexdigest()[:24],
            mission_id=row['mission_id'],node='TEST_DATA',artifact_refs=[artifact],
            result=EvaluationResult.REPAIR_REQUIRED if negative else EvaluationResult.PASS,
            evaluator_ref='dsh:'+row['verifier_worker_id']+'+native-data-verification-gate',
            dimensions={k:row[k] for k in ('finalization_id','data_requirement_id','source_case_sha256',
                'verification_attempt_id','verifier_worker_id','verifier_dsh_session_id','raw_output_sha256','decision','data_ref')},
            gap_refs=[g.gap_id for g in gaps],evidence_refs=[row['verification_evidence_id']])
        if task['state'] in {'PASS','REPAIR_REQUIRED'}:
            current = self._one('rc7_evaluation', evaluation_id=evaluation.evaluation_id)
            expected = asdict(evaluation)
            expected.pop('created_at')
            expected['result'] = evaluation.result.value
            if (task.get('evaluation_id') != evaluation.evaluation_id or task['state'] != evaluation.result.value
                    or any(current.get(k)!=v for k,v in expected.items())):
                raise ContractError('RC72_N5_WORKITEM_ACCEPTANCE_CHANGED')
        else:
            ClosedLoopControlPlane(self.truth,row['release_id'],row['mission_id']).accept_evaluation(
                task['task_id'],evaluation=evaluation,gaps=gaps)
        return outcome


class N5OwnedWorkItemGateService(N5DeliveryGateService):
    """Binding truth alone cannot hide unfinished original discovery work."""
    def complete(self, *, release_batch_id):
        batch = self._one('rc72_release_batch', release_batch_id=release_batch_id)
        for dispatch in self.truth.query('rc72_n5_data_discovery_dispatch', release_batch_id=release_batch_id):
            task = self._one('rc7_task', task_id=dispatch['workitem_id'])
            if (dispatch['mission_id'] != batch['mission_id'] or dispatch['source_commit'] != self.source_commit
                    or task['state'] != 'PASS'):
                raise ContractError('RC72_N5_OWNED_WORKITEM_NOT_ACCEPTED')
            evaluation = self._one('rc7_evaluation', evaluation_id=task['evaluation_id'])
            result = self._one('rc72_n5_data_verification_result',
                finalization_id=evaluation['dimensions'].get('finalization_id'))
            if (evaluation['result'] != 'PASS' or result['decision'] != 'VERIFIED_CANDIDATE'
                    or result['source_commit'] != self.source_commit or result['release_id'] != self.release_id
                    or result['mission_id'] != batch['mission_id'] or result['workitem_id'] != task['task_id']
                    or result['data_requirement_id'] != dispatch['data_requirement_id']
                    or task['lease_owner'] == result['verifier_worker_id']
                    or evaluation['artifact_refs'] != [result['candidate_artifact_id']]
                    or evaluation['evidence_refs'] != [result['verification_evidence_id']]
                    or evaluation['evaluator_ref'] != 'dsh:'+result['verifier_worker_id']+'+native-data-verification-gate'
                    or any(evaluation['dimensions'].get(k)!=result[k] for k in ('data_requirement_id','source_case_sha256',
                        'verification_attempt_id','verifier_worker_id','verifier_dsh_session_id','raw_output_sha256','decision','data_ref'))):
                raise ContractError('RC72_N5_OWNED_WORKITEM_PROOF_CHANGED')
            candidate = CandidatePayloadReader().load(self.truth, result['candidate_artifact_id'],
                expected_mission_id=batch['mission_id'], expected_task_id=task['task_id'])
            if candidate.content_hash != result['candidate_content_hash']:
                raise ContractError('RC72_N5_OWNED_CANDIDATE_CHANGED')
            producer = self._one('rc72_n5_data_discovery_evidence_anchor',
                anchor_id=candidate.envelope['runtime_lineage']['evidence_anchor_id'])
            verifier = self._one('rc72_n5_data_verification_evidence_anchor', anchor_id=result['evidence_anchor_id'])
            if (producer['data_requirement_id'] != dispatch['data_requirement_id']
                    or producer['raw_output_sha256'] != candidate.envelope['runtime_lineage']['raw_output_sha256']
                    or verifier['raw_output_sha256'] != result['raw_output_sha256']):
                raise ContractError('RC72_N5_OWNED_RAW_SCOPE_CHANGED')
            for anchor in (producer,verifier):
                ref = anchor['raw_output_ref']
                if not ref.startswith('file://'):
                    raise ContractError('RC72_N5_OWNED_RAW_PROOF_CHANGED')
                try:
                    digest = 'sha256:'+hashlib.sha256(Path(ref[len('file://'):]).read_bytes()).hexdigest()
                except OSError as exc:
                    raise ContractError('RC72_N5_OWNED_RAW_PROOF_CHANGED') from exc
                if digest != anchor['raw_output_sha256']:
                    raise ContractError('RC72_N5_OWNED_RAW_PROOF_CHANGED')
        return super().complete(release_batch_id=release_batch_id)
