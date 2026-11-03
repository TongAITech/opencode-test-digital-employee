"""Concrete N10 advancement through original policy, measured gaps and diagnosis.

Terminal release review remains a separate required closure; this service never
turns an incomplete original denominator or queued investigation into PASS.
"""
from .models import ContractError
from .rc72_expected_scope_input import ExpectedScopeInputService
from .rc72_n9_accepted_scope import AcceptedScopeN9Service
from .rc72_libra_measurement import NativeLibraMeasurementService
from .rc72_native_coverage_intake import NativeCoverageGapIntakeService
from .rc72_native_coverage_diagnosis import NativeCoveragePathDiagnosisService
from .rc72_release_convergence import ReleaseConvergenceAggregator
from .rc72_obligation_execution_proof import AcceptedObligationExecutionProof


class NativeN10ControlService:
    def __init__(self,expected_scope,n9,measurement,intake,diagnosis):
        self.expected_scope,self.n9,self.measurement,self.intake,self.diagnosis=expected_scope,n9,measurement,intake,diagnosis
        if not isinstance(n9,AcceptedScopeN9Service):raise ContractError('N10_NATIVE_N9_REQUIRED')
        self.truth,self.release_id,self.source_commit=n9.truth,n9.release_id,n9.source_commit
        self._assert_inputs()

    def _assert_inputs(self):
        if (not isinstance(self.expected_scope,ExpectedScopeInputService) or not isinstance(self.n9,AcceptedScopeN9Service)
                or not isinstance(self.measurement,NativeLibraMeasurementService)
                or not isinstance(self.intake,NativeCoverageGapIntakeService)
                or not isinstance(self.diagnosis,NativeCoveragePathDiagnosisService)
                or self.measurement.expected_scope is not self.expected_scope or self.measurement.n9 is not self.n9
                or self.intake.measurement is not self.measurement or self.diagnosis.intake is not self.intake
                or any(s.truth is not self.truth or s.source_commit!=self.source_commit
                       for s in (self.expected_scope,self.n9,self.measurement,self.intake,self.diagnosis))):
            raise ContractError('N10_NATIVE_OWNED_COMPOSITION_REQUIRED')

    def complete(self,*,release_batch_id):
        self._assert_inputs()
        frozen=self.expected_scope.freeze(release_batch_id=release_batch_id)
        n9=self.n9.complete(release_batch_id=release_batch_id)
        if n9.get('status')=='HOLD':return n9
        batch=self.measurement._one('rc72_release_batch',release_batch_id=release_batch_id)
        if batch['release_id']!=self.release_id:raise ContractError('N10_RELEASE_SCOPE_CHANGED')
        node=self.measurement._one('rc72_mission_node',mission_id=batch['mission_id'],node_type='N10_RELEASE_CONVERGENCE')
        if node['state'] not in {'READY','RUNNING'}:raise ContractError('N10_NATIVE_ACTIVE_NODE_REQUIRED')
        measurements=[];intakes=[];investigations=[];holds=[]
        for app in batch['application_ids']:
            actual=self.measurement.collect(release_batch_id=release_batch_id,application_id=app)
            if actual.get('status')=='HOLD':
                holds.append(dict(application_id=app,reason=actual['reason']));continue
            measurements.append(actual['measurement_id'])
            admitted=self.intake.intake(release_batch_id=release_batch_id,application_id=app)
            intakes.append(admitted['intake_id'])
            for gap_id in admitted['gap_ids']:
                try:result=self.diagnosis.run(release_batch_id=release_batch_id,application_id=app,gap_id=gap_id)
                except ContractError as exc:
                    if str(exc)!='COVERAGE_DIAGNOSIS_UNKNOWN_PROCESS_NO_REPLAY':raise
                    result=dict(status='HOLD',reason=str(exc))
                if result.get('status')=='HOLD':holds.append(dict(application_id=app,gap_id=gap_id,reason=result['reason']))
                else:investigations.append(result['investigation_workitem_id'])
        if holds:
            return dict(status='HOLD',reason='N10_COVERAGE_INVESTIGATION_REQUIRED',holds=holds,
                measurement_ids=measurements,intake_ids=intakes,investigation_workitem_ids=investigations,
                manifest_id=frozen['manifest_id'],field_verified=False,bank_final=False)
        aggregator=ReleaseConvergenceAggregator(self.truth,release_id=self.release_id,runtime=self.n9.runtime,
            execution_proof=AcceptedObligationExecutionProof(self.n9.pipeline),expected_scope=self.expected_scope,
            coverage_proof=self.measurement,coverage_intake=self.intake,coverage_diagnosis=self.diagnosis)
        snapshot=aggregator.aggregate(mission_id=batch['mission_id'])
        return dict(status='HOLD',reason='N10_RELEASE_NOT_CONVERGED' if snapshot.result.value!='CONVERGED' else 'N10_TERMINAL_REVIEW_REQUIRED',
            convergence_result=snapshot.result.value,convergence_snapshot_id=snapshot.snapshot_id,blockers=snapshot.blockers,
            measurement_ids=measurements,intake_ids=intakes,investigation_workitem_ids=investigations,
            manifest_id=frozen['manifest_id'],field_verified=False,bank_final=False)
