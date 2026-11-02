"""Actual business/cleanup process evidence is checkpointed, never promoted PASS."""
import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import ContractError
from rc7_runtime.rc72_formal_runner import FormalN7RunnerAdapter
from rc7_runtime.rc72_n7_cleanup import ExecutionCleanupService
from rc7_runtime.rc72_n7_evidence_review import ExecutionEvidenceReviewService
from rc7_runtime.rc72_n7_member_drain import ExecutionMemberDrainService, assert_drained_member
from rc7_runtime.rc72_n7_tool_dispatch import SignedToolDispatchService
from rc72_formal_runner_support import formal_setup, LocalHTTPEnvironment
from test_rc72_n7_execution_preparation import _service


def _completed(tmp_path, monkeypatch, *, cleanup=True):
    truth, plan, prep, server, url = formal_setup(tmp_path, monkeypatch)
    root = tmp_path / 'actual-member'
    env = LocalHTTPEnvironment(url, root)
    runner = FormalN7RunnerAdapter(prep, evidence_root=root, environment_adapter=env,
        execution_env={'RC72_OUTPUT_ROOT': str(root)}, timeout_seconds=30)
    p = prep.prepare(plan_id=plan['plan_id'], workitem_id=plan['items'][0]['workitem_id'])
    try:
        assert SignedToolDispatchService(prep, adapters={'api_http': runner}).dispatch(p['preparation_id'])['state'] == 'RETURNED'
        if cleanup:
            assert ExecutionCleanupService(prep, adapters={'api_http': env.cleanup}).run(p['preparation_id'])['state'] == 'CLEANUP_VERIFIED'
        review = ExecutionEvidenceReviewService(prep, adapter_output_root=root, capture_root=tmp_path / 'captured-member')
        return truth, plan, prep, server, p, ExecutionMemberDrainService(review)
    except BaseException:
        server.shutdown()
        server.server_close()
        raise


def _close(server):
    server.shutdown()
    server.server_close()


def test_actual_member_closes_without_pass_or_business_replay_and_cold_audit_is_read_only(tmp_path, monkeypatch):
    truth, plan, prep, server, p, service = _completed(tmp_path, monkeypatch)
    try:
        attempt = truth.query('execution_attempt', attempt_id=p['attempt_id'])[0]
        result = service.drain(p['preparation_id'])
        assert result['state'] == 'DRAINED'
        assert truth.query('rc72_n7_execution_preparation', preparation_id=p['preparation_id'])[0]['status'] == 'DRAINED'
        assert truth.query('rc72_worker_session', session_id=p['session_id'])[0]['state'] == 'CLOSED'
        assert truth.query('rc7_task', task_id=p['workitem_id'])[0]['state'] == 'RUNNING'
        assert truth.query('rc72_workitem_attempt_binding', binding_id=p['binding_id'])[0]['state'] == 'EVIDENCE_READY'
        assert truth.query('execution_attempt', attempt_id=p['attempt_id'])[0] == attempt
        assert attempt['status'] == 'BLOCKED' and len(server.calls) == 1
        assert all(row['state'] == 'RELEASED' for row in truth.query('rc72_data_lease', attempt_id=p['attempt_id']))
        before = truth.store.path.read_bytes()
        assert service.drain(p['preparation_id']) == result
        cold = _service(TruthRuntime(truth.store.path))
        assert assert_drained_member(cold, p['preparation_id']) == result
        with pytest.raises(ContractError, match='SUSPENDED_BY_MEMBER_CHECKPOINT'):
            cold.assert_current(p['preparation_id'])
        assert cold.truth.store.path.read_bytes() == before
        assert cold.authority.is_lease_revoked(p['task_lease']['lease_id'])
        # Still cannot turn one member into a whole-plan evidence bundle.
        with pytest.raises(ContractError, match='CASE_EXECUTION_REQUIRED'):
            service.review.build(plan['plan_id'])
    finally:
        _close(server)


