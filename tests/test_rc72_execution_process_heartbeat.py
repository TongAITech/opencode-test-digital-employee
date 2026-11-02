"""Real process ownership, automatic renewal and durable failed-guardian fencing."""
from pathlib import Path
import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import ContractError
from rc7_runtime.rc72_formal_runner import FormalN7RunnerAdapter, verified_formal_receipt
from rc7_runtime.rc72_n7_tool_dispatch import SignedToolDispatchService
from rc7_runtime.rc72_n7_cleanup import ExecutionCleanupService
from rc7_runtime.rc72_n7_execution_evidence import ExecutionEvidenceService
from rc72_formal_runner_support import formal_setup, LocalHTTPEnvironment
from test_rc72_n7_execution_preparation import _service


def test_real_owned_process_automatically_renews_and_whole_batch_reaches_independent_n7_gate(tmp_path, monkeypatch):
    from rc7_runtime.rc72_n7_evidence_review import ExecutionEvidenceReviewService
    from rc7_runtime.rc72_n7_finalization import ExecutionFinalizationService
    truth, plan, prep, server, url = formal_setup(tmp_path, monkeypatch)
    try:
        server.business_delay = 0.5
        root = tmp_path / 'automatic-heartbeat'
        env = LocalHTTPEnvironment(url, root)
        runner = FormalN7RunnerAdapter(prep, evidence_root=root, environment_adapter=env,
            execution_env={'RC72_OUTPUT_ROOT': str(root)}, timeout_seconds=30,
            heartbeat_interval_seconds=0.1, renew_before_seconds=300, renewal_ttl_seconds=360)
        for item in plan['items']:
            p = prep.prepare(plan_id=plan['plan_id'], workitem_id=item['workitem_id'])
            original = truth.query('rc72_n7_execution_preparation', preparation_id=p['preparation_id'])[0]
            dispatch = SignedToolDispatchService(prep, adapters={'api_http': runner}).dispatch(p['preparation_id'])
            assert dispatch['state'] == 'RETURNED'
            c = truth.query('rc72_n6_executable_contract', contract_id=p['contract_id'])[0]
            receipt = verified_formal_receipt(prep, p, c, dispatch['raw_result'])
            assert receipt['heartbeat_protocol'] == 'OWNED_PROCESS_V1'
            rows = truth.query('rc72_execution_process_heartbeat', preparation_id=p['preparation_id'])
            assert rows and all(row['state'] == 'COMPLETED' and row['observed_exit_code'] == 0 for row in rows)
            assert any(row['renewal_refs'] for row in rows)
            assert truth.query('rc72_n7_execution_preparation', preparation_id=p['preparation_id'])[0] == original
            assert ExecutionCleanupService(prep, adapters={'api_http': env.cleanup}).run(p['preparation_id'])['state'] == 'CLEANUP_VERIFIED'
        review = ExecutionEvidenceReviewService(prep, adapter_output_root=root, capture_root=tmp_path / 'captured')
        bundle = review.build(plan['plan_id'])
        assert ExecutionFinalizationService(review).finalize(bundle['bundle_id'])['state'] == 'N7_PASS'
        assert len(server.calls) == len(plan['items'])
        assert not prep._active_dispatches and not prep._active_process_heartbeats
        assert truth.query('rc7_mission')[0]['state'] != 'CONVERGED'
    finally:
        server.shutdown()
        server.server_close()


