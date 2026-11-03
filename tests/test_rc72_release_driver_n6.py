"""ReleaseBatch product route reaches native N6 using canonical N1/N4/N5 truth.

External DSH/tool I/O remains an engineering fixture; this is not Field proof.
"""
from rc7_runtime.rc72_canonical_design import CanonicalDesignService
from rc72_integrated_test_support import install_execution_sources
from rc72_n2_test_support import BATCH, COMMIT, RELEASE
from test_rc72_release_driver_n5 import _n5_driver


def _executable_n5_driver(tmp_path, monkeypatch):
    # Reuse the existing real composition fixture that upgrades reviewed N4
    # Cases with explicit request/input/cleanup and machine Oracle material.
    install_execution_sources(tmp_path, monkeypatch)
    import test_rc72_n4_test_design_handoff as n4_fixture
    import test_rc72_release_driver_n4 as product_n4
    # release_driver_n4 imported the fixture symbol directly, so bind that
    # product helper to the upgraded candidate for this test only.
    monkeypatch.setattr(product_n4, '_candidate', n4_fixture._candidate)
    return _n5_driver(tmp_path)


def test_release_batch_driver_compiles_whole_case_denominator_into_n6_and_stops_at_n7(tmp_path, monkeypatch):
    truth, driver, calls = _executable_n5_driver(tmp_path, monkeypatch)

    result = driver.run(release_batch_id=BATCH)

    assert result['status'] == 'HOLD'
    assert result['reason'] == 'NATIVE_PRODUCT_ROUTE_NOT_IMPLEMENTED'
    states = {node['node_type']: node['state'] for node in result['nodes']}
    assert states['N5_TEST_DATA'] == 'PASS'
    assert states['N6_EXECUTABLE_READINESS'] == 'PASS'
    assert states['N7_EXECUTION'] == 'READY'

    design = CanonicalDesignService(
        truth, release_id=RELEASE, source_commit=COMMIT
    ).load(release_batch_id=BATCH)
    contracts = truth.query('rc72_n6_executable_contract', release_batch_id=BATCH)
    assert {row['case_id'] for row in contracts} == {case['tc_id'] for case in design.cases}
    assert len(contracts) == len(design.cases)
    assert all(row['data_refs'] for row in contracts)
    assert all(row['assertions'] for row in contracts)

    deliveries = truth.query(
        'rc72_node_delivery', node_type='N6_EXECUTABLE_READINESS'
    )
    gates = truth.query('rc72_node_gate', node_type='N6_EXECUTABLE_READINESS')
    assert len(deliveries) == len(gates) == 1
    assert deliveries[0]['artifact_refs'] == [row['contract_id'] for row in contracts]
    assert gates[0]['decision'] == 'PASS'
    assert not truth.query('execution_attempt')
    assert not truth.query('rc72_data_lease')

    before = truth.store.path.read_bytes()
    worker_count = len(calls)
    replay = driver.run(release_batch_id=BATCH)
    assert replay == result
    assert truth.store.path.read_bytes() == before
    assert len(calls) == worker_count


def test_legacy_reviewed_case_without_execution_materialization_holds_n6_without_guessing(tmp_path):
    truth, driver, calls = _n5_driver(tmp_path)

    result = driver.run(release_batch_id=BATCH)

    assert result['status'] == 'HOLD'
    assert result['reason'] == 'NATIVE_PRODUCT_ROUTE_NOT_IMPLEMENTED'
    assert result['construction_gap'] == 'N6_EXECUTION_MATERIALIZATION_REQUIRED'
    states = {node['node_type']: node['state'] for node in result['nodes']}
    assert states['N5_TEST_DATA'] == 'PASS'
    assert states['N6_EXECUTABLE_READINESS'] == 'READY'
    assert states['N7_EXECUTION'] == 'NOT_STARTED'
    assert not truth.query('rc72_n6_executable_contract')
    assert not truth.query('execution_attempt')
    assert not truth.query('rc72_data_lease')

    before = truth.store.path.read_bytes()
    worker_count = len(calls)
    replay = driver.run(release_batch_id=BATCH)
    assert replay == result
    assert truth.store.path.read_bytes() == before
    assert len(calls) == worker_count
