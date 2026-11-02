"""Construction fixtures only: no network/Field completion is claimed here."""
from copy import deepcopy
from datetime import timedelta

import pytest

from rc6_runtime.truth import TruthRuntime, EventValidationError
from rc7_runtime.candidate_payload import CandidatePayloadReader
from rc7_runtime.rc72_n6_executable_readiness import N6ExecutableReadinessCompiler, canonical_n5_data_ref
from rc7_runtime.rc72_n6_completion import N6DeliveryGateService, _digest
from rc7_runtime.rc72_n7_execution_admission import ExecutionAdmissionService, ExecutionAdmissionError
from rc7_runtime.rc72_state_machine import RC72StateMachine
from rc7_runtime.rc72_domain import AutonomousMissionNode
from rc72_n2_test_support import BATCH, COMMIT, MISSION, RELEASE
from test_rc72_n6_completion import _ready_truth
from test_rc72_n6_executable_readiness import NOW, _binding


def _ready(tmp_path, monkeypatch):
    truth = _ready_truth(tmp_path, monkeypatch)
    requirements = truth.query('rc72_n5_data_requirement', release_batch_id=BATCH)
    grouped = {}
    for row in requirements:
        grouped.setdefault(row['case_id'], []).append(row)
    compiled = []
    for case_id, rows in grouped.items():
        requirement = rows[0]
        durable = CandidatePayloadReader().load(truth, requirement['source_n4_artifact_id'], expected_mission_id=MISSION)
        source = next(case for case in durable.semantic_payload['cases'] if case['tc_id'] == case_id)
        case = deepcopy(source)
        case.update(case_id=case_id, mission_id=MISSION, status='PASS',
                    case_ref='r1://artifact/' + requirement['source_n4_artifact_id'] + '#case/' + case_id,
                    inputs={'fixture_input': 'explicit fixture runtime binding'},
                    expected=source['expected_results'], oracles=source['oracle']['checks'],
                    authoritative_sources=[requirement['source_n4_artifact_id']])
        refs = []
        for row in rows:
            binding = truth.query('rc72_n5_data_binding', data_requirement_id=row['data_requirement_id'])[0]
            refs.append(canonical_n5_data_ref(binding, row))
        compiled.append(N6ExecutableReadinessCompiler().compile(case, refs, _binding(), now=NOW))
    n6 = N6DeliveryGateService(truth, release_id=RELEASE, source_commit=COMMIT, now=NOW)
    result = n6.complete(release_batch_id=BATCH, contracts=compiled)
    assert result['gate']['decision'] == 'PASS'
    return truth, result['delivery']['contract_ids']


def _service(truth, *, now=NOW):
    return ExecutionAdmissionService(truth, release_id=RELEASE, source_commit=COMMIT, now=now)


def _events(truth):
    return list(truth.store.iter_raw())


def test_admission_binds_current_truth_without_execution_or_lease_side_effects(tmp_path, monkeypatch):
    truth, ids = _ready(tmp_path, monkeypatch)
    before = _events(truth)
    receipt = _service(truth).admit(release_batch_id=BATCH, contract_id=ids[0])
    assert receipt['status'] == 'ADMITTED'
    assert len(receipt['upstream_refs']) == 6
    assert receipt['contract_id'] == ids[0]
    assert len(_events(truth)) == len(before) + 1
    assert _events(truth)[-1]['entity_type'] == 'rc72_n7_execution_admission'
    assert not {'execution_result', 'actual_result', 'data_lease_id', 'n7_pass', 'field_verified', 'bank_final'} & set(receipt)
    assert truth.query('rc72_data_lease') == []
    n7 = truth.query('rc72_mission_node', mission_id=MISSION, node_type='N7_EXECUTION')[0]
    assert n7['state'] == 'READY'


def test_admission_replays_without_duplicate_and_rechecks_before_reuse(tmp_path, monkeypatch):
    truth, ids = _ready(tmp_path, monkeypatch)
    first = _service(truth).admit(release_batch_id=BATCH, contract_id=ids[0])
    count = len(_events(truth))
    replay = TruthRuntime(truth.store.path)
    assert _service(replay).admit(release_batch_id=BATCH, contract_id=ids[0]) == first
    assert _service(replay).assert_current(first['admission_id']) == first
    assert len(_events(replay)) == count
    node = RC72StateMachine(replay, release_id=RELEASE).node_by_type(MISSION, AutonomousMissionNode.N4_TEST_DESIGN)
    RC72StateMachine(replay, release_id=RELEASE).mark_stale(node['mission_node_id'], reason='new design')
    count = len(_events(replay))
    with pytest.raises(ExecutionAdmissionError, match='UPSTREAM_NOT_PASS'):
        _service(replay).assert_current(first['admission_id'])
    assert len(_events(replay)) == count


