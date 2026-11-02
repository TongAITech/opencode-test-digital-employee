from copy import deepcopy
import hashlib
from pathlib import Path
import pytest

from rc6_runtime.truth import TruthRuntime, EventValidationError
from rc7_runtime.rc72_n7_evidence_review import ExecutionEvidenceReviewService, EvidenceReviewError
from rc7_runtime.rc72_n7_tool_dispatch import SignedToolDispatchService
from rc7_runtime.rc72_n7_cleanup import ExecutionCleanupService
from test_rc72_n7_execution_preparation import _setup, _service
from test_rc72_n7_execution_evidence import ACTUAL
from test_rc72_n7_cleanup import _adapter


def _executed(tmp_path, monkeypatch, *, count=None, mutate=None, skip_cleanup=False):
    truth, plan = _setup(tmp_path, monkeypatch)
    preparation = _service(truth)
    output = tmp_path / 'adapter-output'
    output.mkdir()
    prepared = []
    def execute(*, contract, context):
        records = []
        for index, requirement in enumerate(contract['evidence_required']):
            data = ('fixture observation %s %s' % (context['attempt_id'], requirement)).encode()
            name = '%s-%d.log' % (context['attempt_id'], index)
            (output / name).write_bytes(data)
            records.append(dict(requirement=requirement, attempt_id=context['attempt_id'],
                tool=contract['tool_route']['tool'], path=name, sha256=hashlib.sha256(data).hexdigest()))
        if mutate:
            mutate(records, output)
        return dict(deepcopy(ACTUAL), evidence=records)
    for item in plan['items'] if count is None else plan['items'][:count]:
        p = preparation.prepare(plan_id=plan['plan_id'], workitem_id=item['workitem_id'])
        SignedToolDispatchService(preparation, adapters={'api_http': execute}).dispatch(p['preparation_id'])
        if not skip_cleanup:
            ExecutionCleanupService(preparation, adapters={'api_http': _adapter([])}).run(p['preparation_id'])
        prepared.append(p)
    service = ExecutionEvidenceReviewService(preparation, adapter_output_root=output,
                                             capture_root=tmp_path / 'captured')
    return truth, preparation, plan, prepared, service


def test_all_cases_capture_actual_files_and_enter_fresh_review_without_pass(tmp_path, monkeypatch):
    truth, prep, plan, prepared, service = _executed(tmp_path, monkeypatch)
    bundle = service.build(plan['plan_id'])
    assert len(bundle['case_results']) == len(plan['items']) > 1
    assert {case['case_id'] for case in bundle['case_results']} == {item['case_id'] for item in plan['items']}
    assert bundle['known_gaps'] == ['FULL_TARGET_IDENTITY_BINDING_REQUIRED', 'APPROVED_RUNNER_RECEIPT_REQUIRED']
    for case in bundle['case_results']:
        for row in case['captured_evidence']:
            path = Path(row['content_ref'][len('file://'):])
            assert hashlib.sha256(path.read_bytes()).hexdigest() == row['sha256']
            assert truth.query('evidence', id=row['evidence_id'])[0]['attempt_id'] == case['attempt_id']
    review = service.request_review(bundle['bundle_id'])
    assert review['reviewer_session_id'] not in {p['session_id'] for p in prepared}
    assert review['reviewer_worker_id'] not in {p['worker_id'] for p in prepared}
    assert truth.query('rc72_mission_node', mission_id=plan['mission_id'], node_type='N7_EXECUTION')[0]['state'] == 'REVIEW_PENDING'
    assert {row['status'] for row in truth.query('execution_attempt')} == {'BLOCKED'}
    assert {row['state'] for row in truth.query('rc7_task', task_type='RC72_CASE_EXECUTION')} == {'RUNNING'}
    before = list(truth.store.iter_raw())
    assert service.request_review(bundle['bundle_id']) == review
    assert service.build(plan['plan_id']) == bundle
    assert list(truth.store.iter_raw()) == before


def test_partial_case_denominator_never_creates_bundle(tmp_path, monkeypatch):
    truth, prep, plan, prepared, service = _executed(tmp_path, monkeypatch, count=1)
    before = list(truth.store.iter_raw())
    with pytest.raises(EvidenceReviewError, match='CASE_EXECUTION_REQUIRED'):
        service.build(plan['plan_id'])
    assert list(truth.store.iter_raw()) == before
    assert not service.capture_root.exists()


