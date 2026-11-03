"""Actual normalized HTTP coverage read, not bank vendor/Field qualification."""
import json,time,threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import pytest
from test_rc72_n10_expected_scope_provenance import _original_policy_execution
from rc72_n2_test_support import BATCH
from rc7_runtime.rc72_n9_accepted_scope import AcceptedScopeN9Service
from rc7_runtime.rc72_libra_measurement import NativeLibraMeasurementService


class _Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        self.server.calls.append(self.path)
        row=dict(schema='RC72_LIBRA_INCREMENTAL_REPORT_V1',measurement_id=self.headers['X-RC72-Measurement-ID'],
            application_id=self.server.app,base_revision='base-a',target_revision='target-b',metric='LINE',
            observed_at=int(time.time()),source_ref='libra://actual-normalized-fixture/report',
            units=[dict(unit_id='line-'+str(i),code_slice='ChangedService#method',covered=i<3) for i in range(4)])
        if self.server.mutate:self.server.mutate(row)
        raw=json.dumps(row).encode();self.send_response(getattr(self.server,'status',200))
        if getattr(self.server,'status',200)==302:self.send_header('Location','/redirected')
        self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)


def _setup(tmp_path,monkeypatch,mutate=None,auth_mode="ANONYMOUS"):
    server=ThreadingHTTPServer(('127.0.0.1',0),_Handler);server.calls=[];server.mutate=mutate
    threading.Thread(target=server.serve_forever,daemon=True).start()
    def policy(row):
        row['schema']='RC72_EXPECTED_RELEASE_SCOPE_V2'
        server.app=row['application_ids'][0]
        row['coverage_targets']={app:dict(metric='LINE',base_revision='base-a',target_revision='target-b',target_ratio=.9,
            report_url='http://127.0.0.1:%d/report'%server.server_address[1],auth_mode=auth_mode,source_ref='catalog://original-coverage-policy/v1')
            for app in row['application_ids']}
    try:
        truth,plan,pipeline,business,providers,workers=_original_policy_execution(tmp_path,monkeypatch,policy)
        pipeline.complete(release_batch_id=BATCH)
        n9=AcceptedScopeN9Service(pipeline);n9.complete(release_batch_id=BATCH)
        service=NativeLibraMeasurementService(providers[0],n9,capture_root=tmp_path/'actual-libra')
        return truth,plan,pipeline,business,server,service
    except BaseException:server.shutdown();server.server_close();raise


def test_actual_report_uses_original_target_not_caller_percentage_and_replays_without_io(tmp_path,monkeypatch):
    truth,plan,pipeline,business,server,service=_setup(tmp_path,monkeypatch)
    try:
        result=service.collect(release_batch_id=BATCH,application_id=server.app)
        assert result['covered_units']==3 and result['total_units']==4
        assert result['target_ratio']==.9 and result['coverage_met'] is False
        assert len(server.calls)==1 and len(business.calls)==len(plan['items'])
        assert truth.query('rc7_task',task_id=truth.query('rc72_libra_measurement')[0]['workitem_id'])[0]['state']=='PASS'
        before=truth.store.path.read_bytes()
        assert service.collect(release_batch_id=BATCH,application_id=server.app)==result
        assert truth.store.path.read_bytes()==before and len(server.calls)==1
    finally:server.shutdown();server.server_close();business.shutdown();business.server_close()


@pytest.mark.parametrize('field,value,error',[
    ('application_id','foreign-app','SCOPE_MISMATCH'),
    ('target_revision','wrong-revision','SCOPE_MISMATCH'),
    ('measurement_id','replayed-report','SCOPE_MISMATCH'),
    ('observed_at',0,'FRESH_SOURCE_REQUIRED'),
    ('units',[dict(unit_id='duplicate',code_slice='A',covered=True)]*2,'UNIT_IDENTITY_INVALID'),
])
def test_invalid_actual_report_never_accepts_or_repeats_read(tmp_path,monkeypatch,field,value,error):
    truth,plan,pipeline,business,server,service=_setup(tmp_path,monkeypatch,lambda row:row.update({field:value}))
    try:
        for _ in range(2):
            with pytest.raises(ValueError,match=error):service.collect(release_batch_id=BATCH,application_id=server.app)
        assert len(server.calls)==1
        assert not truth.query('rc72_coverage_observation')
        row=truth.query('rc72_libra_measurement')[0]
        assert truth.query('rc7_task',task_id=row['workitem_id'])[0]['state']=='RUNNING'
    finally:server.shutdown();server.server_close();business.shutdown();business.server_close()


