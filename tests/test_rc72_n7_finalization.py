from pathlib import Path
import pytest

from rc7_runtime.rc72_formal_runner import FormalN7RunnerAdapter, FormalRunnerError, verified_formal_receipt
from rc7_runtime.rc72_n7_tool_dispatch import SignedToolDispatchService
from rc7_runtime.rc72_n7_cleanup import ExecutionCleanupService
from rc7_runtime.rc72_n7_execution_evidence import ExecutionEvidenceService
from rc7_runtime.rc72_n7_evidence_review import ExecutionEvidenceReviewService
from rc7_runtime.rc72_n7_finalization import ExecutionFinalizationService, ExecutionFinalizationError
from rc72_formal_runner_support import formal_setup, LocalHTTPEnvironment


def _bundle(tmp_path, monkeypatch):
    truth, plan, prep, server, url = formal_setup(tmp_path, monkeypatch)
    output = tmp_path / 'actual-output'
    environment = LocalHTTPEnvironment(url, output)
    runner = FormalN7RunnerAdapter(prep, evidence_root=output, environment_adapter=environment,
                                  execution_env={'RC72_OUTPUT_ROOT': str(output)}, timeout_seconds=30)
    try:
        for item in plan['items']:
            p = prep.prepare(plan_id=plan['plan_id'], workitem_id=item['workitem_id'])
            SignedToolDispatchService(prep, adapters={'api_http': runner}).dispatch(p['preparation_id'])
            ExecutionCleanupService(prep, adapters={'api_http': environment.cleanup}).run(p['preparation_id'])
        review = ExecutionEvidenceReviewService(prep, adapter_output_root=output, capture_root=tmp_path / 'captured')
        bundle = review.build(plan['plan_id'])
        return truth, plan, prep, server, review, bundle
    except BaseException:
        server.shutdown()
        server.server_close()
        raise


@pytest.mark.parametrize('after_first_case', [False, True])
def test_interrupted_finalization_reuses_review_and_never_repeats_business_io(tmp_path, monkeypatch, after_first_case):
    truth, plan, prep, server, review, bundle = _bundle(tmp_path, monkeypatch)
    try:
        append = truth.append_atomic
        completed = []
        def interrupt(event, payload, **kwargs):
            if event == 'EXECUTION_ATTEMPT_UPSERTED' and payload.get('status') == 'PASS':
                if not after_first_case or completed:
                    raise KeyboardInterrupt()
                completed.append(payload['attempt_id'])
            return append(event, payload, **kwargs)
        monkeypatch.setattr(truth, 'append_atomic', interrupt)
        with pytest.raises(KeyboardInterrupt):
            ExecutionFinalizationService(review).finalize(bundle['bundle_id'])
        assert len(truth.query('rc72_n7_execution_review')) == 1
        pid = truth.query('rc72_n7_execution_review')[0]['pid']
        monkeypatch.setattr(truth, 'append_atomic', append)
        result = ExecutionFinalizationService(review).finalize(bundle['bundle_id'])
        assert result['state'] == 'N7_PASS'
        assert len(server.calls) == len(plan['items'])
        assert truth.query('rc72_n7_execution_review')[0]['pid'] == pid
        assert len(truth.query('execution_attempt')) == len(plan['items'])
        assert len(truth.query('rc72_reviewer_assignment')) == 1
        assert truth.query('rc7_mission', mission_id=plan['mission_id'])[0]['state'] != 'CONVERGED'
    finally:
        server.shutdown()
        server.server_close()


def test_fixture_only_results_cannot_enter_actual_finalization(tmp_path, monkeypatch):
    from test_rc72_n7_evidence_review import _executed
    truth, prep, plan, prepared, review = _executed(tmp_path, monkeypatch)
    bundle = review.build(plan['plan_id'])
    before = list(truth.store.iter_raw())
    with pytest.raises(ExecutionFinalizationError, match='FORMAL_TARGET_OR_RUNNER_PROOF_REQUIRED'):
        ExecutionFinalizationService(review).finalize(bundle['bundle_id'])
    assert list(truth.store.iter_raw()) == before
    assert {row['status'] for row in truth.query('execution_attempt')} == {'BLOCKED'}