@pytest.mark.parametrize('mutation', ['missing', 'wrong_owner', 'wrong_hash', 'outside_path', 'symlink'])
def test_unproven_evidence_cannot_be_collected_or_reviewed(tmp_path, monkeypatch, mutation):
    import os
    if mutation == 'symlink' and os.name == 'nt':
        pytest.skip('Windows symlink privilege is not guaranteed')
    outside = tmp_path / 'outside.log'
    outside.write_bytes(b'outside evidence')
    def mutate(records, output):
        if mutation == 'missing':
            records.clear()
        elif mutation == 'wrong_owner':
            records[0]['attempt_id'] = 'someone-else'
        elif mutation == 'wrong_hash':
            records[0]['sha256'] = '0' * 64
        elif mutation == 'outside_path':
            records[0]['path'] = '../outside.log'
            records[0]['sha256'] = hashlib.sha256(outside.read_bytes()).hexdigest()
        else:
            (output / 'linked.log').unlink(missing_ok=True)
            (output / 'linked.log').symlink_to(outside)
            records[0]['path'] = 'linked.log'
            records[0]['sha256'] = hashlib.sha256(outside.read_bytes()).hexdigest()
    truth, prep, plan, prepared, service = _executed(tmp_path, monkeypatch, mutate=mutate)
    before = list(truth.store.iter_raw())
    with pytest.raises(EvidenceReviewError):
        service.build(plan['plan_id'])
    assert list(truth.store.iter_raw()) == before
    assert not service.capture_root.exists()


def test_captured_bytes_are_rechecked_and_do_not_depend_on_adapter_files(tmp_path, monkeypatch):
    truth, prep, plan, prepared, service = _executed(tmp_path, monkeypatch)
    bundle = service.build(plan['plan_id'])
    for path in service.output_root.iterdir():
        path.unlink()
    assert service.build(plan['plan_id']) == bundle
    captured = Path(bundle['case_results'][0]['captured_evidence'][0]['content_ref'][len('file://'):])
    captured.write_bytes(b'corrupted after collection')
    before = list(truth.store.iter_raw())
    with pytest.raises(EvidenceReviewError, match='DIGEST_MISMATCH'):
        service.request_review(bundle['bundle_id'])
    assert list(truth.store.iter_raw()) == before


def test_upstream_stale_prevents_review_even_with_captured_files(tmp_path, monkeypatch):
    from rc7_runtime.rc72_domain import AutonomousMissionNode
    truth, prep, plan, prepared, service = _executed(tmp_path, monkeypatch)
    bundle = service.build(plan['plan_id'])
    node = service.runtime.node_by_type(plan['mission_id'], AutonomousMissionNode.N6_EXECUTABLE_READINESS)
    service.runtime.mark_stale(node['mission_node_id'], reason='source contract changed')
    before = list(truth.store.iter_raw())
    with pytest.raises(ValueError, match='UPSTREAM_NOT_PASS'):
        service.request_review(bundle['bundle_id'])
    assert list(truth.store.iter_raw()) == before


def test_unreleased_resources_cannot_enter_review(tmp_path, monkeypatch):
    from rc7_runtime.rc72_n7_execution_evidence import ExecutionEvidenceService
    truth, prep, plan, prepared, service = _executed(tmp_path, monkeypatch, skip_cleanup=True)
    for p in prepared:
        ExecutionEvidenceService(prep).record(p['preparation_id'])
    before = list(truth.store.iter_raw())
    with pytest.raises(ValueError):
        service.build(plan['plan_id'])
    assert list(truth.store.iter_raw()) == before


def test_cold_replay_reuses_bundle_and_reviewer(tmp_path, monkeypatch):
    truth, prep, plan, prepared, service = _executed(tmp_path, monkeypatch)
    bundle = service.build(plan['plan_id'])
    review = service.request_review(bundle['bundle_id'])
    replay = TruthRuntime(truth.store.path)
    resumed = ExecutionEvidenceReviewService(_service(replay), adapter_output_root=service.output_root,
                                              capture_root=service.capture_root)
    before = list(replay.store.iter_raw())
    assert resumed.request_review(bundle['bundle_id']) == review
    assert list(replay.store.iter_raw()) == before


def test_resume_delivery_append_before_node_state_write(tmp_path, monkeypatch):
    truth, prep, plan, prepared, service = _executed(tmp_path, monkeypatch)
    bundle = service.build(plan['plan_id'])
    persist = service.runtime._persist_node_state
    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt()
    monkeypatch.setattr(service.runtime, '_persist_node_state', interrupt)
    with pytest.raises(KeyboardInterrupt):
        service.request_review(bundle['bundle_id'])
    assert len(truth.query('rc72_node_delivery', node_type='N7_EXECUTION')) == 1
    monkeypatch.setattr(service.runtime, '_persist_node_state', persist)
    review = service.request_review(bundle['bundle_id'])
    assert review['state'] == 'REVIEW_PENDING'
    assert len(truth.query('rc72_node_delivery', node_type='N7_EXECUTION')) == 1
    assert len(truth.query('rc72_reviewer_assignment', delivery_id=review['delivery_id'])) == 1