@pytest.mark.parametrize('change,code', [
    ('source', 'LINEAGE_MISMATCH'), ('digest', 'DIGEST_INVALID'),
    ('data', 'DATA_REF_STALE'), ('expiry', 'EXPIRED'), ('case', 'DENOMINATOR_MISMATCH'),
])
def test_changed_contract_is_rejected_before_any_admission_write(tmp_path, monkeypatch, change, code):
    truth, ids = _ready(tmp_path, monkeypatch)
    row = truth.query('rc72_n6_executable_contract', contract_id=ids[0])[0]
    if change == 'source':
        row['source_commit'] = '2' * 40
    elif change == 'digest':
        row['steps'] = ['changed after independent gate']
    elif change == 'data':
        row['data_refs'][0]['data_ref'] = 'data://unverified/replacement'
        row['contract_sha256'] = _digest(row)
    elif change == 'expiry':
        row['data_refs'][0]['expires_at'] = (NOW - timedelta(seconds=1)).isoformat()
        row['contract_sha256'] = _digest(row)
    elif change == 'case':
        row['case_id'] = 'orphan-case'
        row['contract_sha256'] = _digest(row)
    row['artifact_version'] += 1
    truth.append_atomic('rc72.n6.executable_contract_compiled', row)
    before = len(_events(truth))
    with pytest.raises(ExecutionAdmissionError, match=code):
        _service(truth).admit(release_batch_id=BATCH, contract_id=ids[0])
    assert len(_events(truth)) == before
    assert truth.query('rc72_n7_execution_admission') == []
    assert truth.query('rc72_data_lease') == []


def test_revoked_resource_invalidates_previously_admitted_receipt(tmp_path, monkeypatch):
    truth, ids = _ready(tmp_path, monkeypatch)
    receipt = _service(truth).admit(release_batch_id=BATCH, contract_id=ids[0])
    contract = truth.query('rc72_n6_executable_contract', contract_id=ids[0])[0]
    resource = truth.query('rc72_data_resource', data_ref=contract['data_refs'][0]['data_ref'])[0]
    resource.update(verified=False, artifact_version=resource['artifact_version'] + 1)
    truth.append_atomic('RC72_DATA_RESOURCE_UPSERTED', resource)
    before = len(_events(truth))
    with pytest.raises(ValueError, match='NOT_VERIFIED'):
        _service(truth).assert_current(receipt['admission_id'])
    assert len(_events(truth)) == before


def test_admission_truth_cannot_contain_a_fake_execution_result(tmp_path, monkeypatch):
    truth, ids = _ready(tmp_path, monkeypatch)
    receipt = _service(truth).admit(release_batch_id=BATCH, contract_id=ids[0])
    receipt['actual_result'] = 'PASS'
    before = len(_events(truth))
    with pytest.raises(EventValidationError, match='PREMATURE_CLAIM'):
        truth.append_atomic('RC72_N7_EXECUTION_ADMISSION_UPSERTED', receipt)
    assert len(_events(truth)) == before


def test_rehashing_changed_steps_cannot_reuse_the_previously_approved_identity(tmp_path, monkeypatch):
    truth, ids = _ready(tmp_path, monkeypatch)
    row = truth.query('rc72_n6_executable_contract', contract_id=ids[0])[0]
    row['steps'] = ['different actions not approved by N6']
    row['contract_sha256'] = _digest(row)
    row['artifact_version'] += 1
    truth.append_atomic('rc72.n6.executable_contract_compiled', row)
    count = len(_events(truth))
    with pytest.raises(ExecutionAdmissionError, match='IDENTITY_CHANGED'):
        _service(truth).admit(release_batch_id=BATCH, contract_id=ids[0])
    assert len(_events(truth)) == count


def test_incomplete_n6_case_denominator_cannot_release_one_case_early(tmp_path, monkeypatch):
    truth, ids = _ready(tmp_path, monkeypatch)
    node = truth.query('rc72_mission_node', mission_id=MISSION, node_type='N6_EXECUTABLE_READINESS')[0]
    delivery = next(row for row in truth.query('rc72_node_delivery', mission_node_id=node['mission_node_id'])
                    if row['version'] == node['active_delivery_version'])
    assert len(ids) > 1
    delivery['artifact_refs'] = [ids[0]]
    delivery['artifact_version'] += 1
    truth.append_atomic('RC72_NODE_DELIVERY_UPSERTED', delivery)
    count = len(_events(truth))
    with pytest.raises(ExecutionAdmissionError, match='DENOMINATOR_MISMATCH'):
        _service(truth).admit(release_batch_id=BATCH, contract_id=ids[0])
    assert len(_events(truth)) == count