def test_guardian_renewal_failure_stops_owned_child_and_cold_business_permission_stays_suspended(tmp_path, monkeypatch):
    from rc7_runtime.rc72_lease_renewal import ExecutionLeaseRenewalService
    from rc7_runtime.rc72_n8_execution_diagnosis import ExecutionDiagnosisService
    truth, plan, prep, server, url = formal_setup(tmp_path, monkeypatch)
    try:
        root = tmp_path / 'denied-heartbeat'
        runner = FormalN7RunnerAdapter(prep, evidence_root=root, environment_adapter=LocalHTTPEnvironment(url, root),
            execution_env={'RC72_OUTPUT_ROOT': str(root)}, timeout_seconds=30,
            heartbeat_interval_seconds=0.1, renew_before_seconds=300, renewal_ttl_seconds=360)
        def denied(*args, **kwargs):
            raise ContractError('N7_RENEWAL_WINDOW_OUTSIDE_POLICY')
        monkeypatch.setattr(ExecutionLeaseRenewalService, 'renew', denied)
        p = prep.prepare(plan_id=plan['plan_id'], workitem_id=plan['items'][0]['workitem_id'])
        dispatch = SignedToolDispatchService(prep, adapters={'api_http': runner}).dispatch(p['preparation_id'])
        assert dispatch['state'] == 'RETURNED'
        heartbeat = truth.query('rc72_execution_process_heartbeat')[0]
        assert heartbeat['state'] == 'FAILED' and heartbeat['observed_exit_code'] is not None
        assert heartbeat['runtime_exit_code'] == 125 and heartbeat['captured_files']
        assert prep.authority.is_lease_revoked(p['task_lease']['lease_id'])
        cold = _service(TruthRuntime(truth.store.path))
        with pytest.raises(ContractError, match='PROCESS_RECOVERY_REQUIRED'):
            cold.assert_current(p['preparation_id'])
        assert p['task_lease']['lease_id'] not in cold.authority._leases
        attempt = ExecutionEvidenceService(prep).record(p['preparation_id'])
        assert attempt['status'] == 'BLOCKED'
        diagnosis = ExecutionDiagnosisService(prep, evidence_root=tmp_path / 'diagnosis')
        assert diagnosis.run(p['preparation_id'])['failure_class'] == 'UNKNOWN'
        assert all(row['state'] == 'ACTIVE' for row in truth.query('rc72_data_lease'))
        assert not prep._active_process_heartbeats and not prep._active_dispatches
    finally:
        server.shutdown()
        server.server_close()


def test_live_process_record_is_not_a_cold_controller_liveness_credential(tmp_path, monkeypatch):
    truth, plan, prep, server, url = formal_setup(tmp_path, monkeypatch)
    try:
        root = tmp_path / 'live-owner'
        server.business_delay = 0.5
        runner = FormalN7RunnerAdapter(prep, evidence_root=root, environment_adapter=LocalHTTPEnvironment(url, root),
            execution_env={'RC72_OUTPUT_ROOT': str(root)}, timeout_seconds=30)
        p = prep.prepare(plan_id=plan['plan_id'], workitem_id=plan['items'][0]['workitem_id'])
        append, observed = truth.append_atomic, []
        def check_cold(event, payload):
            result = append(event, payload)
            if event == 'RC72_EXECUTION_PROCESS_HEARTBEAT_UPSERTED' and payload['state'] == 'RUNNING':
                cold = _service(TruthRuntime(truth.store.path))
                with pytest.raises(ContractError, match='PROCESS_RECOVERY_REQUIRED'):
                    cold.assert_current(p['preparation_id'])
                assert p['task_lease']['lease_id'] not in cold.authority._leases
                observed.append(payload['pid'])
            return result
        monkeypatch.setattr(truth, 'append_atomic', check_cold)
        result = SignedToolDispatchService(prep, adapters={'api_http': runner}).dispatch(p['preparation_id'])
        assert result['state'] == 'RETURNED' and observed and all(pid > 0 for pid in observed)
        assert truth.query('rc72_execution_process_heartbeat')[0]['state'] == 'COMPLETED'
        assert len(server.calls) == 1
    finally:
        server.shutdown()
        server.server_close()


def test_completed_process_capture_bytes_remain_required_for_formal_evidence(tmp_path, monkeypatch):
    truth, plan, prep, server, url = formal_setup(tmp_path, monkeypatch)
    try:
        root = tmp_path / 'immutable-process-proof'
        runner = FormalN7RunnerAdapter(prep, evidence_root=root, environment_adapter=LocalHTTPEnvironment(url, root),
            execution_env={'RC72_OUTPUT_ROOT': str(root)}, timeout_seconds=30)
        p = prep.prepare(plan_id=plan['plan_id'], workitem_id=plan['items'][0]['workitem_id'])
        dispatch = SignedToolDispatchService(prep, adapters={'api_http': runner}).dispatch(p['preparation_id'])
        c = truth.query('rc72_n6_executable_contract', contract_id=p['contract_id'])[0]
        assert verified_formal_receipt(prep, p, c, dispatch['raw_result'])
        heartbeat = truth.query('rc72_execution_process_heartbeat')[0]
        path = Path(heartbeat['captured_files']['stdout']['ref'][len('file://'):])
        path.write_bytes(path.read_bytes() + b'changed stdout')
        before = truth.store.path.read_bytes()
        with pytest.raises(ContractError, match='HEARTBEAT_CAPTURE_BYTES_CHANGED'):
            verified_formal_receipt(prep, p, c, dispatch['raw_result'])
        assert truth.store.path.read_bytes() == before
    finally:
        server.shutdown()
        server.server_close()