def test_lost_lease_after_actual_read_retains_unknown_and_forbids_replay(tmp_path,monkeypatch):
    truth,plan,pipeline,business,server,service=_setup(tmp_path,monkeypatch)
    def revoke(row):
        receipt=truth.query('rc72_libra_measurement')[0]
        service.authority.revoke_worker_lease(receipt['lease']['lease_id'])
    server.mutate=revoke
    try:
        with pytest.raises(Exception):service.collect(release_batch_id=BATCH,application_id=server.app)
        row=truth.query('rc72_libra_measurement')[0]
        assert row['state']=='UNKNOWN' and row['body_sha256']
        assert not truth.query('rc72_coverage_observation')
        assert service.collect(release_batch_id=BATCH,application_id=server.app)['reason']=='LIBRA_UNKNOWN_READ_NO_REPLAY'
        assert len(server.calls)==1
    finally:server.shutdown();server.server_close();business.shutdown();business.server_close()


def test_cold_audit_is_readonly_and_rejects_reviewer_request_tampering(tmp_path,monkeypatch):
    truth,plan,pipeline,business,server,service=_setup(tmp_path,monkeypatch)
    try:
        result=service.collect(release_batch_id=BATCH,application_id=server.app)
        cold=NativeLibraMeasurementService(service.expected_scope,service.n9,capture_root=service.root)
        before=truth.store.path.read_bytes()
        assert cold.audit(release_batch_id=BATCH,application_id=server.app)==result
        assert truth.store.path.read_bytes()==before and len(server.calls)==1
        row=truth.query('rc72_libra_measurement')[0]
        task=truth.query('rc7_task',task_id=row['workitem_id'])[0]
        changed=dict(task,required_capabilities=['unrelated-tool'],artifact_version=task['artifact_version']+1)
        truth.append_atomic('RC7_TASK_UPSERTED',changed)
        tampered=truth.store.path.read_bytes()
        with pytest.raises(Exception,match='WORKITEM_PROOF_CHANGED'):cold.audit(release_batch_id=BATCH,application_id=server.app)
        assert truth.store.path.read_bytes()==tampered and len(server.calls)==1
        truth.append_atomic('RC7_TASK_UPSERTED',dict(task,artifact_version=changed['artifact_version']+1))
        before=truth.store.path.read_bytes()
        request=service.root/row['measurement_id']/'request.json'
        payload=json.loads(request.read_text());payload['application_id']='foreign';request.write_text(json.dumps(payload))
        with pytest.raises(Exception,match='PROCESS_BINDING_CHANGED'):cold.audit(release_batch_id=BATCH,application_id=server.app)
        assert truth.store.path.read_bytes()==before and len(server.calls)==1
    finally:server.shutdown();server.server_close();business.shutdown();business.server_close()