def test_resume_orphan_fresh_review_session_without_creating_a_second_worker(tmp_path, monkeypatch):
    truth, prep, plan, prepared, service = _executed(tmp_path, monkeypatch)
    bundle = service.build(plan['plan_id'])
    append = truth.append_atomic
    def interrupt(event, payload, **kwargs):
        if event == 'RC72_REVIEWER_ASSIGNMENT_UPSERTED':
            raise KeyboardInterrupt()
        return append(event, payload, **kwargs)
    monkeypatch.setattr(truth, 'append_atomic', interrupt)
    with pytest.raises(KeyboardInterrupt):
        service.request_review(bundle['bundle_id'])
    sessions = truth.query('rc72_worker_session', purpose='REVIEW')
    assert len(sessions) == 1
    monkeypatch.setattr(truth, 'append_atomic', append)
    review = service.request_review(bundle['bundle_id'])
    assert review['reviewer_session_id'] == sessions[0]['session_id']
    assert len(truth.query('rc72_worker_session', purpose='REVIEW')) == 1
    before = list(truth.store.iter_raw())
    assert service.request_review(bundle['bundle_id']) == review
    assert list(truth.store.iter_raw()) == before


@pytest.mark.parametrize('limit', ['file', 'bundle'])
def test_evidence_size_limits_fail_before_any_capture_without_truncating_scope(tmp_path, monkeypatch, limit):
    truth, prep, plan, prepared, original = _executed(tmp_path, monkeypatch)
    service = ExecutionEvidenceReviewService(prep, adapter_output_root=original.output_root,
        capture_root=original.capture_root, max_file_bytes=1 if limit == 'file' else 1024 * 1024,
        max_bundle_bytes=1 if limit == 'bundle' else 1024 * 1024)
    before = list(truth.store.iter_raw())
    with pytest.raises(EvidenceReviewError, match='SIZE_LIMIT_EXCEEDED'):
        service.build(plan['plan_id'])
    assert list(truth.store.iter_raw()) == before
    assert not service.capture_root.exists()


@pytest.mark.parametrize('field', ['mission_id', 'source_commit', 'known_gaps'])
def test_rehashed_bundle_cannot_change_scope_or_hide_open_delivery_gaps(tmp_path, monkeypatch, field):
    from rc7_runtime.rc72_n7_execution_admission import _hash
    truth, prep, plan, prepared, service = _executed(tmp_path, monkeypatch)
    bundle = service.build(plan['plan_id'])
    forged = deepcopy(bundle)
    forged[field] = [] if field == 'known_gaps' else 'wrong-scope'
    core = {k: v for k, v in forged.items() if k not in {'bundle_id', 'bundle_sha256', 'artifact_type', 'artifact_version'}}
    forged['bundle_sha256'] = _hash(core)
    forged['bundle_id'] = 'N7BUNDLE-' + forged['bundle_sha256'][:24]
    truth.append_atomic('RC72_N7_EVIDENCE_BUNDLE_UPSERTED', forged)
    before = list(truth.store.iter_raw())
    with pytest.raises(EvidenceReviewError, match='SCOPE_OR_GAPS_CHANGED'):
        service.request_review(forged['bundle_id'])
    assert list(truth.store.iter_raw()) == before


def test_bundle_replays_in_a_separate_process_with_builtin_schema_bootstrap(tmp_path, monkeypatch):
    import subprocess
    import sys
    truth, prep, plan, prepared, service = _executed(tmp_path, monkeypatch)
    bundle = service.build(plan['plan_id'])
    review = service.request_review(bundle['bundle_id'])
    script = '''import sys
import rc7_runtime
from rc6_runtime.truth import TruthRuntime
truth = TruthRuntime(sys.argv[1])
bundle = truth.query('rc72_n7_evidence_bundle', bundle_id=sys.argv[2])[0]
assert len(bundle['case_results']) > 1
assert truth.query('rc72_reviewer_assignment', review_id=sys.argv[3])
'''
    subprocess.run([sys.executable, '-c', script, str(truth.store.path), bundle['bundle_id'], review['review_id']],
                   check=True, capture_output=True, text=True)


def test_interrupted_capture_never_publishes_partial_canonical_bytes(tmp_path, monkeypatch):
    import rc7_runtime.rc72_n7_evidence_review as module
    truth, prep, plan, prepared, service = _executed(tmp_path, monkeypatch)
    link = module.os.link
    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt()
    monkeypatch.setattr(module.os, 'link', interrupt)
    before = list(truth.store.iter_raw())
    with pytest.raises(KeyboardInterrupt):
        service.build(plan['plan_id'])
    assert list(truth.store.iter_raw()) == before
    assert list(service.capture_root.iterdir()) == []
    monkeypatch.setattr(module.os, 'link', link)
    bundle = service.build(plan['plan_id'])
    assert len(bundle['case_results']) == len(plan['items'])