def test_timeout_reaps_owned_child_but_does_not_claim_remote_business_drain(tmp_path, monkeypatch):
    truth, plan, prep, server, url = formal_setup(tmp_path, monkeypatch)
    try:
        server.business_delay = 4
        root = tmp_path / 'timed-out-process'
        runner = FormalN7RunnerAdapter(prep, evidence_root=root, environment_adapter=LocalHTTPEnvironment(url, root),
            execution_env={'RC72_OUTPUT_ROOT': str(root)}, timeout_seconds=10, heartbeat_interval_seconds=0.1)
        runner.timeout = 2  # Keep source validation independent of the deliberately short process budget.
        p = prep.prepare(plan_id=plan['plan_id'], workitem_id=plan['items'][0]['workitem_id'])
        result = SignedToolDispatchService(prep, adapters={'api_http': runner}).dispatch(p['preparation_id'])
        assert result['state'] == 'RETURNED'
        heartbeat = truth.query('rc72_execution_process_heartbeat')[0]
        assert heartbeat['state'] == 'FAILED' and heartbeat['failure_kind'] == 'PROCESS_TIMEOUT'
        assert heartbeat['runtime_exit_code'] == 124 and heartbeat['observed_exit_code'] is not None
        assert len(server.calls) == 1
        assert ExecutionEvidenceService(prep).record(p['preparation_id'])['status'] == 'BLOCKED'
        assert all(row['state'] == 'ACTIVE' for row in truth.query('rc72_data_lease'))
        assert truth.query('rc72_n7_cleanup_call') == []
    finally:
        server.shutdown()
        server.server_close()


def test_lost_completed_journal_response_recovers_observation_without_second_business_action(tmp_path, monkeypatch):
    truth, plan, prep, server, url = formal_setup(tmp_path, monkeypatch)
    try:
        root = tmp_path / 'lost-completion'
        runner = FormalN7RunnerAdapter(prep, evidence_root=root, environment_adapter=LocalHTTPEnvironment(url, root),
            execution_env={'RC72_OUTPUT_ROOT': str(root)}, timeout_seconds=30)
        p = prep.prepare(plan_id=plan['plan_id'], workitem_id=plan['items'][0]['workitem_id'])
        append, lost = truth.append_atomic, []
        def lose_response(event, payload):
            result = append(event, payload)
            if event == 'RC72_EXECUTION_PROCESS_HEARTBEAT_UPSERTED' and payload['state'] == 'COMPLETED' and not lost:
                lost.append(True)
                raise RuntimeError('lost heartbeat fsync response')
            return result
        monkeypatch.setattr(truth, 'append_atomic', lose_response)
        result = SignedToolDispatchService(prep, adapters={'api_http': runner}).dispatch(p['preparation_id'])
        assert result['state'] == 'RETURNED' and lost and len(server.calls) == 1
        assert truth.query('rc72_execution_process_heartbeat')[0]['state'] == 'COMPLETED'
        assert ExecutionEvidenceService(prep).record(p['preparation_id'])['reason'] == 'CLEANUP_AND_EVIDENCE_CLOSURE_REQUIRED'
    finally:
        server.shutdown()
        server.server_close()