def test_stale_target_facts_are_rejected_before_any_dispatch_or_network_call(tmp_path, monkeypatch):
    def stale(profile):
        for row in profile['facts']:
            row['verified_at'] = '2000-01-01T00:00:00+00:00'
    truth, plan, prep, server, url = formal_setup(tmp_path, monkeypatch, profile_mutator=stale)
    try:
        output = tmp_path / 'actual-output'
        environment = LocalHTTPEnvironment(url, output)
        runner = FormalN7RunnerAdapter(prep, evidence_root=output, environment_adapter=environment,
                                      execution_env={'RC72_OUTPUT_ROOT': str(output)}, timeout_seconds=30)
        p = prep.prepare(plan_id=plan['plan_id'], workitem_id=plan['items'][0]['workitem_id'])
        before = list(truth.store.iter_raw())
        with pytest.raises(FormalRunnerError, match='TARGET_FACT_STALE'):
            SignedToolDispatchService(prep, adapters={'api_http': runner}).dispatch(p['preparation_id'])
        assert list(truth.store.iter_raw()) == before
        assert server.calls == []
        assert not list(output.glob('probe-*.json'))
    finally:
        server.shutdown()
        server.server_close()


def test_modified_script_is_caught_by_actual_qualification_loader_before_target_io(tmp_path, monkeypatch):
    truth, plan, prep, server, url = formal_setup(tmp_path, monkeypatch)
    try:
        item = plan['items'][0]
        source = tmp_path / 'qualified' / item['case_id'] / 'test_formal_api.py'
        source.write_text("raise RuntimeError('unapproved source must never execute')\n")
        output = tmp_path / 'actual-output'
        environment = LocalHTTPEnvironment(url, output)
        runner = FormalN7RunnerAdapter(prep, evidence_root=output, environment_adapter=environment,
                                      execution_env={'RC72_OUTPUT_ROOT': str(output)}, timeout_seconds=30)
        p = prep.prepare(plan_id=plan['plan_id'], workitem_id=item['workitem_id'])
        result = SignedToolDispatchService(prep, adapters={'api_http': runner}).dispatch(p['preparation_id'])
        # A changed script was stopped before this fixture's HTTP request,
        # but no signed pre-execution no-effect attestation was produced.
        # Therefore it cannot be downgraded to a retryable FAILED outcome.
        assert result['state'] == 'UNKNOWN' and result['replay_prohibited'] is True
        assert server.calls == []
        assert truth.query('rc72_n7_formal_runner_receipt') == []
        assert all(row['state'] == 'ACTIVE' for row in truth.query('rc72_data_lease'))
    finally:
        server.shutdown()
        server.server_close()


def test_rehashed_process_success_without_runtime_signature_cannot_be_accepted(tmp_path, monkeypatch):
    truth, plan, prep, server, review, bundle = _bundle(tmp_path, monkeypatch)
    try:
        receipt = truth.query('rc72_n7_formal_runner_receipt')[0]
        receipt['runner_result']['exit_code'] = 1
        receipt['artifact_version'] += 1
        truth.append_atomic('RC72_N7_FORMAL_RUNNER_RECEIPT_UPSERTED', receipt)
        before = list(truth.store.iter_raw())
        with pytest.raises(FormalRunnerError, match='SIGNATURE_INVALID'):
            ExecutionFinalizationService(review).finalize(bundle['bundle_id'])
        assert list(truth.store.iter_raw()) == before
        assert {row['status'] for row in truth.query('execution_attempt')} == {'BLOCKED'}
    finally:
        server.shutdown()
        server.server_close()


def test_source_probe_log_rotation_does_not_mutate_captured_runtime_proof(tmp_path, monkeypatch):
    truth, plan, prep, server, review, bundle = _bundle(tmp_path, monkeypatch)
    try:
        for row in truth.query('rc72_n7_formal_runner_receipt'):
            Path(row['tool_probe']['evidence_ref'][len('file://'):]).write_text('rotated provider log')
        result = ExecutionFinalizationService(review).finalize(bundle['bundle_id'])
        assert result['state'] == 'N7_PASS'
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize('missing', ['data', 'precondition'])
def test_live_precondition_or_data_failure_blocks_runner_and_preserves_diagnosis_evidence(tmp_path, monkeypatch, missing):
    truth, plan, prep, server, url = formal_setup(tmp_path, monkeypatch)
    try:
        if missing == 'data':
            server.allowed_data_refs.clear()
        else:
            server.precondition_ready = False
        output = tmp_path / 'actual-output'
        environment = LocalHTTPEnvironment(url, output)
        runner = FormalN7RunnerAdapter(prep, evidence_root=output, environment_adapter=environment,
                                      execution_env={'RC72_OUTPUT_ROOT': str(output)}, timeout_seconds=30)
        p = prep.prepare(plan_id=plan['plan_id'], workitem_id=plan['items'][0]['workitem_id'])
        dispatched = SignedToolDispatchService(prep, adapters={'api_http': runner}).dispatch(p['preparation_id'])
        assert dispatched['state'] == 'FAILED'
        assert server.calls == []
        checks = [row for row in truth.query('rc7_evidence') if row.get('kind') in {'N7_FORMAL_PRECONDITION', 'N7_FORMAL_DATA_RECHECK'}]
        assert any(row['check_success'] is False for row in checks)
        attempt = ExecutionEvidenceService(prep).record(p['preparation_id'])
        assert set(row['evidence_id'] for row in checks).issubset(attempt['evidence_refs'])
        diagnosis = ExecutionEvidenceService(prep).begin_diagnosis(p['preparation_id'])
        assert diagnosis.worker_id != p['worker_id']
    finally:
        server.shutdown()
        server.server_close()


