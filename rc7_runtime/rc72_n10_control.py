"""Concrete N10 advancement through original policy, measured gaps and diagnosis.

Terminal release review remains a separate required closure; this service never
turns an incomplete original denominator or queued investigation into PASS.
When native repair/rerun providers are composed, N10 advances only durable,
evidence-backed control-plane state and invokes the ordinary physical N7 pipeline.
"""
from .models import ContractError
from .rc72_expected_scope_input import ExpectedScopeInputService
from .rc72_n9_accepted_scope import AcceptedScopeN9Service
from .rc72_libra_measurement import NativeLibraMeasurementService
from .rc72_native_coverage_intake import NativeCoverageGapIntakeService
from .rc72_native_coverage_diagnosis import NativeCoveragePathDiagnosisService
from .rc72_native_coverage_repair import NativeCoverageRepairService,active_repair_boundaries
from .rc72_native_coverage_rerun import NativeCoverageRerunService
from .rc72_release_convergence import ReleaseConvergenceAggregator
from .rc72_n10_feedback import NativeN10FeedbackService
from .rc72_obligation_execution_proof import AcceptedObligationExecutionProof


class NativeN10ControlService:
    def __init__(self,expected_scope,n9,measurement,intake,diagnosis,repair=None,rerun=None):
        self.expected_scope,self.n9,self.measurement,self.intake,self.diagnosis=expected_scope,n9,measurement,intake,diagnosis
        self.repair,self.rerun=repair,rerun
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
        if self.repair is not None and (not isinstance(self.repair,NativeCoverageRepairService) or self.repair.diagnosis is not self.diagnosis
                or self.repair.truth is not self.truth or self.repair.source_commit!=self.source_commit):
            raise ContractError('N10_NATIVE_REPAIR_COMPOSITION_REQUIRED')
        if self.rerun is not None and (self.repair is None or not isinstance(self.rerun,NativeCoverageRerunService)
                or self.rerun.repair is not self.repair or self.rerun.truth is not self.truth or self.rerun.source_commit!=self.source_commit):
            raise ContractError('N10_NATIVE_RERUN_COMPOSITION_REQUIRED')

    def _advance_repair(self,*,release_batch_id,application_id,gap_id):
        if self.repair is None:return None
        prepared=self.repair.prepare(release_batch_id=release_batch_id,application_id=application_id,gap_id=gap_id)
        if prepared.get('status')=='HOLD':return dict(status='HOLD',reason=prepared['reason'],gap_id=gap_id,
            investigation_workitem_id=prepared.get('investigation_workitem_id'))
        activated=self.repair.activate(release_batch_id=release_batch_id,application_id=application_id,gap_id=gap_id)
        if activated.get('status')=='HOLD':return dict(status='HOLD',reason=activated['reason'],gap_id=gap_id,
            investigation_workitem_id=prepared.get('investigation_workitem_id'),repair_workitem_id=prepared.get('repair_workitem_id'))
        if activated.get('status')=='FRESH_N7_REQUIRED':return dict(status='HOLD',reason='N10_POST_REPAIR_FRESH_N7_REQUIRED',gap_id=gap_id,
            repair_id=activated['repair_id'],repair_workitem_id=activated['repair_workitem_id'],origin_n7_gate_id=activated['origin_n7_gate_id'])
        if activated.get('status')=='CLOSED':return dict(status='CLOSED',gap_id=gap_id,repair_id=activated['repair_id'],
            repair_workitem_id=activated['repair_workitem_id'])
        raise ContractError('N10_NATIVE_REPAIR_ADVANCEMENT_STATE_INVALID')

    def complete(self,*,release_batch_id):
        self._assert_inputs();frozen=self.expected_scope.freeze(release_batch_id=release_batch_id)
        batch=self.measurement._one('rc72_release_batch',release_batch_id=release_batch_id)
        if batch['release_id']!=self.release_id:raise ContractError('N10_RELEASE_SCOPE_CHANGED')
        rerun_result=None
        active=[]
        for app in batch['application_ids']:
            active.extend(active_repair_boundaries(self.truth,self.measurement.authority,release_id=self.release_id,
                source_commit=self.source_commit,release_batch_id=release_batch_id,application_id=app))
        if active and self.rerun is not None:
            rerun_result=self.rerun.run(release_batch_id=release_batch_id)
            if rerun_result.get('status')=='HOLD':
                return dict(status='HOLD',reason='N10_COVERAGE_RERUN_REQUIRED',rerun=rerun_result,
                    manifest_id=frozen['manifest_id'],field_verified=False,bank_final=False)
        n9=self.n9.complete(release_batch_id=release_batch_id)
        if n9.get('status')=='HOLD':return n9
        node=self.measurement._one('rc72_mission_node',mission_id=batch['mission_id'],node_type='N10_RELEASE_CONVERGENCE')
        if node['state'] not in {'READY','RUNNING','REVIEW_PENDING','PASS'}:raise ContractError('N10_NATIVE_ACTIVE_NODE_REQUIRED')
        measurements=[];intakes=[];investigations=[];repair_workitems=[];holds=[]
        for app in batch['application_ids']:
            repairs=active_repair_boundaries(self.truth,self.measurement.authority,release_id=self.release_id,
                source_commit=self.source_commit,release_batch_id=release_batch_id,application_id=app)
            if repairs:
                _,current_proof=self.measurement._context(release_batch_id,audit_only=True)
                if any(row['origin_n7_gate_id']==current_proof['n7_gate_id'] for row in repairs):
                    holds.append(dict(application_id=app,reason='N10_POST_REPAIR_FRESH_N7_REQUIRED',repair_ids=[row['repair_id'] for row in repairs]));continue
            actual=self.measurement.collect(release_batch_id=release_batch_id,application_id=app)
            if actual.get('status')=='HOLD':holds.append(dict(application_id=app,reason=actual['reason']));continue
            measurements.append(actual['measurement_id'])
            if repairs:
                if self.repair is None:
                    holds.append(dict(application_id=app,reason='N10_NATIVE_COVERAGE_REPAIR_PROVIDER_REQUIRED',repair_ids=[row['repair_id'] for row in repairs]));continue
                repaired=self.repair.reconcile_application(release_batch_id=release_batch_id,application_id=app)
                if repaired.get('status')=='HOLD':holds.append(dict(application_id=app,reason=repaired['reason'],repair_ids=repaired.get('repair_ids',[])));continue
            admitted=self.intake.intake(release_batch_id=release_batch_id,application_id=app);intakes.append(admitted['intake_id'])
            for gap_id in admitted['gap_ids']:
                try:result=self.diagnosis.run(release_batch_id=release_batch_id,application_id=app,gap_id=gap_id)
                except ContractError as exc:
                    if str(exc)!='COVERAGE_DIAGNOSIS_UNKNOWN_PROCESS_NO_REPLAY':raise
                    result=dict(status='HOLD',reason=str(exc))
                if result.get('status')=='HOLD':holds.append(dict(application_id=app,gap_id=gap_id,reason=result['reason']));continue
                investigations.append(result['investigation_workitem_id'])
                advanced=self._advance_repair(release_batch_id=release_batch_id,application_id=app,gap_id=gap_id)
                if advanced is not None:
                    repair_workitem_id=advanced.get('repair_workitem_id')
                    if repair_workitem_id and repair_workitem_id not in repair_workitems:repair_workitems.append(repair_workitem_id)
                    if advanced['status']=='HOLD':holds.append(dict(application_id=app,**advanced));continue
        extra=dict(coverage_rerun_id=rerun_result.get('rerun_id')) if rerun_result and rerun_result.get('rerun_id') else {}
        if holds:return dict(status='HOLD',reason='N10_COVERAGE_INVESTIGATION_REQUIRED',holds=holds,
            measurement_ids=measurements,intake_ids=intakes,investigation_workitem_ids=investigations,repair_workitem_ids=repair_workitems,
            manifest_id=frozen['manifest_id'],field_verified=False,bank_final=False,**extra)
        aggregator=ReleaseConvergenceAggregator(self.truth,release_id=self.release_id,runtime=self.n9.runtime,
            execution_proof=AcceptedObligationExecutionProof(self.n9.pipeline),expected_scope=self.expected_scope,
            coverage_proof=self.measurement,coverage_intake=self.intake,coverage_diagnosis=self.diagnosis,
            coverage_repair=self.repair,replay_safe=True)
        snapshot=aggregator.aggregate(mission_id=batch['mission_id'])
        issues=NativeN10FeedbackService(self.truth,release_id=self.release_id).derive(snapshot=snapshot)
        if snapshot.result.value=='CONVERGED':
            # Terminal PASS is not derived from the aggregator result alone.
            # A fresh, separate reviewer process and signed R1 evidence
            # must apply the N10 Delivery/Gate through its ordinary lifecycle.
            from .rc72_n10_terminal import NativeN10TerminalReviewService
            terminal=NativeN10TerminalReviewService(aggregator,
                authority=self.measurement.authority,source_commit=self.source_commit,
                review_root=self.n9.pipeline.review.capture_root/'n10-terminal',
                lifecycle=self.n9.pipeline.preparation.lifecycle).finalize(snapshot=snapshot)
            return dict(terminal,convergence_result=snapshot.result.value,
                blockers=snapshot.blockers,issues=issues,measurement_ids=measurements,
                intake_ids=intakes,investigation_workitem_ids=investigations,
                repair_workitem_ids=repair_workitems,**extra)
        return dict(status='HOLD',reason='N10_RELEASE_NOT_CONVERGED',
            convergence_result=snapshot.result.value,convergence_snapshot_id=snapshot.snapshot_id,blockers=snapshot.blockers,
            issues=issues,
            measurement_ids=measurements,intake_ids=intakes,investigation_workitem_ids=investigations,repair_workitem_ids=repair_workitems,
            manifest_id=frozen['manifest_id'],field_verified=False,bank_final=False,**extra)
