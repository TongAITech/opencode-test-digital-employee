"""Actual service composition with injected external I/O, not Field acceptance."""
from pathlib import Path

import pytest
from rc7_runtime.rc72_canonical_executable import CanonicalExecutableService, CanonicalExecutableError
from rc7_runtime.rc72_canonical_design import CanonicalDesignService
from rc7_runtime.rc72_n7_execution_admission import ExecutionAdmissionService
from rc72_integrated_test_support import install_execution_sources
from rc72_n2_test_support import BATCH, COMMIT, MISSION, RELEASE
from test_rc72_n6_completion import _ready_truth
from test_rc72_n6_executable_readiness import NOW


def _service(truth):
    return CanonicalExecutableService(truth, release_id=RELEASE, source_commit=COMMIT, now=NOW)


def test_n1_through_n6_uses_actual_approval_hashes_and_approved_cases(tmp_path, monkeypatch):
    install_execution_sources(tmp_path, monkeypatch)
    truth = _ready_truth(tmp_path, monkeypatch)
    result = _service(truth).compile_batch(release_batch_id=BATCH)
    assert result['gate']['decision'] == 'PASS'
    assert len(truth.query('rc72_n1_dsh_evidence_anchor')) == 1
    design = CanonicalDesignService(truth, release_id=RELEASE, source_commit=COMMIT).load(release_batch_id=BATCH)
    rows = truth.query('rc72_n6_executable_contract', release_batch_id=BATCH)
    assert {row['case_id'] for row in rows} == {case['tc_id'] for case in design.cases}
    assert {row['obligation_id'] for row in rows} == {row['obligation_id'] for row in truth.query('rc72_test_obligation')}
    for case in design.cases:
        contract = next(row for row in rows if row['case_id'] == case['tc_id'])
        assert contract['steps'] == case['steps']
        assert contract['preconditions'] == case['preconditions']
        assert contract['input'] == case['execution']['inputs']
        assert contract['oracles'] == case['oracle']['checks']
        assert contract['assertions'] == case['oracle']['checks']
        assert all(ref['source_case_sha256'] == case['source_case_sha256'] for ref in contract['data_refs'])
        assert ExecutionAdmissionService(truth, release_id=RELEASE, source_commit=COMMIT, now=NOW).admit(
            release_batch_id=BATCH, contract_id=contract['contract_id'])['status'] == 'ADMITTED'
    assert truth.query('rc72_data_lease') == []
    assert not truth.query('execution_attempt')


def test_legacy_n4_without_materialization_blocks_instead_of_guessing_an_input(tmp_path, monkeypatch):
    truth = _ready_truth(tmp_path, monkeypatch)
    before = list(truth.store.iter_raw())
    with pytest.raises(CanonicalExecutableError, match='EXECUTION_SPEC_MISSING'):
        _service(truth).compile_batch(release_batch_id=BATCH)
    assert list(truth.store.iter_raw()) == before
    assert truth.query('rc72_n6_executable_contract') == []
    assert truth.query('rc72_data_lease') == []


def test_source_bytes_changed_after_approval_blocks_compilation_without_writes(tmp_path, monkeypatch):
    install_execution_sources(tmp_path, monkeypatch)
    truth = _ready_truth(tmp_path, monkeypatch)
    row = truth.query('rc7_artifact', artifact_type_name='TEST_DESIGN_CANDIDATE')[0]
    path = Path(row['content_ref'][len('file://'):])
    path.write_bytes(path.read_bytes() + b'\n')
    before = list(truth.store.iter_raw())
    with pytest.raises(RuntimeError, match='HASH_MISMATCH'):
        _service(truth).compile_batch(release_batch_id=BATCH)
    assert list(truth.store.iter_raw()) == before


def test_repeat_compilation_recovers_without_duplicate_contracts_or_obligations(tmp_path, monkeypatch):
    install_execution_sources(tmp_path, monkeypatch)
    truth = _ready_truth(tmp_path, monkeypatch)
    _service(truth).compile_batch(release_batch_id=BATCH)
    before = list(truth.store.iter_raw())
    _service(truth).compile_batch(release_batch_id=BATCH)
    assert list(truth.store.iter_raw()) == before


def test_read_only_n1_recheck_rejects_a_modified_persisted_binding(tmp_path, monkeypatch):
    install_execution_sources(tmp_path, monkeypatch)
    truth = _ready_truth(tmp_path, monkeypatch)
    result = _service(truth).compile_batch(release_batch_id=BATCH)
    service = ExecutionAdmissionService(truth, release_id=RELEASE, source_commit=COMMIT, now=NOW)
    admission = service.admit(release_batch_id=BATCH, contract_id=result['delivery']['contract_ids'][0])
    binding = truth.query('rc72_n1_executable_binding')[0]
    binding['endpoint']['url'] = 'http://changed.invalid/'
    binding['artifact_version'] += 1
    truth.append_atomic('RC72_N1_EXECUTABLE_BINDING_UPSERTED', binding)
    before = list(truth.store.iter_raw())
    with pytest.raises(ValueError, match='EXISTING_CONFLICT'):
        service.assert_current(admission['admission_id'])
    assert list(truth.store.iter_raw()) == before


def test_descriptive_oracle_cannot_be_treated_as_a_machine_assertion(tmp_path, monkeypatch):
    from rc7_runtime.rc72_canonical_executable import approved_case_payload
    install_execution_sources(tmp_path, monkeypatch)
    truth = _ready_truth(tmp_path, monkeypatch)
    design = CanonicalDesignService(truth, release_id=RELEASE, source_commit=COMMIT).load(release_batch_id=BATCH)
    case = design.cases[0]
    case['oracle']['checks'] = [{'type': 'API_RESPONSE', 'evidence_ref': 'tool://fixture'}]
    with pytest.raises(CanonicalExecutableError, match='ORACLE_UNRESOLVED'):
        approved_case_payload(case, mission_id=MISSION)