def test_capture_failure_suspends_permissions_and_retains_custody_after_real_business(tmp_path, monkeypatch):
    truth, plan, prep, server, url = formal_setup(tmp_path, monkeypatch)
    try:
        root = tmp_path / 'capture-failure'
        runner = FormalN7RunnerAdapter(prep, evidence_root=root, environment_adapter=LocalHTTPEnvironment(url, root),
            execution_env={'RC72_OUTPUT_ROOT': str(root)}, timeout_seconds=30)
        p = prep.prepare(plan_id=plan['plan_id'], workitem_id=plan['items'][0]['workitem_id'])
        write = Path.write_text
        def no_stdout(path, *args, **kwargs):
            if path.name == 'stdout.log' and any(row['state'] == 'EXITED' for row in truth.query('rc72_execution_process_heartbeat')):
                raise PermissionError('simulated evidence destination unavailable')
            return write(path, *args, **kwargs)
        monkeypatch.setattr(Path, 'write_text', no_stdout)
        result = SignedToolDispatchService(prep, adapters={'api_http': runner}).dispatch(p['preparation_id'])
        assert result['state'] == 'FAILED' and len(server.calls) == 1
        assert truth.query('rc72_execution_process_heartbeat')[0]['failure_kind'] == 'EVIDENCE_CAPTURE_FAILED'
        assert prep.authority.is_lease_revoked(p['task_lease']['lease_id'])
        assert all(row['state'] == 'ACTIVE' for row in truth.query('rc72_data_lease'))
        assert not prep._active_process_heartbeats and not prep._active_dispatches
    finally:
        server.shutdown()
        server.server_close()


def test_generic_fresh_process_replays_heartbeat_schema_without_trusting_pid(tmp_path, monkeypatch):
    import json
    import subprocess
    import sys
    truth, plan, prep, server, url = formal_setup(tmp_path, monkeypatch)
    try:
        root = tmp_path / 'heartbeat-schema'
        runner = FormalN7RunnerAdapter(prep, evidence_root=root, environment_adapter=LocalHTTPEnvironment(url, root),
            execution_env={'RC72_OUTPUT_ROOT': str(root)}, timeout_seconds=30)
        p = prep.prepare(plan_id=plan['plan_id'], workitem_id=plan['items'][0]['workitem_id'])
        assert SignedToolDispatchService(prep, adapters={'api_http': runner}).dispatch(p['preparation_id'])['state'] == 'RETURNED'
        code = '''import json,sys
import rc7_runtime
from rc6_runtime.truth import TruthRuntime
rows=TruthRuntime(sys.argv[1]).query('rc72_execution_process_heartbeat')
print(json.dumps([(row['state'],row['observed_exit_code']) for row in rows]))
'''
        result = subprocess.run([sys.executable, '-c', code, str(truth.store.path)],
            cwd=str(Path(__file__).resolve().parents[1]), capture_output=True, text=True, check=True)
        assert json.loads(result.stdout) == [['COMPLETED', 0]]
    finally:
        server.shutdown()
        server.server_close()


def test_spawn_failure_does_not_fabricate_a_process_or_formal_receipt(tmp_path, monkeypatch):
    import subprocess
    from types import SimpleNamespace
    import rc7_runtime.rc72_execution_heartbeat as heartbeat_module
    truth, plan, prep, server, url = formal_setup(tmp_path, monkeypatch)
    try:
        root = tmp_path / 'missing-runtime'
        runner = FormalN7RunnerAdapter(prep, evidence_root=root, environment_adapter=LocalHTTPEnvironment(url, root),
            execution_env={'RC72_OUTPUT_ROOT': str(root)}, timeout_seconds=30)
        p = prep.prepare(plan_id=plan['plan_id'], workitem_id=plan['items'][0]['workitem_id'])
        def no_process(*args, **kwargs):
            raise FileNotFoundError('runtime unavailable after probe')
        monkeypatch.setattr(heartbeat_module, 'subprocess', SimpleNamespace(Popen=no_process,
            TimeoutExpired=subprocess.TimeoutExpired, CompletedProcess=subprocess.CompletedProcess, PIPE=subprocess.PIPE))
        result = SignedToolDispatchService(prep, adapters={'api_http': runner}).dispatch(p['preparation_id'])
        assert result['state'] == 'FAILED' and result['error_type'] == 'FileNotFoundError'
        assert truth.query('rc72_execution_process_heartbeat') == []
        assert truth.query('rc72_n7_formal_runner_receipt') == [] and server.calls == []
        assert all(row['state'] == 'ACTIVE' for row in truth.query('rc72_data_lease'))
    finally:
        server.shutdown()
        server.server_close()
