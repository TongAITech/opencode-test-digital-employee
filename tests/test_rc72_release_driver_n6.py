"""All N1-N6 native product routes; children are engineering protocol adapters."""
from rc7_runtime.rc72_canonical_design import CanonicalDesignService
from test_rc72_release_driver_n5 import _n5_driver
from rc72_n2_test_support import BATCH, COMMIT, RELEASE


def test_driver_compiles_every_actual_approved_case_and_data_binding_before_n7(tmp_path):
    truth,driver,calls = _n5_driver(tmp_path,materialized=True)
    result = driver.run(release_batch_id=BATCH)
    assert result['status']=='HOLD' and result['reason']=='NATIVE_PRODUCT_ROUTE_NOT_IMPLEMENTED'
    states = {n['node_type']:n['state'] for n in result['nodes']}
    assert states['N6_EXECUTABLE_READINESS']=='PASS' and states['N7_EXECUTION']=='READY'
    design = CanonicalDesignService(truth,release_id=RELEASE,source_commit=COMMIT).load(release_batch_id=BATCH)
    contracts = truth.query('rc72_n6_executable_contract')
    obligation_ids={o.obligation_id for o in design.obligations}
    covered={link['subject_id'] for case in design.cases for link in case['coverage_links']}
    assert obligation_ids.issubset(covered)
    assert {c['obligation_id'] for c in design.cases} < obligation_ids
    assert {o['obligation_id'] for o in truth.query('rc72_test_obligation')}==obligation_ids
    assert {r['case_id'] for r in contracts}=={c['tc_id'] for c in design.cases}
    for case in design.cases:
        row = next(r for r in contracts if r['case_id']==case['tc_id'])
        assert row['steps']==case['steps'] and row['input']==case['execution']['inputs']
        assert row['oracles']==case['oracle']['checks']
        assert all(ref['source_case_sha256']==case['source_case_sha256'] for ref in row['data_refs'])
    assert not truth.query('rc72_data_lease') and not truth.query('execution_attempt')
    before = truth.store.path.read_bytes()
    count = len(calls)
    assert driver.run(release_batch_id=BATCH)==result
    assert truth.store.path.read_bytes()==before and len(calls)==count