@pytest.mark.parametrize('event', ['RC72_N7_MEMBER_DRAIN_UPSERTED', 'RC72_WORKER_SESSION_UPSERTED', 'RC72_N7_EXECUTION_PREPARATION_UPSERTED'])
def test_partial_checkpoint_cold_resume_never_replays_process_or_restores_permission(tmp_path, monkeypatch, event):
    truth, _, prep, server, p, service = _completed(tmp_path, monkeypatch)
    try:
        append, hit = truth.append_atomic, []
        def crash(kind, payload, **kwargs):
            result = append(kind, payload, **kwargs)
            if kind == event and not hit:
                hit.append(True)
                raise KeyboardInterrupt()
            return result
        monkeypatch.setattr(truth, 'append_atomic', crash)
        with pytest.raises(KeyboardInterrupt):
            service.drain(p['preparation_id'])
        cold = _service(TruthRuntime(truth.store.path))
        with pytest.raises(ContractError, match='SUSPENDED_BY_MEMBER_CHECKPOINT'):
            cold.assert_current(p['preparation_id'])
        review = ExecutionEvidenceReviewService(cold, adapter_output_root=service.review.output_root,
                                               capture_root=service.review.capture_root)
        row = ExecutionMemberDrainService(review).drain(p['preparation_id'])
        assert row['state'] == 'DRAINED' and len(server.calls) == 1
        assert len(cold.truth.query('execution_attempt')) == 1
        assert cold.authority.is_lease_revoked(p['task_lease']['lease_id'])
    finally:
        _close(server)


def test_no_cleanup_proof_cannot_checkpoint_or_release_resource_custody(tmp_path, monkeypatch):
    truth, _, prep, server, p, service = _completed(tmp_path, monkeypatch, cleanup=False)
    try:
        before = truth.store.path.read_bytes()
        with pytest.raises(ContractError):
            service.drain(p['preparation_id'])
        assert truth.store.path.read_bytes() == before
        assert not truth.query('rc72_n7_member_drain')
        assert {row['state'] for row in truth.query('rc72_data_lease')} == {'ACTIVE'}
        assert len(server.calls) == 1
    finally:
        _close(server)


def test_captured_bytes_and_signed_scope_are_reverified_before_historical_acceptance(tmp_path, monkeypatch):
    truth, _, _, server, p, service = _completed(tmp_path, monkeypatch)
    try:
        row = service.drain(p['preparation_id'])
        from pathlib import Path
        path = Path(row['captured_evidence'][0]['content_ref'][len('file://'):])
        path.write_bytes(b'changed')
        with pytest.raises(ContractError, match='CAPTURE_BYTES_CHANGED'):
            service.assert_drained(p['preparation_id'])
        changed = dict(row, mission_id='UNRELATED', artifact_version=row['artifact_version'] + 1)
        truth.append_atomic('RC72_N7_MEMBER_DRAIN_UPSERTED', changed)
        with pytest.raises(ContractError, match='SIGNATURE_INVALID'):
            service.drain(p['preparation_id'])
        assert len(server.calls) == 1
    finally:
        _close(server)


