"""Approved fixture assets; these tests do not qualify a real Field mission."""
import pytest
from rc7_runtime.rc72_canonical_design import CanonicalDesignService, CanonicalDesignError
from rc7_runtime.rc72_state_machine import RC72StateMachine
from rc7_runtime.rc72_domain import AutonomousMissionNode
from rc72_n2_test_support import BATCH, COMMIT, MISSION, RELEASE
from test_rc72_n5_data_inventory import _n5_ready


def _service(truth):
    return CanonicalDesignService(truth, release_id=RELEASE, source_commit=COMMIT)


def test_approved_n4_promotes_exact_obligations_and_preserves_case_source(tmp_path, monkeypatch):
    truth, scopes, completed = _n5_ready(tmp_path, monkeypatch)
    design = _service(truth).promote_obligations(release_batch_id=BATCH)
    assert len(design.obligations) == len(scopes)
    rows = truth.query('rc72_test_obligation', mission_id=MISSION)
    assert len(rows) == len(scopes)
    assert {case['obligation_id'] for case in design.cases} == {row['obligation_id'] for row in rows}
    assert all(case['source_case_sha256'].startswith('sha256:') for case in design.cases)
    assert all('n4-gate://' + completed['gate']['gate_id'] in row['change_refs'] for row in rows)
    assert truth.query('rc72_data_lease') == []


def test_promotion_resumes_without_duplicate_or_status_reset(tmp_path, monkeypatch):
    truth, _, _ = _n5_ready(tmp_path, monkeypatch)
    _service(truth).promote_obligations(release_batch_id=BATCH)
    before = list(truth.store.iter_raw())
    _service(truth).promote_obligations(release_batch_id=BATCH)
    assert list(truth.store.iter_raw()) == before


def test_stale_n4_cannot_promote_assets(tmp_path, monkeypatch):
    truth, _, _ = _n5_ready(tmp_path, monkeypatch)
    runtime = RC72StateMachine(truth, release_id=RELEASE)
    node = runtime.node_by_type(MISSION, AutonomousMissionNode.N4_TEST_DESIGN)
    runtime.mark_stale(node['mission_node_id'], reason='design revised')
    before = list(truth.store.iter_raw())
    with pytest.raises(ValueError, match='NOT_PASS'):
        _service(truth).promote_obligations(release_batch_id=BATCH)
    assert list(truth.store.iter_raw()) == before
    assert truth.query('rc72_test_obligation') == []


def test_multiple_applications_require_explicit_case_application(tmp_path, monkeypatch):
    truth, _, _ = _n5_ready(tmp_path, monkeypatch)
    batch = truth.query('rc72_release_batch', release_batch_id=BATCH)[0]
    batch.update(application_ids=['BLOAN', 'SECOND-APP'], artifact_version=batch['artifact_version'] + 1)
    truth.append_atomic('RC72_RELEASE_BATCH_UPSERTED', batch)
    before = list(truth.store.iter_raw())
    with pytest.raises(CanonicalDesignError, match='APPLICATION_AMBIGUOUS'):
        _service(truth).promote_obligations(release_batch_id=BATCH)
    assert list(truth.store.iter_raw()) == before


def test_source_mismatch_never_creates_canonical_obligations(tmp_path, monkeypatch):
    truth, _, _ = _n5_ready(tmp_path, monkeypatch)
    before = list(truth.store.iter_raw())
    with pytest.raises(CanonicalDesignError, match='SOURCE_MISMATCH'):
        CanonicalDesignService(truth, release_id=RELEASE, source_commit='2' * 40).promote_obligations(release_batch_id=BATCH)
    assert list(truth.store.iter_raw()) == before


def test_stale_upstream_blocks_even_when_n4_still_carries_historical_pass(tmp_path, monkeypatch):
    truth, _, _ = _n5_ready(tmp_path, monkeypatch)
    runtime = RC72StateMachine(truth, release_id=RELEASE)
    node = runtime.node_by_type(MISSION, AutonomousMissionNode.N3_CODE_ANALYSIS)
    runtime.mark_stale(node['mission_node_id'], reason='code baseline changed')
    before = list(truth.store.iter_raw())
    with pytest.raises(ValueError, match='NOT_PASS'):
        _service(truth).promote_obligations(release_batch_id=BATCH)
    assert list(truth.store.iter_raw()) == before