def test_review_receipt_rejects_byte_identical_external_file_even_with_valid_signature(tmp_path, monkeypatch):
    """P1-6: signed verdict/digest cannot authorize an unrelated evidence file."""
    from copy import deepcopy
    import hashlib
    truth, plan, prep, server, review, bundle = _bundle(tmp_path, monkeypatch)
    try:
        finalizer = ExecutionFinalizationService(review)
        assert finalizer.finalize(bundle['bundle_id'])['state'] == 'N7_PASS'
        receipt = truth.query('rc72_n7_execution_review')[0]
        original = Path(receipt['stdout_ref'][len('file://'):])
        detached = tmp_path / 'unrelated-review-output.json'
        detached.write_bytes(original.read_bytes())
        forged = deepcopy(receipt)
        forged['stdout_ref'] = 'file://' + str(detached)
        # The native private signer can sign a payload in this adversarial
        # test. File-scope validation must independently refuse it anyway.
        signed = {k: v for k, v in forged.items()
                  if k not in {'signature', 'artifact_type', 'artifact_version'}}
        forged['signature'] = prep.authority._sign(signed)
        assert forged['stdout_sha256'] == hashlib.sha256(detached.read_bytes()).hexdigest()
        before = list(truth.store.iter_raw())
        with pytest.raises(ExecutionFinalizationError, match='N7_REVIEW_PROCESS_EVIDENCE_SCOPE_CHANGED'):
            finalizer._verify(forged)
        assert list(truth.store.iter_raw()) == before
        assert len(server.calls) == len(plan['items'])
    finally:
        server.shutdown()
        server.server_close()


def test_final_gate_rechecks_current_case_fanout_without_repeating_business_io(tmp_path, monkeypatch):
    """An ETU mutated after PASS cannot be used to justify an older N7 Gate."""
    from rc7_runtime.rc72_n7_execution_planning import ExecutionPlanningError
    truth, plan, prep, server, review, bundle = _bundle(tmp_path, monkeypatch)
    try:
        finalizer = ExecutionFinalizationService(review)
        assert finalizer.finalize(bundle['bundle_id'])['state'] == 'N7_PASS'
        etu = truth.query('rc72_etu', etu_id=plan['items'][0]['etu_id'])[0]
        etu['case_ids'] = list(etu['case_ids']) + ['TC-UNAPPROVED-POST-EXECUTION']
        etu['artifact_version'] += 1
        truth.append_atomic('RC72_ETU_UPSERTED', etu)
        before = list(truth.store.iter_raw())
        with pytest.raises(ExecutionPlanningError, match='N7_PLAN_CASE_FANOUT_LINEAGE_MISMATCH'):
            finalizer.audit(bundle['bundle_id'])
        assert list(truth.store.iter_raw()) == before
        assert len(server.calls) == len(plan['items'])
    finally:
        server.shutdown()
        server.server_close()


def test_independent_gate_rejects_attempt_rebound_to_another_case_after_real_dispatch(tmp_path, monkeypatch):
    """P1-5/P1-6: an actual Attempt cannot be claimed by a sibling Case."""
    from rc7_runtime.rc72_n7_evidence_review import EvidenceReviewError
    truth, plan, prep, server, review, bundle = _bundle(tmp_path, monkeypatch)
    try:
        first = bundle['case_results'][0]
        attempt = truth.query('execution_attempt', attempt_id=first['attempt_id'])[0]
        attempt['tc_id'] = 'UNRELATED-CASE-ID'
        attempt['artifact_version'] += 1
        truth.append_atomic('EXECUTION_ATTEMPT_UPSERTED', attempt)
        before = truth.store.path.read_bytes()
        with pytest.raises(EvidenceReviewError, match='N7_REVIEW_ATTEMPT_ASSERTION_MISMATCH'):
            ExecutionFinalizationService(review).finalize(bundle['bundle_id'])
        assert truth.store.path.read_bytes() == before
        assert len(server.calls) == len(plan['items'])
        assert not truth.query('rc72_n7_execution_review')
    finally:
        server.shutdown()
        server.server_close()