def test_other_successful_member_must_be_drained_before_actual_n8_repair_boundary(tmp_path, monkeypatch):
    from rc7_runtime.rc72_n8_execution_diagnosis import ExecutionDiagnosisService
    from rc7_runtime.rc72_n8_repair_boundary import RepairBoundaryService
    from rc7_runtime.rc72_n7_execution_evidence import ExecutionEvidenceService
    truth, plan, prep, server, completed, service = _completed(tmp_path, monkeypatch)
    try:
        original_attempt = truth.query('execution_attempt', attempt_id=completed['attempt_id'])[0]
        # The first Case actually executed and compensated. A different original
        # Case now loses its exact DataRef before any business mutation.
        server.allowed_data_refs.clear()
        failed = prep.prepare(plan_id=plan['plan_id'], workitem_id=plan['items'][1]['workitem_id'])
        root = tmp_path / 'other-failure'
        env = LocalHTTPEnvironment('http://127.0.0.1:%d' % server.server_address[1], root)
        runner = FormalN7RunnerAdapter(prep, evidence_root=root, environment_adapter=env,
            execution_env={'RC72_OUTPUT_ROOT': str(root)}, timeout_seconds=30)
        assert SignedToolDispatchService(prep, adapters={'api_http': runner}).dispatch(failed['preparation_id'])['state'] == 'FAILED'
        ExecutionEvidenceService(prep).record(failed['preparation_id'])
        diagnosis = ExecutionDiagnosisService(prep, evidence_root=tmp_path / 'diagnosis')
        assert diagnosis.run(failed['preparation_id'])['failure_class'] == 'TEST_DATA_GAP'
        boundary = RepairBoundaryService(diagnosis, cleanup_adapters={'api_http': env.cleanup})
        with pytest.raises(ContractError, match='OTHER_EXECUTION_MUST_DRAIN'):
            boundary.open(failed['preparation_id'])
        drained = service.drain(completed['preparation_id'])
        assert drained['state'] == 'DRAINED'
        assert boundary.open(failed['preparation_id'])['state'] == 'REPAIR_OPEN'
        assert len(server.calls) == 1
        assert truth.query('execution_attempt', attempt_id=completed['attempt_id'])[0] == original_attempt
        assert truth.query('rc72_n7_execution_preparation', preparation_id=completed['preparation_id'])[0]['status'] == 'DRAINED'
        # Drain is not a reuse decision. Current continuation must still refuse
        # a READY rewrite or another business run for this historical member.
        assert truth.query('rc7_task', task_id=completed['workitem_id'])[0]['state'] == 'RUNNING'
    finally:
        _close(server)


@pytest.mark.parametrize('change', ['signature', 'unsigned'])
def test_mutated_or_unsigned_cleanup_cannot_authorize_member_checkpoint(tmp_path, monkeypatch, change):
    truth, _, _, server, p, service = _completed(tmp_path, monkeypatch)
    try:
        call = truth.query('rc72_n7_cleanup_call', preparation_id=p['preparation_id'])[0]
        call['artifact_version'] += 1
        if change == 'signature':
            call['runtime_signature'] = '0' * 64
        else:
            call.pop('runtime_signature')
        truth.append_atomic('RC72_N7_CLEANUP_CALL_UPSERTED', call)
        before = truth.store.path.read_bytes()
        with pytest.raises(ContractError, match='CLEANUP_(SIGNATURE_INVALID|REQUIRED)|SIGNED_CLEANUP_REQUIRED'):
            service.drain(p['preparation_id'])
        assert truth.store.path.read_bytes() == before and not truth.query('rc72_n7_member_drain')
        assert len(server.calls) == 1
    finally:
        _close(server)


def test_actual_unknown_business_effect_never_becomes_a_drained_member(tmp_path, monkeypatch):
    import json
    from urllib.request import Request, urlopen
    truth, plan, prep, server, completed, service = _completed(tmp_path, monkeypatch)
    try:
        pending = prep.prepare(plan_id=plan['plan_id'], workitem_id=plan['items'][1]['workitem_id'])
        def lost_after_remote_commit(**kwargs):
            request = Request('http://127.0.0.1:%d/execute' % server.server_address[1],
                              data=json.dumps({'actual': pending['attempt_id']}).encode(), method='POST')
            with urlopen(request, timeout=5) as response:
                assert response.status == 200
            raise KeyboardInterrupt()
        with pytest.raises(KeyboardInterrupt):
            SignedToolDispatchService(prep, adapters={'api_http': lost_after_remote_commit}).dispatch(pending['preparation_id'])
        before = truth.store.path.read_bytes()
        with pytest.raises(ContractError):
            service.drain(pending['preparation_id'])
        assert truth.store.path.read_bytes() == before
        assert not truth.query('rc72_n7_member_drain', preparation_id=pending['preparation_id'])
        assert truth.query('rc72_n7_tool_dispatch', preparation_id=pending['preparation_id'])[0]['state'] == 'IN_FLIGHT'
        assert {row['state'] for row in truth.query('rc72_data_lease', attempt_id=pending['attempt_id'])} == {'ACTIVE'}
        assert len(server.calls) == 2
        cold = _service(TruthRuntime(truth.store.path))
        with pytest.raises(ContractError, match='EXECUTION_CONTROLLER_RECOVERY_REQUIRED'):
            cold.assert_current(pending['preparation_id'])
    finally:
        _close(server)