@pytest.mark.parametrize('all_covered',[False,True])
def test_native_convergence_consumes_actual_counts_and_preserves_all_levels(tmp_path,monkeypatch,all_covered):
    from rc7_runtime.rc72_release_convergence import ReleaseConvergenceAggregator
    from rc7_runtime.rc72_obligation_execution_proof import AcceptedObligationExecutionProof
    from rc7_runtime.rc72_state_machine import RC72StateMachine
    from rc72_n2_test_support import RELEASE,MISSION
    truth,plan,pipeline,business,server,service=_setup(tmp_path,monkeypatch)
    try:
        if all_covered:
            server.mutate=lambda row:[unit.update(covered=True) for unit in row['units']]
        actual=service.collect(release_batch_id=BATCH,application_id=server.app)
        from rc7_runtime.rc72_native_coverage_intake import NativeCoverageGapIntakeService
        intake=NativeCoverageGapIntakeService(service)
        intake.intake(release_batch_id=BATCH,application_id=server.app)
        aggregator=ReleaseConvergenceAggregator(truth,release_id=RELEASE,runtime=RC72StateMachine(truth,release_id=RELEASE),
            execution_proof=AcceptedObligationExecutionProof(pipeline),expected_scope=service.expected_scope,coverage_proof=service,coverage_intake=intake)
        from rc7_runtime.rc72_coverage_convergence import CoverageFeedbackService
        CoverageFeedbackService(truth,release_id=RELEASE).record_observation(observation_id='UNATTESTED-PERCENT',
            mission_id=MISSION,release_batch_id=BATCH,application_id=server.app,source='CALLER',covered_units=100,
            total_units=100,target_ratio=.1,evidence_ref='unverified://caller')
        result=aggregator.aggregate(mission_id=MISSION)
        assert result.facts.incremental_coverage_met is all_covered
        assert result.facts.required_l1_l7_completion is False
        assert result.result.value=='NOT_CONVERGED'
        assert result.coverage_observation_ids==[actual['observation_id']]
        legacy=ReleaseConvergenceAggregator(truth,release_id=RELEASE,runtime=RC72StateMachine(truth,release_id=RELEASE))
        downgraded=legacy.aggregate(mission_id=MISSION)
        assert downgraded.facts.incremental_coverage_met is False
        assert 'coverage:NATIVE_LIBRA_PROOF_REQUIRED' in downgraded.blockers
        assert len(server.calls)==1 and len(business.calls)==len(plan['items'])
    finally:server.shutdown();server.server_close();business.shutdown();business.server_close()


def test_partial_acceptance_resumes_without_restoring_read_authority(tmp_path,monkeypatch):
    truth,plan,pipeline,business,server,service=_setup(tmp_path,monkeypatch)
    try:
        original=service._accept_locked
        def interrupt(*args):raise RuntimeError('injected metadata interruption')
        monkeypatch.setattr(service,'_accept_locked',interrupt)
        with pytest.raises(RuntimeError,match='metadata interruption'):service.collect(release_batch_id=BATCH,application_id=server.app)
        row=truth.query('rc72_libra_measurement')[0]
        assert row['state']=='RETURNED' and row['review_state']=='RETURNED'
        monkeypatch.setattr(service,'_accept_locked',original)
        def forbid(*args,**kwargs):raise AssertionError('must not restore effect authority')
        monkeypatch.setattr(service.authority,'issue_lease',forbid)
        result=service.collect(release_batch_id=BATCH,application_id=server.app)
        assert result['covered_units']==3 and len(server.calls)==1
        assert len(truth.query('rc72_libra_measurement'))==1
    finally:server.shutdown();server.server_close();business.shutdown();business.server_close()


def test_worker_header_policy_holds_before_read_or_measurement_workitem(tmp_path,monkeypatch):
    truth,plan,pipeline,business,server,service=_setup(tmp_path,monkeypatch,auth_mode='WORKER_HEADER')
    try:
        before=truth.store.path.read_bytes()
        result=service.collect(release_batch_id=BATCH,application_id=server.app)
        assert result['reason']=='NATIVE_LIBRA_WORKER_AUTH_PROVIDER_REQUIRED'
        assert truth.store.path.read_bytes()==before and not server.calls
        assert not truth.query('rc72_libra_measurement')
    finally:server.shutdown();server.server_close();business.shutdown();business.server_close()


@pytest.mark.parametrize('status',[302,500])
def test_http_error_or_redirect_is_captured_without_followup_or_acceptance(tmp_path,monkeypatch,status):
    truth,plan,pipeline,business,server,service=_setup(tmp_path,monkeypatch)
    server.status=status
    try:
        for _ in range(2):
            with pytest.raises(Exception,match='MEASUREMENT_SCOPE_CHANGED'):service.collect(release_batch_id=BATCH,application_id=server.app)
        row=truth.query('rc72_libra_measurement')[0]
        assert row['http_status']==status and row['body_sha256']
        assert len(server.calls)==1 and not truth.query('rc72_coverage_observation')
    finally:server.shutdown();server.server_close();business.shutdown();business.server_close()
